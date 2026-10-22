"""0022 作业模块 v5.3：AI 讲评表 homework_ai_review

- scope='class'      班级共性分析（每份作业一行，published_at 非空才对学生可见）
- scope='submission' 学生单份讲评（每份提交一行）
- content_json / stats_json 存 AI 结构化讲评与统计快照；degraded 标记 AI 失败降级

幂等：建表前先 inspect 判存在（兼容 create_all 已建表场景）。

Revision ID: 0022_hw_ai_review
Revises: 0021_hw_enhance
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = '0022_hw_ai_review'
down_revision = '0021_hw_enhance'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'homework_ai_review' in insp.get_table_names():
        print('[0022] homework_ai_review 已存在，跳过')
        return
    op.create_table(
        'homework_ai_review',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('homework_id', sa.Integer(),
                  sa.ForeignKey('homework.id'), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('scope_key', sa.String(length=40), nullable=False),
        sa.Column('submission_id', sa.Integer(),
                  sa.ForeignKey('homework_submission.id'), nullable=True),
        sa.Column('content_json', sa.Text(), nullable=True),
        sa.Column('stats_json', sa.Text(), nullable=True),
        sa.Column('model', sa.String(length=50), nullable=True),
        sa.Column('degraded', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(), nullable=False),
        sa.Column('published_at', sa.TIMESTAMP(), nullable=True),
        sa.UniqueConstraint('homework_id', 'scope_key', name='uq_hw_ai_review_scope'),
    )
    op.create_index('ix_homework_ai_review_homework_id',
                    'homework_ai_review', ['homework_id'])
    print('[0022] homework_ai_review 就绪')


def downgrade():
    op.drop_index('ix_homework_ai_review_homework_id',
                  table_name='homework_ai_review')
    op.drop_table('homework_ai_review')
