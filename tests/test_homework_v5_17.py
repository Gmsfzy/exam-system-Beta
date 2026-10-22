# -*- coding: utf-8 -*-
"""v5.17 订正重做闭环：状态机/开关/账务幂等语义回归门（内存库）。

锁定语义（批改后退回订正，账务仅一次）：
1. SubmissionStatusEnum 含 returned，ALL 固定四态；
2. Homework.allow_revision 默认 False，to_dict 回显（师生均含）；
3. HomeworkSubmission.revision_round 默认 0，to_dict 回显；
4. returned 状态下学生侧可见上次分数与退回意见（to_dict 非教师亦下发 total_score/comment）；
5. 账务幂等键不含订正轮次：award_homework_grade_bonus 以 homework-grade:{hw}:{uid} 为键，
   同一提交重批不二次发分（第二次返回 0）。
端点侧（退回鉴权/未开启拒绝/重交递增/聚合）由 test_http_e2e 覆盖。
"""
import pytest

from database import db
from homework.models import (
    Homework, HomeworkSubmission, HomeworkStatusEnum, HomeworkTypeEnum,
    SubmissionStatusEnum,
)


@pytest.fixture()
def rv_env(app, user_factory):
    teacher = user_factory('v517_teacher', role='teacher')
    student = user_factory('v517_student')

    def make_homework(allow_revision=False, status=HomeworkStatusEnum.PUBLISHED):
        hw = Homework(title='订正作业', hw_type=HomeworkTypeEnum.OPEN,
                      teacher_id=teacher.id, status=status,
                      allow_revision=allow_revision)
        db.session.add(hw)
        db.session.commit()
        return hw

    def make_sub(hw, status=SubmissionStatusEnum.GRADED, total=80.0, round_=0):
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=status, total_score=total, max_score=100.0,
                                 comment='初评', revision_round=round_)
        db.session.add(sub)
        db.session.commit()
        return sub

    return {'make_homework': make_homework, 'make_sub': make_sub,
            'teacher': teacher, 'student': student}


def test_returned_in_status_enum():
    assert SubmissionStatusEnum.RETURNED == 'returned'
    assert set(SubmissionStatusEnum.ALL) == {'draft', 'submitted', 'graded', 'returned'}


def test_allow_revision_default_off(rv_env):
    hw = rv_env['make_homework']()
    assert bool(hw.allow_revision) is False
    assert hw.to_dict()['allow_revision'] is False
    assert hw.to_dict(for_teacher=True)['allow_revision'] is False


def test_allow_revision_on_echo(rv_env):
    hw = rv_env['make_homework'](allow_revision=True)
    assert hw.to_dict()['allow_revision'] is True


def test_revision_round_default_and_echo(rv_env):
    hw = rv_env['make_homework'](allow_revision=True)
    sub = rv_env['make_sub'](hw, round_=2)
    assert sub.revision_round == 2
    assert sub.to_dict()['revision_round'] == 2


def test_returned_exposes_score_and_comment_to_student(rv_env):
    hw = rv_env['make_homework'](allow_revision=True)
    sub = rv_env['make_sub'](hw, status=SubmissionStatusEnum.RETURNED, total=64.0)
    sub.comment = '请补充论证'
    db.session.commit()
    d = sub.to_dict(for_teacher=False)   # 学生视角
    assert d['status'] == 'returned'
    assert d['total_score'] == 64.0      # 退回后仍可见上次分
    assert d['comment'] == '请补充论证'  # 退回意见可见


def test_grade_bonus_idempotency_key_has_no_round(rv_env, monkeypatch):
    """质量积分幂等键固定为 homework-grade:{hw}:{uid}，不含订正轮次（重批不二次发分的根因）。"""
    from homework import services
    captured = {}

    def fake_award(user_id, delta, hw, idempotency_key, memo):
        captured.setdefault('keys', []).append(idempotency_key)
        return 0

    monkeypatch.setattr(services, '_award_homework_points', fake_award)
    monkeypatch.setattr(services, 'learning_recipients', lambda hw, sub: [rv_env['student'].id])
    hw = rv_env['make_homework'](allow_revision=True)
    sub = rv_env['make_sub'](hw, total=80.0)
    services.award_homework_grade_bonus(hw, sub)
    sub.revision_round = 1
    db.session.commit()
    services.award_homework_grade_bonus(hw, sub)   # 订正后重批
    assert captured['keys'][0] == captured['keys'][1] == f'homework-grade:{hw.id}:{rv_env["student"].id}'
