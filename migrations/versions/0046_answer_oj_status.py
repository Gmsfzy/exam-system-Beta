"""v7.0 阶段 3 异步评测队列：answer 加 oj_status/oj_attempts 列

- oj_status：pending/grading/done/failed（NULL=同步链路，历史行为不变）；
- oj_attempts：后台评测尝试次数，异常回炉重放的终止判据。

⚠️ 方言可移植（v6.8 约束）：严禁 PRAGMA/sqlite_master；
用 sa.inspect(bind).get_columns 判存在性，add_column 带 server_default 让存量行回填 0/NULL。

Revision ID: 0046_answer_oj_status
Revises: 0045_question_language
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = '0046_answer_oj_status'
down_revision = '0045_question_language'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    cols = _columns(bind, 'answer')
    if 'oj_status' not in cols:
        op.add_column('answer', sa.Column('oj_status', sa.String(10), nullable=True))
        print('[0046] answer.oj_status 已添加')
    else:
        print('[0046] answer.oj_status 已存在（幂等跳过）')
    if 'oj_attempts' not in cols:
        op.add_column('answer', sa.Column('oj_attempts', sa.Integer(), nullable=False,
                                          server_default='0'))
        print('[0046] answer.oj_attempts 已添加（默认 0）')
    else:
        print('[0046] answer.oj_attempts 已存在（幂等跳过）')


def downgrade():
    bind = op.get_bind()
    cols = _columns(bind, 'answer')
    with op.batch_alter_table('answer') as batch_op:
        if 'oj_attempts' in cols:
            batch_op.drop_column('oj_attempts')
        if 'oj_status' in cols:
            batch_op.drop_column('oj_status')
    print('[0046 downgrade] answer 异步评测列已删除')
