# -*- coding: utf-8 -*-
"""Notebook 持久 kernel 的 worker 引导脚本（作为长驻子进程运行，非被 import）。

协议：换行分隔 JSON（NDJSON）。父进程每写一行请求，本进程回一行响应。
- 请求：{"cmd": "run"|"reset"|"interrupt"|"shutdown", "code": "..."}
- 响应：{"stdout","stderr","html","text","images":[base64PNG...],"displays":[mime bundle],"error"}

持久状态：所有 cell 在同一 globals 字典 G 中执行，变量/导入跨 cell 保留（真 Jupyter 语义）。
富输出（v6.9 阶段 5 增强）：
- 末表达式值：cell 最后一条语句是表达式则 eval 取返回值，_repr_html_→html，否则 repr→text；
- display(obj)：显式产出多 mime bundle（image/png|text/html|text/plain），一次 cell 可产多条 → displays；
- matplotlib：cell 执行后捕获新增 figure，savefig 为 base64 PNG 内联 → images。
魔法子集（安全档，仅不越防呆边界者）：%time / %%time（计时）、%whos（命名空间内省）；
  其余 %magic 与 !shell 明确拒绝（与 check_code 拦 subprocess 的边界一致）。
软中断（尽力而为）：run 在独立线程执行，主读取循环保持响应 stdin；收到 interrupt 用
  ctypes.PyThreadState_SetAsyncExc 向执行线程抛 _Interrupt 打断纯 Python 计算；
  卡在 C 扩展/系统调用时打不断，由父进程超时强杀兜底。
安全：由父进程以 `-I` 隔离解释器 + 最小 env + 独立临时 cwd 启动（见 utils/kernel.py）。
"""
import ast
import base64
import contextlib
import ctypes
import io
import json
import sys
import threading
import time
import traceback

# matplotlib 可选：装则用 Agg 后端捕获图形，未装则跳过图形捕获
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    _HAS_MPL = True
except Exception:  # pragma: no cover - 环境缺 matplotlib 时降级
    _HAS_MPL = False

# 持久命名空间：跨 cell 保留
G = {'__name__': '__main__', '__doc__': None}

# 软中断：当前执行线程 OS tid；_Interrupt 为注入型异常（被 _run_cell 捕获归为 error）
_exec_tid = None


class _Interrupt(Exception):
    """软中断注入异常（纯 Python 计算被打断时抛出）。"""


def _write(obj):
    """把响应写入真实 stdout（sys.__stdout__，不受 redirect 影响）。加锁避免多线程交错。"""
    with _write_lock:
        sys.__stdout__.write(json.dumps(obj, ensure_ascii=False) + '\n')
        sys.__stdout__.flush()


_write_lock = threading.Lock()
_stop = threading.Event()


# ── display() / 多 mime 渲染 ─────────────────────────────────────
_DISPLAYS = []   # 当前 cell 累积的 display() bundle 列表


def _render_bundle(v):
    """对象 → mime bundle（image/png | text/html | text/plain 尽量都给）。"""
    bundle = {}
    r = getattr(v, '_repr_png_', None)
    if callable(r):
        try:
            p = r()
            if isinstance(p, (bytes, bytearray)):
                bundle['image/png'] = base64.b64encode(p).decode('ascii')
            elif isinstance(p, str) and p:
                bundle['image/png'] = p
        except Exception:
            pass
    h = getattr(v, '_repr_html_', None)
    if callable(h):
        try:
            hh = h()
            if isinstance(hh, str) and hh.strip():
                bundle['text/html'] = hh
        except Exception:
            pass
    try:
        bundle.setdefault('text/plain', repr(v))
    except Exception:
        bundle['text/plain'] = '<无法表示的对象>'
    return bundle


def _display(*objs, **kwargs):
    """Jupyter display() 子集：把每个对象渲染为 mime bundle 追加到当前 cell 输出。"""
    for o in objs:
        _DISPLAYS.append(_render_bundle(o))
    return None


# ── 末表达式值渲染（沿用 v6.6 语义）─────────────────────────────
def _render_value(v):
    html = None
    try:
        r = getattr(v, '_repr_html_', None)
        if callable(r):
            h = r()
            if isinstance(h, str) and h.strip():
                html = h
    except Exception:
        html = None
    if html is not None:
        return html, None
    try:
        return None, repr(v)
    except Exception:
        return None, '<无法表示的对象>'


# ── 魔法子集 ────────────────────────────────────────────────────
def _parse_magic(code):
    """返回 (kind, name, payload)：kind ∈ {None,'line','cell'}；非魔法 → (None,None,None)。"""
    s = (code or '').lstrip()
    if s.startswith('!'):
        return ('line', 'shell', s)
    if s.startswith('%%'):
        head, _, body = s.partition('\n')
        toks = head[2:].strip().split(None, 1)
        return ('cell', toks[0] if toks else '', body)
    if s.startswith('%'):
        toks = s[1:].strip().split(None, 1)
        return ('line', toks[0] if toks else '', toks[1] if len(toks) > 1 else '')
    return (None, None, None)


def _magic_whos():
    """%whos：列出命名空间内非 dunder 变量（名称/类型/简略值）。"""
    rows = []
    for k in sorted(G.keys()):
        if k.startswith('__') or k in ('display', '_'):
            continue
        v = G[k]
        try:
            tname = type(v).__name__
        except Exception:
            tname = '?'
        try:
            rep = repr(v)
        except Exception:
            rep = '<...>'
        rows.append(f'{k:<24} {tname:<16} {rep[:60]}')
    if not rows:
        return '(命名空间为空)'
    head = f"{'名称':<24}{'类型':<16}内容\n" + '-' * 56 + '\n'
    return head + '\n'.join(rows)


# ── cell 执行核心 ───────────────────────────────────────────────
def _base_result():
    return {'stdout': '', 'stderr': '', 'html': None, 'text': None,
            'images': [], 'displays': [], 'error': None}


def _collect_images(figs_before, result):
    if not _HAS_MPL:
        return
    for f in [n for n in plt.get_fignums() if n not in figs_before]:
        try:
            buf = io.BytesIO()
            plt.figure(f).savefig(buf, format='png', dpi=110)
            result['images'].append(base64.b64encode(buf.getvalue()).decode('ascii'))
        except Exception:
            pass
    try:
        plt.close('all')
    except Exception:
        pass


def _exec_plain(code, result):
    """在持久 G 中执行纯 Python（无魔法），填充 html/text/error/stdout/stderr/displays/images。"""
    global _DISPLAYS
    _DISPLAYS = []
    figs_before = set(plt.get_fignums()) if _HAS_MPL else set()
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            tree = ast.parse(code or '')
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                prefix = ast.Module(body=tree.body[:-1], type_ignores=[])
                exec(compile(prefix, '<cell>', 'exec'), G)
                last = ast.Expression(body=tree.body[-1].value)
                val = eval(compile(last, '<cell>', 'eval'), G)
                if val is not None:
                    G['_'] = val
                    html, text = _render_value(val)
                    result['html'], result['text'] = html, text
            else:
                exec(compile(tree, '<cell>', 'exec'), G)
    except _Interrupt:
        result['error'] = '执行被用户中断'
    except Exception:
        result['error'] = traceback.format_exc()
    _collect_images(figs_before, result)
    result['stdout'] = out.getvalue()
    result['stderr'] = err.getvalue()
    result['displays'] = list(_DISPLAYS)


def _run_cell(code):
    result = _base_result()
    kind, name, payload = _parse_magic(code)
    if kind is None:
        _exec_plain(code, result)
        return result
    # 计时魔法：%%time（cell）/ %time <语句或表达式>（line）
    if name == 'time':
        body = payload if kind == 'cell' else code.lstrip()[len('%time'):].strip()
        t0 = time.perf_counter()
        c0 = time.process_time()
        _exec_plain(body, result)
        dt = time.perf_counter() - t0
        dc = time.process_time() - c0
        result['stdout'] = (result['stdout'] or '') + f'Wall time: {dt:.4f} s\nCPU time: {dc:.4f} s\n'
        return result
    if name == 'whos' and kind == 'line':
        result['text'] = _magic_whos()
        return result
    # 其余魔法 / !shell：明确拒绝（不越防呆边界）
    result['error'] = f'不支持的魔法命令：{name or "?"}（本环境仅支持 %time / %%time / %whos）'
    return result


# ── 软中断：向执行线程注入 _Interrupt ───────────────────────────
def _do_interrupt():
    global _exec_tid
    tid = _exec_tid
    if not tid:
        return
    try:
        n = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), ctypes.py_object(_Interrupt))
        if n > 1:  # 异常状态，清零回滚
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
    except Exception:
        pass


def _launch_run(code):
    """在独立线程执行 cell，主读取循环保持响应 stdin（可接收 interrupt）。协议保证同一时刻仅一个 run。"""
    def target():
        global _exec_tid
        _exec_tid = threading.get_ident()
        try:
            res = _run_cell(code)
        except Exception:  # 兜底：worker 自身缺陷也须回包，不让父进程空等
            res = _base_result()
            res['error'] = traceback.format_exc()
        finally:
            _exec_tid = None
        _write(res)

    threading.Thread(target=target, daemon=True).start()


def _reset_namespace():
    global _DISPLAYS
    _DISPLAYS = []
    G.clear()
    G.update({'__name__': '__main__', '__doc__': None, 'display': _display})


def _reader():
    for line in sys.stdin:
        if _stop.is_set():
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            res = _base_result()
            res['error'] = '请求解析失败'
            _write(res)
            continue
        cmd = req.get('cmd', 'run')
        if cmd == 'shutdown':
            _stop.set()
            break
        if cmd == 'reset':
            _reset_namespace()
            res = _base_result()
            res['text'] = 'kernel 已重置'
            _write(res)
            continue
        if cmd == 'interrupt':
            _do_interrupt()
            continue
        _launch_run(req.get('code', ''))
    _stop.set()


def main():
    # `-I`/`-E` 隔离解释器在中文 Windows 上 stdio 默认落到 GBK 码页，会让中文源码/输出乱码：
    # 与父进程管道约定统一强制为 UTF-8（双向）。
    for _s in (sys.stdin, sys.stdout, sys.stderr, sys.__stdout__, sys.__stdin__):
        try:
            _s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    G['display'] = _display
    _write({'ready': True, 'has_mpl': _HAS_MPL})
    threading.Thread(target=_reader, daemon=True).start()
    _stop.wait()
    sys.exit(0)


if __name__ == '__main__':
    main()
