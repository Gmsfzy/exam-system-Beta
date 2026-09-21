# -*- coding: utf-8 -*-
"""赏金钱包与托管账本（P3）——v4.8 起委托统一账本内核（currency='bounty'）。

与竞技积分（currency='points'）分账的独立“赏金”货币，提供可审计的收支流水，
用于悬赏发布的资金托管：发布冻结 → 采纳释放给投稿人 → 过期/取消退回发布者，
杜绝“空头悬赏/赖账”。记账原语统一为 ledger.core.post，本模块仅保留“赏金币种”
门面与托管语义（release/refund 对 bounty.frozen_points 的核销）。

托管是否启用由环境变量 BOUNTY_ESCROW 控制（默认关闭，保持既有直接积分激励行为，
向后兼容）。无论开关，钱包/流水接口都可用（充值、发放体验金、查询账单）。
"""
import os

from database import db
from ledger import core as ledger

BOUNTY = 'bounty'


def escrow_enabled():
    """托管总开关：BOUNTY_ESCROW=true/1/on 时启用发布冻结/采纳释放/过期退回。"""
    return (os.environ.get('BOUNTY_ESCROW') or '').strip().lower() in ('1', 'true', 'on', 'yes')


def ensure_wallet(user_id):
    """取（无则建）赏金币种账户（ledger_account 的一行）。"""
    return ledger.ensure_account(user_id, BOUNTY)


def balance_of(user_id):
    return ledger.balance_of(user_id, BOUNTY)


def _apply(account, delta, kind, ref_type=None, ref_id=None, memo=None):
    """在赏金账户上记一笔流水（不 commit，纳入调用方事务）。account 为 ledger 账户。"""
    return ledger.post(account.user_id, BOUNTY, delta, kind,
                       ref_type=ref_type, ref_id=ref_id, memo=memo)


def topup(user_id, amount, memo=None, commit=True):
    """充值（正数入账）。返回流水。"""
    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError('充值金额必须大于 0')
    return ledger.post(user_id, BOUNTY, amount, 'topup', ref_type='wallet', memo=memo, commit=commit)


def grant(user_id, amount, memo=None, commit=True):
    """系统发放体验金/奖励（正数入账）。"""
    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError('发放金额必须大于 0')
    return ledger.post(user_id, BOUNTY, amount, 'grant', ref_type='wallet', memo=memo, commit=commit)


def freeze(user_id, amount, bounty_id):
    """发布托管：从钱包冻结 amount（负数出账）。余额不足返回 None（调用方据此拒绝发布）。"""
    amount = int(amount or 0)
    if amount <= 0:
        return None
    w = ensure_wallet(user_id)
    if (w.balance or 0) < amount:
        return None
    return _apply(w, -amount, 'freeze', ref_type='bounty', ref_id=bounty_id, memo='发布悬赏冻结')


def release_to(bounty, payouts):
    """采纳释放：把悬赏托管冻结的赏金按 payouts=[(user_id, share), ...] 转入得奖者钱包。

    发布时 freeze() 已从发布者余额扣款（frozen_points 记在托管池），因此采纳环节
    发布者钱包不再有任何入账：只向得奖者入账，并同步从 frozen_points 核销等额，
    保证账本守恒（全流程流水之和恒为 0）。所有分账之和不得超过 bounty.frozen_points，
    超出视为调用方漏校验，抛 ValueError 由调用方回滚整笔事务。
    在调用方事务内执行（不 commit）。
    """
    total = sum(int(s or 0) for _, s in payouts if int(s or 0) > 0)
    if total <= 0:
        return
    if total > (bounty.frozen_points or 0):
        raise ValueError('分账总额超出托管剩余额度')
    for uid, share in payouts:
        share = int(share or 0)
        if share <= 0:
            continue
        ledger.post(uid, BOUNTY, share, 'release', ref_type='bounty', ref_id=bounty.id,
                    memo='悬赏投稿中标赏金')
    bounty.frozen_points = (bounty.frozen_points or 0) - total


def refund(bounty, commit=False):
    """过期/取消退回：把尚未释放的冻结额退回发布者钱包。"""
    amount = int(bounty.frozen_points or 0)
    if amount <= 0:
        return
    ledger.post(bounty.publisher_id, BOUNTY, amount, 'refund', ref_type='bounty',
                ref_id=bounty.id, memo='悬赏过期/取消退回')
    bounty.frozen_points = 0
    if commit:
        db.session.commit()
