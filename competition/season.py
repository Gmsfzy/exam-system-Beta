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
    tier_of, current_season, settle_pending_competitions, _grant, cert_grade,
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
        total = len(profiles)
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
                tier=tier_of(p.points, rank, total),
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
        _issue_season_certificates(season, total)
        return True
    except Exception:
        db.session.rollback()
        # 并发撞唯一约束：重查确认是否已被归档
        meta = SeasonMeta.query.filter_by(season=season).first()
        if meta and meta.archived:
            return True
        raise


def _issue_season_certificates(season, total):
    """按最终积分分等级颁发赛季证书（幂等：一人一赛季一份）。"""
    from competition.models import CompetitionCertificate
    try:
        from api.learning_engine import gen_serial_no
    except Exception:
        gen_serial_no = None
    for a in SeasonArchive.query.filter_by(season=season).all():
        graded = cert_grade(a.points)
        if not graded:
            continue
        code, label = graded
        exists = CompetitionCertificate.query.filter_by(
            user_id=a.user_id, season=season).first()
        if exists:
            continue
        cert = CompetitionCertificate(
            user_id=a.user_id, season=season,
            serial_no=(gen_serial_no() if gen_serial_no
                       else f'CERT-{season}-{a.user_id}'),
            grade=code, tier=a.tier, rank=a.rank, points=a.points,
            total_players=total,
            summary={'season_label': season, 'grade_label': label,
                     'pk_total': a.pk_total, 'timed_finished': a.timed_finished,
                     'earned_date': utcnow().date().isoformat()},
        )
        db.session.add(cert)
        db.session.flush()  # 暴露唯一约束竞态
        try:
            from api.notification_routes import create_notification
            create_notification(
                a.user_id, f'恭喜获得赛季{label}',
                f'你在 {season} 赛季以 {a.points} 分获得{label}段位证书（赛季第 {a.rank} 名）。',
                type='success', related_type='competition_cert',
                related_id=cert.id, commit=False)
        except Exception:
            pass
    db.session.commit()
