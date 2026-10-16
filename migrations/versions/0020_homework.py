"""作业练习模块（v5.0）：新建 homework/homework_question/homework_student/homework_submission/homework_answer 5 表

纯新增表，无既有表加列、无数据回填：旧逻辑零感知。
CREATE TABLE IF NOT EXISTS 幂等建表（兼容 create_all 先后顺序，规范同 0019）。
附件 JSON 列以 TEXT 存储（同 attachment_json 惯例），布尔列 BOOLEAN。

Revision ID: 0020_homework
Revises: 0019_data_science
Create Date: 2026-10-16
"""
from sqlalchemy import text

from alembic import op

revision = '0020_homework'
down_revision = '0019_data_science'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS homework (
            id INTEGER NOT NULL PRIMARY KEY,
            title VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            hw_type VARCHAR(20) NOT NULL DEFAULT 'question_set',
            teacher_id INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            deadline DATETIME NOT NULL,
            allow_late BOOLEAN NOT NULL DEFAULT 1,
            allow_resubmit BOOLEAN NOT NULL DEFAULT 1,
            remind_before INTEGER NOT NULL DEFAULT 0,
            reminded_at DATETIME,
            created_at DATETIME NOT NULL,
            published_at DATETIME,
            FOREIGN KEY(teacher_id) REFERENCES user (id)
        )
        """
    ))
    conn.execute(text('CREATE INDEX IF NOT EXISTS ix_homework_teacher_id ON homework (teacher_id)'))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS homework_question (
            homework_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            score FLOAT NOT NULL DEFAULT 1.0,
            "order" INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (homework_id, question_id),
            FOREIGN KEY(homework_id) REFERENCES homework (id),
            FOREIGN KEY(question_id) REFERENCES question (id)
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS homework_student (
            homework_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            assigned_at DATETIME NOT NULL,
            PRIMARY KEY (homework_id, student_id),
            FOREIGN KEY(homework_id) REFERENCES homework (id),
            FOREIGN KEY(student_id) REFERENCES user (id)
        )
        """
    ))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS homework_submission (
            id INTEGER NOT NULL PRIMARY KEY,
            homework_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'draft',
            content TEXT NOT NULL DEFAULT '',
            attachment_json TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            is_late BOOLEAN NOT NULL DEFAULT 0,
            submitted_at DATETIME,
            total_score FLOAT,
            max_score FLOAT,
            comment TEXT,
            graded_by INTEGER,
            graded_at DATETIME,
            UNIQUE (homework_id, student_id),
            FOREIGN KEY(homework_id) REFERENCES homework (id),
            FOREIGN KEY(student_id) REFERENCES user (id),
            FOREIGN KEY(graded_by) REFERENCES user (id)
        )
        """
    ))
    conn.execute(text('CREATE INDEX IF NOT EXISTS ix_homework_submission_homework_id '
                      'ON homework_submission (homework_id)'))
    conn.execute(text('CREATE INDEX IF NOT EXISTS ix_homework_submission_student_id '
                      'ON homework_submission (student_id)'))

    conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS homework_answer (
            id INTEGER NOT NULL PRIMARY KEY,
            submission_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            answer TEXT NOT NULL DEFAULT '',
            auto_score FLOAT,
            manual_score FLOAT,
            is_correct BOOLEAN,
            oj_verdict VARCHAR(10),
            needs_manual_grade BOOLEAN NOT NULL DEFAULT 0,
            comment TEXT,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(submission_id) REFERENCES homework_submission (id),
            FOREIGN KEY(question_id) REFERENCES question (id)
        )
        """
    ))
    conn.execute(text('CREATE INDEX IF NOT EXISTS ix_homework_answer_submission_id '
                      'ON homework_answer (submission_id)'))
    print('[0020] 作业练习 5 表结构就绪')


def downgrade():
    # 保留表（旧逻辑不读取即等效无作业模块），不做破坏性删除
    print('[0020 downgrade] homework 表保留（无害，不回滚数据）')
