# -*- coding: utf-8 -*-
"""v5.21 课程成绩册/权重聚合：模型 + 纯聚合逻辑回归门（内存库）。

锁定语义（跨模块只读视图，不改判分/total_score/ledger）：
1. GradeComponentTypeEnum.ALL={homework,exam}、GradeAggregateEnum.VALUES=(mean,all,best)；
2. _rate_from_pools 三种聚合口径（mean 仅计已完成 / all 未做计入分母 / best 取最高）+ 空项 None；
3. build_course_gradebook 按权重加权总评（Σrate×weight/Σweight×100），权重 0 组件排除；
4. 只读：聚合后 submission.total_score/status 不变（正交红线）；
5. course_grade_scheme 随 Course 级联删除。
端点侧（scheme CRUD/鉴权/学生本人/404）由 test_http_e2e 覆盖。
"""
import pytest

from database import db
from database.models import (
    Major, Course, Exam, Result, User,
    CourseGradeScheme, GradeComponentTypeEnum, GradeAggregateEnum, ExamStatusEnum,
)
from homework.models import (
    Homework, HomeworkSubmission, HomeworkStatusEnum, HomeworkTypeEnum,
    SubmissionStatusEnum,
)
from api.gradebook_routes import build_course_gradebook, _rate_from_pools


def test_gradebook_enums():
    assert set(GradeComponentTypeEnum.ALL) == {'homework', 'exam'}
    assert GradeAggregateEnum.VALUES == ('mean', 'all', 'best')


def test_rate_from_pools_semantics():
    item_rates = {1: {10: 0.8}, 2: {10: 0.6}}       # 学生 10 完成两项：0.8 / 0.6
    assert _rate_from_pools(item_rates, 10, 'mean') == pytest.approx(0.7)
    assert _rate_from_pools(item_rates, 10, 'best') == pytest.approx(0.8)
    # all：分母为全部项（此处 2 项），仅一项有数据 → 0.8/2
    partial = {1: {10: 0.8}, 2: {}}
    assert _rate_from_pools(partial, 10, 'all') == pytest.approx(0.4)
    assert _rate_from_pools(partial, 10, 'mean') == pytest.approx(0.8)  # mean 只看已完成
    assert _rate_from_pools(partial, 99, 'mean') is None                 # 无数据 → None
    assert _rate_from_pools({}, 10, 'all') is None                       # 无项 → None


@pytest.fixture()
def gb_env(app, user_factory):
    teacher = user_factory('v521_teacher', role='teacher')
    s_full = user_factory('v521_s_full')
    s_part = user_factory('v521_s_part')

    def make():
        major = Major(name='v521专业')
        db.session.add(major)
        db.session.flush()
        course = Course(name='v521课程', major_id=major.id)
        db.session.add(course)
        db.session.flush()

        # 两份作业，各满分 100
        def add_hw(scores):  # {student_id: (got, max)}
            hw = Homework(title='v521作业', hw_type=HomeworkTypeEnum.OPEN,
                          teacher_id=teacher.id, course_id=course.id,
                          status=HomeworkStatusEnum.PUBLISHED)
            db.session.add(hw)
            db.session.flush()
            for sid, (got, mx) in scores.items():
                db.session.add(HomeworkSubmission(
                    homework_id=hw.id, student_id=sid, status=SubmissionStatusEnum.GRADED,
                    total_score=got, max_score=mx))
            return hw

        add_hw({s_full.id: (80.0, 100.0), s_part.id: (60.0, 100.0)})   # hw1
        add_hw({s_full.id: (60.0, 100.0)})                              # hw2（s_part 未交）

        # 一场考试，s_full 得分 90/100
        exam = Exam(title='v521考试', creator_id=teacher.id, course_id=course.id,
                    status=ExamStatusEnum.PUBLISHED, start_time=db.func.now(),
                    end_time=db.func.now(), duration=60)
        db.session.add(exam)
        db.session.flush()
        db.session.add(Result(exam_id=exam.id, student_id=s_full.id, score=90.0, total_score=100.0))
        db.session.commit()
        return course.id

    return {'make': make, 'teacher': teacher, 's_full': s_full, 's_part': s_part}


def _add_scheme(course_id, teacher_id, component_type, weight, aggregate='mean', name=''):
    db.session.add(CourseGradeScheme(
        course_id=course_id, created_by=teacher_id, component_type=component_type,
        weight=weight, aggregate=aggregate, name=name))
    db.session.commit()


def test_gradebook_weighted_total(gb_env):
    course_id = gb_env['make']()
    t = gb_env['teacher'].id
    # 作业 40%（mean）+ 考试 60%
    _add_scheme(course_id, t, 'homework', 40, 'mean', '平时作业')
    _add_scheme(course_id, t, 'exam', 60, 'mean', '期末考试')
    groups = build_course_gradebook(course_id)
    assert len(groups) == 1
    g = groups[0]
    assert g['homework_count'] == 2 and g['exam_count'] == 1
    rows = {r['student_id']: r for r in g['rows']}
    # s_full：作业 mean=(0.8+0.6)/2=0.7→70；考试 0.9→90；总评=(0.7*40+0.9*60)/100=0.82→82
    assert rows[gb_env['s_full'].id]['total'] == pytest.approx(82.0, rel=1e-6)
    # s_part：仅 hw1 0.6（mean 只看已完成）→ 60；无考试数据 → 考试组件 None 被排除，总评=60
    assert rows[gb_env['s_part'].id]['total'] == pytest.approx(60.0, rel=1e-6)


def test_gradebook_all_vs_mean_and_zero_weight(gb_env):
    course_id = gb_env['make']()
    t = gb_env['teacher'].id
    # all 口径：s_part 只交 1/2 作业 → 60/2=30；考试组件权重 0 应被排除
    _add_scheme(course_id, t, 'homework', 100, 'all', '全部作业')
    _add_scheme(course_id, t, 'exam', 0, 'mean', '零权重考试')
    g = build_course_gradebook(course_id)[0]
    rows = {r['student_id']: r for r in g['rows']}
    # s_full：all 作业=(0.8+0.6)/2=0.7→70；考试权重 0 不计入
    assert rows[gb_env['s_full'].id]['total'] == pytest.approx(70.0, rel=1e-6)
    # s_part：all 作业=0.6/2=0.3→30
    assert rows[gb_env['s_part'].id]['total'] == pytest.approx(30.0, rel=1e-6)
    # 考试组件虽 rate 存在但 weight=0 → 排除；s_full 的考试组件 rate 仍回显 90
    exam_comp = next(cmp for cmp in rows[gb_env['s_full'].id]['components']
                     if cmp['component_type'] == 'exam')
    assert exam_comp['rate'] == pytest.approx(90.0, rel=1e-6) and exam_comp['weight'] == 0


def test_gradebook_readonly_orthogonal(gb_env):
    course_id = gb_env['make']()
    _add_scheme(course_id, gb_env['teacher'].id, 'homework', 50, 'mean')
    before = {s.id: (s.total_score, s.status) for s in
              HomeworkSubmission.query.filter_by(status=SubmissionStatusEnum.GRADED).all()}
    build_course_gradebook(course_id)
    for s in HomeworkSubmission.query.filter_by(status=SubmissionStatusEnum.GRADED).all():
        assert (s.total_score, s.status) == before[s.id]


def test_scheme_cascades_with_course(gb_env):
    course_id = gb_env['make']()
    _add_scheme(course_id, gb_env['teacher'].id, 'homework', 40, 'mean')
    sid = CourseGradeScheme.query.filter_by(course_id=course_id).first().id
    course = db.session.get(Course, course_id)
    db.session.delete(course)
    db.session.commit()
    assert db.session.get(CourseGradeScheme, sid) is None
