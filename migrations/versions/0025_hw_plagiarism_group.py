"""0025 作业反抄袭 + 小组作业（v5.6 / v5.7）

v5.6：复用 oj/plagiarism.py 算法，无新增表（仅服务层接线）。
v5.7：
- homework 加 is_group 布尔列（默认 false）
- homework_submission 加 group_id 可空外键
- 新建 homework_group / homework_group_member 两表

幂等：建表/加列前 inspect 判存在（SQLite 无 ADD COLUMN IF NOT EXISTS，
加列用 PRAGMA table_info 检查）。

Revision ID: 0025_hw_plagiarism_group
Revises: 0024_hw_peer_review
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = '0025_hw_plagiarism_group'
down_revision = '0024_hw_peer_review'
branch_labels = None
depends_on = None


def _col_exists(conn, table, col):
    return any(r[1] == col for r in conn.execute(
        sa.text(f'PRAGMA table_info({table})')).fetchall())


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    names = insp.get_table_names()

    # homework.is_group
    if not _col_exists(conn, 'homework', 'is_group'):
        op.add_column('homework',
                      sa.Column('is_group', sa.Boolean(), nullable=False,
                                server_default=sa.false()))
        print('[0025] homework.is_group 已加')

    # homework_group
    if 'homework_group' not in names:
        op.create_table(
            'homework_group',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('homework_id', sa.Integer(),
                      sa.ForeignKey('homework.id'), nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False,
                      server_default='小组'),
            sa.Column('created_at', sa.TIMESTAMP(), nullable=False),
        )
        op.create_index('ix_homework_group_homework_id',
                        'homework_group', ['homework_id'])
        print('[0025] homework_group 就绪')

    # homework_group_member
    if 'homework_group_member' not in names:
        op.create_table(
            'homework_group_member',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('group_id', sa.Integer(),
                      sa.ForeignKey('homework_group.id'), nullable=False),
            sa.Column('student_id', sa.Integer(),
                      sa.ForeignKey('user.id'), nullable=False),
            sa.Column('joined_at', sa.TIMESTAMP(), nullable=False),
            sa.UniqueConstraint('group_id', 'student_id',
                                name='uq_hw_group_member_group_student'),
        )
        op.create_index('ix_homework_group_member_group_id',
                        'homework_group_member', ['group_id'])
        op.create_index('ix_homework_group_member_student_id',
                        'homework_group_member', ['student_id'])
        print('[0025] homework_group_member 就绪')

    # homework_submission.group_id（SQLite 不支持 ALTER 加 FK，省略外键约束，
    # 模型层 relationship 仍可用，且 SQLite 默认不强制外键）
    if not _col_exists(conn, 'homework_submission', 'group_id'):
        op.add_column('homework_submission',
                      sa.Column('group_id', sa.Integer(), nullable=True))
        op.create_index('ix_homework_submission_group_id',
                        'homework_submission', ['group_id'])
        print('[0025] homework_submission.group_id 已加')


def downgrade():
    for name in ('ix_homework_submission_group_id',):
        try:
            op.drop_index(name, table_name='homework_submission')
        except Exception:
            pass
    try:
        op.drop_column('homework_submission', 'group_id')
    except Exception:
        pass
    try:
        op.drop_column('homework', 'is_group')
    except Exception:
        pass
    for name in ('ix_homework_group_member_student_id',
                 'ix_homework_group_member_group_id'):
        try:
            op.drop_index(name, table_name='homework_group_member')
        except Exception:
            pass
    try:
        op.drop_table('homework_group_member')
    except Exception:
        pass
    try:
        op.drop_index('ix_homework_group_homework_id', table_name='homework_group')
    except Exception:
        pass
    try:
        op.drop_table('homework_group')
    except Exception:
        pass
