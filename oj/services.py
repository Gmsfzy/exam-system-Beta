# -*- coding: utf-8 -*-
"""OJ 判分服务：stdin/stdout 用例评测（v6.9 多语言）

判定语义（对齐主流 OJ 简化版）：
- 输出比对忽略每行行尾空白与文件末尾空行；
- 逐用例判定 AC/WA/TLE/RE/SE/CE，全部 AC 才 verdict=AC；
- 存在失败用例时 verdict 取第一个失败状态（评分按 AC 通过率折算）。

语言差异下沉到 oj.adapters 适配器：check 静态拒绝→SE，compile 失败→CE，
运行期非零退出→RE，超时→TLE。工具链缺失/未知语言 → supported=False，由调用方回落 AI/人工。
"""
import tempfile

from oj.adapters import get_adapter

# 已注册语言（参考用；实际是否可评测还取决于适配器 available() 工具链就绪）
SUPPORTED_LANGUAGES = {'python', 'java', 'javascript', 'c', 'cpp', 'asm', 'sql', 'avr'}
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
    adapter = get_adapter(lang)
    if adapter is None or not adapter.available() or not cases:
        return {'supported': False, 'verdict': None, 'passed': 0, 'total': len(cases), 'cases': []}

    # 静态防呆拒绝：整题判 SE（不进入编译/运行）
    reason = adapter.check(code)
    if reason:
        return {'supported': True, 'verdict': 'SE', 'passed': 0, 'total': len(cases),
                'cases': [{'index': i, 'status': 'SE', 'message': reason} for i in range(len(cases))]}

    with tempfile.TemporaryDirectory(prefix='oj-') as workdir:
        # 编译/语法校验：失败整题判 CE
        compile_err = adapter.compile(workdir, code)
        if compile_err:
            return {'supported': True, 'verdict': 'CE', 'passed': 0, 'total': len(cases),
                    'cases': [{'index': i, 'status': 'CE', 'message': compile_err} for i in range(len(cases))]}

        results = []
        passed = 0
        for i, case in enumerate(cases):
            stdin = str(case.get('input') or '')
            expected = str(case.get('expected') or '')
            r = adapter.run(workdir, stdin=stdin, timeout=per_case_timeout)
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
