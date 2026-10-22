# -*- coding: utf-8 -*-
"""v5.14 作业多种评分制：numeric | level | comment（仅显示层派生）。

仅 homework 加两列，均有默认/可空，向后兼容；不改 total_score/积分/错题口径。
inspect 幂等：每列先判存在再添加，重复执行不报错。JSON 列以 Text 承载（对齐 0027/0028）。
"""
from alembic import op
import sqlalchemy as sa


revision = '0029_hw_grade_mode'
down_revision = '0028_hw_grading_anti_cheat'


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind

    if not _col_exists(conn, 'homework', 'grade_mode'):
        op.add_column('homework', sa.Column('grade_mode', sa.String(length=10),
                                            nullable=False, server_default='numeric'))
        print('[0029] homework.grade_mode 已加')
    if not _col_exists(conn, 'homework', 'grade_scale_json'):
        op.add_column('homework', sa.Column('grade_scale_json', sa.Text(), nullable=True))
        print('[0029] homework.grade_scale_json 已加')


def downgrade():
    with op.batch_alter_table('homework') as batch:
        for col in ('grade_scale_json', 'grade_mode'):
            try:
                batch.drop_column(col)
            except Exception:
                pass
