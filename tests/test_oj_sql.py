# -*- coding: utf-8 -*-
"""SQL（SQLite 内存实例）OJ 判题回归门（v7.2）。

与其余语言档不同：SQL 走进程内 `sqlite3`（标准库恒就绪），无需外部工具链，
故本文件不设 skipif——任何机器都应全绿。契约：用例 input=setup SQL、expected=结果集文本。
"""
from oj import services as oj_services
from oj.adapters import get_adapter, supported_languages

SETUP = (
    "CREATE TABLE t(a INTEGER, b TEXT);\n"
    "INSERT INTO t VALUES(1,'x'),(2,'y');\n"
)
SQL_SELECT = 'SELECT a,b FROM t ORDER BY a'


# ── 静态/注册档 ──────────────────────────────────────────────────────
class TestSqlStatic:
    def test_sql_registered(self):
        assert 'sql' in supported_languages()
        assert get_adapter('sql') is not None
        assert get_adapter('SQL') is not None          # 大小写归一

    def test_sql_always_available(self):
        assert get_adapter('sql').available() is True  # 标准库，无工具链降级

    def test_sql_danger_rejected(self):
        assert get_adapter('sql').check("ATTACH DATABASE 'x' AS y") is not None
        assert get_adapter('sql').check('PRAGMA table_info(t)') is not None
        assert get_adapter('sql').check('SELECT load_extension("z")') is not None
        assert get_adapter('sql').check(SQL_SELECT) is None   # 干净 SELECT 放行

    def test_sql_empty_rejected(self):
        assert get_adapter('sql').check('') is not None
        assert get_adapter('sql').check('   ') is not None


# ── 判分档（进程内 sqlite3，恒可跑）──────────────────────────────────
class TestSqlGrade:
    def test_ac(self):
        r = oj_services.grade(SQL_SELECT, 'sql',
                              [{'input': SETUP, 'expected': '1 x\n2 y'}])
        assert r['supported'] is True and r['verdict'] == 'AC', r

    def test_wa(self):
        r = oj_services.grade(SQL_SELECT, 'sql',
                              [{'input': SETUP, 'expected': '1 x\n2 z'}])
        assert r['supported'] is True and r['verdict'] == 'WA', r

    def test_re_bad_reference(self):
        # 引用不存在的表 → sqlite OperationalError → 非零退出码 → RE
        r = oj_services.grade('SELECT * FROM nosuchtable', 'sql',
                              [{'input': SETUP, 'expected': ''}])
        assert r['verdict'] == 'RE', r

    def test_danger_is_se(self):
        # 静态黑名单命中 → 整题 SE，不进入执行
        r = oj_services.grade("ATTACH DATABASE 'x' AS y", 'sql',
                              [{'input': SETUP, 'expected': ''}])
        assert r['verdict'] == 'SE', r

    def test_aggregate_and_null(self):
        r = oj_services.grade('SELECT COUNT(*) FROM t', 'sql',
                              [{'input': SETUP, 'expected': '2'}])
        assert r['verdict'] == 'AC', r
        # NULL 渲染为字面量 NULL
        r2 = oj_services.grade('SELECT 1, NULL', 'sql',
                               [{'input': '', 'expected': '1 NULL'}])
        assert r2['verdict'] == 'AC', r2

    def test_multiple_cases_partial(self):
        r = oj_services.grade(SQL_SELECT, 'sql', [
            {'input': SETUP, 'expected': '1 x\n2 y'},      # AC
            {'input': SETUP, 'expected': 'wrong'},          # WA
        ])
        assert r['passed'] == 1 and r['total'] == 2 and r['verdict'] == 'WA', r

    def test_tle_infinite_recursive(self):
        # 无界递归 CTE 恒跑不完 → progress handler 在超时后中断 → TLE
        infinite = ('WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM s) '
                    'SELECT count(*) FROM s')
        r = oj_services.grade(infinite, 'sql', [{'input': '', 'expected': 'x'}],
                              per_case_timeout=0.5)
        assert r['verdict'] == 'TLE', r
