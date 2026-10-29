# -*- coding: utf-8 -*-
"""SQLite 数据库定时备份：由 utils.scheduler 后台线程按日调用。

设计要点：
- 用 sqlite3 在线备份 API（Connection.backup）产出一致性快照，WAL 下读写不阻塞、
  不复制半写的 -wal/-shm，比 shutil 直接拷 .db 文件安全。
- 每天最多一份：按本地日期判重，当日已有自动备份则跳过（配合 60s 轮询天然幂等）。
- 只认自己生成的 `exam_system_auto_*.db`，轮转删除绝不触碰手工 `.bak_*` 备份。
- 全程 try/except 交由调度器吞异常记日志，单点失败不影响其余定时任务。
"""
import os
import glob
import sqlite3

from utils.logger import logger
from utils.timeutil import utcnow, localtime

# 自动备份文件名前缀，与手工 .bak_* 区分，轮转只删本模块产物
_AUTO_PREFIX = 'exam_system_auto_'
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
    """按文件名（含时间戳，字典序即时间序）倒序保留最新 keep 份，删除更旧的自动备份。"""
    files = sorted(
        glob.glob(os.path.join(backup_dir, _AUTO_GLOB)),
        key=os.path.basename, reverse=True,
    )
    for stale in files[keep:]:
        try:
            os.remove(stale)
            logger.info(f'[backup] 轮转删除旧备份: {os.path.basename(stale)}')
        except OSError as e:
            logger.warning(f'[backup] 删除旧备份失败 {stale}: {e}')


def database_backup_tick():
    """每日数据库备份任务入口（幂等，供调度器周期调用）。"""
    from flask import current_app
    if not current_app.config.get('DB_BACKUP_ENABLED', True):
        return

    src_path = _sqlite_source_path()
    if not src_path or not os.path.isfile(src_path):
        # 库文件尚不存在（首次启动前）或为其他数据库，跳过
        return

    backup_dir = _backup_dir(src_path)
    now = localtime(utcnow())  # 文件名与当日判重按上海墙上时间（不随部署机时区漂移）
    day_tag = now.strftime('%Y-%m-%d')

    # 当日已有自动备份则跳过
    if glob.glob(os.path.join(backup_dir, f'{_AUTO_PREFIX}{day_tag}_*.db')):
        return

    dst_path = os.path.join(
        backup_dir, f'{_AUTO_PREFIX}{now.strftime("%Y-%m-%d_%H%M%S")}.db')
    try:
        _do_backup(src_path, dst_path)
    except sqlite3.Error as e:
        logger.error(f'[backup] 备份失败 {src_path} -> {dst_path}: {e}', exc_info=True)
        # 失败可能留下半成品文件，清理避免占用当日判重名额
        if os.path.isfile(dst_path):
            try:
                os.remove(dst_path)
            except OSError:
                pass
        return

    keep = int(current_app.config.get('DB_BACKUP_KEEP', 7))
    _prune(backup_dir, keep)
    logger.info(
        f'[backup] 数据库已备份: {os.path.basename(dst_path)}'
        f'（大小 {os.path.getsize(dst_path)} 字节，保留最近 {keep} 份）')
