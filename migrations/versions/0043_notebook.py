# -*- coding: utf-8 -*-
"""v6.6 代码笔记本：新建 notebook + notebook_cell 表（Jupyter 式分单元代码/Markdown 混排）。

幂等创建：先查 sqlite_master 判表存在性，避免 db.create_all() 先建后迁移冲突。

Revision ID: 0043_notebook
Revises: 0042_user_certificate
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '0043_notebook'
down_revision = '0042_user_certificate'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name):
    row = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {'n': table_name}).fetchone()
    return row is not None


def _create_index_safe(conn, index_name, table_name, columns):
    cols = ', '.join(f'"{c}"' for c in columns)
    conn.execute(text(
        f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ({cols})'
    ))


def upgrade():
    conn = op.get_bind()

    if not _table_exists(conn, 'notebook'):
        op.create_table(
            'notebook',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('title', sa.String(120), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('major_id', sa.Integer(), sa.ForeignKey('major.id'), nullable=True),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('course.id'), nullable=True),
            sa.Column('language', sa.String(20), nullable=False, server_default='python'),
            sa.Column('visibility', sa.String(12), nullable=False, server_default='private'),
            sa.Column('status', sa.String(12), nullable=False, server_default='active'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.CheckConstraint("visibility IN ('private', 'public')", name='_notebook_vis_ck'),
            sa.CheckConstraint("status IN ('active', 'archived')", name='_notebook_status_ck'),
        )
        print('[0043] notebook 已创建')
    else:
        print('[0043] notebook 已存在，跳过 create_table')

    if not _table_exists(conn, 'notebook_cell'):
        op.create_table(
            'notebook_cell',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('notebook_id', sa.Integer(), sa.ForeignKey('notebook.id'), nullable=False),
            sa.Column('order_num', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('cell_type', sa.String(12), nullable=False, server_default='code'),
            sa.Column('source', sa.Text(), nullable=True),
            sa.Column('language', sa.String(20), nullable=False, server_default='python'),
            sa.Column('outputs', sa.Text(), nullable=True),
            sa.Column('exec_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_run_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.CheckConstraint("cell_type IN ('code', 'markdown')", name='_nbcell_type_ck'),
        )
        print('[0043] notebook_cell 已创建')
    else:
        print('[0043] notebook_cell 已存在，跳过 create_table')

    for name, table, cols in [
        ('ix_notebook_user', 'notebook', ['user_id']),
        ('ix_nbcell_notebook_order', 'notebook_cell', ['notebook_id', 'order_num']),
    ]:
        _create_index_safe(conn, name, table, cols)

    print('[0043] 代码笔记本表迁移完成（幂等）')


def downgrade():
    conn = op.get_bind()
    if _table_exists(conn, 'notebook_cell'):
        op.drop_index('ix_nbcell_notebook_order', table_name='notebook_cell', if_exists=True)
        op.drop_table('notebook_cell')
        print('[0043 downgrade] notebook_cell 已删除')
    if _table_exists(conn, 'notebook'):
        op.drop_index('ix_notebook_user', table_name='notebook', if_exists=True)
        op.drop_table('notebook')
        print('[0043 downgrade] notebook 已删除')
