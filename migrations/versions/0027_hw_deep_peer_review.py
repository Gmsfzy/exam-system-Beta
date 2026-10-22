# -*- coding: utf-8 -*-
"""v5.9 深度互评：维度分/审核字段 + 作业互评截止与权重。

inspect 幂等：每列先判存在再添加，重复执行不报错。
SQLite 不支持 ALTER 加外键，audited_by 仅作普通整数列。
"""
from alembic import op
import sqlalchemy as sa


revision = '0027_hw_deep_peer_review'
down_revision = '0026_hw_template_series'


def _col_exists(conn, table, column):
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def _extend_daily_task_source(conn):
    """SQLite CHECK 约束无法 ALTER，重建 daily_task 放开 peer_review 来源。"""
    ddl = conn.execute(sa.text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='daily_task'")).scalar()
    if not ddl or 'peer_review' in (ddl or ''):
        return
    conn.execute(sa.text('PRAGMA foreign_keys=OFF'))
    conn.execute(sa.text('ALTER TABLE daily_task RENAME TO daily_task_old'))
    conn.execute(sa.text("""
        CREATE TABLE daily_task (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            day DATE NOT NULL,
            title VARCHAR(200) NOT NULL,
            source VARCHAR(20) NOT NULL,
            status VARCHAR(10) NOT NULL,
            done_at DATETIME,
            created_at DATETIME NOT NULL,
            CONSTRAINT _daily_source_ck CHECK (source IN ('manual', 'ai', 'peer_review')),
            CONSTRAINT _daily_status_ck CHECK (status IN ('pending', 'done'))
        )
    """))
    conn.execute(sa.text(
        'INSERT INTO daily_task (id, user_id, day, title, source, status, done_at, created_at) '
        'SELECT id, user_id, day, title, source, status, done_at, created_at FROM daily_task_old'))
    conn.execute(sa.text('DROP TABLE daily_task_old'))
    conn.execute(sa.text(
        'CREATE INDEX IF NOT EXISTS ix_daily_task_user_day ON daily_task (user_id, day)'))
    conn.execute(sa.text('PRAGMA foreign_keys=ON'))
    print('[0027] daily_task.source 已放开 peer_review')


def upgrade():
    bind = op.get_bind()
    conn = bind.connect() if hasattr(bind, 'connect') else bind

    if bind.dialect.name == 'sqlite':
        _extend_daily_task_source(conn)

    # 作业级：互评截止时间 / 权重 / 催办标记
    if not _col_exists(conn, 'homework', 'peer_review_deadline'):
        op.add_column('homework', sa.Column('peer_review_deadline', sa.DateTime(), nullable=True))
        print('[0027] homework.peer_review_deadline 已加')
    if not _col_exists(conn, 'homework', 'peer_review_weight'):
        op.add_column('homework', sa.Column('peer_review_weight', sa.Float(),
                                            nullable=False, server_default='0'))
        print('[0027] homework.peer_review_weight 已加')
    if not _col_exists(conn, 'homework', 'peer_review_reminded_at'):
        op.add_column('homework', sa.Column('peer_review_reminded_at', sa.DateTime(), nullable=True))
        print('[0027] homework.peer_review_reminded_at 已加')

    # 互评记录级：维度分 / 教师审核
    if not _col_exists(conn, 'homework_peer_review', 'scores_json'):
        op.add_column('homework_peer_review', sa.Column('scores_json', sa.Text(), nullable=True))
        print('[0027] homework_peer_review.scores_json 已加')
    if not _col_exists(conn, 'homework_peer_review', 'audit_status'):
        op.add_column('homework_peer_review', sa.Column('audit_status', sa.String(20),
                                                        nullable=False,
                                                        server_default='pending'))
        print('[0027] homework_peer_review.audit_status 已加')
    if not _col_exists(conn, 'homework_peer_review', 'teacher_comment'):
        op.add_column('homework_peer_review', sa.Column('teacher_comment', sa.Text(), nullable=True))
        print('[0027] homework_peer_review.teacher_comment 已加')
    if not _col_exists(conn, 'homework_peer_review', 'audited_by'):
        op.add_column('homework_peer_review', sa.Column('audited_by', sa.Integer(), nullable=True))
        print('[0027] homework_peer_review.audited_by 已加')
    if not _col_exists(conn, 'homework_peer_review', 'audited_at'):
        op.add_column('homework_peer_review', sa.Column('audited_at', sa.DateTime(), nullable=True))
        print('[0027] homework_peer_review.audited_at 已加')


def downgrade():
    for table, cols in (
        ('homework_peer_review', ('audited_at', 'audited_by', 'teacher_comment',
                                  'audit_status', 'scores_json')),
        ('homework', ('peer_review_reminded_at', 'peer_review_weight',
                      'peer_review_deadline')),
    ):
        with op.batch_alter_table(table) as batch:
            for col in cols:
                try:
                    batch.drop_column(col)
                except Exception:
                    pass
