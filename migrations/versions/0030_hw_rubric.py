# -*- coding: utf-8 -*-
"""v5.15 评分量规 Rubric：新表 homework_rubric + homework.rubric_id + 提交维度分快照。

仅结构化拆解/建议，不改 total_score/manual_score 推导。JSON 列以 Text 承载（对齐 0026~0029）。
inspect 幂等：建表前先判存在（兼容 create_all 已建表）；加列前用 _col_exists+PRAGMA 判存在。
"""
from alembic import op
import sqlalchemy as sa


revision = '0030_hw_rubric'
down_revision = '0029_hw_grade_mode'
branch_labels = None
depends_on = None


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind
    insp = sa.inspect(conn)

    # 1) 新表 homework_rubric（dimensions_json 以 Text 存 JSON）
    if 'homework_rubric' not in insp.get_table_names():
        op.create_table(
            'homework_rubric',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('teacher_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('dimensions_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_homework_rubric_teacher_id', 'homework_rubric', ['teacher_id'])
        print('[0030] homework_rubric 已建')

    # 2) homework.rubric_id（SQLite 省略 FK 约束）
    if not _col_exists(conn, 'homework', 'rubric_id'):
        op.add_column('homework', sa.Column('rubric_id', sa.Integer(), nullable=True))
        op.create_index('ix_homework_rubric_id', 'homework', ['rubric_id'])
        print('[0030] homework.rubric_id 已加')

    # 3) homework_submission.rubric_scores_json（逐维度得分快照）
    if not _col_exists(conn, 'homework_submission', 'rubric_scores_json'):
        op.add_column('homework_submission', sa.Column('rubric_scores_json', sa.Text(), nullable=True))
        print('[0030] homework_submission.rubric_scores_json 已加')


def downgrade():
    for name in ('ix_homework_rubric_id', 'ix_homework_rubric_teacher_id'):
        try:
            op.drop_index(name)
        except Exception:
            pass
    with op.batch_alter_table('homework_submission') as batch:
        batch.drop_column('rubric_scores_json')
    with op.batch_alter_table('homework') as batch:
        batch.drop_column('rubric_id')
    op.drop_table('homework_rubric')
