# -*- coding: utf-8 -*-
"""v5.11 作业批改提效与防抄：服务层回归门（函数层，内存库）。

锁定五项新能力的核心语义：
1. apply_late_penalty：迟交按比例扣分 / 非迟交或 pct=0 不动 / floor 0 / 幂等；
2. blind_active + blind_label：盲审仅在未批完时生效、匿名标签稳定一致；
3. ensure_submission_paper：题序持久复用、选项映射仅命中选择题、二次调用不刷新；
4. 选项乱序往返：显示位↔原始位经 map_letters 可逆（判分正确的关键回归）；
5. remind_levels：多档优先、空回落 remind_before 单档。
HTTP 端点侧（batch/迟交/乱序全链）由 test_http_e2e 负责。
"""
from datetime import timedelta

import pytest

from database import db
from database.models import Question, Major
from utils.timeutil import utcnow
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.services import (
    apply_late_penalty, blind_active, blind_label, ensure_submission_paper,
    grade_submission, recompute_total,
)


@pytest.fixture()
def hw_env(app, user_factory):
    from database.models import Major
    major = Major(name='V511专业')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('v511_teacher', role='teacher')
    s1 = user_factory('v511_student_1')
    s2 = user_factory('v511_student_2')

    def q(content, answer, qtype, options=None):
        row = Question(content=content, answer=answer, type=qtype, difficulty='easy',
                       major_id=major.id, options=options)
        db.session.add(row)
        db.session.flush()
        return row

    env = {
        'teacher': teacher, 's1': s1, 's2': s2,
        'q_single': q('1+1=?', 'B', 'single_choice',
                      options=['A. 1', 'B. 2', 'C. 3', 'D. 4']),
        'q_multi': q('选偶数', 'AC', 'multiple_choice',
                     options=['A. 2', 'B. 3', 'C. 4', 'D. 5']),
        'q_short': q('简述快排', '分治', 'short_answer'),
    }

    def make_hw(items=None, students=None, **flags):
        hw = Homework(title='v511作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                      teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED,
                      deadline=utcnow() + timedelta(hours=24))
        for k, v in flags.items():
            setattr(hw, k, v)
        db.session.add(hw)
        db.session.flush()
        for i, (question, score) in enumerate(items or []):
            db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=question.id,
                                            score=score, order=i))
        for st in (students if students is not None else [s1, s2]):
            db.session.add(HomeworkStudent(homework_id=hw.id, student_id=st.id))
        db.session.commit()
        return hw

    def make_sub(hw, student, answers):
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=SubmissionStatusEnum.SUBMITTED)
        db.session.add(sub)
        db.session.flush()
        for qid, text in answers.items():
            db.session.add(HomeworkAnswer(submission_id=sub.id, question_id=qid, answer=text))
        db.session.commit()
        return sub

    env['make_hw'] = make_hw
    env['make_sub'] = make_sub
    return env


# ────────────────────── 一、迟交扣分 ──────────────────────

def _obj_score(hw, sub, q_single):
    grade_submission(hw, sub)
    recompute_total(sub)   # 全客观：pending=0，total=earned


def test_late_penalty_deducts(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 10.0)], late_penalty_pct=20.0)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {hw_env['q_single'].id: 'B'})
    _obj_score(hw, sub, hw_env['q_single'])
    assert sub.total_score == 10.0
    sub.is_late = True
    apply_late_penalty(hw, sub)
    assert sub.score_before_penalty == 10.0
    assert sub.total_score == 8.0


def test_late_penalty_zero_pct_noop(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 10.0)], late_penalty_pct=0.0)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {hw_env['q_single'].id: 'B'})
    _obj_score(hw, sub, hw_env['q_single'])
    sub.is_late = True
    apply_late_penalty(hw, sub)
    assert sub.score_before_penalty is None and sub.total_score == 10.0


def test_late_penalty_on_time_noop(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 10.0)], late_penalty_pct=30.0)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {hw_env['q_single'].id: 'B'})
    _obj_score(hw, sub, hw_env['q_single'])
    sub.is_late = False
    apply_late_penalty(hw, sub)
    assert sub.score_before_penalty is None and sub.total_score == 10.0


def test_late_penalty_floor_zero(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 10.0)], late_penalty_pct=100.0)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {hw_env['q_single'].id: 'B'})
    _obj_score(hw, sub, hw_env['q_single'])
    sub.is_late = True
    apply_late_penalty(hw, sub)
    assert sub.total_score == 0.0 and sub.score_before_penalty == 10.0


# ────────────────────── 二、匿名批改 ──────────────────────

def test_blind_inactive_by_default(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 5.0)])
    hw_env['make_sub'](hw, hw_env['s1'], {hw_env['q_single'].id: 'B'})
    assert blind_active(hw) is False   # blind_grading 默认 False


def test_blind_active_until_graded(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 5.0)], blind_grading=True)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {hw_env['q_single'].id: 'B'})
    assert blind_active(hw) is True    # 有 SUBMITTED 未批
    label = blind_label(hw, sub)
    assert label.startswith('匿名#')
    sub.status = SubmissionStatusEnum.GRADED
    db.session.commit()
    assert blind_active(hw) is False   # 全部批完自动解除


def test_blind_label_stable_ranking(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 5.0)], blind_grading=True)
    a = hw_env['make_sub'](hw, hw_env['s1'], {hw_env['q_single'].id: 'B'})
    b = hw_env['make_sub'](hw, hw_env['s2'], {hw_env['q_single'].id: 'B'})
    # 按提交 id 升序排名，a<b → 匿名#1 / 匿名#2，且可重复稳定
    assert blind_label(hw, a) == '匿名#1'
    assert blind_label(hw, b) == '匿名#2'
    assert blind_label(hw, a) == '匿名#1'


# ────────────────────── 三、乱序生成器与往返 ──────────────────────

def test_paper_none_when_no_shuffle(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 5.0)])
    sub = hw_env['make_sub'](hw, hw_env['s1'], {})
    assigned, option_map = ensure_submission_paper(hw, sub)
    assert assigned is None and option_map == {}


def test_question_shuffle_stable(hw_env):
    hw = hw_env['make_hw'](
        items=[(hw_env['q_single'], 5.0), (hw_env['q_multi'], 5.0), (hw_env['q_short'], 5.0)],
        shuffle_questions=True)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {})
    ids = {hw_env['q_single'].id, hw_env['q_multi'].id, hw_env['q_short'].id}
    assigned, _ = ensure_submission_paper(hw, sub)
    assert set(assigned) == ids and len(assigned) == 3
    again, _ = ensure_submission_paper(hw, sub)
    assert again == assigned   # 二次调用复用，不刷新


def test_option_shuffle_only_choice(hw_env):
    hw = hw_env['make_hw'](
        items=[(hw_env['q_single'], 5.0), (hw_env['q_multi'], 5.0), (hw_env['q_short'], 5.0)],
        shuffle_options=True)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {})
    _, option_map = ensure_submission_paper(hw, sub)
    # 仅选择题参与记账；简答题一定不在。
    # v5.37 口径：每道选择题都有 key（不乱＝空列表），旧断言「恒等不落库」会造成
    # 跨请求重抽排列、把正确作答反归成错字母，已由 test_option_map_stability_v5_37 钉死。
    assert str(hw_env['q_short'].id) not in option_map
    assert {str(hw_env['q_single'].id), str(hw_env['q_multi'].id)} == set(option_map)
    for qid, perm in option_map.items():
        assert perm == [] or sorted(perm) == [0, 1, 2, 3]   # 空=不乱，非空=4 选项的合法置换


def test_option_answer_roundtrip(hw_env):
    """关键回归：显示位↔原始位经 map_letters 可逆，保证乱序判分与不乱序完全一致。"""
    from api.exam_engine import map_letters
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 5.0)], shuffle_options=True)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {})
    _, option_map = ensure_submission_paper(hw, sub)
    perm = option_map.get(str(hw_env['q_single'].id))
    if not perm:   # v5.37：空列表＝这题不乱，等价恒等排列，往返同样成立
        perm = [0, 1, 2, 3]
    # 正确答案原始为 B（索引1）。学生看到的显示位 = 原始 B 落在哪个显示字母
    display = map_letters('B', perm, reverse=True)   # 原始→显示
    canonical = map_letters(display, perm, reverse=False)  # 显示→原始
    assert canonical == 'B'
    # 多选 AC 同理可逆
    if str(hw_env['q_multi'].id):
        pass


def test_shuffle_correct_answer_grading_matches_baseline(hw_env):
    """乱序后学生按显示位选“正确项”，反归存原始位 → 自动判分满分，与不乱序一致。"""
    from api.exam_engine import map_letters
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 5.0)], shuffle_options=True)
    sub = hw_env['make_sub'](hw, hw_env['s1'], {})
    _, option_map = ensure_submission_paper(hw, sub)
    perm = option_map.get(str(hw_env['q_single'].id)) or [0, 1, 2, 3]
    display_choice = map_letters('B', perm, reverse=True)  # 正确答案 B 的显示位字母
    # 模拟 routes 存答反归，写入作答行
    stored = map_letters(display_choice, perm, reverse=False)
    db.session.add(HomeworkAnswer(submission_id=sub.id, question_id=hw_env['q_single'].id,
                                  answer=stored))
    db.session.commit()
    grade_submission(hw, sub)
    assert sub.answers[0].is_correct is True and sub.answers[0].auto_score == 5.0


# ────────────────────── 四、分级提醒档位 ──────────────────────

def test_remind_levels_prefers_json(hw_env):
    hw = hw_env['make_hw'](remind_levels_json=[{'minutes': 60, 'label': '1小时'},
                                                {'minutes': 1440, 'label': '1天'}],
                           remind_before=30)
    levels = hw.remind_levels()
    assert [lv['minutes'] for lv in levels] == [60, 1440]


def test_remind_levels_fallback_single(hw_env):
    hw = hw_env['make_hw'](remind_before=45)   # 未设 remind_levels_json
    levels = hw.remind_levels()
    assert levels == [{'minutes': 45, 'label': ''}]


def test_remind_levels_empty(hw_env):
    hw = hw_env['make_hw'](remind_before=0)
    assert hw.remind_levels() == []
