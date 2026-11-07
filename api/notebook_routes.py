# -*- coding: utf-8 -*-
"""代码笔记本 API（v6.6）

蓝图前缀：/api/notebooks
功能：notebook / cell 的 CRUD 与排序、cell 经持久 kernel 执行（跨 cell 保留状态）、
     富输出（stdout/stderr/异常回溯 + matplotlib 图 + DataFrame HTML）落库回显。

全民可用（不分教师/学生），仅校验登录；notebook 归属本人，public 仅放宽只读可见。
执行后端由 utils.kernel 可插拔解析（docker 优先、无则降级 subprocess 防呆级）。
"""
from flask import Blueprint, request, jsonify, Response
import json
import re

from database import db
from database.models import (Notebook, NotebookCell, CELL_TYPE_LABELS,
                             NOTEBOOK_VISIBILITY_LABELS, NOTEBOOK_CTX_LABELS)
from utils.security import limiter, verify_token
from utils.timeutil import utcnow
from utils.logger import logger
from utils.kernel import kernel_manager, run_cell, resolve_backend, interrupt_cell
from utils.ipynb import notebook_to_ipynb, ipynb_to_cells
from config import Config

api_notebook_bp = Blueprint('api_notebook', __name__)


def _cur_user():
    return verify_token()


def _get_own_notebook(nid):
    user = _cur_user()
    if not user:
        return None, None, (jsonify({'message': '请先登录'}), 401)
    nb = Notebook.query.get(nid)
    if not nb:
        return None, None, (jsonify({'message': '笔记本不存在'}), 404)
    if nb.user_id != user.id:
        return None, None, (jsonify({'message': '无权操作他人的笔记本'}), 403)
    return user, nb, None


# ── 后端信息（供前端提示隔离级别）────────────────────────────────
@api_notebook_bp.route('/notebooks/meta', methods=['GET'])
def api_notebook_meta():
    user = _cur_user()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    return jsonify({
        'backend': resolve_backend(),
        'timeout': Config.NOTEBOOK_KERNEL_TIMEOUT,
        'max_cells': Config.NOTEBOOK_MAX_CELLS,
        'max_source': Config.NOTEBOOK_MAX_SOURCE,
        'cell_type_labels': CELL_TYPE_LABELS,
        'visibility_labels': NOTEBOOK_VISIBILITY_LABELS,
        'ctx_labels': NOTEBOOK_CTX_LABELS,
    })


# ── notebook CRUD ────────────────────────────────────────────────
@api_notebook_bp.route('/notebooks', methods=['GET'])
def api_notebook_list():
    user = _cur_user()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    scope = request.args.get('scope', 'mine')
    q = Notebook.query
    # v6.7 六模块接入：「我的」列表默认只展示自由笔记本（ctx 为空），上下文本走 /notebooks/ctx；
    # 公开榜不隐藏上下文本（便于社区发现/ fork）；传 all=1 可含全部
    if scope == 'mine' and request.args.get('all') != '1':
        q = q.filter(Notebook.ctx_type.is_(None))
    ctx_type = request.args.get('ctx_type')
    if ctx_type in NOTEBOOK_CTX_LABELS:
        q = q.filter(Notebook.ctx_type == ctx_type)
        if request.args.get('ctx_id'):
            q = q.filter(Notebook.ctx_id == int(request.args['ctx_id']))
    if scope == 'mine':
        q = q.filter_by(user_id=user.id)
    else:  # public：本人 + 他人公开
        from sqlalchemy import or_
        q = q.filter(or_(Notebook.user_id == user.id, Notebook.visibility == 'public'))
    nbs = q.order_by(Notebook.updated_at.desc()).all()
    return jsonify({'items': [n.to_dict() for n in nbs], 'total': len(nbs)})


@api_notebook_bp.route('/notebooks', methods=['POST'])
@limiter.limit('30 per minute')
def api_notebook_create():
    user = _cur_user()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '请填写笔记本标题'}), 400
    nb = Notebook(user_id=user.id, title=title[:120],
                  description=(data.get('description') or '').strip() or None,
                  major_id=data.get('major_id'), course_id=data.get('course_id'),
                  ctx_type=data.get('ctx_type') if data.get('ctx_type') in NOTEBOOK_CTX_LABELS else None,
                  ctx_id=int(data['ctx_id']) if data.get('ctx_id') else None,
                  visibility=data.get('visibility') if data.get('visibility') in NOTEBOOK_VISIBILITY_LABELS else 'private')
    db.session.add(nb)
    db.session.flush()
    # 默认给一个空 code cell，打开即可写
    db.session.add(NotebookCell(notebook_id=nb.id, order_num=1, cell_type='code', source=''))
    db.session.commit()
    return jsonify(nb.to_dict(with_cells=True)), 201


@api_notebook_bp.route('/notebooks/<int:nid>', methods=['GET'])
def api_notebook_detail(nid):
    user = _cur_user()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    nb = Notebook.query.get(nid)
    if not nb:
        return jsonify({'message': '笔记本不存在'}), 404
    if nb.user_id != user.id and nb.visibility != 'public':
        return jsonify({'message': '无权查看该笔记本'}), 403
    return jsonify(nb.to_dict(with_cells=True))


@api_notebook_bp.route('/notebooks/<int:nid>', methods=['PUT'])
def api_notebook_update(nid):
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if data.get('title'):
        nb.title = data['title'][:120]
    if 'description' in data:
        nb.description = (data.get('description') or '').strip() or None
    if data.get('visibility') in NOTEBOOK_VISIBILITY_LABELS:
        nb.visibility = data['visibility']
    if data.get('status') in ('active', 'archived'):
        nb.status = data['status']
    db.session.commit()
    return jsonify(nb.to_dict())


@api_notebook_bp.route('/notebooks/<int:nid>', methods=['DELETE'])
def api_notebook_delete(nid):
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    kernel_manager.drop((nb.user_id, nb.id))
    db.session.delete(nb)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ── v6.9 阶段 4：.ipynb 导入 / 导出（与 Jupyter 文件互通）───────────
def _safe_filename(title):
    """由标题生成安全文件名（去 Windows/类 Unix 非法字符，回退 notebook）。"""
    name = re.sub(r'[\\/:*?"<>|\r\n]+', '_', (title or '').strip()) or 'notebook'
    return name[:80]


@api_notebook_bp.route('/notebooks/import', methods=['POST'])
@limiter.limit('20 per minute')
def api_notebook_import():
    """上传 .ipynb → 为本用户建 notebook + 有序 cells（输出快照一并导入，不重跑 kernel）。

    接受 multipart 文件字段 file，或 JSON 体 {nb: {...}} / 原始 ipynb JSON。"""
    user = _cur_user()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    nb_json = None
    title = None
    f = request.files.get('file')
    if f is not None and f.filename:
        title = re.sub(r'\.ipynb$', '', f.filename, flags=re.I)
        try:
            nb_json = json.loads(f.read().decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return jsonify({'message': '.ipynb 解析失败：非合法 UTF-8 JSON'}), 400
    else:
        data = request.get_json(silent=True)
        if isinstance(data, dict) and 'cells' in data:
            nb_json = data
        elif isinstance(data, dict) and isinstance(data.get('nb'), dict):
            nb_json = data['nb']
            title = data.get('title')
    if nb_json is None:
        return jsonify({'message': '请上传 .ipynb 文件'}), 400

    try:
        language, cells = ipynb_to_cells(nb_json, max_cells=Config.NOTEBOOK_MAX_CELLS,
                                         max_source=Config.NOTEBOOK_MAX_SOURCE)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    if not cells:
        return jsonify({'message': '.ipynb 无有效单元'}), 400

    # 本系统 notebook 当前仅支持 python 内核，非 python 仍按 python 建本（源码原样保留）
    nb = Notebook(user_id=user.id, title=(title or '导入的笔记本')[:120],
                  language='python', visibility='private')
    db.session.add(nb)
    db.session.flush()
    for i, c in enumerate(cells, start=1):
        db.session.add(NotebookCell(notebook_id=nb.id, order_num=i, cell_type=c['cell_type'],
                                    source=c['source'], language='python', outputs=c['outputs']))
    db.session.commit()
    return jsonify(nb.to_dict(with_cells=True)), 201


@api_notebook_bp.route('/notebooks/<int:nid>/export', methods=['GET'])
def api_notebook_export(nid):
    """导出 notebook 为 .ipynb 下载（权限同 detail：本人或公开本）。"""
    user = _cur_user()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    nb = Notebook.query.get(nid)
    if not nb:
        return jsonify({'message': '笔记本不存在'}), 404
    if nb.user_id != user.id and nb.visibility != 'public':
        return jsonify({'message': '无权查看该笔记本'}), 403
    ipynb = notebook_to_ipynb(nb.to_dict(with_cells=True), language=nb.language)
    body = json.dumps(ipynb, ensure_ascii=False, indent=1)
    fname = _safe_filename(nb.title) + '.ipynb'
    from urllib.parse import quote
    resp = Response(body, mimetype='application/x-ipynb+json')
    resp.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(fname)}"
    return resp


# ── v6.7 六模块接入：上下文笔记本 get-or-create ───────────────────
@api_notebook_bp.route('/notebooks/ctx', methods=['GET'])
def api_notebook_ctx_get():
    """按 (用户, ctx_type, ctx_id) 定位笔记本；不存在则创建（同名上下文复用，不重复建本）。"""
    user = _cur_user()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    ctx_type = request.args.get('ctx_type')
    ctx_id = request.args.get('ctx_id')
    if ctx_type not in NOTEBOOK_CTX_LABELS or not ctx_id:
        return jsonify({'message': '上下文类型/编号无效'}), 400
    ctx_id = int(ctx_id)
    nb = Notebook.query.filter_by(user_id=user.id, ctx_type=ctx_type, ctx_id=ctx_id).first()
    created = False
    if not nb:
        title = (request.args.get('title') or f'{NOTEBOOK_CTX_LABELS[ctx_type]}笔记本 #{ctx_id}')[:120]
        nb = Notebook(user_id=user.id, title=title, ctx_type=ctx_type, ctx_id=ctx_id,
                      description=request.args.get('description') or None)
        db.session.add(nb)
        db.session.flush()
        db.session.add(NotebookCell(notebook_id=nb.id, order_num=1, cell_type='code', source=''))
        db.session.commit()
        created = True
    return jsonify({'notebook': nb.to_dict(with_cells=True), 'created': created})


# ── v6.7 社区接入：公开本一键 fork（只拷源码，输出不带走）──────
@api_notebook_bp.route('/notebooks/<int:nid>/fork', methods=['POST'])
@limiter.limit('10 per minute')
def api_notebook_fork(nid):
    user = _cur_user()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    src = Notebook.query.get(nid)
    if not src:
        return jsonify({'message': '笔记本不存在'}), 404
    if src.user_id != user.id and src.visibility != 'public':
        return jsonify({'message': '仅公开笔记本可 fork'}), 403
    nb = Notebook(user_id=user.id, title=f'副本 - {src.title}'[:120],
                  description=src.description, forked_from_id=src.id, visibility='private')
    db.session.add(nb)
    db.session.flush()
    for c in src.cells.order_by(NotebookCell.order_num).all():
        db.session.add(NotebookCell(notebook_id=nb.id, order_num=c.order_num, cell_type=c.cell_type,
                                    source=c.source, language=c.language))
    db.session.commit()
    return jsonify(nb.to_dict(with_cells=True)), 201


# ── cell CRUD / 排序 ─────────────────────────────────────────────
@api_notebook_bp.route('/notebooks/<int:nid>/cells', methods=['POST'])
@limiter.limit('60 per minute')
def api_cell_add(nid):
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if nb.cells.count() >= Config.NOTEBOOK_MAX_CELLS:
        return jsonify({'message': f'单元数超过上限 {Config.NOTEBOOK_MAX_CELLS}'}), 400
    cell_type = data.get('cell_type') if data.get('cell_type') in CELL_TYPE_LABELS else 'code'
    source = data.get('source') or ''
    if len(source) > Config.NOTEBOOK_MAX_SOURCE:
        return jsonify({'message': '代码长度超过上限'}), 400
    last = db.session.query(db.func.max(NotebookCell.order_num)).filter_by(notebook_id=nb.id).scalar() or 0
    cell = NotebookCell(notebook_id=nb.id, order_num=last + 1, cell_type=cell_type,
                        source=source, language=nb.language)
    db.session.add(cell)
    db.session.commit()
    return jsonify(cell.to_dict()), 201


@api_notebook_bp.route('/notebooks/<int:nid>/cells/<int:cid>', methods=['PUT'])
def api_cell_update(nid, cid):
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    cell = NotebookCell.query.filter_by(id=cid, notebook_id=nb.id).first()
    if not cell:
        return jsonify({'message': '单元不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'source' in data:
        src = data.get('source') or ''
        if len(src) > Config.NOTEBOOK_MAX_SOURCE:
            return jsonify({'message': '代码长度超过上限'}), 400
        cell.source = src
    if data.get('cell_type') in CELL_TYPE_LABELS:
        cell.cell_type = data['cell_type']
    db.session.commit()
    return jsonify(cell.to_dict())


@api_notebook_bp.route('/notebooks/<int:nid>/cells/<int:cid>', methods=['DELETE'])
def api_cell_delete(nid, cid):
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    cell = NotebookCell.query.filter_by(id=cid, notebook_id=nb.id).first()
    if not cell:
        return jsonify({'message': '单元不存在'}), 404
    db.session.delete(cell)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_notebook_bp.route('/notebooks/<int:nid>/cells/reorder', methods=['POST'])
def api_cell_reorder(nid):
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    order = data.get('order') or []
    cells = {c.id: c for c in nb.cells.all()}
    for idx, cid in enumerate(order, start=1):
        c = cells.get(int(cid))
        if c:
            c.order_num = idx
    db.session.commit()
    return jsonify({'cells': [c.to_dict() for c in nb.cells.order_by(NotebookCell.order_num).all()]})


# ── cell 执行（持久 kernel）──────────────────────────────────────
@api_notebook_bp.route('/notebooks/<int:nid>/cells/<int:cid>/run', methods=['POST'])
@limiter.limit('30 per minute')
def api_cell_run(nid, cid):
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    cell = NotebookCell.query.filter_by(id=cid, notebook_id=nb.id).first()
    if not cell:
        return jsonify({'message': '单元不存在'}), 404
    if cell.cell_type != 'code':
        return jsonify({'message': '仅代码单元可执行'}), 400

    try:
        res = run_cell(nb.user_id, nb.id, cell.source or '')
    except Exception:
        logger.exception('[notebook] kernel 执行异常')
        return jsonify({'message': 'kernel 执行异常，请稍后重试'}), 500

    outputs = []
    if res.get('stdout'):
        outputs.append({'output_type': 'stream', 'name': 'stdout', 'text': res['stdout']})
    if res.get('stderr'):
        outputs.append({'output_type': 'stream', 'name': 'stderr', 'text': res['stderr']})
    if res.get('error'):
        outputs.append({'output_type': 'error', 'traceback': res['error']})
    # v6.9 阶段 5：display() 多 mime bundle → 逐条 display_data（与 execute_result 同构）
    for bundle in (res.get('displays') or []):
        mime = ('image/png' if bundle.get('image/png')
                else 'text/html' if bundle.get('text/html') else 'text/plain')
        data = bundle.get(mime)
        if mime == 'image/png':
            outputs.append({'output_type': 'image', 'mime': 'image/png', 'data': data})
        elif mime == 'text/html':
            outputs.append({'output_type': 'html', 'html': data})
        else:
            outputs.append({'output_type': 'text', 'text': data})
    for img in (res.get('images') or []):
        outputs.append({'output_type': 'image', 'mime': 'image/png', 'data': img})
    if res.get('html'):
        outputs.append({'output_type': 'html', 'html': res['html']})
    elif res.get('text'):
        outputs.append({'output_type': 'text', 'text': res['text']})

    cell.outputs = outputs
    cell.exec_count = (cell.exec_count or 0) + 1
    cell.last_run_at = utcnow()
    db.session.commit()
    return jsonify({'cell': cell.to_dict(), 'backend': resolve_backend(),
                    'timed_out': bool(res.get('timed_out'))})


@api_notebook_bp.route('/notebooks/<int:nid>/kernel/reset', methods=['POST'])
def api_kernel_reset(nid):
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    kernel_manager.drop((nb.user_id, nb.id))
    return jsonify({'message': 'kernel 已重置，跨 cell 状态已清空'})


@api_notebook_bp.route('/notebooks/<int:nid>/kernel/interrupt', methods=['POST'])
def api_kernel_interrupt(nid):
    """v6.9 阶段 5：软中断当前正在执行的 cell（尽力）；无活跃执行返回 interrupted=False，
    卡 C 扩展打不断时由前端回退到超时强杀。"""
    _u, nb, err = _get_own_notebook(nid)
    if err:
        return err
    return jsonify({'interrupted': interrupt_cell(nb.user_id, nb.id)})
