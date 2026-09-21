# -*- coding: utf-8 -*-
"""v4.6.1 中危修复回归门：采纳双原子占坑的条件 UPDATE 语义。

与 bounty/routes.py::submission_accept 中的两条占坑 SQL 保持一致：
A) 悬赏行：名额扣减 + open 状态 + 托管池校验（frozen >= share 或未托管 frozen<=0）
B) 投稿行：pending -> accepted 抢占，防同一投稿双采纳双发钱
"""
import pytest

from bounty.models import Bounty, BountySubmission, BountyStatusEnum, SubmissionStatusEnum
from database import db

SLOT_A = ('UPDATE bounty SET accept_count = accept_count + 1 '
          'WHERE id = :bid AND status = :open '
          'AND accept_count < max_accepts '
          'AND (frozen_points >= :share OR frozen_points <= 0)')
SLOT_B = ('UPDATE bounty_submission SET status = :acc '
          'WHERE id = :sid AND status = :pend')


def _bounty(pub, **kw):
    args = dict(publisher_id=pub.id, title='T', reward_points=100,
                max_accepts=2, accept_count=0, frozen_points=100)
    args.update(kw)
    b = Bounty(**args)
    db.session.add(b)
    db.session.commit()
    return b


def _slot_a(bid, share):
    return db.session.execute(db.text(SLOT_A), {
        'bid': bid, 'open': BountyStatusEnum.OPEN, 'share': share}).rowcount


def _slot_b(sid):
    return db.session.execute(db.text(SLOT_B), {
        'sid': sid, 'acc': SubmissionStatusEnum.ACCEPTED,
        'pend': SubmissionStatusEnum.PENDING}).rowcount


def test_slot_a_quota_serial(app, user_factory):
    pub = user_factory('tpub', 'teacher')
    b = _bounty(pub, accept_count=1)          # 2 个名额还剩 1
    assert _slot_a(b.id, 50) == 1             # 第一次占坑成功
    db.session.commit()
    assert _slot_a(b.id, 50) == 0             # 名额用尽：并发第二请求被拦
    db.session.rollback()


def test_slot_a_escrow_pool_guard(app, user_factory):
    pub = user_factory('tpub2', 'teacher')
    b = _bounty(pub, frozen_points=40)
    assert _slot_a(b.id, 60) == 0             # 分赏超托管池：拒绝
    db.session.rollback()
    assert _slot_a(b.id, 40) == 1             # 恰好等于池：放行
    db.session.commit()


def test_slot_a_legacy_unescrowed_passes(app, user_factory):
    pub = user_factory('tpub3', 'teacher')
    b = _bounty(pub, frozen_points=0)         # 托管关闭期的老悬赏：frozen<=0 分支放行
    assert _slot_a(b.id, 999) == 1
    db.session.commit()


def test_slot_a_rejects_non_open(app, user_factory):
    pub = user_factory('tpub4', 'teacher')
    b = _bounty(pub, status=BountyStatusEnum.CLOSED)
    assert _slot_a(b.id, 10) == 0
    db.session.rollback()


def test_slot_b_double_accept_blocked(app, user_factory):
    pub = user_factory('tpub5', 'teacher')
    st = user_factory('tsub5')
    b = _bounty(pub)
    s = BountySubmission(bounty_id=b.id, submitter_id=st.id,
                         content='ans', status=SubmissionStatusEnum.PENDING)
    db.session.add(s)
    db.session.commit()
    assert _slot_b(s.id) == 1                 # 第一采纳抢占成功
    db.session.commit()
    assert _slot_b(s.id) == 0                 # 同稿二次采纳被拦
    db.session.rollback()


@pytest.mark.parametrize('share,frozen,expect', [
    (10, 10, 1), (11, 10, 0), (0, 0, 1), (100, 0, 1), (100, 99, 0),
])
def test_slot_a_matrix(app, user_factory, share, frozen, expect):
    pub = user_factory('tpubm', 'teacher')
    b = _bounty(pub, frozen_points=frozen)
    assert _slot_a(b.id, share) == expect
    db.session.rollback()
