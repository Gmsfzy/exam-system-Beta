"""v6.9 OJ 多语言：question 加 language 列（判分按语言选适配器）

- language：python/java/javascript（阶段 2 扩 c/cpp），默认 python 兼容存量编程题。

⚠️ 方言可移植（v6.8 约束）：本迁移会被现存 PostgreSQL 库实跑（0044→0045 升级），
故严禁使用 PRAGMA/sqlite_master；用 sa.inspect(bind).get_columns 判存在性，
add_column 带 server_default 让存量行回填 'python'。

Revision ID: 0045_question_language
Revises: 0044_notebook_ctx
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = '0045_question_language'
down_revision = '0044_notebook_ctx'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if 'language' not in _columns(bind, 'question'):
        op.add_column('question', sa.Column('language', sa.String(20), nullable=False,
                                             server_default='python'))
        print('[0045] question.language 已添加（默认 python）')
    else:
        print('[0045] question.language 已存在（幂等跳过）')


def downgrade():
    bind = op.get_bind()
    if 'language' in _columns(bind, 'question'):
        with op.batch_alter_table('question') as batch_op:
            batch_op.drop_column('language')
        print('[0045 downgrade] question.language 已删除')
