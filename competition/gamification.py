# -*- coding: utf-8 -*-
"""竞技化服务层：竞技积分 / 段位 / 勋章 / 结算
规则：
- 段位由积分实时推导（不入库，避免漂移）
- PK 积分在对战结算时即时入账（与结算同事务）
- 限时赛积分在竞赛结束后按最终名次统一结算（兜底扫描，CAS 幂等）
"""
from sqlalchemy.exc import IntegrityError
from database import db
from utils.timeutil import utcnow, season_of, local_today
from utils.timeutil import current_season as _current_season
from competition.models import (
    Competition, CompetitionParticipant, PkBattle, PkBattleStatusEnum,
    ParticipantStatusEnum, UserPointsProfile, UserBadge,
    CompetitionStatusEnum, ArenaRating, PointsHistory,
)
from competition.leaderboard import get_leaderboard
from ledger import core as ledger
from competition.realtime import notify_user


# ═══════════════ 段位定义 ═══════════════
# (名称, 达到该段位所需最低积分, 排名百分位要求|None)
# 百分位要求：需同时满足「积分门槛」与「赛季排名前 X%」才能定档（对标 Kaggle 相对位置晋升）。
# 赛季参与人数 < MIN_RANK_PLAYERS 时忽略百分位、只认门槛（解决人少时人人都能封王）。
MIN_RANK_PLAYERS = 20
TIERS = [
    ('青铜', 0, None),
    ('白银', 100, None),
    ('黄金', 250, None),
    ('铂金', 450, 0.50),   # 需赛季前 50%
    ('钻石', 700, 0.15),   # 需赛季前 15%
    ('星耀', 900, 0.07),   # 需赛季前 7%
    ('王者', 1200, 0.03),  # 需赛季前 3%（门槛抬高）
]

TIER_COLORS = {
    '青铜': '#b08d57', '白银': '#a8b4c4', '黄金': '#f0c14b',
    '铂金': '#7fd8d8', '钻石': '#7db9f5', '星耀': '#c084fc', '王者': '#ff7a45',
}

# 无百分位要求的最高基准档（黄金）索引：排名不达标时最低也只保到这一档
_BASELINE_IDX = max(i for i, t in enumerate(TIERS) if t[2] is None)


# ═══════════════ 赛季证书等级（按最终积分分档，复用段位积分锚点）═══════════════
# (达到该等级所需最低积分, 等级码, 等级名)
CERT_GRADES = [
    (700, 'gold', '金奖'),
    (450, 'silver', '银奖'),
    (250, 'bronze', '铜奖'),
    (1, 'merit', '纪念奖'),
]


def cert_grade(points):
    """赛季最终积分 -> (等级码, 等级名)；积分 <=0 不发（返回 None）。"""
    points = int(points or 0)
    if points <= 0:
        return None
    for floor, code, label in CERT_GRADES:
        if points >= floor:
            return code, label
    return None


def tier_of(points, rank=None, total=None):
    """积分 + （可选）赛季排名 -> 段位名称。
    传入 rank/total 且 total>=MIN_RANK_PLAYERS 时启用百分位封顶，最终档 = min(门槛档, 百分位档)。
    """
    floor_idx = 0
    for i, (_n, floor, _tp) in enumerate(TIERS):
        if points >= floor:
            floor_idx = i
    if rank is not None and total is not None and total >= MIN_RANK_PLAYERS and rank >= 1:
        ratio = rank / total
        pct_idx = _BASELINE_IDX  # 排名不达标时只保到基准档
        for i, (_n, _f, tp) in enumerate(TIERS):
            if tp is not None and ratio <= tp:
                pct_idx = i
        final_idx = min(floor_idx, pct_idx)
    else:
        final_idx = floor_idx
    return TIERS[final_idx][0]


def tier_progress(points, rank=None, total=None):
    """段位进度：当前段位/积分/下一档/门槛/进度百分比 + 是否被排名百分位封顶"""
    tier = tier_of(points, rank, total)
    idx = next(i for i, (name, _, _) in enumerate(TIERS) if name == tier)
    next_tier, next_at, next_tp = (None, None, None)
    if idx + 1 < len(TIERS):
        next_tier, next_at, next_tp = TIERS[idx + 1]
    percent = 100
    if next_at is not None:
        cur_floor = TIERS[idx][1]
        span = next_at - cur_floor
        percent = min(100, round((points - cur_floor) / span * 100))
    # gated：积分已够上档位，但因排名未达百分位而被封顶
    gated = False
    if next_tier is not None and next_tp is not None and total is not None \
            and total >= MIN_RANK_PLAYERS and points >= next_at:
        ratio = (rank or total) / total
        if ratio > next_tp:
            gated = True
    return {
        'tier': tier,
        'tier_color': TIER_COLORS[tier],
        'points': points,
        'next_tier': next_tier,
        'next_at': next_at,
        'next_rank_top_pct': (round(next_tp * 100) if next_tp is not None else None),
        'percent': percent,
        'gated': gated,
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
    # 学习闭环徽章（api.learning_engine.grant_learning_badges 触发）
    'study_streak_7':   {'name': '七日之约', 'description': '连续打卡学习 7 天',        'icon': '📅'},
    'study_streak_21':  {'name': '三周不辍', 'description': '连续打卡学习 21 天',       'icon': '⛓️'},
    'first_certificate': {'name': '学以致用', 'description': '获得首张学习路径结业证书', 'icon': '📜'},
    'first_path_complete': {'name': '首程抵达', 'description': '完整掌握首条学习路径',   'icon': '🏁'},
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
    triggers ⊆ {'first_pk_win','pk_streak_3','pk_streak_5','timed_finish_10','perfect_score',
                'team_found','study_streak_7','study_streak_21','first_certificate','first_path_complete'}
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
        elif code in _LEARNING_BADGE_CODES:
            _try(code, _learning_cond(user_id, code))
    return granted


# 学习闭环徽章：条件校验延迟导入，避免与 api 层循环依赖
_LEARNING_BADGE_CODES = ('study_streak_7', 'study_streak_21',
                         'first_certificate', 'first_path_complete')


def _learning_cond(user_id, code):
    db.session.flush()  # 让调用方事务内未提交的变更对下面的查询可见
    if code in ('study_streak_7', 'study_streak_21'):
        from api.learning_engine import compute_streak
        need = 7 if code == 'study_streak_7' else 21
        return compute_streak(user_id) >= need
    if code == 'first_certificate':
        from database.models import PathCertificate
        return PathCertificate.query.filter_by(user_id=user_id).count() >= 1
    if code == 'first_path_complete':
        from database.models import UserPathEnrollment
        return UserPathEnrollment.query.filter_by(
            user_id=user_id, status='completed').count() >= 1
    return False


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


def _tier_ctx(user_id, season):
    """返回 (rank, total)，供段位百分位封顶使用；无档案时 (None, 0)"""
    rank = season_rank_of(user_id, season)
    total = UserPointsProfile.query.filter_by(season=season).count()
    return rank, total


# ═══════════════ 对战等级分 Elo（跨赛季持久） ═══════════════

def is_bot_user(user_id):
    """机器人（训练对手）判定：不参与积分/排行/Elo/历史入账"""
    from database.models import User, RoleEnum
    u = db.session.get(User, user_id)
    return u is not None and u.role == RoleEnum.BOT


def get_or_create_rating(user_id):
    r = db.session.get(ArenaRating, user_id)
    if r is None:
        r = ArenaRating(user_id=user_id, elo=1200, peak_elo=1200)
        db.session.add(r)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            r = db.session.get(ArenaRating, user_id)
    return r


def _expected(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def apply_elo(battle, winner_id, is_draw):
    """对真人双方更新 Elo（K=32，双方总场次>=25 时 K=24）。
    机器人对战不参与 Elo。返回 {user_id: delta}；写回 battle.delta_*。
    在调用方事务内执行（不 commit）。
    """
    if battle.is_bot:
        return {}
    c_id, o_id = battle.challenger_id, battle.opponent_id
    if not o_id or is_bot_user(c_id) or is_bot_user(o_id):
        return {}
    rc, ro = get_or_create_rating(c_id), get_or_create_rating(o_id)
    k = 32 if (rc.games + ro.games) < 25 else 24
    ec, eo = _expected(rc.elo, ro.elo), _expected(ro.elo, rc.elo)
    if is_draw:
        sc = so = 0.5
    elif winner_id == c_id:
        sc, so = 1.0, 0.0
    else:
        sc, so = 0.0, 1.0
    dc = round(k * (sc - ec))
    do = round(k * (so - eo))
    rc.elo += dc
    ro.elo += do
    rc.games += 1
    ro.games += 1
    rc.peak_elo = max(rc.peak_elo, rc.elo)
    ro.peak_elo = max(ro.peak_elo, ro.elo)
    rc.updated_at = ro.updated_at = utcnow()
    battle.delta_challenger = dc
    battle.delta_opponent = do
    return {c_id: dc, o_id: do}


# ═══════════════ 积分历史快照 ═══════════════

def upsert_points_history(user_id, season, points, elo=None):
    """按天 upsert 当前赛季积分/Elo 快照（同一天覆盖为最新值）。"""
    if is_bot_user(user_id):
        return
    day = local_today().isoformat()   # 快照按上海日历日切（与 season 的本地月口径一致）
    elo_val = elo if elo is not None else get_or_create_rating(user_id).elo
    row = PointsHistory.query.filter_by(user_id=user_id, season=season, day=day).first()
    if row is None:
        row = PointsHistory(user_id=user_id, season=season, day=day)
        db.session.add(row)
    row.points = int(points)
    row.elo = int(elo_val)
    row.updated_at = utcnow()


# ═══════════════ PK 积分结算（即时） ═══════════════

def award_pk_result(battle):
    """PK 结算：真人发积分（胜 25+连胜加成 / 平 10 / 负 5）+ Elo 更新；机器人不计分。
    在 _settle_battle 主事务内调用（不 commit）；返回 {user_id: {...}} 供推送
    """
    season = season_of(battle.started_at) if battle.started_at else current_season()
    results = {}

    def _apply(uid, outcome, final_score):
        if uid is None or is_bot_user(uid):
            return
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
        ledger.post(uid, 'points', gained, 'battle', scope=season, ref_type='pk',
                    ref_id=battle.id, memo='PK 对战结算')
        p.last_played_at = utcnow()
        results[uid] = {
            'gained': gained,
            'final_score': final_score,
            'before_tier': old_tier,
            'season': season,
            'profile': p,
        }

    challenger_score = float(battle.challenger_score or 0)
    opponent_score = float(battle.opponent_score or 0)
    is_draw = battle.winner_id is None
    if is_draw:
        _apply(battle.challenger_id, 'draw', challenger_score)
        _apply(battle.opponent_id, 'draw', opponent_score)
    else:
        loser_id = battle.opponent_id if battle.winner_id == battle.challenger_id \
            else battle.challenger_id
        _apply(battle.winner_id, 'win',
               challenger_score if battle.winner_id == battle.challenger_id else opponent_score)
        _apply(loser_id, 'lose',
               opponent_score if battle.winner_id == battle.challenger_id else challenger_score)

    # Elo：真人双方更新，并将增量回写到结果供推送/战报
    elo_deltas = apply_elo(battle, battle.winner_id, is_draw)
    for uid, d in elo_deltas.items():
        if uid in results:
            results[uid]['elo_delta'] = d
            results[uid]['elo'] = get_or_create_rating(uid).elo
    # 积分历史快照（真人）
    for uid, info in results.items():
        upsert_points_history(uid, season, info['profile'].points, info.get('elo'))

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
        ledger.post(uid, 'points', gained, 'settle', scope=season, ref_type='competition',
                    ref_id=comp.id, memo='限时赛名次结算')
        p.last_played_at = utcnow()
        results[uid] = {'gained': gained, 'before_tier': old_tier,
                        'season': season, 'profile': p}

    for uid, info in results.items():
        triggers = {'timed_finish_10', 'perfect_score'}
        info['granted'] = check_and_grant(uid, triggers, season=season)
        upsert_points_history(uid, season, info['profile'].points)
    db.session.commit()

    for uid, info in results.items():
        _notify_profile_update(uid, info)
    return results


def _notify_profile_update(user_id, info):
    """积分/段位变化推送（含排名百分位封顶与 Elo 增减；socket 不可用时静默）"""
    p = info['profile']
    season = info.get('season') or current_season()
    rank, total = _tier_ctx(user_id, season)
    progress = tier_progress(p.points, rank, total)
    old_points = p.points - info['gained']
    payload = {
        'reason': info.get('reason', 'competition'),
        'gained': info['gained'],
        'points': p.points,
        'tier': progress['tier'],
        'tier_changed': progress['tier'] != tier_of(old_points, rank, total),
        'old_tier': info.get('before_tier'),
        'elo_delta': info.get('elo_delta'),
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
