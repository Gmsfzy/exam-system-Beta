# -*- coding: utf-8 -*-
"""v6.1 竞赛段位加分：exam 表加 rank_bonus_tier / rank_bonus_score。

只加分、不免考。幂等：列存在则跳过。

Revision ID: 0041_rank_bonus
Revises: 0040_community_expand3
Create Date: 2026-11-04
"""
from alembic import op
from sqlalchemy import text


revision = '0041_rank_bonus'
down_revision = '0040_community_expand3'
branch_labels = None
depends_on = None


def _columns(conn, table_name):
    rows = conn.execute(text(f'PRAGMA table_info("{table_name}")')).fetchall()
    return {r[1] for r in rows}


def _add_column(conn, table_name, name, ddl):
    if name in _columns(conn, table_name):
        print(f'[0041] {table_name}.{name} 已存在，跳过')
        return
    conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {ddl}'))
    print(f'[0041] {table_name}.{name} 已新增')


def upgrade():
    conn = op.get_bind()
    _add_column(conn, 'exam', 'rank_bonus_tier', 'VARCHAR(20)')
    _add_column(conn, 'exam', 'rank_bonus_score', 'FLOAT NOT NULL DEFAULT 0')


def downgrade():
    # SQLite 不支持 DROP COLUMN，降级仅置空/归零
    conn = op.get_bind()
    conn.execute(text('UPDATE exam SET rank_bonus_tier = NULL, rank_bonus_score = 0'))
