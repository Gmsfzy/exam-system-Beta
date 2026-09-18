"""0006 学习路径个人计划字段：learning_path 加 学习目标/计划起止日期

学习路径定位为「学习者给自己规划的学习路线」（个人学习计划），新增：
- learning_goal     TEXT    学习目标
- start_date        DATE    计划开始日期
- target_end_date   DATE    计划完成日期

SQLite 不支持 ADD COLUMN IF NOT EXISTS，先用 PRAGMA table_info 判存在性，幂等加列。

Revision ID: 0006_path_plan_fields
Revises: 0005_study_plan_tasks
Create Date: 2026-09-17
"""
from sqlalchemy import text

from alembic import op

revision = '0006_path_plan_fields'
down_revision = '0005_study_plan_tasks'
branch_labels = None
depends_on = None


# (列名, 列定义)
_NEW_COLUMNS = [
    ('learning_goal', 'TEXT'),
    ('start_date', 'DATE'),
    ('target_end_date', 'DATE'),
]


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    existing = _existing_columns(conn, 'learning_path')
    added = 0
    for name, ddl in _NEW_COLUMNS:
        if name not in existing:
            conn.execute(text(f'ALTER TABLE learning_path ADD COLUMN {name} {ddl}'))
            added += 1
    print(f'[0006] learning_path 学习目标/计划周期字段已就绪（新增 {added} 列，幂等）')


def downgrade():
    # SQLite 老版本不支持 DROP COLUMN（3.35 以下），且仅为计划字段，downgrade 保留列不删
    print('[0006 downgrade] SQLite 不主动删除列，保留 learning_goal/start_date/target_end_date')
