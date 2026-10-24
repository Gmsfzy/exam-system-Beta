# -*- coding: utf-8 -*-
"""v5.20 批改批注：模型/序列化层回归门（内存库）。

锁定语义（纯叠加层，与批改状态/总分/账本正交）：
1. AnnotationTypeEnum.ALL 固定 7 类（pen/line/arrow/rect/ellipse/highlight/text）；
2. HomeworkAnnotation 一份提交一条，to_dict 回显 shapes，submission.annotation 反向可达；
3. 批注不改 submission.total_score/status（正交红线）；
4. 批注随提交级联删除（relationship cascade='all, delete-orphan'）。
端点侧（教师存/学生只读/鉴权/坐标归一化/脏数据过滤）由 test_http_e2e 覆盖。
"""
import pytest

from database import db
from homework.models import (
    Homework, HomeworkSubmission, SubmissionStatusEnum, AnnotationTypeEnum,
    HomeworkAnnotation, HomeworkStatusEnum, HomeworkTypeEnum,
)


@pytest.fixture()
def an_env(app, user_factory):
    teacher = user_factory('v520_teacher', role='teacher')
    student = user_factory('v520_student')

    def make_sub():
        hw = Homework(title='批注作业', hw_type=HomeworkTypeEnum.OPEN,
                      teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED)
        db.session.add(hw)
        db.session.flush()
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=SubmissionStatusEnum.GRADED, content='正文',
                                 total_score=88.0, max_score=100.0)
        db.session.add(sub)
        db.session.commit()
        return sub

    return {'make_sub': make_sub, 'teacher': teacher, 'student': student}


def test_annotation_type_enum():
    assert set(AnnotationTypeEnum.ALL) == {
        'pen', 'line', 'arrow', 'rect', 'ellipse', 'highlight', 'text'}


def test_annotation_upsert_and_to_dict(an_env):
    sub = an_env['make_sub']()
    ann = HomeworkAnnotation(
        submission_id=sub.id, homework_id=sub.homework_id, author_id=an_env['teacher'].id,
        shapes_json=[{'type': 'pen', 'page': 0, 'points': [[0.1, 0.2]], 'color': '#f00', 'width': 3}])
    db.session.add(ann)
    db.session.commit()
    d = ann.to_dict()
    assert d['submission_id'] == sub.id and len(d['shapes']) == 1
    assert sub.annotation.id == ann.id   # 反向 relationship 可达


def test_annotation_orthogonal_to_grading(an_env):
    sub = an_env['make_sub']()
    db.session.add(HomeworkAnnotation(
        submission_id=sub.id, homework_id=sub.homework_id, author_id=an_env['teacher'].id,
        shapes_json=[{'type': 'text', 'x': 0.5, 'y': 0.5, 'text': '好'}]))
    db.session.commit()
    assert sub.status == SubmissionStatusEnum.GRADED
    assert sub.to_dict(for_teacher=True)['total_score'] == 88.0


def test_annotation_cascades_with_submission(an_env):
    sub = an_env['make_sub']()
    db.session.add(HomeworkAnnotation(
        submission_id=sub.id, homework_id=sub.homework_id,
        author_id=an_env['teacher'].id, shapes_json=[]))
    db.session.commit()
    aid = HomeworkAnnotation.query.filter_by(submission_id=sub.id).first().id
    db.session.delete(sub)
    db.session.commit()
    assert db.session.get(HomeworkAnnotation, aid) is None
