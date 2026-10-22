"""0023 作业讨论区（v5.4）：homework_comment

- 作业级讨论（question_id 为空）或按题讨论（question_id 指向 question）
- parent_id 一层回复；deleted_at 软删除保留楼层
- is_teacher 发帖时身份快照

幂等：建表前 inspect 判存在（兼容 create_all 已建表场景）。

Revision ID: 0023_hw_comment
Revises: 0022_hw_ai_review
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = '0023_hw_comment'
down_revision = '0022_hw_ai_review'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'homework_comment' in insp.get_table_names():
        print('[0023] homework_comment 已存在，跳过')
        return
    op.create_table(
        'homework_comment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('homework_id', sa.Integer(),
                  sa.ForeignKey('homework.id'), nullable=False),
        sa.Column('question_id', sa.Integer(),
                  sa.ForeignKey('question.id'), nullable=True),
        sa.Column('parent_id', sa.Integer(),
                  sa.ForeignKey('homework_comment.id'), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_teacher', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('created_at', sa.TIMESTAMP(), nullable=False),
        sa.Column('deleted_at', sa.TIMESTAMP(), nullable=True),
    )
    op.create_index('ix_homework_comment_homework_id',
                    'homework_comment', ['homework_id'])
    op.create_index('ix_homework_comment_question_id',
                    'homework_comment', ['question_id'])
    op.create_index('ix_homework_comment_parent_id',
                    'homework_comment', ['parent_id'])
    op.create_index('ix_homework_comment_user_id',
                    'homework_comment', ['user_id'])
    print('[0023] homework_comment 就绪')


def downgrade():
    for name in ('ix_homework_comment_user_id', 'ix_homework_comment_parent_id',
                 'ix_homework_comment_question_id', 'ix_homework_comment_homework_id'):
        op.drop_index(name, table_name='homework_comment')
    op.drop_table('homework_comment')
