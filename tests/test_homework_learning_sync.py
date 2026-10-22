# -*- coding: utf-8 -*-
"""v5.2 作业→学习闭环联动回归门（函数层，内存库）。

锁住 homework.services.sync_learning_effects 与错题本答案门控的核心语义：
1. 错题收录判错标准为得分率 <60%（客观错 0 收、人工 5/10 收、8/10 不收、满分不收）；
2. 两段式 scope 不双计：auto 只收自动判分题、final 只收人工题；重复同步 wrong_count 幂等 +1；
3. 收录走统一入口：source_type='homework'、复习队列 ReviewItem 同步建立；
4. 知识点掌握度 EWMA 联动（答错下降、答对上升）；
5. 答案门控 _source_still_reanswerable：作业未批改/可重交时隐藏，GRADED/关闭后放行；
   考试发布中未截止且剩余次数未用完时隐藏。
"""
from datetime import timedelta

import pytest

from database import db
from database.models import (
    Course, Chapter, Exam, ExamSession, ExamStatusEnum, KnowledgeMastery,
    KnowledgePoint, Major, Notification, Question, ReviewItem, WrongAnswerRecord,
    question_knowledge_point,
)
from utils.timeutil import utcnow
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.services import (
    finalize_submission, grade_submission, sync_learning_effects,
)
from api.learning_routes import _source_still_reanswerable, _wrong_record_to_dict


@pytest.fixture()
def sync_env(app, user_factory):
    """教师+学生+四类题与作业助手（沿用 test_homework_services 构造法）。"""
    major = Major(name='SYNC专业')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('sync_teacher', role='teacher')
    student = user_factory('sync_student')

    def q(content, answer, qtype, test_cases=None):
        row = Question(content=content, answer=answer, type=qtype, difficulty='easy',
                       major_id=major.id,
                       options=['A. 对', 'B. 错'] if qtype in ('single_choice', 'true_false') else None,
                       test_cases=test_cases)
        db.session.add(row)
        db.session.flush()
        return row

    env = {'teacher': teacher, 'student': student, 'major': major,
           'q_single': q('1+1=?', 'B', 'single_choice'),
           'q_tf': q('1>2 是对的？', 'B', 'true_false'),
           'q_short': q('简述快排思想', '分治', 'short_answer')}

    def make_hw(items, deadline_hours=24, allow_late=True):
        hw = Homework(title='联动作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                      teacher_id=teacher.id,
                      deadline=utcnow() + timedelta(hours=deadline_hours),
                      status=HomeworkStatusEnum.PUBLISHED, allow_late=allow_late)
        db.session.add(hw)
        db.session.flush()
        for i, (question, score) in enumerate(items):
            db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=question.id,
                                            score=score, order=i))
        db.session.add(HomeworkStudent(homework_id=hw.id, student_id=student.id))
        db.session.commit()
        return hw

    def submit(hw, answers):
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=SubmissionStatusEnum.DRAFT)
        db.session.add(sub)
        db.session.flush()
        for qid, text in answers.items():
            db.session.add(HomeworkAnswer(submission_id=sub.id, question_id=qid, answer=text))
        db.session.commit()
        finalize_submission(hw, sub)
        db.session.commit()
        return sub

    env['make_hw'] = make_hw
    env['submit'] = submit
    return env


def _wrong_rows(student_id):
    return WrongAnswerRecord.query.filter_by(user_id=student_id, source_type='homework').all()


def test_auto_sync_objective_wrong_and_review_item(sync_env):
    hw = sync_env['make_hw']([(sync_env['q_single'], 5.0), (sync_env['q_tf'], 5.0)])
    sub = sync_env['submit'](hw, {sync_env['q_single'].id: 'A',  # 错（正确 B）
                                  sync_env['q_tf'].id: 'B'})     # 对
    n = sync_learning_effects(hw, sub, scope='auto')
    assert n == 1
    rows = _wrong_rows(sync_env['student'].id)
    assert len(rows) == 1
    rec = rows[0]
    assert rec.question_id == sync_env['q_single'].id
    assert rec.source_id == hw.id and rec.wrong_count == 1
    assert rec.correct_answer == 'B'
    # 复习队列同步建立
    assert ReviewItem.query.filter_by(user_id=sync_env['student'].id,
                                      question_id=sync_env['q_single'].id).count() == 1


def test_wrong_count_merges_idempotently_on_resync(sync_env):
    hw = sync_env['make_hw']([(sync_env['q_single'], 5.0)])
    sub = sync_env['submit'](hw, {sync_env['q_single'].id: 'A'})
    sync_learning_effects(hw, sub, scope='auto')
    # 重交仍错 → 再次同步：仍是单条记录，wrong_count +1（不双计同一 scope 外的题）
    sync_learning_effects(hw, sub, scope='auto')
    rows = _wrong_rows(sync_env['student'].id)
    assert len(rows) == 1 and rows[0].wrong_count == 2


def test_subjective_not_synced_until_final_and_ratio_threshold(sync_env):
    hw = sync_env['make_hw']([(sync_env['q_short'], 10.0)])
    sub = sync_env['submit'](hw, {sync_env['q_short'].id: '随便写的答案'})
    # 主观题在 auto 阶段不收录（尚未人工判分）
    assert sync_learning_effects(hw, sub, scope='auto') == 0
    assert _wrong_rows(sync_env['student'].id) == []
    # 人工给 5/10（得分率 0.5 < 0.6）→ final 收录
    sub.answers[0].manual_score = 5.0
    db.session.commit()
    assert sync_learning_effects(hw, sub, scope='final') == 1
    assert len(_wrong_rows(sync_env['student'].id)) == 1


def test_ratio_above_threshold_not_synced(sync_env):
    hw = sync_env['make_hw']([(sync_env['q_short'], 10.0)])
    sub = sync_env['submit'](hw, {sync_env['q_short'].id: '还行的答案'})
    # 人工给 8/10（0.8 ≥ 0.6）：未满分但基本掌握，不打扰
    sub.answers[0].manual_score = 8.0
    db.session.commit()
    assert sync_learning_effects(hw, sub, scope='final') == 0
    assert _wrong_rows(sync_env['student'].id) == []


def test_perfect_score_no_record(sync_env):
    hw = sync_env['make_hw']([(sync_env['q_single'], 5.0), (sync_env['q_tf'], 5.0)])
    sub = sync_env['submit'](hw, {sync_env['q_single'].id: 'B', sync_env['q_tf'].id: 'B'})
    assert sync_learning_effects(hw, sub, scope='auto') == 0
    assert _wrong_rows(sync_env['student'].id) == []


def test_mastery_ewma_updates_both_directions(sync_env):
    course = Course(name='同步课程', major_id=sync_env['major'].id)
    db.session.add(course)
    db.session.flush()
    chapter = Chapter(name='同步章', course_id=course.id)
    db.session.add(chapter)
    db.session.flush()
    kp = KnowledgePoint(chapter_id=chapter.id, name='快排')
    db.session.add(kp)
    db.session.flush()
    db.session.execute(question_knowledge_point.insert().values(
        question_id=sync_env['q_single'].id, knowledge_point_id=kp.id))
    db.session.commit()

    # 答错：掌握度建立且观测为 0（EWMA 从 0 起仍 0，total_attempts 计数）
    hw = sync_env['make_hw']([(sync_env['q_single'], 5.0)])
    sub = sync_env['submit'](hw, {sync_env['q_single'].id: 'A'})
    sync_learning_effects(hw, sub, scope='auto')
    m = KnowledgeMastery.query.filter_by(user_id=sync_env['student'].id,
                                         knowledge_point_id=kp.id).first()
    assert m is not None and m.total_attempts == 1 and (m.total_correct or 0) == 0
    level_after_wrong = m.level

    # 换号学生答对：观测 100 → EWMA 抬升
    s2 = sync_env['teacher']  # 复用现成用户行即可（掌握度不按角色）
    hw2 = sync_env['make_hw']([(sync_env['q_single'], 5.0)])
    db.session.add(HomeworkStudent(homework_id=hw2.id, student_id=s2.id))
    sub2 = HomeworkSubmission(homework_id=hw2.id, student_id=s2.id,
                              status=SubmissionStatusEnum.DRAFT)
    db.session.add(sub2)
    db.session.flush()
    db.session.add(HomeworkAnswer(submission_id=sub2.id,
                                  question_id=sync_env['q_single'].id, answer='B'))
    db.session.commit()
    finalize_submission(hw2, sub2)
    db.session.commit()
    sync_learning_effects(hw2, sub2, scope='auto')
    m2 = KnowledgeMastery.query.filter_by(user_id=s2.id, knowledge_point_id=kp.id).first()
    assert m2 is not None and m2.level > level_after_wrong and m2.total_correct == 1


def test_answer_gate_homework_lifecycle(sync_env):
    hw = sync_env['make_hw']([(sync_env['q_single'], 5.0)])
    sub = sync_env['submit'](hw, {sync_env['q_single'].id: 'A'})
    sync_learning_effects(hw, sub, scope='auto')
    sid = sync_env['student'].id
    # 提交未批改：仍可重答 → 门控隐藏
    assert _source_still_reanswerable(sid, 'homework', hw.id) is True
    rec = _wrong_rows(sid)[0]
    d = _wrong_record_to_dict(rec, hide_answer=True)
    assert d['correct_answer'] is None and d['answer_hidden'] is True
    # 批改完成（GRADED 后禁止再交）→ 放行
    sub.status = SubmissionStatusEnum.GRADED
    db.session.commit()
    assert _source_still_reanswerable(sid, 'homework', hw.id) is False
    d2 = _wrong_record_to_dict(rec, hide_answer=False)
    assert d2['correct_answer'] == 'B' and d2['answer_hidden'] is False
    # 作业关闭（不再接收提交）→ 放行
    sub.status = SubmissionStatusEnum.SUBMITTED
    hw.status = HomeworkStatusEnum.CLOSED
    db.session.commit()
    assert _source_still_reanswerable(sid, 'homework', hw.id) is False


def test_answer_gate_exam_attempts_window(sync_env, user_factory):
    teacher = sync_env['teacher']
    student = sync_env['student']
    exam = Exam(title='门控考试', start_time=utcnow() - timedelta(hours=1),
                end_time=utcnow() + timedelta(hours=1), duration=60,
                status=ExamStatusEnum.PUBLISHED, creator_id=teacher.id, max_attempts=2)
    db.session.add(exam)
    db.session.flush()
    sess = ExamSession(exam_id=exam.id, student_id=student.id, status='submitted',
                       start_time=utcnow(), attempt_no=1)
    db.session.add(sess)
    db.session.commit()
    # 已用 1 次 < 最多 2 次且未截止 → 仍可重考 → 门控
    assert _source_still_reanswerable(student.id, 'exam', exam.id) is True
    # 次数用完 → 放行
    db.session.add(ExamSession(exam_id=exam.id, student_id=student.id, status='submitted',
                               start_time=utcnow(), attempt_no=2))
    db.session.commit()
    assert _source_still_reanswerable(student.id, 'exam', exam.id) is False
    # 已过截止时间 → 放行
    exam2 = Exam(title='过期考试', start_time=utcnow() - timedelta(hours=3),
                 end_time=utcnow() - timedelta(hours=1), duration=60,
                 status=ExamStatusEnum.PUBLISHED, creator_id=teacher.id, max_attempts=5)
    db.session.add(exam2)
    db.session.commit()
    assert _source_still_reanswerable(student.id, 'exam', exam2.id) is False
    # 其余来源不门控
    assert _source_still_reanswerable(student.id, 'practice', 1) is False
    assert _source_still_reanswerable(student.id, 'competition', 1) is False
