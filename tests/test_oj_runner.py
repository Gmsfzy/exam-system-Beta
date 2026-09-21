# -*- coding: utf-8 -*-
"""OJ 评测回归门（v4.7）

- oj.runner：真子进程执行（AC/TLE/RE/静态拒绝）
- oj.services：判定聚合与输出规范化比对
- ai_service.ai_grade_exam：编程题有用例→自动判分不送人工；无用例→回落主观链路
"""
from database import db
from database.models import (
    Major, Course, Exam, ExamQuestion, ExamSession, Answer, Question, User,
)
from oj import services as oj_services
from oj.runner import check_code, run_python


# ── runner ──────────────────────────────────────────────────────────

class TestRunner:
    def test_echo_ac(self):
        r = run_python('print(int(input()) + 1)', stdin='41\n')
        assert r['error'] is None and not r['timed_out']
        assert r['exit_code'] == 0
        assert r['stdout'].strip() == '42'

    def test_timeout_killed(self):
        r = run_python('while True:\n    pass', timeout=1.0)
        assert r['timed_out'] is True

    def test_runtime_error(self):
        r = run_python('print(1 / 0)')
        assert r['exit_code'] not in (0, None)
        assert 'ZeroDivisionError' in r['stderr']

    def test_static_reject_dangerous(self):
        for bad in ['import socket', 'import subprocess', 'os.system("dir")',
                    '__import__("os")', 'open("x.txt")', 'import ctypes']:
            assert check_code(bad) is not None, f'应拒绝: {bad}'

    def test_clean_code_passes_static(self):
        assert check_code('n = int(input())\nprint(n * 2)') is None

    def test_empty_code_rejected(self):
        assert check_code('   ') is not None


# ── services.grade ──────────────────────────────────────────────────

class TestGrade:
    CODE = 'print(int(input()) + 1)'

    def test_all_ac(self):
        r = oj_services.grade(self.CODE, 'python',
                              [{'input': '1', 'expected': '2'},
                               {'input': '9', 'expected': '10'}])
        assert r['supported'] and r['verdict'] == 'AC'
        assert r['passed'] == 2 and r['total'] == 2

    def test_wa_ratio(self):
        r = oj_services.grade(self.CODE, 'python',
                              [{'input': '1', 'expected': '2'},
                               {'input': '1', 'expected': '999'}])
        assert r['verdict'] == 'WA'
        assert r['passed'] == 1 and r['total'] == 2

    def test_trailing_whitespace_ignored(self):
        """行尾空白与末尾空行不参与比对（主流 OJ 简化语义）"""
        r = oj_services.grade('print("hi")', 'python',
                              [{'input': '', 'expected': 'hi  \n\n'}])
        assert r['verdict'] == 'AC'

    def test_re_verdict(self):
        r = oj_services.grade('raise ValueError("x")', 'python',
                              [{'input': '', 'expected': 'x'}])
        assert r['verdict'] == 'RE' and r['passed'] == 0

    def test_tle_verdict(self):
        r = oj_services.grade('while True:\n    pass', 'python',
                              [{'input': '', 'expected': '1'}],
                              per_case_timeout=1.0)
        assert r['verdict'] == 'TLE'

    def test_se_security_verdict(self):
        r = oj_services.grade('import socket', 'python',
                              [{'input': '', 'expected': '1'}])
        assert r['verdict'] == 'SE'

    def test_unsupported_language_or_no_cases(self):
        assert oj_services.grade('x', 'java', [{'input': '', 'expected': ''}])['supported'] is False
        assert oj_services.grade('x', 'python', [])['supported'] is False
        assert oj_services.grade('x', 'python', None)['supported'] is False


# ── ai_grade_exam 集成 ───────────────────────────────────────────────

def _seed_exam_with_programming(score_full=10.0, with_cases=True):
    """构造 考试+编程题+学生作答 的最小闭环数据，返回 (session_id, answer_hint)"""
    major = Major(name='oj软件')
    course = Course(name='oj课', major=major)
    tea = User(username='oj_tea', role='teacher')
    tea.set_password('x')
    stu = User(username='oj_stu', role='student')
    stu.set_password('x')
    db.session.add_all([major, course, tea, stu])
    db.session.commit()
    from utils.timeutil import utcnow
    q = Question(content='读入整数输出+1', answer='print(int(input())+1)',
                 major_id=major.id, course_id=course.id,
                 type='programming', difficulty='easy', creator_id=tea.id)
    if with_cases:
        q.test_cases = [{'input': '41', 'expected': '42'},
                        {'input': '0', 'expected': '1'}]
    db.session.add(q)
    exam = Exam(title='oj考', start_time=utcnow(), end_time=utcnow(),
                duration=60, creator_id=tea.id, status='published')
    db.session.add(exam)
    db.session.commit()
    db.session.add(ExamQuestion(exam_id=exam.id, question_id=q.id, score=score_full, order=1))
    sess = ExamSession(exam_id=exam.id, student_id=stu.id,
                       start_time=utcnow(), status='submitted')
    db.session.add(sess)
    db.session.commit()
    db.session.add(Answer(session_id=sess.id, question_id=q.id,
                          student_answer='print(int(input()) + 1)'))
    db.session.commit()
    return exam, sess, q


class TestGradeExamIntegration:
    def test_programming_with_cases_auto_graded(self, app):
        from ai_service.services import ai_grade_exam
        exam, sess, q = _seed_exam_with_programming(score_full=10.0)
        earned, total = ai_grade_exam(db.session, sess.id)
        ans = Answer.query.filter_by(session_id=sess.id, question_id=q.id).first()
        assert ans.needs_manual_grade is False       # 不再送 AI/人工
        assert ans.oj_verdict == 'AC'
        assert ans.is_correct is True
        assert ans.score == 10.0
        assert earned == 10.0 and total == 10.0

    def test_programming_partial_pass(self, app):
        """只对一半用例通过的代码：按 AC 通过率折算得分"""
        from ai_service.services import ai_grade_exam
        exam, sess, q = _seed_exam_with_programming(score_full=8.0)
        # 换成只处理第一用例的"作弊式"代码：固定输出 42/期望 1 不符
        ans = Answer.query.filter_by(session_id=sess.id, question_id=q.id).first()
        ans.student_answer = 'import sys\nprint(42 if sys.argv else 42)'
        # stdin=0 期望 1 → WA；固定输出只对第一用例 AC → 通过率 1/2
        db.session.commit()
        earned, total = ai_grade_exam(db.session, sess.id)
        db.session.refresh(ans)
        assert ans.needs_manual_grade is False
        assert ans.oj_verdict == 'WA'
        assert ans.score == 4.0                      # 8.0 × 1/2
        assert earned == 4.0

    def test_programming_without_cases_falls_back(self, app, monkeypatch):
        """无用例编程题回落主观链路：needs_manual_grade=True，AI 失败给 0 等人工"""
        import ai_service.services as svc

        def _boom(*a, **k):
            raise RuntimeError('AI 不可用（测试桩）')
        monkeypatch.setattr(svc.ai_client, 'grade_answer', _boom)
        exam, sess, q = _seed_exam_with_programming(score_full=10.0, with_cases=False)
        earned, total = svc.ai_grade_exam(db.session, sess.id)
        ans = Answer.query.filter_by(session_id=sess.id, question_id=q.id).first()
        assert ans.needs_manual_grade is True
        assert ans.oj_verdict is None
        assert ans.score == 0
