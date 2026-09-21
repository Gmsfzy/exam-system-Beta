"""0014 学习社区升级（v4.5）：新表 + 已有表幂等加列

新表：
- study_folder              个人资料库文件夹（树形）
- study_material            个人学习资料（AI 生成多形态/手写，可公开到广场）
- material_favorite         资料收藏
- material_report           资料举报（教师核实下架）
- user_follow               关注关系（互关即好友）
- ai_usage_log              AI 调用日志（耗时/状态，成本治理）
- ai_quota                  AI 每日生成配额
- competition_announcement  赛事公告
- competition_resource      赛事资料包附件
- competition_work          作品型竞赛提交（一人一份，重交升版）

加列：
- competition : reviewer_id / reviewed_at / review_reason / prize_points / frozen_points
- bounty      : reviewer_id / reviewed_at / review_reason

CREATE TABLE IF NOT EXISTS / PRAGMA 判列，全部幂等。

Revision ID: 0014_learning_community
Revises: 0013_learning_experience
Create Date: 2026-09-19
"""
from sqlalchemy import text

from alembic import op

revision = '0014_learning_community'
down_revision = '0013_learning_experience'
branch_labels = None
depends_on = None


_TABLES = [
    # 个人资料库文件夹
    """
    CREATE TABLE IF NOT EXISTS study_folder (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        name VARCHAR(50) NOT NULL,
        parent_id INTEGER,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(parent_id) REFERENCES study_folder (id)
    )
    """,
    # 个人学习资料
    """
    CREATE TABLE IF NOT EXISTS study_material (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        folder_id INTEGER,
        kind VARCHAR(20) NOT NULL DEFAULT 'manual',
        title VARCHAR(200) NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        subject VARCHAR(50),
        difficulty VARCHAR(20),
        knowledge_point_id INTEGER,
        source VARCHAR(10) NOT NULL DEFAULT 'manual',
        is_public BOOLEAN NOT NULL DEFAULT 0,
        views INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(10) NOT NULL DEFAULT 'active',
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT _material_kind_ck CHECK (kind IN ('video_script', 'mindmap', 'lecture', 'summary', 'quiz', 'manual')),
        CONSTRAINT _material_source_ck CHECK (source IN ('manual', 'ai')),
        CONSTRAINT _material_status_ck CHECK (status IN ('active', 'removed')),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(folder_id) REFERENCES study_folder (id),
        FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_point (id)
    )
    """,
    # 资料收藏
    """
    CREATE TABLE IF NOT EXISTS material_favorite (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        material_id INTEGER NOT NULL,
        created_at DATETIME NOT NULL,
        CONSTRAINT _user_material_fav_uc UNIQUE (user_id, material_id),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(material_id) REFERENCES study_material (id)
    )
    """,
    # 资料举报
    """
    CREATE TABLE IF NOT EXISTS material_report (
        id INTEGER NOT NULL PRIMARY KEY,
        material_id INTEGER NOT NULL,
        reporter_id INTEGER NOT NULL,
        reason VARCHAR(200) NOT NULL DEFAULT '',
        status VARCHAR(10) NOT NULL DEFAULT 'pending',
        handler_id INTEGER,
        note VARCHAR(200),
        created_at DATETIME NOT NULL,
        handled_at DATETIME,
        CONSTRAINT _report_status_ck CHECK (status IN ('pending', 'removed', 'rejected')),
        FOREIGN KEY(material_id) REFERENCES study_material (id),
        FOREIGN KEY(reporter_id) REFERENCES user (id),
        FOREIGN KEY(handler_id) REFERENCES user (id)
    )
    """,
    # 关注关系
    """
    CREATE TABLE IF NOT EXISTS user_follow (
        id INTEGER NOT NULL PRIMARY KEY,
        follower_id INTEGER NOT NULL,
        followee_id INTEGER NOT NULL,
        created_at DATETIME NOT NULL,
        CONSTRAINT _user_follow_uc UNIQUE (follower_id, followee_id),
        CONSTRAINT _follow_not_self_ck CHECK (follower_id != followee_id),
        FOREIGN KEY(follower_id) REFERENCES user (id),
        FOREIGN KEY(followee_id) REFERENCES user (id)
    )
    """,
    # AI 调用日志
    """
    CREATE TABLE IF NOT EXISTS ai_usage_log (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        action VARCHAR(40) NOT NULL,
        status VARCHAR(10) NOT NULL DEFAULT 'success',
        cost_ms INTEGER NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL,
        CONSTRAINT _ai_log_status_ck CHECK (status IN ('success', 'degraded', 'fail')),
        FOREIGN KEY(user_id) REFERENCES user (id)
    )
    """,
    # AI 每日配额
    """
    CREATE TABLE IF NOT EXISTS ai_quota (
        user_id INTEGER NOT NULL PRIMARY KEY,
        daily_limit INTEGER NOT NULL DEFAULT 30,
        used_today INTEGER NOT NULL DEFAULT 0,
        reset_date DATE NOT NULL,
        FOREIGN KEY(user_id) REFERENCES user (id)
    )
    """,
    # 赛事公告
    """
    CREATE TABLE IF NOT EXISTS competition_announcement (
        id INTEGER NOT NULL PRIMARY KEY,
        competition_id INTEGER NOT NULL,
        title VARCHAR(100) NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        created_by INTEGER NOT NULL,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(competition_id) REFERENCES competition (id),
        FOREIGN KEY(created_by) REFERENCES user (id)
    )
    """,
    # 赛事资料包附件
    """
    CREATE TABLE IF NOT EXISTS competition_resource (
        id INTEGER NOT NULL PRIMARY KEY,
        competition_id INTEGER NOT NULL,
        title VARCHAR(200) NOT NULL,
        filename VARCHAR(200) NOT NULL,
        stored_name VARCHAR(200) NOT NULL,
        size INTEGER NOT NULL DEFAULT 0,
        uploaded_by INTEGER NOT NULL,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(competition_id) REFERENCES competition (id),
        FOREIGN KEY(uploaded_by) REFERENCES user (id)
    )
    """,
    # 作品型竞赛提交
    """
    CREATE TABLE IF NOT EXISTS competition_work (
        id INTEGER NOT NULL PRIMARY KEY,
        competition_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        filename VARCHAR(200),
        stored_name VARCHAR(200),
        size INTEGER NOT NULL DEFAULT 0,
        version INTEGER NOT NULL DEFAULT 1,
        score FLOAT,
        review_note TEXT,
        scored_by INTEGER,
        scored_at DATETIME,
        submitted_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT _comp_work_uc UNIQUE (competition_id, user_id),
        FOREIGN KEY(competition_id) REFERENCES competition (id),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(scored_by) REFERENCES user (id)
    )
    """,
]

_INDEXES = [
    'CREATE INDEX IF NOT EXISTS ix_folder_user ON study_folder (user_id)',
    'CREATE INDEX IF NOT EXISTS ix_material_user_updated ON study_material (user_id, updated_at)',
    'CREATE INDEX IF NOT EXISTS ix_material_public ON study_material (is_public, status)',
    'CREATE INDEX IF NOT EXISTS ix_report_status ON material_report (status, created_at)',
    'CREATE INDEX IF NOT EXISTS ix_follow_followee ON user_follow (followee_id)',
    'CREATE INDEX IF NOT EXISTS ix_ai_log_user_created ON ai_usage_log (user_id, created_at)',
    'CREATE INDEX IF NOT EXISTS ix_comp_announce_comp ON competition_announcement (competition_id)',
    'CREATE INDEX IF NOT EXISTS ix_comp_resource_comp ON competition_resource (competition_id)',
]

_NEW_COLUMNS = [
    ('competition', [
        ('reviewer_id', 'INTEGER'),
        ('reviewed_at', 'DATETIME'),
        ('review_reason', 'VARCHAR(200)'),
        ('prize_points', 'INTEGER'),
        ('frozen_points', 'INTEGER'),
    ]),
    ('bounty', [
        ('reviewer_id', 'INTEGER'),
        ('reviewed_at', 'DATETIME'),
        ('review_reason', 'VARCHAR(200)'),
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
    print(f'[0014] 学习社区升级：10 张新表 + {added} 列已就绪（幂等）')


def downgrade():
    # 新列可空/带默认，保留无害；新表按依赖倒序删除
    conn = op.get_bind()
    for table in ('competition_work', 'competition_resource', 'competition_announcement',
                  'ai_quota', 'ai_usage_log', 'user_follow',
                  'material_report', 'material_favorite', 'study_material', 'study_folder'):
        conn.execute(text(f'DROP TABLE IF EXISTS {table}'))
    print('[0014 downgrade] 新表已删除，加列保留（可空，不影响旧逻辑）')
