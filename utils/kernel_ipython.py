# -*- coding: utf-8 -*-
"""真·IPython/ZMQ kernel 会话（v7.0 阶段 6）。

NOTEBOOK_BACKEND=ipython 时替代 NDJSON 子进程 worker，走 Jupyter 消息协议
（ipykernel + jupyter_client + pyzmq）：解锁完整 Jupyter 生态——任意魔法
（%time/%matplotlib/%%html…）、!shell、tab 补全、ipywidgets、富 display。

接口与 subprocess 后端的 KernelSession 对齐（execute/interrupt/reset/shutdown/alive），
返回结果字典同构（stdout/stderr/html/text/images/displays/error/timed_out），
前端 NotebookCell 渲染链路零改动。

能力/边界取舍：
- 超时/崩溃：与 subprocess 后端同语义——强杀重启并回放历史，超时返回 timed_out；
- 软中断：km.interrupt_kernel()（Windows 走 signal/message 模式，KeyboardInterrupt
  映射为「执行被用户中断」）；
- 静态危险拒绝不适用（本后端定位即完整生态，防呆边界由内核可用性兜底），
  run_cell 的 strict 检查仅对 subprocess 生效（既有条件不变）；
- 依赖缺失（未装 ipykernel）由 resolve_backend 降级 subprocess 并告警。
"""
import io
import os
import re
import shutil
import sys
import tempfile
import threading
import time

from utils.logger import logger

_ansi_re = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

# 子进程最小可用环境（与 subprocess 后端同一口径；connection file 固定放 workdir，
# 不依赖 APPDATA/HOME 下的 jupyter runtime dir）
_ENV_ALLOW = ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
              'LANG', 'LC_ALL', 'HOME', 'USERPROFILE')


def _minimal_env():
    return {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}


def _base_result():
    return {'stdout': '', 'stderr': '', 'html': None, 'text': None,
            'images': [], 'displays': [], 'error': None, 'timed_out': False}


def ipykernel_available():
    """ipykernel + jupyter_client 是否可导入（阶段 6 就绪判定）。"""
    try:
        import ipykernel            # noqa: F401
        import jupyter_client       # noqa: F401
        return True
    except Exception:
        return False


class IpyKernelSession:
    """一个 notebook 会话 = 一个 ipykernel 子进程（ZMQ 通信），跨 cell 保留命名空间。"""

    backend = 'ipython'

    def __init__(self, key, history=None, ready_timeout=60.0):
        self.key = key
        self.workdir = tempfile.mkdtemp(prefix='nb-ipy-')
        self.last_active = time.time()
        self._lock = threading.Lock()
        self._ready_timeout = ready_timeout
        self._history = history if history is not None else []
        self._km = None
        self._cli = None
        self._collector = None
        self._start()

    # ── 生命周期 ────────────────────────────────────────────────
    def _start(self):
        from jupyter_client import KernelManager
        self._km = KernelManager()
        # jupyter_client 8：kernel_cmd 为实例属性，{connection_file} 占位在 launch 时展开
        self._km.kernel_cmd = [sys.executable, '-m', 'ipykernel_launcher',
                               '-f', '{connection_file}']
        self._km.connection_file = os.path.join(self.workdir, 'kernel.json')
        self._km.start_kernel(cwd=self.workdir, env=_minimal_env())
        self._cli = self._km.client()
        self._cli.start_channels()
        self._cli.wait_for_ready(timeout=self._ready_timeout)
        # matplotlib 走 inline 渲染器：plt 图自动以 display_data(image/png) 推送，
        # 对齐真 Jupyter notebook 行为（未装 matplotlib 时该引导为无害 no-op）
        try:
            self._cli.execute_interactive('%matplotlib inline', silent=True,
                                          store_history=False, timeout=30)
        except Exception:
            logger.debug('[nb-ipy] %matplotlib inline 引导失败（未装 matplotlib？忽略）')

    def _stop_channels(self):
        try:
            if self._cli:
                self._cli.stop_channels()
        except Exception:
            pass

    def alive(self):
        try:
            return bool(self._km) and self._km.is_alive()
        except Exception:
            return False

    def _kill_restart(self, replay=True):
        """强杀重启（超时/崩溃兜底）。重启失败整体重建，再按历史回放。"""
        try:
            self._stop_channels()
            self._km.restart_kernel(now=True)
            self._cli = self._km.client()
            self._cli.start_channels()
            self._cli.wait_for_ready(timeout=self._ready_timeout)
        except Exception:
            logger.warning('[nb-ipy] 重启失败，整体重建 kernel 会话')
            try:
                self._km.shutdown_kernel(now=True)
            except Exception:
                pass
            self._start()
        if replay:
            self._replay()

    # ── iopub 消息收集 → 项目结果字典 ────────────────────────────
    def _hook(self, msg):
        mtype = msg.get('msg_type')
        content = msg.get('content') or {}
        c = self._collector
        if mtype == 'stream':
            c['stderr' if content.get('name') == 'stderr' else 'stdout'].append(
                content.get('text') or '')
        elif mtype == 'clear_output':
            c['stdout'].clear()
            c['stderr'].clear()
        elif mtype in ('execute_result', 'display_data', 'update_display_data'):
            data = content.get('data') or {}
            if mtype == 'execute_result':
                c['last_result'] = data      # 末表达式值 → html/text
            else:
                c['displays'].append(self._bundle(data))
            png = data.get('image/png')
            if isinstance(png, str) and png.strip():
                c['images'].append(''.join(png.split()))   # 去折行空白
        elif mtype == 'error':
            ename = content.get('ename') or 'Error'
            evalue = content.get('evalue') or ''
            tb = '\n'.join(_ansi_re.sub('', ln)
                           for ln in (content.get('traceback') or []))
            c['errors'].append((ename, evalue, tb))

    @staticmethod
    def _bundle(data):
        """Jupyter mime data → 项目 display bundle（text/plain|text/html|image/png）。"""
        out = {}
        if 'text/plain' in data:
            out['text/plain'] = str(data['text/plain'])
        if 'text/html' in data:
            out['text/html'] = str(data['text/html'])
        png = data.get('image/png')
        if isinstance(png, str) and png.strip():
            out['image/png'] = ''.join(png.split())
        return out

    def _finalize(self, reply):
        """execute_interactive 回复 + 收集器 → 项目结果字典。"""
        c = self._collector
        res = _base_result()
        res['stdout'] = ''.join(c['stdout'])
        res['stderr'] = ''.join(c['stderr'])
        res['images'] = c['images']
        res['displays'] = c['displays']
        last = c.get('last_result')
        if last:
            html = last.get('text/html')
            if isinstance(html, str) and html.strip():
                res['html'] = html
            else:
                res['text'] = str(last.get('text/plain') or '')
        status = (reply or {}).get('content', {}).get('status')
        if c['errors']:
            ename, evalue, tb = c['errors'][-1]
            if ename == 'KeyboardInterrupt':
                res['error'] = '执行被用户中断'      # 与 subprocess 后端同语义
            else:
                res['error'] = tb or f'{ename}: {evalue}'
        elif status == 'aborted':
            res['error'] = '执行被中断'
        elif status == 'error':
            res['error'] = '执行出错'
        return res

    # ── 对外接口（对齐 KernelSession）────────────────────────────
    def execute(self, code, timeout=None):
        if timeout is None:
            from utils.kernel import _cfg
            timeout = _cfg()[1]
        with self._lock:
            if not self.alive():
                self._kill_restart(replay=True)
            self._collector = {'stdout': [], 'stderr': [], 'images': [],
                               'displays': [], 'errors': [], 'last_result': None}
            try:
                reply = self._cli.execute_interactive(
                    code, silent=False, store_history=True,
                    allow_stdin=False, output_hook=self._hook, timeout=timeout)
            except Exception as exc:
                # 超时（jupyter_client TimeoutExpired）或通道/进程异常
                self._collector = None
                if self.alive():
                    # 判读为超时：中断尝试打断，再重启回放，返回 timed_out（与 subprocess 后端一致）
                    logger.warning('[nb-ipy] 执行超时(%s)，重启 kernel 并回放', exc)
                    self._kill_restart(replay=True)
                    from utils.kernel import _TIMEOUT_RESULT
                    return dict(_TIMEOUT_RESULT)
                logger.warning('[nb-ipy] kernel 进程失效(%s)，重建并回放', exc)
                try:
                    self._start()
                    self._replay()
                except Exception:
                    logger.exception('[nb-ipy] kernel 重建失败')
                from utils.kernel import _TIMEOUT_RESULT
                return dict(_TIMEOUT_RESULT, error='kernel 进程已退出，请重试')
            res = self._finalize(reply)
            self._collector = None
            self.last_active = time.time()
            if not res.get('error'):
                self._history.append(code)
            return res

    def interrupt(self):
        """软中断当前执行（真 SIGINT 语义，纯 Python/C 阻塞均可打断）。"""
        try:
            if self.alive():
                self._km.interrupt_kernel()
        except Exception:
            logger.debug('[nb-ipy] interrupt 失败', exc_info=True)

    def _replay(self):
        """重建/重启后重放历史成功 cell 恢复命名空间（调用方须持 self._lock）。"""
        if not self._history:
            return
        saved = list(self._history)
        self._history.clear()
        from utils.kernel import _cfg
        timeout = _cfg()[1]
        for code in saved:
            self._collector = {'stdout': [], 'stderr': [], 'images': [],
                               'displays': [], 'errors': [], 'last_result': None}
            try:
                reply = self._cli.execute_interactive(
                    code, silent=False, store_history=True,
                    allow_stdin=False, output_hook=self._hook, timeout=timeout)
                res = self._finalize(reply)
            except Exception:
                self._collector = None
                break
            self._collector = None
            if res.get('error'):
                break                      # 部分恢复：停在该 cell，其后历史丢弃
            self._history.append(code)

    def reset(self):
        with self._lock:
            self._history.clear()
            try:
                self._stop_channels()
                self._km.restart_kernel(now=True)
                self._cli = self._km.client()
                self._cli.start_channels()
                self._cli.wait_for_ready(timeout=self._ready_timeout)
            except Exception:
                logger.exception('[nb-ipy] reset 重启失败，整体重建')
                try:
                    self._start()
                except Exception:
                    pass

    def shutdown(self):
        with self._lock:
            self._stop_channels()
            try:
                if self._km:
                    self._km.shutdown_kernel(now=True)
            except Exception:
                pass
        shutil.rmtree(self.workdir, ignore_errors=True)
