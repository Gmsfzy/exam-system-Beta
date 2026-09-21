# -*- coding: utf-8 -*-
"""客观题判分规则矩阵（api.exam_engine.check_objective）

v4.3 multi_score_rule 落地后一直无回归门，本文件锁定：
- 单选/判断：忽略大小写精确匹配
- 填空：忽略大小写
- 多选 all_or_nothing：漏选 0 分（默认规则）
- 多选 partial：非空子集按漏选比例给分，含错选 0 分
- 乱序字母/重复字母归一化（排序去重后比较）
"""
from api.exam_engine import check_objective


class TestSingleAndJudge:
    def test_single_choice_case_insensitive(self):
        assert check_objective('single_choice', 'a', 'A') == (True, 1.0)
        assert check_objective('single_choice', 'A', 'a') == (True, 1.0)

    def test_single_choice_wrong(self):
        assert check_objective('single_choice', 'B', 'A') == (False, 0.0)

    def test_empty_answer(self):
        assert check_objective('single_choice', '', 'A') == (False, 0.0)
        assert check_objective('single_choice', None, 'A') == (False, 0.0)

    def test_true_false(self):
        ok, ratio = check_objective('true_false', 'true', 'TRUE')
        assert ok and ratio == 1.0


class TestFillBlank:
    def test_case_insensitive_equal(self):
        assert check_objective('fill_blank', 'Hello World', 'hello world') == (True, 1.0)

    def test_mismatch(self):
        ok, ratio = check_objective('fill_blank', 'hello!', 'hello')
        assert not ok and ratio == 0.0


class TestMultipleChoiceAllOrNothing:
    def test_exact_match_reordered(self):
        """乱序与重复字母归一化后全对"""
        assert check_objective('multiple_choice', 'CA', 'AC') == (True, 1.0)
        assert check_objective('multiple_choice', 'AACC', 'AC') == (True, 1.0)

    def test_partial_selection_zero(self):
        """默认规则：漏选不给分"""
        assert check_objective('multiple_choice', 'AB', 'ABC') == (False, 0.0)

    def test_wrong_selection_zero(self):
        assert check_objective('multiple_choice', 'ABD', 'ABC') == (False, 0.0)

    def test_non_letter_noise_stripped(self):
        assert check_objective('multiple_choice', 'A、C', 'AC') == (True, 1.0)


class TestMultipleChoicePartial:
    def test_subset_gets_ratio(self):
        ok, ratio = check_objective('multiple_choice', 'A', 'ABC', rule='partial')
        assert not ok and abs(ratio - 1 / 3) < 1e-9

    def test_two_of_three(self):
        ok, ratio = check_objective('multiple_choice', 'CB', 'ABC', rule='partial')
        assert not ok and abs(ratio - 2 / 3) < 1e-9

    def test_exact_still_full(self):
        assert check_objective('multiple_choice', 'ABC', 'CBA', rule='partial') == (True, 1.0)

    def test_any_wrong_letter_zero(self):
        _, ratio = check_objective('multiple_choice', 'ABD', 'ABC', rule='partial')
        assert ratio == 0.0

    def test_empty_selection_zero(self):
        _, ratio = check_objective('multiple_choice', '', 'ABC', rule='partial')
        assert ratio == 0.0

    def test_empty_correct_answer_guard(self):
        """标准答案无字母：防御性 0 分，不除零"""
        assert check_objective('multiple_choice', 'A', '', rule='partial') == (False, 0.0)
