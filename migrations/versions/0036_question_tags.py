# -*- coding: utf-8 -*-
"""v5.23 题目标签系统：question 加可空 tags 列（JSONType，底层 TEXT）。

自由多维标签，纯组织/检索用途，与知识点（KnowledgePoint / Question.knowledge）正交，
不进掌握度/判分/推荐任何口径。SQLite 不支持 ADD COLUMN IF NOT EXISTS，
先用 PRAGMA table_info 判存在性，幂等加列；存量题 tags=NULL→序列化按 []。

Revision ID: 0036_question_tags
Revises: 0035_gradebook
Create Date: 2026-10-24
"""
from sqlalchemy import text

from alembic import op

revision = '0036_question_tags'
down_revision = '0035_gradebook'
branch_labels = None
depends_on = None


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    if 'tags' not in _existing_columns(conn, 'question'):
        conn.execute(text('ALTER TABLE question ADD COLUMN tags TEXT'))
        print('[0036] question.tags 已加（幂等）')
    else:
        print('[0036] question.tags 已存在，跳过')


def downgrade():
    # 可空列，保留无害（SQLite 老版本不支持 DROP COLUMN）
    print('[0036 downgrade] tags 列保留（可空，不影响旧逻辑）')
