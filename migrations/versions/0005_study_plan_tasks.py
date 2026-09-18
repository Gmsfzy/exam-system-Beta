"""0005 学习计划任务条目：study_plan_task 表

学习计划从「题量式」改造为「任务清单式」：
- study_plan_task  计划任务条目（学知识点/看资源/刷题/自定义，可勾选打卡）

全新表，CREATE TABLE IF NOT EXISTS 幂等（create_all 在迁移前已建表时直接跳过）。
旧 study_plan 表结构不变（target_count/completed_count 保留但任务清单式下不再使用）。

Revision ID: 0005_study_plan_tasks
Revises: 0004_learning_path_graph
Create Date: 2026-09-17
"""
from sqlalchemy import text

from alembic import op

revision = '0005_study_plan_tasks'
down_revision = '0004_learning_path_graph'
branch_labels = None
depends_on = None


_TABLES = [
    # 学习计划任务条目（plan 删除时 ORM 级联清理；任务挂知识点/资源可选）
    """
    CREATE TABLE IF NOT EXISTS study_plan_task (
        id INTEGER NOT NULL PRIMARY KEY,
        plan_id INTEGER NOT NULL,
        title VARCHAR(200) NOT NULL,
        task_type VARCHAR(20) NOT NULL DEFAULT 'custom',
        knowledge_point_id INTEGER,
        resource_id INTEGER,
        question_count INTEGER,
        estimated_minutes INTEGER,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        done_at DATETIME,
        order_num INTEGER,
        created_at DATETIME NOT NULL,
        CONSTRAINT _plan_task_type_ck CHECK (task_type IN ('knowledge_point', 'resource', 'practice', 'custom')),
        CONSTRAINT _plan_task_status_ck CHECK (status IN ('pending', 'done')),
        FOREIGN KEY(plan_id) REFERENCES study_plan (id),
        FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_point (id),
        FOREIGN KEY(resource_id) REFERENCES learning_resource (id)
    )
    """,
]

_INDEXES = [
    'CREATE INDEX IF NOT EXISTS ix_plan_task_plan ON study_plan_task (plan_id)',
]


def _table_exists(conn, table):
    row = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
    ), {'t': table}).fetchone()
    return row is not None


def upgrade():
    conn = op.get_bind()
    for ddl in _TABLES:
        conn.execute(text(ddl))
    print(f'[0005] {len(_TABLES)} 张任务清单表已就绪（IF NOT EXISTS 幂等）')

    for ddl in _INDEXES:
        conn.execute(text(ddl))
    print(f'[0005] {len(_INDEXES)} 个索引已就绪')


def downgrade():
    conn = op.get_bind()
    if _table_exists(conn, 'study_plan_task'):
        conn.execute(text('DROP TABLE study_plan_task'))
        print('[0005 downgrade] 已删除表 study_plan_task')
