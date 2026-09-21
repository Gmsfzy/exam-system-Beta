"""0015 统一文件上传（v4.6）：已有表幂等加附件列

加列：
- bounty_submission : attachment_json（投稿附件列表 [{filename, stored_name, size, uploaded_at}]）
- study_note        : attachment_json（笔记附件列表，同结构）

附件本体落 uploads/（统一白名单 utils/uploads.py：文档/表格/压缩包/图片/视频/代码，≤50MB）。
SQLite 不支持 ADD COLUMN IF NOT EXISTS，先用 PRAGMA table_info 判存在性，幂等加列。

Revision ID: 0015_upload_attachments
Revises: 0014_learning_community
Create Date: 2026-09-19
"""
from sqlalchemy import text

from alembic import op

revision = '0015_upload_attachments'
down_revision = '0014_learning_community'
branch_labels = None
depends_on = None


_NEW_COLUMNS = [
    ('bounty_submission', [
        ('attachment_json', 'TEXT'),
    ]),
    ('study_note', [
        ('attachment_json', 'TEXT'),
    ]),
]


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    added = 0
    for table, cols in _NEW_COLUMNS:
        existing = _existing_columns(conn, table)
        for name, ddl in cols:
            if name not in existing:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
                added += 1
    print(f'[0015] 统一上传附件列已就绪（新增 {added} 列，幂等）')


def downgrade():
    # 可空列，保留无害（SQLite 老版本不支持 DROP COLUMN）
    print('[0015 downgrade] 列保留（可空，不影响旧逻辑）')
