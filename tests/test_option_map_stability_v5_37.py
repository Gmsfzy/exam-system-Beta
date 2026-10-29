# -*- coding: utf-8 -*-
"""选项乱序映射稳定性回归门（v5.37 缺陷修复）

背景缺陷（v5.11 起潜伏，偶发约 1/n! 每题）：`ensure_submission_paper` 只在
抽到**非恒等**排列时把排列写进 `option_map_json`，恒等排列时整个 key 不落库。
而该函数在 take / 保存答案 / 提交三处都会被调用，于是：
  take 抽中恒等 → 学生看到原序，选「C」；
  submit 再调 → key 仍缺失 → 重抽一个新排列并按它反归 → 存成「A」/「B」
  → 自动判分把正确答案判 0 分（graded=True、total_score=0.0，教师侧无感）。

锁定口径：
1. 每道 ≥2 选项的选择题都被记账：乱序存排列，不乱存空列表（决策一次定型）；
2. 二次调用绝不重抽（跨请求映射一致），空列表在读侧等价「原样显示/原样存答」；
3. 24 种排列全量往返：按显示位选正确项 → 反归存原始位 → 判满分，与不乱序一致。
"""
import itertools

import pytest

from database import db
from database.models import Question, Major
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.services import ensure_submission_paper, grade_submission


class _Rng:
    """可控随机源：按队列吐出「索引排列」，其余 shuffle 不动（避免影响抽题等逻辑）。"""

    def __init__(self, perms):
        self.perms = list(perms)
        self.shuffles = 0

    def shuffle(self, seq):
        self.shuffles += 1
        if seq == list(range(len(seq))) and self.perms:
            seq[:] = self.perms.pop(0)

    def randint(self, a, b):
        return a


@pytest.fixture()
def hw_env(app, user_factory):
    """最小作业环境：一个单选（答案为 B，4 选项）+ 一个多选 + 一个简答。"""
    major = Major(name='V537专业')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('v537_teacher', role='teacher')
    student = user_factory('v537_student')

    def q(content, answer, qtype, options=None):
        row = Question(content=content, answer=answer, type=qtype, difficulty='easy',
                       major_id=major.id, options=options)
        db.session.add(row)
        db.session.flush()
        return row

    env = {
        'teacher': teacher, 'student': student,
        'q_single': q('1+1=?', 'B', 'single_choice',
                      options=['A. 1', 'B. 2', 'C. 3', 'D. 4']),
        'q_multi': q('选偶数', 'AC', 'multiple_choice',
                     options=['A. 2', 'B. 3', 'C. 4', 'D. 5']),
        'q_short': q('简述快排', '分治', 'short_answer'),
    }

    def make_hw(items, **flags):
        hw = Homework(title='v537作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                      teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED)
        for k, v in flags.items():
            setattr(hw, k, v)
        db.session.add(hw)
        db.session.flush()
        for i, (question, score) in enumerate(items):
            db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=question.id,
                                            score=score, order=i))
        db.session.add(HomeworkStudent(homework_id=hw.id, student_id=student.id))
        db.session.commit()
        return hw

    def make_sub(hw):
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=SubmissionStatusEnum.DRAFT)
        db.session.add(sub)
        db.session.commit()
        return sub

    env.update(make_hw=make_hw, make_sub=make_sub)
    return env


def test_identity_perm_is_recorded(hw_env, monkeypatch):
    """抽中恒等排列也要落库（空列表），且读侧等价「不乱」。"""
    import homework.services as hs
    monkeypatch.setattr(hs, 'random', _Rng([[0, 1, 2, 3]]))
    hw = hw_env['make_hw']([(hw_env['q_single'], 5.0)], shuffle_options=True)
    sub = hw_env['make_sub'](hw)

    _, first = ensure_submission_paper(hw, sub)
    assert first == {str(hw_env['q_single'].id): []}
    assert sub.option_map_json == first     # 决策已持久化，不再依赖下次重抽


def test_second_call_never_redraws(hw_env, monkeypatch):
    """缺陷正解：take 抽中恒等后，submit 再调不得重抽新排列来反归。"""
    import homework.services as hs
    rng = _Rng([[0, 1, 2, 3], [1, 0, 2, 3]])   # 第一次恒等，第二次想打乱
    monkeypatch.setattr(hs, 'random', rng)
    hw = hw_env['make_hw']([(hw_env['q_single'], 5.0)], shuffle_options=True)
    sub = hw_env['make_sub'](hw)

    _, first = ensure_submission_paper(hw, sub)
    _, second = ensure_submission_paper(hw, sub)
    assert second == first
    assert rng.shuffles == 1                  # 第二次连抽都不该发生


@pytest.mark.parametrize('perm', [list(p) for p in itertools.permutations(range(4))])
def test_display_canonical_roundtrip(hw_env, monkeypatch, perm):
    """任意排列（含恒等）：显示位选正确项 → 反归存原始位 → 自动判满分。"""
    from api.exam_engine import display_options, map_letters
    import homework.services as hs
    monkeypatch.setattr(hs, 'random', _Rng([perm]))
    hw = hw_env['make_hw']([(hw_env['q_single'], 5.0)], shuffle_options=True)
    sub = hw_env['make_sub'](hw)

    _, option_map = ensure_submission_paper(hw, sub)
    p = option_map.get(str(hw_env['q_single'].id))
    assert str(hw_env['q_single'].id) in option_map      # 恒等也要有 key

    # 复现读取侧（homework/routes.py 的 _take_question_payload / _canonical_choice_answer）
    q = hw_env['q_single']
    shown = display_options(q, p) if p else q.options
    disp = next(o for o in shown if '2' in str(o))[0]     # 正确项「2」的显示字母
    stored = map_letters(disp, p, reverse=False) if p else disp
    assert stored == 'B', f'perm={perm} disp={disp} stored={stored} shown={shown}'

    db.session.add(HomeworkAnswer(submission_id=sub.id, question_id=q.id, answer=stored))
    db.session.commit()
    grade_submission(hw, sub)
    assert sub.answers[0].is_correct is True and sub.answers[0].auto_score == 5.0


def test_non_choice_questions_stay_unmapped(hw_env):
    """简答题不参与乱序：不记账、不受影响（向后兼容旧数据无 key 的语义）。"""
    hw = hw_env['make_hw'](
        [(hw_env['q_single'], 5.0), (hw_env['q_multi'], 5.0), (hw_env['q_short'], 5.0)],
        shuffle_options=True)
    sub = hw_env['make_sub'](hw)
    _, option_map = ensure_submission_paper(hw, sub)
    assert str(hw_env['q_short'].id) not in option_map
    assert {str(hw_env['q_single'].id), str(hw_env['q_multi'].id)} == set(option_map)
    for p in option_map.values():
        assert p == [] or sorted(p) == [0, 1, 2, 3]
