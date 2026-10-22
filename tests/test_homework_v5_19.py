# -*- coding: utf-8 -*-
"""v5.19 优秀作业展示墙：模型/序列化层回归门（内存库）。

锁定语义（纯新增展示维度，与批改状态正交、不改判分/账本）：
1. ShowcaseStatusEnum.ALL 固定三态（none/nominated/featured）；
2. HomeworkSubmission.showcase_status 默认 'none'、showcase_anon 默认 False；
3. to_dict 回显 showcase_status/showcase_anon（师生均含，不属敏感信息）；
4. 精选状态与批改状态互不干扰：置 featured 不改 total_score/status。
端点侧（提名/同意/可见性/匿名/撤回全链）由 test_http_e2e 覆盖。
"""
import pytest

from database import db
from homework.models import (
    Homework, HomeworkSubmission, SubmissionStatusEnum, ShowcaseStatusEnum,
    HomeworkStatusEnum, HomeworkTypeEnum,
)


@pytest.fixture()
def sc_env(app, user_factory):
    teacher = user_factory('v519_teacher', role='teacher')
    student = user_factory('v519_student')

    def make_sub(status=SubmissionStatusEnum.GRADED, total=88.0):
        hw = Homework(title='展示墙作业', hw_type=HomeworkTypeEnum.OPEN,
                      teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED)
        db.session.add(hw)
        db.session.flush()
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=status, content='佳作', total_score=total, max_score=100.0)
        db.session.add(sub)
        db.session.commit()
        return sub

    return {'make_sub': make_sub, 'teacher': teacher, 'student': student}


def test_showcase_status_enum():
    assert set(ShowcaseStatusEnum.ALL) == {'none', 'nominated', 'featured'}


def test_showcase_defaults(sc_env):
    sub = sc_env['make_sub']()
    assert sub.showcase_status == ShowcaseStatusEnum.NONE
    assert bool(sub.showcase_anon) is False
    assert sub.showcase_at is None


def test_to_dict_exposes_showcase(sc_env):
    sub = sc_env['make_sub']()
    sub.showcase_status = ShowcaseStatusEnum.FEATURED
    sub.showcase_anon = True
    db.session.commit()
    for_teacher = sub.to_dict(for_teacher=True)
    for_student = sub.to_dict()
    assert for_teacher['showcase_status'] == 'featured'
    assert for_teacher['showcase_anon'] is True
    assert for_student['showcase_status'] == 'featured'
    assert for_student['showcase_anon'] is True


def test_showcase_does_not_touch_grading(sc_env):
    sub = sc_env['make_sub'](status=SubmissionStatusEnum.GRADED, total=88.0)
    sub.showcase_status = ShowcaseStatusEnum.FEATURED
    db.session.commit()
    assert sub.status == SubmissionStatusEnum.GRADED
    assert sub.to_dict(for_teacher=True)['total_score'] == 88.0
