# -*- coding: utf-8 -*-
"""赛季结算归档回归门（competition.season.archive_season）

锁定语义：
- CAS 抢锁：首次归档 True，二次调用 False（不重复快照）
- 排名快照：积分降序；同分同 last_played_at 并列同名次，后续名次跳号（1,1,3）
- 快照行携带段位 tier 与 pk/完赛统计
- 归档后 SeasonMeta.archived 置位
"""
import pytest

from database import db
from database.models import User
from utils.timeutil import utcnow, aware_min


@pytest.fixture()
def season_seed(app):
    """建一个未来赛季 + 若干积分档案。返回 (season_key, add_profile)。"""
    from competition.models import SeasonMeta, UserPointsProfile

    season = '2099-01'
    db.session.add(SeasonMeta(season=season))
    db.session.commit()

    counter = {'n': 0}

    def add_profile(points, last_played_at=None, **kw):
        counter['n'] += 1
        u = User(username=f'ssn_{counter["n"]}', role='student')
        u.set_password('x')
        db.session.add(u)
        db.session.commit()
        p = UserPointsProfile(user_id=u.id, season=season, points=points,
                              last_played_at=last_played_at or utcnow(), **kw)
        db.session.add(p)
        db.session.commit()
        return p

    return season, add_profile


class TestArchiveSeason:
    def test_first_archive_succeeds_and_locks(self, season_seed):
        from competition.models import SeasonMeta, SeasonArchive
        from competition.season import archive_season
        season, add_profile = season_seed
        add_profile(100)
        assert archive_season(season) is True
        meta = SeasonMeta.query.filter_by(season=season).first()
        assert meta.archived is True and meta.archived_at is not None
        assert SeasonArchive.query.filter_by(season=season).count() == 1
        # CAS 二次抢锁失败：不产生第二份快照
        assert archive_season(season) is False
        assert SeasonArchive.query.filter_by(season=season).count() == 1

    def test_ranking_and_tie_rank(self, season_seed):
        from competition.models import SeasonArchive
        from competition.season import archive_season
        season, add_profile = season_seed
        t = utcnow()
        a = add_profile(300)                       # 第 1 名
        b = add_profile(100, last_played_at=t)     # 同分并列第 2
        c = add_profile(100, last_played_at=t)
        d = add_profile(50)                        # 跳号第 4
        assert archive_season(season) is True
        rows = {r.user_id: r for r in
                SeasonArchive.query.filter_by(season=season).all()}
        assert rows[a.id].rank == 1
        assert rows[b.id].rank == 2 and rows[c.id].rank == 2
        assert rows[d.id].rank == 4
        # 快照冗余存积分与统计，供回放/证书
        assert rows[a.id].points == 300
        assert rows[a.id].tier  # tier_of 已计算
        assert rows[b.id].pk_total == rows[b.id].pk_win + 0 + 0

    def test_earlier_reached_tie_break(self, season_seed):
        """同分不同 last_played_at：先到者排前（严格名次）"""
        from competition.models import SeasonArchive
        from competition.season import archive_season
        season, add_profile = season_seed
        early = add_profile(100, last_played_at=aware_min())      # 最早时间
        late = add_profile(100, last_played_at=utcnow())          # 后到达
        assert archive_season(season) is True
        rows = {r.user_id: r for r in
                SeasonArchive.query.filter_by(season=season).all()}
        assert rows[early.id].rank == 1
        assert rows[late.id].rank == 2

    def test_ensure_seasons_archives_stale(self, season_seed, monkeypatch):
        """ensure_seasons 惰性归档：未过期赛季不动，预结算钩子跳过网络/AI"""
        from competition.models import SeasonMeta
        from competition.season import ensure_seasons
        import competition.season as sz
        season, add_profile = season_seed
        add_profile(100)
        monkeypatch.setattr(sz, 'settle_pending_competitions', lambda: None)
        ensure_seasons()
        stale = SeasonMeta.query.filter_by(season=season).first()
        # '2099-01' 晚于当前赛季，不属于过期赛季：不应被归档
        assert stale.archived is False
