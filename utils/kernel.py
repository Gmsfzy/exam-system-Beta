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
- ipython（v7.0 阶段 6，需装 ipykernel/jupyter_client/pyzmq）：真·Jupyter 消息协议 kernel
  （见 kernel_ipython.py），解锁完整魔法/!shell/补全/display/ipywidgets 生态；未安装依赖时
  同样降级 subprocess。仅显式指定启用，auto 不自动升级（保持既有部署行为不变）。

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
                   'text': None, 'images': [], 'displays': [],
                   'error': '执行超时，kernel 已重启（尝试回放历史单元恢复跨 cell 状态）',
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
    """auto：有 docker 用容器，否则子进程；显式 docker/ipython 不满足条件时降级 subprocess。"""
    backend, _t, _i, _img = _cfg()
    if backend == 'subprocess':
        return 'subprocess'
    if backend == 'ipython':
        from utils.kernel_ipython import ipykernel_available
        if ipykernel_available():
            return 'ipython'
        logger.warning('[notebook] NOTEBOOK_BACKEND=ipython 但缺 ipykernel/jupyter_client，'
                       '降级 subprocess（pip install ipykernel 可启用真 IPython kernel）')
        return 'subprocess'
    has_docker = shutil.which('docker') is not None
    if backend == 'docker':
        if has_docker:
            return 'docker'
        logger.warning('[notebook] NOTEBOOK_BACKEND=docker 但未检测到 docker，降级 subprocess（防呆级）')
        return 'subprocess'
    # auto：维持 docker→subprocess 既有优先级，不自动升级 ipython（部署行为不变）
    return 'docker' if has_docker else 'subprocess'


class KernelSession:
    """一个 notebook 会话对应一个长驻 worker 子进程。

    v6.9 阶段 5：新增软中断（interrupt）与命名空间回放——
    - `self._history`（与 KernelManager 共享同一 list 引用）记录本会话已成功执行的 cell 源码有序序列；
    - worker 崩溃/超时强杀/空闲回收后重建时，`_replay()` 自动重放该序列恢复跨 cell 变量；
    - 回放中任一 cell 再次超时/出错 → 停止回放并降级为「状态已重置」（清空 history）。
    """

    def __init__(self, key, backend, history=None):
        self.key = key
        self.backend = backend
        self.workdir = tempfile.mkdtemp(prefix='nb-kernel-')
        self.last_active = time.time()
        self._lock = threading.Lock()          # 串行化 execute/interrupt 的整个交互
        self._stdin_lock = threading.Lock()    # 串行化对 worker stdin 的写入（run 与 interrupt 可能并发）
        self._q = queue.Queue()
        self._gen = 0                          # worker 代际号：重启后旧 reader 的残留消息因代际不匹配被丢弃
        self._proc = None
        self._reader = None
        self._history = history if history is not None else []   # 共享引用，进程级持久
        self._start(replay=False)

    def _start(self, replay=False):
        # 每次 (重)启动换一代：新建空队列并推进代际号，隔旧 worker 残留的 ready/None 污染新会话
        self._gen += 1
        my_gen = self._gen
        self._q = queue.Queue()
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
        self._reader = threading.Thread(target=self._read_loop, args=(my_gen,), daemon=True)
        self._reader.start()
        # 等待 ready 握手
        try:
            self._q.get(timeout=15)
        except queue.Empty:
            pass
        # 新建/重建 worker 后按需回放历史（构造期不回放，交由 get()/respawn 触发）
        if replay:
            self._replay()

    def _docker_argv(self):
        _b, _t, _i, image = _cfg()
        # 挂载 worker 脚本与临时工作目录；--network none 断网；容器即隔离边界
        return ['docker', 'run', '-i', '--rm', '--network', 'none',
                '-v', f'{_WORKER}:/kb.py:ro',
                '-v', f'{self.workdir}:/work', '-w', '/work',
                image, 'python', '-I', '/kb.py']

    def _read_loop(self, gen):
        proc = self._proc          # 绑定本代际的进程/队列，避免重启后误写新会话
        q = self._q
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                if gen != self._gen:      # 已被更新代际取代 → 丢弃旧 worker 输出
                    return
                try:
                    q.put(json.loads(line))
                except Exception:
                    q.put({'stdout': line, 'stderr': '', 'html': None,
                           'text': None, 'images': [], 'displays': [], 'error': None})
        except Exception:
            pass
        finally:
            if gen == self._gen:
                q.put(None)  # 进程结束哨兵（仅当代际未被取代）

    def _send(self, obj):
        with self._stdin_lock:
            self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + '\n')
            self._proc.stdin.flush()

    def _execute_raw(self, code, timeout):
        """发送 run 并等响应。返回 dict 结果，或 'TIMEOUT'（卡住）/ None（进程失效）。
        调用方须持 self._lock。"""
        try:
            self._send({'cmd': 'run', 'code': code})
        except (OSError, ValueError):
            return None
        try:
            res = self._q.get(timeout=timeout + 5)
        except queue.Empty:
            return 'TIMEOUT'
        if res is None:
            return None
        return res

    def execute(self, code, timeout=None):
        if timeout is None:
            timeout = _cfg()[1]
        with self._lock:
            if self._proc.poll() is not None:
                self._respawn()
            res = self._execute_raw(code, timeout)
            if res == 'TIMEOUT':
                # 硬超时（多因卡在 C 扩展/系统调用，软中断打不断）→ 强杀重启并回放历史
                self._kill()
                self._start(replay=True)
                self.last_active = time.time()
                return dict(_TIMEOUT_RESULT)
            if res is None:
                self._respawn()
                return dict(_TIMEOUT_RESULT, error='kernel 进程已退出，请重试')
            self.last_active = time.time()
            res.setdefault('images', [])
            res.setdefault('displays', [])
            res['timed_out'] = False
            # 成功执行的 cell 纳入历史（供崩溃/重启后回放）；出错/中断/魔法拒绝不记录
            if not res.get('error'):
                self._history.append(code)
            return res

    def interrupt(self):
        """尽力软中断当前正在执行的 cell（纯 Python 计算可打断；卡在 C 调用则无效，由超时兜底）。
        不持 self._lock（execute 正占用等待结果），仅串行化 stdin 写入。"""
        with self._stdin_lock:
            try:
                if self._proc and self._proc.poll() is None:
                    self._proc.stdin.write(json.dumps({'cmd': 'interrupt'}) + '\n')
                    self._proc.stdin.flush()
            except (OSError, ValueError):
                pass

    def _replay(self):
        """重建 worker 后重放历史成功 cell 恢复命名空间（调用方须持 self._lock）。
        任一 cell 再超时/出错 → 停在该处，其后的历史丢弃（部分恢复，降级非全丢）。"""
        if not self._history:
            return
        saved = list(self._history)
        self._history.clear()
        for code in saved:
            r = self._execute_raw(code, _cfg()[1])
            if isinstance(r, dict) and not r.get('error'):
                self._history.append(code)     # 重放成功，保留供下次重启
            else:
                if r == 'TIMEOUT':
                    self._kill(); self._start(replay=False); self._history.clear()
                break

    def reset(self):
        with self._lock:
            self._history.clear()   # 重置即清空回放序列（命名空间从零开始）
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
            self._start(replay=True)
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

    def alive(self):
        """worker 进程是否存活（KernelManager 复用判定统一入口，与 IpyKernelSession 同接口）。"""
        return bool(self._proc) and self._proc.poll() is None


class KernelManager:
    """全局 kernel 会话池：按 (user_id, notebook_id) 复用，空闲超时回收。

    _history_store 保存每个 key 的「已成功执行 cell 源码有序列表」（与 KernelSession 共享同一 list）：
    会话因空闲回收/崩溃重建时，新会话据此回放恢复跨 cell 命名空间（进程内存，不落库）。"""

    def __init__(self):
        self._sessions = {}
        self._history_store = {}
        self._lock = threading.Lock()
        self._reaper = None

    def get(self, key):
        self._ensure_reaper()
        _b, _t, idle, _img = _cfg()
        with self._lock:
            s = self._sessions.get(key)
            if s and s.alive():
                return s
            if s:  # 已死，清理重建
                s.shutdown()
            backend = resolve_backend()
            hist = self._history_store.get(key)
            if hist is None:
                hist = []
                self._history_store[key] = hist
            if backend == 'ipython':
                from utils.kernel_ipython import IpyKernelSession
                s = IpyKernelSession(key, history=hist)
            else:
                s = KernelSession(key, backend, history=hist)
            self._sessions[key] = s
            # 空闲回收/崩溃后重建且有历史 → 在刚拉起的 worker 上回放一次恢复命名空间
            if hist:
                try:
                    with s._lock:
                        s._replay()
                except Exception:
                    logger.exception('[notebook] 会话重建回放失败')
            return s

    def interrupt(self, key):
        """向已有活跃会话下发软中断（无会话则 no-op）。供「停止」路由异步调用。"""
        with self._lock:
            s = self._sessions.get(key)
        if s:
            s.interrupt()
            return True
        return False

    def drop(self, key):
        with self._lock:
            s = self._sessions.pop(key, None)
            self._history_store.pop(key, None)   # 重置/删除彻底清空回放历史
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
                    'images': [], 'displays': [], 'error': f'代码包含受限操作：{reason}', 'timed_out': False}
    session = kernel_manager.get((user_id, notebook_id))
    return session.execute(code, timeout=timeout)


def interrupt_cell(user_id, notebook_id):
    """尽力软中断 (user, notebook) 会话当前正在执行的 cell（无活跃会话返回 False）。"""
    return kernel_manager.interrupt((user_id, notebook_id))
