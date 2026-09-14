# -*- coding: utf-8 -*-
"""赛季管理：自然月赛季，惰性归档（访问时结算上赛季）
并发安全：CAS 抢锁 + 唯一约束 + 重查三重兜底
"""
from database import db
from utils.timeutil import utcnow, aware_min
from competition.models import (
    SeasonMeta, SeasonArchive, UserPointsProfile,
)
from competition.gamification import (
    tier_of, current_season, settle_pending_competitions, _grant,
)


def ensure_seasons():
    """确保当前赛季存在并归档所有过期赛季；在读接口入口调用"""
    now_key = current_season()
    meta = SeasonMeta.query.filter_by(season=now_key).first()
    if meta is None:
        db.session.add(SeasonMeta(season=now_key))
        db.session.commit()
    stale = (SeasonMeta.query
             .filter(SeasonMeta.season < now_key, SeasonMeta.archived.is_(False))
             .all())
    for m in stale:
        archive_season(m.season)


def archive_season(season):
    """归档单个赛季：预结算 -> CAS 抢锁 -> 排名快照 -> Top3 勋章"""
    # 1. 预结算该赛季内未结算的限时赛，保证快照数据完整
    settle_pending_competitions()

    # 2. CAS 抢锁：抢到才继续（SQLite 写锁串行，天然防并发）
    rowcount = db.session.execute(
        db.text('UPDATE season_meta SET archived = 1, archived_at = :at '
                'WHERE season = :s AND archived = 0'),
        {'at': utcnow(), 's': season}).rowcount
    db.session.commit()
    if rowcount != 1:
        return False  # 已被其他请求归档

    try:
        # 3. 该赛季全部档案按积分排名（同分先到者前），批量写快照
        profiles = (UserPointsProfile.query
                    .filter(UserPointsProfile.season == season)
                    .all())
        profiles.sort(key=lambda p: (-p.points, p.last_played_at or aware_min()))
        prev_key, rank = None, 0
        for i, p in enumerate(profiles, start=1):
            key = (p.points, p.last_played_at)
            if key != prev_key:
                rank, prev_key = i, key
            db.session.add(SeasonArchive(
                season=season,
                user_id=p.user_id,
                rank=rank,
                points=p.points,
                tier=tier_of(p.points),
                pk_win=p.pk_win,
                pk_total=p.pk_win + p.pk_lose + p.pk_draw,
                timed_finished=p.timed_finished,
            ))
        db.session.commit()

        # 4. 赛季 Top3 勋章
        for a in SeasonArchive.query.filter_by(season=season).filter(
                SeasonArchive.rank <= 3).all():
            if _grant(a.user_id, 'season_top3', season=season, related_id=None):
                db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        # 并发撞唯一约束：重查确认是否已被归档
        meta = SeasonMeta.query.filter_by(season=season).first()
        if meta and meta.archived:
            return True
        raise
