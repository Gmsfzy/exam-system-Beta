# -*- coding: utf-8 -*-
"""非 Python 单元执行（v7.23 代码笔记本多语言）

笔记本的持久 kernel 只有 Python（变量跨单元保留）。Java / JavaScript / C / C++ 是
编译型或独立运行时，做不到跨单元保留状态，因此按「一个单元 = 一个完整程序」执行：
写临时目录 → 编译（解释型做语法检查）→ 运行 → 收 stdout/stderr。

编译与运行原语直接复用 oj.adapters（javac/node/gcc/g++ 探测、静态防呆黑名单、
进程树强杀、最小 env 白名单与输出截断口径完全一致），避免两套执行逻辑漂移。
工具链缺失时返回可读提示，前端据此引导安装，不静默失败。
"""
import shutil
import tempfile

from config import Config
from oj.adapters import get_adapter

# 笔记本可选语言：python 走持久 kernel，其余走一次性执行
ONESHOT_LANGUAGES = ('java', 'javascript', 'c', 'cpp')
SUPPORTED_LANGUAGES = ('python',) + ONESHOT_LANGUAGES

LANGUAGE_LABELS = {
    'python': 'Python 3（交互式，变量跨单元保留）',
    'java': 'Java（单次运行，每个单元是完整程序）',
    'javascript': 'JavaScript / Node.js（单次运行）',
    'c': 'C（单次运行，需 GCC）',
    'cpp': 'C++（单次运行，需 G++）',
}

_TOOLCHAIN_HINTS = {
    'java': '未检测到 JDK：请安装 JDK 17+ 并把 javac/java 加入 PATH',
    'javascript': '未检测到 Node.js：请安装 Node.js 18+ 并加入 PATH',
    'c': '未检测到 GCC：请安装 MinGW-w64（如 winget install BrechtSanders.WinLibs.POSIX.UCRT）',
    'cpp': '未检测到 G++：请安装 MinGW-w64（如 winget install BrechtSanders.WinLibs.POSIX.UCRT）',
}


def is_oneshot(language):
    """是否走「一次性编译运行」而非持久 kernel"""
    return (language or '').lower() in ONESHOT_LANGUAGES


# ipynb 的 kernelspec 写法五花八门（python3/js/c++/node…），统一收敛到本系统取值
_ALIASES = {
    'python': 'python', 'python3': 'python', 'ipython': 'python',
    'java': 'java', 'javascript': 'javascript', 'js': 'javascript',
    'node': 'javascript', 'nodejs': 'javascript',
    'c': 'c', 'cpp': 'cpp', 'c++': 'cpp', 'cxx': 'cpp',
}


def normalize_language(raw):
    """把外部语言名收敛到本系统支持集合；不认识的一律回落 python（源码原样保留）"""
    key = (raw or '').lower().strip().replace(' ', '')
    lang = _ALIASES.get(key, key)
    return lang if lang in SUPPORTED_LANGUAGES else 'python'


def language_available(language):
    """语言是否可用：python 恒可用；其余看工具链是否就绪"""
    lang = (language or '').lower()
    if lang == 'python':
        return True
    adapter = get_adapter(lang)
    return bool(adapter and adapter.available())


def language_catalog():
    """前端语言下拉/提示用的清单（含可用性与缺失原因）"""
    out = []
    for lang in SUPPORTED_LANGUAGES:
        ok = language_available(lang)
        out.append({
            'value': lang,
            'label': LANGUAGE_LABELS[lang],
            'available': ok,
            'oneshot': is_oneshot(lang),
            'hint': None if ok or lang == 'python' else _TOOLCHAIN_HINTS.get(lang),
        })
    return out


def _empty_result(error=None, timed_out=False):
    return {'stdout': '', 'stderr': '', 'error': error, 'timed_out': timed_out,
            'text': None, 'html': None, 'images': [], 'displays': []}


def run_oneshot(language, code, timeout=None):
    """编译并运行一个单元，返回与 kernel.run_cell 同构的结果字典。

    编译失败（CE）与工具链缺失都放在 error 字段，由路由渲染为 error 输出；
    运行期非零退出码保留 stdout/stderr 并附退出码说明，便于学生自查。
    """
    lang = (language or '').lower()
    adapter = get_adapter(lang)
    if not adapter or not is_oneshot(lang):
        return _empty_result(f'不支持的语言：{language}')

    if not adapter.available():
        return _empty_result(_TOOLCHAIN_HINTS.get(lang, f'{lang} 工具链未就绪'))

    reason = adapter.check(code)
    if reason:
        return _empty_result(f'代码包含受限操作：{reason}')

    timeout = float(timeout or Config.NOTEBOOK_KERNEL_TIMEOUT)
    workdir = tempfile.mkdtemp(prefix=f'nb_{lang}_')
    try:
        compile_err = adapter.compile(workdir, code)
        if compile_err:
            return _empty_result(compile_err)

        res = adapter.run(workdir, stdin='', timeout=timeout)
        if res.get('error'):
            return _empty_result(res['error'], timed_out=bool(res.get('timed_out')))

        error = None
        if res.get('timed_out'):
            error = f'运行超时（>{timeout:.0f}s）'
        elif res.get('exit_code') not in (0, None):
            tail = (res.get('stderr') or '').strip()
            error = f'进程退出码 {res["exit_code"]}' + (f'：{tail[:300]}' if tail else '')

        return {
            'stdout': res.get('stdout') or '',
            'stderr': res.get('stderr') or '',
            'error': error,
            'timed_out': bool(res.get('timed_out')),
            'text': None,
            'html': None,
            'images': [],
            'displays': [],
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
