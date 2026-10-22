# -*- coding: utf-8 -*-
"""v5.18 跨作业学情分析看板：服务层回归门（函数层，内存库）。

锁定纯读聚合语义（不改判分/账本）：
1. build_class_analytics 返回 {summary,trend,knowledge_heat,weak_questions} 四块，
   summary 计数与逐作业 trend 完成率/得分率一致；
2. 每题区分度用 27% 高低分组：高分组全对、低分组全错的题 D=1.0，
   高低组同得分率的题 D=0.0（与考试 item_analysis 同口径）；
3. weak_questions 跨作业按平均得分率升序（最弱在前）；
4. 样本过小（n ≤ 2×组容量）时区分度不可信 → 返回空/None；
5. 开放式作业无题目级指标，仅进 trend，不进 weak_questions。
端点侧（鉴权/教师过滤）由 test_http_e2e 覆盖。
"""
import pytest

from database import db
from database.models import Question, Major
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.services import build_class_analytics, _question_discrimination


@pytest.fixture()
def an_env(app, user_factory):
    major = Major(name='V518专业')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('v518_teacher', role='teacher')
    students = [user_factory(f'v518_s{i}') for i in range(1, 5)]

    def q(content, answer, qtype='single_choice', options=None):
        row = Question(content=content, answer=answer, type=qtype, difficulty='easy',
                       major_id=major.id, options=options or ['A. 1', 'B. 2', 'C. 3', 'D. 4'])
        db.session.add(row)
        db.session.flush()
        return row

    def make_hw(questions, hw_type=HomeworkTypeEnum.QUESTION_SET, pub=None):
        hw = Homework(title='v518作业', hw_type=hw_type, teacher_id=teacher.id,
                      status=HomeworkStatusEnum.PUBLISHED, published_at=pub)
        db.session.add(hw)
        db.session.flush()
        for i, (question, score) in enumerate(questions):
            db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=question.id,
                                            score=score, order=i))
        for st in students:
            db.session.add(HomeworkStudent(homework_id=hw.id, student_id=st.id))
        db.session.commit()
        return hw

    def grade(hw, per_student):
        """per_student: {student_index: {question_id: answer_text}}，全客观自动判分并置已批。"""
        subs = []
        for idx, answers in per_student.items():
            sub = HomeworkSubmission(homework_id=hw.id, student_id=students[idx].id,
                                     status=SubmissionStatusEnum.SUBMITTED, max_score=hw.max_score())
            db.session.add(sub)
            db.session.flush()
            for qid, text in answers.items():
                db.session.add(HomeworkAnswer(submission_id=sub.id, question_id=qid, answer=text))
            db.session.commit()
            from homework.services import grade_submission, recompute_total
            grade_submission(hw, sub)
            recompute_total(sub)
            sub.status = SubmissionStatusEnum.GRADED
            db.session.commit()
            subs.append(sub)
        return subs

    return {'teacher': teacher, 'students': students, 'q': q,
            'make_hw': make_hw, 'grade': grade}


def test_analytics_structure_and_rates(an_env):
    easy = an_env['q']('1+1=?', 'B')
    hw = an_env['make_hw']([(easy, 10.0)])
    an_env['grade'](hw, {i: {easy.id: 'B'} for i in range(4)})   # 四人全对
    data = build_class_analytics([hw])
    assert set(data) == {'summary', 'trend', 'knowledge_heat', 'weak_questions'}
    assert data['summary']['homework_count'] == 1
    assert data['summary']['total_submissions'] == 4
    assert data['trend'][0]['submitted_rate'] == 100.0
    assert data['trend'][0]['avg_ratio'] == 1.0


def test_discrimination_27_percent_method(an_env):
    easy = an_env['q']('人人会', 'B')
    hard = an_env['q']('只有榜首会', 'AC', qtype='multiple_choice',
                       options=['A. 2', 'B. 3', 'C. 4', 'D. 5'])
    hw = an_env['make_hw']([(easy, 10.0), (hard, 10.0)])
    an_env['grade'](hw, {
        0: {easy.id: 'B', hard.id: 'AC'},   # 榜首：两题全对 → 总分 20（高分组）
        1: {easy.id: 'B', hard.id: 'A'},
        2: {easy.id: 'B', hard.id: 'A'},
        3: {easy.id: 'B', hard.id: 'A'},     # 末位：难题错 → 低分组
    })
    disc = _question_discrimination(hw)
    assert disc[easy.id] == 0.0            # 高低组都全对 → 无区分
    assert disc[hard.id] == 1.0            # 高分组对、低分组错 → 满分区分
    data = build_class_analytics([hw])
    weak = {w['question_id']: w for w in data['weak_questions']}
    assert weak[hard.id]['avg_ratio'] == 0.25      # 4 人仅 1 人对
    assert weak[hard.id]['discrimination'] == 1.0
    # 得分率升序：最弱（hard 0.25）排在 easy（1.0）之前
    ratios = [w['avg_ratio'] for w in data['weak_questions']]
    assert ratios == sorted(ratios)


def test_discrimination_none_when_sample_small(an_env):
    hard = an_env['q']('难题', 'AC', qtype='multiple_choice',
                       options=['A. 2', 'B. 3', 'C. 4', 'D. 5'])
    hw = an_env['make_hw']([(hard, 10.0)])
    an_env['grade'](hw, {0: {hard.id: 'AC'}, 1: {hard.id: 'A'}})   # 仅 2 人，样本过小
    assert _question_discrimination(hw) == {}
    data = build_class_analytics([hw])
    assert data['weak_questions'][0]['discrimination'] is None


def test_open_homework_only_in_trend(an_env):
    hw = an_env['make_hw']([], hw_type=HomeworkTypeEnum.OPEN)
    sub = HomeworkSubmission(homework_id=hw.id, student_id=an_env['students'][0].id,
                             status=SubmissionStatusEnum.GRADED, content='作答',
                             total_score=8.0, max_score=10.0)
    db.session.add(sub)
    db.session.commit()
    data = build_class_analytics([hw])
    assert len(data['trend']) == 1
    assert data['weak_questions'] == []
    assert data['knowledge_heat'] == []
