# -*- coding: utf-8 -*-
"""v7.20 作业 AI 批改建议落库（函数层，内存库）。

`ai_suggest_grading` 的 docstring 以前自己写着「不落库」：建议只在接口返回里活一次，
教师采不采纳、当时 AI 说了什么，事后一概查不出来——「AI 建议 8 分、教师给 5 分」这
3 分差在哪永远没有对照，判分公平性就没有可回溯的入口。锁住四件事：
① 建议分/批语/时间落到 `ai_suggested_*`，接口调用方丢了也还在库里；
② 建议与 `manual_score` 互不覆盖，教师已给分或客观题已自动判分的行不再重推；
③ AI 失败只计 failed，不写脏字段；
④ 建议只进教师视角，学生那份 to_dict 拿不到。
"""
import json

import pytest

from database import db
from database.models import Major, Question
from utils.timeutil import utcnow
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.services import ai_suggest_grading


@pytest.fixture()
def hw_env(app, user_factory):
    """教师一份作业：一道主观题待人工批改（满分 10），学生已提交作答。"""
    teacher = user_factory('sug_teacher', role='teacher')
    student = user_factory('sug_student')
    major = Major(name='AI建议专业')
    db.session.add(major)
    db.session.flush()
    q = Question(content='简述矩阵秩的三种等价定义。', answer='秩=极大线性无关组个数',
                 type='subjective', difficulty='medium', major_id=major.id)
    db.session.add(q)
    db.session.commit()

    hw = Homework(title='AI建议作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                  teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED, allow_late=True)
    db.session.add(hw)
    db.session.flush()
    db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id, score=10.0, order=0))
    db.session.add(HomeworkStudent(homework_id=hw.id, student_id=student.id))
    db.session.commit()

    sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                             status=SubmissionStatusEnum.SUBMITTED, submitted_at=utcnow())
    db.session.add(sub)
    db.session.flush()
    # needs_manual_grade 由建答卷时按题型置好，这里直接构造待批改态
    a = HomeworkAnswer(submission_id=sub.id, question_id=q.id,
                       answer='秩就是极大线性无关组的个数', needs_manual_grade=True)
    db.session.add(a)
    db.session.commit()
    return {'teacher': teacher, 'student': student, 'hw': hw, 'q': q,
            'sub': sub, 'answer': a}


def _grade(monkeypatch, score=80, comment='思路正确，但少写了一个定义'):
    from ai_service.services import ai_client

    def fake(question_content, correct_answer, student_answer):
        return json.dumps({'is_correct': True, 'score': score, 'analysis': comment},
                          ensure_ascii=False)
    monkeypatch.setattr(ai_client, 'grade_answer', fake)


def test_suggestion_is_persisted(hw_env, monkeypatch):
    _grade(monkeypatch)
    res = ai_suggest_grading(hw_env['sub'])
    assert res['failed'] == 0 and len(res['suggestions']) == 1
    sug = res['suggestions'][0]
    assert sug['answer_id'] == hw_env['answer'].id
    # AI 给的是 0-100 百分比，落库前已按本题满分换算
    assert sug['score'] == 8.0 and sug['max_score'] == 10.0
    assert sug['is_correct'] is True and sug['comment'].startswith('思路正确')
    assert sug['suggested_at']

    a = hw_env['answer']
    db.session.refresh(a)
    assert a.ai_suggested_score == 8.0
    assert a.ai_suggested_comment == '思路正确，但少写了一个定义'
    assert a.ai_suggested_at is not None
    # 建议不是成绩：教师没点采纳，这份答卷仍然是没批过的
    assert a.manual_score is None and a.auto_score is None
    assert hw_env['sub'].total_score is None

    # 返回给调用方的那份被丢掉也查得回来（这正是「不落库」丢掉的东西）
    assert ai_suggest_grading(hw_env['sub'])['suggestions'][0]['score'] == 8.0
    db.session.refresh(a)
    assert a.ai_suggested_score == 8.0


def test_regenerate_updates_suggestion_only(hw_env, monkeypatch):
    """重跑建议覆盖 ai_suggested_*，但绝不动 manual_score：重批覆盖的是人工分。"""
    _grade(monkeypatch, score=80)
    ai_suggest_grading(hw_env['sub'])
    a = hw_env['answer']
    db.session.refresh(a)
    first_at = a.ai_suggested_at

    _grade(monkeypatch, score=60, comment='漏了两条定义')
    res = ai_suggest_grading(hw_env['sub'])
    db.session.refresh(a)
    assert res['suggestions'][0]['score'] == 6.0
    assert a.ai_suggested_score == 6.0 and a.ai_suggested_comment == '漏了两条定义'
    assert a.ai_suggested_at >= first_at
    assert a.manual_score is None


def test_teacher_score_and_auto_graded_rows_are_skipped(hw_env, monkeypatch):
    """教师已给分（或客观题已自动判分）的行不再重推建议，也不覆盖已有留痕。"""
    _grade(monkeypatch, score=80)
    ai_suggest_grading(hw_env['sub'])
    a = hw_env['answer']
    a.manual_score = 5.0
    db.session.add(HomeworkAnswer(submission_id=hw_env['sub'].id,
                                  question_id=hw_env['q'].id, answer='B',
                                  is_correct=True, auto_score=10.0,
                                  needs_manual_grade=False))
    db.session.commit()

    res = ai_suggest_grading(hw_env['sub'])
    assert res == {'suggestions': [], 'failed': 0}
    db.session.refresh(a)
    assert a.manual_score == 5.0 and a.ai_suggested_score == 8.0


def test_ai_failure_leaves_no_partial_trace(hw_env, monkeypatch):
    from ai_service.services import ai_client

    def boom(*a, **kw):
        raise RuntimeError('AI 连接中断')
    monkeypatch.setattr(ai_client, 'grade_answer', boom)

    res = ai_suggest_grading(hw_env['sub'])
    assert res == {'suggestions': [], 'failed': 1}
    a = hw_env['answer']
    db.session.refresh(a)
    assert a.ai_suggested_score is None and a.ai_suggested_comment is None
    assert a.ai_suggested_at is None


def test_suggestion_visible_to_teacher_only(hw_env, monkeypatch):
    _grade(monkeypatch, score=80)
    ai_suggest_grading(hw_env['sub'])
    a = hw_env['answer']

    student_view = a.to_dict(for_teacher=False, max_score=10.0)
    assert 'ai_suggested_score' not in student_view
    assert 'ai_suggested_comment' not in student_view
    # 学生看到「AI 说 8 分而我拿 5 分」只会起争议，这份数据是事后审计用的
    teacher_view = a.to_dict(for_teacher=True, max_score=10.0)
    assert teacher_view['ai_suggested_score'] == 8.0
    assert teacher_view['ai_suggested_comment'].startswith('思路正确')
    assert teacher_view['ai_suggested_at'] and teacher_view['manual_score'] is None
