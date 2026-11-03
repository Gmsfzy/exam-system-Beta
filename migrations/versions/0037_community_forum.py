# -*- coding: utf-8 -*-
"""v5.29 社区交流 Phase 1 · 论坛 MVP：新建三张社区表。

幂等创建：先查 sqlite_master 判表存在性，避免 db.create_all() 先建后迁移冲突。

Revision ID: 0037_community_forum
Revises: 0036_question_tags
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '0037_community_forum'
down_revision = '0036_question_tags'
branch_labels = None
depends_on = None


def _table_exists(conn, table_name):
    row = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
    ), {'n': table_name}).fetchone()
    return row is not None


def _create_index_safe(conn, index_name, table_name, columns):
    """幂等建索引：SQLite CREATE INDEX IF NOT EXISTS"""
    cols = ', '.join(f'"{c}"' for c in columns)
    conn.execute(text(
        f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ({cols})'
    ))


def upgrade():
    conn = op.get_bind()

    # ── community_post ──
    if not _table_exists(conn, 'community_post'):
        op.create_table(
            'community_post',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('title', sa.String(100), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('category', sa.String(20), nullable=False, server_default='other'),
            sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('linked_type', sa.String(20), nullable=True),
            sa.Column('linked_id', sa.Integer(), nullable=True),
            sa.Column('is_anonymous', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('anon_index', sa.Integer(), nullable=True),
            sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('like_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('comment_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        print('[0037] community_post 已创建')
    else:
        print('[0037] community_post 已存在，跳过 create_table')

    for name, cols in [
        ('ix_community_post_author_created', ['author_id', 'created_at']),
        ('ix_community_post_category_created', ['category', 'created_at']),
        ('ix_community_post_linked', ['linked_type', 'linked_id']),
        ('ix_community_post_title', ['title']),
        ('ix_community_post_created', ['created_at']),
        ('ix_community_post_category', ['category']),
    ]:
        _create_index_safe(conn, name, 'community_post', cols)

    # ── community_comment ──
    if not _table_exists(conn, 'community_comment'):
        op.create_table(
            'community_comment',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('community_post.id'), nullable=False),
            sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('is_anonymous', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('anon_index', sa.Integer(), nullable=True),
            sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('like_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        print('[0037] community_comment 已创建')
    else:
        print('[0037] community_comment 已存在，跳过 create_table')

    for name, cols in [
        ('ix_community_comment_post', ['post_id']),
        ('ix_community_comment_author', ['author_id']),
        ('ix_community_comment_created', ['created_at']),
    ]:
        _create_index_safe(conn, name, 'community_comment', cols)

    # ── community_like ──
    if not _table_exists(conn, 'community_like'):
        op.create_table(
            'community_like',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('target_type', sa.String(10), nullable=False),
            sa.Column('target_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('target_type', 'target_id', 'user_id', name='_community_like_uc'),
        )
        print('[0037] community_like 已创建')
    else:
        print('[0037] community_like 已存在，跳过 create_table')

    for name, cols in [
        ('ix_community_like_target', ['target_type', 'target_id']),
        ('ix_community_like_user', ['user_id']),
    ]:
        _create_index_safe(conn, name, 'community_like', cols)

    print('[0037] 社区三张表迁移完成（幂等）')


def downgrade():
    conn = op.get_bind()

    if _table_exists(conn, 'community_like'):
        op.drop_index('ix_community_like_user', table_name='community_like', if_exists=True)
        op.drop_index('ix_community_like_target', table_name='community_like', if_exists=True)
        op.drop_table('community_like')
        print('[0037 downgrade] community_like 已删除')

    if _table_exists(conn, 'community_comment'):
        op.drop_index('ix_community_comment_created', table_name='community_comment', if_exists=True)
        op.drop_index('ix_community_comment_author', table_name='community_comment', if_exists=True)
        op.drop_index('ix_community_comment_post', table_name='community_comment', if_exists=True)
        op.drop_table('community_comment')
        print('[0037 downgrade] community_comment 已删除')

    if _table_exists(conn, 'community_post'):
        op.drop_index('ix_community_post_category', table_name='community_post', if_exists=True)
        op.drop_index('ix_community_post_created', table_name='community_post', if_exists=True)
        op.drop_index('ix_community_post_title', table_name='community_post', if_exists=True)
        op.drop_index('ix_community_post_linked', table_name='community_post', if_exists=True)
        op.drop_index('ix_community_post_category_created', table_name='community_post', if_exists=True)
        op.drop_index('ix_community_post_author_created', table_name='community_post', if_exists=True)
        op.drop_table('community_post')
        print('[0037 downgrade] community_post 已删除')

    print('[0037 downgrade] 社区三张表清理完成')
