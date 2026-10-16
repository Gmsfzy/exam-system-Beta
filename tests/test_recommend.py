# -*- coding: utf-8 -*-
"""薄弱点自适应推荐回归门：冷启动空、按掌握度薄弱排序、排除已作答的题。"""
from datetime import timedelta

from database import db
from database.models import (Answer, Exam, ExamSession, KnowledgeMastery,
                             KnowledgePoint, Question, User,
                             question_knowledge_point, utcnow)
from api import learning_engine as eng


def _mkq(content):
    q = Question(content=content, answer='a', major_id=1,
                 type='single_choice', difficulty='easy')
    db.session.add(q)
    db.session.commit()
    return q


def _link(qid, kpid):
    db.session.execute(
        question_knowledge_point.insert().values(
            question_id=qid, knowledge_point_id=kpid))


def _seed():
    stu = User(username='r_stu', role='student')
    stu.set_password('pw')
    db.session.add(stu)
    db.session.commit()
    kp1 = KnowledgePoint(chapter_id=1, name='KP1')
    kp2 = KnowledgePoint(chapter_id=1, name='KP2')
    db.session.add_all([kp1, kp2])
    db.session.commit()
    q1, q2, q3 = _mkq('q1属于KP1'), _mkq('q2属于KP2'), _mkq('q3属于KP1')
    _link(q1.id, kp1.id)
    _link(q2.id, kp2.id)
    _link(q3.id, kp1.id)
    # kp2 掌握度更低(5) 比 kp1(10) 更薄弱 → 其题目应优先被推荐
    db.session.add_all([
        KnowledgeMastery(user_id=stu.id, knowledge_point_id=kp1.id, level=10.0),
        KnowledgeMastery(user_id=stu.id, knowledge_point_id=kp2.id, level=5.0),
    ])
    db.session.commit()
    return stu, q1, q2, q3


def _mark_answered(stu, q):
    """把某题记入该生一次已交卷考试的作答，用于验证"已练过"被排除。"""
    now = utcnow()
    exam = Exam(title='已练卷', start_time=now - timedelta(hours=1),
                end_time=now + timedelta(hours=1), duration=60,
                creator_id=stu.id)
    db.session.add(exam)
    db.session.commit()
    sess = ExamSession(exam_id=exam.id, student_id=stu.id, status='submitted')
    db.session.add(sess)
    db.session.commit()
    db.session.add(Answer(session_id=sess.id, question_id=q.id,
                          student_answer='a'))
    db.session.commit()


def test_cold_start_returns_empty(app):
    stu = User(username='cold', role='student')
    stu.set_password('pw')
    db.session.add(stu)
    db.session.commit()
    # 无任何掌握度记录：冷启动不强推
    assert eng.recommend_practice_questions(stu.id, limit=5) == []


def test_recommend_orders_by_weakness(app):
    stu, q1, q2, q3 = _seed()
    recs = eng.recommend_practice_questions(stu.id, limit=5)
    ids = [r['question_id'] for r in recs]
    # 更薄弱的 KP2 题(q2)优先；q1/q3 同属 KP1 按题 id 升序
    assert ids == [q2.id, q1.id, q3.id]
    assert recs[0]['knowledge_point'] == 'KP2'
    assert recs[0]['mastery'] == 5.0


def test_recommend_excludes_answered(app):
    stu, q1, q2, q3 = _seed()
    _mark_answered(stu, q3)
    ids = [r['question_id']
           for r in eng.recommend_practice_questions(stu.id, limit=5)]
    assert q3.id not in ids       # 已作答的题不再推荐
    assert q2.id in ids and q1.id in ids


def test_recommend_respects_limit(app):
    stu, q1, q2, q3 = _seed()
    assert len(eng.recommend_practice_questions(stu.id, limit=1)) == 1
