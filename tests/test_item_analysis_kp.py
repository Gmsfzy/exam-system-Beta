# -*- coding: utf-8 -*-
"""v4.6.1 扩展补齐回归门：试题分析的知识点维度聚合。

规则：多对多主数据（question_knowledge_point）优先；无主数据时旧
knowledge 逗号字符串必须拆分成多个桶（曾整串当一个键）；输出附带
knowledge_point_id / avg_discrimination / question_ids 供前端联动。
"""
import api.exam_routes as er
from database import db
from database.models import (
    Answer, Chapter, Course, Exam, ExamQuestion, ExamSession, KnowledgePoint,
    Major, Question, Result,
)
from utils.timeutil import utcnow


def _seed(user_factory):
    teacher = user_factory('kp_t', 'teacher')
    student = user_factory('kp_s')
    major = Major(name='M')
    course = Course(name='C', major=major)
    chapter = Chapter(name='CH', course=course)
    kp = KnowledgePoint(name='向量', chapter=chapter)
    db.session.add_all([teacher, student, major, course, chapter, kp])
    db.session.commit()

    def _q(content, knowledge):
        return Question(content=content, answer='A', type='single_choice',
                        difficulty='easy', knowledge=knowledge,
                        major_id=major.id, course_id=course.id, chapter_id=chapter.id)

    q_m = _q('主数据题', '杂项字符串')   # 有主数据：字符串应被忽略
    db.session.add(q_m)                   # 先入 session 再挂 m2m，避免 autoflush 警告
    q_m.knowledge_points.append(kp)
    q_s = _q('字符串题', '三角函数,数列')  # 无主数据：应拆成两个桶
    now = utcnow()
    exam = Exam(title='E', start_time=now, end_time=now, duration=60,
                creator_id=teacher.id, status='ended')
    db.session.add_all([q_m, q_s, exam])
    db.session.commit()
    for i, q in enumerate([q_m, q_s], start=1):
        db.session.add(ExamQuestion(exam_id=exam.id, question_id=q.id, score=10, order=i))
    sess = ExamSession(exam_id=exam.id, student_id=student.id, status='submitted')
    db.session.add(sess)
    db.session.commit()
    # 主数据题答对（10/10），字符串题答错（0/10）
    db.session.add_all([
        Answer(session_id=sess.id, question_id=q_m.id, student_answer='A',
               is_correct=True, score=10),
        Answer(session_id=sess.id, question_id=q_s.id, student_answer='B',
               is_correct=False, score=0),
    ])
    db.session.add(Result(exam_id=exam.id, student_id=student.id,
                          score=10, total_score=20, session_id=sess.id))
    db.session.commit()
    return teacher, exam


def test_knowledge_aggregation_uses_master_data_first(app, user_factory, monkeypatch):
    teacher, exam = _seed(user_factory)
    monkeypatch.setattr(er, 'verify_token', lambda: teacher)

    resp = None
    with app.test_request_context():
        resp = er.api_item_analysis(exam.id)
    data = resp.get_json()

    buckets = {k['knowledge']: k for k in data['knowledge']}
    # 旧字符串拆分生效：'三角函数,数列' 不再是一个桶
    assert '三角函数,数列' not in buckets
    assert set(buckets) == {'向量', '三角函数', '数列'}

    vec = buckets['向量']
    assert vec['knowledge_point_id'] is not None          # 主数据实体 id
    assert vec['question_ids'] and vec['question_count'] == 1
    assert vec['avg_score_rate'] == 1.0
    for name in ('三角函数', '数列'):
        assert buckets[name]['knowledge_point_id'] is None  # 字符串兜底桶无实体 id
        assert buckets[name]['avg_score_rate'] == 0.0

    # 单学生场景高低分组不可比：区分度应为 None 而不报错
    assert buckets['向量']['avg_discrimination'] is None

    # 逐题 knowledge 展示串已切换为主数据名（旧字符串仅兜底不参与聚合展示）
    qrow = {q['question_id']: q for q in data['questions']}
    assert qrow[data['questions'][0]['question_id']]['knowledge']


def test_empty_exam_returns_empty_knowledge(app, user_factory, monkeypatch):
    teacher, exam = _seed(user_factory)
    Result.query.delete()          # 无成绩路径
    db.session.commit()
    monkeypatch.setattr(er, 'verify_token', lambda: teacher)
    with app.test_request_context():
        data = er.api_item_analysis(exam.id).get_json()
    assert data['knowledge'] == [] and data['participants'] == 0
