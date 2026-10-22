# -*- coding: utf-8 -*-
"""v5.3 作业 AI 讲评回归门（函数层，内存库）。

锁住：
1. 班级统计快照：提交率/平均得分率/题目得分率/选项分布/薄弱题；
2. 知识点薄弱项聚合（question_knowledge_point 多对多）；
3. AI 成功路径解析 + AI 失败降级（规则讲评，统计不丢）；
4. 讲评落库幂等（同作业同 scope 覆盖不新增）；
5. 单份讲评：未批改拒绝、已批改按逐题明细生成。

HTTP 往返（发布门控/学生可见性）由 test_http_e2e 的 AI 讲评链负责。
"""
import json

import pytest

from database import db
from database.models import (
    Course, Chapter, KnowledgePoint, Major, Question, question_knowledge_point,
)
from utils.timeutil import utcnow
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkAiReview, HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.services import (
    _class_stats, build_class_review, build_submission_review, upsert_ai_review,
)


@pytest.fixture()
def ai_env(app, user_factory):
    """教师 + 两学生 + 两题（单选，答案均为 B）+ 已批改答卷助手。"""
    teacher = user_factory('ai_teacher', role='teacher')
    s1 = user_factory('ai_student_1')
    s2 = user_factory('ai_student_2')
    major = Major(name='AI讲评专业')
    db.session.add(major)
    db.session.flush()
    q1 = Question(content='1+1=?', answer='B', type='single_choice', difficulty='easy',
                  major_id=major.id, options=['A. 1', 'B. 2'])
    q2 = Question(content='2+2=?', answer='B', type='single_choice', difficulty='easy',
                  major_id=major.id, options=['A. 3', 'B. 4'])
    db.session.add_all([q1, q2])
    db.session.commit()

    def make_hw(students=(s1, s2)):
        hw = Homework(title='AI讲评作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                      teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED,
                      allow_late=True)
        db.session.add(hw)
        db.session.flush()
        for i, q in enumerate((q1, q2)):
            db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id,
                                            score=10.0, order=i))
        for st in students:
            db.session.add(HomeworkStudent(homework_id=hw.id, student_id=st.id))
        db.session.commit()
        return hw

    def submit(hw, student, answers, status=SubmissionStatusEnum.GRADED):
        """answers: {qid: text}；按客观题自动判分并直接置 graded。"""
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=status, submitted_at=utcnow())
        db.session.add(sub)
        db.session.flush()
        total = 0.0
        for hq in hw.hw_questions:
            text = answers.get(hq.question_id, '')
            q = db.session.get(Question, hq.question_id)
            correct = bool(text) and text.strip().upper() == (q.answer or '').strip().upper()
            score = hq.score if correct else 0.0
            total += score
            db.session.add(HomeworkAnswer(
                submission_id=sub.id, question_id=hq.question_id, answer=text,
                is_correct=correct, auto_score=score, needs_manual_grade=False))
        sub.max_score = hw.max_score()
        sub.total_score = round(total, 2)
        db.session.commit()
        return sub

    env = {'teacher': teacher, 's1': s1, 's2': s2, 'q1': q1, 'q2': q2,
           'major': major, 'make_hw': make_hw, 'submit': submit}
    return env


def _ai_json():
    return json.dumps({
        'summary': 'AI 班级讲评', 'common_mistakes': [
            {'question': '1+1=?', 'mistake': '概念混淆', 'advice': '课堂重讲'}],
        'weak_points': ['加法'], 'teaching_suggestions': ['安排变式练习'],
        'strengths': ['基础较好'],
        'improvements': [{'point': '进位加法', 'advice': '多练'}],
        'next_steps': ['重做错题'],
    }, ensure_ascii=False)


def test_class_stats_aggregates_scores_and_options(ai_env):
    hw = ai_env['make_hw']()
    ai_env['submit'](hw, ai_env['s1'], {ai_env['q1'].id: 'B', ai_env['q2'].id: 'A'})
    ai_env['submit'](hw, ai_env['s2'], {ai_env['q1'].id: 'A', ai_env['q2'].id: 'A'})
    stats = _class_stats(hw)

    assert stats['total_students'] == 2 and stats['submitted'] == 2
    assert stats['submitted_rate'] == 100.0 and stats['graded'] == 2
    assert stats['max_score'] == 20.0
    assert stats['avg_score'] == 5.0          # (10 + 0) / 2
    assert stats['avg_ratio'] == 0.25
    q1 = next(q for q in stats['questions'] if q['question_id'] == ai_env['q1'].id)
    q2 = next(q for q in stats['questions'] if q['question_id'] == ai_env['q2'].id)
    assert q1['avg_ratio'] == 0.5 and q1['answer_distribution'] == {'A': 1, 'B': 1}
    assert q2['avg_ratio'] == 0.0 and q2['is_weak'] is True
    assert len(stats['weak_questions']) == 2


def test_class_stats_knowledge_points(ai_env):
    course = Course(name='数学2', major_id=ai_env['major'].id)
    db.session.add(course)
    db.session.flush()
    chapter = Chapter(name='第一章', course_id=course.id)
    db.session.add(chapter)
    db.session.flush()
    kp = KnowledgePoint(chapter_id=chapter.id, name='加法')
    db.session.add(kp)
    db.session.flush()
    db.session.execute(question_knowledge_point.insert().values(
        question_id=ai_env['q1'].id, knowledge_point_id=kp.id))
    db.session.commit()

    hw = ai_env['make_hw']()
    ai_env['submit'](hw, ai_env['s1'], {ai_env['q1'].id: 'A'})
    stats = _class_stats(hw)
    assert [k['name'] for k in stats['knowledge_points']] == ['加法']
    assert stats['knowledge_points'][0]['avg_ratio'] == 0.0
    assert stats['weak_knowledge_points'][0]['name'] == '加法'


def test_build_class_review_ai_success(ai_env, monkeypatch):
    from ai_service.services import ai_client
    hw = ai_env['make_hw']()
    ai_env['submit'](hw, ai_env['s1'], {ai_env['q1'].id: 'B', ai_env['q2'].id: 'A'})
    monkeypatch.setattr(ai_client, 'generate_json',
                        lambda *a, **kw: _ai_json())
    result = build_class_review(hw)
    assert result['degraded'] is False
    assert result['content']['summary'] == 'AI 班级讲评'
    assert result['content']['common_mistakes'][0]['advice'] == '课堂重讲'


def test_build_class_review_falls_back_when_ai_fails(ai_env, monkeypatch):
    from ai_service.services import ai_client

    def boom(*a, **kw):
        raise RuntimeError('AI down')

    hw = ai_env['make_hw']()
    ai_env['submit'](hw, ai_env['s1'], {ai_env['q1'].id: 'A', ai_env['q2'].id: 'A'})
    monkeypatch.setattr(ai_client, 'generate_json', boom)
    result = build_class_review(hw)
    assert result['degraded'] is True
    assert result['stats']['submitted'] == 1
    assert '平均分' in result['content']['summary']
    assert result['content']['common_mistakes']     # 规则版讲评仍给出薄弱题
    assert result['content']['teaching_suggestions']


def test_upsert_class_review_is_idempotent(ai_env, monkeypatch):
    from ai_service.services import ai_client
    hw = ai_env['make_hw']()
    ai_env['submit'](hw, ai_env['s1'], {ai_env['q1'].id: 'B'})
    monkeypatch.setattr(ai_client, 'generate_json', lambda *a, **kw: _ai_json())
    r1 = build_class_review(hw)
    upsert_ai_review(hw, 'class', r1, ai_env['teacher'].id)
    r2 = build_class_review(hw)
    rec = upsert_ai_review(hw, 'class', r2, ai_env['teacher'].id)
    assert HomeworkAiReview.query.filter_by(homework_id=hw.id,
                                            scope_key='class').count() == 1
    assert rec.id is not None and rec.published_at is None


def test_submission_review_requires_graded(ai_env, monkeypatch):
    from ai_service.services import ai_client
    hw = ai_env['make_hw']()
    draft_sub = ai_env['submit'](hw, ai_env['s1'], {ai_env['q1'].id: 'A'},
                                 status=SubmissionStatusEnum.SUBMITTED)
    result = build_submission_review(hw, draft_sub)
    assert result['degraded'] is True       # 未批改走降级，路由层另有 400 拦截

    graded = ai_env['submit'](hw, ai_env['s2'], {ai_env['q1'].id: 'A'})
    monkeypatch.setattr(ai_client, 'generate_json', lambda *a, **kw: _ai_json())
    result = build_submission_review(hw, graded)
    assert result['degraded'] is False
    assert result['content']['summary'] == 'AI 班级讲评'   # 复用同一份 mock JSON
    assert result['stats']['questions'][0]['correct_answer'] == 'B'


def test_class_stats_empty_and_open_homework(ai_env):
    hw = ai_env['make_hw'](students=())
    stats = _class_stats(hw)
    assert stats['submitted'] == 0 and stats['submitted_rate'] == 0.0
    assert all(q['attempts'] == 0 and q['avg_ratio'] is None for q in stats['questions'])
    assert stats['weak_questions'] == []

    open_hw = Homework(title='开放式', hw_type=HomeworkTypeEnum.OPEN,
                       teacher_id=ai_env['teacher'].id,
                       status=HomeworkStatusEnum.PUBLISHED)
    db.session.add(open_hw)
    db.session.flush()
    db.session.add(HomeworkStudent(homework_id=open_hw.id,
                                   student_id=ai_env['s1'].id))
    db.session.commit()
    sub = HomeworkSubmission(homework_id=open_hw.id, student_id=ai_env['s1'].id,
                             status=SubmissionStatusEnum.GRADED,
                             content='小论文', total_score=80.0)
    db.session.add(sub)
    db.session.commit()
    stats = _class_stats(open_hw)
    assert stats['questions'] == [] and stats['avg_score'] == 80.0
    assert stats['avg_ratio'] is None       # 开放式无满分基准
