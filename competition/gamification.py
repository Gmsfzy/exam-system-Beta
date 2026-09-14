# -*- coding: utf-8 -*-
"""竞技化服务层：竞技积分 / 段位 / 勋章 / 结算
规则：
- 段位由积分实时推导（不入库，避免漂移）
- PK 积分在对战结算时即时入账（与结算同事务）
- 限时赛积分在竞赛结束后按最终名次统一结算（兜底扫描，CAS 幂等）
"""
from sqlalchemy.exc import IntegrityError
from database import db
from utils.timeutil import utcnow, season_of
from utils.timeutil import current_season as _current_season
from competition.models import (
    Competition, CompetitionParticipant, PkBattle, PkBattleStatusEnum,
    ParticipantStatusEnum, UserPointsProfile, UserBadge,
    CompetitionStatusEnum,
)
from competition.leaderboard import get_leaderboard
from competition.realtime import notify_user


# ═══════════════ 段位定义 ═══════════════
# (名称, 达到该段位所需最低积分)；王者无上限
TIERS = [
    ('青铜', 0),
    ('白银', 100),
    ('黄金', 250),
    ('铂金', 450),
    ('钻石', 700),
    ('王者', 1000),
]

TIER_COLORS = {
    '青铜': '#b08d57', '白银': '#a8b4c4', '黄金': '#f0c14b',
    '铂金': '#7fd8d8', '钻石': '#7db9f5', '王者': '#ff7a45',
}


def tier_of(points):
    """积分 -> 段位名称"""
    tier = TIERS[0][0]
    for name, floor in TIERS:
        if points >= floor:
            tier = name
    return tier


def tier_progress(points):
    """段位进度信息：当前段位/积分/下一档位/所需积分/进度百分比"""
    tier = tier_of(points)
    idx = next(i for i, (name, _) in enumerate(TIERS) if name == tier)
    next_tier, next_at = (None, None)
    if idx + 1 < len(TIERS):
        next_tier, next_at = TIERS[idx + 1]
    percent = 100
    if next_at is not None:
        cur_floor = TIERS[idx][1]
        span = next_at - cur_floor
        percent = min(100, round((points - cur_floor) / span * 100))
    return {
        'tier': tier,
        'tier_color': TIER_COLORS[tier],
        'points': points,
        'next_tier': next_tier,
        'next_at': next_at,
        'percent': percent,
    }


# ═══════════════ 勋章定义 ═══════════════
# code -> {name, description, icon(emoji), season 型勋章在归档时直接授予}
BADGE_DEFS = {
    'first_pk_win':    {'name': '首战告捷', 'description': '首次在 1v1 PK 对战中获胜', 'icon': '🥇'},
    'pk_streak_3':     {'name': '三连胜',   'description': 'PK 对战达成 3 连胜',       'icon': '🔥'},
    'pk_streak_5':     {'name': '五连王者', 'description': 'PK 对战达成 5 连胜',       'icon': '👑'},
    'timed_finish_10': {'name': '身经百战', 'description': '限时积分赛累计完赛 10 场',  'icon': '🎖️'},
    'perfect_score':   {'name': '一战封神', 'description': '限时积分赛取得单场满分',    'icon': '💯'},
    'season_top3':     {'name': '季度巅峰', 'description': '赛季结算时全校排名前三',    'icon': '🏆'},
    'team_found':      {'name': '开疆辟土', 'description': '创建了自己的战队',          'icon': '🛡️'},
}


def badge_payload(code, season='', related_id=None):
    d = BADGE_DEFS[code]
    return {'code': code, 'name': d['name'], 'description': d['description'],
            'icon': d['icon'], 'season': season, 'related_id': related_id}


def _grant(user_id, code, season='', related_id=None):
    """插入勋章（幂等）；返回是否新发放。
    唯一约束 (user_id, badge_code, season) 兜底：并发发放时 IntegrityError → 视为已存在
    """
    exists = UserBadge.query.filter_by(
        user_id=user_id, badge_code=code, season=season).first()
    if exists:
        return False
    db.session.add(UserBadge(
        user_id=user_id, badge_code=code, season=season, related_id=related_id))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return False  # 并发已被其他请求发放
    return True


def _pk_win_count(user_id):
    return PkBattle.query.filter(
        PkBattle.status == PkBattleStatusEnum.FINISHED,
        PkBattle.winner_id == user_id).count()


def _timed_finish_count(user_id):
    return CompetitionParticipant.query.filter_by(
        user_id=user_id, status=ParticipantStatusEnum.FINISHED).count()


def check_and_grant(user_id, triggers, season='', related_id=None):
    """按触发器聚合校验并发放勋章（不 commit，由调用方提交）
    triggers ⊆ {'first_pk_win','pk_streak_3','pk_streak_5','timed_finish_10','perfect_score'}
    返回新发放的勋章 payload 列表
    """
    granted = []

    def _try(code, cond):
        if cond and _grant(user_id, code, season, related_id):
            granted.append(badge_payload(code, season, related_id))

    profile = ensure_profile(user_id, season)
    for code in triggers:
        if code == 'first_pk_win':
            _try(code, _pk_win_count(user_id) >= 1)
        elif code == 'pk_streak_3':
            _try(code, profile.streak >= 3)
        elif code == 'pk_streak_5':
            _try(code, profile.streak >= 5)
        elif code == 'timed_finish_10':
            _try(code, _timed_finish_count(user_id) >= 10)
        elif code == 'perfect_score':
            _try(code, _has_perfect_score(user_id))
        elif code == 'team_found':
            _try(code, True)  # 事件驱动：调用即触发
    return granted


def _has_perfect_score(user_id):
    row = (db.session.query(CompetitionParticipant.id)
           .join(Competition, Competition.id == CompetitionParticipant.competition_id)
           .filter(
               CompetitionParticipant.user_id == user_id,
               CompetitionParticipant.status == ParticipantStatusEnum.FINISHED,
               Competition.total_score > 0,
               CompetitionParticipant.score == Competition.total_score,
           ).first())
    return row is not None


# ═══════════════ 赛季与档案 ═══════════════

def current_season():
    """当前赛季键（本地日历月 'YYYY-MM'），委托 utils.timeutil"""
    return _current_season()


def ensure_profile(user_id, season=None):
    """获取/创建当前赛季档案（赛季重置 = 新月自动建空行）
    唯一约束 (user_id, season) 兜底：并发创建时 IntegrityError → 回退查询
    """
    season = season or current_season()
    p = UserPointsProfile.query.filter_by(user_id=user_id, season=season).first()
    if p is not None:
        return p
    p = UserPointsProfile(user_id=user_id, season=season)
    db.session.add(p)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        p = UserPointsProfile.query.filter_by(user_id=user_id, season=season).first()
    return p


def season_rank_of(user_id, season=None):
    """用户在指定赛季的排名（实时口径：points desc, last_played_at asc，同分同名次）"""
    season = season or current_season()
    rows = (UserPointsProfile.query
            .filter(UserPointsProfile.season == season)
            .order_by(UserPointsProfile.points.desc(),
                      UserPointsProfile.last_played_at.asc())
            .all())
    if not rows:
        return None
    prev_key, rank = None, 0
    for i, r in enumerate(rows, start=1):
        key = (r.points, r.last_played_at)
        if key != prev_key:
            rank, prev_key = i, key
        if r.user_id == user_id:
            return rank
    return None


# ═══════════════ PK 积分结算（即时） ═══════════════

def award_pk_result(battle):
    """PK 结算发积分：胜 25+连胜加成 / 平 10 / 负 5（保底）
    在 _settle_battle 主事务内调用（不 commit）；返回 {user_id: {...}} 供推送
    """
    season = season_of(battle.started_at) if battle.started_at else current_season()
    results = {}

    def _apply(uid, outcome, final_score):
        p = ensure_profile(uid, season)
        old_tier = tier_of(p.points)
        before_streak = p.streak
        if outcome == 'win':
            gained = 25 + min(before_streak, 5) * 2
            p.pk_win += 1
            p.streak += 1
        elif outcome == 'draw':
            gained = 10
            p.pk_draw += 1
        else:
            gained = 5
            p.pk_lose += 1
            p.streak = 0
        p.max_streak = max(p.max_streak, p.streak)
        p.points += gained
        p.last_played_at = utcnow()
        results[uid] = {
            'gained': gained,
            'final_score': final_score,
            'before_tier': old_tier,
            'profile': p,
        }

    challenger_score = float(battle.challenger_score or 0)
    opponent_score = float(battle.opponent_score or 0)
    if battle.winner_id is None:
        _apply(battle.challenger_id, 'draw', challenger_score)
        if battle.opponent_id:
            _apply(battle.opponent_id, 'draw', opponent_score)
    else:
        loser_id = battle.opponent_id if battle.winner_id == battle.challenger_id \
            else battle.challenger_id
        _apply(battle.winner_id, 'win',
               challenger_score if battle.winner_id == battle.challenger_id else opponent_score)
        _apply(loser_id, 'lose',
               opponent_score if battle.winner_id == battle.challenger_id else challenger_score)

    # 勋章校验（基于加分后的状态）
    for uid, info in results.items():
        triggers = {'first_pk_win'}
        p = info['profile']
        if p.streak >= 3:
            triggers.add('pk_streak_3')
        if p.streak >= 5:
            triggers.add('pk_streak_5')
        info['granted'] = check_and_grant(uid, triggers, season=season)
    return results


# ═══════════════ 限时赛积分结算（ENDED 后统一） ═══════════════

def _rank_points(rank):
    if rank == 1:
        return 40
    if rank == 2:
        return 30
    if rank == 3:
        return 20
    if 4 <= rank <= 10:
        return 10
    return 5


def award_timed_competition(comp):
    """竞赛结束后按最终名次统一结算积分（幂等：points_settled CAS）
    返回 {user_id: {...}}；无参与者/已结算返回 None
    """
    rowcount = db.session.execute(
        db.text('UPDATE competition SET points_settled = 1 '
                'WHERE id = :cid AND points_settled = 0'),
        {'cid': comp.id}).rowcount
    db.session.commit()
    if rowcount != 1:
        return None

    season = season_of(comp.end_time) if comp.end_time else current_season()
    board = get_leaderboard(comp.id, limit=10000)
    total_score = float(comp.total_score or 0)
    multiplayer = len(board) >= 2  # 单人参赛不发名次分
    results = {}
    for entry in board:
        uid = entry['user_id']
        p = ensure_profile(uid, season)
        old_tier = tier_of(p.points)
        gained = 5  # 参与分
        if entry['status'] == ParticipantStatusEnum.FINISHED:
            perf = round(float(entry['score'] or 0) / total_score * 30) if total_score > 0 else 0
            gained = 5 + min(perf, 30)
            if multiplayer:
                gained += _rank_points(entry['rank'])
            if total_score > 0 and float(entry['score'] or 0) >= total_score:
                gained += 10
            p.timed_finished += 1
        p.points += gained
        p.last_played_at = utcnow()
        results[uid] = {'gained': gained, 'before_tier': old_tier, 'profile': p}

    for uid, info in results.items():
        triggers = {'timed_finish_10', 'perfect_score'}
        info['granted'] = check_and_grant(uid, triggers, season=season)
    db.session.commit()

    for uid, info in results.items():
        _notify_profile_update(uid, info)
    return results


def _notify_profile_update(user_id, info):
    """积分/段位变化推送（socket 不可用时静默）"""
    p = info['profile']
    progress = tier_progress(p.points)
    payload = {
        'reason': info.get('reason', 'competition'),
        'gained': info['gained'],
        'points': p.points,
        'tier': progress['tier'],
        'tier_changed': progress['tier'] != info['before_tier'],
        'old_tier': info['before_tier'],
        'granted_badges': info.get('granted', []),
    }
    notify_user(user_id, 'profile_update', payload)
    for badge in info.get('granted', []):
        notify_user(user_id, 'badge_granted', badge)


# ═══════════════ 待结算竞赛兜底扫描 ═══════════════

def settle_pending_competitions():
    """扫描已过期但未结算积分的竞赛统一结算
    在段位/战队/画像等读接口入口调用；幂等
    """
    now = utcnow()
    pendings = Competition.query.filter(
        Competition.end_time.isnot(None),
        Competition.end_time < now,
        Competition.status != CompetitionStatusEnum.DRAFT,
    ).all()
    for comp in pendings:
        comp.sync_status()  # 归档答题中参与者（幂等）
        try:
            award_timed_competition(comp)
        except Exception:
            db.session.rollback()  # 单场失败不影响其余
