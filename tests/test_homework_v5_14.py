# -*- coding: utf-8 -*-
"""v5.14 多种评分制：grade_mode 显示层派生回归门（函数层，内存库）。

锁定语义（全部为展示层派生，不改 total_score/积分/错题口径）：
1. numeric：grade_display 原样等于数值总分，师生一致；
2. level：按得分率映射内置四档（优≥0.9 良≥0.8 中≥0.6 差<0.6），grade_scale_json 可覆盖；
3. comment：仅显示评语，教师侧仍见数值分、学生侧 total_score 置 None；
4. 任意模式下 total_score 数值口径不变（level/comment 不篡改分数）；
5. Homework.to_dict 回显 grade_mode（师生均含）。
HTTP 端点侧由 test_http_e2e 负责。
"""
import pytest

from database import db
from homework.models import (
    Homework, HomeworkSubmission, HomeworkStatusEnum, HomeworkTypeEnum,
    SubmissionStatusEnum,
)


@pytest.fixture()
def gm_env(app, user_factory):
    teacher = user_factory('v514_teacher', role='teacher')
    student = user_factory('v514_student')

    def make(mode='numeric', scale=None, total=8.0, max_score=10.0,
             comment='写得不错', status=SubmissionStatusEnum.GRADED):
        hw = Homework(title='评分制作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                      teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED,
                      grade_mode=mode)
        hw.grade_scale_json = scale
        db.session.add(hw)
        db.session.flush()
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=status, total_score=total, max_score=max_score,
                                 comment=comment)
        db.session.add(sub)
        db.session.commit()
        return hw, sub

    return {'make': make, 'teacher': teacher, 'student': student}


def test_grade_mode_numeric_passthrough(gm_env):
    hw, sub = gm_env['make']('numeric', total=8.0, max_score=10.0)
    t = sub.to_dict(for_teacher=True)
    s = sub.to_dict(for_teacher=False)
    assert t['grade_mode'] == 'numeric'
    assert t['grade_display'] == 8.0 and s['grade_display'] == 8.0
    assert t['total_score'] == 8.0 and s['total_score'] == 8.0   # 数值口径不变


def test_grade_mode_level_default(gm_env):
    cases = {0.95: '优', 0.9: '优', 0.85: '良', 0.8: '良', 0.65: '中', 0.5: '差'}
    for ratio, label in cases.items():
        _hw, sub = gm_env['make']('level', total=ratio * 10, max_score=10.0)
        d = sub.to_dict(for_teacher=True)
        assert d['grade_display'] == label, (ratio, label, d['grade_display'])
        assert d['total_score'] == round(ratio * 10, 10) or d['total_score'] == ratio * 10  # 分数未被篡改


def test_grade_mode_level_custom_scale(gm_env):
    scale = [{'label': 'A', 'min': 0.85}, {'label': 'B', 'min': 0.7},
             {'label': 'C', 'min': 0.0}]
    _hw, sub = gm_env['make']('level', scale=scale, total=7.5, max_score=10.0)
    assert sub.to_dict()['grade_display'] == 'B'          # 0.75 → B（非内置「中」）
    _hw2, sub2 = gm_env['make']('level', scale=scale, total=9.0, max_score=10.0)
    assert sub2.to_dict()['grade_display'] == 'A'          # 0.9 → A


def test_grade_mode_comment_hides_number_for_student(gm_env):
    hw, sub = gm_env['make']('comment', total=8.0, max_score=10.0, comment='继续努力')
    t = sub.to_dict(for_teacher=True)
    s = sub.to_dict(for_teacher=False)
    assert t['grade_display'] == '继续努力' and t['total_score'] == 8.0   # 教师仍见数值
    assert s['grade_display'] == '继续努力' and s['total_score'] is None   # 学生仅评语，隐数值分


def test_grade_mode_dict_echo(gm_env):
    hw, _sub = gm_env['make']('level')
    assert hw.to_dict()['grade_mode'] == 'level'           # 学生侧也回显
    assert hw.to_dict(for_teacher=True)['grade_mode'] == 'level'
    _hw, sub = gm_env['make']('level', total=5.0, max_score=10.0,
                              status=SubmissionStatusEnum.SUBMITTED)
    # 未批改：level 无 display，但 total_score 仍按可见性口径为 None（学生）
    assert sub.to_dict()['grade_display'] is None
