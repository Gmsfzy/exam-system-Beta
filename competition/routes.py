"""竞赛管理端 API（教师）"""
import json

from flask import Blueprint, request, jsonify

from database import db
from database.models import Question
from utils.timeutil import parse_dt, utcnow, iso_local
from utils.security import verify_token
from competition.models import (
    Competition, CompetitionQuestion, CompetitionStatusEnum, CompetitionTypeEnum
)
from competition.scoring import COMPETITION_QUESTION_TYPES, parse_scoring_rule

competition_bp = Blueprint('competition', __name__)


def _require_teacher():
    user = verify_token()
    if not user or not user.is_teacher():
        return None, (jsonify({'message': '无权访问'}), 403)
    return user, None


def _get_own_competition(user, comp_id):
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return None, (jsonify({'message': '竞赛不存在'}), 404)
    if comp.creator_id != user.id:
        return None, (jsonify({'message': '无权访问'}), 403)
    return comp, None


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
    }
    if with_questions:
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

    duration = int(data.get('duration') or 0)
    if duration <= 0:
        return jsonify({'message': '答题时长必须大于0分钟'}), 400

    comp_type = data.get('competition_type', CompetitionTypeEnum.TIMED)
    if comp_type not in (CompetitionTypeEnum.TIMED,):
        return jsonify({'message': '暂不支持该竞赛类型'}), 400

    rule = data.get('scoring_rule') or {}
    base_ratio = float(rule.get('base_ratio', 0.7))
    speed_ratio = float(rule.get('speed_ratio', 0.3))
    draw_count = int(data.get('draw_count') or 0)
    allow_pk = bool(data.get('allow_pk', True))

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
    if comp.status != CompetitionStatusEnum.DRAFT:
        return jsonify({'message': '仅草稿状态可编辑'}), 400

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
        if comp.duration <= 0:
            return jsonify({'message': '答题时长必须大于0分钟'}), 400
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

    db.session.commit()
    return jsonify({'message': '更新成功'})


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
    if comp.status != CompetitionStatusEnum.DRAFT:
        return jsonify({'message': '仅草稿状态可发布'}), 400
    if not comp.questions:
        return jsonify({'message': '请先添加题目'}), 400

    # 校验快照完整性并重排序号
    questions = sorted(comp.questions, key=lambda x: x.order)
    for i, cq in enumerate(questions):
        cq.order = i
        if not cq.content or not cq.answer:
            return jsonify({'message': f'第{i + 1}题快照数据不完整'}), 400

    comp.total_score = round(sum(cq.score for cq in questions), 2)
    parse_scoring_rule(comp.scoring_rule)  # 校验规则合法
    comp.status = CompetitionStatusEnum.PUBLISHED
    db.session.commit()
    return jsonify({'message': '发布成功', 'total_score': comp.total_score})


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
