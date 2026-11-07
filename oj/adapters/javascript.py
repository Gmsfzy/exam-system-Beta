# -*- coding: utf-8 -*-
"""JavaScript 适配器（v6.9）：node 运行，源码固定 main.js。

工具链缺失（无 node）时 available()=False，调用方回落人工评分。compile 阶段用
`node --check` 做语法校验（失败判 CE）；静态黑名单拦截 child_process/fs/net/vm 等
危险模块与动态执行。仍为校内防呆级，非防逃逸。
"""
import re
import shutil

from oj.adapters.base import LanguageAdapter, _exec

_JS_CHECKER = [
    r'\brequire\s*\(\s*[\'"]child_process[\'"]\s*\)', r'\bchild_process\b',
    r'\brequire\s*\(\s*[\'"]fs[\'"]\s*\)', r'\brequire\s*\(\s*[\'"]net[\'"]\s*\)',
    r'\brequire\s*\(\s*[\'"]dns[\'"]\s*\)', r'\brequire\s*\(\s*[\'"]http(s)?[\'"]\s*\)',
    r'\bprocess\s*\.\s*(binding|env|exit|kill|abort)\b',
    r'\brequire\s*\(\s*[\'"]vm[\'"]\s*\)', r'\bnew\s+Function\s*\(',
    r'\beval\s*\(', r'\bcluster\b',
]
_JS_RE = [re.compile(p) for p in _JS_CHECKER]


class JavaScriptAdapter(LanguageAdapter):
    language = 'javascript'
    source_file = 'main.js'

    def available(self):
        return shutil.which('node') is not None

    def check(self, code):
        bad = self._empty_or_oversize(code)
        if bad:
            return bad
        for pat in _JS_RE:
            if pat.search(code):
                return f'代码包含受限操作（{pat.pattern[:40]}…）'
        return None

    def compile(self, workdir, code):
        self._write_source(workdir, code)
        r = _exec(['node', '--check', 'main.js'], workdir, stdin='', timeout=15.0)
        if r['error']:
            return r['error']
        if r['exit_code'] not in (0, None):
            return ('语法错误：' + (r['stderr'] or '').strip())[:500]
        return None

    def build_argv(self, workdir):
        return ['node', 'main.js']
