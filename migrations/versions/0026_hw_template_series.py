# -*- coding: utf-8 -*-
"""v5.8 作业模板与系列化：homework_template / homework_series 两表 + homework.series_id。

inspect 幂等：每步先判存在再操作，重复执行不报错。
"""
from alembic import op
import sqlalchemy as sa


revision = '0026_hw_template_series'
down_revision = '0025_hw_plagiarism_group'


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind

    # homework.series_id（SQLite 省略 FK）
    if not _col_exists(conn, 'homework', 'series_id'):
        op.add_column('homework', sa.Column('series_id', sa.Integer(), nullable=True))
        op.create_index('ix_homework_series_id', 'homework', ['series_id'])
        print('[0026] homework.series_id 已加')

    # homework_template
    if not op.get_bind().dialect.has_table(conn, 'homework_template'):
        op.create_table(
            'homework_template',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('teacher_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('config_json', sa.Text(), nullable=False, server_default='{}'),
            sa.Column('settings_json', sa.Text(), nullable=False, server_default='{}'),
            sa.Column('roster_json', sa.Text()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_homework_template_teacher_id', 'homework_template', ['teacher_id'])
        print('[0026] homework_template 已建')

    # homework_series
    if not op.get_bind().dialect.has_table(conn, 'homework_series'):
        op.create_table(
            'homework_series',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('teacher_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('template_id', sa.Integer(), sa.ForeignKey('homework_template.id'), nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('start_at', sa.DateTime(), nullable=False),
            sa.Column('interval_hours', sa.Integer(), nullable=False, server_default='24'),
            sa.Column('count', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('generated_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_homework_series_teacher_id', 'homework_series', ['teacher_id'])
        op.create_index('ix_homework_series_template_id', 'homework_series', ['template_id'])
        print('[0026] homework_series 已建')


def downgrade():
    for name in ('ix_homework_series_template_id', 'ix_homework_series_teacher_id',
                 'ix_homework_template_teacher_id', 'ix_homework_series_id'):
        try:
            op.drop_index(name)
        except Exception:
            pass
    op.drop_table('homework_series')
    op.drop_table('homework_template')
    with op.batch_alter_table('homework') as batch:
        batch.drop_column('series_id')
