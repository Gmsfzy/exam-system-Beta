"""1v1 PK 对战 API"""
import json
import random
from datetime import timedelta

from flask import Blueprint, request, jsonify

from database import db
from database.models import User, Question
from utils.timeutil import utcnow, iso_local
from utils.security import verify_token
from competition.models import (
    Competition, CompetitionQuestion, PkBattle, PkAnswer, PkBattleStatusEnum,
    CompetitionStatusEnum
)
from competition.scoring import (
    parse_scoring_rule, grade_objective, calc_question_score,
    COMPETITION_QUESTION_TYPES,
)
from competition.realtime import (
    notify_battle_update, notify_battle_end, notify_battle_accepted
)

pk_bp = Blueprint('pk_battle', __name__)

# WAITING 挑战超过该时长无人接受则自动作废（不再阻塞发起人、不再出现在大厅）
WAITING_EXPIRE_SECONDS = 30 * 60
# 快速 PK：真人匹配窗口（秒）与允许的最大 Elo 差
QUICK_MATCH_WINDOW_SECONDS = 90
QUICK_ELO_GAP = 150
# 机器人拟真：单题人类最短反应用时（秒），用于 bot 用时与反作弊阀值一致
MIN_REACT_SECONDS = 1


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


def _advance_bot(battle, now=None, force=False):
    """快速 PK 机器人进度模拟：按已用时间（或 force 强制）为对手补写逐题作答。
    仅在 PLAYING 且 is_bot 且已写 bot_plan 时生效；返回是否有新增。
    """
    if not battle.is_bot or not battle.bot_plan or battle.status != PkBattleStatusEnum.PLAYING:
        return False
    bot_id = battle.opponent_id
    if not bot_id:
        return False
    try:
        plan = json.loads(battle.bot_plan)
    except (ValueError, TypeError):
        return False
    if not isinstance(plan, list) or not plan:
        return False
    now = now or utcnow()
    comp = battle.competition
    elapsed = (now - battle.started_at).total_seconds() if battle.started_at else 0
    cq_map = {cq.id: cq for cq in comp.questions}
    existing = {a.cq_id for a in battle.answers if a.player_id == bot_id}
    per_q = comp.per_question_seconds_for(len(comp.questions))
    base_ratio, speed_ratio = parse_scoring_rule(comp.scoring_rule)
    added = 0
    for item in plan:
        cq_id = item.get('cq_id')
        cq = cq_map.get(cq_id)
        if cq is None or cq_id in existing:
            continue
        if not force and item.get('at_sec', 0) > elapsed:
            continue
        will_correct = bool(item.get('will_correct'))
        time_spent = int(min(max(item.get('at_sec', MIN_REACT_SECONDS), MIN_REACT_SECONDS), per_q * 2))
        gained = calc_question_score(cq.score, will_correct, time_spent, per_q, base_ratio, speed_ratio)
        db.session.add(PkAnswer(
            battle_id=battle.id, player_id=bot_id, cq_id=cq_id,
            answer=(cq.answer if will_correct else '（机器人错答）'),
            is_correct=will_correct, gained_score=gained, time_spent=time_spent))
        existing.add(cq_id)
        added += 1
    if added:
        db.session.flush()
        battle.opponent_score = round(sum(
            a.gained_score for a in battle.answers if a.player_id == bot_id), 2)
        battle.opponent_answered = sum(1 for a in battle.answers if a.player_id == bot_id)
    if len(existing) >= len(plan) and not battle.opponent_finished_at:
        battle.opponent_finished_at = now
    if added:
        db.session.commit()
    return added > 0


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
    _advance_bot(battle, now)  # 先推进机器人进度（可能置 opponent_finished_at）
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
    if battle.status == PkBattleStatusEnum.PLAYING:
        _advance_bot(battle)  # 真人轮询时推进机器人分数
    data = {
        'battle': battle.to_dict(),
        'role': role,
        'sanctioned': bool(user and user.is_sanctioned),
        'competition': {
            'id': comp.id, 'title': comp.title, 'duration': comp.duration,
            'total_score': comp.total_score,
        },
        'is_player': is_player,
    }
    data['battle']['is_bot'] = battle.is_bot

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


@pk_bp.route('/pk/<int:battle_id>/replay', methods=['GET'])
def api_pk_replay(battle_id):
    """对战回放：按服务端作答时间重建双方分数随时间爬升的时间轴（仅参与者/教师可看）。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    battle, err = _get_battle(battle_id)
    if err:
        return err
    comp = battle.competition
    allowed = (battle.challenger_id == user.id or battle.opponent_id == user.id
               or user.is_teacher() or (comp is not None and comp.creator_id == user.id))
    if not allowed:
        return jsonify({'message': '无权查看该对战回放'}), 403

    started = battle.started_at
    names = {
        battle.challenger_id: battle.challenger.username if battle.challenger else str(battle.challenger_id),
        battle.opponent_id: battle.opponent.username if battle.opponent else str(battle.opponent_id),
    }
    running = {battle.challenger_id: 0.0, battle.opponent_id: 0.0}
    timeline = []
    for a in sorted(battle.answers, key=lambda x: (x.answered_at or started or utcnow())):
        side = _player_role(battle, a.player_id)
        if side is None:
            continue
        t_sec = round((a.answered_at - started).total_seconds(), 1) if (a.answered_at and started) else 0
        running[a.player_id] = round(running[a.player_id] + float(a.gained_score or 0), 2)
        timeline.append({
            't_sec': max(0, t_sec), 'side': side, 'user_id': a.player_id,
            'username': names.get(a.player_id), 'cq_id': a.cq_id,
            'is_correct': bool(a.is_correct), 'gained': round(float(a.gained_score or 0), 2),
            'running_score': running[a.player_id],
        })

    b = battle.to_dict()
    b.update({
        'winner_id': battle.winner_id,
        'winner': names.get(battle.winner_id) if battle.winner_id else None,
        'delta_challenger': battle.delta_challenger,
        'delta_opponent': battle.delta_opponent,
        'is_bot': battle.is_bot,
    })
    return jsonify({
        'battle': b,
        'competition_id': battle.competition_id,
        'duration': comp.duration if comp else 0,
        'started_at': iso_local(started),
        'timeline': timeline,
        'final': {
            'challenger_score': battle.challenger_score,
            'opponent_score': battle.opponent_score,
            'total_questions': len(comp.questions) if comp else 0,
        },
    })


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
        flagged=(time_spent < MIN_REACT_SECONDS),
        flag_reason=('fast' if time_spent < MIN_REACT_SECONDS else None),
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

    # 对机器人：真人交卷后立即把 bot 剩余题目按预定结果补齐，即时结算
    if battle.is_bot:
        _advance_bot(battle, now, force=True)

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


# ═══════════════ 快速 PK（知识点即时匹配 + 机器人填充） ═══════════════

def _quick_draw_questions(scope_type, scope_id, count):
    """按范围抽客观题 Question 对象列表；同范围不足回退全库公开客观题。"""
    base = Question.query.filter(Question.type.in_(COMPETITION_QUESTION_TYPES))
    pool = []
    if scope_type == 'chapter' and scope_id:
        pool = base.filter_by(chapter_id=scope_id).all()
    elif scope_type == 'major' and scope_id:
        pool = base.filter_by(major_id=scope_id).all()
    if len(pool) < count:
        have = {q.id for q in pool}
        extra = base.filter_by(is_public=True).all()
        pool += [q for q in extra if q.id not in have]
    if len(pool) < count:
        have = {q.id for q in pool}
        pool += [q for q in base.all() if q.id not in have]
    random.shuffle(pool)
    return pool[:count]


@pk_bp.route('/pk/quick', methods=['POST'])
def api_quick_pk():
    """快速对战：任选范围即时抽题建隐藏题源，尝试就近 Elo 匹配真人，否则进入等待。"""
    user, err = _require_student()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    scope_type = data.get('scope_type') or 'all'
    scope_id = data.get('scope_id')
    try:
        count = int(data.get('count') or 6)
    except (TypeError, ValueError):
        count = 6
    count = max(3, min(15, count))
    try:
        duration = int(data.get('duration') or 5)
    except (TypeError, ValueError):
        duration = 5
    duration = max(1, min(30, duration))

    questions = _quick_draw_questions(scope_type, scope_id, count)
    if len(questions) < 2:
        return jsonify({'message': '题库可用题目不足，暂无法开局'}), 400

    scope_label = {'chapter': '章节速赛', 'major': '专业速赛'}.get(scope_type, '综合速赛')
    now = utcnow()
    comp = Competition(
        title=f'快速对战·{scope_label}',
        description='快速对战自动生成的题源',
        competition_type='quick',
        status=CompetitionStatusEnum.ONGOING,
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(days=365),
        duration=duration,
        draw_count=0,
        allow_pk=True,
        is_quick=True,
        scoring_rule=json.dumps({'base_ratio': 0.7, 'speed_ratio': 0.3}),
        creator_id=user.id,
    )
    db.session.add(comp)
    db.session.flush()
    for i, q in enumerate(questions):
        db.session.add(CompetitionQuestion(
            competition_id=comp.id, question_id=q.id, q_type=q.type,
            content=q.content, options=q.options, answer=q.answer,
            analysis=q.analysis, score=1.0, order=i))
    comp.total_score = round(float(len(questions)), 2)
    db.session.commit()

    from competition.gamification import get_or_create_rating
    my_elo = get_or_create_rating(user.id).elo

    # 就近 Elo 匹配一个等待中的他人快速对战（同轮时长、同题数、Elo 相近）
    window_since = now - timedelta(seconds=QUICK_MATCH_WINDOW_SECONDS)
    candidates = PkBattle.query.filter(
        PkBattle.quick.is_(True),
        PkBattle.status == PkBattleStatusEnum.WAITING,
        PkBattle.challenger_id != user.id,
        PkBattle.created_at >= window_since,
    ).order_by(PkBattle.created_at.desc()).limit(20).all()
    for b in candidates:
        if b.competition is None or b.competition.duration != duration:
            continue
        if len(b.competition.questions) != len(questions):
            continue
        opp_elo = get_or_create_rating(b.challenger_id).elo
        if abs(opp_elo - my_elo) > QUICK_ELO_GAP:
            continue
        b.opponent_id = user.id
        b.status = PkBattleStatusEnum.PLAYING
        b.started_at = utcnow()
        db.session.commit()
        notify_battle_accepted(b)
        notify_battle_update(b)
        return jsonify({'battle_id': b.id, 'matched': 'human',
                        'competition_id': comp.id, 'message': '已匹配到对手，对战开始'})

    battle = PkBattle(competition_id=comp.id, challenger_id=user.id, quick=True)
    db.session.add(battle)
    db.session.commit()
    return jsonify({'battle_id': battle.id, 'matched': 'waiting',
                    'competition_id': comp.id, 'message': '正在为你寻找对手...'})


@pk_bp.route('/pk/quick/<int:battle_id>/bot', methods=['POST'])
def api_quick_bot(battle_id):
    """无人匹配时改用训练机器人填充对手，按目标 Elo 生成逐题作答计划。"""
    user, err = _require_student()
    if err:
        return err
    battle = db.session.get(PkBattle, battle_id)
    if not battle:
        return jsonify({'message': '对战不存在'}), 404
    if battle.challenger_id != user.id:
        return jsonify({'message': '仅发起人可加入机器人'}), 403
    if not battle.quick:
        return jsonify({'message': '仅快速对战可用机器人'}), 400
    if battle.status != PkBattleStatusEnum.WAITING:
        return jsonify({'message': '该对战已开始或结束'}), 400

    from database.init_data import ensure_bot_user
    from competition.gamification import get_or_create_rating, _expected
    bot = ensure_bot_user()
    comp = battle.competition
    player_elo = get_or_create_rating(user.id).elo
    bot_elo = max(600, player_elo - 40)  # 略低于玩家，保证有得打但仍具挑战
    p_correct = _expected(bot_elo, player_elo)
    per_q = comp.per_question_seconds_for(len(comp.questions))
    total_q = len(comp.questions)
    plan = []
    acc = 0.0
    for cq in sorted(comp.questions, key=lambda x: x.order):
        acc += random.uniform(0.35, 1.1) * per_q
        plan.append({
            'cq_id': cq.id,
            'will_correct': random.random() < p_correct,
            'at_sec': round(min(acc, per_q * total_q), 1),
        })
    battle.opponent_id = bot.id
    battle.is_bot = True
    battle.status = PkBattleStatusEnum.PLAYING
    battle.started_at = utcnow()
    battle.bot_plan = json.dumps(plan)
    db.session.commit()
    notify_battle_accepted(battle)
    notify_battle_update(battle)
    return jsonify({'battle_id': battle.id, 'opponent': bot.username,
                    'message': '训练对手已就绪，对战开始'})
