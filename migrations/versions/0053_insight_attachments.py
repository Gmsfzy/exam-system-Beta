"""v7.24 心得文档附件：study_insight 增加 attachment_json

背景：心得从纯文本升级为「文档」编辑器（Markdown / 公式 / 化学式 / 代码 / 流程图 /
思维导图），并支持挂 Word/Excel/PPT/PDF/图片/视频等附件。笔记 v4.6 已有同形列，
心得这里补齐同名列（JSONType 底层 TEXT，与资料附件结构一致）。

Revision ID: 0053_insight_attachments
Revises: 0052_plan_repository
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = '0053_insight_attachments'
down_revision = '0052_plan_repository'
branch_labels = None
depends_on = None

TABLE = 'study_insight'
COL = 'attachment_json'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(TABLE):
        return
    cols = {c['name'] for c in insp.get_columns(TABLE)}
    if COL not in cols:
        op.add_column(TABLE, sa.Column(COL, sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(TABLE):
        return
    cols = {c['name'] for c in insp.get_columns(TABLE)}
    if COL in cols:
        op.drop_column(TABLE, COL)
