# -*- coding: utf-8 -*-
"""v6.4 证书中心：新建 user_certificate 表（社会/第三方证书，用户上传+教师核验）。

幂等创建：先查 sqlite_master 判表存在性，避免 db.create_all() 先建后迁移冲突。

Revision ID: 0042_user_certificate
Revises: 0041_rank_bonus
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '0042_user_certificate'
down_revision = '0041_rank_bonus'
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

    if not _table_exists(conn, 'user_certificate'):
        op.create_table(
            'user_certificate',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('category', sa.String(20), nullable=False, server_default='other'),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('issuer', sa.String(120), nullable=True),
            sa.Column('cert_no', sa.String(80), nullable=True),
            sa.Column('serial_no', sa.String(32), nullable=False),
            sa.Column('grade', sa.String(60), nullable=True),
            sa.Column('earned_date', sa.DateTime(), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('file_name', sa.String(120), nullable=True),
            sa.Column('file_orig', sa.String(200), nullable=True),
            sa.Column('file_size', sa.Integer(), nullable=True),
            sa.Column('verify_status', sa.String(12), nullable=False, server_default='pending'),
            sa.Column('verify_note', sa.String(200), nullable=True),
            sa.Column('verified_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('verified_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('serial_no', name='_usercert_serial_uc'),
            sa.CheckConstraint(
                "category IN ('language', 'it', 'practice', 'academic', 'award', 'other')",
                name='_usercert_category_ck'),
            sa.CheckConstraint(
                "verify_status IN ('pending', 'verified', 'rejected')",
                name='_usercert_verify_ck'),
        )
        print('[0042] user_certificate 已创建')
    else:
        print('[0042] user_certificate 已存在，跳过 create_table')

    for name, cols in [
        ('ix_usercert_user', ['user_id']),
        ('ix_usercert_status', ['verify_status']),
    ]:
        _create_index_safe(conn, name, 'user_certificate', cols)

    print('[0042] 社会证书表迁移完成（幂等）')


def downgrade():
    conn = op.get_bind()
    if _table_exists(conn, 'user_certificate'):
        op.drop_index('ix_usercert_status', table_name='user_certificate', if_exists=True)
        op.drop_index('ix_usercert_user', table_name='user_certificate', if_exists=True)
        op.drop_table('user_certificate')
        print('[0042 downgrade] user_certificate 已删除')
