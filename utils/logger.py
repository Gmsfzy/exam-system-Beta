import logging
import os
from logging.handlers import RotatingFileHandler

# 单文件大小上限 10MB，保留 30 个轮转文件
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 30


class SafeRotatingFileHandler(RotatingFileHandler):
    """Windows 友好的按大小轮转 handler。

    标准 RotatingFileHandler.doRollover 在轮转时执行 close→rename→重开，
    Windows 下若日志文件被其他进程（IDE / 杀软 / 日志查看器）占用，
    os.rename 会抛 PermissionError [WinError 32]，且可能留下已关闭的 stream。
    本类在轮转失败时安全降级：放弃本次轮转、重新打开原文件继续追加写，
    保证日志不丢、进程不崩（下次写满再尝试轮转）。
    """

    def doRollover(self):
        try:
            super().doRollover()
        except OSError:
            try:
                if not self.stream:
                    self.stream = self._open()
            except OSError:
                pass


def _safe_handler(handler):
    handler.raiseExceptions = False
    return handler


def _make_file_handler(path, level):
    """统一用 SafeRotatingFileHandler（按大小轮转，Windows 占用时安全降级）"""
    h = _safe_handler(SafeRotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding='utf-8'
    ))
    h.setLevel(level)
    h.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    ))
    return h


def setup_logger():
    """root logger：只负责 app.log（全量）+ error.log（错误）。
    access / vue3 由各自独立 logger 处理，避免同一文件被多个 handler 打开。
    """
    log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.raiseExceptions = False

    if logger.handlers:
        return logger

    try:
        logger.addHandler(_make_file_handler(
            os.path.join(log_dir, 'app.log'), logging.DEBUG))
    except Exception:
        pass

    try:
        logger.addHandler(_make_file_handler(
            os.path.join(log_dir, 'error.log'), logging.ERROR))
    except Exception:
        pass

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(console)

    # werkzeug 默认对每个 HTTP 请求打 INFO（含 /socket.io 轮询、/api/csrf-token
    # 等高频请求），与 access 日志重复且会加速 app.log 增长、放大轮转冲突概率。
    # 请求审计统一由 access logger 负责（已过滤高频路径），werkzeug 提升到 WARNING
    # 只保留启动/异常信息。
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    return logger


def get_access_logger():
    access_logger = logging.getLogger('access')
    access_logger.setLevel(logging.INFO)
    if access_logger.handlers:
        return access_logger

    log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    h = _make_file_handler(os.path.join(log_dir, 'access.log'), logging.INFO)
    h.setFormatter(logging.Formatter('%(asctime)s - access - %(levelname)s - %(message)s'))
    access_logger.addHandler(h)
    access_logger.propagate = False
    return access_logger


def get_vue3_logger():
    vue3_logger = logging.getLogger('vue3')
    vue3_logger.setLevel(logging.DEBUG)
    if vue3_logger.handlers:
        return vue3_logger

    log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    h = _make_file_handler(os.path.join(log_dir, 'vue3.log'), logging.DEBUG)
    h.setFormatter(logging.Formatter('%(asctime)s - vue3 - %(levelname)s - %(message)s'))
    vue3_logger.addHandler(h)
    vue3_logger.propagate = False
    return vue3_logger


logger = setup_logger()
access_logger = get_access_logger()
vue3_logger = get_vue3_logger()