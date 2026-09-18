"""0007 学习闭环与知识库：掌握度/笔记/小测/复习/打卡/证书 6 张新表 + 任务进度列

支撑"学-练-测-沉淀"闭环：
- knowledge_mastery    知识点掌握度（答题驱动，展示按遗忘曲线衰减）
- user_kp_note         个人知识笔记（每知识点一篇总结，upsert）
- quiz_attempt         轻量小测尝试（节点小测/路径终测）
- quiz_attempt_answer  小测单题作答
- review_item          间隔复习卡（简化 SM-2 排期）
- study_checkin        学习打卡（连击天数）
- path_certificate     路径结业证书
- daily_task           每日学习任务（用户自建 / AI 建议采纳）
- study_plan_task      加 progress_count / auto_done 列（practice 型任务自动核销）

全新表 CREATE TABLE IF NOT EXISTS 幂等；加列用 PRAGMA table_info 判存在性。

Revision ID: 0007_learning_closed_loop
Revises: 0006_path_plan_fields
Create Date: 2026-09-18
"""
from sqlalchemy import text

from alembic import op

revision = '0007_learning_closed_loop'
down_revision = '0006_path_plan_fields'
branch_labels = None
depends_on = None


_TABLES = [
    # 知识点掌握度
    """
    CREATE TABLE IF NOT EXISTS knowledge_mastery (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        knowledge_point_id INTEGER NOT NULL,
        level FLOAT NOT NULL DEFAULT 0.0,
        last_verified_at DATETIME NOT NULL,
        total_attempts INTEGER NOT NULL DEFAULT 0,
        total_correct INTEGER NOT NULL DEFAULT 0,
        updated_at DATETIME NOT NULL,
        CONSTRAINT _user_kp_mastery_uc UNIQUE (user_id, knowledge_point_id),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_point (id)
    )
    """,
    # 个人知识笔记
    """
    CREATE TABLE IF NOT EXISTS user_kp_note (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        knowledge_point_id INTEGER NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT _user_kp_note_uc UNIQUE (user_id, knowledge_point_id),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_point (id)
    )
    """,
    # 轻量小测尝试
    """
    CREATE TABLE IF NOT EXISTS quiz_attempt (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        scope_type VARCHAR(20) NOT NULL,
        node_id INTEGER,
        path_id INTEGER,
        question_ids TEXT,
        questions_count INTEGER NOT NULL DEFAULT 0,
        correct_count INTEGER NOT NULL DEFAULT 0,
        score_ratio FLOAT,
        status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
        started_at DATETIME NOT NULL,
        completed_at DATETIME,
        CONSTRAINT _quiz_scope_ck CHECK (scope_type IN ('node', 'path_final')),
        CONSTRAINT _quiz_status_ck CHECK (status IN ('in_progress', 'completed')),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(node_id) REFERENCES learning_path_node (id),
        FOREIGN KEY(path_id) REFERENCES learning_path (id)
    )
    """,
    # 小测单题作答
    """
    CREATE TABLE IF NOT EXISTS quiz_attempt_answer (
        id INTEGER NOT NULL PRIMARY KEY,
        attempt_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        student_answer TEXT,
        is_correct BOOLEAN,
        answered_at DATETIME NOT NULL,
        FOREIGN KEY(attempt_id) REFERENCES quiz_attempt (id),
        FOREIGN KEY(question_id) REFERENCES question (id)
    )
    """,
    # 间隔复习卡
    """
    CREATE TABLE IF NOT EXISTS review_item (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        interval_days INTEGER NOT NULL DEFAULT 1,
        repetitions INTEGER NOT NULL DEFAULT 0,
        ease FLOAT NOT NULL DEFAULT 2.5,
        due_at DATETIME NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        source_type VARCHAR(20) NOT NULL DEFAULT 'wrong',
        created_at DATETIME NOT NULL,
        CONSTRAINT _user_review_uc UNIQUE (user_id, question_id),
        CONSTRAINT _review_status_ck CHECK (status IN ('pending', 'retired')),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(question_id) REFERENCES question (id)
    )
    """,
    # 学习打卡
    """
    CREATE TABLE IF NOT EXISTS study_checkin (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        day DATE NOT NULL,
        minutes INTEGER NOT NULL DEFAULT 0,
        tasks_done INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL,
        CONSTRAINT _user_day_checkin_uc UNIQUE (user_id, day),
        FOREIGN KEY(user_id) REFERENCES user (id)
    )
    """,
    # 路径结业证书
    """
    CREATE TABLE IF NOT EXISTS path_certificate (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        path_id INTEGER NOT NULL,
        serial_no VARCHAR(32) NOT NULL UNIQUE,
        final_score FLOAT NOT NULL DEFAULT 0.0,
        summary TEXT,
        earned_at DATETIME NOT NULL,
        CONSTRAINT _user_path_cert_uc UNIQUE (user_id, path_id),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(path_id) REFERENCES learning_path (id)
    )
    """,
    # 每日学习任务
    """
    CREATE TABLE IF NOT EXISTS daily_task (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        day DATE NOT NULL,
        title VARCHAR(200) NOT NULL,
        source VARCHAR(10) NOT NULL DEFAULT 'manual',
        status VARCHAR(10) NOT NULL DEFAULT 'pending',
        done_at DATETIME,
        created_at DATETIME NOT NULL,
        CONSTRAINT _daily_source_ck CHECK (source IN ('manual', 'ai')),
        CONSTRAINT _daily_status_ck CHECK (status IN ('pending', 'done')),
        FOREIGN KEY(user_id) REFERENCES user (id)
    )
    """,
]

_INDEXES = [
    'CREATE INDEX IF NOT EXISTS ix_mastery_user ON knowledge_mastery (user_id)',
    'CREATE INDEX IF NOT EXISTS ix_note_user ON user_kp_note (user_id)',
    'CREATE INDEX IF NOT EXISTS ix_quiz_user_scope ON quiz_attempt (user_id, scope_type)',
    'CREATE INDEX IF NOT EXISTS ix_quiz_answer_attempt ON quiz_attempt_answer (attempt_id)',
    'CREATE INDEX IF NOT EXISTS ix_review_user_due ON review_item (user_id, status, due_at)',
    'CREATE INDEX IF NOT EXISTS ix_checkin_user_day ON study_checkin (user_id, day)',
    'CREATE INDEX IF NOT EXISTS ix_daily_task_user_day ON daily_task (user_id, day)',
]

# study_plan_task 自动核销支持列
_TASK_COLUMNS = [
    ('progress_count', 'INTEGER NOT NULL DEFAULT 0'),
    ('auto_done', 'BOOLEAN NOT NULL DEFAULT 0'),
]


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def upgrade():
    conn = op.get_bind()
    for ddl in _TABLES:
        conn.execute(text(ddl))
    print(f'[0007] {len(_TABLES)} 张学习闭环表已就绪（IF NOT EXISTS 幂等）')

    for ddl in _INDEXES:
        conn.execute(text(ddl))
    print(f'[0007] {len(_INDEXES)} 个索引已就绪')

    existing = _existing_columns(conn, 'study_plan_task')
    added = 0
    for name, ddl in _TASK_COLUMNS:
        if name not in existing:
            conn.execute(text(f'ALTER TABLE study_plan_task ADD COLUMN {name} {ddl}'))
            added += 1
    print(f'[0007] study_plan_task 自动核销列已就绪（新增 {added} 列，幂等）')


def downgrade():
    conn = op.get_bind()
    for table in reversed(['daily_task', 'path_certificate', 'study_checkin', 'review_item',
                           'quiz_attempt_answer', 'quiz_attempt', 'user_kp_note',
                           'knowledge_mastery']):
        conn.execute(text(f'DROP TABLE IF EXISTS {table}'))
    print('[0007 downgrade] 学习闭环新表已删除（study_plan_task 列保留）')
