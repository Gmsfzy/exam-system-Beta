# -*- coding: utf-8 -*-
"""OJ 异步评测队列回归门（v7.0 阶段 3）。

锁定语义：
- 开关开启 + 工具链就绪：交卷判分把编程题置 pending（暂定 0 分）立即返回；
- 队列 process_once：抢占→评测→回填 verdict/score→重算会话与 Result→通知学生；
- 幂等：按 answer_id 原子抢占，重复排空不双评；崩溃遗留 grading 行复位重放；
- 失败可重放：评测异常回炉 pending 计 attempts，超限置 failed 终态；
- supported=False 回落人工（needs_manual_grade=True、状态清空）；
- 开关关闭：与既有同步链路逐位一致（oj_status 恒为 NULL）；
- HTTP E2E：start→save_answer→submit（oj_pending）→轮询 oj_status→排空→done。
"""
import pytest

from datetime import timedelta

from database import db
from database.models import (
    Major, Course, Exam, ExamQuestion, ExamStudent, ExamSession, Answer, Question, User, Result,
)
from utils.timeutil import utcnow

import oj.services as _svc
from oj import queue


AC_CODE = 'print(int(input()) + 1)'


def _seed(score_full=10.0, code=AC_CODE, cases=True):
    """考试+编程题+已交卷会话的最小闭环（同 test_oj_runner 口径）。"""
    major = Major(name='aq软件')
    course = Course(name='aq课', major=major)
    tea = User(username='aq_tea', role='teacher')
    tea.set_password('x')
    stu = User(username='aq_stu', role='student')
    stu.set_password('x')
    db.session.add_all([major, course, tea, stu])
    db.session.commit()
    q = Question(content='读入整数输出+1', answer=AC_CODE,
                 major_id=major.id, course_id=course.id,
                 type='programming', difficulty='easy', creator_id=tea.id)
    if cases:
        q.test_cases = [{'input': '41', 'expected': '42'},
                        {'input': '0', 'expected': '1'}]
    db.session.add(q)
    exam = Exam(title='aq考', start_time=utcnow(), end_time=utcnow(),
                duration=60, creator_id=tea.id, status='published')
    db.session.add(exam)
    db.session.commit()
    db.session.add(ExamQuestion(exam_id=exam.id, question_id=q.id, score=score_full, order=1))
    sess = ExamSession(exam_id=exam.id, student_id=stu.id,
                       start_time=utcnow(), end_time=utcnow(), status='submitted')
    db.session.add(sess)
    db.session.commit()
    db.session.add(Answer(session_id=sess.id, question_id=q.id, student_answer=code))
    db.session.commit()
    return exam, sess, q, stu, tea


def _answer_of(sess, q):
    return Answer.query.filter_by(session_id=sess.id, question_id=q.id).first()


@pytest.fixture()
def async_on(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, 'OJ_ASYNC_GRADING', True)


class TestAsyncEnqueue:
    def test_submit_marks_pending(self, app, async_on):
        from ai_service.services import ai_grade_exam
        exam, sess, q, stu, tea = _seed()
        earned, total = ai_grade_exam(db.session, sess.id)
        ans = _answer_of(sess, q)
        assert ans.oj_status == 'pending'
        assert ans.oj_verdict is None and ans.score == 0
        assert ans.needs_manual_grade is False
        assert earned == 0 and total == 10.0        # 暂定 0 分，total 含该题满分

    def test_disabled_keeps_sync_path(self, app):
        from ai_service.services import ai_grade_exam
        exam, sess, q, stu, tea = _seed()
        earned, total = ai_grade_exam(db.session, sess.id)
        ans = _answer_of(sess, q)
        assert ans.oj_status is None and ans.oj_verdict == 'AC'
        assert earned == 10.0

    def test_empty_code_still_sync_ce(self, app, async_on):
        from ai_service.services import ai_grade_exam
        exam, sess, q, stu, tea = _seed(code='   ')
        ai_grade_exam(db.session, sess.id)
        ans = _answer_of(sess, q)
        assert ans.oj_status is None and ans.oj_verdict == 'CE'


class TestQueueProcessing:
    def _submitted(self, score_full=10.0, code=AC_CODE):
        """走完整交卷口径：判分 + 落 Result（模拟 _finalize_submission 前半段）。"""
        from ai_service.services import ai_grade_exam
        from api.exam_engine import apply_exam_result
        exam, sess, q, stu, tea = _seed(score_full=score_full, code=code)
        earned, total = ai_grade_exam(db.session, sess.id)
        sess.score = earned
        apply_exam_result(sess, earned, total)
        db.session.commit()
        return exam, sess, q, stu

    def test_backfill_resettle_notify(self, app, async_on):
        exam, sess, q, stu = self._submitted()
        assert queue.process_once() == 1
        ans = _answer_of(sess, q)
        db.session.refresh(ans)
        assert ans.oj_status == 'done' and ans.oj_verdict == 'AC'
        assert ans.is_correct is True and ans.score == 10.0
        db.session.refresh(sess)
        assert sess.score == 10.0
        result = Result.query.filter_by(exam_id=exam.id, student_id=stu.id).first()
        assert result.score == 10.0 and result.total_score == 10.0
        # 评测完成通知（经 ORM 事件再走 Socket 推送）
        from database.models import Notification
        assert Notification.query.filter_by(
            user_id=stu.id, related_type='exam', title='编程题评测完成').count() == 1

    def test_idempotent_no_double_grade(self, app, async_on):
        exam, sess, q, stu = self._submitted()
        assert queue.process_once() == 1
        assert queue.process_once() == 0            # done 后无可排空
        ans = _answer_of(sess, q)
        assert ans.oj_attempts == 0                 # 正常回填不计 attempts（仅异常重放计）

    def test_stale_grading_recovered(self, app, async_on):
        exam, sess, q, stu = self._submitted()
        ans = _answer_of(sess, q)
        ans.oj_status = 'grading'                   # 模拟崩溃遗留
        db.session.commit()
        assert queue.process_once() == 1
        db.session.refresh(ans)
        assert ans.oj_status == 'done' and ans.oj_verdict == 'AC'

    def test_failure_replays_until_failed(self, app, async_on, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError('runner 崩了（测试桩）')
        monkeypatch.setattr(_svc, 'grade', _boom)
        exam, sess, q, stu = self._submitted()
        ans = _answer_of(sess, q)
        for i in range(1, queue.MAX_ATTEMPTS):
            queue.process_once()
            db.session.refresh(ans)
            assert ans.oj_status == 'pending' and ans.oj_attempts == i
        queue.process_once()
        db.session.refresh(ans)
        assert ans.oj_status == 'failed' and ans.oj_attempts == queue.MAX_ATTEMPTS
        assert queue.process_once() == 0            # failed 终态不再自动重试

    def test_unsupported_falls_back_manual(self, app, async_on, monkeypatch):
        monkeypatch.setattr(_svc, 'grade',
                            lambda *a, **k: {'supported': False, 'verdict': None,
                                             'passed': 0, 'total': 2, 'cases': []})
        exam, sess, q, stu = self._submitted()
        queue.process_once()
        ans = _answer_of(sess, q)
        db.session.refresh(ans)
        assert ans.oj_status is None and ans.needs_manual_grade is True

    def test_partial_pass_score_by_ratio(self, app, async_on):
        exam, sess, q, stu = self._submitted(score_full=8.0,
                                             code='print(42 if input() else 42)')
        queue.process_once()
        ans = _answer_of(sess, q)
        db.session.refresh(ans)
        assert ans.oj_verdict == 'WA' and ans.score == 4.0   # 通过率 1/2

    def test_pending_info_shape(self, app, async_on):
        from ai_service.services import ai_grade_exam
        exam, sess, q, stu, tea = _seed()
        ai_grade_exam(db.session, sess.id)
        info = queue.pending_info(sess.id)
        assert info['pending'] is True and len(info['items']) == 1
        item = info['items'][0]
        assert item['status'] == 'pending' and item['question_id'] == q.id

    def test_wake_and_has_pending(self, app, async_on):
        from ai_service.services import ai_grade_exam
        exam, sess, q, stu, tea = _seed()
        ai_grade_exam(db.session, sess.id)
        assert queue.has_pending(sess.id) is True
        queue.wake()                                # 仅置事件，不应抛错
        assert queue._wake.is_set()
        queue._wake.clear()


class TestBackgroundThread:
    def test_thread_drains_queue(self, app, async_on):
        """真异步链：后台线程被 wake 后自行排空（不手动调 process_once）。"""
        import threading
        import time as _t
        from ai_service.services import ai_grade_exam
        from api.exam_engine import apply_exam_result
        exam, sess, q, stu, tea = _seed()
        earned, total = ai_grade_exam(db.session, sess.id)
        sess.score = earned
        apply_exam_result(sess, earned, total)
        db.session.commit()

        queue.start_queue(app, interval=0.2)
        try:
            queue.wake()
            deadline = _t.time() + 15
            while _t.time() < deadline and queue.has_pending(sess.id):
                _t.sleep(0.1)
            assert not queue.has_pending(sess.id), '后台线程未在 15s 内完成评测'
            ans = _answer_of(sess, q)
            assert ans.oj_status == 'done' and ans.oj_verdict == 'AC'
        finally:
            queue.stop_queue()


# ─────────────────────── HTTP 层 E2E ───────────────────────

@pytest.fixture(scope='module')
def prod_app():
    """真实 app（跳过 bootstrap 不起线程）+ 临时库建表（conftest 已改指）。"""
    import app as prod
    prod._boot_done.set()
    prod.app.config['TESTING'] = True
    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False
    with prod.app.app_context():
        import database.models        # noqa: F401
        import competition.models     # noqa: F401
        import bounty.models          # noqa: F401
        import ledger.models          # noqa: F401
        import dsci.models            # noqa: F401
        import homework.models        # noqa: F401
        db.create_all()
        yield prod
        db.session.remove()


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def test_async_chain_http(prod_app):
    """全链：开关开→开考→存码→交卷（oj_pending=True）→轮询 pending→排空→done+成绩回填。"""
    from config import Config
    a = prod_app.app
    c = a.test_client()
    r = c.post('/api/register', json={'username': 'aq_http_tea', 'password': 'pw-123',
                                      'role': 'teacher'})
    t_token, tid = r.get_json()['token'], r.get_json()['user']['id']
    r = c.post('/api/register', json={'username': 'aq_http_stu', 'password': 'pw-123',
                                      'role': 'student'})
    s_token, sid = r.get_json()['token'], r.get_json()['user']['id']

    with a.app_context():
        from database.models import Notification
        major = Major(name='AQ-HTTP专业')
        db.session.add(major)
        db.session.flush()
        q = Question(content='读入整数输出+1', answer=AC_CODE, type='programming',
                     difficulty='easy', major_id=major.id)
        q.test_cases = [{'input': '41', 'expected': '42'}]
        db.session.add(q)
        now = utcnow()
        exam = Exam(title='AQ-HTTP考', start_time=now - timedelta(minutes=1),
                    end_time=now + timedelta(hours=3),
                    duration=60, creator_id=tid, status='published', results_published=True)
        db.session.add(exam)
        db.session.commit()
        db.session.add(ExamQuestion(exam_id=exam.id, question_id=q.id, score=5.0, order=1))
        db.session.add(ExamStudent(exam_id=exam.id, student_id=sid))
        db.session.commit()
        exam_id, qid = exam.id, q.id

    Config.OJ_ASYNC_GRADING = True
    try:
        r = c.post(f'/api/exam/{exam_id}/start', headers=_auth(s_token))
        assert r.status_code == 200, r.get_json()
        sess_id = r.get_json()['session_id']

        r = c.post(f'/api/exam/{exam_id}/save_answer', json={
            'session_id': sess_id, 'question_id': qid, 'answer': AC_CODE},
            headers=_auth(s_token))
        assert r.status_code == 200, r.get_json()

        r = c.post(f'/api/exam/{exam_id}/submit', json={'session_id': sess_id},
                   headers=_auth(s_token))
        assert r.status_code == 200, r.get_json()
        assert r.get_json().get('oj_pending') is True

        # 轮询端点：排空前 pending=True
        r = c.get(f'/api/exam/session/{sess_id}/oj_status', headers=_auth(s_token))
        assert r.status_code == 200
        body = r.get_json()['data']
        assert body['pending'] is True and body['items'][0]['status'] == 'pending'

        # 驱动队列（生产由后台线程完成，此处等价同步调用保证确定性）
        with a.app_context():
            assert queue.process_once() == 1

        r = c.get(f'/api/exam/session/{sess_id}/oj_status', headers=_auth(s_token))
        body = r.get_json()['data']
        assert body['pending'] is False
        assert body['items'][0]['status'] == 'done'
        assert body['items'][0]['verdict'] == 'AC' and body['items'][0]['score'] == 5.0

        # 成绩回填 + 通知到达
        with a.app_context():
            sess = db.session.get(ExamSession, sess_id)
            assert sess.score == 5.0
            result = Result.query.filter_by(exam_id=exam_id, student_id=sid).first()
            assert result is not None and result.score == 5.0
            assert Notification.query.filter_by(
                user_id=sid, title='编程题评测完成', related_type='exam').count() == 1
        # 越权：他人会话不可查（教师放行、其他学生 403）
        r2 = c.post('/api/register', json={'username': 'aq_http_stu2', 'password': 'pw-123',
                                           'role': 'student'})
        tok2 = r2.get_json()['token']
        assert c.get(f'/api/exam/session/{sess_id}/oj_status',
                     headers=_auth(tok2)).status_code == 403
        assert c.get(f'/api/exam/session/{sess_id}/oj_status',
                     headers=_auth(t_token)).status_code == 200
    finally:
        Config.OJ_ASYNC_GRADING = False
