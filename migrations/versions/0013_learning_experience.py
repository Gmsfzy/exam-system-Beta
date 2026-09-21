"""0013 学习体验升级（v4.4）：新表 + 已有表幂等加列

新表：
- ai_chat_conversation   AI 学习助手会话（持久化多轮对话）
- ai_chat_message        AI 学习助手消息
- focus_session          专注计时会话（番茄钟/正计时）
- study_note             自由学习笔记（分类/标签/置顶）
- explain_card           知识点讲解卡（即问即讲）

加列：
- study_checkin       : mood / content（打卡心情与当日总结）
- wrong_answer_record : ai_analysis / ai_analyzed_at（逐题 AI 归因）

CREATE TABLE IF NOT EXISTS / PRAGMA 判列，全部幂等。

Revision ID: 0013_learning_experience
Revises: 0012_exam_upgrade
Create Date: 2026-09-19
"""
from sqlalchemy import text

from alembic import op

revision = '0013_learning_experience'
down_revision = '0012_exam_upgrade'
branch_labels = None
depends_on = None


_TABLES = [
    # AI 学习助手会话
    """
    CREATE TABLE IF NOT EXISTS ai_chat_conversation (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        title VARCHAR(100) NOT NULL DEFAULT '新的对话',
        context VARCHAR(60),
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        FOREIGN KEY(user_id) REFERENCES user (id)
    )
    """,
    # AI 学习助手消息（会话删除时级联清理）
    """
    CREATE TABLE IF NOT EXISTS ai_chat_message (
        id INTEGER NOT NULL PRIMARY KEY,
        conversation_id INTEGER NOT NULL,
        role VARCHAR(10) NOT NULL,
        content TEXT NOT NULL,
        degraded BOOLEAN NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES ai_chat_conversation (id)
    )
    """,
    # 专注计时会话
    """
    CREATE TABLE IF NOT EXISTS focus_session (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        topic VARCHAR(200),
        mode VARCHAR(10) NOT NULL DEFAULT 'pomodoro',
        planned_min INTEGER NOT NULL DEFAULT 25,
        actual_sec INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(10) NOT NULL DEFAULT 'running',
        started_at DATETIME NOT NULL,
        ended_at DATETIME,
        CONSTRAINT _focus_mode_ck CHECK (mode IN ('pomodoro', 'stopwatch')),
        CONSTRAINT _focus_status_ck CHECK (status IN ('running', 'dropped', 'finished')),
        FOREIGN KEY(user_id) REFERENCES user (id)
    )
    """,
    # 自由学习笔记
    """
    CREATE TABLE IF NOT EXISTS study_note (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        title VARCHAR(200) NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        category VARCHAR(50),
        tags TEXT,
        pinned BOOLEAN NOT NULL DEFAULT 0,
        source VARCHAR(10) NOT NULL DEFAULT 'manual',
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT _note_source_ck CHECK (source IN ('manual', 'explain')),
        FOREIGN KEY(user_id) REFERENCES user (id)
    )
    """,
    # 知识点讲解卡
    """
    CREATE TABLE IF NOT EXISTS explain_card (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        topic VARCHAR(200) NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        knowledge_point_id INTEGER,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_point (id)
    )
    """,
]

_INDEXES = [
    'CREATE INDEX IF NOT EXISTS ix_ai_conv_user_updated ON ai_chat_conversation (user_id, updated_at)',
    'CREATE INDEX IF NOT EXISTS ix_ai_msg_conv ON ai_chat_message (conversation_id, id)',
    'CREATE INDEX IF NOT EXISTS ix_focus_user_started ON focus_session (user_id, started_at)',
    'CREATE INDEX IF NOT EXISTS ix_study_note_user_updated ON study_note (user_id, updated_at)',
    'CREATE INDEX IF NOT EXISTS ix_explain_card_user_created ON explain_card (user_id, created_at)',
]

_NEW_COLUMNS = [
    ('study_checkin', [
        ('mood', 'VARCHAR(16)'),
        ('content', 'TEXT'),
    ]),
    ('wrong_answer_record', [
        ('ai_analysis', 'TEXT'),
        ('ai_analyzed_at', 'DATETIME'),
    ]),
]


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    for ddl in _TABLES:
        conn.execute(text(ddl))
    for ddl in _INDEXES:
        conn.execute(text(ddl))
    added = 0
    for table, cols in _NEW_COLUMNS:
        existing = _existing_columns(conn, table)
        for name, ddl in cols:
            if name not in existing:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))
                added += 1
    print(f'[0013] 学习体验升级：5 张新表 + {added} 列已就绪（幂等）')


def downgrade():
    # 新列可空/带默认，保留无害；新表按依赖倒序删除
    conn = op.get_bind()
    for table in ('explain_card', 'study_note', 'focus_session',
                  'ai_chat_message', 'ai_chat_conversation'):
        conn.execute(text(f'DROP TABLE IF EXISTS {table}'))
    print('[0013 downgrade] 新表已删除，加列保留（可空，不影响旧逻辑）')
