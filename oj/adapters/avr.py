# -*- coding: utf-8 -*-
"""AVR 单片机（ATmega）适配器（v7.2 路线 B）：avr-gcc 交叉编译 + simavr 模拟运行。

支持三种提交形态（按提交内容自动嗅探，见 `_sniff_form`）：
- Intel HEX（每行以 `:` 开头的十六进制记录）→ `avr-objcopy -I ihex -O elf32-avr` 转 ELF；
- C 源码（含 `#include` 或 C 风格 `main`）→ `avr-gcc -mmcu=<mcu> -Os` 编译 ELF；
- 汇编源码（其余）→ `avr-gcc -mmcu=<mcu> -x assembler-with-cpp` 汇编 ELF。
工具链经 `_toolchain.find_compiler` 三级发现（显式配置 `OJ_AVR_PATH`/`OJ_SIMAVR_PATH`
→ 项目内 tools/mingw64/bin → 系统 PATH）。

⚠ 重要边界（如实登记，见《存在隐患.md》#8 与《环境兼容说明.md》第五节）：
裸机 AVR 固件**没有操作系统、没有 stdin/stdout、没有自然退出码**——与 x86 汇编（宿主
可执行、有正常 main/exit/console I/O）根本不同。要接入现有 stdin→stdout 文本判分契约，
需要一个「预置输入→跑 N 个时钟周期→捕获 UART TX 队列→判定 halt」的 harness（通常链接
libsimavr 的小 C 程序）。本环境的 simavr 运行契约（`run`）**未做实机校准**
（本机与项目 MinGW 均无 avr-gcc/simavr/libsimavr，且不可联网安装）。

因此 available() 采用**双重门控**：需「avr-gcc 与 simavr 均就绪」**且**「显式开关
`OJ_AVR_ENABLED=true`」同时成立才为真。默认关 → 任何未校准环境一律 `supported=False`
→ 回落 AI/人工评分，**杜绝盲写 run 路径产生错误判题**。维护者装好工具链并按本地 simavr
的 UART/cycle-halt 行为校准 `run` 后，再显式开启本开关。

依赖：外部 avr-gcc + simavr 交叉工具链（项目自带 MinGW 不含）。零迁移。
"""
import os
import re

from config import logger
from oj.adapters.base import LanguageAdapter, _exec
from oj.adapters._toolchain import find_compiler

_HEX_LINE = re.compile(r'^:[0-9A-Fa-f]{8,}$')
_C_MARKERS = re.compile(r'#\s*include\s*[<"]|int\s+main\s*\(|\bvoid\s+main\s*\(')


def _conf(attr, default=None):
    try:
        from config import Config
        return getattr(Config, attr, default)
    except Exception:
        return default


class AvrAdapter(LanguageAdapter):
    language = 'avr'
    source_file = 'main'
    elf_name = 'main.elf'

    def available(self):
        # 双重门控：显式开关 + 工具链就绪。默认关（未实机校准）→ False → 回落人工
        if not _conf('OJ_AVR_ENABLED', False):
            return False
        return (find_compiler('avr-gcc', 'OJ_AVR_PATH', 'OJ_AVR_PATH') is not None
                and find_compiler('simavr', 'OJ_SIMAVR_PATH', 'OJ_SIMAVR_PATH') is not None)

    @staticmethod
    def _sniff_form(code):
        """按内容嗅探提交形态：'hex'（Intel HEX）/'c'（C 源码）/'asm'（汇编，默认）。"""
        body = (code or '').strip()
        # Intel HEX：以冒号起始的十六进制记录行（且无 C/汇编特征）
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if lines and all(_HEX_LINE.match(ln) for ln in lines):
            return 'hex'
        if _C_MARKERS.search(body):
            return 'c'
        return 'asm'

    def check(self, code):
        bad = self._empty_or_oversize(code)
        if bad:
            return bad
        # 裸机代码运行在 simavr 沙箱内（无宿主 FS/进程/网络可达面），静态仅做体量防呆
        return None

    def compile(self, workdir, code):
        form = self._sniff_form(code)
        avr_gcc = find_compiler('avr-gcc', 'OJ_AVR_PATH', 'OJ_AVR_PATH')
        mcu = _conf('OJ_AVR_MCU', 'atmega328p')
        elf = os.path.join(workdir, self.elf_name)
        if form == 'hex':
            src = os.path.join(workdir, 'main.hex')
            with open(src, 'w', encoding='utf-8') as f:
                f.write(code or '')
            objcopy = find_compiler('avr-objcopy', 'OJ_AVR_PATH', 'OJ_AVR_PATH')
            if not objcopy:
                objcopy = find_compiler('avr-objcopy')
            if not objcopy:
                return 'avr-objcopy 不可用（Intel HEX 转 ELF 需 avr-binutils）'
            r = _exec([objcopy, '-I', 'ihex', '-O', 'elf32-avr', src, elf],
                      workdir, stdin='', timeout=15.0)
        elif form == 'c':
            src = os.path.join(workdir, 'main.c')
            with open(src, 'w', encoding='utf-8') as f:
                f.write(code or '')
            if not avr_gcc:
                return 'avr-gcc 交叉编译器不可用（未安装）'
            r = _exec([avr_gcc, f'-mmcu={mcu}', '-Os', '-o', elf, src],
                      workdir, stdin='', timeout=15.0)
        else:  # asm
            src = os.path.join(workdir, 'main.S')
            with open(src, 'w', encoding='utf-8') as f:
                f.write(code or '')
            if not avr_gcc:
                return 'avr-gcc 交叉编译器不可用（未安装）'
            r = _exec([avr_gcc, f'-mmcu={mcu}', '-x', 'assembler-with-cpp', '-o', elf, src],
                      workdir, stdin='', timeout=15.0)
        if r['error']:
            return r['error']
        if r['exit_code'] not in (0, None):
            return ('编译/转换失败：' + (r['stderr'] or '').strip())[:500]
        return None

    def build_argv(self, workdir):
        return [os.path.join(workdir, self.elf_name)]

    def run(self, workdir, stdin='', timeout=5.0):
        """⚠ 未实机校准：以 simavr 加载 ELF，把 UART TX 视作 stdout。

        simavr 的裸机运行不含 stdin/stdout/退出码语义，此实现按常见 `simavr -m <mcu> <elf>`
        约定：喂 stdin（多数 simavr 版本忽略）、超时强杀、捕获其 stdout 作为 UART 输出。
        真实可用性取决于维护者本地 simavr 是否配了 UART harness 与 cycle-halt 约定；
        available() 默认关使本路径在非校准环境不会被触发。
        """
        simavr = find_compiler('simavr', 'OJ_SIMAVR_PATH', 'OJ_SIMAVR_PATH')
        if not simavr:
            return {'stdout': '', 'stderr': 'simavr 不可用', 'exit_code': None,
                    'timed_out': False, 'error': 'simavr 模拟器不可用（未安装）'}
        mcu = _conf('OJ_AVR_MCU', 'atmega328p')
        argv = [simavr, '-m', mcu, os.path.join(workdir, self.elf_name)]
        logger.debug('[avr] run（未实机校准）：simavr -m %s main.elf', mcu)
        return _exec(argv, workdir, stdin=stdin, timeout=timeout)
