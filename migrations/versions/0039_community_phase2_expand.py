# -*- coding: utf-8 -*-
"""v5.31 社区交流第二批扩充：采纳答案 / 标签 / 投票帖。

幂等：先查 PRAGMA table_info / sqlite_master，避免 db.create_all() 先建后迁移冲突。

Revision ID: 0039_community_expand2
Revises: 0038_community_expand
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '0039_community_expand2'
down_revision = '0038_community_expand'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name):
    row = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {'n': table_name}).fetchone()
    return row is not None


def _columns(conn, table_name):
    rows = conn.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
    return {r[1] for r in rows}


def _add_column(conn, table_name, name, ddl):
    if name in _columns(conn, table_name):
        print(f'[0039] {table_name}.{name} 已存在，跳过')
        return
    conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {ddl}'))
    print(f'[0039] {table_name}.{name} 已新增')


def _create_index_safe(conn, index_name, table_name, columns, unique=False):
    cols = ', '.join(f'"{c}"' for c in columns)
    keyword = 'UNIQUE INDEX' if unique else 'INDEX'
    conn.execute(text(
        f'CREATE {keyword} IF NOT EXISTS "{index_name}" ON "{table_name}" ({cols})'
    ))


def upgrade():
    conn = op.get_bind()

    # ── community_post 扩充字段 ──
    _add_column(conn, 'community_post', 'accepted_comment_id', 'INTEGER')
    _add_column(conn, 'community_post', 'tags', 'VARCHAR(200)')
    _create_index_safe(conn, 'ix_community_post_accepted_comment',
                       'community_post', ['accepted_comment_id'])

    # ── community_poll_option ──
    if not _table_exists(conn, 'community_poll_option'):
        op.create_table(
            'community_poll_option',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('community_post.id'), nullable=False),
            sa.Column('text', sa.String(100), nullable=False),
            sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        print('[0039] community_poll_option 已创建')
    else:
        print('[0039] community_poll_option 已存在，跳过')

    for name, cols in [
        ('ix_community_poll_option_post', ['post_id']),
    ]:
        _create_index_safe(conn, name, 'community_poll_option', cols)

    # ── community_poll_vote ──
    if not _table_exists(conn, 'community_poll_vote'):
        op.create_table(
            'community_poll_vote',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('community_post.id'), nullable=False),
            sa.Column('option_id', sa.Integer(), sa.ForeignKey('community_poll_option.id'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('post_id', 'user_id', name='_community_poll_vote_uc'),
        )
        print('[0039] community_poll_vote 已创建')
    else:
        print('[0039] community_poll_vote 已存在，跳过')

    for name, cols, unique in [
        ('ix_community_poll_vote_post', ['post_id'], False),
        ('ix_community_poll_vote_option', ['option_id'], False),
        ('ix_community_poll_vote_user', ['user_id'], False),
        ('ix_community_poll_vote_post_user', ['post_id', 'user_id'], True),
    ]:
        _create_index_safe(conn, name, 'community_poll_vote', cols, unique=unique)

    print('[0039] 社区第二批扩充迁移完成（幂等）')


def downgrade():
    conn = op.get_bind()

    for table in ('community_poll_vote', 'community_poll_option'):
        if _table_exists(conn, table):
            op.drop_table(table)
            print(f'[0039 downgrade] {table} 已删除')

    for name in ('accepted_comment_id', 'tags'):
        if name in _columns(conn, 'community_post'):
            conn.execute(text(f'ALTER TABLE "community_post" DROP COLUMN "{name}"'))

    print('[0039 downgrade] 社区第二批扩充字段清理完成')
