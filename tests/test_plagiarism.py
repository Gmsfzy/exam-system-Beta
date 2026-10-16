# -*- coding: utf-8 -*-
"""编程题代码抄袭查重回归门：词法归一、Jaccard 相似度、阈值与短码排除、DB 集成。"""
from datetime import timedelta

from database import db
from database.models import (Answer, Exam, ExamSession, Question, User,
                             utcnow)
from oj import plagiarism as pl

CODE_A = (
    "def solve(n):\n"
    "    total = 0\n"
    "    for i in range(n):\n"
    "        total = total + i * 2\n"
    "    print(total)\n"
    "    return total\n"
)
# 与 CODE_A 逻辑一致，仅多整行注释/空行/缩进差异——归一化后应高度相似
CODE_COPY = (
    "# 计算前 n 项\n"
    "def solve( n ):\n\n"
    "        total=0\n"
    "        for i in range(n):\n"
    "                total = total + i * 2\n"
    "        print( total )\n"
    "        return total\n"
)
CODE_UNRELATED = (
    "import math\n"
    "def area(r):\n"
    "    pi = math.pi\n"
    "    result = pi * r * r\n"
    "    return round(result, 2)\n"
)


def test_tokenize_strips_comments_and_blank_lines():
    toks = pl._tokenize(CODE_COPY)
    # 注释词"计算前"不应出现在 token 流（整行注释被丢弃）
    assert '计算前' not in ''.join(toks)
    assert 'def' in toks and 'solve' in toks


def test_similarity_identical_is_one():
    assert pl.similarity(CODE_A, CODE_A) == 1.0


def test_similarity_reformat_high():
    # 仅注释/缩进/空格差异：归一化后 token 序列一致 → 高相似
    assert pl.similarity(CODE_A, CODE_COPY) >= 0.9


def test_similarity_unrelated_low():
    assert pl.similarity(CODE_A, CODE_UNRELATED) < 0.3


def test_similarity_empty_is_zero():
    assert pl.similarity('', CODE_A) == 0.0


def test_compare_submissions_flags_pair_and_excludes_short():
    subs = [
        {'student_id': 1, 'username': 'u1', 'code': CODE_A},
        {'student_id': 2, 'username': 'u2', 'code': CODE_COPY},
        {'student_id': 3, 'username': 'u3', 'code': CODE_UNRELATED},
        {'student_id': 4, 'username': 'short', 'code': 'return 1'},  # 过短排除
    ]
    pairs = pl.compare_submissions(subs, threshold=0.7, min_tokens=15)
    flagged = {(p['a']['student_id'], p['b']['student_id']) for p in pairs}
    assert (1, 2) in flagged           # 抄袭对被识别
    assert (1, 3) not in flagged       # 无关对不误报
    assert all('short' not in (p['a']['username'], p['b']['username'])
               for p in pairs)         # 短码不参与


def _seed_full_exam():
    """建 1 道编程题 + 3 名学生：u1/u2 提交雷同，u3 提交无关代码。"""
    teacher = User(username='t_plag', role='teacher')
    teacher.set_password('pw')
    db.session.add(teacher)
    db.session.commit()

    now = utcnow()
    exam = Exam(title='编程测验', start_time=now - timedelta(hours=1),
                end_time=now + timedelta(hours=1), duration=60,
                creator_id=teacher.id)
    db.session.add(exam)
    q = Question(content='写函数', answer='略', major_id=1,
                 type='programming', difficulty='easy')
    db.session.add(q)
    db.session.commit()

    codes = {'s1': ('p1', CODE_A), 's2': ('p2', CODE_COPY),
             's3': ('p3', CODE_UNRELATED)}
    for uname, code in codes.values():
        stu = User(username=uname, role='student')
        stu.set_password('pw')
        db.session.add(stu)
        db.session.commit()
        sess = ExamSession(exam_id=exam.id, student_id=stu.id, status='submitted')
        db.session.add(sess)
        db.session.commit()
        db.session.add(Answer(session_id=sess.id, question_id=q.id,
                              student_answer=code))
    db.session.commit()
    return exam.id, q.id


def test_find_similar_pairs_integration(app):
    exam_id, qid = _seed_full_exam()
    items = pl.find_similar_pairs(exam_id, threshold=0.7)
    assert len(items) == 1
    assert items[0]['question_id'] == qid
    pairs = items[0]['pairs']
    assert len(pairs) == 1
    names = {pairs[0]['a']['username'], pairs[0]['b']['username']}
    assert names == {'p1', 'p2'}


def test_find_similar_pairs_threshold_filters(app):
    exam_id, _ = _seed_full_exam()
    # 抬高阈值到 0.99：雷同对相似度略低于它则被过滤（无关对始终被排除）
    items = pl.find_similar_pairs(exam_id, threshold=0.99)
    for it in items:
        for p in it['pairs']:
            assert p['similarity'] >= 0.99
