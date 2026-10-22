# -*- coding: utf-8 -*-
"""v5.19 优秀作业展示墙：homework_submission 加精选状态三列。

showcase_status（none/nominated/featured，String(12)）+ showcase_anon（匿名展示 Bool）
+ showcase_at（状态变更时间 UTCDateTime）。与批改状态 SubmissionStatusEnum 正交，
纯新增展示维度，不改判分/账本。隐私口径：教师提名 → 学生同意才 featured 上墙。
加列用 _col_exists+PRAGMA 幂等，向后兼容（存量提交默认 none、不匿名、时间空）。
"""
from alembic import op
import sqlalchemy as sa


revision = '0033_hw_showcase'
down_revision = '0032_hw_revision'
branch_labels = None
depends_on = None


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind

    if not _col_exists(conn, 'homework_submission', 'showcase_status'):
        op.add_column('homework_submission', sa.Column(
            'showcase_status', sa.String(length=12), nullable=False, server_default='none'))
        print('[0033] homework_submission.showcase_status 已加')

    if not _col_exists(conn, 'homework_submission', 'showcase_anon'):
        op.add_column('homework_submission', sa.Column(
            'showcase_anon', sa.Boolean(), nullable=False, server_default=sa.false()))
        print('[0033] homework_submission.showcase_anon 已加')

    if not _col_exists(conn, 'homework_submission', 'showcase_at'):
        op.add_column('homework_submission', sa.Column(
            'showcase_at', sa.DateTime(), nullable=True))
        print('[0033] homework_submission.showcase_at 已加')


def downgrade():
    with op.batch_alter_table('homework_submission') as batch:
        batch.drop_column('showcase_at')
        batch.drop_column('showcase_anon')
        batch.drop_column('showcase_status')
