"""统一账本：建 ledger_account/ledger_txn，搬移赏金/积分存量，旧钱包表改名 legacy

- 新表 ledger_account / ledger_txn（CREATE TABLE IF NOT EXISTS，兼容 create_all 先后顺序）
- 赏金：bounty_wallet → ledger_account(currency='bounty')，bounty_txn → ledger_txn
- 竞技积分：user_points_profile.points(≠0) → ledger_account(currency='points', scope=season)
  并各记一笔 kind='init' 期初建账流水，使「Σdelta==balance」不变量对存量同样成立
- 守恒门：迁移后逐账户对账，Σ流水delta≠余额即中止（回滚，保留原表）
- 原表改名 *_legacy 原位留存（user_points_profile 作为读端物化列保留不动）

幂等：以 ledger 是否已有对应币种流水/账户为判据，重复执行不二次搬移。

Revision ID: 0018_ledger_unify
Revises: 0017_oj_test_cases
Create Date: 2026-09-21
"""
from sqlalchemy import text

from alembic import op

revision = '0018_ledger_unify'
down_revision = '0017_oj_test_cases'
branch_labels = None
depends_on = None


def _table_exists(conn, name):
    return conn.execute(text(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=:n"
    ), {'n': name}).scalar() > 0


def _count(conn, sql, params=None):
    return conn.execute(text(sql), params or {}).scalar() or 0


def upgrade():
    conn = op.get_bind()

    # 1) 新表（IF NOT EXISTS：无论 create_all 是否已建都安全）
    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS ledger_account (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            currency VARCHAR(10) NOT NULL,
            scope VARCHAR(10) NOT NULL,
            balance INTEGER NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT _ledger_acct_uc UNIQUE (user_id, currency, scope)
        )
        """
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_ledger_account_user_id ON ledger_account (user_id)"
    ))
    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS ledger_txn (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            currency VARCHAR(10) NOT NULL,
            scope VARCHAR(10) NOT NULL,
            delta INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            kind VARCHAR(20) NOT NULL,
            ref_type VARCHAR(20),
            ref_id INTEGER,
            memo VARCHAR(200),
            idempotency_key VARCHAR(64),
            created_at DATETIME NOT NULL,
            CONSTRAINT ux_ledger_txn_idempotency_key UNIQUE (idempotency_key)
        )
        """
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_ledger_txn_user_id ON ledger_txn (user_id)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS _ledger_txn_user_cur_scope "
        "ON ledger_txn (user_id, currency, scope)"
    ))
    print('[0018] ledger_account / ledger_txn 已就绪')

    # 2) 搬移赏金钱包（源表存在且 ledger 尚无 bounty 流水时）
    src_wallet = _table_exists(conn, 'bounty_wallet') and _table_exists(conn, 'bounty_txn')
    if src_wallet and _count(conn, "SELECT count(*) FROM ledger_txn WHERE currency='bounty'") == 0:
        conn.execute(text(
            """
            INSERT INTO ledger_account (user_id, currency, scope, balance, updated_at)
            SELECT user_id, 'bounty', '', balance, updated_at FROM bounty_wallet
            """
        ))
        conn.execute(text(
            """
            INSERT INTO ledger_txn
                (user_id, currency, scope, delta, balance_after, kind, ref_type, ref_id, memo, created_at)
            SELECT user_id, 'bounty', '', delta, balance_after, kind, ref_type, ref_id, memo, created_at
            FROM bounty_txn
            """
        ))
        print('[0018] 赏金钱包存量已搬入 ledger（bounty）')

    # 3) 竞技积分建账（存量 points≠0 的档案，各记一笔 init 期初流水）
    if _table_exists(conn, 'user_points_profile') and \
            _count(conn, "SELECT count(*) FROM ledger_txn WHERE currency='points'") == 0:
        conn.execute(text(
            """
            INSERT INTO ledger_account (user_id, currency, scope, balance, updated_at)
            SELECT user_id, 'points', season, points, updated_at
            FROM user_points_profile WHERE points <> 0
            """
        ))
        conn.execute(text(
            """
            INSERT INTO ledger_txn
                (user_id, currency, scope, delta, balance_after, kind, ref_type, ref_id, memo, created_at)
            SELECT la.user_id, 'points', la.scope, la.balance, la.balance, 'init', 'season', NULL,
                   '期初建账（存量竞技积分迁移）', la.updated_at
            FROM ledger_account la WHERE la.currency='points'
            """
        ))
        print('[0018] 竞技积分存量已建账（points/init）')

    # 4) 守恒门：任何账户 Σdelta != balance 即中止（事务回滚，原表未改名，可人工排查）
    bad = _count(conn,
                 """
                 SELECT count(*) FROM ledger_account la
                 WHERE la.balance <> (
                     SELECT COALESCE(SUM(t.delta), 0) FROM ledger_txn t
                     WHERE t.user_id=la.user_id AND t.currency=la.currency AND t.scope=la.scope)
                 """
                 )
    if bad > 0:
        raise RuntimeError(f'[0018] 账本守恒校验失败：{bad} 个账户 Σ流水≠余额，迁移已中止，请人工核查')
    print('[0018] 守恒校验通过（全账户 Σdelta==balance）')

    # 5) 旧表改名 *_legacy 原位留存（幂等：仅当源在、目标不在）
    if _table_exists(conn, 'bounty_wallet') and not _table_exists(conn, 'bounty_wallet_legacy'):
        conn.execute(text('ALTER TABLE bounty_wallet RENAME TO bounty_wallet_legacy'))
        print('[0018] bounty_wallet → bounty_wallet_legacy')
    if _table_exists(conn, 'bounty_txn') and not _table_exists(conn, 'bounty_txn_legacy'):
        conn.execute(text('ALTER TABLE bounty_txn RENAME TO bounty_txn_legacy'))
        print('[0018] bounty_txn → bounty_txn_legacy')


def downgrade():
    conn = op.get_bind()
    # 还原旧表名并把 bounty 余额回写（流水无法逐笔还原，points 侧余额回写档案）
    if _table_exists(conn, 'bounty_wallet_legacy') and not _table_exists(conn, 'bounty_wallet'):
        conn.execute(text('ALTER TABLE bounty_wallet_legacy RENAME TO bounty_wallet'))
    if _table_exists(conn, 'bounty_txn_legacy') and not _table_exists(conn, 'bounty_txn'):
        conn.execute(text('ALTER TABLE bounty_txn_legacy RENAME TO bounty_txn'))
    if _table_exists(conn, 'bounty_wallet'):
        conn.execute(text(
            """
            UPDATE bounty_wallet SET balance = COALESCE((
                SELECT la.balance FROM ledger_account la
                WHERE la.user_id=bounty_wallet.user_id AND la.currency='bounty' AND la.scope=''), 0)
            """
        ))
    conn.execute(text('DROP TABLE IF EXISTS ledger_txn'))
    conn.execute(text('DROP TABLE IF EXISTS ledger_account'))
    print('[0018 downgrade] 已还原 bounty_wallet/bounty_txn 并删除 ledger 表（points 逐笔流水不回滚）')
