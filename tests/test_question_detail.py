# -*- coding: utf-8 -*-
"""v6.1 单题详情序列化 _serialize_question 的角色脱敏回归门（内存库，函数级）。

锁住「题目一步直达」新增端点 GET /api/questions/<id> 背后的序列化单一真值语义
（列表与详情共用同一 helper）：
1. 教师视角回显答案/解析/OJ 用例，is_owner 按 creator 判定；
2. 学生视角剔除答案/解析/用例（answer==''、analysis==''、test_cases is None），
   但保留题干/选项（脱敏只剔「答案类」字段，不削弱考前可正常看到题面）；
3. is_owner 对学生恒为 False（即便未来放开，也不把所有权泄露给学生视图）。
"""
from database import db
from database.models import Question, Major
from api.question_routes import _serialize_question


def test_serialize_question_teacher_full(app, user_factory):
    major = Major(name='详情专业')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('qd_teacher', role='teacher')
    q = Question(content='1+1=?', answer='2', analysis='因为合并', type='single_choice',
                 difficulty='easy', major_id=major.id, creator_id=teacher.id,
                 options=['1', '2', '3'], test_cases=[{'input': '', 'expected': '2'}])
    db.session.add(q)
    db.session.commit()

    d = _serialize_question(q, is_teacher=True, uid=teacher.id)
    assert d['id'] == q.id
    assert d['answer'] == '2'
    assert d['analysis'] == '因为合并'
    assert d['test_cases'] == [{'input': '', 'expected': '2'}]
    assert d['major_name'] == '详情专业'
    assert d['is_owner'] is True


def test_serialize_question_student_masked(app, user_factory):
    major = Major(name='详情专业2')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('qd_teacher2', role='teacher')
    q = Question(content='选 B', answer='B', analysis='解析正文', type='single_choice',
                 difficulty='easy', major_id=major.id, creator_id=teacher.id,
                 options=['A', 'B'], test_cases=[{'input': '', 'expected': 'B'}])
    db.session.add(q)
    db.session.commit()

    student = user_factory('qd_student', role='student')
    d = _serialize_question(q, is_teacher=False, uid=student.id)
    # 学生剔除答案类字段
    assert d['answer'] == ''
    assert d['analysis'] == ''
    assert d['test_cases'] is None
    # 但题干/选项照常可见（脱敏不影响题面）
    assert d['content'] == '选 B'
    assert d['options'] == ['A', 'B']
    # 所有权标识对学生恒 False
    assert d['is_owner'] is False
