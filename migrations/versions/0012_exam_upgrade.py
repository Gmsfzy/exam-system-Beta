"""考试模块考务升级：已有表幂等加列（v4.3 P0–P3）

- exam          : results_published / max_attempts / score_strategy / paper_mode /
                  random_count / shuffle_options / multi_score_rule / anonymous_grading
- exam_session  : attempt_no / score / assigned_question_ids / option_map
- exam_student  : extra_attempts
- result        : session_id / review_status / review_reason / review_reply / reviewed_at
- question      : material / material_group（材料题）

SQLite 不支持 ADD COLUMN IF NOT EXISTS，先用 PRAGMA table_info 判存在性，幂等加列。

Revision ID: 0012_exam_upgrade
Revises: 0011_bounty_upgrade
Create Date: 2026-09-19
"""
from sqlalchemy import text

from alembic import op

revision = '0012_exam_upgrade'
down_revision = '0011_bounty_upgrade'
branch_labels = None
depends_on = None


# (表名, [(列名, 列定义), ...])
_NEW_COLUMNS = [
    ('exam', [
        ('results_published', 'INTEGER NOT NULL DEFAULT 1'),
        ('max_attempts', 'INTEGER NOT NULL DEFAULT 1'),
        ('score_strategy', "VARCHAR(10) NOT NULL DEFAULT 'last'"),
        ('paper_mode', "VARCHAR(10) NOT NULL DEFAULT 'unified'"),
        ('random_count', 'INTEGER NOT NULL DEFAULT 0'),
        ('shuffle_options', 'INTEGER NOT NULL DEFAULT 0'),
        ('multi_score_rule', "VARCHAR(20) NOT NULL DEFAULT 'all_or_nothing'"),
        ('anonymous_grading', 'INTEGER NOT NULL DEFAULT 0'),
    ]),
    ('exam_session', [
        ('attempt_no', 'INTEGER NOT NULL DEFAULT 1'),
        ('score', 'FLOAT'),
        ('assigned_question_ids', 'TEXT'),
        ('option_map', 'TEXT'),
    ]),
    ('exam_student', [
        ('extra_attempts', 'INTEGER NOT NULL DEFAULT 0'),
    ]),
    ('result', [
        ('session_id', 'INTEGER'),
        ('review_status', "VARCHAR(20) NOT NULL DEFAULT 'none'"),
        ('review_reason', 'TEXT'),
        ('review_reply', 'TEXT'),
        ('reviewed_at', 'DATETIME'),
    ]),
    ('question', [
        ('material', 'TEXT'),
        ('material_group', 'VARCHAR(50)'),
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
    print(f'[0012] 考试考务升级列已就绪（新增 {added} 列，幂等）')


def downgrade():
    # SQLite 老版本不支持 DROP COLUMN，且均为可空/带默认列，保留无害
    print('[0012 downgrade] 列保留（可空或带默认值，不影响旧逻辑）')
