# -*- coding: utf-8 -*-
"""判分口径统一对偶矩阵（v5.26）

锁定 api.learning_routes._check_answer 已委托 api.exam_engine.check_objective：
- 四类客观题：与 check_objective 判定逐格一致（单一实现，杜绝语义漂移）
- 主观/编程/未知题型：返回 None（走人工/自评链路，白名单外不自动判）
- 脏格式回归：多选答案含逗号/顿号/空格不再误判（本次修复的实际 bug）
- 有意的行为变化：空多选答案对空标准答案由 True 改为 False（空选不给对）
"""
from api.learning_routes import _check_answer, _OBJECTIVE_TYPES
from api.exam_engine import check_objective


class TestParityWithCheckObjective:
    """客观题四类：_check_answer 的布尔结果必须与 check_objective 完全一致"""

    CASES = [
        ('single_choice', 'a', 'A'),
        ('single_choice', 'B', 'A'),
        ('single_choice', '', 'A'),
        ('single_choice', None, 'A'),
        ('true_false', 'true', 'TRUE'),
        ('true_false', 'false', 'TRUE'),
        ('fill_blank', 'Hello World', 'hello world'),
        ('fill_blank', 'hello!', 'hello'),
        ('multiple_choice', 'CA', 'AC'),
        ('multiple_choice', 'AACC', 'AC'),
        ('multiple_choice', 'AB', 'ABC'),
        ('multiple_choice', 'ABD', 'ABC'),
        ('multiple_choice', 'A、C', 'AC'),
        ('multiple_choice', 'A,C', 'AC'),
        ('multiple_choice', 'a c', 'AC'),
        ('multiple_choice', '', 'ABC'),
    ]

    def test_matrix_parity(self):
        for q_type, s, c in self.CASES:
            expected, _ratio = check_objective(q_type, s, c)
            assert _check_answer(q_type, s, c) is expected or \
                _check_answer(q_type, s, c) == expected, f'漂移: {q_type} {s!r} vs {c!r}'


class TestSubjectiveReturnsNone:
    """白名单之外一律 None：主观题/编程题/未知类型不自动判对错"""

    def test_essay_none(self):
        assert _check_answer('essay', '任意作答', '参考答案') is None

    def test_short_answer_none(self):
        assert _check_answer('short_answer', 'x', 'x') is None

    def test_programming_none(self):
        assert _check_answer('programming', 'print(1)', 'print(1)') is None

    def test_unknown_type_none(self):
        assert _check_answer('new_type', 'a', 'a') is None

    def test_whitelist_locked(self):
        assert _OBJECTIVE_TYPES == ('single_choice', 'true_false',
                                    'multiple_choice', 'fill_blank')


class TestDirtyFormatRegression:
    """v5.26 修复点：旧整串排序比对对脏格式误判，统一后与考试口径一致"""

    def test_comma_separated_multi_choice_ok(self):
        # 旧实现：'A,C' 排序含逗号 != 'AC' → 误判 False；新实现判对
        assert _check_answer('multiple_choice', 'A,C', 'AC') is True

    def test_noisy_correct_answer_ok(self):
        # 存量标准答案脏（Word 导入/AI 出题带顿号）也不再误判
        assert _check_answer('multiple_choice', 'AC', 'A、C') is True

    def test_wrong_selection_still_false(self):
        assert _check_answer('multiple_choice', 'AD', 'AC') is False


class TestIntendedBehaviorChange:
    def test_empty_vs_empty_multi_false(self):
        """空多选对空标准答案：旧 True → 新 False（防御性不给对，属有意修正）"""
        assert _check_answer('multiple_choice', '', '') is False
