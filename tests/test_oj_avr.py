# -*- coding: utf-8 -*-
"""AVR 单片机（avr-gcc + simavr）适配器回归门（v7.2 路线 B）。

AVR 判题依赖外部交叉工具链（本机与项目 MinGW 均无 avr-gcc/simavr），且 available() 采用
「显式开关 + 工具链就绪」双重门控、默认关。故本文件只覆盖**与工具链无关的静态档**：
注册、默认回落、双重门控、形态嗅探、体量防呆——这些在任何机器都应全绿。

实跑判题（compile/run via simavr）需维护者装好工具链、按本地 simavr 的 UART/cycle-halt
契约校准后，另补用例；当前 run 路径**未实机验证**（见适配器 docstring 与《环境兼容说明.md》）。
"""
from config import Config
from oj import services as oj_services
from oj.adapters import get_adapter, supported_languages
from oj.adapters.avr import AvrAdapter

INTEL_HEX = (
    ':10000000112233445566778899AABBCCDDEEFF00\r\n'
    ':00000001FF\r\n'
)
AVR_C = '#include <avr/io.h>\nint main(void){ return 0; }\n'
AVR_ASM = '; simple\nldi r16, 5\nmov r17, r16\n'


class TestAvrStatic:
    def test_avr_registered(self):
        assert 'avr' in supported_languages()
        assert get_adapter('avr') is not None
        assert get_adapter('AVR') is not None          # 大小写归一

    def test_default_unavailable_falls_back(self):
        # 默认 OJ_AVR_ENABLED=false → available False → grade 回落 supported=False（零误判）
        assert get_adapter('avr').available() is False
        r = oj_services.grade(AVR_C, 'avr', [{'input': '', 'expected': '1'}])
        assert r['supported'] is False

    def test_double_gate_needs_toolchain(self, monkeypatch):
        # 即便显式开开关，缺 avr-gcc/simavr 仍 available False（双重门控之工具链维度）
        monkeypatch.setattr(Config, 'OJ_AVR_ENABLED', True, raising=False)
        # 本机无 avr 工具链（前置已实测）：find_compiler 落空 → False
        assert AvrAdapter().available() is False

    def test_sniff_form(self):
        a = AvrAdapter()
        assert a._sniff_form(INTEL_HEX) == 'hex'       # Intel HEX 记录
        assert a._sniff_form(AVR_C) == 'c'             # C 源码
        assert a._sniff_form(AVR_ASM) == 'asm'         # 其余按汇编

    def test_empty_rejected(self):
        a = AvrAdapter()
        assert a.check('') is not None
        assert a.check('   ') is not None
        assert a.check(AVR_C) is None                  # 体量合规放行（沙箱由 simavr 兜）
