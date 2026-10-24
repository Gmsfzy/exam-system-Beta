# -*- coding: utf-8 -*-
"""v5.21 课程成绩册/权重聚合：homework/exam 加可空 course_id + 新表 course_grade_scheme。

course_id 为课程归属（可空，向后兼容存量数据），仅用于跨模块只读加权聚合，
不改任何判分/total_score/ledger 口径。course_grade_scheme 存教师对某门课定义的
计分组件（作业/考试 + 权重 + 聚合策略）。SQLite 省略新 FK 约束；加列/建表均判存在幂等。
"""
from alembic import op
import sqlalchemy as sa


revision = '0035_gradebook'
down_revision = '0034_hw_annotation'
branch_labels = None
depends_on = None


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind
    insp = sa.inspect(conn)

    # 1) homework.course_id / exam.course_id（可空，存量默认 NULL）
    if not _col_exists(conn, 'homework', 'course_id'):
        op.add_column('homework', sa.Column('course_id', sa.Integer(), nullable=True))
        op.create_index('ix_homework_course_id', 'homework', ['course_id'])
        print('[0035] homework.course_id 已加')

    if not _col_exists(conn, 'exam', 'course_id'):
        op.add_column('exam', sa.Column('course_id', sa.Integer(), nullable=True))
        op.create_index('ix_exam_course_id', 'exam', ['course_id'])
        print('[0035] exam.course_id 已加')

    # 2) course_grade_scheme 新表
    if 'course_grade_scheme' not in insp.get_table_names():
        op.create_table(
            'course_grade_scheme',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('course.id'), nullable=False),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('component_type', sa.String(length=20), nullable=False, server_default='homework'),
            sa.Column('name', sa.String(length=100), nullable=False, server_default=''),
            sa.Column('weight', sa.Float(), nullable=False, server_default='0'),
            sa.Column('aggregate', sa.String(length=10), nullable=False, server_default='mean'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_course_grade_scheme_course_id', 'course_grade_scheme', ['course_id'])
        op.create_index('ix_course_grade_scheme_created_by', 'course_grade_scheme', ['created_by'])
        print('[0035] course_grade_scheme 已建')


def downgrade():
    for name in ('ix_course_grade_scheme_created_by', 'ix_course_grade_scheme_course_id'):
        try:
            op.drop_index(name)
        except Exception:
            pass
    op.drop_table('course_grade_scheme')
    for table, idx, col in (('exam', 'ix_exam_course_id', 'course_id'),
                            ('homework', 'ix_homework_course_id', 'course_id')):
        try:
            op.drop_index(idx)
        except Exception:
            pass
        with op.batch_alter_table(table) as batch:
            batch.drop_column(col)
