# -*- coding: utf-8 -*-
"""v5.15 评分量规 Rubric：维度/得分校验与派生的回归门（函数层，内存库）。

锁定语义（量规仅作结构化拆解/建议，不改 total_score/manual_score 推导）：
1. HomeworkRubric.dimensions()/max_total()：维度求和建议满分；
2. _clean_rubric_dimensions：非空、label 非空、max_score 数字且非负、levels 归一；
3. _normalize_rubric_scores：dict/list 两种入参、越界拒绝、缺失/空跳过、按量规索引对齐；
4. Homework.to_dict 回显 rubric_id（师生均含）、教师含 rubric_title；
5. Submission.to_dict 教师侧含 rubric_scores 快照。
HTTP 端点侧（CRUD/归属/批改落库不改总分）由 test_http_e2e 负责。
"""
import pytest

from database import db
from homework.models import (
    Homework, HomeworkSubmission, HomeworkRubric, HomeworkStatusEnum,
    HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.routes import _clean_rubric_dimensions, _normalize_rubric_scores


@pytest.fixture()
def rb_env(app, user_factory):
    teacher = user_factory('v515_teacher', role='teacher')
    student = user_factory('v515_student')

    def make_rubric(dims=None, title='作文量规'):
        rb = HomeworkRubric(teacher_id=teacher.id, title=title,
                            description='内容/语言两维',
                            dimensions_json=dims if dims is not None else [
                                {'label': '内容', 'max_score': 60, 'levels': [{'score': 60, 'desc': '切题'}]},
                                {'label': '语言', 'max_score': 40, 'levels': []}])
        db.session.add(rb)
        db.session.commit()
        return rb

    def make_homework(rb=None, sub_rubric_scores=None):
        hw = Homework(title='量规作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                      teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED,
                      rubric_id=rb.id if rb else None)
        db.session.add(hw)
        db.session.flush()
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=SubmissionStatusEnum.GRADED,
                                 total_score=75.0, max_score=100.0, comment='好')
        sub.rubric_scores_json = sub_rubric_scores
        db.session.add(sub)
        db.session.commit()
        return hw, sub

    return {'make_rubric': make_rubric, 'make_homework': make_homework,
            'teacher': teacher, 'student': student}


def test_rubric_dimensions_and_total(rb_env):
    rb = rb_env['make_rubric']()
    assert rb.max_total() == 100.0
    d = rb.to_dict()
    assert d['max_total'] == 100.0 and len(d['dimensions']) == 2
    assert d['dimensions'][0]['label'] == '内容'


def test_clean_dimensions_valid_and_errors(rb_env):
    ok, err = _clean_rubric_dimensions([{'label': '内容', 'max_score': 60,
                                         'levels': [{'score': 60, 'desc': 'x'}]}])
    assert err is None and ok[0]['max_score'] == 60.0
    assert len(ok[0]['levels']) == 1
    # 空列表
    assert _clean_rubric_dimensions([])[1] is not None
    # label 空
    assert _clean_rubric_dimensions([{'label': '', 'max_score': 10}])[1] is not None
    # max_score 非数字
    assert _clean_rubric_dimensions([{'label': 'a', 'max_score': 'x'}])[1] is not None
    # max_score 负
    assert _clean_rubric_dimensions([{'label': 'a', 'max_score': -1}])[1] is not None


def test_normalize_scores_dict_and_list(rb_env):
    rb = rb_env['make_rubric']()   # 内容 max 60 / 语言 max 40
    # dict 形式 {index: score}
    out, err = _normalize_rubric_scores(rb, {'0': 50, '1': 30})
    assert err is None
    assert {o['index']: o['score'] for o in out} == {0: 50.0, 1: 30.0}
    # list 形式 [{index, score}]，缺失索引跳过、空值跳过
    out2, err2 = _normalize_rubric_scores(rb, [{'index': 1, 'score': 38}, {'index': 0, 'score': None}])
    assert err2 is None and len(out2) == 1 and out2[0] == {'index': 1, 'label': '语言', 'score': 38.0}
    # 越界拒绝
    assert _normalize_rubric_scores(rb, {'0': 70})[1] is not None    # 内容 max 60
    # 非数字
    assert _normalize_rubric_scores(rb, {'0': 'abc'})[1] is not None


def test_homework_dict_rubric_echo(rb_env):
    rb = rb_env['make_rubric']()
    hw, _sub = rb_env['make_homework'](rb=rb)
    assert hw.to_dict()['rubric_id'] == rb.id
    td = hw.to_dict(for_teacher=True)
    assert td['rubric_id'] == rb.id and td['rubric_title'] == '作文量规'


def test_submission_dict_rubric_scores(rb_env):
    scores = [{'index': 0, 'label': '内容', 'score': 50.0}]
    _hw, sub = rb_env['make_homework'](sub_rubric_scores=scores)
    t = sub.to_dict(for_teacher=True)
    assert t['rubric_scores'] == scores
    s = sub.to_dict(for_teacher=False)
    assert 'rubric_scores' not in s          # 学生侧不下发教师量规分
    # total_score 未因量规分改变
    assert t['total_score'] == 75.0
