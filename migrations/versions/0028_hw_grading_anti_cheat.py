# -*- coding: utf-8 -*-
"""v5.11 作业批改提效与防抄：迟交扣分 / 匿名批改 / 分级提醒 / 乱序防抄。

全部为 homework 与 homework_submission 加列，均有默认值或可空，向后兼容。
inspect 幂等：每列先判存在再添加，重复执行不报错。JSON 列以 Text 承载（对齐 0027）。
"""
from alembic import op
import sqlalchemy as sa


revision = '0028_hw_grading_anti_cheat'
down_revision = '0027_hw_deep_peer_review'


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind

    # 作业级：迟交扣分 / 匿名批改 / 分级提醒 / 乱序开关
    if not _col_exists(conn, 'homework', 'late_penalty_pct'):
        op.add_column('homework', sa.Column('late_penalty_pct', sa.Float(),
                                            nullable=False, server_default='0'))
        print('[0028] homework.late_penalty_pct 已加')
    if not _col_exists(conn, 'homework', 'blind_grading'):
        op.add_column('homework', sa.Column('blind_grading', sa.Boolean(),
                                            nullable=False, server_default='0'))
        print('[0028] homework.blind_grading 已加')
    if not _col_exists(conn, 'homework', 'remind_levels_json'):
        op.add_column('homework', sa.Column('remind_levels_json', sa.Text(), nullable=True))
        print('[0028] homework.remind_levels_json 已加')
    if not _col_exists(conn, 'homework', 'reminded_json'):
        op.add_column('homework', sa.Column('reminded_json', sa.Text(), nullable=True))
        print('[0028] homework.reminded_json 已加')
    if not _col_exists(conn, 'homework', 'shuffle_questions'):
        op.add_column('homework', sa.Column('shuffle_questions', sa.Boolean(),
                                            nullable=False, server_default='0'))
        print('[0028] homework.shuffle_questions 已加')
    if not _col_exists(conn, 'homework', 'shuffle_options'):
        op.add_column('homework', sa.Column('shuffle_options', sa.Boolean(),
                                            nullable=False, server_default='0'))
        print('[0028] homework.shuffle_options 已加')

    # 提交级：扣分前总分 / 乱序题序与选项映射
    if not _col_exists(conn, 'homework_submission', 'score_before_penalty'):
        op.add_column('homework_submission', sa.Column('score_before_penalty', sa.Float(),
                                                       nullable=True))
        print('[0028] homework_submission.score_before_penalty 已加')
    if not _col_exists(conn, 'homework_submission', 'assigned_order_json'):
        op.add_column('homework_submission', sa.Column('assigned_order_json', sa.Text(),
                                                       nullable=True))
        print('[0028] homework_submission.assigned_order_json 已加')
    if not _col_exists(conn, 'homework_submission', 'option_map_json'):
        op.add_column('homework_submission', sa.Column('option_map_json', sa.Text(),
                                                       nullable=True))
        print('[0028] homework_submission.option_map_json 已加')


def downgrade():
    for table, cols in (
        ('homework_submission', ('option_map_json', 'assigned_order_json',
                                 'score_before_penalty')),
        ('homework', ('shuffle_options', 'shuffle_questions', 'reminded_json',
                      'remind_levels_json', 'blind_grading', 'late_penalty_pct')),
    ):
        with op.batch_alter_table(table) as batch:
            for col in cols:
                try:
                    batch.drop_column(col)
                except Exception:
                    pass
