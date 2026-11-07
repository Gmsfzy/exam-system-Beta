# -*- coding: utf-8 -*-
"""Jupyter .ipynb（nbformat v4）↔ 本系统 notebook/cells 双向映射（v6.9 阶段 4）

设计约束：
- 不引入 nbformat 依赖，手写映射即可产出/消费符合 nbformat v4.5 schema 的 JSON
  （source / stream.text 采用官方规范的「按行数组，保留换行符」形式，splitlines(keepends)
  与 ''.join 互逆，无损往返）。
- 本系统 cell 内部输出为扁平快照列表，与 run_cell 落库口径一致：
    {'output_type':'stream','name','text'}
    {'output_type':'error','ename','evalue','traceback':[]}
    {'output_type':'image','mime':'image/png','data'(base64),'text'?}
    {'output_type':'html','html'}
    {'output_type':'text','text'}
- 富输出映射（对齐 nbformat）：
    stream          ↔ output_type=stream
    error           ↔ output_type=error（traceback 列表原样）
    execute_result  ↔ html 优先（text/html+text/plain），否则 text/plain 单条
    display_data    ↔ image/png（可带 text/plain）
  一个数据束 data 同时含多 mime 时，导入拆为多条内部输出，保持可见性不丢。
"""


# ── 文本/行 双向辅助 ─────────────────────────────────────────────
def _to_lines(text):
    """字符串 → nbformat 行数组（每行保留结尾换行符；空串 → []）。"""
    return (text or '').splitlines(keepends=True)


def _from_src(src):
    """nbformat source/text（str 或 行数组）→ 单一字符串。"""
    if isinstance(src, list):
        return ''.join(str(x) for x in src)
    return src if isinstance(src, str) else ('' if src is None else str(src))


# ── notebook → ipynb（导出）───────────────────────────────────────
def _outputs_to_nb(outputs):
    """内部扁平输出快照 → nbformat outputs 列表（保序）。"""
    nb_out = []
    for o in outputs or []:
        if not isinstance(o, dict):
            continue
        t = o.get('output_type')
        if t == 'stream':
            nb_out.append({'output_type': 'stream', 'name': o.get('name') or 'stdout',
                           'text': _to_lines(o.get('text', ''))})
        elif t == 'error':
            tb = o.get('traceback')
            if isinstance(tb, str):
                tb = [tb]
            nb_out.append({'output_type': 'error', 'ename': o.get('ename') or 'Error',
                           'evalue': o.get('evalue') or '', 'traceback': list(tb or [])})
        elif t == 'image':
            data = {o.get('mime') or 'image/png': o.get('data') or ''}
            if o.get('text'):
                data['text/plain'] = _to_lines(o['text'])
            nb_out.append({'output_type': 'display_data', 'execution_count': None,
                           'data': data, 'metadata': {}})
        elif t == 'html':
            data = {'text/html': _to_lines(o.get('html', ''))}
            if o.get('text'):
                data['text/plain'] = _to_lines(o['text'])
            nb_out.append({'output_type': 'execute_result', 'execution_count': o.get('execution_count'),
                           'data': data, 'metadata': {}})
        elif t == 'text':
            nb_out.append({'output_type': 'execute_result', 'execution_count': o.get('execution_count'),
                           'data': {'text/plain': _to_lines(o.get('text', ''))}, 'metadata': {}})
    return nb_out


def notebook_to_ipynb(nb, language='python'):
    """notebook（含 cells 的内部 dict）→ nbformat v4 dict。

    nb: Notebook.to_dict(with_cells=True) 形状；cells 已按 order_num 排好。
    """
    cells = []
    exec_no = 1
    for c in nb.get('cells') or []:
        src = _to_lines(c.get('source', ''))
        if c.get('cell_type') == 'markdown':
            cells.append({'cell_type': 'markdown', 'source': src, 'metadata': {}})
        else:
            outputs = _outputs_to_nb(c.get('outputs'))
            # 已执行过的 cell 回填执行序号，与 exec_count 语义对齐
            ec = c.get('exec_count') or 0
            nb_exec = ec if ec else None
            cells.append({'cell_type': 'code', 'source': src, 'outputs': outputs,
                          'execution_count': nb_exec, 'metadata': {}})
            if ec:
                exec_no = ec + 1
    return {
        'cells': cells,
        'metadata': {
            'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
            'language_info': {'name': (language or 'python'), 'version': ''},
        },
        'nbformat': 4,
        'nbformat_minor': 5,
    }


# ── ipynb → cells（导入）──────────────────────────────────────────
def _outputs_from_nb(nb_outputs):
    """nbformat outputs 列表 → 内部扁平输出快照（保序；未知 mime 跳过）。"""
    internal = []
    for o in nb_outputs or []:
        if not isinstance(o, dict):
            continue
        t = o.get('output_type')
        if t == 'stream':
            internal.append({'output_type': 'stream', 'name': o.get('name') or 'stdout',
                             'text': _from_src(o.get('text', ''))})
        elif t == 'error':
            tb = o.get('traceback')
            if isinstance(tb, str):
                tb = [tb]
            internal.append({'output_type': 'error', 'ename': o.get('ename') or '',
                             'evalue': o.get('evalue') or '', 'traceback': list(tb or [])})
        elif t in ('execute_result', 'display_data'):
            data = o.get('data') or {}
            if 'image/png' in data:
                e = {'output_type': 'image', 'mime': 'image/png',
                     'data': _from_src(data['image/png'])}
                if 'text/plain' in data:
                    e['text'] = _from_src(data['text/plain'])
                internal.append(e)
            if 'text/html' in data:
                e = {'output_type': 'html', 'html': _from_src(data['text/html'])}
                if 'text/plain' in data and 'image/png' not in data:
                    e['text'] = _from_src(data['text/plain'])
                internal.append(e)
            elif 'text/plain' in data and 'image/png' not in data:
                internal.append({'output_type': 'text', 'text': _from_src(data['text/plain'])})
    return internal


def _infer_language(nb_json):
    """从 kernelspec / language_info 猜主语言（本系统 notebook 当前仅 python）。"""
    md = (nb_json or {}).get('metadata') or {}
    lang = ((md.get('kernelspec') or {}).get('language')
            or (md.get('language_info') or {}).get('language')
            or 'python')
    return (lang or 'python').lower()


def ipynb_to_cells(nb_json, max_cells=200, max_source=20000):
    """nbformat dict → (language, cells[])；cells 元素 {cell_type, source, outputs}。

    越界（超 cell 数 / 单 cell 源码长度）抛 ValueError，由路由转 400。
    """
    if not isinstance(nb_json, dict) or 'cells' not in nb_json:
        raise ValueError('不是有效的 .ipynb（缺少 cells）')
    raw_cells = nb_json.get('cells') or []
    if len(raw_cells) > max_cells:
        raise ValueError(f'单元数超过上限 {max_cells}')
    cells = []
    for c in raw_cells:
        if not isinstance(c, dict):
            continue
        source = _from_src(c.get('source', ''))
        if len(source) > max_source:
            raise ValueError(f'单单元代码长度超过上限 {max_source}')
        ctype = 'markdown' if c.get('cell_type') == 'markdown' else 'code'
        cells.append({'cell_type': ctype, 'source': source,
                      'outputs': _outputs_from_nb(c.get('outputs')) if ctype == 'code' else []})
    return _infer_language(nb_json), cells
