# -*- coding: utf-8 -*-
"""SQL 适配器（v7.2）：进程内 SQLite 内存实例判题，源码固定 main.sql。

教学口径与判分契约：
- 用例的 `input` 复用为**建表 + 种子数据的 setup SQL**（教师提供、可信），
  `expected` 为**结果集文本**（逐行、列以空格分隔，NULL 渲染为 `NULL`）；
- 学生提交的 SQL（通常是单条 SELECT）在应用 setup 后的内存库上执行，结果按上述
  口径序列化为 stdout 文本，由 `services._normalize` 比对 expected → AC/WA；
- 执行报错（语法/语义/引用不存在的表）→ 非零退出码 → 判 RE；查询超时由 SQLite
  progress handler 中断 → 判 TLE。

安全与沙箱（v7.2）：与其他语言「子进程 jail」不同，SQL 走**进程内 `sqlite3`**——
`connect(':memory:')` 无落盘、Python sqlite3 默认未开启 `enable_load_extension`
（readfile()/filemap 等文件 IO 扩展不可用），故天然收敛在内存实例内。静态黑名单再拦
ATTACH/DETACH（可挂载磁盘任意库文件）、PRAGMA（部分可读写文件/改环境）与显式扩展装载，
命中判 SE。仍为校内防呆级、非防逃逸（资源型攻击靠超时 progress handler 兜）。

依赖：仅 Python 标准库 `sqlite3`（恒就绪，available() 恒为真）。零外部工具链、零迁移。
"""
import os
import re
import sqlite3
import time

from oj.adapters.base import LanguageAdapter

# SQL 危险语句黑名单：挂载/卸载外部库文件、PRAGMA（部分可读写文件/改运行环境）、
# 扩展装载（进程内 sqlite3 默认不开，双保险）。大小写不敏感。
_SQL_CHECKER = [
    re.compile(r'\bATTACH\b', re.I),
    re.compile(r'\bDETACH\b', re.I),
    re.compile(r'\bPRAGMA\b', re.I),
    re.compile(r'\bload_extension\b', re.I),
    re.compile(r'\benable_load_extension\b', re.I),
]

_TIMEOUT_CLAMP = (0.5, 15.0)


class SqlAdapter(LanguageAdapter):
    language = 'sql'
    source_file = 'main.sql'

    def available(self):
        # 依赖标准库 sqlite3，恒就绪（无外部工具链，不随平台降级）
        return True

    def check(self, code):
        bad = self._empty_or_oversize(code)
        if bad:
            return bad
        for pat in _SQL_CHECKER:
            if pat.search(code):
                return f'SQL 包含受限语句（{pat.pattern[:24]}…）'
        return None

    def compile(self, workdir, code):
        # SQL 为声明式语言，无独立编译期（表存在性要到用例 setup 后才可知）；
        # 仅把学生 SQL 落到 workdir，供 run 读取（保持 workdir 级线程安全，不依赖实例状态）。
        self._write_source(workdir, code)
        return None

    def build_argv(self, workdir):  # 不走子进程，保留占位以符合基类契约
        raise NotImplementedError('SQL 走进程内 sqlite3，不使用子进程')

    def run(self, workdir, stdin='', timeout=5.0):
        """在内存 SQLite 上：先执行 setup（stdin），再执行学生 SQL，结果集序列化为文本。

        返回与 `_exec` 同构的结果字典：{stdout, stderr, exit_code, timed_out, error}。
        """
        sql_path = os.path.join(workdir, self.source_file)
        try:
            with open(sql_path, encoding='utf-8') as f:
                code = f.read()
        except OSError as exc:
            return {'stdout': '', 'stderr': str(exc), 'exit_code': None,
                    'timed_out': False, 'error': f'读取源码失败：{exc}'}

        setup = stdin or ''
        secs = max(_TIMEOUT_CLAMP[0], min(float(timeout), _TIMEOUT_CLAMP[1]))
        deadline = time.monotonic() + secs
        try:
            conn = sqlite3.connect(':memory:')
        except sqlite3.Error as exc:
            return {'stdout': '', 'stderr': str(exc), 'exit_code': None,
                    'timed_out': False, 'error': f'SQLite 环境异常：{exc}'}

        def _progress():
            # 返回非 0 触发 SQLite 中断（Interrupted），实现查询级超时
            return 1 if time.monotonic() > deadline else 0

        conn.set_progress_handler(_progress, 1000)
        try:
            if setup.strip():
                conn.executescript(setup)
            cur = conn.execute(code)
            rows = cur.fetchall()
            lines = [' '.join('NULL' if v is None else str(v) for v in row) for row in rows]
            return {'stdout': '\n'.join(lines), 'stderr': '',
                    'exit_code': 0, 'timed_out': False, 'error': None}
        except sqlite3.OperationalError as exc:
            msg = str(exc)
            if 'interrupt' in msg.lower():
                return {'stdout': '', 'stderr': msg, 'exit_code': None,
                        'timed_out': True, 'error': None}
            return {'stdout': '', 'stderr': msg, 'exit_code': 1,
                    'timed_out': False, 'error': None}
        except sqlite3.Error as exc:
            return {'stdout': '', 'stderr': str(exc), 'exit_code': 1,
                    'timed_out': False, 'error': None}
        finally:
            try:
                conn.close()
            except Exception:
                pass
