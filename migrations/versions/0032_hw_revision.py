# -*- coding: utf-8 -*-
"""v5.17 订正重做闭环：homework.allow_revision 开关 + homework_submission.revision_round 轮次。

状态机扩展：SubmissionStatusEnum 新增 'returned'（String(10) 承载，无 DB 级 CHECK，无需改列）。
订正重做账务护栏：积分幂等键 homework-submit/homework-grade 保持 {hw}:{uid} 不含轮次，
退回重批天然不二次发分。加列用 _col_exists+PRAGMA 幂等，向后兼容（存量默认关闭/轮次 0）。
"""
from alembic import op
import sqlalchemy as sa


revision = '0032_hw_revision'
down_revision = '0031_hw_proctor'
branch_labels = None
depends_on = None


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind

    # 1) homework.allow_revision（订正重做开关，默认关闭）
    if not _col_exists(conn, 'homework', 'allow_revision'):
        op.add_column('homework', sa.Column(
            'allow_revision', sa.Boolean(), nullable=False, server_default=sa.false()))
        print('[0032] homework.allow_revision 已加')

    # 2) homework_submission.revision_round（退回订正轮次，默认 0）
    if not _col_exists(conn, 'homework_submission', 'revision_round'):
        op.add_column('homework_submission', sa.Column(
            'revision_round', sa.Integer(), nullable=False, server_default='0'))
        print('[0032] homework_submission.revision_round 已加')


def downgrade():
    with op.batch_alter_table('homework_submission') as batch:
        batch.drop_column('revision_round')
    with op.batch_alter_table('homework') as batch:
        batch.drop_column('allow_revision')
