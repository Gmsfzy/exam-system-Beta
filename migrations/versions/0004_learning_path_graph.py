"""0004 学习路径与知识图谱：8 张新表

专业学习路径 + 知识图谱模块（一期 MVP）数据表：
- question_knowledge_point  题目-知识点多对多关联
- knowledge_point           知识点实体
- knowledge_edge            知识点关系边
- learning_path             专业学习路径
- learning_path_node        路径节点
- user_path_enrollment      用户选课
- user_node_progress        用户节点进度
- learning_resource         学习资源

全部为全新表，CREATE TABLE IF NOT EXISTS 幂等（create_all 在迁移前已建表时直接跳过）。

Revision ID: 0004_learning_path_graph
Revises: 0003_schema_refactor
Create Date: 2026-09-17
"""
from sqlalchemy import text

from alembic import op

revision = '0004_learning_path_graph'
down_revision = '0003_schema_refactor'
branch_labels = None
depends_on = None


_TABLES = [
    # 题目-知识点 多对多关联（复合主键天然防重复）
    """
    CREATE TABLE IF NOT EXISTS question_knowledge_point (
        question_id INTEGER NOT NULL,
        knowledge_point_id INTEGER NOT NULL,
        PRIMARY KEY (question_id, knowledge_point_id),
        FOREIGN KEY(question_id) REFERENCES question (id),
        FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_point (id)
    )
    """,
    # 知识点实体（挂章节，章内同名唯一；软删用 status=deprecated）
    """
    CREATE TABLE IF NOT EXISTS knowledge_point (
        id INTEGER NOT NULL PRIMARY KEY,
        chapter_id INTEGER NOT NULL,
        name VARCHAR(80) NOT NULL,
        description TEXT,
        order_num INTEGER,
        difficulty VARCHAR(20) NOT NULL DEFAULT 'easy',
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        created_at DATETIME NOT NULL,
        CONSTRAINT _chapter_kp_uc UNIQUE (chapter_id, name),
        FOREIGN KEY(chapter_id) REFERENCES chapter (id)
    )
    """,
    # 知识点关系边（source 前置 → target 后继；同向同类型唯一）
    """
    CREATE TABLE IF NOT EXISTS knowledge_edge (
        id INTEGER NOT NULL PRIMARY KEY,
        source_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        relation_type VARCHAR(20) NOT NULL DEFAULT 'prerequisite',
        weight FLOAT,
        created_at DATETIME NOT NULL,
        CONSTRAINT _edge_uc UNIQUE (source_id, target_id, relation_type),
        FOREIGN KEY(source_id) REFERENCES knowledge_point (id),
        FOREIGN KEY(target_id) REFERENCES knowledge_point (id)
    )
    """,
    # 专业学习路径（草稿/发布/归档三态，同专业同标题同版本唯一）
    """
    CREATE TABLE IF NOT EXISTS learning_path (
        id INTEGER NOT NULL PRIMARY KEY,
        major_id INTEGER NOT NULL,
        title VARCHAR(100) NOT NULL,
        description TEXT,
        target_hours INTEGER,
        difficulty VARCHAR(20),
        version VARCHAR(20) NOT NULL DEFAULT 'v1',
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        creator_id INTEGER,
        created_at DATETIME NOT NULL,
        updated_at DATETIME,
        CONSTRAINT _path_uc UNIQUE (major_id, title, version),
        FOREIGN KEY(major_id) REFERENCES major (id),
        FOREIGN KEY(creator_id) REFERENCES user (id)
    )
    """,
    # 路径节点（知识点/章节二选一，路径内顺序号唯一）
    """
    CREATE TABLE IF NOT EXISTS learning_path_node (
        id INTEGER NOT NULL PRIMARY KEY,
        path_id INTEGER NOT NULL,
        node_type VARCHAR(20) NOT NULL DEFAULT 'knowledge_point',
        knowledge_point_id INTEGER,
        chapter_id INTEGER,
        order_num INTEGER NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'core',
        estimated_minutes INTEGER,
        CONSTRAINT _node_ref_check CHECK (knowledge_point_id IS NOT NULL OR chapter_id IS NOT NULL),
        CONSTRAINT _path_node_order_uc UNIQUE (path_id, order_num),
        FOREIGN KEY(path_id) REFERENCES learning_path (id),
        FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_point (id),
        FOREIGN KEY(chapter_id) REFERENCES chapter (id)
    )
    """,
    # 用户选课（同用户同路径仅一条；total_count 为入学时节点总数快照）
    """
    CREATE TABLE IF NOT EXISTS user_path_enrollment (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        path_id INTEGER NOT NULL,
        enrolled_at DATETIME NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        current_node_id INTEGER,
        completed_count INTEGER,
        total_count INTEGER,
        completed_at DATETIME,
        CONSTRAINT _enroll_uc UNIQUE (user_id, path_id),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(path_id) REFERENCES learning_path (id),
        FOREIGN KEY(current_node_id) REFERENCES learning_path_node (id)
    )
    """,
    # 用户节点进度（同用户同节点仅一条；path_id 冗余便于按路径聚合）
    """
    CREATE TABLE IF NOT EXISTS user_node_progress (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        path_id INTEGER NOT NULL,
        node_id INTEGER NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'not_started',
        started_at DATETIME,
        mastered_at DATETIME,
        time_spent_sec INTEGER,
        attempts_count INTEGER,
        CONSTRAINT _user_node_uc UNIQUE (user_id, node_id),
        FOREIGN KEY(user_id) REFERENCES user (id),
        FOREIGN KEY(path_id) REFERENCES learning_path (id),
        FOREIGN KEY(node_id) REFERENCES learning_path_node (id)
    )
    """,
    # 学习资源（挂知识点或章节；text/video/exercise/external_link）
    """
    CREATE TABLE IF NOT EXISTS learning_resource (
        id INTEGER NOT NULL PRIMARY KEY,
        title VARCHAR(120) NOT NULL,
        type VARCHAR(20) NOT NULL DEFAULT 'text',
        content TEXT,
        url VARCHAR(500),
        knowledge_point_id INTEGER,
        chapter_id INTEGER,
        creator_id INTEGER,
        order_num INTEGER,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_point (id),
        FOREIGN KEY(chapter_id) REFERENCES chapter (id),
        FOREIGN KEY(creator_id) REFERENCES user (id)
    )
    """,
]

_INDEXES = [
    'CREATE INDEX IF NOT EXISTS ix_qkp_question ON question_knowledge_point (question_id)',
    'CREATE INDEX IF NOT EXISTS ix_qkp_kp ON question_knowledge_point (knowledge_point_id)',
    'CREATE INDEX IF NOT EXISTS ix_kp_chapter ON knowledge_point (chapter_id)',
    'CREATE INDEX IF NOT EXISTS ix_kp_name ON knowledge_point (name)',
    'CREATE INDEX IF NOT EXISTS ix_edge_source ON knowledge_edge (source_id)',
    'CREATE INDEX IF NOT EXISTS ix_edge_target ON knowledge_edge (target_id)',
    'CREATE INDEX IF NOT EXISTS ix_path_major_status ON learning_path (major_id, status)',
    'CREATE INDEX IF NOT EXISTS ix_path_node_path ON learning_path_node (path_id)',
    'CREATE INDEX IF NOT EXISTS ix_enroll_user ON user_path_enrollment (user_id)',
    'CREATE INDEX IF NOT EXISTS ix_unp_user_path ON user_node_progress (user_id, path_id)',
]


def _table_exists(conn, table):
    row = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
    ), {'t': table}).fetchone()
    return row is not None


def upgrade():
    conn = op.get_bind()
    created = 0
    for ddl in _TABLES:
        conn.execute(text(ddl))
        created += 1
    print(f'[0004] {created} 张路径/图谱表已就绪（IF NOT EXISTS 幂等）')

    for ddl in _INDEXES:
        conn.execute(text(ddl))
    print(f'[0004] {len(_INDEXES)} 个索引已就绪')


def downgrade():
    conn = op.get_bind()
    # 子表在前、父表在后
    for table in ('learning_resource', 'user_node_progress', 'user_path_enrollment',
                  'learning_path_node', 'learning_path', 'knowledge_edge',
                  'knowledge_point', 'question_knowledge_point'):
        if _table_exists(conn, table):
            conn.execute(text(f'DROP TABLE {table}'))
            print(f'[0004 downgrade] 已删除表 {table}')
