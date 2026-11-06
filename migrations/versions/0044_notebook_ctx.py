"""v6.7 代码笔记本六模块接入：notebook 加上下文绑定与 fork 溯源列

- ctx_type / ctx_id：notebook 绑定到作业/考试/竞赛/悬赏上下文（get-or-create 复用口径）
- forked_from_id：社区公开本一键 fork 的来源溯源
- ix_notebook_ctx：按 (user_id, ctx_type, ctx_id) 快速定位上下文笔记本

加列用 PRAGMA table_info 判存在性，幂等可重复执行。

Revision ID: 0044_notebook_ctx
Revises: 0043_notebook
Create Date: 2026-11-06
"""
from sqlalchemy import text

from alembic import op

revision = '0044_notebook_ctx'
down_revision = '0043_notebook'
branch_labels = None
depends_on = None


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    existing = _existing_columns(conn, 'notebook')
    added = []
    if 'ctx_type' not in existing:
        conn.execute(text('ALTER TABLE notebook ADD COLUMN ctx_type VARCHAR(20)'))
        added.append('ctx_type')
    if 'ctx_id' not in existing:
        conn.execute(text('ALTER TABLE notebook ADD COLUMN ctx_id INTEGER'))
        added.append('ctx_id')
    if 'forked_from_id' not in existing:
        conn.execute(text('ALTER TABLE notebook ADD COLUMN forked_from_id INTEGER'))
        added.append('forked_from_id')
    if added:
        print(f'[0044] notebook 列已添加: {", ".join(added)}')
    else:
        print('[0044] notebook 上下文列已存在（幂等跳过）')
    conn.execute(text('CREATE INDEX IF NOT EXISTS ix_notebook_ctx ON notebook (user_id, ctx_type, ctx_id)'))
    print('[0044] 六模块接入迁移完成（幂等）')


def downgrade():
    # 可空列不影响旧逻辑，静默保留
    print('[0044 downgrade] 上下文列保留（可空列无害）')
