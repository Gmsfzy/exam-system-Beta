# -*- coding: utf-8 -*-
"""数据库定时备份：由 utils.scheduler 后台线程按日调用，按方言分派双后端。

设计要点：
- sqlite     ：用 sqlite3 在线备份 API（Connection.backup）产出一致性快照，WAL 下读写不阻塞、
  不复制半写的 -wal/-shm，比 shutil 直接拷 .db 文件安全。
- postgresql ：调本机 pg_dump --format=custom 产出 .dump 压缩归档（subprocess），
  产物可直接用 pg_restore 恢复。pg_dump 二进制路径由环境变量 PG_DUMP_PATH 指定（默认走 PATH）。
- 每天最多一份：按本地日期判重，当日已有自动备份则跳过（配合 60s 轮询天然幂等）。
- 只认自己生成的 exam_system_auto_*.{db,dump}，轮转删除绝不触碰手工 .bak_* 备份。
- 全程 try/except 交由调度器吞异常记日志，单点失败不影响其余定时任务。
"""
import os
import glob
import sqlite3
import subprocess

from utils.logger import logger
from utils.timeutil import utcnow, localtime

# 自动备份文件名前缀，与手工 .bak_* 区分，轮转只删本模块产物
_AUTO_PREFIX = 'exam_system_auto_'
# 向后兼容：SQLite 自动备份产物 glob（测试/外部引用仍用此名）
_AUTO_GLOB = _AUTO_PREFIX + '*.db'


def _backup_dir(src_path):
    """自动备份存放目录：与库文件同级的 backups/（不存在则创建）。

    由库文件路径就地推导，自动适配开发机/打包运行时的 instance 实际位置。
    """
    path = os.path.join(os.path.dirname(src_path), 'backups')
    os.makedirs(path, exist_ok=True)
    return path


def _sqlite_source_path():
    """从 SQLAlchemy 引擎 URL 取 sqlite 库文件绝对路径；非 sqlite 返回 None。"""
    from database import db
    url = db.engine.url
    if url.drivername != 'sqlite':
        return None
    return url.database


def _do_backup(src_path, dst_path):
    """用在线备份 API 产出一致性快照。"""
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _prune(backup_dir, keep):
    """按文件名（含时间戳，字典序即时间序）倒序保留最新 keep 份，删除更旧的自动备份。

    glob 同时命中 .db（sqlite）与 .dump（postgresql），保证混用/切库后轮转仍只留 N 份。
    """
    files = sorted(
        glob.glob(os.path.join(backup_dir, _AUTO_PREFIX + '*.*')),
        key=os.path.basename, reverse=True,
    )
    # 只删本模块自动产物（前缀匹配已由 glob 保证），保留手工 .bak_*
    for stale in files[keep:]:
        try:
            os.remove(stale)
            logger.info(f'[backup] 轮转删除旧备份: {os.path.basename(stale)}')
        except OSError as e:
            logger.warning(f'[backup] 删除旧备份失败 {stale}: {e}')


def _sqlite_tick(backup_dir, src_path, day_tag, now, keep):
    """SQLite 备份：在线备份 API 产出 .db 快照。当日已有则跳过。"""
    if glob.glob(os.path.join(backup_dir, f'{_AUTO_PREFIX}{day_tag}_*.db')):
        return
    dst_path = os.path.join(
        backup_dir, f'{_AUTO_PREFIX}{now.strftime("%Y-%m-%d_%H%M%S")}.db')
    try:
        _do_backup(src_path, dst_path)
    except sqlite3.Error as e:
        logger.error(f'[backup] 备份失败 {src_path} -> {dst_path}: {e}', exc_info=True)
        if os.path.isfile(dst_path):
            try:
                os.remove(dst_path)
            except OSError:
                pass
        return
    _prune(backup_dir, keep)
    logger.info(
        f'[backup] 数据库已备份: {os.path.basename(dst_path)}'
        f'（大小 {os.path.getsize(dst_path)} 字节，保留最近 {keep} 份）')


def _pg_tick(backup_dir, day_tag, now, keep):
    """PostgreSQL 备份：调本机 pg_dump -Fc 产出 .dump 自定义格式归档。当日已有则跳过。"""
    from database import db
    if glob.glob(os.path.join(backup_dir, f'{_AUTO_PREFIX}{day_tag}_*.dump')):
        return
    dst_path = os.path.join(
        backup_dir, f'{_AUTO_PREFIX}{now.strftime("%Y-%m-%d_%H%M%S")}.dump')

    url = db.engine.url
    pg_dump = os.getenv('PG_DUMP_PATH', 'pg_dump')
    # 凭证通过 PGPASSWORD 环境变量传递，不进命令行（避免进程列表泄露）
    env = os.environ.copy()
    if url.password:
        env['PGPASSWORD'] = url.password
    cmd = [
        pg_dump, '--format=custom', '--no-password',
        f'--host={url.host or "localhost"}',
        f'--port={url.port or 5432}',
        f'--username={url.username}',
        f'--dbname={url.database}',
        f'--file={dst_path}',
    ]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(f'[backup] pg_dump 调用失败（检查 PG_DUMP_PATH 是否指向 pg_dump）: {e}')
        if os.path.isfile(dst_path):
            try:
                os.remove(dst_path)
            except OSError:
                pass
        return
    if proc.returncode != 0:
        logger.error(
            f'[backup] pg_dump 退出码 {proc.returncode}: '
            f'{(proc.stderr or "").strip()}')
        if os.path.isfile(dst_path):
            try:
                os.remove(dst_path)
            except OSError:
                pass
        return
    _prune(backup_dir, keep)
    logger.info(
        f'[backup] 数据库已备份: {os.path.basename(dst_path)}'
        f'（大小 {os.path.getsize(dst_path)} 字节，保留最近 {keep} 份）')


def database_backup_tick():
    """每日数据库备份任务入口（幂等，供调度器周期调用），按方言分派。"""
    from flask import current_app
    from database import db
    if not current_app.config.get('DB_BACKUP_ENABLED', True):
        return

    dialect = db.engine.dialect.name
    now = localtime(utcnow())  # 文件名与当日判重按上海墙上时间（不随部署机时区漂移）
    day_tag = now.strftime('%Y-%m-%d')
    keep = int(current_app.config.get('DB_BACKUP_KEEP', 7))

    if dialect == 'sqlite':
        src_path = _sqlite_source_path()
        if not src_path or not os.path.isfile(src_path):
            # 库文件尚不存在（首次启动前），跳过
            return
        _sqlite_tick(_backup_dir(src_path), src_path, day_tag, now, keep)
    elif dialect == 'postgresql':
        backup_dir = os.path.join(current_app.instance_path, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        _pg_tick(backup_dir, day_tag, now, keep)
    # 其他方言不备份（静默跳过）
