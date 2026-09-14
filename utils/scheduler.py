# -*- coding: utf-8 -*-
"""后台定时调度线程：把过期考试自动结束、竞赛结算、赛季归档从请求路径剥离。

原方案在 before_request 中每请求触发，存在两个问题：
1. 每个请求都查 DB，性能差；
2. 多请求并发触发同一结算，竞态多（虽有幂等标记，但浪费资源）。

现改为单后台 daemon 线程，固定间隔（默认 60s）执行一次，请求路径完全不做结算。
"""
import threading

_INTERVAL = 60  # 秒
_stop_event = threading.Event()
_thread = None


def _run(app):
    with app.app_context():
        # 延迟导入，避免与 app.py 循环依赖
        from app import auto_end_expired_exams
        from competition.gamification import settle_pending_competitions
        from competition.season import ensure_seasons

        while not _stop_event.is_set():
            # 三个任务独立 try/except，单点失败不阻塞其余任务
            for name, task in (
                ('auto_end_expired_exams', auto_end_expired_exams),
                ('settle_pending_competitions', settle_pending_competitions),
                ('ensure_seasons', ensure_seasons),
            ):
                try:
                    task()
                except Exception as e:
                    app.logger.error(f'[scheduler] {name} 异常: {e}', exc_info=True)
                    try:
                        from database import db
                        db.session.rollback()
                    except Exception:
                        pass
            _stop_event.wait(_INTERVAL)


def start_scheduler(app, interval: int = _INTERVAL):
    """启动后台调度线程（幂等：重复调用不重复启动）"""
    global _thread, _INTERVAL
    if _thread is not None and _thread.is_alive():
        return
    _INTERVAL = interval
    _stop_event.clear()
    _thread = threading.Thread(target=_run, args=(app,), daemon=True, name='bg-scheduler')
    _thread.start()
    print(f'[scheduler] 后台调度线程已启动（间隔 {interval}s）')


def stop_scheduler():
    """停止后台调度线程（用于测试或优雅退出）"""
    _stop_event.set()
