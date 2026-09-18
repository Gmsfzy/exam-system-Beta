"""学习计划增强：任务截止日

- study_plan_task 加 due_date 列（DATE，可空；配合前端时间轴/逾期标红）

加列用 PRAGMA table_info 判存在性，幂等可重复执行。

Revision ID: 0008_task_due_date
Revises: 0007_learning_closed_loop
Create Date: 2026-09-18
"""
from sqlalchemy import text

from alembic import op

revision = '0008_task_due_date'
down_revision = '0007_learning_closed_loop'
branch_labels = None
depends_on = None


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    existing = _existing_columns(conn, 'study_plan_task')
    if 'due_date' not in existing:
        conn.execute(text('ALTER TABLE study_plan_task ADD COLUMN due_date DATE'))
        print('[0008] study_plan_task.due_date 列已添加')
    else:
        print('[0008] study_plan_task.due_date 已存在（幂等跳过）')


def downgrade():
    # SQLite 旧版不支持 DROP COLUMN 时静默保留；列可空且无默认值，留档无害
    print('[0008 downgrade] due_date 列保留（可空列不影响旧逻辑）')
