# -*- coding: utf-8 -*-
"""v5.16 作答防作弊监测：新表 homework_proctor_event + homework.enable_monitor 开关。

仅记录事件（只记不拦，不强制交卷），与考试 switch_count/强制交卷口径不同。
SQLite 省略 FK 约束；建表前先判存在（兼容 create_all 已建表）；加列用 _col_exists+PRAGMA 幂等。
"""
from alembic import op
import sqlalchemy as sa


revision = '0031_hw_proctor'
down_revision = '0030_hw_rubric'
branch_labels = None
depends_on = None


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind
    insp = sa.inspect(conn)

    # 1) 新表 homework_proctor_event（逐条监测事件）
    if 'homework_proctor_event' not in insp.get_table_names():
        op.create_table(
            'homework_proctor_event',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('homework_id', sa.Integer(), sa.ForeignKey('homework.id'), nullable=False),
            sa.Column('submission_id', sa.Integer(), sa.ForeignKey('homework_submission.id'), nullable=True),
            sa.Column('student_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('type', sa.String(length=20), nullable=False),
            sa.Column('at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_proctor_event_homework_id', 'homework_proctor_event', ['homework_id'])
        op.create_index('ix_proctor_event_submission_id', 'homework_proctor_event', ['submission_id'])
        op.create_index('ix_proctor_event_student_id', 'homework_proctor_event', ['student_id'])
        print('[0031] homework_proctor_event 已建')

    # 2) homework.enable_monitor（可选开关，默认关闭）
    if not _col_exists(conn, 'homework', 'enable_monitor'):
        op.add_column('homework', sa.Column(
            'enable_monitor', sa.Boolean(), nullable=False, server_default=sa.false()))
        print('[0031] homework.enable_monitor 已加')


def downgrade():
    for name in ('ix_proctor_event_student_id', 'ix_proctor_event_submission_id',
                 'ix_proctor_event_homework_id'):
        try:
            op.drop_index(name)
        except Exception:
            pass
    with op.batch_alter_table('homework') as batch:
        batch.drop_column('enable_monitor')
    op.drop_table('homework_proctor_event')
