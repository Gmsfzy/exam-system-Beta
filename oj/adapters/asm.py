# -*- coding: utf-8 -*-
"""x86-64 汇编适配器（NASM，v7.0 路线 A）：nasm 汇编 + gcc 链接 + 运行，源码固定 main.asm。

教学口径（本机 MinGW winlibs gcc 16.2 + 随项目走 nasm 实测通过）：
- 目标格式 `-f win64`；学生入口写 `global main`（普通 gcc 链接由 MinGW CRT 提供
  console 子系统与标准句柄，ReadFile/WriteFile/ExitProcess 直接经 kernel32 使用）；
- 判题用 stdin/stdout 文本契约，与 C/C++ 同一口径（喂 input、比 expected）。
静态防呆黑名单拦截进程/文件/网络/动态加载等危险 extern，编译或汇编失败判 CE。

平台边界（如实登记）：本后端在 **Windows + 项目内便携 MinGW** 上验证；汇编调用约定
（win64 vs SysV）跨平台不通用，故 available() 仅在 nt 且 nasm/gcc 均就绪时为真，
其余环境返回 False → 调用方回落 AI/人工评分（与其余适配器降级哲学一致，见《存在隐患.md》#8）。
"""
import os
import re

from oj.adapters.base import LanguageAdapter, _exec
from oj.adapters._toolchain import find_compiler

# win64 汇编危险 extern/API：进程、文件、网络、动态加载、环境读取（放行 GetStdHandle/ReadFile/
# WriteFile/ExitProcess 这类标准 I/O 与退出，其余落到 kernel32 之外的能力一律拦截）。
# 同时拦截 %include（可拉取外部文件）与 GetProcAddress/LoadLibrary 动态解析绕过。
_ASM_CHECKER = [
    re.compile(r'%\s*include\b'),
    re.compile(r'\bCreateFile[AW]?\b'), re.compile(r'\bDeleteFile[AW]?\b'),
    re.compile(r'\bMoveFile[AW]?\b'), re.compile(r'\bCopyFile[AW]?\b'),
    re.compile(r'\bCreateProcess[AW]?\b'), re.compile(r'\bWinExec\b'),
    re.compile(r'\bShellExecute[AW]?\b'), re.compile(r'\bOpenProcess\b'),
    re.compile(r'\bTerminateProcess\b'), re.compile(r'\bVirtualAllocEx\b'),
    re.compile(r'\bLoadLibrary[AW]?\b'), re.compile(r'\bGetProcAddress\b'),
    re.compile(r'\bExitWindowsEx\b'), re.compile(r'\bGetEnvironment\w*\b'),
    re.compile(r'\bWSAStartup\b'), re.compile(r'\bsocket\b'), re.compile(r'\bconnect\b'),
    re.compile(r'\blisten\b'), re.compile(r'\bsend\b'), re.compile(r'\brecv\b'),
    re.compile(r'\bInternetOpen\w*\b'), re.compile(r'\bURLDownloadTo\w*\b'),
    re.compile(r'\bWinHttp\w*\b'),
    re.compile(r'\bws2_32\b', re.I), re.compile(r'\bwininet\b', re.I),
    re.compile(r'\burlmon\b', re.I),
]


class AsmAdapter(LanguageAdapter):
    language = 'asm'
    source_file = 'main.asm'
    exe_name = 'main.exe' if os.name == 'nt' else 'main'
    obj_name = 'main.obj' if os.name == 'nt' else 'main.o'
    asm_format = 'win64' if os.name == 'nt' else 'elf64'
    assembler_exe = 'nasm'
    assembler_cfg = 'OJ_NASM_PATH'
    linker_exe = 'gcc'
    linker_cfg = 'OJ_GCC_PATH'

    def available(self):
        # 仅 Windows + MinGW 便携链已验证；非 nt 一律回落人工（汇编调用约定不跨平台）
        if os.name != 'nt':
            return False
        return (find_compiler(self.assembler_exe, self.assembler_cfg, self.assembler_cfg) is not None
                and find_compiler(self.linker_exe, self.linker_cfg, self.linker_cfg) is not None)

    def check(self, code):
        bad = self._empty_or_oversize(code)
        if bad:
            return bad
        for pat in _ASM_CHECKER:
            if pat.search(code):
                return f'代码包含受限操作（{pat.pattern[:40]}…）'
        return None

    def compile(self, workdir, code):
        """两阶段：nasm -f win64 汇编出 obj，再 gcc 链接成可执行文件。任一非零判 CE。"""
        self._write_source(workdir, code)
        nasm = find_compiler(self.assembler_exe, self.assembler_cfg, self.assembler_cfg)
        gcc = find_compiler(self.linker_exe, self.linker_cfg, self.linker_cfg)
        if not nasm or not gcc:
            return 'NASM/GCC 工具链不可用（未安装或未在项目 tools/mingw64 下）'
        ra = _exec([nasm, '-f', self.asm_format, '-o', self.obj_name, self.source_file],
                   workdir, stdin='', timeout=15.0)
        if ra['error']:
            return ra['error']
        if ra['exit_code'] not in (0, None):
            return ('汇编失败：' + (ra['stderr'] or '').strip())[:500]
        rl = _exec([gcc, '-o', self.exe_name, self.obj_name], workdir, stdin='', timeout=15.0)
        if rl['error']:
            return rl['error']
        if rl['exit_code'] not in (0, None):
            return ('链接失败：' + (rl['stderr'] or '').strip())[:500]
        return None

    def build_argv(self, workdir):
        return [os.path.join(workdir, self.exe_name)]
