# -*- coding: utf-8 -*-
"""账本内核引擎：ensure_account / post（唯一写入原语）/ balance_of / assert_conservation。

所有货币的余额变动都必须经此，保证「逐笔流水 + 余额 + 守恒」三件套一致。
默认不 commit（纳入调用方事务），与赏金托管既有的「同一事务内记账」语义对齐。
"""
import logging

from sqlalchemy.exc import IntegrityError

from database import db
from ledger.models import LedgerAccount, LedgerTxn

logger = logging.getLogger(__name__)

# 币种 kind 白名单：防止任意字符串污染审计口径（post 越界即 raise）
KINDS = {
    'bounty': {'topup', 'grant', 'freeze', 'release', 'refund'},
    'points': {'award', 'thanks', 'battle', 'settle', 'inherit', 'init'},
}


def ensure_account(user_id, currency, scope=''):
    """取（无则建）账户。唯一约束 (user,currency,scope) 兜底并发创建冲突。"""
    if currency not in KINDS:
        raise ValueError(f'未知账本币种: {currency}')
    acct = LedgerAccount.query.filter_by(user_id=user_id, currency=currency, scope=scope).first()
    if acct is not None:
        return acct
    acct = LedgerAccount(user_id=user_id, currency=currency, scope=scope, balance=0)
    db.session.add(acct)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        acct = LedgerAccount.query.filter_by(
            user_id=user_id, currency=currency, scope=scope).first()
    return acct


def balance_of(user_id, currency, scope=''):
    acct = LedgerAccount.query.filter_by(user_id=user_id, currency=currency, scope=scope).first()
    return acct.balance if acct else 0


def post(user_id, currency, delta, kind, scope='', ref_type=None, ref_id=None,
         memo=None, idempotency_key=None, commit=False):
    """记账唯一入口：写一笔流水并同步账户余额（不单独 commit，除非 commit=True）。

    - kind 必须落在该币种白名单内，否则 ValueError（由调用方回滚整笔事务）。
    - idempotency_key 非空且已存在同键流水时，直接返回既有流水，不重复记账（重放去重）。
    - delta 正入负出，允许任意整数（含负数）；余额是否可为负由调用方业务约束把关。
    返回 LedgerTxn。
    """
    allowed = KINDS.get(currency)
    if allowed is None:
        raise ValueError(f'未知账本币种: {currency}')
    if kind not in allowed:
        raise ValueError(f'币种 {currency} 不允许流水类型 {kind}')

    if idempotency_key:
        exist = LedgerTxn.query.filter_by(idempotency_key=idempotency_key).first()
        if exist is not None:
            return exist

    delta = int(delta or 0)
    acct = ensure_account(user_id, currency, scope)
    acct.balance = (acct.balance or 0) + delta
    txn = LedgerTxn(user_id=user_id, currency=currency, scope=scope, delta=delta,
                    balance_after=acct.balance, kind=kind, ref_type=ref_type, ref_id=ref_id,
                    memo=(memo or '')[:200] or None, idempotency_key=idempotency_key)
    db.session.add(txn)
    if commit:
        db.session.commit()
    return txn


def txns_of(user_id, currency=None, limit=None):
    """按用户（可选币种）取流水，时间倒序，供账单/审计接口序列化。"""
    q = LedgerTxn.query.filter_by(user_id=user_id)
    if currency:
        q = q.filter_by(currency=currency)
    q = q.order_by(LedgerTxn.created_at.desc(), LedgerTxn.id.desc())
    if limit:
        q = q.limit(limit)
    return q.all()


def assert_conservation(currency=None):
    """全量对账：返回 Σ流水delta != 账户余额 的账户清单 [(user,currency,scope,sigma,balance)]。

    空列表即账本内部守恒成立。测试与迁移校验门用。
    """
    sums = {}
    q = db.session.query(LedgerTxn.user_id, LedgerTxn.currency, LedgerTxn.scope,
                         db.func.sum(LedgerTxn.delta))
    if currency:
        q = q.filter(LedgerTxn.currency == currency)
    for uid, cur, sc, s in q.group_by(LedgerTxn.user_id, LedgerTxn.currency, LedgerTxn.scope).all():
        sums[(uid, cur, sc)] = int(s or 0)

    aq = LedgerAccount.query
    if currency:
        aq = aq.filter(LedgerAccount.currency == currency)
    diffs = []
    for acct in aq.all():
        sigma = sums.get((acct.user_id, acct.currency, acct.scope), 0)
        if sigma != (acct.balance or 0):
            diffs.append((acct.user_id, acct.currency, acct.scope, sigma, acct.balance or 0))
    return diffs
