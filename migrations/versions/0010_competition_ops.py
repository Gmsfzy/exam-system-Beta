"""竞赛模块竞技内核升级（第三批）：已有表加列

运营能力所需列（新表 competition_certificate 由 create_all 自动建，不在此列）：
- competition : remind_before / remind_sent_at / access_mode / invite_code

SQLite 不支持 ADD COLUMN IF NOT EXISTS，先用 PRAGMA table_info 判存在性，幂等加列。

Revision ID: 0010_competition_ops
Revises: 0009_competition_arena
Create Date: 2026-09-18
"""
from sqlalchemy import text

from alembic import op

revision = '0010_competition_ops'
down_revision = '0009_competition_arena'
branch_labels = None
depends_on = None


# (表名, [(列名, 列定义), ...])
_NEW_COLUMNS = [
    ('competition', [
        ('remind_before', 'INTEGER NOT NULL DEFAULT 0'),
        ('remind_sent_at', 'DATETIME'),
        ('access_mode', "VARCHAR(10) NOT NULL DEFAULT 'public'"),
        ('invite_code', 'VARCHAR(16)'),
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
    print(f'[0010] 竞赛运营能力列已就绪（新增 {added} 列，幂等）')


def downgrade():
    # SQLite 老版本不支持 DROP COLUMN，且均为可空/带默认列，保留无害
    print('[0010 downgrade] 列保留（可空或带默认值，不影响旧逻辑）')
