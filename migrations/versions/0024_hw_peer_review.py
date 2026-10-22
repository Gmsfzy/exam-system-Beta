"""0024 生生互评（v5.5）：homework_peer_review

- submission_id + reviewer_id 唯一约束，防重复分配/重复提交
- status pending/submitted；score 0-100 百分制；不改官方总分
- 匿名：被评学生不可见 reviewer 身份，教师端完整可见

幂等：建表前 inspect 判存在（兼容 create_all 已建表场景）。

Revision ID: 0024_hw_peer_review
Revises: 0023_hw_comment
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = '0024_hw_peer_review'
down_revision = '0023_hw_comment'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'homework_peer_review' in insp.get_table_names():
        print('[0024] homework_peer_review 已存在，跳过')
        return
    op.create_table(
        'homework_peer_review',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('homework_id', sa.Integer(),
                  sa.ForeignKey('homework.id'), nullable=False),
        sa.Column('submission_id', sa.Integer(),
                  sa.ForeignKey('homework_submission.id'), nullable=False),
        sa.Column('reviewer_id', sa.Integer(),
                  sa.ForeignKey('user.id'), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='pending'),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False),
        sa.Column('submitted_at', sa.TIMESTAMP(), nullable=True),
        sa.UniqueConstraint('submission_id', 'reviewer_id',
                            name='uq_hw_peer_review_sub_reviewer'),
    )
    op.create_index('ix_homework_peer_review_homework_id',
                    'homework_peer_review', ['homework_id'])
    op.create_index('ix_homework_peer_review_submission_id',
                    'homework_peer_review', ['submission_id'])
    op.create_index('ix_homework_peer_review_reviewer_id',
                    'homework_peer_review', ['reviewer_id'])
    print('[0024] homework_peer_review 就绪')


def downgrade():
    for name in ('ix_homework_peer_review_reviewer_id',
                 'ix_homework_peer_review_submission_id',
                 'ix_homework_peer_review_homework_id'):
        op.drop_index(name, table_name='homework_peer_review')
    op.drop_table('homework_peer_review')
