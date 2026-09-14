"""竞赛学生端 API：报名、答题、交卷、排行榜"""
import json
import random
from datetime import timedelta

from flask import Blueprint, request, jsonify

from database import db
from database.models import User
from utils.timeutil import utcnow, iso_local
from utils.security import verify_token
from competition.models import (
    Competition, CompetitionQuestion, CompetitionParticipant,
    CompetitionAnswer, CompetitionStatusEnum, ParticipantStatusEnum
)
from competition.scoring import parse_scoring_rule, grade_objective, calc_question_score
from competition.leaderboard import get_leaderboard, get_my_rank
from competition.realtime import notify_leaderboard_update

competition_play_bp = Blueprint('competition_play', __name__)


def _require_student():
    user = verify_token()
    if not user or not user.is_student():
        return None, (jsonify({'message': '无权访问'}), 403)
    return user, None


def _get_playing_participant(user, comp_id):
    """获取参与者并校验归属；竞赛截止/超时则先结算"""
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return None, None, (jsonify({'message': '竞赛不存在'}), 404)
    participant = CompetitionParticipant.query.filter_by(
        competition_id=comp_id, user_id=user.id).first()
    if not participant:
        return None, None, (jsonify({'message': '请先报名该竞赛'}), 400)
    return comp, participant, None


def _settle_if_needed(comp, participant):
    """竞赛窗口结束或个人用时超限，自动结算"""
    now = utcnow()
    deadline = None
    if participant.started_at:
        deadline = participant.started_at + timedelta(minutes=comp.duration)
    comp_deadline = comp.end_time

    timed_out = participant.status == ParticipantStatusEnum.PLAYING and \
        deadline and now >= deadline
    comp_ended = comp.status == CompetitionStatusEnum.ENDED or now > comp_deadline

    if timed_out or (comp_ended and participant.status != ParticipantStatusEnum.FINISHED):
        if _finish_participant(comp, participant, now):
            notify_leaderboard_update(comp.id)
    return timed_out or comp_ended


def _finish_participant(comp, participant, now):
    """结算：汇总得分与用时"""
    if participant.status == ParticipantStatusEnum.FINISHED:
        return False
    total = sum(a.gained_score for a in participant.answers)
    participant.score = round(total, 2)
    if participant.started_at:
        elapsed = (now - participant.started_at).total_seconds()
        participant.used_time = int(min(elapsed, comp.duration * 60))
    participant.status = ParticipantStatusEnum.FINISHED
    participant.finished_at = now
    return True


@competition_play_bp.route('/competitions/lobby', methods=['GET'])
def api_competition_lobby():
    """学生竞赛广场：已发布的竞赛 + 我的报名状态"""
    user, err = _require_student()
    if err:
        return err

    comps = Competition.query.filter(
        Competition.status.in_([CompetitionStatusEnum.PUBLISHED,
                                CompetitionStatusEnum.ONGOING,
                                CompetitionStatusEnum.ENDED])
    ).order_by(Competition.start_time.desc()).all()
    for c in comps:
        c.sync_status()
    db.session.commit()

    my_parts = {p.competition_id: p for p in
                CompetitionParticipant.query.filter_by(user_id=user.id).all()}

    comp_ids = [c.id for c in comps]
    # 批量聚合题目数 / 参与人数，避免循环内懒加载 N+1
    q_count_map = dict(
        db.session.query(CompetitionQuestion.competition_id, db.func.count())
        .filter(CompetitionQuestion.competition_id.in_(comp_ids))
        .group_by(CompetitionQuestion.competition_id).all()
    ) if comp_ids else {}
    p_count_map = dict(
        db.session.query(CompetitionParticipant.competition_id, db.func.count())
        .filter(CompetitionParticipant.competition_id.in_(comp_ids))
        .group_by(CompetitionParticipant.competition_id).all()
    ) if comp_ids else {}

    result = []
    for c in comps:
        p = my_parts.get(c.id)
        # 已有 my_parts 行直接复用；未开始答题（JOINED）无排名可算
        my_rank = get_my_rank(c.id, user.id, participant=p)['rank'] \
            if p and p.status != ParticipantStatusEnum.JOINED else None
        result.append({
            'id': c.id,
            'title': c.title,
            'description': c.description,
            'status': c.status,
            'start_time': iso_local(c.start_time),
            'end_time': iso_local(c.end_time),
            'duration': c.duration,
            'total_score': c.total_score,
            'question_count': q_count_map.get(c.id, 0),
            'participant_count': p_count_map.get(c.id, 0),
            'my_status': p.status if p else None,
            'my_score': p.score if p else None,
            'my_rank': my_rank,
        })
    return jsonify(result)


@competition_play_bp.route('/competitions/<int:comp_id>/leaderboard', methods=['GET'])
def api_leaderboard(comp_id):
    """排行榜：登录用户即可查看"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return jsonify({'message': '竞赛不存在'}), 404
    comp.sync_status()
    db.session.commit()
    return jsonify({
        'competition': {
            'id': comp.id, 'title': comp.title, 'status': comp.status,
            'total_score': comp.total_score,
            'start_time': iso_local(comp.start_time),
            'end_time': iso_local(comp.end_time),
        },
        'leaderboard': get_leaderboard(comp.id),
        'my': get_my_rank(comp_id, user.id),
    })


@competition_play_bp.route('/competitions/<int:comp_id>/join', methods=['POST'])
def api_join(comp_id):
    user, err = _require_student()
    if err:
        return err
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return jsonify({'message': '竞赛不存在'}), 404
    comp.sync_status()
    db.session.commit()
    if comp.status == CompetitionStatusEnum.DRAFT:
        return jsonify({'message': '竞赛未发布'}), 400
    if comp.status == CompetitionStatusEnum.ENDED:
        return jsonify({'message': '竞赛已结束'}), 400

    existing = CompetitionParticipant.query.filter_by(
        competition_id=comp_id, user_id=user.id).first()
    if existing:
        return jsonify({'message': '已报名', 'participant_id': existing.id})
    participant = CompetitionParticipant(competition_id=comp_id, user_id=user.id)
    db.session.add(participant)
    db.session.commit()
    return jsonify({'message': '报名成功', 'participant_id': participant.id})


def _assign_questions(comp, participant):
    """开始答题时抽题固化（防作弊）：draw_count>0 且题池充足时随机抽取"""
    if participant.assigned_cq_ids:
        return
    all_ids = [cq.id for cq in comp.questions]
    draw = comp.draw_count if comp.draw_count and comp.draw_count > 0 else 0
    if draw > 0 and draw < len(all_ids):
        assigned = random.sample(all_ids, draw)
    else:
        assigned = all_ids
    participant.assigned_cq_ids = json.dumps(assigned)


def _participant_questions(comp, participant):
    """该参与者实际作答的题目列表（按 order 排序）"""
    ids = participant.assigned_question_ids()
    questions = sorted(comp.questions, key=lambda x: x.order)
    if ids is None:
        return questions
    id_set = set(ids)
    return [q for q in questions if q.id in id_set]


@competition_play_bp.route('/competitions/<int:comp_id>/start', methods=['POST'])
def api_start(comp_id):
    user, err = _require_student()
    if err:
        return err
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return jsonify({'message': '竞赛不存在'}), 404
    comp.sync_status()
    db.session.commit()
    if comp.status != CompetitionStatusEnum.ONGOING:
        return jsonify({'message': '竞赛不在答题时间内'}), 400

    participant = CompetitionParticipant.query.filter_by(
        competition_id=comp_id, user_id=user.id).first()
    if not participant:
        return jsonify({'message': '请先报名该竞赛'}), 400

    if participant.status == ParticipantStatusEnum.PLAYING:
        return jsonify({'message': '答题已在进行中'})
    if participant.status == ParticipantStatusEnum.FINISHED:
        return jsonify({'message': '您已完成本次竞赛'}), 400

    participant.status = ParticipantStatusEnum.PLAYING
    participant.started_at = utcnow()
    _assign_questions(comp, participant)
    db.session.commit()

    return jsonify(_play_payload(comp, participant))


@competition_play_bp.route('/competitions/<int:comp_id>/play', methods=['GET'])
def api_play_state(comp_id):
    """答题状态恢复（刷新页面/断线重连）"""
    user, err = _require_student()
    if err:
        return err
    comp, participant, err = _get_playing_participant(user, comp_id)
    if err:
        return err
    comp.sync_status()
    db.session.commit()
    _settle_if_needed(comp, participant)
    db.session.commit()

    if participant.status == ParticipantStatusEnum.JOINED:
        return jsonify({'status': 'joined'})
    if participant.status == ParticipantStatusEnum.FINISHED:
        return jsonify({'status': 'finished', 'my': get_my_rank(comp_id, user.id)})
    return jsonify(_play_payload(comp, participant))


def _play_payload(comp, participant):
    """构造答题数据：题目列表（无答案）+ 已答记录 + 剩余时间"""
    now = utcnow()
    deadline = participant.started_at + timedelta(minutes=comp.duration)
    remaining = max(0, int((deadline - now).total_seconds()))

    answered = {a.cq_id: {
        'answer': a.answer,
        'is_correct': a.is_correct,
        'gained_score': a.gained_score,
    } for a in participant.answers}

    questions = []
    for cq in _participant_questions(comp, participant):
        item = cq.to_public_dict()
        if cq.id in answered:
            item['student_answer'] = answered[cq.id]['answer']
            item['is_correct'] = answered[cq.id]['is_correct']
            item['gained_score'] = answered[cq.id]['gained_score']
        questions.append(item)

    return {
        'status': participant.status,
        'competition': {
            'id': comp.id, 'title': comp.title, 'duration': comp.duration,
            'total_score': comp.total_score,
            'scoring_rule': json.loads(comp.scoring_rule or '{}'),
        },
        'started_at': iso_local(participant.started_at),
        'remaining_seconds': remaining,
        'questions': questions,
    }


@competition_play_bp.route('/competitions/<int:comp_id>/answer', methods=['POST'])
def api_answer(comp_id):
    """逐题作答：即时判分并返回结果"""
    user, err = _require_student()
    if err:
        return err
    comp, participant, err = _get_playing_participant(user, comp_id)
    if err:
        return err
    comp.sync_status()
    settled = _settle_if_needed(comp, participant)
    db.session.commit()
    if settled or participant.status != ParticipantStatusEnum.PLAYING:
        return jsonify({'message': '答题已结束', 'finished': True}), 400

    data = request.get_json() or {}
    cq_id = data.get('cq_id')
    answer_text = str(data.get('answer') or '')

    cq = CompetitionQuestion.query.filter_by(id=cq_id, competition_id=comp.id).first()
    if not cq:
        return jsonify({'message': '题目不存在'}), 404

    # 抽题防作弊：题目必须在开始答题时固化的抽题集合内（None 表示全量作答模式）
    assigned_ids = participant.assigned_question_ids()
    if assigned_ids is not None and cq.id not in assigned_ids:
        return jsonify({'message': '该题目不在你的作答范围内'}), 403

    existing = CompetitionAnswer.query.filter_by(
        participant_id=participant.id, cq_id=cq.id).first()
    if existing:
        return jsonify({'message': '该题已作答'}), 400

    per_q_seconds = comp.per_question_seconds_for(len(_participant_questions(comp, participant)))
    # 服务端计算单题用时：距上一题作答（或开始作答）的时间差，客户端上报值不可信
    now = utcnow()
    last_event = participant.started_at or now
    last_answered = db.session.query(db.func.max(CompetitionAnswer.answered_at)).filter(
        CompetitionAnswer.participant_id == participant.id,
        CompetitionAnswer.answered_at.isnot(None)).scalar()
    if last_answered and last_answered > last_event:
        last_event = last_answered
    time_spent = min(int(max(0.0, (now - last_event).total_seconds())), per_q_seconds * 2)

    is_correct = grade_objective(cq.q_type, answer_text, cq.answer)
    base_ratio, speed_ratio = parse_scoring_rule(comp.scoring_rule)
    gained = calc_question_score(cq.score, is_correct, time_spent,
                                 per_q_seconds, base_ratio, speed_ratio)

    record = CompetitionAnswer(
        participant_id=participant.id,
        cq_id=cq.id,
        answer=answer_text,
        is_correct=is_correct,
        gained_score=gained,
        time_spent=time_spent,
    )
    db.session.add(record)
    db.session.commit()
    # 提交后重新聚合，避免会话缓存导致漏加/重复计数
    total = db.session.query(db.func.coalesce(
        db.func.sum(CompetitionAnswer.gained_score), 0.0)) \
        .filter_by(participant_id=participant.id).scalar()
    participant.score = round(float(total), 2)
    db.session.commit()

    return jsonify({
        'message': '已记录',
        'is_correct': is_correct,
        'gained_score': gained,
        'total_score': participant.score,
        'correct_answer': cq.answer,  # 作答后展示正确选项
    })


@competition_play_bp.route('/competitions/<int:comp_id>/finish', methods=['POST'])
def api_finish(comp_id):
    """主动交卷"""
    user, err = _require_student()
    if err:
        return err
    comp, participant, err = _get_playing_participant(user, comp_id)
    if err:
        return err
    comp.sync_status()
    now = utcnow()
    if _finish_participant(comp, participant, now):
        db.session.commit()
        notify_leaderboard_update(comp.id)
    db.session.commit()
    return jsonify({'message': '交卷成功', 'my': get_my_rank(comp_id, user.id)})
