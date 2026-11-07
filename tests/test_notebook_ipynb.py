# -*- coding: utf-8 -*-
"""Notebook .ipynb 导入/导出（v6.9 阶段 4）往返一致性。

分两层：
1. 纯映射层：notebook_to_ipynb / ipynb_to_cells 双向自洽（导出→导入 cell 数/内容/输出结构等价），
   覆盖 markdown/LaTeX、stream、execute_result(HTML/DataFrame)、display_data(matplotlib base64 图)、error 回溯。
2. HTTP 层：真实 app 走 POST /api/notebooks/import → GET /api/notebooks/<id>/export 往返，
   校验端点连通、归属权限、nbformat v4 形状。
"""
import io
import json

import pytest

from utils.ipynb import notebook_to_ipynb, ipynb_to_cells

# 62 字节 PNG（1×1 透明），matplotlib base64 图占位用
_PNG_B64 = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4'
            '2mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


def _nb():
    """构造一个含各类输出的内部 notebook dict（Notebook.to_dict(with_cells=True) 形状）。"""
    return {
        'title': '往返测试', 'language': 'python',
        'cells': [
            {'order_num': 1, 'cell_type': 'markdown',
             'source': '# 标题\n\n行内公式 $E=mc^2$\n\n$$\\int_0^1 x\\,dx$$', 'outputs': [], 'exec_count': 0},
            {'order_num': 2, 'cell_type': 'code', 'source': 'print("hi")\nx = 1\nx',
             'exec_count': 3,
             'outputs': [
                 {'output_type': 'stream', 'name': 'stdout', 'text': 'hi\n'},
                 {'output_type': 'text', 'text': '1'},
             ]},
            {'order_num': 3, 'cell_type': 'code', 'source': 'df', 'exec_count': 1,
             'outputs': [{'output_type': 'html',
                          'html': '<table><tr><td>a</td></tr></table>'}]},
            {'order_num': 4, 'cell_type': 'code', 'source': 'plt.plot([1,2])', 'exec_count': 1,
             'outputs': [{'output_type': 'image', 'mime': 'image/png', 'data': _PNG_B64}]},
            {'order_num': 5, 'cell_type': 'code', 'source': 'raise ValueError("boom")', 'exec_count': 1,
             'outputs': [{'output_type': 'error', 'ename': 'ValueError', 'evalue': 'boom',
                          'traceback': ['Traceback...', 'ValueError: boom']}]},
        ],
    }


def _norm_outputs(outputs):
    """把内部/导入输出的顺序无关结构规整，便于等价比较（各类型只比关键字段）。"""
    norm = []
    for o in outputs or []:
        t = o.get('output_type')
        if t == 'stream':
            norm.append(('stream', o.get('name'), o.get('text')))
        elif t == 'error':
            norm.append(('error', o.get('traceback')))
        elif t == 'image':
            norm.append(('image', o.get('data')))
        elif t == 'html':
            norm.append(('html', o.get('html')))
        elif t == 'text':
            norm.append(('text', o.get('text')))
    return norm


# ───────────────────────── 纯映射层 ─────────────────────────
def test_export_is_valid_nbformat_v4():
    ipynb = notebook_to_ipynb(_nb())
    assert ipynb['nbformat'] == 4 and ipynb['nbformat_minor'] == 5
    assert isinstance(ipynb['cells'], list) and len(ipynb['cells']) == 5
    # markdown cell 无 outputs，code cell 有 outputs/execution_count
    md = ipynb['cells'][0]
    assert md['cell_type'] == 'markdown' and 'outputs' not in md
    code = ipynb['cells'][1]
    assert code['cell_type'] == 'code' and code['execution_count'] == 3
    # source 采用官方「按行数组保留换行」形式，且 join 回去无损
    assert ''.join(md['source']) == _nb()['cells'][0]['source']
    # 富输出 mime 正确落位
    assert ipynb['cells'][2]['outputs'][0]['data']['text/html']
    assert ipynb['cells'][3]['outputs'][0]['data']['image/png'] == _PNG_B64
    assert ipynb['cells'][4]['outputs'][0]['traceback'][-1] == 'ValueError: boom'


def test_roundtrip_export_import_equivalent():
    """导出 → 导入：cell 数 / 源码 / 输出结构等价（阶段 4 验收口径）。"""
    src = _nb()
    ipynb = notebook_to_ipynb(src)
    language, cells = ipynb_to_cells(ipynb)

    assert language == 'python'
    assert len(cells) == len(src['cells'])
    for a, b in zip(src['cells'], cells):
        assert a['cell_type'] == b['cell_type']
        assert a['source'] == b['source']
    # 输出结构等价（类型集合 + 关键字段）
    assert _norm_outputs(cells[1]['outputs']) == _norm_outputs(src['cells'][1]['outputs'])
    assert _norm_outputs(cells[2]['outputs']) == _norm_outputs(src['cells'][2]['outputs'])
    assert _norm_outputs(cells[3]['outputs']) == _norm_outputs(src['cells'][3]['outputs'])
    assert _norm_outputs(cells[4]['outputs']) == _norm_outputs(src['cells'][4]['outputs'])


def test_import_accepts_string_and_list_source():
    """nbformat 允许 source 为 str 或行数组，两形都能吃进且无损。"""
    nb = notebook_to_ipynb(_nb())
    nb['cells'][0]['source'] = '单行 markdown'      # 改成 str 形
    _, cells = ipynb_to_cells(nb)
    assert cells[0]['source'] == '单行 markdown'


def test_import_rejects_oversize_and_bad_shape():
    with pytest.raises(ValueError):
        ipynb_to_cells({'no_cells': True})
    with pytest.raises(ValueError):
        ipynb_to_cells({'cells': [{'cell_type': 'code', 'source': 'x' * 10}]}, max_source=5)
    with pytest.raises(ValueError):
        ipynb_to_cells({'cells': [{'cell_type': 'code', 'source': ''} for _ in range(3)]}, max_cells=2)


# ───────────────────────── HTTP 层 ─────────────────────────
@pytest.fixture(scope='module')
def client():
    """真实 app 单例（复用 e2e 装配口径：跳 bootstrap、关限流、建全表）+ 注册一个用户取 token。"""
    import os
    import app as prod
    from database import db

    prod._boot_done.set()
    prod.app.config['TESTING'] = True
    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False

    with prod.app.app_context():
        import database.models        # noqa: F401
        import competition.models     # noqa: F401
        import bounty.models          # noqa: F401
        import ledger.models          # noqa: F401
        import dsci.models            # noqa: F401
        import homework.models        # noqa: F401
        db.create_all()

    c = prod.app.test_client()
    r = c.post('/api/register', json={'username': 'ipynb_user', 'password': 'pw-123456', 'role': 'student'})
    assert r.status_code == 200, r.get_json()
    tok = r.get_json()['token']
    yield c, {'Authorization': f'Bearer {tok}'}


def _auth(h):
    return h


def test_http_export_import_roundtrip(client):
    c, hdr = client
    ipynb = notebook_to_ipynb(_nb())

    # 上传 .ipynb（multipart 文件字段）
    data = {'file': (io.BytesIO(json.dumps(ipynb, ensure_ascii=False).encode('utf-8')), '往返测试.ipynb')}
    r = c.post('/api/notebooks/import', data=data, content_type='multipart/form-data', headers=hdr)
    assert r.status_code == 201, r.get_json()
    created = r.get_json()
    assert created['title'] == '往返测试'
    assert len(created['cells']) == 5
    # 富输出随导入落库（png/html/error 原样回显）
    outs3 = created['cells'][3]['outputs']
    assert any(o.get('output_type') == 'image' and o.get('data') == _PNG_B64 for o in outs3)

    nid = created['id']
    # 导出 .ipynb 下载
    r = c.get(f'/api/notebooks/{nid}/export', headers=hdr)
    assert r.status_code == 200
    assert 'attachment' in r.headers['Content-Disposition']
    assert r.mimetype == 'application/x-ipynb+json'
    exported = json.loads(r.data.decode('utf-8'))
    assert exported['nbformat'] == 4 and len(exported['cells']) == 5

    # 再导入导出结果 → cell 数/源码等价（端到端往返闭合）
    data2 = {'file': (io.BytesIO(json.dumps(exported).encode('utf-8')), 'again.ipynb')}
    r2 = c.post('/api/notebooks/import', data=data2, content_type='multipart/form-data', headers=hdr)
    assert r2.status_code == 201, r2.get_json()
    again = r2.get_json()
    assert len(again['cells']) == len(created['cells'])
    assert [cc['source'] for cc in again['cells']] == [cc['source'] for cc in created['cells']]


def test_http_import_requires_login(client):
    """匿名写请求先被 CSRF 前置门拦下（400，与全系统写链一致，钉死现状）。"""
    c, _ = client
    r = c.post('/api/notebooks/import', data={'file': (io.BytesIO(b'{"cells":[]}'), 'x.ipynb')},
               content_type='multipart/form-data')
    assert r.status_code == 400


def test_http_export_permission_denied_for_other(client):
    """他人私有本不可导出（权限同 detail）。"""
    c, hdr = client
    r = c.post('/api/notebooks', json={'title': '私有本'}, headers=hdr)
    assert r.status_code == 201
    nid = r.get_json()['id']
    r2 = c.post('/api/register', json={'username': 'ipynb_other', 'password': 'pw-123456', 'role': 'student'})
    other = {'Authorization': f"Bearer {r2.get_json()['token']}"}
    assert c.get(f'/api/notebooks/{nid}/export', headers=other).status_code == 403
