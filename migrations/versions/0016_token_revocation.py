"""令牌吊销水位：user.token_valid_at

- user 加 token_valid_at 列（DATETIME，可空；登出时置为当前 UTC，
  早于该时刻签发的 JWT 在 verify_token 一律失效，NULL=从未吊销）

加列用 PRAGMA table_info 判存在性，幂等可重复执行。

Revision ID: 0016_token_revocation
Revises: 0015_upload_attachments
Create Date: 2026-09-21
"""
from sqlalchemy import text

from alembic import op

revision = '0016_token_revocation'
down_revision = '0015_upload_attachments'
branch_labels = None
depends_on = None


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    existing = _existing_columns(conn, 'user')
    if 'token_valid_at' not in existing:
        conn.execute(text('ALTER TABLE "user" ADD COLUMN token_valid_at DATETIME'))
        print('[0016] user.token_valid_at 列已添加')
    else:
        print('[0016] user.token_valid_at 已存在（幂等跳过）')


def downgrade():
    # 可空列留档无害（旧逻辑不读该列即等效从未吊销）
    print('[0016 downgrade] token_valid_at 列保留（可空列不影响旧逻辑）')
