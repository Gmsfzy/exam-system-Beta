# -*- coding: utf-8 -*-
"""静态时间契约门 + 运行时契约（v5.36）

为什么要有这个门：项目的时间契约是「库内存 naive UTC / Python 层 aware UTC /
展示与业务日历按 Asia/Shanghai 固定 +8」（见 utils/timeutil.py 头注释），
但它只写在注释里，靠人记。历史上两次事故都是违反同一契约：
- v5.33：测试里用 `datetime.now()`（= 机器墙钟），本机 UTC+8 恰好蒙对，
  换到 UTC runner 立刻判错考试窗口 → CI 红才暴露；
- v5.35：生产里 `utcnow().date()` / `date.today()` 混用，打卡与逾期日界
  落在上海 08:00，8 小时窗口里归错日历日。

本机绿灯不代表正确（机器时区可能恰好掩盖问题），所以把契约钉成 AST 级静态扫描：
禁止「读机器时区」和「拿 UTC 当用户日历」的写法进入业务代码与测试。

扫描面：api/ homework/ competition/ bounty/ ledger/ dsci/ database/ utils/
       ai_service/ oj/ tests/ + app.py config.py
豁免：utils/timeutil.py —— 它是契约的实现本体，必须自己碰这些原语。
先 tokenize 掉注释与字符串字面量再匹配，避免文档里的字样被误判（也避免本文件的
规则字符串把自己判红）。
"""
import io
import os
import re
import tokenize
from datetime import date, datetime, timedelta, timezone

import pytest

from utils.timeutil import (LOCAL_TZ, iso_local, local_date, local_day_start,
                            local_today, localtime, parse_dt, utcnow)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ('api', 'homework', 'competition', 'bounty', 'ledger', 'dsci',
             'database', 'utils', 'ai_service', 'oj', 'tests')
SCAN_FILES = ('app.py', 'config.py')
EXEMPT = {'utils/timeutil.py'}

# (说明, 违规写法)。左侧是「为什么错」，改动时请连同说明一起评估。
RULES = (
    ('datetime.now() 裸调用：跟机器时区，换机器就变口径', r'datetime\.now\s*\(\s*\)'),
    ('datetime.utcnow()：返回 naive，跨层比较会炸', r'datetime\.utcnow\s*\('),
    ('date.today()：机器本地日，不是用户日历日', r'(?<![\w.])date\.today\s*\('),
    ('utcnow().date()：UTC 日，日界落在上海 08:00 → 用 local_today()/local_date()',
     r'utcnow\(\)\s*\.\s*date\s*\('),
    ('utcnow().strftime(...)：拿 UTC 拼日历键/展示串 → 用 local_today()/fmt_local()',
     r'utcnow\(\)\s*\.\s*strftime\s*\('),
    ('now.date()：now 为 UTC 时刻，同样错归日历日 → 用 local_date(now)',
     r'(?<![\w.])now\.date\s*\('),
    ('.astimezone() 无参：按系统时区换算', r'\.astimezone\s*\(\s*\)'),
    ('time.localtime/strftime/strptime：读系统时区', r'(?<![\w.])time\.(?:localtime|strftime|strptime)\s*\('),
    # 只判「单个位置参」这种显然漏 tz 的写法；带逗号（已传 tz=/其他参）不报，避免误杀
    ('fromtimestamp 未带 tz=：按系统时区解释秒数', r'\.fromtimestamp\s*\([^(),]*\)'),
    ('引入 pytz/zoneinfo：项目用固定 +8，不引时区库与 tzdata',
     r'\b(?:import|from)\s+(?:pytz|zoneinfo)\b'),
)
RULES = [(label, re.compile(pat)) for label, pat in RULES]


def _code_only(text):
    """返回逐行「纯代码」文本：注释与字符串字面量按原位置抹成空格（行数不变）。

    f-string 在 3.12 被拆成 FSTRING_START/MIDDLE/END，表达式部分不在 STRING token 里，
    因此 `f'练习 {utcnow().strftime(...)}'` 这类隐藏写法仍能被扫到。
    tokenize 失败（语法不合法等）时退回原文：宁误报，不漏报。
    """
    lines = text.splitlines()
    grid = [list(ln) for ln in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return lines
    for tok in tokens:
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (sr, sc), (er, ec) = tok.start, tok.end
        for row in range(sr, er + 1):
            if row - 1 >= len(grid):
                break
            cols = grid[row - 1]
            lo = sc if row == sr else 0
            hi = ec if row == er else len(cols)
            for i in range(max(lo, 0), min(hi, len(cols))):
                cols[i] = ' '
    return [''.join(cols) for cols in grid]


def _scan_source(rel_path, text):
    """扫描单个源文件，返回违规清单 [(lineno, 说明, 原始行), ...]。"""
    hits = []
    raw_lines = text.splitlines()
    for lineno, code in enumerate(_code_only(text), 1):
        for label, pattern in RULES:
            if pattern.search(code):
                hits.append((lineno, label, raw_lines[lineno - 1].strip()))
    return hits


def _iter_sources():
    for name in SCAN_FILES:
        path = os.path.join(ROOT, name)
        if os.path.isfile(path):
            yield name, path
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x != '__pycache__']
            for fn in sorted(filenames):
                if not fn.endswith('.py'):
                    continue
                path = os.path.join(dirpath, fn)
                yield os.path.relpath(path, ROOT).replace('\\', '/'), path


# ─────────────────────── 一、静态门：业务代码与测试 ───────────────────────

def test_no_time_contract_violations():
    """全项目零违规：任何「读机器时区」或「拿 UTC 当用户日历」的写法都判红。"""
    violations = []
    scanned = 0
    for rel, path in _iter_sources():
        if rel in EXEMPT:
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
        scanned += 1
        for lineno, label, line in _scan_source(rel, text):
            violations.append('%s:%d %s\n    %s' % (rel, lineno, label, line))
    assert scanned > 100, f'扫描面异常（只扫到 {scanned} 个文件），门已失效'
    assert not violations, (
        '违反时间契约（契约见 utils/timeutil.py 头注释；'
        '业务日历用 local_today()/local_date()，日窗口下界用 local_day_start()，'
        '展示串用 fmt_local()/iso_local()）：\n' + '\n'.join(violations)
    )


def test_gate_actually_detects_planted_violations():
    """自检：门不是空转——把 10 条规则的违规写法各喂一遍，必须全部命中。"""
    planted = [
        'x = datetime.now()',
        'x = datetime.utcnow().date()',
        'x = date.today()',
        'x = utcnow().date()',
        'x = utcnow().strftime("%Y-%m-%d")',
        'now = utcnow(); x = now.date()',
        'x = dt.astimezone()',
        'x = time.localtime()',
        'x = datetime.fromtimestamp(ts)',
        'import pytz',
    ]
    for src, (label, pattern) in zip(planted, RULES):
        assert pattern.search(src), f'规则未编译/过窄：{label}'
    hits = _scan_source('fake.py', '\n'.join(planted))
    fired = {label for _, label, _ in hits}
    missing = [label for label, _ in RULES if label not in fired]
    assert not missing, f'这些规则一条也没命中，写宽了：{missing}'


def test_gate_ignores_comments_and_docstrings():
    """自检：注释/文档字符串里的字样不算违规（否则本文件自己就会判红）。"""
    text = ('# 别再写 utcnow().date() 了\n'
            '"""date.today() 与 datetime.now() 的历史说明，仅文字。\n'
            'utcnow().strftime 也在这里""" \n'
            'x = local_today()\n')
    assert _scan_source('fake.py', text) == []


# ─────────────────────── 二、运行时契约：真值与机器时区无关 ───────────────────────

def test_local_tz_is_fixed_plus_eight():
    """契约地基：Asia/Shanghai 用固定偏移 +8（中国 1991 年起无夏令时），不读系统时区。"""
    assert LOCAL_TZ.utcoffset(None) == timedelta(hours=8)
    assert LOCAL_TZ.tzname(None) == 'Asia/Shanghai'
    # 固定偏移 ⇒ 全年同一偏移（夏令时不存在的断据）；timezone 对象的 dst() 恒为 None
    winter = datetime(2026, 1, 1, 12, tzinfo=LOCAL_TZ)
    summer = datetime(2026, 7, 1, 12, tzinfo=LOCAL_TZ)
    assert winter.utcoffset() == summer.utcoffset() == timedelta(hours=8)
    assert winter.astimezone(timezone.utc) == datetime(2026, 1, 1, 4, tzinfo=timezone.utc)
    assert summer.astimezone(timezone.utc) == datetime(2026, 7, 1, 4, tzinfo=timezone.utc)


def test_utcnow_is_aware_utc():
    """Python 层「现在」必须是 aware UTC（naive 会被当成上海墙上时间解释）。"""
    now = utcnow()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)


@pytest.mark.parametrize('wall,expect_utc', [
    ('2026-10-29T01:30', datetime(2026, 10, 28, 17, 30, tzinfo=timezone.utc)),
    ('2026-10-28 23:59', datetime(2026, 10, 28, 15, 59, tzinfo=timezone.utc)),
])
def test_parse_dt_reads_naive_input_as_shanghai_wall_time(wall, expect_utc):
    """输入侧契约：不带时区的用户输入按上海墙上时间解释（前端无需换算）。"""
    got = parse_dt(wall)
    assert got.utcoffset() == timedelta(0)
    assert got == expect_utc


def test_parse_dt_honours_explicit_offset():
    """输入侧契约：带 Z / 偏移的输入按其自身时区转 UTC。"""
    assert parse_dt('2026-10-28T17:30:00Z') == datetime(2026, 10, 28, 17, 30, tzinfo=timezone.utc)
    assert parse_dt('2026-10-29T01:30:00+08:00') == datetime(2026, 10, 28, 17, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize('s', ['2026-10-29T01:30:00', '2026-02-28T23:59:59', '2026-01-01T00:00:00'])
def test_iso_local_roundtrip(s):
    """输出侧契约：iso_local(parse_dt(s)) == s —— 序列化与解析互逆，前端原样可读。"""
    assert iso_local(parse_dt(s)) == s


def test_helpers_are_machine_timezone_independent():
    """同一 UTC 时刻在任何机器上都折成同一个上海日/日窗口（不读系统时区）。"""
    instant = datetime(2026, 10, 28, 16, 30, tzinfo=timezone.utc)
    assert local_date(instant) == date(2026, 10, 29)
    assert local_date(instant) == local_date(instant.replace(tzinfo=None))  # naive 按 UTC
    assert local_day_start(date(2026, 10, 29)) == datetime(2026, 10, 28, 16, 0,
                                                          tzinfo=timezone.utc)
    assert localtime(instant).utcoffset() == timedelta(hours=8)


def test_local_today_matches_local_date_of_now():
    """两个 helper 之间也必须自洽：今天 = 现在的上海日，且现在落在今天的日窗口内。"""
    now = utcnow()
    today = local_date(now)
    assert abs((local_today() - today).days) <= 1   # 读表瞬间跨日允许 ±1
    start = local_day_start(local_today())
    assert start <= now < start + timedelta(days=1)
