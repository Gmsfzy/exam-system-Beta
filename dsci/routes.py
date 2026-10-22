# -*- coding: utf-8 -*-
"""数据科学竞赛 API（v4.11）：数据集管理 / 在线编写运行 / 提交评分 / 公私榜。

宿主复用 competition.Competition（建赛/发布/交叉审核/邀请码门禁/托管结算全部沿用），
本蓝图只负责 DS 专有的 config/dataset/notebook/submission/leaderboard 端点，
以 /ds 前缀挂载（app.py 统一 url_prefix='/api'）。结算冠军判定在 competition.routes
的 settle 里按 private_score 计算，资金发放仍走统一 ledger。
"""
import io
import os
import secrets

import pandas as pd
from flask import Blueprint, jsonify, request, send_from_directory

from database import db
from utils.permissions import require_teacher
from utils.security import verify_token
from utils.timeutil import utcnow, iso_local
from competition.models import (
    Competition, CompetitionStatusEnum, CompetitionTypeEnum, CompetitionParticipant,
)
from competition.routes import (_get_own_competition, _notify,
                                _visible_to_student)
from utils.uploads import UPLOAD_DIR as _UPLOAD_DIR, save_upload as _save_upload
from dsci.metrics import METRICS, higher_is_better, score_from_frames
from dsci.models import (Dataset, DatasetFile, DatasetRole, DsNotebookRun, DsSubmission)
from dsci.runner import run_custom_scorer, run_notebook

dsci_bp = Blueprint('dsci', __name__)

_MAX_CSV_BYTES = 5 * 1024 * 1024   # 预测/数据集读入内存上限


def _require_student():
    user = verify_token()
    if not user or not user.is_student():
        return None, (jsonify({'message': '仅学生可参与'}), 403)
    return user, None


def _get_comp(comp_id):
    comp = db.session.get(Competition, comp_id)
    if not comp or comp.competition_type != CompetitionTypeEnum.DS:
        return None, (jsonify({'message': '数据科学赛不存在'}), 404)
    return comp, None


def _get_or_create_dataset(comp, owner_id):
    ds = Dataset.query.filter_by(competition_id=comp.id).order_by(Dataset.id).first()
    if not ds:
        ds = Dataset(competition_id=comp.id, name=f'{comp.title} 数据集',
                     owner_id=owner_id)
        db.session.add(ds)
        db.session.flush()
    return ds


def _files_of(comp, roles=None):
    q = (DatasetFile.query.join(Dataset, DatasetFile.dataset_id == Dataset.id)
         .filter(Dataset.competition_id == comp.id))
    if roles:
        q = q.filter(DatasetFile.role.in_(roles))
    return q.all()


def _read_upload_text(stored_name):
    path = os.path.join(_UPLOAD_DIR, stored_name)
    try:
        if os.path.getsize(path) > _MAX_CSV_BYTES:
            return None, '文件超过 5MB 评分上限'
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(), None
    except OSError as exc:
        return None, f'文件读取失败：{exc}'


def _public_mask(n, ratio):
    """确定性公榜子集：每 10 行取前 ratio*10 行，避免 leaderboard 可被针对性刷分。"""
    keep = max(1, min(9, int(round((ratio if ratio is not None else 0.3) * 10))))
    return (pd.Series(range(n)).values % 10) < keep


def _parse_csv(text):
    try:
        return pd.read_csv(io.StringIO(text)), None
    except Exception as exc:
        return None, f'CSV 解析失败：{exc}'


def _score_prediction(comp, pred_df, pred_text):
    """按 comp 配置对预测评分，返回 (public_score, private_score, error)。

    预置指标走 metrics；custom 走沙箱 scorer。任一子集评分失败即整体 error。
    """
    gold_files = _files_of(comp, roles=[DatasetRole.GOLD])
    if not gold_files:
        return None, None, '尚未上传隐藏答案（gold）'
    gold_text, err = _read_upload_text(gold_files[0].stored_name)
    if err:
        return None, None, err
    gold_df, err = _parse_csv(gold_text)
    if err:
        return None, None, 'gold ' + err

    cfg = {'metric': comp.ds_metric, 'id_column': comp.ds_id_column,
           'target_column': comp.ds_target_column}

    if comp.ds_metric == 'custom':
        scorer = comp.ds_scorer_code or ''
        priv = run_custom_scorer(scorer, gold_text, pred_text)
        if not priv['ok']:
            return None, None, priv['error'] or '自定义评分失败'
        mask = _public_mask(len(gold_df), comp.ds_public_ratio)
        gold_pub_text = gold_df[mask].to_csv(index=False)
        pub = run_custom_scorer(scorer, gold_pub_text, pred_text)
        if not pub['ok']:
            return None, None, pub['error'] or '自定义评分失败'
        return pub['score'], priv['score'], None

    priv_res = score_from_frames(pred_df, gold_df, cfg)
    if priv_res['status'] != 'ok':
        return None, None, priv_res['error']
    mask = _public_mask(len(gold_df), comp.ds_public_ratio)
    pub_res = score_from_frames(pred_df, gold_df[mask], cfg)
    if pub_res['status'] != 'ok':
        return None, None, pub_res['error']
    return pub_res['score'], priv_res['score'], None


def _save_pred_csv(text):
    stored = f'dssub_{secrets.token_hex(12)}.csv'
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(_UPLOAD_DIR, stored), 'w', encoding='utf-8') as f:
        f.write(text)
    return stored


# ═══════════════════════ 配置（教师）═══════════════════════

@dsci_bp.route('/ds/competitions/<int:comp_id>/config', methods=['POST'])
def api_set_config(comp_id):
    user, err = require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    comp, err = _get_comp(comp_id) if comp and comp.competition_type == CompetitionTypeEnum.DS else (comp, err)
    if not comp or comp.competition_type != CompetitionTypeEnum.DS:
        return jsonify({'message': '仅数据科学赛可配置'}), 400

    data = request.get_json(silent=True) or {}
    metric = str(data.get('metric') or '').strip()
    if metric not in METRICS:
        return jsonify({'message': f'指标须为 {"|".join(METRICS)} 之一'}), 400
    comp.ds_metric = metric
    comp.ds_id_column = str(data.get('id_column') or 'id').strip()[:50]
    comp.ds_target_column = str(data.get('target_column') or 'label').strip()[:50]
    try:
        ratio = float(data.get('public_ratio', comp.ds_public_ratio if comp.ds_public_ratio is not None else 0.3))
        comp.ds_public_ratio = min(max(ratio, 0.1), 0.9)
    except (TypeError, ValueError):
        return jsonify({'message': 'public_ratio 须为 0.1~0.9 的小数'}), 400
    try:
        comp.ds_daily_limit = min(max(int(data.get('daily_limit', comp.ds_daily_limit or 5)), 1), 100)
    except (TypeError, ValueError):
        return jsonify({'message': 'daily_limit 须为整数'}), 400

    if metric == 'custom':
        scorer = str(data.get('scorer_code') or '').strip()
        if not scorer:
            return jsonify({'message': 'custom 指标须提供 scorer_code'}), 400
        try:
            compile(scorer, '<scorer>', 'exec')
        except SyntaxError as se:
            return jsonify({'message': f'评分脚本语法错误：{se}'}), 400
        comp.ds_scorer_code = scorer[:20000]
        comp.ds_higher_is_better = bool(data.get('higher_is_better', True))
    else:
        comp.ds_higher_is_better = higher_is_better(metric)
    db.session.commit()
    return jsonify({'message': '配置已保存', 'config': _config_dict(comp)})


@dsci_bp.route('/ds/competitions/<int:comp_id>/config', methods=['GET'])
def api_get_config(comp_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp, err = _get_comp(comp_id)
    if err:
        return err
    return jsonify({'config': _config_dict(comp), 'is_teacher': user.is_teacher()})


def _config_dict(comp):
    return {'metric': comp.ds_metric, 'metric_label': METRICS.get(comp.ds_metric, {}).get('label'),
            'id_column': comp.ds_id_column, 'target_column': comp.ds_target_column,
            'public_ratio': comp.ds_public_ratio, 'daily_limit': comp.ds_daily_limit,
            'higher_is_better': higher_is_better(comp.ds_metric, comp.ds_higher_is_better)
            if comp.ds_metric else None,
            'has_custom': bool(comp.ds_scorer_code) if comp.ds_metric == 'custom' else False,
            'configured': bool(comp.ds_metric and comp.ds_id_column and comp.ds_target_column)}


# ═══════════════════════ 数据集（教师上传/管理，学生下载）═══════════════════════

@dsci_bp.route('/ds/competitions/<int:comp_id>/datasets', methods=['POST'])
def api_upload_dataset(comp_id):
    user, err = require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.competition_type != CompetitionTypeEnum.DS:
        return jsonify({'message': '仅数据科学赛可上传数据集'}), 400
    file = request.files.get('file')
    role = str(request.form.get('role') or '').strip().lower()
    if not file or not file.filename:
        return jsonify({'message': '请选择文件'}), 400
    if role not in DatasetRole.ALL:
        return jsonify({'message': 'role 须为 train/test/gold/sample'}), 400
    if os.path.splitext(file.filename)[1].lower() != '.csv':
        return jsonify({'message': '数据集文件须为 .csv'}), 400
    try:
        stored, size = _save_upload(file, 'dsdata')
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    ds = _get_or_create_dataset(comp, user.id)
    # 同角色旧文件覆盖式删除（gold 唯一）
    for old in _files_of(comp, roles=[role]):
        _safe_remove(old.stored_name)
        db.session.delete(old)
    db.session.flush()
    df = DatasetFile(dataset_id=ds.id, role=role, filename=file.filename[:200],
                     stored_name=stored, size=size, is_downloadable=(role != DatasetRole.GOLD),
                     uploaded_by=user.id)
    db.session.add(df)
    db.session.commit()
    return jsonify({'message': '上传成功', 'file': df.to_dict(for_teacher=True)}), 201


@dsci_bp.route('/ds/competitions/<int:comp_id>/datasets', methods=['GET'])
def api_list_datasets(comp_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp, err = _get_comp(comp_id)
    if err:
        return err
    if user.is_student() and not _visible_to_student(comp):
        return jsonify({'message': '竞赛未对你开放'}), 403
    for_teacher = user.is_teacher()
    rows = _files_of(comp)
    return jsonify({'items': [f.to_dict(for_teacher=for_teacher) for f in rows]})


@dsci_bp.route('/ds/files/<int:file_id>', methods=['DELETE'])
def api_delete_dataset_file(file_id):
    user, err = require_teacher()
    if err:
        return err
    df = db.session.get(DatasetFile, file_id)
    if not df:
        return jsonify({'message': '文件不存在'}), 404
    ds = db.session.get(Dataset, df.dataset_id)
    comp, err = _get_own_competition(user, ds.competition_id)
    if err:
        return err
    _safe_remove(df.stored_name)
    db.session.delete(df)
    db.session.commit()
    return jsonify({'message': '已删除'})


@dsci_bp.route('/ds/files/<int:file_id>/download', methods=['GET'])
def api_download_dataset_file(file_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    df = db.session.get(DatasetFile, file_id)
    if not df:
        return jsonify({'message': '文件不存在'}), 404
    ds = db.session.get(Dataset, df.dataset_id)
    if not df.is_downloadable or df.role == DatasetRole.GOLD:
        return jsonify({'message': '该文件为隐藏答案，不可下载'}), 403
    if not user.is_teacher():
        joined = CompetitionParticipant.query.filter_by(
            competition_id=ds.competition_id, user_id=user.id).first()
        if not joined:
            return jsonify({'message': '报名竞赛后可下载数据'}), 403
    return send_from_directory(_UPLOAD_DIR, df.stored_name,
                               as_attachment=True, download_name=df.filename)


def _safe_remove(stored_name):
    try:
        os.remove(os.path.join(_UPLOAD_DIR, stored_name))
    except OSError:
        pass


# ═══════════════════════ 在线编写运行（学生）═══════════════════════

@dsci_bp.route('/ds/competitions/<int:comp_id>/notebook/run', methods=['POST'])
def api_notebook_run(comp_id):
    user, err = _require_student()
    if err:
        return err
    comp, err = _get_comp(comp_id)
    if err:
        return err
    comp.sync_status()
    if comp.status not in (CompetitionStatusEnum.PUBLISHED, CompetitionStatusEnum.ONGOING):
        return jsonify({'message': '竞赛不在开放期，无法运行'}), 400
    if not CompetitionParticipant.query.filter_by(competition_id=comp.id, user_id=user.id).first():
        return jsonify({'message': '请先报名竞赛'}), 403

    data = request.get_json(silent=True) or {}
    code = str(data.get('code') or '')
    public_files = {}
    for f in _files_of(comp, roles=list(DatasetRole.VISIBLE)):
        text, _ = _read_upload_text(f.stored_name)
        if text is not None:
            public_files[os.path.basename(f.filename)] = text
    r = run_notebook(code, public_files)
    run = DsNotebookRun(competition_id=comp.id, user_id=user.id, code=code[:200000],
                        stdout=(r.get('stdout') or '')[:100000],
                        stderr=(r.get('stderr') or '')[:50000],
                        exit_code=r.get('exit_code'), timed_out=bool(r.get('timed_out')),
                        rejected=r['error'] if r['status'] == 'rejected' else None,
                        produced_submission=r.get('produced_submission'))
    db.session.add(run)
    db.session.commit()
    produced = r.get('produced_submission')
    return jsonify({
        'run_id': run.id, 'status': r['status'],
        'stdout': r.get('stdout') or '', 'stderr': r.get('stderr') or '',
        'exit_code': r.get('exit_code'), 'timed_out': r.get('timed_out'),
        'error': r.get('error'),
        'has_submission': bool(produced),
        'submission_preview': (produced or '')[:2000],
    })


# ═══════════════════════ 提交与评分（学生）═══════════════════════

@dsci_bp.route('/ds/competitions/<int:comp_id>/submit', methods=['POST'])
def api_submit(comp_id):
    user, err = _require_student()
    if err:
        return err
    comp, err = _get_comp(comp_id)
    if err:
        return err
    comp.sync_status()
    if comp.status != CompetitionStatusEnum.ONGOING:
        return jsonify({'message': '仅竞赛进行中可提交'}), 400
    if not CompetitionParticipant.query.filter_by(competition_id=comp.id, user_id=user.id).first():
        return jsonify({'message': '请先报名竞赛'}), 403
    if not (comp.ds_metric and comp.ds_id_column and comp.ds_target_column):
        return jsonify({'message': '赛事尚未配置评分指标，暂不可提交'}), 400

    # 取预测 csv：multipart file 或 from_run_id 取在线产出
    pred_text, fname = None, 'prediction.csv'
    from_run_id = None
    file = request.files.get('file')
    if file and file.filename:
        if os.path.splitext(file.filename)[1].lower() != '.csv':
            return jsonify({'message': '预测文件须为 .csv'}), 400
        try:
            raw = file.read()
        except Exception:
            return jsonify({'message': '读取上传失败'}), 400
        if len(raw) > _MAX_CSV_BYTES:
            return jsonify({'message': '预测文件超过 5MB 上限'}), 400
        pred_text = raw.decode('utf-8', errors='replace')
        fname = file.filename[:200]
    else:
        data = request.get_json(silent=True) or {}
        from_run_id = data.get('from_run_id')
        run = db.session.get(DsNotebookRun, int(from_run_id)) if from_run_id else None
        if not run or run.user_id != user.id or run.competition_id != comp.id:
            return jsonify({'message': '请选择有效运行记录或上传预测文件'}), 400
        if not run.produced_submission:
            return jsonify({'message': '该运行未产出 submission.csv'}), 400
        pred_text = run.produced_submission
        fname = 'submission.csv'

    # 每日限次
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today = DsSubmission.query.filter(DsSubmission.competition_id == comp.id,
                                      DsSubmission.user_id == user.id,
                                      DsSubmission.created_at >= day_start).count()
    if today >= (comp.ds_daily_limit or 5):
        return jsonify({'message': f'今日提交次数已达上限（{comp.ds_daily_limit}）'}), 429

    pred_df, perr = _parse_csv(pred_text)
    stored = _save_pred_csv(pred_text)
    version = DsSubmission.query.filter_by(competition_id=comp.id, user_id=user.id).count() + 1
    sub = DsSubmission(competition_id=comp.id, user_id=user.id,
                       kind='notebook' if from_run_id else 'file',
                       filename=fname, stored_name=stored, version=version)
    if perr:
        sub.status, sub.error_msg = DsSubmission.STATUS_ERROR, perr[:300]
        db.session.add(sub)
        db.session.commit()
        return jsonify({'message': perr, 'submission': sub.to_dict()}), 400

    pub, priv, serr = _score_prediction(comp, pred_df, pred_text)
    if serr:
        sub.status, sub.error_msg = DsSubmission.STATUS_ERROR, serr[:300]
    else:
        sub.status, sub.public_score, sub.private_score = DsSubmission.STATUS_SCORED, pub, priv
        sub.scored_at = utcnow()
    db.session.add(sub)
    db.session.commit()
    return jsonify({'message': '提交成功' if not serr else serr,
                    'submission': sub.to_dict(with_private=user.is_teacher())}), 201


@dsci_bp.route('/ds/competitions/<int:comp_id>/my-submissions', methods=['GET'])
def api_my_submissions(comp_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp, err = _get_comp(comp_id)
    if err:
        return err
    subs = (DsSubmission.query.filter_by(competition_id=comp.id, user_id=user.id)
            .order_by(DsSubmission.created_at.desc()).all())
    return jsonify({'items': [s.to_dict() for s in subs]})


# ═══════════════════════ 榜单（公开/私密）═══════════════════════

@dsci_bp.route('/ds/competitions/<int:comp_id>/leaderboard', methods=['GET'])
def api_leaderboard(comp_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp, err = _get_comp(comp_id)
    if err:
        return err
    scope = str(request.args.get('scope') or 'public').lower()
    private_visible = user.is_teacher() and comp.status == CompetitionStatusEnum.ENDED
    if scope == 'private' and not private_visible:
        return jsonify({'message': '私榜仅竞赛结束后对教师可见'}), 403
    key = 'private_score' if scope == 'private' else 'public_score'
    rows = _rank(comp, key)
    return jsonify({'scope': scope, 'metric': comp.ds_metric,
                    'higher_is_better': higher_is_better(comp.ds_metric, comp.ds_higher_is_better),
                    'items': rows})


def _rank(comp, key):
    """每位用户取该榜单维度下的最优一次提交，按方向排序编号。"""
    hib = higher_is_better(comp.ds_metric, comp.ds_higher_is_better)
    best = {}
    for s in comp.ds_submissions:
        val = getattr(s, key)
        if val is None:
            continue
        cur = best.get(s.user_id)
        if cur is None or (val > cur[key] if hib else val < cur[key]):
            best[s.user_id] = {'user_id': s.user_id, key: val, 'submission_id': s.id,
                               'username': s.user.username if s.user else ''}
    ordered = sorted(best.values(), key=lambda r: r[key], reverse=hib)
    for i, r in enumerate(ordered, start=1):
        r['rank'] = i
    return ordered


# ═══════════════════════ 重跑评分（教师，幂等）═══════════════════════

@dsci_bp.route('/ds/competitions/<int:comp_id>/rescore', methods=['POST'])
def api_rescore(comp_id):
    user, err = require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.competition_type != CompetitionTypeEnum.DS:
        return jsonify({'message': '仅数据科学赛可重跑评分'}), 400
    n = 0
    for s in comp.ds_submissions:
        text, _ = _read_upload_text(s.stored_name)
        if text is None:
            continue
        pred_df, perr = _parse_csv(text)
        if perr:
            s.status, s.error_msg = DsSubmission.STATUS_ERROR, perr[:300]
            continue
        pub, priv, serr = _score_prediction(comp, pred_df, text)
        if serr:
            s.status, s.error_msg = DsSubmission.STATUS_ERROR, serr[:300]
        else:
            s.status, s.public_score, s.private_score = DsSubmission.STATUS_SCORED, pub, priv
            s.scored_at = utcnow()
            s.error_msg = None
        n += 1
    db.session.commit()
    return jsonify({'message': f'已重跑 {n} 条提交评分', 'rescored': n})
