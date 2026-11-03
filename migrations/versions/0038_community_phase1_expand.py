# -*- coding: utf-8 -*-
"""v5.30 社区交流第一批扩充：收藏 / 楼中楼 / 通知 / 举报折叠 / 已解决。

幂等：先查 PRAGMA table_info / sqlite_master，避免 db.create_all() 先建后迁移冲突。

Revision ID: 0038_community_expand
Revises: 0037_community_forum
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '0038_community_expand'
down_revision = '0037_community_forum'
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
        print(f'[0038] {table_name}.{name} 已存在，跳过')
        return
    conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {ddl}'))
    print(f'[0038] {table_name}.{name} 已新增')


def _create_index_safe(conn, index_name, table_name, columns):
    cols = ', '.join(f'"{c}"' for c in columns)
    conn.execute(text(
        f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}" ({cols})'
    ))


def upgrade():
    conn = op.get_bind()

    # ── community_post 扩充字段 ──
    _add_column(conn, 'community_post', 'favorite_count',
                'INTEGER NOT NULL DEFAULT 0')
    _add_column(conn, 'community_post', 'is_resolved',
                'BOOLEAN NOT NULL DEFAULT 0')
    _add_column(conn, 'community_post', 'resolved_at', 'DATETIME')
    _add_column(conn, 'community_post', 'resolved_by', 'INTEGER')
    _add_column(conn, 'community_post', 'hidden', 'BOOLEAN NOT NULL DEFAULT 0')
    _add_column(conn, 'community_post', 'report_count',
                'INTEGER NOT NULL DEFAULT 0')

    # ── community_comment 扩充字段 ──
    _add_column(conn, 'community_comment', 'parent_id', 'INTEGER')
    _add_column(conn, 'community_comment', 'hidden', 'BOOLEAN NOT NULL DEFAULT 0')
    _add_column(conn, 'community_comment', 'report_count',
                'INTEGER NOT NULL DEFAULT 0')
    _create_index_safe(conn, 'ix_community_comment_parent', 'community_comment', ['parent_id'])

    # ── community_favorite ──
    if not _table_exists(conn, 'community_favorite'):
        op.create_table(
            'community_favorite',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('community_post.id'), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('post_id', 'user_id', name='_community_favorite_uc'),
        )
        print('[0038] community_favorite 已创建')
    else:
        print('[0038] community_favorite 已存在，跳过')

    for name, cols in [
        ('ix_community_favorite_post', ['post_id']),
        ('ix_community_favorite_user', ['user_id']),
        ('ix_community_favorite_created', ['created_at']),
    ]:
        _create_index_safe(conn, name, 'community_favorite', cols)

    # ── community_notification ──
    if not _table_exists(conn, 'community_notification'):
        op.create_table(
            'community_notification',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('type', sa.String(20), nullable=False),
            sa.Column('post_id', sa.Integer(), sa.ForeignKey('community_post.id'), nullable=True),
            sa.Column('comment_id', sa.Integer(), sa.ForeignKey('community_comment.id'), nullable=True),
            sa.Column('content', sa.String(200), nullable=True),
            sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        print('[0038] community_notification 已创建')
    else:
        print('[0038] community_notification 已存在，跳过')

    for name, cols in [
        ('ix_community_notification_user', ['user_id']),
        ('ix_community_notification_type', ['type']),
        ('ix_community_notification_post', ['post_id']),
        ('ix_community_notification_read', ['is_read']),
        ('ix_community_notification_created', ['created_at']),
        ('ix_community_notification_user_read', ['user_id', 'is_read', 'created_at']),
    ]:
        _create_index_safe(conn, name, 'community_notification', cols)

    # ── community_report ──
    if not _table_exists(conn, 'community_report'):
        op.create_table(
            'community_report',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('target_type', sa.String(10), nullable=False),
            sa.Column('target_id', sa.Integer(), nullable=False),
            sa.Column('reporter_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('reason', sa.String(200), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('handled_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('handled_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('target_type', 'target_id', 'reporter_id', name='_community_report_uc'),
        )
        print('[0038] community_report 已创建')
    else:
        print('[0038] community_report 已存在，跳过')

    for name, cols in [
        ('ix_community_report_target_type', ['target_type']),
        ('ix_community_report_target_id', ['target_id']),
        ('ix_community_report_reporter', ['reporter_id']),
        ('ix_community_report_status', ['status']),
        ('ix_community_report_created', ['created_at']),
        ('ix_community_report_status_created', ['status', 'created_at']),
    ]:
        _create_index_safe(conn, name, 'community_report', cols)

    print('[0038] 社区第一批扩充迁移完成（幂等）')


def downgrade():
    conn = op.get_bind()

    for table in ('community_report', 'community_notification', 'community_favorite'):
        if _table_exists(conn, table):
            op.drop_table(table)
            print(f'[0038 downgrade] {table} 已删除')

    for name in ('parent_id', 'hidden', 'report_count'):
        if name in _columns(conn, 'community_comment'):
            conn.execute(text(f'ALTER TABLE "community_comment" DROP COLUMN "{name}"'))
    for name in ('favorite_count', 'is_resolved', 'resolved_at', 'resolved_by', 'hidden', 'report_count'):
        if name in _columns(conn, 'community_post'):
            conn.execute(text(f'ALTER TABLE "community_post" DROP COLUMN "{name}"'))

    print('[0038 downgrade] 社区第一批扩充字段清理完成')
