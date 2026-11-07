# -*- coding: utf-8 -*-
"""C++ 适配器（v6.9 阶段 2）：g++ 编译 + 运行，源码固定 main.cpp。

复用 CAdapter 的发现/编译/运行骨架，仅换编译器（g++）、源文件名与扩展危险模式
（std::ofstream 文件写）。缺失 g++ 时 available()=False，调用方回落人工评分。
"""
import re

from oj.adapters.c import CAdapter, _C_RE

_CPP_CHECKER = _C_RE + [
    re.compile(r'\bstd\s*::\s*ofstream\b'),
    re.compile(r'\bofstream\b'),
]


class CppAdapter(CAdapter):
    language = 'cpp'
    source_file = 'main.cpp'
    compiler_exe = 'g++'
    compiler_cfg = 'OJ_GPP_PATH'

    def _danger_res(self):
        return _CPP_CHECKER
