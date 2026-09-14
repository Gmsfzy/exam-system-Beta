"""1v1 PK 对战 API"""
import json
from datetime import timedelta

from flask import Blueprint, request, jsonify

from database import db
from database.models import User
from utils.timeutil import utcnow, iso_local
from utils.security import verify_token
from competition.models import (
    Competition, CompetitionQuestion, PkBattle, PkAnswer, PkBattleStatusEnum,
    CompetitionStatusEnum
)
from competition.scoring import parse_scoring_rule, grade_objective, calc_question_score
from competition.realtime import (
    notify_battle_update, notify_battle_end, notify_battle_accepted
)

pk_bp = Blueprint('pk_battle', __name__)

# WAITING 挑战超过该时长无人接受则自动作废（不再阻塞发起人、不再出现在大厅）
WAITING_EXPIRE_SECONDS = 30 * 60


def _expire_stale_waiting():
    """把超时未被接受的 WAITING 挑战批量置为 CANCELLED（从未开战即作废）。"""
    deadline = utcnow() - timedelta(seconds=WAITING_EXPIRE_SECONDS)
    PkBattle.query.filter(
        PkBattle.status == PkBattleStatusEnum.WAITING,
        PkBattle.created_at < deadline,
    ).update({
        'status': PkBattleStatusEnum.CANCELLED,
        'finished_at': utcnow(),
    }, synchronize_session=False)
    db.session.commit()


def _is_cancelled(battle):
    """已作废的对战：显式 CANCELLED，或从未开战（未接受就过期/置 FINISHED）"""
    if battle.status == PkBattleStatusEnum.CANCELLED:
        return True
    return battle.status == PkBattleStatusEnum.FINISHED and battle.started_at is None


def _require_student():
    user = verify_token()
    if not user or not user.is_student():
        return None, (jsonify({'message': '无权访问'}), 403)
    return user, None


def _get_battle(battle_id):
    battle = db.session.get(PkBattle, battle_id)
    if not battle:
        return None, (jsonify({'message': '对战不存在'}), 404)
    return battle, None


def _player_role(battle, user_id):
    """返回 'challenger' / 'opponent' / None"""
    if battle.challenger_id == user_id:
        return 'challenger'
    if battle.opponent_id == user_id:
        return 'opponent'
    return None


def _settle_battle(battle, now=None):
    """惰性结算：双方完成或超时后决出胜负（分高者胜，同分先完成者胜）

    CAS 抢结算权：lobby/state/answer/finish 多入口都会触发结算，
    并发时仅一个请求能将 status 从 playing 原子置为 finished（rowcount=1），
    后续积分发放因此只执行一次；积分发放后在本函数内 commit，
    调用方（尤其 api_pk_lobby）无需再补 commit。
    """
    if battle.status != PkBattleStatusEnum.PLAYING:
        return False
    now = now or utcnow()
    comp = battle.competition
    deadline = battle.started_at + timedelta(minutes=comp.duration) if battle.started_at else None
    both_done = battle.challenger_finished_at and battle.opponent_finished_at
    timed_out = deadline and now >= deadline

    if not (both_done or timed_out):
        return False

    # CAS：仅当 status 仍为 playing 时才授予结算权（与 award_timed_competition 的
    # points_settled CAS 同思路，防止并发重复发积分）
    claimed = PkBattle.query.filter(
        PkBattle.id == battle.id,
        PkBattle.status == PkBattleStatusEnum.PLAYING,
    ).update({'status': PkBattleStatusEnum.FINISHED}, synchronize_session=False)
    db.session.commit()
    if claimed != 1:
        return False  # 已被其他请求抢先结算

    # commit 后对象已过期，以下访问会从库里重载 FINISHED 状态
    battle.challenger_score = round(sum(
        a.gained_score for a in battle.answers if a.player_id == battle.challenger_id), 2)
    if battle.opponent_id:
        battle.opponent_score = round(sum(
            a.gained_score for a in battle.answers if a.player_id == battle.opponent_id), 2)

    if battle.challenger_score > battle.opponent_score:
        battle.winner_id = battle.challenger_id
    elif battle.opponent_score > battle.challenger_score:
        battle.winner_id = battle.opponent_id
    else:
        # 同分：先完成者胜；都未记录完成时间则平局（winner 为空）
        c_ft = battle.challenger_finished_at
        o_ft = battle.opponent_finished_at
        if c_ft and o_ft:
            battle.winner_id = battle.challenger_id if c_ft <= o_ft else battle.opponent_id
        elif c_ft:
            battle.winner_id = battle.challenger_id
        elif o_ft:
            battle.winner_id = battle.opponent_id

    battle.finished_at = now
    db.session.commit()

    # 竞技积分/段位/勋章结算；在本函数内提交，避免 lobby 等不 commit 的调用路径丢积分
    from competition.gamification import award_pk_result, _notify_profile_update
    results = {}
    try:
        results = award_pk_result(battle)
        db.session.commit()
    except Exception:
        db.session.rollback()  # 积分失败不影响对战结果
        results = {}
    for uid, info in results.items():
        _notify_profile_update(uid, {**info, 'reason': 'pk'})

    notify_battle_end(battle)
    return True


def _battle_state_payload(battle, user):
    role = _player_role(battle, user.id)
    is_player = role is not None
    comp = battle.competition
    data = {
        'battle': battle.to_dict(),
        'role': role,
        'competition': {
            'id': comp.id, 'title': comp.title, 'duration': comp.duration,
            'total_score': comp.total_score,
        },
        'is_player': is_player,
    }

    if battle.status == PkBattleStatusEnum.WAITING:
        data['message'] = '等待对手接受挑战...'
        return data

    if battle.status == PkBattleStatusEnum.CANCELLED:
        data['message'] = '挑战已过期作废'
        return data

    if battle.status == PkBattleStatusEnum.FINISHED:
        winner_name = None
        if battle.winner_id:
            winner = db.session.get(User, battle.winner_id)
            winner_name = winner.username if winner else None
        data['winner'] = winner_name
        return data

    # playing：下发题目（无答案）+ 我的已答记录
    now = utcnow()
    deadline = battle.started_at + timedelta(minutes=comp.duration)
    data['remaining_seconds'] = max(0, int((deadline - now).total_seconds()))

    my_answered = {a.cq_id: {
        'answer': a.answer, 'is_correct': a.is_correct, 'gained_score': a.gained_score,
    } for a in battle.answers if a.player_id == user.id}

    questions = []
    for cq in sorted(comp.questions, key=lambda x: x.order):
        item = cq.to_public_dict()
        if cq.id in my_answered:
            item['student_answer'] = my_answered[cq.id]['answer']
            item['is_correct'] = my_answered[cq.id]['is_correct']
            item['gained_score'] = my_answered[cq.id]['gained_score']
        questions.append(item)
    data['questions'] = questions
    return data


@pk_bp.route('/competitions/<int:comp_id>/pk', methods=['POST'])
def api_create_pk(comp_id):
    """发起 1v1 挑战"""
    user, err = _require_student()
    if err:
        return err
    comp = db.session.get(Competition, comp_id)
    if not comp:
        return jsonify({'message': '竞赛不存在'}), 404
    comp.sync_status()
    db.session.commit()
    if comp.status != CompetitionStatusEnum.ONGOING:
        return jsonify({'message': '仅进行中的竞赛可发起PK'}), 400
    if not comp.allow_pk:
        return jsonify({'message': '该竞赛未开放PK对战'}), 400

    _expire_stale_waiting()
    existing = PkBattle.query.filter_by(
        challenger_id=user.id, competition_id=comp_id,
        status=PkBattleStatusEnum.WAITING).first()
    if existing:
        return jsonify({'message': '您已有等待中的挑战', 'battle_id': existing.id})

    battle = PkBattle(competition_id=comp_id, challenger_id=user.id)
    db.session.add(battle)
    db.session.commit()
    return jsonify({'message': '挑战已创建，等待对手接受', 'battle_id': battle.id})


@pk_bp.route('/pk/lobby', methods=['GET'])
def api_pk_lobby():
    """PK 大厅：等待中的挑战 + 我的相关对战"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    _expire_stale_waiting()

    waiting = []
    for b in PkBattle.query.filter_by(status=PkBattleStatusEnum.WAITING) \
            .order_by(PkBattle.created_at.desc()).limit(50).all():
        if b.competition is None:
            continue  # 竞赛已删除的残留挑战不下发
        waiting.append({
            'id': b.id,
            'challenger': b.challenger.username,
            'competition_title': b.competition.title,
            'question_count': len(b.competition.questions),
            'duration': b.competition.duration,
            'total_score': b.competition.total_score,
            'is_mine': b.challenger_id == user.id,
            'created_at': iso_local(b.created_at),
        })

    mine = []
    battles = PkBattle.query.filter(
        (PkBattle.challenger_id == user.id) | (PkBattle.opponent_id == user.id)
    ).order_by(PkBattle.created_at.desc()).limit(50).all()
    for b in battles:
        if _is_cancelled(b):
            continue  # 未开战即作废的挑战不进入"我的对战"列表
        if b.status == PkBattleStatusEnum.PLAYING:
            _settle_battle(b)
        item = b.to_dict()
        item['competition_title'] = b.competition.title if b.competition else ''
        item['result'] = None
        if b.status == PkBattleStatusEnum.FINISHED:
            if not b.winner_id:
                item['result'] = 'draw'
            elif b.winner_id == user.id:
                item['result'] = 'win'
            else:
                item['result'] = 'lose'
        mine.append(item)

    return jsonify({'waiting': waiting, 'mine': mine})


@pk_bp.route('/pk/<int:battle_id>/accept', methods=['POST'])
def api_accept_pk(battle_id):
    """接受挑战：双方立即进入对战"""
    user, err = _require_student()
    if err:
        return err
    _expire_stale_waiting()
    battle, err = _get_battle(battle_id)
    if err:
        return err
    if battle.status != PkBattleStatusEnum.WAITING:
        return jsonify({'message': '该挑战已被接受或已结束'}), 400
    if battle.challenger_id == user.id:
        return jsonify({'message': '不能接受自己的挑战'}), 400

    battle.opponent_id = user.id
    battle.status = PkBattleStatusEnum.PLAYING
    battle.started_at = utcnow()
    db.session.commit()
    notify_battle_accepted(battle)
    notify_battle_update(battle)
    return jsonify({'message': '对战开始', 'battle_id': battle.id})


@pk_bp.route('/pk/<int:battle_id>/state', methods=['GET'])
def api_pk_state(battle_id):
    """对战状态恢复 / 轮询"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    battle, err = _get_battle(battle_id)
    if err:
        return err
    role = _player_role(battle, user.id)
    if not role:
        return jsonify({'message': '您不是该对战的参与者'}), 403
    if battle.status == PkBattleStatusEnum.PLAYING:
        _settle_battle(battle)
    db.session.commit()
    return jsonify(_battle_state_payload(battle, user))


@pk_bp.route('/pk/<int:battle_id>/answer', methods=['POST'])
def api_pk_answer(battle_id):
    """PK 逐题作答：即时判分并实时推送双方进度"""
    user, err = _require_student()
    if err:
        return err
    battle, err = _get_battle(battle_id)
    if err:
        return err
    role = _player_role(battle, user.id)
    if not role:
        return jsonify({'message': '您不是该对战的参与者'}), 403
    if battle.status != PkBattleStatusEnum.PLAYING:
        return jsonify({'message': '对战已结束', 'finished': True}), 400

    # 超时自动结算
    if _settle_battle(battle):
        db.session.commit()
        return jsonify({'message': '对战时间已结束', 'finished': True}), 400

    data = request.get_json() or {}
    cq_id = data.get('cq_id')
    answer_text = str(data.get('answer') or '')

    cq = CompetitionQuestion.query.filter_by(
        id=cq_id, competition_id=battle.competition_id).first()
    if not cq:
        return jsonify({'message': '题目不存在'}), 404
    existing = PkAnswer.query.filter_by(
        battle_id=battle.id, player_id=user.id, cq_id=cq.id).first()
    if existing:
        return jsonify({'message': '该题已作答'}), 400

    comp = battle.competition
    per_q = comp.per_question_seconds_for(len(comp.questions))
    # 服务端计算单题用时：距己方上一题作答（或对战开始）的时间差，客户端上报值不可信
    now = utcnow()
    last_event = battle.started_at or now
    last_answered = db.session.query(db.func.max(PkAnswer.answered_at)).filter(
        PkAnswer.battle_id == battle.id, PkAnswer.player_id == user.id,
        PkAnswer.answered_at.isnot(None)).scalar()
    if last_answered and last_answered > last_event:
        last_event = last_answered
    time_spent = min(int(max(0.0, (now - last_event).total_seconds())), per_q * 2)

    is_correct = grade_objective(cq.q_type, answer_text, cq.answer)
    base_ratio, speed_ratio = parse_scoring_rule(comp.scoring_rule)
    gained = calc_question_score(cq.score, is_correct, time_spent,
                                 per_q, base_ratio, speed_ratio)

    db.session.add(PkAnswer(
        battle_id=battle.id, player_id=user.id, cq_id=cq.id,
        answer=answer_text, is_correct=is_correct,
        gained_score=gained, time_spent=time_spent,
    ))
    if role == 'challenger':
        battle.challenger_score = round(battle.challenger_score + gained, 2)
        battle.challenger_answered += 1
    else:
        battle.opponent_score = round(battle.opponent_score + gained, 2)
        battle.opponent_answered += 1
    db.session.commit()

    notify_battle_update(battle)
    return jsonify({
        'message': '已记录',
        'is_correct': is_correct,
        'gained_score': gained,
        'total_score': battle.challenger_score if role == 'challenger' else battle.opponent_score,
        'correct_answer': cq.answer,
    })


@pk_bp.route('/pk/<int:battle_id>/finish', methods=['POST'])
def api_pk_finish(battle_id):
    """完成己方作答：对方完成或超时后自动结算"""
    user, err = _require_student()
    if err:
        return err
    battle, err = _get_battle(battle_id)
    if err:
        return err
    role = _player_role(battle, user.id)
    if not role:
        return jsonify({'message': '您不是该对战的参与者'}), 403
    if battle.status != PkBattleStatusEnum.PLAYING:
        return jsonify({'message': '对战已结束'}), 400

    now = utcnow()
    if role == 'challenger' and not battle.challenger_finished_at:
        battle.challenger_finished_at = now
    if role == 'opponent' and not battle.opponent_finished_at:
        battle.opponent_finished_at = now
    db.session.commit()

    settled = _settle_battle(battle, now)
    db.session.commit()
    notify_battle_update(battle)

    result = None
    finished = battle.status == PkBattleStatusEnum.FINISHED
    if finished:
        result = 'draw' if not battle.winner_id else (
            'win' if battle.winner_id == user.id else 'lose')
    return jsonify({
        'message': '已交卷' + ('，对战已结算' if finished else '，等待对方完成...'),
        'settled': finished,
        'result': result,
    })
