# -*- coding: utf-8 -*-
"""v5.0 作业判分与时效回归门（函数层，内存库）。

锁住 homework.services 的核心语义：
1. 判分矩阵：客观题对错/未答补 0、编程题 OJ AC/CE、主观题待人工；
2. recompute_total：人工优先有效分、pending 计数驱动 graded 状态机；
3. finalize_submission：开放式整体待批、迟交标记 is_late；
4. expiry tick：过期禁迟交自动关闭；截止前提醒只发未交学生且幂等。
HTTP 往返/序列化脱敏由 test_http_e2e 作业全链负责。
"""
from datetime import timedelta

import pytest

from database import db
from database.models import Question, Notification
from utils.timeutil import utcnow
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.services import (
    grade_submission, recompute_total, finalize_submission, homework_expiry_tick,
)


@pytest.fixture()
def hw_env(app, user_factory):
    """教师+学生+专业+四类题（单选/判断/编程/简答）与作业助手。"""
    from database.models import Major
    major = Major(name='HW专业')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('hw_teacher', role='teacher')
    s1 = user_factory('hw_student_1')
    s2 = user_factory('hw_student_2')

    def q(content, answer, qtype, test_cases=None):
        row = Question(content=content, answer=answer, type=qtype, difficulty='easy',
                       major_id=major.id, options=['A. 对', 'B. 错'] if qtype in
                       ('single_choice', 'true_false') else None, test_cases=test_cases)
        db.session.add(row)
        db.session.flush()
        return row

    env = {'teacher': teacher, 's1': s1, 's2': s2,
           'q_single': q('1+1=?', 'B', 'single_choice'),
           'q_tf': q('1>2 是对的？', 'B', 'true_false'),
           'q_prog': q('读入 n 输出 n+1', '', 'programming',
                       test_cases=[{'input': '3', 'expected': '4'}]),
           'q_short': q('简述快排思想', '分治', 'short_answer')}

    def make_hw(hw_type=HomeworkTypeEnum.QUESTION_SET, deadline_hours=24,
               allow_late=True, students=None, items=None):
        hw = Homework(title='作业', hw_type=hw_type, teacher_id=teacher.id,
                      deadline=utcnow() + timedelta(hours=deadline_hours),
                      status=HomeworkStatusEnum.PUBLISHED, allow_late=allow_late)
        db.session.add(hw)
        db.session.flush()
        for i, (question, score) in enumerate(items or []):
            db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=question.id,
                                            score=score, order=i))
        for st in (students if students is not None else [s1, s2]):
            db.session.add(HomeworkStudent(homework_id=hw.id, student_id=st.id))
        db.session.commit()
        return hw

    env['make_hw'] = make_hw
    return env


def _submit(hw, student, answers):
    """构造提交与作答行（不走 HTTP）。answers: {question_id: text}"""
    sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                             status=SubmissionStatusEnum.DRAFT)
    db.session.add(sub)
    db.session.flush()
    for qid, text in answers.items():
        db.session.add(HomeworkAnswer(submission_id=sub.id, question_id=qid, answer=text))
    db.session.commit()
    return sub


def test_grade_objective_matrix(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_single'], 5.0), (hw_env['q_tf'], 3.0)])
    # 单选答对、判断未答（空）：得分 5 + 0，未答补记空行
    sub = _submit(hw, hw_env['s1'], {hw_env['q_single'].id: 'B'})
    earned, total = grade_submission(hw, sub)
    assert total == 8.0 and earned == 5.0
    assert len(sub.answers) == 2   # 未答题补空行
    tf = next(a for a in sub.answers if a.question_id == hw_env['q_tf'].id)
    assert tf.is_correct is False and tf.auto_score == 0.0 and tf.needs_manual_grade is False
    db.session.commit()


def test_grade_programming_oj(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_prog'], 10.0)])
    sub_ac = _submit(hw, hw_env['s1'], {hw_env['q_prog'].id: 'print(int(input())+1)'})
    grade_submission(hw, sub_ac)
    a = sub_ac.answers[0]
    assert a.oj_verdict == 'AC' and a.auto_score == 10.0 and a.needs_manual_grade is False
    sub_ce = _submit(hw, hw_env['s2'], {})   # 空码 CE
    grade_submission(hw, sub_ce)
    assert sub_ce.answers[0].oj_verdict == 'CE' and sub_ce.answers[0].auto_score == 0.0
    db.session.commit()


def test_grade_subjective_pending_and_manual(hw_env):
    hw = hw_env['make_hw'](items=[(hw_env['q_short'], 6.0)])
    sub = _submit(hw, hw_env['s1'], {hw_env['q_short'].id: '采用分治递归排序'})
    earned, total = grade_submission(hw, sub)
    a = sub.answers[0]
    assert a.needs_manual_grade is True and a.auto_score is None
    assert earned == 0 and total == 6.0
    db.session.commit()
    # 未批改前 pending=1；人工给分后 effective 与 pending 归零
    e, m, pending = recompute_total(sub)
    assert pending == 1 and e == 0.0
    a.manual_score = 4.5
    db.session.commit()
    e, m, pending = recompute_total(sub)
    assert pending == 0 and e == 4.5 and sub.total_score == 4.5


def test_finalize_open_and_late_flag(hw_env):
    # 开放式：整体待批（无逐题行，max/total 均空）
    hw = hw_env['make_hw'](hw_type=HomeworkTypeEnum.OPEN)
    sub = HomeworkSubmission(homework_id=hw.id, student_id=hw_env['s1'].id,
                             content='小论文正文')
    db.session.add(sub)
    finalize_submission(hw, sub)
    assert sub.status == SubmissionStatusEnum.SUBMITTED and not sub.is_late
    assert sub.total_score is None and sub.max_score is None
    # 过期迟交：allow_late=True 提交成功但标记 late
    hw2 = hw_env['make_hw'](hw_type=HomeworkTypeEnum.OPEN, deadline_hours=-1)
    sub2 = HomeworkSubmission(homework_id=hw2.id, student_id=hw_env['s1'].id, content='x')
    db.session.add(sub2)
    finalize_submission(hw2, sub2)
    assert sub2.is_late is True


def test_expiry_tick_close_and_remind_idempotent(hw_env):
    closed_hw = hw_env['make_hw'](items=[(hw_env['q_single'], 1.0)],
                                  deadline_hours=-1, allow_late=False)
    remind_hw = hw_env['make_hw'](items=[(hw_env['q_single'], 1.0)],
                                  deadline_hours=0.5, allow_late=True)
    remind_hw.remind_before = 60   # 窗口已开（30min 后截止 < 提前 60min）
    db.session.commit()

    homework_expiry_tick()
    assert closed_hw.status == HomeworkStatusEnum.CLOSED
    db.session.refresh(remind_hw)
    assert remind_hw.reminded_at is not None
    # 提醒只发未交学生：s1 交一题后 tick 不再通知 s1
    notes = Notification.query.filter_by(related_type='homework',
                                         related_id=remind_hw.id).count()
    assert notes == 2   # s1 + s2 各一条
    sub = _submit(remind_hw, hw_env['s1'], {})
    sub.status = SubmissionStatusEnum.SUBMITTED
    db.session.commit()
    # 幂等：reminded_at 已置位，重跑 tick 不重复提醒、不重复关闭
    homework_expiry_tick()
    assert Notification.query.filter_by(related_type='homework',
                                       related_id=remind_hw.id).count() == notes
