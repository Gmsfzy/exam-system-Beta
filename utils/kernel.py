# -*- coding: utf-8 -*-
"""Notebook 持久 kernel 管理器（v6.6）。

职责：为每个 notebook 会话维护一个长驻 Python worker 子进程（见 _notebook_kernel.py），
跨 cell 保留命名空间；提供执行、重置、超时重启、空闲回收。

可插拔执行后端（NOTEBOOK_BACKEND）：
- subprocess（默认/回落）：本机子进程，`-I` 隔离解释器 + 最小 env 白名单 + 独立临时 cwd +
  超时强杀 + 静态危险模式拒绝（复用 oj.runner.check_code）。定位「校内防呆级」，非防逃逸。
- docker（容器级隔离，需 Docker 主机 + 预装 numpy/pandas/matplotlib 的镜像）：以
  `docker run --network none` 起容器跑 worker，静态检查放宽（容器即边界）。本机无 Docker 时
  自动降级 subprocess 并告警——与项目 Redis「auto/fake/disabled」分层降级同一思路。

风险边界登记于《存在隐患.md》。
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from utils.logger import logger

_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_notebook_kernel.py')

# 子进程最小可用环境（复用 oj.runner 口径：Windows 空 env 会使子进程随机数源初始化失败）
_ENV_ALLOW = ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
              'LANG', 'LC_ALL', 'HOME', 'USERPROFILE')

_TIMEOUT_RESULT = {'stdout': '', 'stderr': '', 'html': None,
                   'text': None, 'images': [], 'error': '执行超时，kernel 已重启（跨 cell 状态丢失）',
                   'timed_out': True}


def _minimal_env():
    return {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}


def _cfg():
    from config import Config
    backend = getattr(Config, 'NOTEBOOK_BACKEND', 'auto')
    timeout = float(getattr(Config, 'NOTEBOOK_KERNEL_TIMEOUT', 30))
    idle = float(getattr(Config, 'NOTEBOOK_KERNEL_IDLE_TTL', 600))
    image = getattr(Config, 'NOTEBOOK_DOCKER_IMAGE', 'python:3.12-slim')
    return backend, timeout, idle, image


def resolve_backend():
    """auto：有 docker 用容器，否则子进程；显式 docker 但无 docker 时降级 subprocess。"""
    backend, _t, _i, _img = _cfg()
    if backend == 'subprocess':
        return 'subprocess'
    has_docker = shutil.which('docker') is not None
    if backend == 'docker':
        if has_docker:
            return 'docker'
        logger.warning('[notebook] NOTEBOOK_BACKEND=docker 但未检测到 docker，降级 subprocess（防呆级）')
        return 'subprocess'
    # auto
    return 'docker' if has_docker else 'subprocess'


class KernelSession:
    """一个 notebook 会话对应一个长驻 worker 子进程。"""

    def __init__(self, key, backend):
        self.key = key
        self.backend = backend
        self.workdir = tempfile.mkdtemp(prefix='nb-kernel-')
        self.last_active = time.time()
        self._lock = threading.Lock()
        self._q = queue.Queue()
        self._proc = None
        self._reader = None
        self._start()

    def _start(self):
        if self.backend == 'docker':
            argv = self._docker_argv()
        else:
            argv = [sys.executable, '-I', _WORKER]
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            self._proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=self.workdir,
                env=_minimal_env(), text=True, encoding='utf-8', errors='replace',
                bufsize=1, **kwargs)
        except OSError as exc:
            # docker 启动失败 → 降级 subprocess 再试一次
            if self.backend == 'docker':
                logger.warning('[notebook] docker 启动失败(%s)，降级 subprocess', exc)
                self.backend = 'subprocess'
                self._proc = subprocess.Popen(
                    [sys.executable, '-I', _WORKER],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=self.workdir, env=_minimal_env(), text=True, encoding='utf-8',
                    errors='replace', bufsize=1, **kwargs)
            else:
                raise
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        # 等待 ready 握手
        try:
            self._q.get(timeout=15)
        except queue.Empty:
            pass

    def _docker_argv(self):
        _b, _t, _i, image = _cfg()
        # 挂载 worker 脚本与临时工作目录；--network none 断网；容器即隔离边界
        return ['docker', 'run', '-i', '--rm', '--network', 'none',
                '-v', f'{_WORKER}:/kb.py:ro',
                '-v', f'{self.workdir}:/work', '-w', '/work',
                image, 'python', '-I', '/kb.py']

    def _read_loop(self):
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._q.put(json.loads(line))
                except Exception:
                    self._q.put({'stdout': line, 'stderr': '', 'html': None,
                                 'text': None, 'images': [], 'error': None})
        except Exception:
            pass
        finally:
            self._q.put(None)  # 进程结束哨兵

    def _send(self, obj):
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + '\n')
        self._proc.stdin.flush()

    def execute(self, code, timeout=None):
        if timeout is None:
            timeout = _cfg()[1]
        with self._lock:
            if self._proc.poll() is not None:
                self._respawn()
            try:
                self._send({'cmd': 'run', 'code': code})
            except (OSError, ValueError):
                self._respawn()
                return dict(_TIMEOUT_RESULT, error='kernel 已失效，请重试')
            try:
                res = self._q.get(timeout=timeout + 5)
            except queue.Empty:
                # 超时：worker 仍卡在 exec，无法中断 → 强杀重启（丢状态）
                self._kill()
                self._start()
                self.last_active = time.time()
                return dict(_TIMEOUT_RESULT)
            self.last_active = time.time()
            if res is None:
                self._respawn()
                return dict(_TIMEOUT_RESULT, error='kernel 进程已退出，请重试')
            res.setdefault('images', [])
            res['timed_out'] = False
            return res

    def reset(self):
        with self._lock:
            if self._proc.poll() is not None:
                self._respawn()
                return
            try:
                self._send({'cmd': 'reset'})
                try:
                    self._q.get(timeout=5)
                except queue.Empty:
                    pass
            except (OSError, ValueError):
                self._respawn()

    def _respawn(self):
        self._kill()
        try:
            self._start()
        except Exception:
            logger.exception('[notebook] kernel 重启失败')

    def _kill(self):
        try:
            if self._proc and self._proc.poll() is None:
                from oj.runner import _kill_tree
                _kill_tree(self._proc)
        except Exception:
            pass

    def shutdown(self):
        with self._lock:
            try:
                if self._proc and self._proc.poll() is None:
                    self._send({'cmd': 'shutdown'})
            except Exception:
                pass
            self._kill()
        shutil.rmtree(self.workdir, ignore_errors=True)


class KernelManager:
    """全局 kernel 会话池：按 (user_id, notebook_id) 复用，空闲超时回收。"""

    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()
        self._reaper = None

    def get(self, key):
        self._ensure_reaper()
        _b, _t, idle, _img = _cfg()
        with self._lock:
            s = self._sessions.get(key)
            if s and s._proc and s._proc.poll() is None:
                return s
            if s:  # 已死，清理重建
                s.shutdown()
            backend = resolve_backend()
            s = KernelSession(key, backend)
            self._sessions[key] = s
            return s

    def drop(self, key):
        with self._lock:
            s = self._sessions.pop(key, None)
        if s:
            s.shutdown()

    def reap_idle(self):
        _b, _t, idle, _img = _cfg()
        now = time.time()
        dead = []
        with self._lock:
            for k, s in list(self._sessions.items()):
                if now - s.last_active > idle:
                    dead.append((k, s))
                    self._sessions.pop(k, None)
        for _k, s in dead:
            try:
                s.shutdown()
            except Exception:
                pass

    def shutdown_all(self):
        with self._lock:
            items = list(self._sessions.items())
            self._sessions.clear()
        for _k, s in items:
            try:
                s.shutdown()
            except Exception:
                pass

    def _ensure_reaper(self):
        with self._lock:
            if self._reaper and not self._reaper.is_alive():
                self._reaper = None
            if self._reaper is None:
                self._reaper = threading.Thread(target=self._reap_loop, daemon=True)
                self._reaper.start()

    def _reap_loop(self):
        while True:
            time.sleep(60)
            try:
                self.reap_idle()
            except Exception:
                logger.exception('[notebook] 空闲回收异常')


# 模块级单例
kernel_manager = KernelManager()


def run_cell(user_id, notebook_id, code, timeout=None, strict=True):
    """执行一个 cell。strict=True（subprocess 后端）时先做静态危险模式拒绝。
    返回结果字典；拒绝时返回 {error: '...'}。"""
    if strict and resolve_backend() == 'subprocess':
        from oj.runner import check_code
        reason = check_code(code)
        if reason:
            return {'stdout': '', 'stderr': '', 'html': None, 'text': None,
                    'images': [], 'error': f'代码包含受限操作：{reason}', 'timed_out': False}
    session = kernel_manager.get((user_id, notebook_id))
    return session.execute(code, timeout=timeout)
