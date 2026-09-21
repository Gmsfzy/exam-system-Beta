"""征集悬赏模块社区化与治理升级：已有表加列（P0–P3）

新表 bounty_comment / bounty_vote / bounty_report / bounty_wallet / bounty_txn
由 db.create_all() 启动自动建，不在此列。此处只对已有表幂等加列：
- bounty            : max_accepts / accept_count / tags / visibility / target_json / frozen_points / updated_at
- bounty_submission : reward_share / is_anonymous / edited_at

SQLite 不支持 ADD COLUMN IF NOT EXISTS，先用 PRAGMA table_info 判存在性，幂等加列。

Revision ID: 0011_bounty_upgrade
Revises: 0010_competition_ops
Create Date: 2026-09-19
"""
from sqlalchemy import text

from alembic import op

revision = '0011_bounty_upgrade'
down_revision = '0010_competition_ops'
branch_labels = None
depends_on = None


# (表名, [(列名, 列定义), ...])
_NEW_COLUMNS = [
    ('bounty', [
        ('max_accepts', 'INTEGER NOT NULL DEFAULT 1'),
        ('accept_count', 'INTEGER NOT NULL DEFAULT 0'),
        ('tags', 'VARCHAR(200)'),
        ('visibility', "VARCHAR(10) NOT NULL DEFAULT 'public'"),
        ('target_json', 'TEXT'),
        ('frozen_points', 'INTEGER NOT NULL DEFAULT 0'),
        ('updated_at', 'DATETIME'),
    ]),
    ('bounty_submission', [
        ('reward_share', 'INTEGER NOT NULL DEFAULT 0'),
        ('is_anonymous', 'INTEGER NOT NULL DEFAULT 0'),
        ('edited_at', 'DATETIME'),
    ]),
]


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    added = 0
    for table, cols in _NEW_COLUMNS:
        existing = _existing_columns(conn, table)
        for name, ddl in cols:
            if name not in existing:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
                added += 1
    print(f'[0011] 悬赏升级列已就绪（新增 {added} 列，幂等）')


def downgrade():
    # SQLite 老版本不支持 DROP COLUMN，且均为可空/带默认列，保留无害
    print('[0011 downgrade] 列保留（可空或带默认值，不影响旧逻辑）')
