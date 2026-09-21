"""OJ 评测铺垫：question.test_cases + answer.oj_verdict

- question 加 test_cases 列（JSON，可空；[{input, expected}] stdin/stdout 用例，
  NULL=编程题无自动评测，回落既有 AI/人工评分链路）
- answer 加 oj_verdict 列（String(10)，可空；AC/WA/TLE/RE，OJ 自动评测判定留痕）

加列用 PRAGMA table_info 判存在性，幂等可重复执行。

Revision ID: 0017_oj_test_cases
Revises: 0016_token_revocation
Create Date: 2026-09-21
"""
from sqlalchemy import text

from alembic import op

revision = '0017_oj_test_cases'
down_revision = '0016_token_revocation'
branch_labels = None
depends_on = None


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    cols = _existing_columns(conn, 'question')
    if 'test_cases' not in cols:
        conn.execute(text('ALTER TABLE question ADD COLUMN test_cases TEXT'))
        print('[0017] question.test_cases 列已添加')
    else:
        print('[0017] question.test_cases 已存在（幂等跳过）')
    cols = _existing_columns(conn, 'answer')
    if 'oj_verdict' not in cols:
        conn.execute(text('ALTER TABLE answer ADD COLUMN oj_verdict VARCHAR(10)'))
        print('[0017] answer.oj_verdict 列已添加')
    else:
        print('[0017] answer.oj_verdict 已存在（幂等跳过）')


def downgrade():
    # 可空列留档无害（旧逻辑不读这两列即等效无 OJ 功能）
    print('[0017 downgrade] test_cases/oj_verdict 列保留（可空列不影响旧逻辑）')
