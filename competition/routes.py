"""竞赛管理端 API（教师）"""
import json
import os
import secrets

from flask import Blueprint, request, jsonify, send_from_directory

from database import db
from database.models import Question, User, RoleEnum
from utils.timeutil import parse_dt, utcnow, iso_local
from utils.security import verify_token
from utils.notify import create_notification
from utils.uploads import save_upload as _unified_save_upload, UPLOAD_DIR as _UPLOAD_DIR, ALLOWED_EXTENSIONS as _FILE_EXTS
from ledger import core as ledger
from competition.models import (
    Competition, CompetitionQuestion, CompetitionStatusEnum, CompetitionTypeEnum,
    CompetitionSeries, CompetitionParticipant, ParticipantStatusEnum, DiscussionPost,
    CompetitionAnnouncement, CompetitionResource, CompetitionWork,
)
from competition.scoring import COMPETITION_QUESTION_TYPES, parse_scoring_rule

competition_bp = Blueprint('competition', __name__)


def _require_teacher():
    """委托 utils.permissions 统一实现（RBAC 收敛）；保持未登录/非教师均 403 原语义。"""
    from utils.permissions import require_teacher
    return require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)


def _get_own_competition(user, comp_id):
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return None, (jsonify({'message': '竞赛不存在'}), 404)
    if comp.creator_id != user.id:
        return None, (jsonify({'message': '无权访问'}), 403)
    return comp, None


def _gen_invite_code():
    """生成 8 位十六进制邀请码。"""
    return secrets.token_hex(4).upper()


def _notify(user_id, title, content, type='info', related_id=None):
    create_notification(user_id=user_id, title=title[:200], content=content,
                        type=type, related_type='competition', related_id=related_id,
                        commit=True)


def _other_teachers(exclude_id):
    """v4.5 审核门禁：可参与互审的其他教师列表。"""
    return User.query.filter(User.role == RoleEnum.TEACHER,
                             User.id != exclude_id).all()


def _refund_frozen(comp, memo='赛事奖金托管退回'):
    """把尚未发放的托管积分退回创建者钱包（在调用方事务内）。"""
    amount = int(comp.frozen_points or 0)
    if amount <= 0:
        return
    ledger.post(comp.creator_id, 'bounty', amount, 'refund', ref_type='competition',
                ref_id=comp.id, memo=memo)
    comp.frozen_points = 0


def _norm_access(value):
    return 'restricted' if value == 'restricted' else 'public'


def _norm_remind(value):
    try:
        return min(max(int(value or 0), 0), 1440)
    except (TypeError, ValueError):
        return 0


def competition_to_dict(comp, with_questions=False):
    data = {
        'id': comp.id,
        'title': comp.title,
        'description': comp.description,
        'competition_type': comp.competition_type,
        'status': comp.status,
        'start_time': iso_local(comp.start_time),
        'end_time': iso_local(comp.end_time),
        'duration': comp.duration,
        'draw_count': comp.draw_count or 0,
        'allow_pk': bool(comp.allow_pk),
        'scoring_rule': json.loads(comp.scoring_rule or '{}'),
        'total_score': comp.total_score,
        'question_count': len(comp.questions),
        'participant_count': len(comp.participants),
        'created_at': iso_local(comp.created_at),
        'access_mode': comp.access_mode or 'public',
        'remind_before': comp.remind_before or 0,
        'prize_points': comp.prize_points or 0,
        'frozen_points': comp.frozen_points or 0,
        'review_reason': comp.review_reason,
    }
    if with_questions:
        data['invite_code'] = comp.invite_code
        data['questions'] = [{
            'id': cq.id,
            'question_id': cq.question_id,
            'q_type': cq.q_type,
            'content': cq.content,
            'options': cq.options,
            'score': cq.score,
            'order': cq.order,
        } for cq in sorted(comp.questions, key=lambda x: x.order)]
    return data


@competition_bp.route('/competitions', methods=['GET'])
def api_list_competitions():
    user, err = _require_teacher()
    if err:
        return err
    comps = Competition.query.filter_by(creator_id=user.id) \
        .order_by(Competition.created_at.desc()).all()
    for c in comps:
        c.sync_status()
    db.session.commit()
    return jsonify([competition_to_dict(c) for c in comps])


@competition_bp.route('/competitions', methods=['POST'])
def api_create_competition():
    user, err = _require_teacher()
    if err:
        return err
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '竞赛标题不能为空'}), 400

    try:
        start_time = parse_dt(data['start_time'])
        end_time = parse_dt(data['end_time'])
    except (KeyError, ValueError):
        return jsonify({'message': '时间格式不正确'}), 400
    if end_time <= start_time:
        return jsonify({'message': '结束时间必须晚于开始时间'}), 400

    comp_type = data.get('competition_type', CompetitionTypeEnum.TIMED)
    if comp_type not in (CompetitionTypeEnum.TIMED, CompetitionTypeEnum.PROJECT,
                         CompetitionTypeEnum.DS):
        return jsonify({'message': '暂不支持该竞赛类型'}), 400

    duration = int(data.get('duration') or 0)
    if comp_type in (CompetitionTypeEnum.PROJECT, CompetitionTypeEnum.DS):
        duration = max(duration, 0)  # 作品/数据赛型竞赛无答题时长限制
    elif duration <= 0:
        return jsonify({'message': '答题时长必须大于0分钟'}), 400

    # v4.5 冠军奖金（积分托管，0=纯荣誉赛）
    try:
        prize_points = max(0, min(int(data.get('prize_points') or 0), 100000))
    except (TypeError, ValueError):
        return jsonify({'message': 'prize_points 必须为整数'}), 400

    rule = data.get('scoring_rule') or {}
    base_ratio = float(rule.get('base_ratio', 0.7))
    speed_ratio = float(rule.get('speed_ratio', 0.3))
    draw_count = int(data.get('draw_count') or 0)
    allow_pk = bool(data.get('allow_pk', True))
    remind_before = _norm_remind(data.get('remind_before'))
    access_mode = _norm_access(data.get('access_mode'))
    invite_code = None
    if access_mode == 'restricted':
        invite_code = (data.get('invite_code') or '').strip().upper() or _gen_invite_code()

    comp = Competition(
        title=title,
        description=data.get('description'),
        competition_type=comp_type,
        status=CompetitionStatusEnum.DRAFT,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
        draw_count=draw_count,
        allow_pk=allow_pk,
        scoring_rule=json.dumps({'base_ratio': base_ratio, 'speed_ratio': speed_ratio}),
        creator_id=user.id,
        remind_before=remind_before,
        access_mode=access_mode,
        invite_code=invite_code,
        prize_points=prize_points,
    )
    db.session.add(comp)
    db.session.commit()
    return jsonify({'message': '创建成功', 'id': comp.id})


@competition_bp.route('/competitions/<int:comp_id>', methods=['GET'])
def api_get_competition(comp_id):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    comp.sync_status()
    db.session.commit()
    return jsonify(competition_to_dict(comp, with_questions=True))


@competition_bp.route('/competitions/<int:comp_id>', methods=['PUT'])
def api_update_competition(comp_id):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.status not in (CompetitionStatusEnum.DRAFT, CompetitionStatusEnum.REJECTED):
        return jsonify({'message': '仅草稿/被驳回状态可编辑'}), 400

    data = request.get_json() or {}
    if 'title' in data:
        comp.title = (data['title'] or '').strip() or comp.title
    if 'description' in data:
        comp.description = data['description']
    if 'start_time' in data:
        try:
            comp.start_time = parse_dt(data['start_time'])
        except ValueError:
            return jsonify({'message': '时间格式不正确'}), 400
    if 'end_time' in data:
        try:
            comp.end_time = parse_dt(data['end_time'])
        except ValueError:
            return jsonify({'message': '时间格式不正确'}), 400
    if comp.end_time <= comp.start_time:
        return jsonify({'message': '结束时间必须晚于开始时间'}), 400
    if 'duration' in data:
        comp.duration = int(data['duration'] or 0)
        if comp.competition_type != CompetitionTypeEnum.PROJECT and comp.duration <= 0:
            return jsonify({'message': '答题时长必须大于0分钟'}), 400
    if 'prize_points' in data:
        try:
            comp.prize_points = max(0, min(int(data['prize_points'] or 0), 100000))
        except (TypeError, ValueError):
            return jsonify({'message': 'prize_points 必须为整数'}), 400
    if 'scoring_rule' in data:
        rule = data['scoring_rule'] or {}
        comp.scoring_rule = json.dumps({
            'base_ratio': float(rule.get('base_ratio', 0.7)),
            'speed_ratio': float(rule.get('speed_ratio', 0.3)),
        })
    if 'draw_count' in data:
        comp.draw_count = max(0, int(data['draw_count'] or 0))
    if 'allow_pk' in data:
        comp.allow_pk = bool(data['allow_pk'])
    if 'remind_before' in data:
        comp.remind_before = _norm_remind(data['remind_before'])
    if 'access_mode' in data:
        access_mode = _norm_access(data['access_mode'])
        comp.access_mode = access_mode
        if access_mode == 'restricted':
            if not comp.invite_code:
                comp.invite_code = (data.get('invite_code') or '').strip().upper() or _gen_invite_code()
        else:  # 改回 public：清空邀请码，保留已报名者
            comp.invite_code = None

    db.session.commit()
    return jsonify({'message': '更新成功'})


@competition_bp.route('/competitions/<int:comp_id>/invite/reset', methods=['POST'])
def api_reset_invite_code(comp_id):
    """重置邀请码（仅创建者）；返回新码。"""
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.access_mode != 'restricted':
        return jsonify({'message': '仅受限竞赛需要邀请码'}), 400
    comp.invite_code = _gen_invite_code()
    db.session.commit()
    return jsonify({'message': '已重置', 'invite_code': comp.invite_code})


@competition_bp.route('/competitions/<int:comp_id>', methods=['DELETE'])
def api_delete_competition(comp_id):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.status == CompetitionStatusEnum.ONGOING:
        return jsonify({'message': '进行中的竞赛不能删除，请先结束'}), 400
    # 未发放的托管积分退回创建者钱包
    _refund_frozen(comp)
    # v4.5 新表无级联删除关系，先手动清理公告/资料/作品
    CompetitionWork.query.filter_by(competition_id=comp.id).delete()
    CompetitionAnnouncement.query.filter_by(competition_id=comp.id).delete()
    CompetitionResource.query.filter_by(competition_id=comp.id).delete()
    db.session.delete(comp)
    db.session.commit()
    return jsonify({'message': '删除成功'})


@competition_bp.route('/competitions/<int:comp_id>/questions', methods=['POST'])
def api_add_questions(comp_id):
    """批量添加题目并生成快照"""
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.status != CompetitionStatusEnum.DRAFT:
        return jsonify({'message': '仅草稿状态可编辑题目'}), 400

    data = request.get_json() or {}
    question_ids = data.get('question_ids', [])
    score = float(data.get('score', 1.0))
    if not question_ids:
        return jsonify({'message': '请选择题目'}), 400
    if score <= 0:
        return jsonify({'message': '每题分值必须大于0'}), 400

    added, skipped = 0, 0
    next_order = len(comp.questions)
    for q_id in question_ids:
        q = db.session.get(Question, q_id)
        if not q:
            skipped += 1
            continue
        if q.type not in COMPETITION_QUESTION_TYPES:
            skipped += 1
            continue
        exists = CompetitionQuestion.query.filter_by(
            competition_id=comp.id, question_id=q.id).first()
        if exists:
            skipped += 1
            continue
        cq = CompetitionQuestion(
            competition_id=comp.id,
            question_id=q.id,
            q_type=q.type,
            content=q.content,
            options=q.options,
            answer=q.answer,
            analysis=q.analysis,
            score=score,
            order=next_order,
        )
        next_order += 1
        db.session.add(cq)
        added += 1

    db.session.commit()
    return jsonify({'message': f'已添加{added}题', 'added': added, 'skipped': skipped})


@competition_bp.route('/competitions/<int:comp_id>/questions/<int:cq_id>', methods=['DELETE'])
def api_remove_question(comp_id, cq_id):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.status != CompetitionStatusEnum.DRAFT:
        return jsonify({'message': '仅草稿状态可编辑题目'}), 400

    cq = CompetitionQuestion.query.filter_by(id=cq_id, competition_id=comp.id).first()
    if not cq:
        return jsonify({'message': '题目不存在'}), 404
    db.session.delete(cq)
    # 重排序号
    for i, item in enumerate(sorted(
            [c for c in comp.questions if c.id != cq_id], key=lambda x: x.order)):
        item.order = i
    db.session.commit()
    return jsonify({'message': '移除成功'})


@competition_bp.route('/competitions/<int:comp_id>/publish', methods=['POST'])
def api_publish_competition(comp_id):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.status not in (CompetitionStatusEnum.DRAFT, CompetitionStatusEnum.REJECTED):
        return jsonify({'message': '仅草稿/被驳回状态可发布'}), 400
    is_work = comp.competition_type in (CompetitionTypeEnum.PROJECT, CompetitionTypeEnum.DS)
    if not is_work and not comp.questions:
        return jsonify({'message': '请先添加题目'}), 400

    # 校验快照完整性并重排序号
    questions = sorted(comp.questions, key=lambda x: x.order)
    for i, cq in enumerate(questions):
        cq.order = i
        if not cq.content or not cq.answer:
            return jsonify({'message': f'第{i + 1}题快照数据不完整'}), 400

    comp.total_score = round(sum(cq.score for cq in questions), 2)
    parse_scoring_rule(comp.scoring_rule)  # 校验规则合法

    # v4.5 积分托管：发布时从创建者钱包冻结冠军奖金，余额不足拒绝发布
    if (comp.prize_points or 0) > 0:
        if ledger.balance_of(user.id, 'bounty') < comp.prize_points:
            return jsonify({'message': f'积分钱包余额不足，需托管 {comp.prize_points} 积分作为冠军奖金'}), 400
        ledger.post(user.id, 'bounty', -comp.prize_points, 'freeze', ref_type='competition',
                    ref_id=comp.id, memo='赛事冠军奖金托管')
        comp.frozen_points = comp.prize_points

    # v4.5 发布审核门禁：存在其他教师则交叉审核，仅一名教师时自动通过
    reviewers = _other_teachers(comp.creator_id)
    comp.review_reason = None
    if reviewers:
        comp.status = CompetitionStatusEnum.REVIEWING
        comp.reviewer_id = None
        comp.reviewed_at = None
        db.session.commit()
        for t in reviewers[:50]:
            _notify(t.id, '有赛事待审核',
                    f'「{comp.title}」已提交发布，待你审核。',
                    type='info', related_id=comp.id)
        return jsonify({'message': '已提交审核，通过后将对全体学生开放',
                        'status': comp.status, 'total_score': comp.total_score})
    comp.status = CompetitionStatusEnum.PUBLISHED
    comp.reviewed_at = utcnow()
    db.session.commit()
    return jsonify({'message': '发布成功', 'status': comp.status,
                    'total_score': comp.total_score})


@competition_bp.route('/competitions/pending', methods=['GET'])
def api_pending_competitions():
    """v4.5 审核门禁：待审核赛事列表（教师）"""
    user, err = _require_teacher()
    if err:
        return err
    comps = (Competition.query.filter_by(status=CompetitionStatusEnum.REVIEWING)
             .order_by(Competition.created_at.asc()).all())
    items = []
    for c in comps:
        c.sync_status()
        d = competition_to_dict(c)
        d['creator'] = c.creator.username if c.creator else None
        items.append(d)
    db.session.commit()
    return jsonify({'items': items})


@competition_bp.route('/competitions/<int:comp_id>/review', methods=['POST'])
def api_review_competition(comp_id):
    """v4.5 审核门禁：教师交叉审核（审核人不可为创建者）；驳回退回托管积分"""
    user, err = _require_teacher()
    if err:
        return err
    comp = db.session.get(Competition, comp_id)
    if not comp or comp.status != CompetitionStatusEnum.REVIEWING:
        return jsonify({'message': '赛事不存在或不在待审核状态'}), 404
    if comp.creator_id == user.id:
        return jsonify({'message': '不能审核自己创建的赛事'}), 403
    data = request.get_json() or {}
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return jsonify({'message': '参数错误：action 须为 approve/reject'}), 400
    reason = str(data.get('reason') or '').strip()[:200]
    comp.reviewer_id = user.id
    comp.reviewed_at = utcnow()
    if action == 'approve':
        comp.status = CompetitionStatusEnum.PUBLISHED
        comp.review_reason = None
        db.session.commit()
        comp.sync_status()
        db.session.commit()
        _notify(comp.creator_id, '赛事审核通过',
                f'「{comp.title}」已通过审核并发布。',
                type='success', related_id=comp.id)
        return jsonify({'message': '已通过', 'status': comp.status})
    comp.status = CompetitionStatusEnum.REJECTED
    comp.review_reason = reason or '内容不符合发布要求'
    _refund_frozen(comp, memo='赛事驳回托管退回')
    db.session.commit()
    _notify(comp.creator_id, '赛事审核驳回',
            f'「{comp.title}」驳回原因：{comp.review_reason}。修改后可重新提交发布。',
            type='warning', related_id=comp.id)
    return jsonify({'message': '已驳回', 'status': comp.status})


@competition_bp.route('/competitions/<int:comp_id>/end', methods=['POST'])
def api_end_competition(comp_id):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    if comp.status == CompetitionStatusEnum.ENDED:
        return jsonify({'message': '竞赛已结束'}), 400
    comp.end_time = utcnow()
    comp.status = CompetitionStatusEnum.ENDED
    comp._finish_all_playing()
    db.session.commit()
    return jsonify({'message': '已结束'})


@competition_bp.route('/competitions/<int:comp_id>/participants', methods=['GET'])
def api_list_participants(comp_id):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    comp.sync_status()
    db.session.commit()

    from competition.models import ParticipantStatusEnum
    from competition.leaderboard import get_leaderboard
    participants = []
    for p in comp.participants:
        participants.append({
            'id': p.id,
            'username': p.user.username,
            'status': p.status,
            'score': p.score,
            'used_time': p.used_time,
            'started_at': iso_local(p.started_at),
            'finished_at': iso_local(p.finished_at),
            'answered_count': len(p.answers),
        })
    return jsonify({
        'competition': competition_to_dict(comp),
        'participants': participants,
        'leaderboard': get_leaderboard(comp.id),
    })


# ═══════════════ 多轮系列赛（Series） ═══════════════

def _series_dict(s, round_count=0, participant_count=0):
    d = s.to_dict()
    d['round_count'] = round_count
    d['participant_count'] = participant_count
    return d


@competition_bp.route('/series', methods=['POST'])
def api_create_series():
    user, err = _require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '系列赛标题不能为空'}), 400
    scoring_mode = data.get('scoring_mode') or 'best_n'
    if scoring_mode not in ('sum', 'best_n'):
        return jsonify({'message': '结算模式仅支持 sum / best_n'}), 400
    best_n = max(0, int(data.get('best_n') or 0))
    s = CompetitionSeries(title=title, description=data.get('description'),
                          scoring_mode=scoring_mode, best_n=best_n, creator_id=user.id)
    db.session.add(s)
    db.session.commit()
    return jsonify({'message': '创建成功', 'id': s.id})


@competition_bp.route('/series/<int:series_id>', methods=['PUT'])
def api_update_series(series_id):
    user, err = _require_teacher()
    if err:
        return err
    s = db.session.get(CompetitionSeries, series_id)
    if not s or s.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        s.title = (data['title'] or '').strip() or s.title
    if 'description' in data:
        s.description = data['description']
    if 'scoring_mode' in data and data['scoring_mode'] in ('sum', 'best_n'):
        s.scoring_mode = data['scoring_mode']
    if 'best_n' in data:
        s.best_n = max(0, int(data['best_n'] or 0))
    db.session.commit()
    return jsonify({'message': '更新成功'})


@competition_bp.route('/series/<int:series_id>', methods=['DELETE'])
def api_delete_series(series_id):
    user, err = _require_teacher()
    if err:
        return err
    s = db.session.get(CompetitionSeries, series_id)
    if not s or s.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    # 解除竞赛关联（不删竞赛本身）
    Competition.query.filter_by(series_id=s.id).update({'series_id': None, 'series_round': None})
    db.session.delete(s)
    db.session.commit()
    return jsonify({'message': '删除成功'})


@competition_bp.route('/series/<int:series_id>/competitions', methods=['POST'])
def api_bind_series_competition(series_id):
    user, err = _require_teacher()
    if err:
        return err
    s = db.session.get(CompetitionSeries, series_id)
    if not s or s.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    data = request.get_json(silent=True) or {}
    comp = db.session.get(Competition, data.get('competition_id') or 0)
    if not comp or comp.creator_id != user.id:
        return jsonify({'message': '竞赛不存在或非本人创建'}), 400
    try:
        rnd = int(data.get('series_round') or 0)
    except (TypeError, ValueError):
        rnd = 0
    if rnd < 1:
        rnd = (db.session.query(db.func.max(Competition.series_round))
               .filter(Competition.series_id == s.id).scalar() or 0) + 1
    comp.series_id = s.id
    comp.series_round = rnd
    db.session.commit()
    return jsonify({'message': '已关联', 'series_round': rnd})


@competition_bp.route('/series', methods=['GET'])
def api_list_series():
    user, err = _require_teacher()
    if err:
        return err
    out = []
    for s in CompetitionSeries.query.filter_by(creator_id=user.id).order_by(
            CompetitionSeries.created_at.desc()).all():
        comps = Competition.query.filter_by(series_id=s.id).all()
        pcount = (db.session.query(db.func.count(db.distinct(CompetitionParticipant.id)))
                  .filter(CompetitionParticipant.competition_id.in_(
                      [c.id for c in comps] or [-1])).scalar() or 0)
        out.append(_series_dict(s, round_count=len(comps), participant_count=pcount))
    return jsonify(out)


@competition_bp.route('/series/<int:series_id>', methods=['GET'])
def api_get_series(series_id):
    """系列赛详情（含轮次竞赛列表）；登录用户可读"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    s = db.session.get(CompetitionSeries, series_id)
    if not s:
        return jsonify({'message': '系列赛不存在'}), 404
    comps = Competition.query.filter_by(series_id=s.id).order_by(
        Competition.series_round.asc()).all()
    rounds = [{'competition_id': c.id, 'title': c.title, 'series_round': c.series_round,
               'status': c.status, 'total_score': c.total_score,
               'end_time': iso_local(c.end_time)} for c in comps]
    return jsonify({'series': _series_dict(s, round_count=len(comps)), 'rounds': rounds})


@competition_bp.route('/series/<int:series_id>/standings', methods=['GET'])
def api_series_standings(series_id):
    """系列赛总排名：每用户各轮名次分按 scoring_mode 求和或取最佳 best_n"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    s = db.session.get(CompetitionSeries, series_id)
    if not s:
        return jsonify({'message': '系列赛不存在'}), 404
    rounds_meta, standings = _compute_series_standings(s)
    return jsonify({'series': _series_dict(s), 'rounds': rounds_meta, 'standings': standings})


def _compute_series_standings(s):
    """聚合系列赛各轮已完赛者的名次分，按 scoring_mode 求和 / 取最佳 best_n。"""
    from competition.gamification import _rank_points
    from competition.leaderboard import get_leaderboard
    comps = Competition.query.filter_by(series_id=s.id).order_by(
        Competition.series_round.asc()).all()
    per_user = {}
    rounds_meta = []
    for c in comps:
        rounds_meta.append({'competition_id': c.id, 'round': c.series_round,
                            'title': c.title, 'status': c.status})
        board = get_leaderboard(c.id, limit=10000)
        for e in board:
            if e['status'] != ParticipantStatusEnum.FINISHED:
                continue
            rp = _rank_points(e['rank'])
            rec = per_user.setdefault(e['user_id'], {
                'user_id': e['user_id'], 'username': e['username'], 'rounds': {}})
            rec['rounds'][c.id] = {'rank': e['rank'], 'score': e['score'], 'points': rp}
    standings = []
    for uid, rec in per_user.items():
        pts = sorted([r['points'] for r in rec['rounds'].values()], reverse=True)
        if s.scoring_mode == 'best_n' and s.best_n > 0:
            total = sum(pts[:s.best_n])
        else:
            total = sum(pts)
        standings.append({'user_id': uid, 'username': rec['username'],
                          'total': total, 'rounds': rec['rounds']})
    standings.sort(key=lambda x: -x['total'])
    for i, row in enumerate(standings, start=1):
        row['rank'] = i
    return rounds_meta, standings


@competition_bp.route('/series/available', methods=['GET'])
def api_series_available():
    """学生端：列出在办系列赛（含至少一轮已发布/进行中/已结束），附带我的当前排名。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    visible = {CompetitionStatusEnum.PUBLISHED, CompetitionStatusEnum.ONGOING,
               CompetitionStatusEnum.ENDED}
    out = []
    for s in CompetitionSeries.query.order_by(CompetitionSeries.created_at.desc()).all():
        comps = Competition.query.filter_by(series_id=s.id).order_by(
            Competition.series_round.asc()).all()
        comps = [c for c in comps if c.status in visible]
        if not comps:
            continue
        rounds_meta, standings = _compute_series_standings(s)
        me = next((x for x in standings if x['user_id'] == user.id), None)
        out.append({
            'id': s.id, 'title': s.title, 'description': s.description or '',
            'scoring_mode': s.scoring_mode, 'best_n': s.best_n,
            'round_count': len(comps),
            'ongoing': any(c.status == CompetitionStatusEnum.ONGOING for c in comps),
            'my_rank': me['rank'] if me else None,
            'my_total': me['total'] if me else None,
        })
    return jsonify(out)


# ═══════════════ 公平性审查与公示（反作弊） ═══════════════

def _hist_accuracy(user_id, exclude_comp_id):
    """该用户除本场外历史限时赛作答平均正确率（样本不足返回 None）"""
    from competition.models import CompetitionAnswer
    rows = (db.session.query(CompetitionAnswer.is_correct)
            .join(CompetitionParticipant,
                  CompetitionParticipant.id == CompetitionAnswer.participant_id)
            .filter(CompetitionParticipant.user_id == user_id,
                    CompetitionParticipant.competition_id != exclude_comp_id).all())
    if len(rows) < 5:
        return None, len(rows)
    correct = sum(1 for r in rows if r.is_correct)
    return correct / len(rows), len(rows)


@competition_bp.route('/competitions/<int:comp_id>/integrity', methods=['GET'])
def api_competition_integrity(comp_id):
    """教师端公平审查：聚合每位参与者的正确率/用时/反常标记得分，可一键标记受限"""
    from competition.models import CompetitionAnswer
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    from competition.leaderboard import get_leaderboard
    board = {e['user_id']: e['rank'] for e in get_leaderboard(comp.id, limit=10000)}
    out = []
    for p in comp.participants:
        if p.status != ParticipantStatusEnum.FINISHED or not p.answers:
            continue
        n = len(p.answers)
        correct = sum(1 for a in p.answers if a.is_correct)
        acc = correct / n if n else 0
        avg_time = round(sum(a.time_spent for a in p.answers) / n, 1) if n else 0
        fast_flags = sum(1 for a in p.answers if a.flagged)
        hist_acc, hist_n = _hist_accuracy(p.user_id, comp.id)
        reasons = []
        if fast_flags >= 2:
            reasons.append(f'{fast_flags} 题反应用时异常')
        if acc >= 0.98 and n >= 5 and avg_time < 3:
            reasons.append('高正确率且极短用时')
        if hist_acc is not None and acc - hist_acc > 0.4:
            reasons.append(f'本场正确率较历史({int(hist_acc * 100)}%)异常提升')
        suspicious = bool(reasons)
        p.flagged = suspicious
        out.append({
            'user_id': p.user_id, 'username': p.user.username,
            'rank': board.get(p.user_id), 'score': p.score,
            'accuracy': round(acc, 4), 'answered': n, 'avg_time': avg_time,
            'fast_flags': fast_flags, 'hist_accuracy': round(hist_acc, 4) if hist_acc is not None else None,
            'hist_sample': hist_n, 'suspicious': suspicious, 'reasons': reasons,
            'sanctioned': p.user.is_sanctioned,
        })
    out.sort(key=lambda x: (not x['suspicious'], x['rank'] or 9999))
    db.session.commit()
    return jsonify({'competition': competition_to_dict(comp), 'participants': out})


@competition_bp.route('/competitions/<int:comp_id>/participants/<int:target_uid>/sanction',
                      methods=['POST'])
def api_sanction(comp_id, target_uid):
    """对参赛者施加/撤销竞技受限（仅竞赛创建者）。body: {reason} 或 {revoke:true}"""
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    target = db.session.get(User, target_uid)
    if not target or target.role == 'bot':
        return jsonify({'message': '用户不存在'}), 404
    data = request.get_json(silent=True) or {}
    if data.get('revoke'):
        target.sanctioned_at = None
        target.sanction_reason = None
        db.session.commit()
        return jsonify({'message': '已解除受限'})
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'message': '受限原因不能为空'}), 400
    target.sanctioned_at = utcnow()
    target.sanction_reason = reason[:200]
    db.session.commit()
    try:
        create_notification(user_id=target.id, title='竞技账号受限',
                            content=f'你在竞赛「{comp.title}」中被标记受限：{reason}。如有疑问请联系教师。',
                            type='warning', related_type='competition', related_id=comp.id)
    except Exception:
        pass
    return jsonify({'message': '已标记受限'})


# ═══════════════ 赛后讨论区（竞技内核升级第二批） ═══════════════

def _post_payload(p):
    return {
        'id': p.id, 'user_id': p.user_id,
        'username': p.author.username if p.author else None,
        'content': p.content, 'parent_id': p.parent_id,
        'created_at': iso_local(p.created_at),
    }


def _post_view(p, user, comp):
    d = _post_payload(p)
    d['is_author'] = (p.user_id == user.id)
    d['can_delete'] = (p.user_id == user.id or user.is_teacher() or comp.creator_id == user.id)
    return d


@competition_bp.route('/competitions/<int:comp_id>/discussions', methods=['GET'])
def api_list_discussions(comp_id):
    """讨论区列表：顶层帖（最新在前）+ 嵌套回复（时间升序）。登录可读。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return jsonify({'message': '竞赛不存在'}), 404
    posts = (DiscussionPost.query.filter_by(competition_id=comp_id)
             .order_by(DiscussionPost.created_at.asc()).all())
    tops, replies, top_index = [], {}, {}
    for p in posts:
        if p.parent_id:
            replies.setdefault(p.parent_id, []).append(_post_view(p, user, comp))
        else:
            d = _post_view(p, user, comp)
            d['replies'] = []
            tops.append(d)
            top_index[p.id] = d
    for pid, rs in replies.items():
        t = top_index.get(pid)
        if t is not None:
            t['replies'].extend(rs)
    tops.reverse()
    return jsonify(tops)


@competition_bp.route('/competitions/<int:comp_id>/discussions', methods=['POST'])
def api_create_discussion(comp_id):
    """发帖/回复（发即显示、无需审核）；回复给被回复者发通知并向房间广播。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    if not (user.is_student() or user.is_teacher()):
        return jsonify({'message': '无权发言'}), 403
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return jsonify({'message': '竞赛不存在'}), 404
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'message': '内容不能为空'}), 400
    if len(content) > 500:
        return jsonify({'message': '内容不能超过 500 字'}), 400
    parent_id = data.get('parent_id')
    parent = None
    if parent_id:
        parent = db.session.get(DiscussionPost, parent_id)
        if not parent or parent.competition_id != comp_id:
            return jsonify({'message': '被回复的帖子不存在'}), 404
        if parent.parent_id:  # 仅一层：回复的回复仍挂到顶层
            parent_id = parent.parent_id
            parent = db.session.get(DiscussionPost, parent_id)
    post = DiscussionPost(competition_id=comp_id, user_id=user.id,
                          parent_id=parent_id, content=content)
    db.session.add(post)
    db.session.commit()
    if parent is not None and parent.user_id != user.id:
        try:
            create_notification(
                user_id=parent.user_id, title='收到新回复',
                content=f'{user.username} 在竞赛「{comp.title}」的讨论中回复了你。',
                type='info', related_type='competition', related_id=comp.id)
        except Exception:
            pass
    from competition.realtime import notify_discussion
    notify_discussion(comp_id, _post_payload(post))
    return jsonify({'message': '已发布', 'post': _post_view(post, user, comp)})


@competition_bp.route('/competitions/<int:comp_id>/discussions/<int:post_id>', methods=['DELETE'])
def api_delete_discussion(comp_id, post_id):
    """删除帖子（作者本人/教师/竞赛创建者）；顶层帖连带删除其回复。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return jsonify({'message': '竞赛不存在'}), 404
    post = db.session.get(DiscussionPost, post_id)
    if not post or post.competition_id != comp_id:
        return jsonify({'message': '帖子不存在'}), 404
    if not (post.user_id == user.id or user.is_teacher() or comp.creator_id == user.id):
        return jsonify({'message': '无权删除'}), 403
    DiscussionPost.query.filter_by(parent_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ═══════════════ v4.5 赛事公告 / 资料包 / 作品评审 / 结算 ═══════════════
# _UPLOAD_DIR 已上移至 utils/uploads.UPLOAD_DIR（顶部 import），与学习/悬/作业共用同一落盘目录。


def _save_upload(file, prefix):
    """校验并保存上传文件，返回 (stored_name, size)；出错抛 ValueError。"""
    return _unified_save_upload(file, prefix, _UPLOAD_DIR)


def _visible_to_student(comp):
    return comp.status in (CompetitionStatusEnum.PUBLISHED,
                           CompetitionStatusEnum.ONGOING,
                           CompetitionStatusEnum.ENDED)


def _announcement_dict(a):
    return {'id': a.id, 'competition_id': a.competition_id, 'title': a.title,
            'content': a.content, 'author': a.author.username if a.author else None,
            'created_at': iso_local(a.created_at)}


def _resource_dict(r):
    return {'id': r.id, 'competition_id': r.competition_id, 'title': r.title,
            'filename': r.filename, 'size': r.size or 0,
            'uploader': r.uploader.username if r.uploader else None,
            'created_at': iso_local(r.created_at)}


def _work_dict(w, with_user=False):
    d = {'id': w.id, 'competition_id': w.competition_id, 'description': w.description,
         'filename': w.filename, 'size': w.size or 0, 'version': w.version or 1,
         'score': w.score, 'review_note': w.review_note,
         'submitted_at': iso_local(w.submitted_at), 'updated_at': iso_local(w.updated_at),
         'scored_at': iso_local(w.scored_at)}
    if with_user and w.user:
        d['user_id'] = w.user_id
        d['username'] = w.user.username
    return d


@competition_bp.route('/competitions/<int:comp_id>/announcements', methods=['GET'])
def api_list_announcements(comp_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp = db.session.get(Competition, comp_id)
    if not comp or (user.is_student() and not _visible_to_student(comp)):
        return jsonify({'message': '竞赛不存在'}), 404
    rows = (CompetitionAnnouncement.query.filter_by(competition_id=comp_id)
            .order_by(CompetitionAnnouncement.created_at.desc()).all())
    return jsonify({'items': [_announcement_dict(a) for a in rows]})


@competition_bp.route('/competitions/<int:comp_id>/announcements', methods=['POST'])
def api_create_announcement(comp_id):
    """发布赛事公告并向全体参赛者广播通知"""
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()[:100]
    content = str(data.get('content') or '').strip()[:5000]
    if not title or not content:
        return jsonify({'message': '标题与内容不能为空'}), 400
    ann = CompetitionAnnouncement(competition_id=comp.id, title=title,
                                  content=content, created_by=user.id)
    db.session.add(ann)
    db.session.flush()
    for uid in {p.user_id for p in comp.participants}:
        _notify(uid, f'赛事公告：{title}', content[:120],
                type='info', related_id=comp.id)
    db.session.commit()
    return jsonify({'message': '已发布', 'announcement': _announcement_dict(ann)}), 201


@competition_bp.route('/competitions/<int:comp_id>/announcements/<int:aid>', methods=['DELETE'])
def api_delete_announcement(comp_id, aid):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    ann = db.session.get(CompetitionAnnouncement, aid)
    if not ann or ann.competition_id != comp.id:
        return jsonify({'message': '公告不存在'}), 404
    db.session.delete(ann)
    db.session.commit()
    return jsonify({'message': '已删除'})


@competition_bp.route('/competitions/<int:comp_id>/resources', methods=['GET'])
def api_list_resources(comp_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp = db.session.get(Competition, comp_id)
    if not comp or (user.is_student() and not _visible_to_student(comp)):
        return jsonify({'message': '竞赛不存在'}), 404
    rows = (CompetitionResource.query.filter_by(competition_id=comp_id)
            .order_by(CompetitionResource.created_at.desc()).all())
    return jsonify({'items': [_resource_dict(r) for r in rows]})


@competition_bp.route('/competitions/<int:comp_id>/resources', methods=['POST'])
def api_upload_resource(comp_id):
    """上传赛题附件/资料包（multipart file，可选 title 字段）"""
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'message': '请选择文件'}), 400
    try:
        stored, size = _save_upload(file, 'compres')
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    title = str(request.form.get('title') or '').strip()[:200] or file.filename
    res = CompetitionResource(competition_id=comp.id, title=title,
                              filename=file.filename[:200], stored_name=stored,
                              size=size, uploaded_by=user.id)
    db.session.add(res)
    db.session.commit()
    return jsonify({'message': '上传成功', 'resource': _resource_dict(res)}), 201


@competition_bp.route('/competitions/<int:comp_id>/resources/<int:rid>', methods=['DELETE'])
def api_delete_resource(comp_id, rid):
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    res = db.session.get(CompetitionResource, rid)
    if not res or res.competition_id != comp.id:
        return jsonify({'message': '资料不存在'}), 404
    db.session.delete(res)
    db.session.commit()
    try:
        os.remove(os.path.join(_UPLOAD_DIR, res.stored_name))
    except OSError:
        pass
    return jsonify({'message': '已删除'})


@competition_bp.route('/competition-resources/<int:rid>/download', methods=['GET'])
def api_download_resource(rid):
    """资料下载：教师或已报名学生；UUID 存储名不可枚举"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    res = db.session.get(CompetitionResource, rid)
    if not res:
        return jsonify({'message': '资料不存在'}), 404
    if not user.is_teacher():
        joined = CompetitionParticipant.query.filter_by(
            competition_id=res.competition_id, user_id=user.id).first()
        if not joined:
            return jsonify({'message': '报名竞赛后可下载资料'}), 403
    return send_from_directory(_UPLOAD_DIR, res.stored_name,
                               as_attachment=True, download_name=res.filename)


@competition_bp.route('/competitions/<int:comp_id>/works', methods=['GET'])
def api_list_works(comp_id):
    """教师查看作品提交列表（project 型竞赛）"""
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    rows = (CompetitionWork.query.filter_by(competition_id=comp.id)
            .order_by(CompetitionWork.score.is_(None),
                      CompetitionWork.score.desc(),
                      CompetitionWork.submitted_at.asc()).all())
    return jsonify({'items': [_work_dict(w, with_user=True) for w in rows]})


@competition_bp.route('/competition-works/<int:w_id>/score', methods=['POST'])
def api_score_work(w_id):
    """教师人工评审：{score: 0-100, note}；仅竞赛创建者可评"""
    user, err = _require_teacher()
    if err:
        return err
    work = db.session.get(CompetitionWork, w_id)
    if not work:
        return jsonify({'message': '作品不存在'}), 404
    comp = db.session.get(Competition, work.competition_id)
    if not comp or comp.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    data = request.get_json(silent=True) or {}
    try:
        score = float(data.get('score'))
    except (TypeError, ValueError):
        return jsonify({'message': 'score 必须为数字'}), 400
    if not 0 <= score <= 100:
        return jsonify({'message': '评分范围 0-100'}), 400
    work.score = round(score, 1)
    work.review_note = str(data.get('note') or '').strip()[:2000] or None
    work.scored_by = user.id
    work.scored_at = utcnow()
    db.session.commit()
    _notify(work.user_id, '赛事作品已评分',
            f'「{comp.title}」你的作品得分：{work.score}。'
            + (f'评语：{work.review_note}' if work.review_note else ''),
            type='success', related_id=comp.id)
    return jsonify({'message': '已评分', 'work': _work_dict(work, with_user=True)})


@competition_bp.route('/competition-works/<int:w_id>/download', methods=['GET'])
def api_download_work(w_id):
    """作品文件下载：竞赛创建者或作品本人"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    work = db.session.get(CompetitionWork, w_id)
    if not work or not work.stored_name:
        return jsonify({'message': '作品文件不存在'}), 404
    comp = db.session.get(Competition, work.competition_id)
    if not (work.user_id == user.id or (comp and comp.creator_id == user.id)):
        if not user.is_teacher():
            return jsonify({'message': '无权访问'}), 403
    return send_from_directory(_UPLOAD_DIR, work.stored_name,
                               as_attachment=True, download_name=work.filename)


@competition_bp.route('/competitions/<int:comp_id>/settle', methods=['POST'])
def api_settle_competition(comp_id):
    """结算积分托管：冠军获全部托管积分；同分取最早提交/用时短者；无有效作品流标退回"""
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    comp.sync_status()
    if comp.status != CompetitionStatusEnum.ENDED:
        return jsonify({'message': '竞赛结束后才能结算'}), 400
    frozen = int(comp.frozen_points or 0)
    if frozen <= 0:
        return jsonify({'message': '无待发放的托管积分（已结算或纯荣誉赛）'})

    winner_id = None
    if comp.competition_type == CompetitionTypeEnum.DS:
        # 数据科学赛：按私榜分（全量 gold）决冠军，同分取更早提交；方向依指标
        from dsci.metrics import higher_is_better
        scored = [s for s in comp.ds_submissions if s.private_score is not None]
        if scored:
            hib = higher_is_better(comp.ds_metric, comp.ds_higher_is_better)
            best = max(scored, key=lambda s: ((s.private_score if hib else -s.private_score),
                                              -s.created_at.timestamp()))
            winner_id = best.user_id
    elif comp.competition_type == CompetitionTypeEnum.PROJECT:
        scored = [w for w in comp.works if w.score is not None]
        if scored:
            best = max(scored, key=lambda w: (w.score, -(w.submitted_at.timestamp())))
            winner_id = best.user_id
    else:
        fin = [p for p in comp.participants
               if p.status == ParticipantStatusEnum.FINISHED and (p.score or 0) > 0]
        if fin:
            winner_id = min(fin, key=lambda p: (-(p.score or 0), p.used_time or 0)).user_id

    if winner_id:
        ledger.post(winner_id, 'bounty', frozen, 'release', ref_type='competition',
                    ref_id=comp.id, memo='赛事冠军奖金')
        comp.frozen_points = 0
        db.session.commit()
        _notify(winner_id, '恭喜获得赛事冠军奖金',
                f'「{comp.title}」你获得冠军，{frozen} 积分奖金已发放到赏金钱包。',
                type='success', related_id=comp.id)
        return jsonify({'message': '结算完成', 'winner_id': winner_id, 'released': frozen})
    _refund_frozen(comp, memo='赛事流标托管退回')
    db.session.commit()
    _notify(comp.creator_id, '赛事奖金流标退回',
            f'「{comp.title}」无有效获奖作品，托管的 {frozen} 积分已退回你的钱包。',
            type='warning', related_id=comp.id)
    return jsonify({'message': '无有效作品，托管积分已退回', 'refunded': frozen})


@competition_bp.route('/competitions/<int:comp_id>/archive', methods=['POST'])
def api_archive_competition(comp_id):
    """v4.5 赛题归档：结束后赛题正式入公共题库"""
    user, err = _require_teacher()
    if err:
        return err
    comp, err = _get_own_competition(user, comp_id)
    if err:
        return err
    comp.sync_status()
    if comp.status != CompetitionStatusEnum.ENDED:
        return jsonify({'message': '仅已结束竞赛可归档'}), 400
    archived, majors = 0, set()
    for cq in comp.questions:
        q = db.session.get(Question, cq.question_id) if cq.question_id else None
        if q and not q.is_public:
            q.is_public = True
            archived += 1
            if q.major_id:
                majors.add(q.major_id)
    db.session.commit()
    if archived:
        from utils.redis_cache import invalidate_question_cache
        for mid in majors:
            invalidate_question_cache(major_id=mid)
    return jsonify({'message': f'已归档 {archived} 题入公共题库', 'archived': archived})
