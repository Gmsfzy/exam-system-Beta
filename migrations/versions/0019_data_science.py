"""数据科学竞赛（v4.11）：competition DS 列 + dataset/dataset_file/ds_submission/ds_notebook_run

- competition 增 DS 赛道列（幂等加列，PRAGMA table_info 判存在）
- 建 4 张新表（CREATE TABLE IF NOT EXISTS，兼容 create_all 先后顺序）
  dataset / dataset_file（gold 文件 is_downloadable=0 隐藏答案）
  ds_submission（预测提交 + 公/私榜分）
  ds_notebook_run（在线编写运行留痕）

无数据回填：新表空、DS 列可空或带默认值，不影响既有 TIMED/PK/PROJECT。

Revision ID: 0019_data_science
Revises: 0018_ledger_unify
Create Date: 2026-09-21
"""
from sqlalchemy import text

from alembic import op

revision = '0019_data_science'
down_revision = '0018_ledger_unify'
branch_labels = None
depends_on = None


def _existing_columns(conn, table):
    rows = conn.execute(text(f'PRAGMA table_info({table})')).fetchall()
    return {r[1] for r in rows}


def _add_col(conn, table, col, ddl):
    if col not in _existing_columns(conn, table):
        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {ddl}'))
        print(f'[0019] {table}.{col} 列已添加')
    else:
        print(f'[0019] {table}.{col} 已存在（幂等跳过）')


def upgrade():
    conn = op.get_bind()

    # 1) competition DS 赛道列
    _add_col(conn, 'competition', 'ds_metric', 'ds_metric VARCHAR(20)')
    _add_col(conn, 'competition', 'ds_higher_is_better', 'ds_higher_is_better BOOLEAN')
    _add_col(conn, 'competition', 'ds_id_column', 'ds_id_column VARCHAR(50)')
    _add_col(conn, 'competition', 'ds_target_column', 'ds_target_column VARCHAR(50)')
    _add_col(conn, 'competition', 'ds_public_ratio',
             'ds_public_ratio FLOAT NOT NULL DEFAULT 0.3')
    _add_col(conn, 'competition', 'ds_daily_limit',
             'ds_daily_limit INTEGER NOT NULL DEFAULT 5')
    _add_col(conn, 'competition', 'ds_scorer_code', 'ds_scorer_code TEXT')

    # 2) 数据集 / 数据集文件
    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS dataset (
            id INTEGER NOT NULL PRIMARY KEY,
            competition_id INTEGER,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(competition_id) REFERENCES competition (id),
            FOREIGN KEY(owner_id) REFERENCES user (id)
        )
        """
    ))
    conn.execute(text(
        'CREATE INDEX IF NOT EXISTS ix_dataset_competition_id ON dataset (competition_id)'
    ))
    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS dataset_file (
            id INTEGER NOT NULL PRIMARY KEY,
            dataset_id INTEGER NOT NULL,
            role VARCHAR(10) NOT NULL,
            filename VARCHAR(200) NOT NULL,
            stored_name VARCHAR(200) NOT NULL,
            size INTEGER NOT NULL,
            is_downloadable BOOLEAN NOT NULL,
            uploaded_by INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(dataset_id) REFERENCES dataset (id),
            FOREIGN KEY(uploaded_by) REFERENCES user (id)
        )
        """
    ))
    conn.execute(text(
        'CREATE INDEX IF NOT EXISTS ix_dataset_file_dataset_id ON dataset_file (dataset_id)'
    ))

    # 3) 预测提交
    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS ds_submission (
            id INTEGER NOT NULL PRIMARY KEY,
            competition_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            kind VARCHAR(10) NOT NULL,
            filename VARCHAR(200),
            stored_name VARCHAR(200) NOT NULL,
            public_score FLOAT,
            private_score FLOAT,
            status VARCHAR(10) NOT NULL,
            error_msg VARCHAR(300),
            version INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            scored_at DATETIME,
            FOREIGN KEY(competition_id) REFERENCES competition (id),
            FOREIGN KEY(user_id) REFERENCES user (id)
        )
        """
    ))
    conn.execute(text(
        'CREATE INDEX IF NOT EXISTS ix_ds_submission_competition_id ON ds_submission (competition_id)'
    ))
    conn.execute(text(
        'CREATE INDEX IF NOT EXISTS ix_ds_submission_user_id ON ds_submission (user_id)'
    ))

    # 4) 在线运行留痕
    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS ds_notebook_run (
            id INTEGER NOT NULL PRIMARY KEY,
            competition_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            stdout TEXT NOT NULL,
            stderr TEXT NOT NULL,
            exit_code INTEGER,
            timed_out BOOLEAN NOT NULL,
            rejected VARCHAR(200),
            produced_submission TEXT,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(competition_id) REFERENCES competition (id),
            FOREIGN KEY(user_id) REFERENCES user (id)
        )
        """
    ))
    conn.execute(text(
        'CREATE INDEX IF NOT EXISTS ix_ds_notebook_run_competition_id ON ds_notebook_run (competition_id)'
    ))
    conn.execute(text(
        'CREATE INDEX IF NOT EXISTS ix_ds_notebook_run_user_id ON ds_notebook_run (user_id)'
    ))
    print('[0019] 数据科学竞赛表结构就绪')


def downgrade():
    # 保留表与可空列（旧逻辑不读取即等效无 DS 功能），仅提示，不做破坏性删除
    print('[0019 downgrade] DS 表与列保留（无害，不回滚数据）')
