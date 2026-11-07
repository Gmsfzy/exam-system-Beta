# -*- coding: utf-8 -*-
"""Java 适配器（v6.9）：javac 编译 + java 运行，源码固定 Main.java、public class Main。

工具链缺失（无 javac/java）时 available()=False，调用方回落人工评分。静态防呆黑名单
拦截进程/网络/反射逃逸/文件写等危险操作；编译失败判 CE。仍为校内防呆级，非防逃逸。
"""
import re
import shutil

from oj.adapters.base import LanguageAdapter, _exec

_JAVA_CHECKER = [
    r'\bRuntime\s*\.\s*getRuntime\s*\(',          # Runtime.getRuntime().exec / availableProcessors 等
    r'\bnew\s+ProcessBuilder\b', r'\bProcessBuilder\b',
    r'\bSystem\s*\.\s*exit\b',                     # 干扰评测进程退出码
    r'\bjava\.lang\.reflect\b', r'\bsetAccessible\s*\(',
    r'\bjava\.net\b', r'\bSocket\b', r'\bURL(?:Connection)?\b',
    r'\b(FileOutputStream|FileWriter|RandomAccessFile)\b',
    r'\bFiles\s*\.\s*(write|delete|copy|move)\b',
    r'\bjavax\.',                                  # 仅拦 javax.*（不伤 java.util/java.io 正常导入）
    r'\bScriptEngine\b',
    r'\bgetClass\s*\(\s*\)\s*\.\s*getClassLoader\b',
]
_JAVA_RE = [re.compile(p) for p in _JAVA_CHECKER]


class JavaAdapter(LanguageAdapter):
    language = 'java'
    source_file = 'Main.java'

    def available(self):
        return shutil.which('javac') is not None and shutil.which('java') is not None

    def check(self, code):
        bad = self._empty_or_oversize(code)
        if bad:
            return bad
        for pat in _JAVA_RE:
            if pat.search(code):
                return f'代码包含受限操作（{pat.pattern[:40]}…）'
        return None

    def compile(self, workdir, code):
        self._write_source(workdir, code)
        r = _exec(['javac', '-encoding', 'UTF-8', 'Main.java'], workdir,
                  stdin='', timeout=15.0)
        if r['error']:
            return r['error']
        if r['exit_code'] not in (0, None):
            return ('编译失败：' + (r['stderr'] or '').strip())[:500]
        return None

    def build_argv(self, workdir):
        return ['java', '-cp', '.', 'Main']
