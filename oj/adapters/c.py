# -*- coding: utf-8 -*-
"""C 适配器（v6.9 阶段 2）：gcc 编译 + 运行，源码固定 main.c。

编译器经 _toolchain.find_compiler 三级发现（配置 → 项目内 tools/mingw64/bin → 系统 PATH），
缺失时 available()=False，调用方回落人工评分。编译用 `-O2 -static`（静态链接使产物无外部
DLL 依赖，最小 env 下即可运行）。静态防呆黑名单拦截进程/网络/文件写等危险操作；编译失败判 CE。
仍为校内防呆级，非防逃逸（详见《存在隐患.md》#8）。
"""
import os
import re

from oj.adapters.base import LanguageAdapter, _exec
from oj.adapters._toolchain import find_compiler

# 进程/网络/文件写等危险操作（C 与 C++ 共用；C++ 另加 ofstream）
_C_CHECKER = [
    r'\bsystem\s*\(', r'\bpopen\s*\(',
    r'\bexecl?p?e?\s*\(', r'\bfork\s*\(', r'\bposix_spawn\b',
    r'\bsocket\s*\(', r'\bconnect\s*\(', r'\blisten\s*\(', r'\bsend\s*\(', r'\brecv\s*\(',
    r'\bWSAStartup\b', r'\bWinsock',
    r'\bCreateProcess[AW]?\b', r'\bWinExec\b', r'\bShellExecute[AW]?\b',
    r'#\s*include\s*[<"]windows\.h[>"]', r'#\s*include\s*[<"]winsock',
    r'\bfreopen\s*\(', r'\bunlink\s*\(', r'\bremove\s*\(', r'\brename\s*\(',
    r'\bfopen\s*\([^)]*,\s*"[^"]*[wax]',      # fopen 写/追加模式
]
_C_RE = [re.compile(p) for p in _C_CHECKER]


class CAdapter(LanguageAdapter):
    language = 'c'
    source_file = 'main.c'
    compiler_exe = 'gcc'
    compiler_cfg = 'OJ_GCC_PATH'
    exe_name = 'main.exe' if os.name == 'nt' else 'main'

    def available(self):
        return find_compiler(self.compiler_exe, self.compiler_cfg, self.compiler_cfg) is not None

    def check(self, code):
        bad = self._empty_or_oversize(code)
        if bad:
            return bad
        for pat in self._danger_res():
            if pat.search(code):
                return f'代码包含受限操作（{pat.pattern[:40]}…）'
        return None

    def _danger_res(self):
        return _C_RE

    def compile(self, workdir, code):
        self._write_source(workdir, code)
        cc = find_compiler(self.compiler_exe, self.compiler_cfg, self.compiler_cfg)
        if not cc:
            return f'{self.compiler_exe} 编译器不可用（未安装或未在项目 tools/mingw64 下）'
        argv = [cc, '-O2', '-static', '-o', self.exe_name, self.source_file] + self._extra_flags()
        r = _exec(argv, workdir, stdin='', timeout=15.0)
        if r['error']:
            return r['error']
        if r['exit_code'] not in (0, None):
            return ('编译失败：' + (r['stderr'] or '').strip())[:500]
        return None

    def _extra_flags(self):
        return []

    def build_argv(self, workdir):
        return [os.path.join(workdir, self.exe_name)]
