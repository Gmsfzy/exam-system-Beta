# -*- coding: utf-8 -*-
"""成绩策略幂等回归门（api.exam_engine.apply_exam_result，v4.3 引入后首补）

锁定语义：
- 首次落分 created=True 建 Result 行
- best：更低/相等不覆盖（changed=False），更高才覆盖且 session_id 跟随
- last：总是覆盖为最近一次
- strategy 缺省 → 按 last
- 重复应用同分数不产生第二行（一学生一行）
"""
import pytest

from database import db
from database.models import Exam, ExamSession, Result, User
from utils.timeutil import utcnow


@pytest.fixture()
def seed(app):
    """返回 (exam_factory, student, mk_session)：可按 score_strategy 建考试与作答会话"""
    from database.models import RoleEnum

    student = User(username='res_stu', role=RoleEnum.STUDENT)
    student.set_password('x')
    teacher = User(username='res_tea', role=RoleEnum.TEACHER)
    teacher.set_password('x')
    db.session.add_all([student, teacher])
    db.session.commit()

    def mk_session():
        sess = ExamSession(exam_id=_exam.id, student_id=student.id,
                           start_time=utcnow(), end_time=utcnow(),
                           status='submitted')
        db.session.add(sess)
        db.session.commit()
        return sess

    _exam = None

    def exam_factory(strategy):
        nonlocal _exam
        _exam = Exam(title='策略考', start_time=utcnow(), end_time=utcnow(),
                     duration=60, creator_id=teacher.id, status='published',
                     score_strategy=strategy)
        db.session.add(_exam)
        db.session.commit()
        return _exam

    return exam_factory, mk_session


class TestApplyExamResult:
    def test_first_apply_creates(self, seed):
        from api.exam_engine import apply_exam_result
        exam_factory, mk_session = seed
        exam = exam_factory('best')
        sess = mk_session()
        result, created, changed = apply_exam_result(sess, 80.0, 100.0)
        db.session.commit()
        assert created is True and changed is True
        assert result.score == 80.0 and result.session_id == sess.id

    def test_best_lower_not_overwrite(self, seed):
        from api.exam_engine import apply_exam_result
        exam_factory, mk_session = seed
        exam = exam_factory('best')
        s1 = mk_session()
        apply_exam_result(s1, 80.0, 100.0)
        db.session.commit()
        s2 = mk_session()
        result, created, changed = apply_exam_result(s2, 60.0, 100.0)
        db.session.commit()
        assert created is False and changed is False
        assert result.score == 80.0            # 历史最高保持
        assert result.session_id == s1.id      # 有效会话不漂移

    def test_best_higher_overwrites(self, seed):
        from api.exam_engine import apply_exam_result
        exam_factory, mk_session = seed
        exam = exam_factory('best')
        s1 = mk_session()
        apply_exam_result(s1, 60.0, 100.0)
        db.session.commit()
        s2 = mk_session()
        result, created, changed = apply_exam_result(s2, 90.0, 100.0)
        db.session.commit()
        assert changed is True and result.score == 90.0
        assert result.session_id == s2.id

    def test_last_always_overwrites(self, seed):
        from api.exam_engine import apply_exam_result
        exam_factory, mk_session = seed
        exam = exam_factory('last')
        s1 = mk_session()
        apply_exam_result(s1, 90.0, 100.0)
        db.session.commit()
        s2 = mk_session()
        result, created, changed = apply_exam_result(s2, 30.0, 100.0)
        db.session.commit()
        assert changed is True
        assert result.score == 30.0            # 最近一次覆盖最高分
        assert result.session_id == s2.id

    def test_default_strategy_is_last(self, seed):
        """strategy 为 None/空 → 按 last 语义"""
        from api.exam_engine import apply_exam_result
        exam_factory, mk_session = seed
        exam = exam_factory(None)
        s1 = mk_session()
        apply_exam_result(s1, 90.0, 100.0)
        db.session.commit()
        s2 = mk_session()
        result, _, changed = apply_exam_result(s2, 10.0, 100.0)
        db.session.commit()
        assert changed is True and result.score == 10.0

    def test_one_row_per_student(self, seed):
        """多轮次反复应用始终一行 Result（幂等）"""
        from api.exam_engine import apply_exam_result
        exam_factory, mk_session = seed
        exam = exam_factory('best')
        for score in (50.0, 70.0, 65.0, 88.0):
            sess = mk_session()
            apply_exam_result(sess, score, 100.0)
            db.session.commit()
        assert Result.query.filter_by(exam_id=exam.id).count() == 1
        assert Result.query.filter_by(exam_id=exam.id).first().score == 88.0
