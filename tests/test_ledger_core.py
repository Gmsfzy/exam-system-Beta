# -*- coding: utf-8 -*-
"""v4.8 统一账本内核回归门。

锁住 ledger.core 的四类不变量与两处易错语义：
1. kind 白名单：越界币种/类型必须 raise（防任意字符串污染审计口径）；
2. idempotency_key：同业务动作重放只记一笔、只入账一次；
3. 守恒对账 assert_conservation：篡改余额必须被检出、复位即清零；
4. 币种隔离：bounty 与 points（含不同赛季 scope）互不串账；
5. 积分镜像入账：award_bounty/thank_you 使 ledger Σdelta 与 UserPointsProfile.points 同步；
6. 全链净零：freeze/release/refund 不凭空造币，Σdelta==发行总额。
"""
import pytest

from database import db
from ledger import core as ledger
from ledger.models import LedgerAccount, LedgerTxn


def test_post_kind_whitelist_rejects(app, user_factory):
    u = user_factory('lc1')
    with pytest.raises(ValueError):
        ledger.post(u.id, 'bounty', 10, 'not_a_real_kind')
    with pytest.raises(ValueError):
        ledger.post(u.id, 'points', 10, 'topup')      # topup 属 bounty 币种，points 越界
    with pytest.raises(ValueError):
        ledger.post(u.id, 'gold', 10, 'topup')         # 未知币种
    db.session.rollback()


def test_post_idempotency_key_dedups(app, user_factory):
    u = user_factory('lc2')
    t1 = ledger.post(u.id, 'points', 30, 'award', scope='2026-09',
                     idempotency_key='award:sub:99', commit=True)
    t2 = ledger.post(u.id, 'points', 30, 'award', scope='2026-09',
                     idempotency_key='award:sub:99', commit=True)
    assert t1.id == t2.id                                       # 同键返回既有流水
    assert ledger.balance_of(u.id, 'points', '2026-09') == 30   # 仅入账一次
    assert db.session.query(LedgerTxn).filter_by(idempotency_key='award:sub:99').count() == 1


def test_conservation_flags_imbalance(app, user_factory):
    u = user_factory('lc3')
    ledger.post(u.id, 'bounty', 100, 'topup', commit=True)
    assert ledger.assert_conservation('bounty') == []
    acct = LedgerAccount.query.filter_by(user_id=u.id, currency='bounty').first()
    acct.balance = 999                                          # 篡改余额、流水不变
    db.session.commit()
    diffs = ledger.assert_conservation('bounty')
    assert len(diffs) == 1 and diffs[0][0] == u.id
    acct.balance = 100
    db.session.commit()
    assert ledger.assert_conservation('bounty') == []


def test_currency_isolation(app, user_factory):
    u = user_factory('lc4')
    ledger.post(u.id, 'bounty', 50, 'grant', commit=True)
    ledger.post(u.id, 'points', 80, 'battle', scope='2026-09', commit=True)
    assert ledger.balance_of(u.id, 'bounty') == 50
    assert ledger.balance_of(u.id, 'points', '2026-09') == 80
    assert ledger.balance_of(u.id, 'points', '2020-01') == 0    # 不同赛季 scope 独立


def test_points_mirror_equals_profile(app, user_factory):
    """悬赏采纳/落选加分镜像入账后，ledger Σdelta 与物化列 profile.points 恒等。"""
    from bounty import rewards
    from competition.models import UserPointsProfile
    u = user_factory('lc5')
    rewards.award_bounty(u.id, 30, related_id=None)
    rewards.thank_you(u.id, 5, related_id=None)
    season = rewards.current_season()
    p = UserPointsProfile.query.filter_by(user_id=u.id, season=season).first()
    assert p.points == 35
    sigma = sum(t.delta for t in LedgerTxn.query.filter_by(
        user_id=u.id, currency='points', scope=season).all())
    assert sigma == p.points
    assert ledger.assert_conservation('points') == []


def test_release_net_zero_across_users(app, user_factory):
    """freeze/release 不凭空造币：全库 bounty Σdelta 恒等于发行额（grant/topup）。"""
    from bounty import wallet
    from bounty.models import Bounty
    pub = user_factory('lc6p', 'teacher')
    w1 = user_factory('lc6w1')
    w2 = user_factory('lc6w2')
    wallet.grant(pub.id, 200)
    b = Bounty(publisher_id=pub.id, title='T', bounty_type='question',
               reward_points=200, frozen_points=200)
    db.session.add(b)
    db.session.commit()
    assert wallet.freeze(pub.id, 200, b.id) is not None
    db.session.commit()
    wallet.release_to(b, [(w1.id, 120), (w2.id, 80)])
    db.session.commit()
    assert wallet.balance_of(w1.id) == 120 and wallet.balance_of(w2.id) == 80
    assert b.frozen_points == 0
    assert wallet.balance_of(pub.id) == 0
    allsum = sum(t.delta for t in LedgerTxn.query.filter_by(currency='bounty').all())
    assert allsum == 200                                # 等于发行额，无凭空增发
    assert ledger.assert_conservation('bounty') == []
