# -*- coding: utf-8 -*-
"""v4.6.1 高危修复回归门：赏金钱包账本守恒。

铁律：任意时刻 每个用户 balance == 其全部流水 delta 之和；
     全库 balance 总和 == topup/grant 发行总额 - （无销毁项时恒等）；
     release_to 只向得奖者入账、发布者采纳环节零入账；超额分账必须抛错。
"""
from bounty import wallet
from bounty.models import Bounty
from ledger import core as ledger
from ledger.models import LedgerAccount, LedgerTxn
from database import db


def _make_bounty(publisher_id, frozen):
    b = Bounty(publisher_id=publisher_id, title='T', bounty_type='question',
               reward_points=frozen, frozen_points=frozen)
    db.session.add(b)
    db.session.commit()
    return b


def _sum_delta(uid):
    return sum(t.delta for t in LedgerTxn.query.filter_by(user_id=uid, currency='bounty').all())


def test_topup_freeze_release_refund_conservation(app, user_factory):
    pub = user_factory('pub1', 'teacher')
    sub = user_factory('sub1')
    topup = wallet.topup(pub.id, 150)
    assert topup is not None

    b = _make_bounty(pub.id, 150)
    assert wallet.freeze(pub.id, 150, b.id) is not None
    assert wallet.balance_of(pub.id) == 0
    db.session.commit()

    # 采纳释放 100：只进得奖者，发布者零入账，冻结池核销
    wallet.release_to(b, [(sub.id, 100)])
    db.session.commit()
    assert wallet.balance_of(sub.id) == 100
    assert wallet.balance_of(pub.id) == 0
    assert b.frozen_points == 50

    # 剩余冻结退回发布者，池清零
    wallet.refund(b, commit=True)
    assert wallet.balance_of(pub.id) == 50
    assert b.frozen_points == 0

    # 守恒：全库余额和 == 发行额 150 == 各用户流水和
    total_balance = sum(a.balance for a in db.session.query(LedgerAccount).filter_by(currency='bounty').all())
    assert total_balance == 150
    assert ledger.assert_conservation('bounty') == []  # 内核逐账户 Σdelta==balance
    assert _sum_delta(pub.id) == 50
    assert _sum_delta(sub.id) == 100


def test_release_over_escrow_raises_and_no_side_effect(app, user_factory):
    pub = user_factory('pub2', 'teacher')
    winner = user_factory('sub2')
    wallet.grant(pub.id, 100)
    b = _make_bounty(pub.id, 100)
    wallet.freeze(pub.id, 100, b.id)
    db.session.commit()
    pub_bal_before = wallet.balance_of(pub.id)

    try:
        wallet.release_to(b, [(winner.id, 120)])  # 超托管池：必须抛错
        raised = False
    except ValueError:
        raised = True
    assert raised
    # 抛错发生在任何写之前：无人入账、池不变
    assert wallet.balance_of(winner.id) == 0
    assert wallet.balance_of(pub.id) == pub_bal_before
    assert b.frozen_points == 100


def test_release_zero_and_negative_shares_skipped(app, user_factory):
    pub = user_factory('pub3', 'teacher')
    w1 = user_factory('sub3a')
    b = _make_bounty(pub.id, 60)
    wallet.release_to(b, [(w1.id, 60), (pub.id, 0), (w1.id, -5)])
    db.session.commit()
    assert wallet.balance_of(w1.id) == 60
    assert b.frozen_points == 0


def test_freeze_insufficient_returns_none(app, user_factory):
    poor = user_factory('poor1')
    b = _make_bounty(poor.id, 10)
    assert wallet.freeze(poor.id, 10, b.id) is None  # 余额 0 不足：拒绝且不记账
    assert db.session.query(LedgerTxn).filter_by(user_id=poor.id, currency='bounty', kind='freeze').count() == 0
