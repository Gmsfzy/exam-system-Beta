# -*- coding: utf-8 -*-
"""Python 适配器（v6.9）：静态检查与执行完全复用 oj.runner 既有实现，行为与 v4.7 一致。"""
import sys

from oj.adapters.base import LanguageAdapter
from oj.runner import check_code


class PythonAdapter(LanguageAdapter):
    language = 'python'
    source_file = 'main.py'

    def check(self, code):
        return check_code(code)

    def build_argv(self, workdir):
        # -I：隔离解释器（忽略环境变量/用户 site-packages），与 run_python 同一口径
        return [sys.executable, '-I', self.source_file]
