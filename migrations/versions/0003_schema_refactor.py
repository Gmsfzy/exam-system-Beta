"""0003 结构补全：缺失列 + Result 唯一约束

把原 init_database 中硬编码的 ALTER TABLE ADD COLUMN 迁移到 Alembic，
并为 result 表加 (exam_id, student_id) 唯一约束，防止并发重复成绩。

Revision ID: 0003_schema_refactor
Revises: 0002_tz_normalize
Create Date: 2026-09-07
"""
from sqlalchemy import text

from alembic import op

revision = '0003_schema_refactor'
down_revision = '0002_tz_normalize'
branch_labels = None
depends_on = None


# 原 init_database 中逐列 ADD 的字段（SQLite 不支持 ADD COLUMN IF NOT EXISTS，
# 用 try/except 保证幂等）
_NEW_COLUMNS = [
    ('answer', 'manual_score', 'FLOAT'),
    ('answer', 'manual_comment', 'TEXT'),
    ('answer', 'needs_manual_grade', 'BOOLEAN DEFAULT 0'),
    ('exam_session', 'switch_count', 'INTEGER DEFAULT 0'),
    ('question', 'knowledge', 'TEXT'),
    ('question', 'chapter_id', 'INTEGER'),
    ('competition', 'draw_count', 'INTEGER DEFAULT 0'),
    ('competition', 'allow_pk', 'BOOLEAN DEFAULT 1'),
    ('competition', 'points_settled', 'BOOLEAN DEFAULT 0'),
    ('competition_participant', 'assigned_cq_ids', 'TEXT'),
]


def _column_exists(conn, table, column):
    cols = [row[1] for row in conn.execute(text(f'PRAGMA table_info({table})'))]
    return column in cols


def upgrade():
    conn = op.get_bind()

    # 1) 补全历史缺失列
    for table, col, col_type in _NEW_COLUMNS:
        if _column_exists(conn, table, col):
            continue
        try:
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {col_type}'))
            print(f'[0003] 已添加列 {table}.{col}')
        except Exception as e:
            print(f'[0003] 添加列 {table}.{col} 跳过（{e}）')

    # 2) result 表唯一约束：同一学生同一考试只允许一条成绩
    #    SQLite 中 UNIQUE 约束底层即唯一索引，用 CREATE UNIQUE INDEX 更安全
    conn.execute(text(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_result_exam_student '
        'ON result (exam_id, student_id)'
    ))
    print('[0003] result 表唯一约束 (exam_id, student_id) 已创建')


def downgrade():
    conn = op.get_bind()
    conn.execute(text('DROP INDEX IF EXISTS idx_result_exam_student'))
    # 列不回滚（ADD COLUMN 不可逆）
