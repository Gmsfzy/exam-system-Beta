# -*- coding: utf-8 -*-
"""v5.16 作答防作弊监测：模型/开关层回归门（内存库）。

锁定语义（只记不拦，不改判分/账本）：
1. Homework.enable_monitor 默认 False，to_dict 回显 enable_monitor（师生均含）；
2. ProctorEventTypeEnum.ALL 固定四类（tab_switch/blur/paste/copy）；
3. HomeworkProctorEvent.to_dict 逐字段（type/at/homework_id/student_id/submission_id）；
4. 事件与提交/作业无耦合判分：建事件不影响 submission.total_score。
端点侧（上报鉴权/名单/未开启空操作/教师聚合）由 test_http_e2e 覆盖。
"""
import pytest

from database import db
from homework.models import (
    Homework, HomeworkSubmission, HomeworkProctorEvent, ProctorEventTypeEnum,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)


@pytest.fixture()
def pc_env(app, user_factory):
    teacher = user_factory('v516_teacher', role='teacher')
    student = user_factory('v516_student')

    def make_homework(enable_monitor=False, status=HomeworkStatusEnum.PUBLISHED):
        hw = Homework(title='监测作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                      teacher_id=teacher.id, status=status,
                      enable_monitor=enable_monitor)
        db.session.add(hw)
        db.session.commit()
        return hw

    def make_sub(hw, status=SubmissionStatusEnum.GRADED, total=80.0):
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=status, total_score=total, max_score=100.0)
        db.session.add(sub)
        db.session.commit()
        return sub

    return {'make_homework': make_homework, 'make_sub': make_sub,
            'teacher': teacher, 'student': student}


def test_enable_monitor_default_off(pc_env):
    hw = pc_env['make_homework']()
    assert bool(hw.enable_monitor) is False
    assert hw.to_dict()['enable_monitor'] is False
    assert hw.to_dict(for_teacher=True)['enable_monitor'] is False


def test_enable_monitor_on_echo(pc_env):
    hw = pc_env['make_homework'](enable_monitor=True)
    assert bool(hw.enable_monitor) is True
    assert hw.to_dict()['enable_monitor'] is True


def test_proctor_event_type_enum():
    assert set(ProctorEventTypeEnum.ALL) == {'tab_switch', 'blur', 'paste', 'copy'}


def test_proctor_event_to_dict(pc_env):
    hw = pc_env['make_homework'](enable_monitor=True)
    sub = pc_env['make_sub'](hw)
    ev = HomeworkProctorEvent(homework_id=hw.id, submission_id=sub.id,
                              student_id=pc_env['student'].id, type='tab_switch')
    db.session.add(ev)
    db.session.commit()
    d = ev.to_dict()
    assert d['homework_id'] == hw.id and d['submission_id'] == sub.id
    assert d['student_id'] == pc_env['student'].id and d['type'] == 'tab_switch'
    assert d['at']  # iso_local 非空


def test_event_does_not_touch_score(pc_env):
    hw = pc_env['make_homework'](enable_monitor=True)
    sub = pc_env['make_sub'](hw, total=80.0)
    for t in ProctorEventTypeEnum.ALL:
        db.session.add(HomeworkProctorEvent(homework_id=hw.id, submission_id=sub.id,
                                            student_id=pc_env['student'].id, type=t))
    db.session.commit()
    assert sub.to_dict(for_teacher=True)['total_score'] == 80.0
    assert HomeworkProctorEvent.query.filter_by(homework_id=hw.id).count() == 4
