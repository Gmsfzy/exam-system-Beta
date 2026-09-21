# -*- coding: utf-8 -*-
"""OJ 判分服务：stdin/stdout 用例评测

判定语义（对齐主流 OJ 简化版）：
- 输出比对忽略每行行尾空白与文件末尾空行；
- 逐用例判定 AC/WA/TLE/RE/SE，全部 AC 才 verdict=AC；
- 存在失败用例时 verdict 取第一个失败状态（评分按 AC 通过率折算）。
"""
from oj.runner import run_python

# 当前仅 Python 可自动评测；其余语言 supported=False，由调用方回落 AI/人工评分
SUPPORTED_LANGUAGES = {'python'}
MAX_CASES = 20            # 用例数上限（防单题评测过久）
PER_CASE_TIMEOUT = 5.0    # 单用例超时（秒）


def _normalize(text):
    """输出规范化：统一换行、去每行行尾空白、去末尾空行。"""
    lines = (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    lines = [ln.rstrip() for ln in lines]
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def grade(code, language, test_cases, per_case_timeout=PER_CASE_TIMEOUT):
    """评测 code 对用例集的表现。

    test_cases: [{input, expected}]（元素可为 None/缺字段，按空串处理）
    返回：{supported, verdict, passed, total, cases:[{index, status, message}]}
    """
    lang = (language or 'python').lower()
    cases = [c for c in (test_cases or []) if isinstance(c, dict)][:MAX_CASES]
    if lang not in SUPPORTED_LANGUAGES or not cases:
        return {'supported': False, 'verdict': None, 'passed': 0, 'total': len(cases), 'cases': []}

    results = []
    passed = 0
    for i, case in enumerate(cases):
        stdin = str(case.get('input') or '')
        expected = str(case.get('expected') or '')
        r = run_python(code, stdin=stdin, timeout=per_case_timeout)
        if r['error']:
            status, msg = 'SE', r['error']
        elif r['timed_out']:
            status, msg = 'TLE', f'超过 {per_case_timeout:g}s 未结束'
        elif r['exit_code'] not in (0, None):
            status, msg = 'RE', (r['stderr'] or '').strip()[:300] or f'退出码 {r["exit_code"]}'
        elif _normalize(r['stdout']) == _normalize(expected):
            status, msg = 'AC', ''
        else:
            status, msg = 'WA', ''
        if status == 'AC':
            passed += 1
        results.append({'index': i, 'status': status, 'message': msg})

    total = len(results)
    first_fail = next((x['status'] for x in results if x['status'] != 'AC'), None)
    return {
        'supported': True,
        'verdict': 'AC' if passed == total else first_fail,
        'passed': passed,
        'total': total,
        'cases': results,
    }
