# -*- coding: utf-8 -*-
"""作业判分与时效服务（v5.0）。

判分口径与考试链路一致但独立实现（避免耦合 ExamSession 结构）：
- 客观题：api/exam_engine.check_objective 单一判分事实源（单选/多选/填空/判断）
- 编程题（有 test_cases）：oj.services.grade 按通过率折算，记 oj_verdict；空码 CE
- 其余主观题/开放式：needs_manual_grade=True，待教师逐题/整体给分
作业不进 ledger：此处只落 HomeworkSubmission/HomeworkAnswer，无任何积分/钱包写入。
"""
import json

from database import db
from database.models import Question, QuestionTypeEnum
from utils.logger import logger
from utils.timeutil import utcnow, iso_local
from homework.models import (
    Homework, HomeworkStatusEnum, HomeworkTypeEnum, HomeworkSubmission,
    HomeworkAnswer, SubmissionStatusEnum,
)


def grade_submission(hw, sub):
    """对题集式提交逐题判分（重交覆盖时全量重算并清人工分）。

    返回 (auto_earned, max_total)；调用方负责 commit。
    未作答的题目补记空作答行（自动 0 分 / 主观空答不送人工），与考试收卷语义一致。
    """
    from api.exam_engine import check_objective

    hqs = sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))
    q_ids = [hq.question_id for hq in hqs]
    qmap = {q.id: q for q in Question.query.filter(Question.id.in_(q_ids)).all()} if q_ids else {}
    amap = {a.question_id: a for a in sub.answers}
    earned = 0.0
    total = 0.0
    for hq in hqs:
        total += hq.score or 0
        q = qmap.get(hq.question_id)
        a = amap.get(hq.question_id)
        if a is None:
            a = HomeworkAnswer(submission_id=sub.id, question_id=hq.question_id, answer='')
            db.session.add(a)
            sub.answers.append(a)
        # 重交覆盖：清空上一轮人工批改痕迹
        a.manual_score = None
        a.comment = None
        if not q:
            a.needs_manual_grade = False
            a.is_correct = False
            a.auto_score = 0.0
            continue
        text = (a.answer or '').strip()

        # 编程题 OJ：有用例即机器判（与考试/练习链路同一口径）
        if q.type == QuestionTypeEnum.PROGRAMMING and getattr(q, 'test_cases', None):
            a.needs_manual_grade = False
            if not text:
                a.oj_verdict, a.is_correct, a.auto_score = 'CE', False, 0.0
            else:
                from oj.services import grade as oj_grade
                r = oj_grade(text, 'python', q.test_cases)
                if r['supported']:
                    ratio = (r['passed'] / r['total']) if r['total'] else 0.0
                    a.oj_verdict = r['verdict']
                    a.is_correct = r['verdict'] == 'AC'
                    a.auto_score = round((hq.score or 0) * ratio, 2)
                else:
                    a.needs_manual_grade = True   # 语言不支持评测 → 回落人工
                    a.auto_score = None
            if not a.needs_manual_grade:
                earned += a.auto_score or 0.0
            continue

        if QuestionTypeEnum.is_subjective(q.type):
            if not text:
                a.needs_manual_grade = False
                a.is_correct = False
                a.auto_score = 0.0
            else:
                a.needs_manual_grade = True
                a.is_correct = None
                a.auto_score = None
            continue

        ok, ratio = check_objective(q.type, text, (q.answer or '').strip())
        a.needs_manual_grade = False
        a.is_correct = ok
        a.auto_score = round((hq.score or 0) * ratio, 2)
        earned += a.auto_score
    sub.max_score = round(total, 2)
    sub.total_score = None   # 含人工待批则总分以批改完成为准
    return round(earned, 2), round(total, 2)


def recompute_total(sub):
    """按当前作答有效分汇总总分（批改调用后复用）。返回 (earned, max_total, pending_manual)。"""
    earned = round(sum(a.effective_score for a in sub.answers), 2)
    max_total = sub.max_score or round(sum(
        (hq.score or 0) for hq in sub.homework.hw_questions), 2)
    pending = [a for a in sub.answers if a.needs_manual_grade and a.manual_score is None]
    sub.total_score = earned
    sub.max_score = max_total
    return earned, max_total, len(pending)


def finalize_submission(hw, sub):
    """提交/重交落状态：题集式走自动判分，开放式整体待批。"""
    if hw.hw_type == HomeworkTypeEnum.QUESTION_SET:
        grade_submission(hw, sub)
    else:
        sub.max_score = None
        sub.total_score = None
    sub.status = SubmissionStatusEnum.SUBMITTED
    sub.submitted_at = utcnow()
    sub.is_late = bool(hw.is_expired)
    return sub


def notify_homework_students(hw, title, content, only_unsubmitted=False):
    """批量通知名单学生：commit=False 由调用方统一提交（遵守循环内不逐行 commit 规范）。

    实时推送由 ORM 事件（utils/notify_socket）在调用方 commit 后自动发出，此处无需手动推。"""
    from api.notification_routes import create_notification
    submitted_ids = set()
    if only_unsubmitted:
        submitted_ids = {s.student_id for s in hw.submissions
                         if s.status in (SubmissionStatusEnum.SUBMITTED,
                                         SubmissionStatusEnum.GRADED)}
    n = 0
    for hs in hw.hw_students:
        if hs.student_id in submitted_ids:
            continue
        create_notification(hs.student_id, title, content, type='info',
                            related_type='homework', related_id=hw.id, commit=False)
        n += 1
    return n


def homework_expiry_tick():
    """后台调度任务：到期锁定 + 截止前未交提醒（各自独立事务，单点失败不阻塞其余）。

    1) published 且已过 deadline 且 allow_late=False → 自动 closed（迟交通道关闭）
    2) published 且 remind_before>0 且未提醒过 且 now >= deadline-提醒窗口 →
       给未提交学生发提醒；reminded_at 条件 UPDATE CAS 抢占，多进程/多轮幂等
    """
    now = utcnow()
    # 1) 到期锁定
    due = Homework.query.filter(Homework.status == HomeworkStatusEnum.PUBLISHED,
                                 Homework.deadline < now,
                                 Homework.allow_late == False).all()  # noqa: E712
    for hw in due:
        try:
            hw.status = HomeworkStatusEnum.CLOSED
            db.session.commit()
            logger.info(f'[homework] 作业 {hw.id} 截止且不允许迟交，已自动关闭')
        except Exception:
            db.session.rollback()
            logger.error(f'[homework] 到期关闭失败 hw={hw.id}', exc_info=True)
    # 2) 截止前提醒
    to_remind = Homework.query.filter(Homework.status == HomeworkStatusEnum.PUBLISHED,
                                      Homework.remind_before > 0,
                                      Homework.reminded_at.is_(None)).all()
    for hw in to_remind:
        try:
            if hw.deadline is None:
                continue
            from datetime import timedelta
            remind_at = hw.deadline - timedelta(minutes=hw.remind_before)
            if now < remind_at or now > hw.deadline:
                continue
            # CAS 抢占提醒权（并发/多进程幂等）
            res = db.session.execute(
                db.text('UPDATE homework SET reminded_at = :now '
                        'WHERE id = :id AND reminded_at IS NULL'),
                {'now': now, 'id': hw.id})
            if res.rowcount != 1:
                db.session.rollback()
                continue
            db.session.refresh(hw)
            title = '作业即将截止'
            content = f'《{hw.title}》将于 {iso_local(hw.deadline)} 截止，请尽快提交。'
            notify_homework_students(hw, title, content, only_unsubmitted=True)
            db.session.commit()
            logger.info(f'[homework] 作业 {hw.id} 截止提醒已发送给未提交学生')
        except Exception:
            db.session.rollback()
            logger.error(f'[homework] 截止提醒失败 hw={hw.id}', exc_info=True)


def ai_suggest_grading(sub):
    """AI 辅助批改建议（不落库）：对每个待人工作答调用 ai_client.grade_answer。

    返回 {suggestions: [{answer_id, suggestion_id?, score, comment}], failed: n}；
    score 已按题目满分换算（AI 原始返回 0-100 百分比，同考试 clamp 口径）。
    """
    from ai_service.services import ai_client
    hw = sub.homework
    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
    suggestions = []
    failed = 0
    for a in sub.answers:
        if not a.needs_manual_grade or a.manual_score is not None:
            continue
        q = db.session.get(Question, a.question_id)
        hq = hq_map.get(a.question_id)
        if not q or not hq:
            continue
        try:
            result = ai_client.grade_answer(q.content, q.answer or '', a.answer or '')
            data = json.loads(result)
            ratio = max(0.0, min(float(data.get('score', 0) or 0), 100.0)) / 100.0
            suggestions.append({
                'answer_id': a.id, 'question_id': a.question_id,
                'score': round(ratio * (hq.score or 0), 2), 'max_score': hq.score,
                'is_correct': bool(data.get('is_correct', False)),
                'comment': str(data.get('comment') or data.get('analysis') or '')[:500],
            })
        except Exception:
            failed += 1
            logger.debug(f'[homework] AI 建议失败 answer={a.id}（非关键路径）', exc_info=True)
    return {'suggestions': suggestions, 'failed': failed}
