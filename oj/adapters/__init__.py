# -*- coding: utf-8 -*-
"""OJ 语言适配器注册表（v6.9）。

新增语言：实现 LanguageAdapter 子类并登记到 _REGISTRY 即可，判分主链无需改动。
阶段 2（C/C++）在此追加 CAdapter/CppAdapter。
"""
from oj.adapters.asm import AsmAdapter
from oj.adapters.avr import AvrAdapter
from oj.adapters.c import CAdapter
from oj.adapters.cpp import CppAdapter
from oj.adapters.java import JavaAdapter
from oj.adapters.javascript import JavaScriptAdapter
from oj.adapters.python import PythonAdapter
from oj.adapters.sql import SqlAdapter

_REGISTRY = {
    'python': PythonAdapter(),
    'java': JavaAdapter(),
    'javascript': JavaScriptAdapter(),
    'c': CAdapter(),
    'cpp': CppAdapter(),
    'asm': AsmAdapter(),
    'sql': SqlAdapter(),
    'avr': AvrAdapter(),
}


def get_adapter(language):
    """按语言取适配器实例；未知语言返回 None。"""
    return _REGISTRY.get((language or '').lower())


def supported_languages():
    """当前已注册语言集合（不含工具链可用性判断）。"""
    return set(_REGISTRY.keys())
