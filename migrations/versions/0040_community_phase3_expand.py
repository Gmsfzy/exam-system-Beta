# -*- coding: utf-8 -*-
"""v5.32 社区交流第三批扩充：班级圈子 / 悬赏 / 积分等级。

幂等：先查 PRAGMA table_info / sqlite_master，避免 db.create_all() 先建后迁移冲突。

Revision ID: 0040_community_expand3
Revises: 0039_community_expand2
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '0040_community_expand3'
down_revision = '0039_community_expand2'
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
        print(f'[0040] {table_name}.{name} 已存在，跳过')
        return
    conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {ddl}'))
    print(f'[0040] {table_name}.{name} 已新增')


def _create_index_safe(conn, index_name, table_name, columns, unique=False):
    cols = ', '.join(f'"{c}"' for c in columns)
    keyword = 'UNIQUE INDEX' if unique else 'INDEX'
    conn.execute(text(
        f'CREATE {keyword} IF NOT EXISTS "{index_name}" ON "{table_name}" ({cols})'
    ))


def upgrade():
    conn = op.get_bind()

    # ── community_post 扩充字段：班级圈子（课程）+ 悬赏 ──
    _add_column(conn, 'community_post', 'course_id', 'INTEGER')
    _add_column(conn, 'community_post', 'bounty_points', 'INTEGER NOT NULL DEFAULT 0')
    _add_column(conn, 'community_post', 'bounty_rewarded',
                'BOOLEAN NOT NULL DEFAULT 0')
    _create_index_safe(conn, 'ix_community_post_course', 'community_post', ['course_id'])

    # ── community_user_stat ──
    if not _table_exists(conn, 'community_user_stat'):
        op.create_table(
            'community_user_stat',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('points', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        print('[0040] community_user_stat 已创建')
    else:
        print('[0040] community_user_stat 已存在，跳过')

    _create_index_safe(conn, 'ix_community_user_stat_user', 'community_user_stat',
                       ['user_id'], unique=True)

    # ── community_point_log ──
    if not _table_exists(conn, 'community_point_log'):
        op.create_table(
            'community_point_log',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('delta', sa.Integer(), nullable=False),
            sa.Column('reason', sa.String(30), nullable=False),
            sa.Column('related_type', sa.String(20), nullable=True),
            sa.Column('related_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )
        print('[0040] community_point_log 已创建')
    else:
        print('[0040] community_point_log 已存在，跳过')

    for name, cols in [
        ('ix_community_point_log_user', ['user_id']),
        ('ix_community_point_log_created', ['created_at']),
    ]:
        _create_index_safe(conn, name, 'community_point_log', cols)

    print('[0040] 社区第三批扩充迁移完成（幂等）')


def downgrade():
    conn = op.get_bind()

    for table in ('community_point_log', 'community_user_stat'):
        if _table_exists(conn, table):
            op.drop_table(table)
            print(f'[0040 downgrade] {table} 已删除')

    for name in ('bounty_rewarded', 'bounty_points', 'course_id'):
        if name in _columns(conn, 'community_post'):
            conn.execute(text(f'ALTER TABLE "community_post" DROP COLUMN "{name}"'))

    print('[0040 downgrade] 社区第三批扩充字段清理完成')
