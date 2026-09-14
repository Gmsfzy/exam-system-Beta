"""0001 基线：表结构继续由 db.create_all() 管理，本迁移仅作版本锚点

历史背景：项目在引入 Flask-Migrate 之前已用 create_all + 手工 ALTER 建表，
存量库无需重建表结构；0002 开始承担数据级迁移。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-07
"""
revision = '0001_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
