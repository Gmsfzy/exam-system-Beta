# -*- coding: utf-8 -*-
"""v5.20 批改批注：新表 homework_annotation（一份提交一条批注图层，upsert）。

教师在学生提交的图片/PDF 上绘制的画线批注，纯叠加层，与批改状态/total_score/ledger
完全正交（不改任何成绩字段）。shapes_json 存图形列表，坐标归一化（0~1），page 支持 PDF 多页。
写权限仅创建教师，学生/回评人只读回放。SQLite 省略 FK 约束；建表前判存在（兼容 create_all）。
"""
from alembic import op
import sqlalchemy as sa


revision = '0034_hw_annotation'
down_revision = '0033_hw_showcase'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind
    insp = sa.inspect(conn)

    if 'homework_annotation' not in insp.get_table_names():
        op.create_table(
            'homework_annotation',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('submission_id', sa.Integer(),
                      sa.ForeignKey('homework_submission.id'), nullable=False, unique=True),
            sa.Column('homework_id', sa.Integer(), sa.ForeignKey('homework.id'), nullable=False),
            sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('shapes_json', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_hw_annotation_submission_id', 'homework_annotation', ['submission_id'])
        op.create_index('ix_hw_annotation_homework_id', 'homework_annotation', ['homework_id'])
        print('[0034] homework_annotation 已建')


def downgrade():
    for name in ('ix_hw_annotation_homework_id', 'ix_hw_annotation_submission_id'):
        try:
            op.drop_index(name)
        except Exception:
            pass
    op.drop_table('homework_annotation')
