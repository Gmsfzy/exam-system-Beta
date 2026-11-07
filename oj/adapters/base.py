# -*- coding: utf-8 -*-
"""OJ 语言适配器基类与共享执行原语（v6.9 多语言判题）。

各语言适配器实现 check / compile / build_argv，统一用 `_exec` 跑子进程，
复用 oj.runner 的进程树强杀、最小 env 白名单与输出截断口径——保持「校内防呆级、
非防逃逸」定位（详见《存在隐患.md》#8）。解释型语言 compile 仅做语法校验或空操作；
编译型语言（Java 等）compile 失败判 CE。
"""
import os
import subprocess

from oj.runner import MAX_OUTPUT, _kill_tree, _minimal_env

_STDERR_CAP = 8192
_TIMEOUT_CLAMP = (0.5, 15.0)


def _exec(argv, workdir, stdin='', timeout=5.0):
    """在 workdir 以最小 env 跑 argv，喂 stdin，返回与 run_python 同构的结果字典。

    返回：{stdout, stderr, exit_code, timed_out, error}；error 非 None 表示未执行
    （工具链缺失/环境异常）。
    """
    timeout = max(_TIMEOUT_CLAMP[0], min(float(timeout), _TIMEOUT_CLAMP[1]))
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=workdir,
            env=_minimal_env(), **kwargs)
    except OSError as exc:
        return {'stdout': '', 'stderr': str(exc), 'exit_code': None,
                'timed_out': False, 'error': f'执行环境异常：{exc}'}
    timed_out = False
    try:
        out, err = proc.communicate(
            (stdin or '').encode('utf-8', errors='replace'), timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out, err = b'', b''
    return {
        'stdout': (out or b'')[:MAX_OUTPUT].decode('utf-8', errors='replace'),
        'stderr': (err or b'')[:_STDERR_CAP].decode('utf-8', errors='replace'),
        'exit_code': proc.returncode,
        'timed_out': timed_out,
        'error': None,
    }


class LanguageAdapter:
    """语言适配器基类。子类须覆盖 language / source_file / build_argv。"""
    language = ''
    source_file = 'main'
    max_code_size = 20000  # 提交代码长度上限（与 Python 口径一致）

    def available(self):
        """工具链是否就绪（如 javac/node 是否存在）。缺失时调用方按 supported=False 回落人工。"""
        return True

    def check(self, code):
        """静态防呆检查：命中危险模式返回原因字符串，干净返回 None。"""
        return None

    def _write_source(self, workdir, code):
        path = os.path.join(workdir, self.source_file)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(code or '')
        return path

    def compile(self, workdir, code):
        """写源码并（如需）编译。成功返回 None；失败返回编译错误信息字符串（判 CE）。"""
        self._write_source(workdir, code)
        return None

    def build_argv(self, workdir):
        raise NotImplementedError

    def run(self, workdir, stdin='', timeout=5.0):
        return _exec(self.build_argv(workdir), workdir, stdin=stdin, timeout=timeout)

    def _empty_or_oversize(self, code):
        if not code or not code.strip():
            return '代码为空'
        if len(code) > self.max_code_size:
            return f'代码超过 {self.max_code_size} 字符上限'
        return None
