"""0002 一次性数据迁移：历史时间列时区归一化（本地 UTC+8 -> UTC）

写入点审计结论（代码路径分析 + 现库数据核对，2026-09-07）：
- 「UTC 列」：模型 default=datetime.utcnow 写入，历史上就是 UTC → 不动
- 「本地列」：datetime.now() / 表单 datetime-local 写入，
  为 Asia/Shanghai 墙上时间 → 整列 -8h 归一为 UTC
- 「混合列」result.submitted_at 与 exam_session.end_time：
  - 正常提交路径（exam_execution.routes）写本地时间
  - app.py 自动结束路径写 _utcnow()（UTC），且两列来自同一 now 对象，
    微秒完全相同 —— 以此作为行级判别依据
中国无夏令时，固定 +8h；本迁移幂等靠哨兵表 tz_migration_v1 保证。

Revision ID: 0002_tz_normalize
Revises: 0001_baseline
Create Date: 2026-09-07
"""
import datetime as dt

from sqlalchemy import text

from alembic import op

revision = '0002_tz_normalize'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None

_SHIFT = dt.timedelta(hours=8)
_FORMATS = ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S')

# 历史上即 UTC 的列（default=utcnow 写入），无需转换
UTC_COLUMNS = [
    ('user', 'created_at'),
    ('question', 'created_at'),
    ('exam', 'created_at'),
    ('exam_student', 'invited_at'),
    ('notification', 'created_at'),
    ('competition', 'created_at'),
    ('competition_participant', 'created_at'),
    ('competition_answer', 'answered_at'),
    ('pk_battle', 'created_at'),
    ('pk_answer', 'answered_at'),
    ('user_points_profile', 'updated_at'),
    ('season_archive', 'created_at'),
    ('user_badge', 'granted_at'),
    ('team', 'created_at'),
    ('team_member', 'joined_at'),
]

# 历史上为本地时间（Asia/Shanghai）的列，需 -8h
LOCAL_COLUMNS = [
    ('exam', 'start_time'),
    ('exam', 'end_time'),
    ('exam_session', 'start_time'),
    ('competition', 'start_time'),
    ('competition', 'end_time'),
    ('competition_participant', 'started_at'),
    ('competition_participant', 'finished_at'),
    ('pk_battle', 'started_at'),
    ('pk_battle', 'finished_at'),
    ('pk_battle', 'challenger_finished_at'),
    ('pk_battle', 'opponent_finished_at'),
    ('user_points_profile', 'last_played_at'),
    ('season_meta', 'archived_at'),
]


def _parse(value):
    for fmt in _FORMATS:
        try:
            return dt.datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    raise ValueError(f'0002 迁移：无法解析时间值 {value!r}')


def _table_exists(conn, name):
    return conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"),
        {'n': name}).fetchone() is not None


def _column_exists(conn, table, column):
    cols = [row[1] for row in conn.execute(text(f'PRAGMA table_info({table})'))]
    return column in cols


def _shift_column(conn, table, column, delta):
    """按行读取-平移-写回，保留微秒精度（SQLite datetime() 会截断毫秒以下）"""
    if not _table_exists(conn, table) or not _column_exists(conn, table, column):
        return 0
    rows = conn.execute(text(
        f'SELECT rowid AS rid, {column} AS val FROM {table} '
        f'WHERE {column} IS NOT NULL')).fetchall()
    changed = 0
    for row in rows:
        new_val = (_parse(row.val) + delta).strftime('%Y-%m-%d %H:%M:%S.%f')
        conn.execute(text(f'UPDATE {table} SET {column} = :v WHERE rowid = :r'),
                     {'v': new_val, 'r': row.rid})
        changed += 1
    return changed


def _auto_ended_ids(conn):
    """自动结束路径产生的 result.id 集合：submitted_at 与其会话 end_time
    出自同一 now 对象（微秒一致）→ 该行是 UTC，无需平移"""
    if not _table_exists(conn, 'result') or not _table_exists(conn, 'exam_session'):
        return set()
    rows = conn.execute(text(
        'SELECT r.id AS rid FROM result r '
        'JOIN exam_session s ON s.exam_id = r.exam_id '
        'AND s.student_id = r.student_id AND s.end_time = r.submitted_at '
        'WHERE r.submitted_at IS NOT NULL')).fetchall()
    return {row.rid for row in rows}


def _shift_mixed_columns(conn):
    """混合列：result.submitted_at / exam_session.end_time 按行判别"""
    total = 0
    auto_ids = _auto_ended_ids(conn)

    if _table_exists(conn, 'result'):
        rows = conn.execute(text(
            'SELECT id AS rid, submitted_at AS val FROM result '
            'WHERE submitted_at IS NOT NULL')).fetchall()
        for row in rows:
            if row.rid in auto_ids:
                continue  # 自动结束路径：已是 UTC
            new_val = (_parse(row.val) - _SHIFT).strftime('%Y-%m-%d %H:%M:%S.%f')
            conn.execute(text('UPDATE result SET submitted_at = :v WHERE id = :r'),
                         {'v': new_val, 'r': row.rid})
            total += 1

    if _table_exists(conn, 'exam_session'):
        rows = conn.execute(text(
            'SELECT s.id AS rid, s.end_time AS val FROM exam_session s '
            'WHERE s.end_time IS NOT NULL AND NOT EXISTS ('
            '  SELECT 1 FROM result r WHERE r.exam_id = s.exam_id '
            '  AND r.student_id = s.student_id AND r.submitted_at = s.end_time)'
        )).fetchall()
        for row in rows:
            new_val = (_parse(row.val) - _SHIFT).strftime('%Y-%m-%d %H:%M:%S.%f')
            conn.execute(text('UPDATE exam_session SET end_time = :v WHERE id = :r'),
                         {'v': new_val, 'r': row.rid})
            total += 1
    return total


def upgrade():
    conn = op.get_bind()
    exists = conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tz_migration_v1'"
    )).fetchone()
    if exists:
        print('[0002] 哨兵表已存在，跳过时区归一化')
        return

    total = 0
    for table, column in LOCAL_COLUMNS:
        n = _shift_column(conn, table, column, -_SHIFT)
        if n:
            print(f'[0002] {table}.{column}: {n} 行 本地时间 -> UTC (-8h)')
        total += n
    n = _shift_mixed_columns(conn)
    if n:
        print(f'[0002] 混合列(result.submitted_at/exam_session.end_time): {n} 行 -> UTC')
    total += n
    print(f'[0002] 时区归一化完成，共 {total} 行；UTC 列 {len(UTC_COLUMNS)} 个无需处理')

    conn.execute(text('CREATE TABLE tz_migration_v1 (applied_at TEXT NOT NULL)'))
    conn.execute(text("INSERT INTO tz_migration_v1 (applied_at) "
                      "VALUES (datetime('now'))"))


def downgrade():
    """应急回滚：本地列 +8h 还原。
    混合列按行判别的结果无法逆推，回滚后统一按本地时间 +8h 处理
    （仅回滚 upgrade 前提下的数据时可用）"""
    conn = op.get_bind()
    for table, column in LOCAL_COLUMNS:
        _shift_column(conn, table, column, _SHIFT)
    conn.execute(text('DROP TABLE IF EXISTS tz_migration_v1'))
