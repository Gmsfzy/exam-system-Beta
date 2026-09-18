"""竞赛模块竞技内核升级（第一批）：已有表加列

对标 Kaggle 竞技体系，为已有表补充竞技/公平所需列（新表由 create_all 自动建，不在此列）：
- competition              : series_id / series_round / is_quick
- pk_battle                : is_bot / quick / bot_plan / delta_challenger / delta_opponent
- competition_answer       : flagged / flag_reason
- pk_answer                : flagged / flag_reason
- competition_participant  : flagged
- user                     : sanctioned_at / sanction_reason

SQLite 不支持 ADD COLUMN IF NOT EXISTS，先用 PRAGMA table_info 判存在性，幂等加列。

Revision ID: 0009_competition_arena
Revises: 0008_task_due_date
Create Date: 2026-09-18
"""
from sqlalchemy import text

from alembic import op

revision = '0009_competition_arena'
down_revision = '0008_task_due_date'
branch_labels = None
depends_on = None


# (表名, [(列名, 列定义), ...])
_NEW_COLUMNS = [
    ('competition', [
        ('series_id', 'INTEGER'),
        ('series_round', 'INTEGER'),
        ('is_quick', 'BOOLEAN NOT NULL DEFAULT 0'),
    ]),
    ('pk_battle', [
        ('is_bot', 'BOOLEAN NOT NULL DEFAULT 0'),
        ('quick', 'BOOLEAN NOT NULL DEFAULT 0'),
        ('bot_plan', 'TEXT'),
        ('delta_challenger', 'INTEGER NOT NULL DEFAULT 0'),
        ('delta_opponent', 'INTEGER NOT NULL DEFAULT 0'),
    ]),
    ('competition_answer', [
        ('flagged', 'BOOLEAN NOT NULL DEFAULT 0'),
        ('flag_reason', 'VARCHAR(20)'),
    ]),
    ('pk_answer', [
        ('flagged', 'BOOLEAN NOT NULL DEFAULT 0'),
        ('flag_reason', 'VARCHAR(20)'),
    ]),
    ('competition_participant', [
        ('flagged', 'BOOLEAN NOT NULL DEFAULT 0'),
    ]),
    ('user', [
        ('sanctioned_at', 'DATETIME'),
        ('sanction_reason', 'VARCHAR(200)'),
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
    print(f'[0009] 竞赛竞技内核升级列已就绪（新增 {added} 列，幂等）')


def downgrade():
    # SQLite 老版本不支持 DROP COLUMN，且均为可空/带默认列，保留无害
    print('[0009 downgrade] 列保留（可空或带默认值，不影响旧逻辑）')
