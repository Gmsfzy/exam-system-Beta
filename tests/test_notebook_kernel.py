# -*- coding: utf-8 -*-
"""Notebook 内核增强（v6.9 阶段 5）：display/魔法子集/软中断/命名空间回放。

直接走 utils.kernel（真实 worker 子进程），不依赖 Flask/DB。docker 后端环境跳过
（本阶段面向 subprocess 防呆级；resolve_backend 非 subprocess 则 skip）。
"""
import threading
import time

import pytest

from utils.kernel import kernel_manager, run_cell, interrupt_cell, resolve_backend

pytestmark = pytest.mark.skipif(
    resolve_backend() != 'subprocess',
    reason='阶段 5 内核增强面向 subprocess 后端')

_SEQ = [0]


def _key():
    """每次给一个独立 (user_id, notebook_id) 元组，隔离 kernel 会话。"""
    _SEQ[0] += 1
    n = 900000 + _SEQ[0]
    return n, n


# ── %whos + 跨 cell 命名空间 ─────────────────────────────────────
def test_whos_and_persistent_namespace():
    u, nb = _key()
    r = run_cell(u, nb, 'x = 41')
    assert r.get('error') is None
    r = run_cell(u, nb, 'x + 1')                 # 末表达式值走 text
    assert r.get('text') == '42'
    r = run_cell(u, nb, '%whos')                 # 命名空间内省应见 x
    assert 'x' in (r.get('text') or '')


# ── %time / %%time ───────────────────────────────────────────────
def test_time_line_and_cell_magic():
    u, nb = _key()
    r = run_cell(u, nb, '%time sum(range(1000))')
    assert 'Wall time' in (r.get('stdout') or '')
    r = run_cell(u, nb, '%%time\nimport math\nmath.factorial(10)')
    assert 'Wall time' in (r.get('stdout') or '')
    assert r.get('text') == '3628800'


# ── 不支持的魔法 / shell 明确拒绝 ────────────────────────────────
def test_unsupported_magic_rejected():
    u, nb = _key()
    for src in ('%magic', '%%bash\nls', '!echo hi'):
        r = run_cell(u, nb, src)
        assert r.get('error') and '不支持' in r['error'], src


# ── display() 多 mime bundle ─────────────────────────────────────
def test_display_multimime():
    u, nb = _key()
    src = ('class Box:\n'
           '    def _repr_html_(self):\n'
           '        return "<b>box!</b>"\n'
           'display(Box())\n')
    r = run_cell(u, nb, src)
    assert r.get('error') is None
    disp = r.get('displays') or []
    assert any(b.get('text/html') == '<b>box!</b>' for b in disp)
    assert any('text/plain' in b for b in disp)


# ── run_cell 返回结构向后兼容：只新增 displays，不破坏旧键 ───────
def test_result_shape_backcompatible():
    u, nb = _key()
    r = run_cell(u, nb, 'print("hello")')
    for k in ('stdout', 'stderr', 'html', 'text', 'images', 'error', 'timed_out'):
        assert k in r
    assert 'displays' in r
    assert 'hello' in r['stdout']


# ── 软中断：纯 Python 死循环可被 interrupt 打断 ──────────────────
def test_soft_interrupt_pure_python_loop():
    u, nb = _key()
    run_cell(u, nb, '1')                      # 预热：先拉起 kernel 子进程，避开启动延时竞争
    box = {}

    def worker():
        box['res'] = run_cell(u, nb, 'i = 0\nwhile True:\n    i += 1', timeout=20)

    t = threading.Thread(target=worker)
    t.start()
    deadline = time.time() + 12
    while time.time() < deadline and t.is_alive():
        time.sleep(0.4)                       # 让死循环先跑起来（预热后很快）
        if not t.is_alive():
            break
        interrupt_cell(u, nb)                 # 向执行线程注入 _Interrupt（幂等，未运行则 no-op）
    t.join(5)
    assert not t.is_alive(), '软中断未生效，线程仍卡死'
    err = (box.get('res') or {}).get('error') or ''
    assert '中断' in err


# ── 命名空间回放：worker 崩溃重建后自动重放历史成功 cell ─────────
def test_namespace_replay_after_respawn():
    u, nb = _key()
    s = kernel_manager.get((u, nb))
    s.execute('replay_marker = 777')
    # 模拟崩溃/超时强杀后的重建（历史仍在会话/管理器）
    with s._lock:
        s._kill()
        s._start(replay=True)
    res = s.execute('replay_marker', timeout=15)
    assert res.get('text') == '777'       # 回放恢复了跨 cell 变量
    # reset 清空历史与命名空间
    s.reset()
    res = s.execute('replay_marker', timeout=15)
    assert res.get('error') is not None   # 名称已丢失
