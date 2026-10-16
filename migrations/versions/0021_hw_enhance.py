"""0021 作业模块 v5.1 增强：homework.deadline 改可空（截止时间可选）+ 加及格线/参考资料列

- deadline       NOT NULL -> NULL  教师可选择不设截止时间（NULL=永不过期，随时可交）
- pass_score     FLOAT  NULL       及格线（用于统计及格率/优秀率）
- reference_json TEXT  NULL        教师参考资料附件元数据 {filename,stored_name,size,ext}

SQLite 不支持改列可空性，用 batch_alter_table(recreate='always') 重建表并原样搬运数据；
加列前先 PRAGMA table_info 判存在，保证幂等（兼容 create_all 已建新列的场景）。

Revision ID: 0021_hw_enhance
Revises: 0020_homework
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = '0021_hw_enhance'
down_revision = '0020_homework'
branch_labels = None
depends_on = None


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    existing = _existing_columns(conn, 'homework')
    with op.batch_alter_table('homework', recreate='always') as batch:
        # 截止时间改为可空
        batch.alter_column('deadline', existing_type=sa.TIMESTAMP(), nullable=True)
        # 幂等加列
        if 'pass_score' not in existing:
            batch.add_column(sa.Column('pass_score', sa.Float(), nullable=True))
        if 'reference_json' not in existing:
            batch.add_column(sa.Column('reference_json', sa.Text(), nullable=True))
    print('[0021] homework.deadline 可空 + pass_score/reference_json 就绪')


def downgrade():
    # 保留新列与可空性（无害），不回滚数据；deadline 可空对旧逻辑零影响
    print('[0021 downgrade] 保留列与可空约束，不做破坏性回滚')
