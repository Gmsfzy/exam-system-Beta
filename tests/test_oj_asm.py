# -*- coding: utf-8 -*-
"""x86-64 汇编（NASM）OJ 判题回归门（v7.0 路线 A）。

分两档（与 test_oj_multi_language.py 同构）：
1. 静态/注册档（不依赖工具链，任何机器都跑）：asm 已注册、危险 extern 静态拒绝、空码拒绝。
2. 实跑档（需 Windows + 便携 MinGW 的 nasm+gcc）：AC/WA/CE 全链评测；
   非 nt 或缺工具链时自动 skip，避免 CI（仅 Python/Linux）假红。
"""
import os

import pytest

from oj import services as oj_services
from oj.adapters import get_adapter, supported_languages
from oj.adapters.asm import AsmAdapter

_HAS_ASM = AsmAdapter().available()
requires_asm = pytest.mark.skipif(not _HAS_ASM, reason='本机无 nasm+gcc（或非 Windows），跳过汇编实跑')

# 已在本机 MinGW 实测通过的 win64 回显程序：读 stdin → 原样写 stdout → ExitProcess(0)
ASM_ECHO = r'''
        extern ReadFile
        extern WriteFile
        extern GetStdHandle
        extern ExitProcess
        section .bss
buf resb 8192
        section .data
nread dq 0
nwrite dq 0
        section .text
        global main
main:
        sub rsp, 40
        mov ecx, -10
        call GetStdHandle
        mov rcx, rax
        lea rdx, [rel buf]
        mov r8d, 8192
        lea r9, [rel nread]
        mov qword [rsp+32], 0
        call ReadFile
        mov rbx, [rel nread]
        mov ecx, -11
        call GetStdHandle
        mov rcx, rax
        lea rdx, [rel buf]
        mov r8, rbx
        lea r9, [rel nwrite]
        mov qword [rsp+32], 0
        call WriteFile
        xor ecx, ecx
        call ExitProcess
'''
# 语法错误：非法指令操作数 → nasm 汇编失败 → CE
ASM_CE = 'global main\nmain:\n    mov [1bad], eax\n'
# 危险 extern（文件写）：静态黑名单命中 → SE，不进入汇编
ASM_DANGER = 'extern CreateFile\nglobal main\nmain:\n    ret\n'


# ── 静态/注册档（无工具链依赖）────────────────────────────────────────
class TestAsmStatic:
    def test_asm_registered(self):
        assert 'asm' in supported_languages()
        assert get_adapter('asm') is not None
        assert get_adapter('ASM') is not None          # 大小写归一

    def test_asm_danger_rejected(self):
        assert get_adapter('asm').check(ASM_DANGER) is not None      # CreateFile 危险
        assert get_adapter('asm').check('extern WSAStartup') is not None
        assert get_adapter('asm').check('%include "x.asm"') is not None   # 拉外部文件
        assert get_adapter('asm').check(ASM_ECHO) is None            # 标准 I/O 干净代码放行

    def test_asm_empty_rejected(self):
        assert get_adapter('asm').check('') is not None
        assert get_adapter('asm').check('   ') is not None

    def test_unavailable_language_falls_back(self):
        # 未注册语言回落 supported=False（调用方转人工/AI）
        r = oj_services.grade('x', 'ruby', [{'input': '', 'expected': '1'}])
        assert r['supported'] is False


# ── 汇编实跑档（需 nasm+gcc）──────────────────────────────────────────
@requires_asm
class TestAsmGrade:
    def test_ac(self):
        r = oj_services.grade(ASM_ECHO, 'asm', [{'input': 'hello\n', 'expected': 'hello\n'}])
        assert r['supported'] is True and r['verdict'] == 'AC', r

    def test_wa(self):
        r = oj_services.grade(ASM_ECHO, 'asm', [{'input': 'hello\n', 'expected': 'world\n'}])
        assert r['supported'] is True and r['verdict'] == 'WA', r

    def test_ce(self):
        r = oj_services.grade(ASM_CE, 'asm', [{'input': '', 'expected': 'x'}])
        assert r['verdict'] == 'CE', r

    def test_danger_is_se(self):
        r = oj_services.grade(ASM_DANGER, 'asm', [{'input': '', 'expected': '1'}])
        assert r['verdict'] == 'SE', r
