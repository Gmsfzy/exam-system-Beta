"""v7.25 社区微博化：community_notification 增加动态通知落点

新表（community_moment / _comment / _topic / _moment_topic / _moment_favorite）
由启动时 db.create_all() 幂等创建，无需迁移；本迁移只做 create_all 不会处理的
已有表 ALTER —— 给通知表补 moment_id / moment_comment_id 两个可空外键列。

Revision ID: 0054_community_moment_notify
Revises: 0053_insight_attachments
Create Date: 2026-11-17
"""
import sqlalchemy as sa
from alembic import op

revision = '0054_community_moment_notify'
down_revision = '0053_insight_attachments'
branch_labels = None
depends_on = None

TABLE = 'community_notification'
COLUMNS = ('moment_id', 'moment_comment_id')
INDEX = 'ix_community_notification_moment_id'


def _columns(insp):
    return {c['name'] for c in insp.get_columns(TABLE)}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(TABLE):
        return
    cols = _columns(insp)
    for col in COLUMNS:
        if col not in cols:
            # SQLite 不支持 ALTER 加外键约束；列本身可空，ORM 层已声明 FK，
            # 真实库（MySQL）由模型侧外键保证，此处只对齐列结构。
            op.add_column(TABLE, sa.Column(col, sa.Integer(), nullable=True))
    indexes = {i['name'] for i in insp.get_indexes(TABLE)}
    if INDEX not in indexes:
        op.create_index(INDEX, TABLE, ['moment_id'])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(TABLE):
        return
    indexes = {i['name'] for i in insp.get_indexes(TABLE)}
    if INDEX in indexes:
        op.drop_index(INDEX, table_name=TABLE)
    cols = _columns(insp)
    for col in COLUMNS:
        if col in cols:
            op.drop_column(TABLE, col)
