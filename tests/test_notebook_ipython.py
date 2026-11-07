# -*- coding: utf-8 -*-
"""阶段 6：真·IPython/ZMQ kernel 后端（NOTEBOOK_BACKEND=ipython）。

依赖 ipykernel + jupyter_client（未安装则整文件 skip）。走 utils.kernel.run_cell
全链接（resolve_backend → KernelManager → IpyKernelSession），验证：
- 结果字典与 subprocess 后端同构（前端渲染链路零改动的契约）；
- 真 Jupyter 生态能力（%time 魔法、!shell——subprocess 后端明确拒绝的行为差异钉死）；
- 软中断语义（'执行被用户中断'）、超时重启回放、reset 清历史。
"""
import threading
import time

import pytest

from utils.kernel import kernel_manager, run_cell, interrupt_cell
from utils.kernel_ipython import ipykernel_available

pytestmark = pytest.mark.skipif(
    not ipykernel_available(),
    reason='未安装 ipykernel/jupyter_client（pip install ipykernel 启用阶段 6 测试）')

_SEQ = [0]


@pytest.fixture()
def ipy(monkeypatch):
    """强制 ipython 后端 + 每用例独立会话 key + 用毕关停 kernel 子进程。"""
    from config import Config
    monkeypatch.setattr(Config, 'NOTEBOOK_BACKEND', 'ipython', raising=False)
    _SEQ[0] += 1
    n = 910000 + _SEQ[0]
    key = (n, n)
    yield key
    kernel_manager.drop(key)


def _backend_of(key):
    return kernel_manager.get(key).backend


# ── 后端解析：显式 ipython 且依赖就绪 → IpyKernelSession ──────────
def test_resolve_backend_ipython(ipy):
    assert _backend_of(ipy) == 'ipython'


# ── 结果字典同构（向后兼容契约）──────────────────────────────────
def test_result_shape_backcompatible(ipy):
    u, nb = ipy
    r = run_cell(u, nb, 'print("hello 中文")')
    for k in ('stdout', 'stderr', 'html', 'text', 'images', 'displays', 'error', 'timed_out'):
        assert k in r
    assert r.get('error') is None
    assert 'hello 中文' in r['stdout']          # 中文 stdout 编码一致


# ── 末表达式 → text；HTML repr → html ────────────────────────────
def test_last_expression_and_html(ipy):
    u, nb = ipy
    r = run_cell(u, nb, 'x = 41')
    assert r.get('error') is None
    r = run_cell(u, nb, 'x + 1')               # 跨 cell 命名空间 + 末表达式
    assert r.get('text') == '42'
    r = run_cell(u, nb, 'class Box:\n    def _repr_html_(self):\n        return "<b>box!</b>"\nBox()')
    assert r.get('html') and 'box!' in r['html']


# ── 真 Jupyter 魔法：%time（subprocess 后端仅支持子集，此处全生态）──
def test_time_magic(ipy):
    u, nb = ipy
    r = run_cell(u, nb, '%time sum(range(1000))')
    assert r.get('error') is None
    out = r['stdout']
    assert ('Wall time' in out) or ('CPU time' in out), out


# ── !shell 在 ipython 后端可用（subprocess 后端 run_cell strict 拒绝的行为差异）──
def test_shell_escape_available(ipy):
    u, nb = ipy
    r = run_cell(u, nb, '!python -c "print(\'shell-ok\')"')
    assert r.get('error') is None              # 不被拒绝=真生态语义
    assert 'shell-ok' in r['stdout']


# ── display(HTML) → displays bundle ──────────────────────────────
def test_display_bundle(ipy):
    u, nb = ipy
    r = run_cell(u, nb,
                 'from IPython.display import display, HTML\ndisplay(HTML("<b>bold</b>"))')
    disp = r.get('displays') or []
    assert any(b.get('text/html') and 'bold' in b['text/html'] for b in disp), disp


# ── 异常回溯 → error ─────────────────────────────────────────────
def test_error_traceback(ipy):
    u, nb = ipy
    r = run_cell(u, nb, '1/0')
    assert r.get('error')
    assert 'ZeroDivisionError' in r['error']


# ── 软中断：死循环可被打断，语义与 subprocess 后端一致 ────────────
def test_soft_interrupt(ipy):
    u, nb = ipy
    run_cell(u, nb, '1')                       # 预热，避开 kernel 启动延时竞争
    box = {}

    def worker():
        box['res'] = run_cell(u, nb, 'while True: pass', timeout=20)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    deadline = time.time() + 12
    while time.time() < deadline and t.is_alive():
        time.sleep(0.4)
        interrupt_cell(u, nb)
    t.join(8)
    assert not t.is_alive(), '软中断未生效，执行仍卡死'
    err = (box.get('res') or {}).get('error') or ''
    assert '中断' in err, err


# ── 超时：强杀重启回放，返回 timed_out（与 subprocess 后端同语义）──
def test_timeout_restarts(ipy):
    u, nb = ipy
    r = run_cell(u, nb, 'import time; time.sleep(8)', timeout=2)
    assert r.get('timed_out') is True
    assert r.get('error')


# ── 重启回放 + reset 清历史 ──────────────────────────────────────
def test_replay_and_reset(ipy):
    s = kernel_manager.get(ipy)
    s.execute('replay_marker = 777')
    with s._lock:
        s._kill_restart(replay=True)
    res = s.execute('replay_marker', timeout=15)
    assert res.get('text') == '777'            # 重启回放恢复跨 cell 变量
    s.reset()
    res = s.execute('replay_marker', timeout=15)
    assert res.get('error') is not None        # reset 后名称丢失
