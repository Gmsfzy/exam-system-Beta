# -*- coding: utf-8 -*-
"""统一账本内核：多币种流水 + 余额模型（v4.8 ledger 合并）。

设计取舍（见方案）：
- 记账内核统一（LedgerAccount/LedgerTxn 一套引擎），货币语义分账：
  currency='bounty'（赏金钱包，可充值/托管，跨季永续，scope=''）
  currency='points'（赛季竞技积分，荣誉驱动段位，scope='YYYY-MM'），两币永不互兑。
- 所有余额变动必须经 ledger.core.post 唯一写入口，逐笔记 LedgerTxn，
  balance_after 冗余当期余额便于账单展示；守恒不变量按 (user,currency,scope) 成立。
- 与既有物化列的关系：UserPointsProfile.points / BountyWallet 余额仍作为读端物化，
  由 ledger 派生维护（见各门面），保证榜单/段位/钱包读端零改动。
"""
from database import db
from database.types import UTCDateTime
from utils.timeutil import utcnow, iso_local


class LedgerAccount(db.Model):
    """账本账户：一个 (user_id, currency, scope) 一行余额。"""
    __tablename__ = 'ledger_account'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    currency = db.Column(db.String(10), nullable=False)     # bounty / points
    scope = db.Column(db.String(10), nullable=False, default='')  # points=赛季; bounty=''
    balance = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user = db.relationship('User', backref='ledger_accounts')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'currency', 'scope', name='_ledger_acct_uc'),
    )

    def to_dict(self):
        return {
            'user_id': self.user_id, 'currency': self.currency, 'scope': self.scope,
            'balance': self.balance, 'updated_at': iso_local(self.updated_at),
        }


class LedgerTxn(db.Model):
    """账本流水：每笔收支可审计，delta 正入负出，balance_after 记账后余额。

    kind 白名单（按币种）：
      bounty: topup/grant/freeze/release/refund
      points: award/thanks/battle/settle/inherit/init
    idempotency_key 非空时唯一，用于采纳/结算重放去重（同键只记一笔）。
    """
    __tablename__ = 'ledger_txn'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    currency = db.Column(db.String(10), nullable=False)
    scope = db.Column(db.String(10), nullable=False, default='')
    delta = db.Column(db.Integer, nullable=False)
    balance_after = db.Column(db.Integer, nullable=False, default=0)
    kind = db.Column(db.String(20), nullable=False)
    ref_type = db.Column(db.String(20))       # bounty/competition/submission/season/wallet
    ref_id = db.Column(db.Integer)
    memo = db.Column(db.String(200))
    idempotency_key = db.Column(db.String(64), unique=True)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='ledger_txns', lazy=True)

    __table_args__ = (
        db.Index('_ledger_txn_user_cur_scope', 'user_id', 'currency', 'scope'),
    )

    def to_dict(self):
        return {
            'id': self.id, 'user_id': self.user_id, 'currency': self.currency,
            'scope': self.scope, 'delta': self.delta, 'balance_after': self.balance_after,
            'kind': self.kind, 'ref_type': self.ref_type, 'ref_id': self.ref_id,
            'memo': self.memo, 'created_at': iso_local(self.created_at),
        }
