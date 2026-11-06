# -*- coding: utf-8 -*-
"""Notebook 持久 kernel 的 worker 引导脚本（作为长驻子进程运行，非被 import）。

协议：换行分隔 JSON（NDJSON）。父进程每写一行请求，本进程回一行响应。
- 请求：{"cmd": "run"|"reset"|"shutdown", "code": "..."}
- 响应：{"stdout","stderr","html","text","images":[base64PNG...],"error"}

持久状态：所有 cell 在同一 globals 字典 G 中执行，变量/导入跨 cell 保留（真 Jupyter 语义）。
富输出：
- 末表达式值：Jupyter 风格——若 cell 最后一条语句是表达式，eval 取返回值，
  优先 `_repr_html_`（DataFrame 等）→ html，否则 repr → text。
- matplotlib：cell 执行后捕获新增 figure，savefig 为 base64 PNG 内联。
安全：由父进程以 `-I` 隔离解释器 + 最小 env + 独立临时 cwd 启动（见 utils/kernel.py）。
"""
import ast
import base64
import contextlib
import io
import json
import sys
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


def _write(obj):
    """把响应写入真实 stdout（sys.__stdout__，不受 redirect 影响）。"""
    sys.__stdout__.write(json.dumps(obj, ensure_ascii=False) + '\n')
    sys.__stdout__.flush()


def _render_value(v):
    """末表达式值渲染：返回 (html, text)。html 优先（DataFrame._repr_html_）。"""
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


def _run_cell(code):
    result = {'stdout': '', 'stderr': '', 'html': None, 'text': None,
              'images': [], 'error': None}
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
    except Exception:
        result['error'] = traceback.format_exc()

    if _HAS_MPL:
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

    result['stdout'] = out.getvalue()
    result['stderr'] = err.getvalue()
    return result


def main():
    _write({'ready': True, 'has_mpl': _HAS_MPL})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            _write({'stdout': '', 'stderr': '', 'html': None, 'text': None,
                    'images': [], 'error': '请求解析失败'})
            continue
        cmd = req.get('cmd', 'run')
        if cmd == 'shutdown':
            break
        if cmd == 'reset':
            G.clear()
            G.update({'__name__': '__main__', '__doc__': None})
            _write({'stdout': '', 'stderr': '', 'html': None, 'text': 'kernel 已重置',
                    'images': [], 'error': None})
            continue
        _write(_run_cell(req.get('code', '')))
    sys.exit(0)


if __name__ == '__main__':
    main()
