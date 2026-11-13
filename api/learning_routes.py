"""自我学习模块 API

蓝图前缀：/api/learning
功能：错题本、自由刷题、学习计划、学习报告聚合、AI 答疑、
     专业学习路径 + 知识图谱（知识点/边/路径/选课/进度/资源）
"""
import json
import hashlib
import math
import os
import re
import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, Response, stream_with_context, send_from_directory
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from database import db
from database.models import (
    Question, Major, Course, Chapter, User,
    WrongAnswerRecord, PracticeSession, PracticeAnswer,
    StudyPlan, StudyPlanTask, StudyLog,
    Exam, ExamSession, ExamStudent, ExamStatusEnum, Answer, Result,
    KnowledgePoint, KnowledgeEdge,
    LearningPath, LearningPathNode,
    UserPathEnrollment, UserNodeProgress, LearningResource,
    KnowledgeMastery, UserKpNote, QuizAttempt, QuizAttemptAnswer,
    ReviewItem, StudyCheckin, PathCertificate, DailyTask,
    UserCertificate, CERT_CATEGORY_LABELS, CERT_VERIFY_LABELS,
    CertificateDisplay, StudyInsight, CERT_KIND_LABELS,
    INSIGHT_SECTION_LABELS, INSIGHT_PERIOD_LABELS,
    AiChatConversation, AiChatMessage, FocusSession, StudyNote, ExplainCard,
    StudyFolder, StudyMaterial, MaterialFavorite, MaterialReport, UserFollow,
    AiUsageLog, AiQuota, Notebook, AiAskRecord,
    question_knowledge_point,
)
from utils.security import limiter, RateLimitConfig, verify_token
from utils.uploads import save_upload, UPLOAD_DIR, ALLOWED_EXTENSIONS as _UPLOAD_EXTS
from utils.timeutil import (utcnow, iso_local, parse_dt, local_today, local_date,
                           local_day_start, fmt_local)
from utils.logger import logger
from utils.notify import create_notification
from api import learning_engine as eng
from api.exam_engine import check_objective
from utils.permissions import require_teacher
from ai_service.gate import (check_ai_quota, charge_ai_quota, log_ai_usage,
                             get_quota_info)

api_learning_bp = Blueprint('api_learning', __name__)


# ── 错题本 ──────────────────────────────────────────────────────────

@api_learning_bp.route('/learning/wrong-records', methods=['GET'])
def api_wrong_list():
    """错题本列表（支持按来源、是否已掌握筛选）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    is_mastered = request.args.get('is_mastered')
    source_type = request.args.get('source_type')
    q_kw = (request.args.get('q') or '').strip()
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))

    q = WrongAnswerRecord.query.filter_by(user_id=user.id)
    if is_mastered is not None:
        q = q.filter_by(is_mastered=(is_mastered.lower() == 'true'))
    if source_type:
        q = q.filter_by(source_type=source_type)
    if q_kw:
        # v4.4 关键词检索：题干/知识点模糊匹配
        like = f'%{q_kw}%'
        q = q.join(Question, WrongAnswerRecord.question_id == Question.id).filter(
            or_(Question.content.like(like), Question.knowledge.like(like)))

    total = q.count()
    records = q.order_by(WrongAnswerRecord.last_wrong_at.desc()) \
        .offset((page - 1) * per_page).limit(per_page).all()

    # v5.2 答案门控：按来源逐类判定一次（缓存防 N+1），仍可重答的来源暂隐答案
    gate_cache = {}
    # v5.9 作业来源回链：批量取作业标题，错题本可跳回作业结果页
    hw_ids = {r.source_id for r in records if r.source_type == 'homework' and r.source_id}
    hw_titles = {}
    if hw_ids:
        from homework.models import Homework
        hw_titles = {h.id: h.title for h in Homework.query.filter(Homework.id.in_(hw_ids)).all()}
    items = []
    for r in records:
        key = (r.source_type, r.source_id)
        if key not in gate_cache:
            gate_cache[key] = _source_still_reanswerable(user.id, r.source_type, r.source_id)
        items.append(_wrong_record_to_dict(r, hide_answer=gate_cache[key],
                                           source_title=hw_titles.get(r.source_id)))

    return jsonify({
        'total': total,
        'page': page,
        'per_page': per_page,
        'items': items
    })


@api_learning_bp.route('/learning/wrong-records/<int:wr_id>/master', methods=['POST'])
def api_wrong_master(wr_id):
    """标记/取消标记某题为已掌握"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    rec = db.session.get(WrongAnswerRecord, wr_id)
    if not rec or rec.user_id != user.id:
        return jsonify({'message': '错题记录不存在'}), 404

    data = request.get_json(silent=True) or {}
    mastered = bool(data.get('mastered', True))
    rec.is_mastered = mastered
    rec.mastered_at = utcnow() if mastered else None
    db.session.commit()
    return jsonify({'message': '已更新掌握状态', 'is_mastered': rec.is_mastered})


@api_learning_bp.route('/learning/wrong-records/<int:wr_id>', methods=['DELETE'])
def api_wrong_delete(wr_id):
    """从错题本移除"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    rec = db.session.get(WrongAnswerRecord, wr_id)
    if not rec or rec.user_id != user.id:
        return jsonify({'message': '错题记录不存在'}), 404

    db.session.delete(rec)
    db.session.commit()
    return jsonify({'message': '已从错题本移除'})


def sync_wrong_from_answers(user_id, source_type, source_id, answers_with_correct):
    """通用错题收录：传入 [(question_id, wrong_answer, correct_answer), ...]"""
    count = 0
    for qid, wrong, correct in answers_with_correct:
        if not db.session.get(Question, qid):
            continue
        existing = WrongAnswerRecord.query.filter_by(user_id=user_id, question_id=qid).first()
        if existing:
            existing.wrong_count = (existing.wrong_count or 1) + 1
            existing.is_mastered = False
            existing.mastered_at = None
            existing.last_wrong_at = utcnow()
            existing.wrong_answer = wrong[:2000] if wrong else None
        else:
            db.session.add(WrongAnswerRecord(
                user_id=user_id, question_id=qid,
                source_type=source_type, source_id=source_id,
                wrong_answer=wrong[:2000] if wrong else None,
                correct_answer=correct[:2000] if correct else None,
            ))
        # 错题进入间隔复习队列（次日到期；已有卡则复活）
        eng.ensure_review_item(user_id, qid, source_type='wrong',
                              due_at=utcnow() + timedelta(days=1))
        count += 1
    db.session.commit()
    return count


# ── 自由刷题 ──────────────────────────────────────────────────────

@api_learning_bp.route('/learning/practice/start', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_practice_start():
    """开启一个自由刷题会话，返回本次会话的题目列表"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    title = data.get('title', '')
    major_id = data.get('major_id')
    course_id = data.get('course_id')
    chapter_id = data.get('chapter_id')
    knowledge_point_id = data.get('knowledge_point_id')  # 节点练习：按知识点关联表筛题
    count = min(max(int(data.get('count', 10) or 10), 1), 50)

    pool = Question.query
    if major_id:
        pool = pool.filter_by(major_id=major_id)
    if course_id:
        pool = pool.filter_by(course_id=course_id)
    if chapter_id:
        pool = pool.filter_by(chapter_id=chapter_id)
    if knowledge_point_id:
        pool = pool.join(
            question_knowledge_point,
            Question.id == question_knowledge_point.c.question_id,
        ).filter(question_knowledge_point.c.knowledge_point_id == knowledge_point_id)

    available = pool.all()
    if not available:
        return jsonify({'message': '未找到符合条件的题目，请选择不同的筛选条件'}), 404

    picked_count = min(count, len(available))
    import random
    picked = random.sample(available, picked_count)

    session = PracticeSession(
        user_id=user.id, title=title or f'练习 {fmt_local(utcnow(), "%m-%d %H:%M")}',
        major_id=major_id, course_id=course_id,
        questions_count=picked_count,
    )
    db.session.add(session)
    db.session.commit()
    db.session.refresh(session)

    # 预存题目关联到 PracticeAnswer（空答题，供刷新恢复）
    for q in picked:
        db.session.add(PracticeAnswer(session_id=session.id, question_id=q.id))
    db.session.commit()

    return jsonify({
        'session_id': session.id,
        'questions_count': picked_count,
        'questions': [_question_min_dict(q) for q in picked],
        'start_time': iso_local(session.start_time),
    })


@api_learning_bp.route('/learning/practice/<int:session_id>', methods=['GET'])
def api_practice_detail(session_id):
    """查询练习会话详情与答题情况"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    sess = db.session.get(PracticeSession, session_id)
    if not sess or sess.user_id != user.id:
        return jsonify({'message': '练习会话不存在'}), 404

    answers = db.session.query(PracticeAnswer).filter_by(session_id=sess.id).all()
    return jsonify({
        'id': sess.id, 'title': sess.title, 'status': sess.status,
        'questions_count': sess.questions_count,
        'correct_count': sess.correct_count,
        'total_time_sec': sess.total_time_sec,
        'start_time': iso_local(sess.start_time),
        'end_time': iso_local(sess.end_time) if sess.end_time else None,
        # questions 数组用于前端恢复完整题目（含 options/type）
        'questions': [_question_min_dict(a.question) for a in answers if a.question],
        'answers': [{
            'question_id': a.question_id,
            'question_content': a.question.content if a.question else None,
            'student_answer': a.student_answer,
            'correct_answer': a.question.answer if a.question else None,
            'is_correct': a.is_correct,
            'analysis': a.question.analysis if a.question else None,
        } for a in answers],
    })


@api_learning_bp.route('/learning/practice/<int:session_id>/answer', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_practice_answer(session_id):
    """提交单题作答（练习模式，可反复提交，最后一次覆盖）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    sess = db.session.get(PracticeSession, session_id)
    if not sess or sess.user_id != user.id:
        return jsonify({'message': '练习会话不存在'}), 404
    if sess.status != 'in_progress':
        return jsonify({'message': '该练习已结束'}), 400

    data = request.get_json(silent=True) or {}
    question_id = data.get('question_id')
    student_answer = (data.get('student_answer') or '').strip()
    time_spent_sec = int(data.get('time_spent_sec', 0) or 0)

    question = db.session.get(Question, question_id)
    if not question:
        return jsonify({'message': '题目不存在'}), 404

    # v4.10 编程题 OJ 自动评测（与考试判分链路一致）：有用例且非空代码直接判 AC/WA，
    # 未作答判 CE；无用例/工具链不可用语言回落原链路（主观题 is_correct=None 待人工）
    oj_info = None
    is_correct = None
    if question.type == 'programming' and getattr(question, 'test_cases', None):
        from oj.services import grade as oj_grade
        if not student_answer:
            oj_info = {'verdict': 'CE', 'passed': 0,
                       'total': len(question.test_cases), 'score_ratio': 0}
            is_correct = False
        else:
            r = oj_grade(student_answer, getattr(question, 'language', None) or 'python', question.test_cases)
            if r['supported']:
                is_correct = r['verdict'] == 'AC'
                oj_info = {'verdict': r['verdict'], 'passed': r['passed'], 'total': r['total'],
                           'score_ratio': round(r['passed'] / r['total'], 4) if r['total'] else 0}
    if is_correct is None:
        is_correct = _check_answer(question.type, student_answer, question.answer)

    pa = PracticeAnswer.query.filter_by(session_id=sess.id, question_id=question_id).first()
    if pa:
        pa.student_answer = student_answer
        pa.is_correct = is_correct
        pa.time_spent_sec = time_spent_sec
        pa.answered_at = utcnow()
    else:
        pa = PracticeAnswer(
            session_id=sess.id, question_id=question_id,
            student_answer=student_answer, is_correct=is_correct,
            time_spent_sec=time_spent_sec,
        )
        db.session.add(pa)

    # 统计练习会话
    existing_answers = PracticeAnswer.query.filter_by(session_id=sess.id).all()
    sess.correct_count = sum(1 for a in existing_answers if a.is_correct)
    sess.total_time_sec = sum((a.time_spent_sec or 0) for a in existing_answers)

    # 掌握度驱动：按本题判分结果更新其关联知识点掌握度（主观题不自动判分则跳过）
    if is_correct is not None:
        kp_ids = eng.kp_ids_of_question(question_id)
        if kp_ids:
            eng.update_mastery(user.id, kp_ids, 1.0 if is_correct else 0.0)

    # 自动收录错题（仅客观题）
    if is_correct is False:
        sync_wrong_from_answers(user.id, 'practice', sess.id,
                                 [(question_id, student_answer, question.answer)])
    db.session.commit()

    resp = {
        'is_correct': is_correct,
        'correct_answer': question.answer,
        'analysis': question.analysis,
        'knowledge': question.knowledge,
        'type': question.type,
    }
    if oj_info:
        resp['oj'] = oj_info
    return jsonify(resp)


@api_learning_bp.route('/learning/practice/<int:session_id>/submit', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_practice_submit(session_id):
    """结束练习会话：状态置 completed，写 StudyLog"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    sess = db.session.get(PracticeSession, session_id)
    if not sess or sess.user_id != user.id:
        return jsonify({'message': '练习会话不存在'}), 404

    sess.status = 'completed'
    sess.end_time = utcnow()

    # 补统计
    pa_list = PracticeAnswer.query.filter_by(session_id=sess.id).all()
    sess.correct_count = sum(1 for a in pa_list if a.is_correct)
    sess.total_time_sec = sum((a.time_spent_sec or 0) for a in pa_list)

    correct = sess.correct_count
    total = sess.questions_count or max(len(pa_list), 1)

    db.session.add(StudyLog(
        user_id=user.id, log_type='practice', reference_id=sess.id,
        total_questions=total, correct_count=correct,
        score_ratio=round(correct / total, 4) if total else 0,
        time_spent_sec=sess.total_time_sec or 0,
        studied_at=utcnow(),
    ))

    # 掌握度二次校准：按本次会话每题对错聚合到其 KP
    from collections import defaultdict
    kp_hits = defaultdict(lambda: [0, 0])  # kp_id -> [correct, total]
    for a in pa_list:
        if a.is_correct is None:
            continue
        for kp in eng.kp_ids_of_question(a.question_id):
            kp_hits[kp][1] += 1
            if a.is_correct:
                kp_hits[kp][0] += 1
    practiced_kps = set(kp_hits.keys())
    for kp, (c, t) in kp_hits.items():
        eng.update_mastery(user.id, [kp], c / t if t else 0)

    # 学习计划任务自动核销 + 打卡（旧题量式字段同步保留）
    newly_done = eng.auto_complete_tasks(user.id, kp_ids=practiced_kps,
                                         practiced_delta=total)
    eng.touch_checkin(user.id, minutes=round((sess.total_time_sec or 0) / 60),
                      tasks_delta=newly_done)

    # 学习计划进度（旧题量式字段，保留兼容）
    if sess.major_id:
        for plan in StudyPlan.query.filter_by(user_id=user.id, status='active').all():
            if plan.major_id and plan.major_id == sess.major_id:
                plan.completed_count = (plan.completed_count or 0) + total
                if plan.completed_count >= plan.target_count:
                    plan.status = 'completed'
                break

    db.session.commit()
    return jsonify({
        'message': '练习完成',
        'correct_count': correct,
        'total': total,
        'score_ratio': round(correct / total, 4) if total else 0,
        'total_time_sec': sess.total_time_sec,
    })


@api_learning_bp.route('/learning/practice/<int:session_id>', methods=['DELETE'])
def api_practice_delete(session_id):
    """删除练习会话"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    sess = db.session.get(PracticeSession, session_id)
    if not sess or sess.user_id != user.id:
        return jsonify({'message': '练习会话不存在'}), 404

    db.session.delete(sess)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_learning_bp.route('/learning/practice/history', methods=['GET'])
def api_practice_history():
    """练习历史列表"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    sessions = PracticeSession.query.filter_by(user_id=user.id) \
        .order_by(PracticeSession.start_time.desc()).limit(30).all()

    return jsonify([{
        'id': s.id, 'title': s.title, 'status': s.status,
        'questions_count': s.questions_count,
        'correct_count': s.correct_count,
        'total_time_sec': s.total_time_sec,
        'start_time': iso_local(s.start_time),
        'score_ratio': round(s.correct_count / s.questions_count, 4) if s.questions_count else 0,
        'major_id': s.major_id,
        'course_id': s.course_id,
    } for s in sessions])


# ── 学习计划（任务清单式：计划 = 多个可打卡的具体任务） ────────────

_TASK_TYPES = ('knowledge_point', 'resource', 'practice', 'custom')


def _task_to_dict(t):
    kp = t.knowledge_point
    return {
        'id': t.id, 'plan_id': t.plan_id, 'title': t.title,
        'task_type': t.task_type,
        'knowledge_point_id': t.knowledge_point_id,
        'knowledge_point_name': kp.name if kp else None,
        'resource_id': t.resource_id,
        'question_count': t.question_count,
        'progress_count': t.progress_count or 0,
        'auto_done': bool(t.auto_done),
        'estimated_minutes': t.estimated_minutes,
        'due_date': t.due_date.isoformat() if t.due_date else None,
        'overdue': bool(t.due_date and t.status != 'done' and t.due_date < local_today()),
        'status': t.status,
        'done_at': iso_local(t.done_at) if t.done_at else None,
        'order_num': t.order_num,
    }


def _plan_to_dict(p):
    tasks = p.tasks
    done = sum(1 for t in tasks if t.status == 'done')
    total = len(tasks)
    # 全部任务完成 → 计划自动标记完成（仅 active 状态流转，paused 不动）
    if total and done == total and p.status == 'active':
        p.status = 'completed'
    elif total and done < total and p.status == 'completed':
        p.status = 'active'
    # 时间进度（供前端时间轴双条对比）与落后预警：时间进度超出完成率 30 个百分点以上
    today = local_today()
    time_pct = None
    if p.start_date and p.end_date:
        span = (p.end_date - p.start_date).days
        if span > 0:
            time_pct = min(100, max(0, round((today - p.start_date).days / span * 100)))
    lagging = bool(p.status == 'active' and total and time_pct is not None
                   and time_pct - round(done / total * 100) > 30)
    # 近 14 天完成热力点（按任务 done_at 聚合）与逾期任务数
    heat = {}
    overdue_count = 0
    for t in tasks:
        if t.status == 'done' and t.done_at:
            d = local_date(t.done_at)
            if today - timedelta(days=13) <= d <= today:
                key = d.isoformat()
                heat[key] = heat.get(key, 0) + 1
        if t.due_date and t.status != 'done' and t.due_date < today:
            overdue_count += 1
    return {
        'id': p.id, 'title': p.title, 'description': p.description,
        'status': p.status,
        'tasks_done': done, 'tasks_total': total,
        'progress': round(done / total * 100, 1) if total else 0,
        'lagging': lagging,
        'time_pct': time_pct,
        'heat': heat,
        'overdue_count': overdue_count,
        'total_minutes': sum(t.estimated_minutes or 0 for t in tasks),
        'start_date': p.start_date.isoformat() if p.start_date else None,
        'end_date': p.end_date.isoformat() if p.end_date else None,
        'created_at': iso_local(p.created_at),
        'tasks': [_task_to_dict(t) for t in tasks],
    }


@api_learning_bp.route('/learning/plans', methods=['GET'])
def api_plan_list():
    """学习计划列表（含任务清单与打卡进度）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    plans = StudyPlan.query.filter_by(user_id=user.id) \
        .order_by(StudyPlan.created_at.desc()).all()
    out = []
    changed = False
    for p in plans:
        d = _plan_to_dict(p)  # 内部会按任务实况流转 plan.status
        if p in db.session.dirty:
            changed = True
        out.append(d)
    if changed:
        db.session.commit()
    return jsonify(out)


@api_learning_bp.route('/learning/plans/<int:plan_id>', methods=['GET'])
def api_plan_detail(plan_id):
    """单份计划详情（供 /learning/plan?plan=id 深链直达，字段与列表项一致）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    plan = db.session.get(StudyPlan, plan_id)
    # 计划是私人账本，别人的 id 与不存在同返回，不泄漏标题
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404
    d = _plan_to_dict(plan)
    if plan in db.session.dirty:
        db.session.commit()   # 同上：任务全完时这里会落库状态流转
    return jsonify(d)


@api_learning_bp.route('/learning/plans', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_plan_create():
    """创建学习计划（任务清单式：标题+日期+描述，任务后续添加/从路径导入）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    start_raw = data.get('start_date')
    try:
        start_date = date.fromisoformat(start_raw) if start_raw else local_today()
    except (ValueError, TypeError):
        start_date = local_today()
    end_date = None
    if data.get('end_date'):
        try:
            end_date = date.fromisoformat(data['end_date'])
        except (ValueError, TypeError):
            return jsonify({'message': '结束日期格式错误'}), 400

    plan = StudyPlan(
        user_id=user.id,
        title=(data.get('title') or '').strip() or '未命名计划',
        description=(data.get('description') or '').strip() or None,
        start_date=start_date,
        end_date=end_date,
        status='active',
    )
    db.session.add(plan)
    db.session.commit()
    return jsonify({'id': plan.id, 'message': '创建成功'})


@api_learning_bp.route('/learning/plans/<int:plan_id>', methods=['PUT'])
def api_plan_update(plan_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        title = (data.get('title') or '').strip()
        if not title:
            return jsonify({'message': '标题不能为空'}), 400
        plan.title = title
    if 'description' in data:
        plan.description = data['description']
    if data.get('start_date'):
        try:
            plan.start_date = date.fromisoformat(data['start_date'])
        except ValueError:
            return jsonify({'message': '开始日期格式错误'}), 400
    if 'end_date' in data:
        if data['end_date']:
            try:
                plan.end_date = date.fromisoformat(data['end_date'])
            except ValueError:
                return jsonify({'message': '结束日期格式错误'}), 400
        else:
            plan.end_date = None
    db.session.commit()
    return jsonify({'message': '已更新'})


@api_learning_bp.route('/learning/plans/<int:plan_id>/pause', methods=['POST'])
def api_plan_pause(plan_id):
    """暂停/恢复学习计划"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404

    if plan.status == 'active':
        plan.status = 'paused'
    elif plan.status == 'paused':
        tasks = plan.tasks
        done = sum(1 for t in tasks if t.status == 'done')
        plan.status = 'completed' if (tasks and done == len(tasks)) else 'active'
    db.session.commit()
    return jsonify({'status': plan.status})


@api_learning_bp.route('/learning/plans/<int:plan_id>', methods=['DELETE'])
def api_plan_delete(plan_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404

    # v7.9 之后 study_material/material_gen_job 反向指着计划与任务，不清会让 PG 直接
    # 拒绝删除（文档本身保留，只摘反链）
    from ai_service.material_queue import purge_refs
    purge_refs(plan_id, [t.id for t in (plan.tasks or [])])
    db.session.delete(plan)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_learning_bp.route('/learning/plans/<int:plan_id>/tasks', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_plan_task_create(plan_id):
    """给计划添加一个任务条目"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    task_type = data.get('task_type', 'custom')
    if not title:
        return jsonify({'message': '任务标题不能为空'}), 400
    if task_type not in _TASK_TYPES:
        return jsonify({'message': '无效的任务类型'}), 400

    kp_id = data.get('knowledge_point_id')
    res_id = data.get('resource_id')
    if kp_id and not db.session.get(KnowledgePoint, kp_id):
        return jsonify({'message': '知识点不存在'}), 404
    if res_id and not db.session.get(LearningResource, res_id):
        return jsonify({'message': '学习资源不存在'}), 404

    max_order = db.session.query(func.max(StudyPlanTask.order_num)) \
        .filter_by(plan_id=plan_id).scalar() or 0
    due_date = None
    if data.get('due_date'):
        try:
            due_date = date.fromisoformat(data['due_date'])
        except (ValueError, TypeError):
            return jsonify({'message': '截止日格式应为 YYYY-MM-DD'}), 400
    task = StudyPlanTask(
        plan_id=plan_id, title=title[:200], task_type=task_type,
        knowledge_point_id=kp_id, resource_id=res_id,
        question_count=data.get('question_count'),
        estimated_minutes=data.get('estimated_minutes'),
        due_date=due_date,
        order_num=max_order + 1,
    )
    db.session.add(task)
    if plan.status == 'completed':
        plan.status = 'active'  # 加了新任务，计划重新激活
    db.session.commit()
    return jsonify({'id': task.id, 'message': '任务已添加'})


@api_learning_bp.route('/learning/plans/<int:plan_id>/tasks/<int:task_id>', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_plan_task_update(plan_id, task_id):
    """任务更新：打卡 done ↔ pending（传 status），和/或编辑字段
    （title/estimated_minutes/question_count/due_date/knowledge_point_id）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404
    task = db.session.get(StudyPlanTask, task_id)
    if not task or task.plan_id != plan_id:
        return jsonify({'message': '任务不存在'}), 404

    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status is not None and status not in ('pending', 'done'):
        return jsonify({'message': 'status 须为 pending 或 done'}), 400

    if 'title' in data:
        new_title = (data.get('title') or '').strip()
        if not new_title:
            return jsonify({'message': '任务标题不能为空'}), 400
        task.title = new_title[:200]
    for field in ('estimated_minutes', 'question_count'):
        if field in data:
            try:
                setattr(task, field, int(data[field]) if data[field] is not None else None)
            except (TypeError, ValueError):
                return jsonify({'message': f'{field} 须为整数'}), 400
    if 'knowledge_point_id' in data:
        kp_id = data.get('knowledge_point_id')
        if kp_id and not db.session.get(KnowledgePoint, kp_id):
            return jsonify({'message': '知识点不存在'}), 404
        task.knowledge_point_id = kp_id or None
    if 'due_date' in data:
        if data['due_date']:
            try:
                task.due_date = date.fromisoformat(data['due_date'])
            except (ValueError, TypeError):
                return jsonify({'message': '截止日格式应为 YYYY-MM-DD'}), 400
        else:
            task.due_date = None

    if status is not None:
        task.status = status
        task.done_at = utcnow() if status == 'done' else None

    tasks = plan.tasks
    done = sum(1 for t in tasks if t.status == 'done')
    if tasks and done == len(tasks):
        if plan.status != 'paused':
            plan.status = 'completed'
    elif plan.status == 'completed':
        plan.status = 'active'

    db.session.commit()
    return jsonify({
        'message': ('已打卡' if status == 'done' else '已取消打卡') if status else '已更新',
        'status': task.status,
        'task': _task_to_dict(task),
        'tasks_done': done, 'tasks_total': len(tasks),
        'plan_status': plan.status,
    })


@api_learning_bp.route('/learning/plans/<int:plan_id>/tasks/<int:task_id>', methods=['DELETE'])
def api_plan_task_delete(plan_id, task_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404
    task = db.session.get(StudyPlanTask, task_id)
    if not task or task.plan_id != plan_id:
        return jsonify({'message': '任务不存在'}), 404

    from ai_service.material_queue import purge_refs
    purge_refs(task_ids=[task_id])           # 同上：该任务的作业行与成品反链
    db.session.delete(task)
    db.session.commit()
    return jsonify({'message': '任务已删除'})


@api_learning_bp.route('/learning/plans/from-path', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_plan_from_path():
    """从学习路径一键生成计划：每个路径节点生成一个任务（学知识点+建议刷题数）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    path_id = data.get('path_id')
    node_ids = data.get('node_ids')  # 可选：只导入勾选的节点
    if not path_id:
        return jsonify({'message': 'path_id 不能为空'}), 400

    path = db.session.get(LearningPath, path_id)
    if not path:
        return jsonify({'message': '学习路径不存在'}), 404

    nodes = [n for n in path.nodes
             if not node_ids or n.id in node_ids]
    if not nodes:
        return jsonify({'message': '该路径没有可导入的节点'}), 400

    plan = StudyPlan(
        user_id=user.id,
        title=(data.get('title') or '').strip() or f'路径计划：{path.title}'[:100],
        description=(data.get('description') or '').strip() or
        f'由学习路径「{path.title}」生成的任务清单，共 {len(nodes)} 个节点',
        start_date=local_today(),
        status='active',
    )
    db.session.add(plan)
    db.session.flush()  # 拿 plan.id

    for idx, n in enumerate(nodes, 1):
        # LearningPathNode 无 title 字段，标题由挂载对象动态决定（同 _node_to_dict）
        node_title = n.knowledge_point.name if (n.knowledge_point_id and n.knowledge_point) \
            else (n.chapter.name if n.chapter_id and n.chapter else '未命名节点')
        db.session.add(StudyPlanTask(
            plan_id=plan.id,
            title=f'{idx}. 学习 {node_title}'[:200],
            task_type='knowledge_point' if n.node_type == 'knowledge_point' else 'custom',
            knowledge_point_id=n.knowledge_point_id,
            question_count=5,  # 每节点建议配套刷 5 题
            estimated_minutes=n.estimated_minutes or 30,
            order_num=idx,
        ))
    db.session.commit()
    return jsonify({'id': plan.id, 'tasks_created': len(nodes), 'message': '已从路径生成计划'})


# ── 任务排序 / 批量采纳 / AI 拆计划 ────────────────────────────────
@api_learning_bp.route('/learning/plans/<int:plan_id>/tasks/reorder', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_plan_task_reorder(plan_id):
    """任务拖拽排序：按传入 id 顺序依次赋 order_num"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404
    data = request.get_json(silent=True) or {}
    task_ids = data.get('task_ids')
    if not isinstance(task_ids, list) or not task_ids:
        return jsonify({'message': '请提供 task_ids 列表'}), 400
    tmap = {t.id: t for t in plan.tasks}
    if any(tid not in tmap for tid in task_ids):
        return jsonify({'message': '存在不属于该计划的任务'}), 400
    for i, tid in enumerate(task_ids, 1):
        tmap[tid].order_num = i
    db.session.commit()
    return jsonify({'message': '顺序已更新'})


def _clean_task_item(raw):
    """校验/清洗一条任务建议，非法返回 None"""
    if not isinstance(raw, dict):
        return None
    title = str(raw.get('title') or '').strip()[:200]
    if not title:
        return None
    ttype = raw.get('task_type') if raw.get('task_type') in _TASK_TYPES else 'custom'
    kp_id = raw.get('knowledge_point_id')
    if kp_id and not db.session.get(KnowledgePoint, kp_id):
        kp_id = None
    if ttype == 'knowledge_point' and not kp_id:
        ttype = 'custom'
    due_date = None
    if raw.get('due_date'):
        try:
            due_date = date.fromisoformat(str(raw['due_date']))
        except (ValueError, TypeError):
            due_date = None
    def _int_or_none(v):
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    return {'title': title, 'task_type': ttype, 'knowledge_point_id': kp_id,
            'question_count': _int_or_none(raw.get('question_count')),
            'estimated_minutes': _int_or_none(raw.get('estimated_minutes')),
            'due_date': due_date}


@api_learning_bp.route('/learning/plans/<int:plan_id>/tasks/batch', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_plan_task_batch(plan_id):
    """批量添加任务（AI 拆解建议采纳）：单次上限 10 条，按标题去重

    notify=True（v7.18）：学习规划台「确认应用」最后一块提交时带上，应用成功后落
    一条站内通知。放在这里而不是建计划接口：此时任务已全部落库，通知里的条数是真的；
    手动新建计划不传该标志，不产噪音。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return jsonify({'message': '学习计划不存在'}), 404
    data = request.get_json(silent=True) or {}
    items = data.get('items')
    if not isinstance(items, list) or not items:
        return jsonify({'message': '请提供 items 任务列表'}), 400
    existing_titles = {t.title for t in plan.tasks}
    max_order = db.session.query(func.max(StudyPlanTask.order_num)) \
        .filter_by(plan_id=plan_id).scalar() or 0
    added = []
    for raw in items[:10]:
        item = _clean_task_item(raw)
        if not item or item['title'] in existing_titles:
            continue
        max_order += 1
        t = StudyPlanTask(plan_id=plan_id, order_num=max_order, **item)
        db.session.add(t)
        existing_titles.add(item['title'])
        added.append(t)
    if plan.status == 'completed' and added:
        plan.status = 'active'  # 加了新任务，计划重新激活
    db.session.commit()
    if data.get('notify') and added:
        _notify_plan_applied(user, plan)
    return jsonify({'added': len(added), 'tasks': [_task_to_dict(t) for t in added]})


def _notify_plan_applied(user, plan):
    """学习规划应用成功的站内通知（v7.18 需求 a）。

    非关键路径单独裹异常：通知写挂不能把已落库的计划报成「应用失败」（同 AI 出题那次教训）。
    related_type='plan' + related_id 让铃铛点下去直达那一份计划（深链 /learning/plan?plan=id）。"""
    try:
        create_notification(
            user.id, '学习规划已应用',
            f'《{plan.title}》已写入你的学习计划，共 {len(plan.tasks or [])} 个任务'
            f'（{plan.start_date} 起），可在「学习计划」页逐项开始。',
            type='success', related_type='plan', related_id=plan.id)
    except Exception:
        db.session.rollback()
        logger.exception('[learning] 学习规划应用通知创建失败 plan_id=%s', plan.id)


def _match_plan_kps(keyword_text, limit=15):
    """从目标文本分词模糊匹配候选知识点，返回 [(id, name)]"""
    words = [w for w in re.split(r'[\s,，、;；/。.:：()（）\[\]【】\-+]+', keyword_text or '')
             if len(w) >= 2][:10]
    found = {}
    for w in words:
        rows = KnowledgePoint.query.filter(
            KnowledgePoint.name.like(f'%{w}%'),
            KnowledgePoint.status == 'active').limit(8).all()
        for kp in rows:
            found[kp.id] = kp.name
        if len(found) >= limit:
            break
    return list(found.items())[:limit]


def _plan_rule_tasks(kp_pairs, days, base_date):
    """规则兜底拆解：匹配到知识点则按知识点均摊截止日，否则用通用五阶段里程碑"""
    tasks = []
    if kp_pairs:
        step = max(1, round(days / len(kp_pairs)))
        for i, (kid, name) in enumerate(kp_pairs[:8]):
            due = base_date + timedelta(days=min(days, (i + 1) * step) - 1)
            tasks.append({'title': f'掌握「{name}」并完成配套练习', 'task_type': 'knowledge_point',
                          'knowledge_point_id': kid, 'question_count': 5,
                          'estimated_minutes': 45, 'due_date': due.isoformat()})
    else:
        milestones = ['通览材料，梳理整体知识框架', '精学核心章节并完成配套题',
                      '专项刷题，巩固薄弱知识点', '整理错题与笔记，查漏补缺',
                      '综合模拟自测，复盘冲刺']
        n = len(milestones)
        for i, m in enumerate(milestones):
            due = base_date + timedelta(days=max(1, round((i + 1) * days / n)) - 1)
            tasks.append({'title': m, 'task_type': 'custom', 'estimated_minutes': 60,
                          'question_count': 10 if ('刷题' in m or '配套题' in m) else None,
                          'due_date': due.isoformat()})
    return tasks


@api_learning_bp.route('/learning/plans/ai-suggest-tasks', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_plan_ai_suggest_tasks():
    """AI 拆计划：目标文本→任务建议列表（前端勾选后经 tasks/batch 采纳）；
    AI 不可用时降级为规则拆解（知识点匹配或五阶段模板）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    desc = (data.get('description') or '').strip()
    goal = f'{title} {desc}'.strip()
    if not goal:
        return jsonify({'message': '请先填写计划标题或目标描述'}), 400
    try:
        start = date.fromisoformat(data['start_date']) if data.get('start_date') else local_today()
    except (ValueError, TypeError):
        start = local_today()
    days = 56  # 未选周期时默认按两个月（八周）拆解，预留知识图谱/知识点整理/预习复习的空间
    if data.get('end_date'):
        try:
            days = max(1, min((date.fromisoformat(data['end_date']) - start).days or 1, 365))
        except (ValueError, TypeError):
            pass

    kps = _match_plan_kps(goal)
    basis = f'目标：{goal[:200]}；周期 {days} 天'
    if kps:
        basis += '；匹配到候选知识点：' + '、'.join(n for _, n in kps[:10])
    else:
        basis += '；未匹配到题库知识点，按通用阶段模板拆解'

    source, tasks = 'rule', _plan_rule_tasks(kps, days, start)
    try:
        from ai_service.services import ai_suggest_plan_tasks
        kp_lines = '\n'.join(f'{i}|{n}' for i, n in kps)
        arr = ai_suggest_plan_tasks(db.session, goal, kp_lines, days, {i for i, _ in kps})
        n = len(arr)
        out = []
        for idx, it in enumerate(arr):
            due_day = it.pop('due_day', None) or max(1, min(round((idx + 1) * days / n), days))
            it['due_date'] = (start + timedelta(days=due_day - 1)).isoformat()
            out.append(it)
        if out:
            tasks, source = out, 'ai'
    except Exception:
        logger.exception('AI 拆计划失败，降级规则拆解')
    return jsonify({'basis': basis, 'tasks': tasks, 'source': source, 'days': days})


# ── 学习报告（聚合查询 StudyLog + Result + Competition） ──────────

def _report_overview_payload(user_id, days):
    """学习概览聚合（按 user_id 参数化，供本人/公开报告两种入口复用）"""
    cutoff = utcnow() - __import__('datetime').timedelta(days=days)

    # 练习/考试/竞赛聚合
    logs = StudyLog.query.filter_by(user_id=user_id).filter(StudyLog.studied_at >= cutoff).all()
    log_total = sum(l.total_questions for l in logs)
    log_correct = sum(l.correct_count for l in logs)

    # 错题统计
    wrong_total = WrongAnswerRecord.query.filter_by(user_id=user_id).count()
    wrong_unmastered = WrongAnswerRecord.query.filter_by(user_id=user_id, is_mastered=False).count()
    wrong_mastered = wrong_total - wrong_unmastered

    # 活跃学习计划
    active_plans = StudyPlan.query.filter_by(user_id=user_id, status='active').count()

    # 最近 7 天每日学习时长聚合（从 StudyLog 逐日求和）
    daily = db.session.query(
        func.date(StudyLog.studied_at).label('day'),
        func.sum(StudyLog.time_spent_sec).label('time_sec'),
        func.sum(StudyLog.total_questions).label('total'),
        func.sum(StudyLog.correct_count).label('correct'),
    ).filter(
        StudyLog.user_id == user_id,
        StudyLog.studied_at >= utcnow() - __import__('datetime').timedelta(days=7),
    ).group_by(func.date(StudyLog.studied_at)).all()

    daily_map = {str(r.day): {'time_sec': int(r.time_sec or 0),
                               'total': int(r.total or 0),
                               'correct': int(r.correct or 0)} for r in daily}

    return {
        'period_days': days,
        'total_questions': log_total,
        'correct_count': log_correct,
        'score_ratio': round(log_correct / log_total, 4) if log_total else 0,
        'total_time_sec': sum(l.time_spent_sec for l in logs),
        'sessions_count': len(logs),
        'wrong_total': wrong_total,
        'wrong_unmastered': wrong_unmastered,
        'wrong_mastered': wrong_mastered,
        'active_plans': active_plans,
        'daily': daily_map,
    }


def _report_daily_payload(user_id, days):
    """每日学习记录明细（按 user_id 参数化）"""
    cutoff = utcnow() - __import__('datetime').timedelta(days=days)

    logs = StudyLog.query.filter_by(user_id=user_id) \
        .filter(StudyLog.studied_at >= cutoff) \
        .order_by(StudyLog.studied_at.desc()).all()

    return [{
        'id': l.id, 'log_type': l.log_type, 'reference_id': l.reference_id,
        'total_questions': l.total_questions, 'correct_count': l.correct_count,
        'score_ratio': l.score_ratio, 'time_spent_sec': l.time_spent_sec,
        'studied_at': iso_local(l.studied_at),
    } for l in logs]


def _resolve_report_target(uid):
    """公开报告访问控制：本人直返；他人需 user.is_study_report_public=True。
    返回 (target_user, error_response)；error_response 非 None 时直接返回它。"""
    user = verify_token()
    if not user:
        return None, (jsonify({'message': '未登录'}), 401)
    if uid == user.id:
        return user, None
    target = db.session.get(User, uid)
    if not target:
        return None, (jsonify({'message': '用户不存在'}), 404)
    if not target.is_study_report_public:
        return None, (jsonify({'message': '该用户未公开学习报告'}), 403)
    return target, None


@api_learning_bp.route('/learning/report/overview', methods=['GET'])
def api_report_overview():
    """学习概览：最近 30 天聚合 + 统计指标"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    days = int(request.args.get('days', 30))
    return jsonify(_report_overview_payload(user.id, days))


@api_learning_bp.route('/learning/report/<int:uid>/overview', methods=['GET'])
def api_report_overview_public(uid):
    """查看指定用户的学习概览：本人或对方开启"学习报告公开"时可用"""
    target, err = _resolve_report_target(uid)
    if err:
        return err
    days = int(request.args.get('days', 30))
    return jsonify(_report_overview_payload(target.id, days))


@api_learning_bp.route('/learning/report/daily', methods=['GET'])
def api_report_daily():
    """最近 N 天的每日学习记录明细（含错题/练习详情）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    days = int(request.args.get('days', 30))
    return jsonify(_report_daily_payload(user.id, days))


@api_learning_bp.route('/learning/report/<int:uid>/daily', methods=['GET'])
def api_report_daily_public(uid):
    """查看指定用户的每日学习明细：本人或对方开启"学习报告公开"时可用"""
    target, err = _resolve_report_target(uid)
    if err:
        return err
    days = int(request.args.get('days', 30))
    return jsonify(_report_daily_payload(target.id, days))


# ── AI 答疑 ────────────────────────────────────────────────────────

# 答疑留痕复用窗口：窗口内同指纹直接回上次的解析，不再打 AI
ASK_REUSE_DAYS = 7


def _ask_fingerprint(uid, question_id, doubt, student_answer):
    """四元组指纹：换题/换问法/改作答都会 miss，不会把旧解析硬套到新问题上。"""
    raw = '|'.join(str(v or '') for v in (uid, question_id, doubt, student_answer))
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


@api_learning_bp.route('/learning/ask', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_learning_ask():
    """AI 答疑：题目 id（或题面）+ 学生疑问 → 解析，并留痕供短期内同问复用。

    v7.20 两处收口：① doubt 真正进 prompt（以前收下就丢，学生写不写疑问结果一样）；
    ② 解析落 `ai_ask_record`，同指纹 ASK_REUSE_DAYS 天内命中就回旧解——不扣额度也不重烧外呼。
    没 question_id 的「拍题提问」也不再回空字符串（旧代码那句 `if question_id else ''`）。
    `refresh=true` 跳过复用重生成：想换个思路再问一次的人，不该被自己的历史回答挡着。

    顺带不再下发 `question_answer`：错题本场景要看标准答案该走错题自己的字段，而这个端点没有
    错题归因那套 `_source_still_reanswerable` 答案门控，源仍可重答时它等于直接把答案送出去。
    """
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    question_id = data.get('question_id')
    question_content = str(data.get('question_content') or '').strip()[:4000]
    student_answer = str(data.get('student_answer') or '').strip()[:4000]
    doubt = str(data.get('doubt') or '').strip()[:2000]
    refresh = bool(data.get('refresh'))

    question = None
    if question_id:
        question = db.session.get(Question, question_id)
        if question:
            question_content = question.content

    if not question_content and not doubt:
        return jsonify({'message': '请提供题目内容或您的疑问'}), 400

    fp = _ask_fingerprint(user.id, question_id if question else None, doubt, student_answer)
    since = utcnow() - timedelta(days=ASK_REUSE_DAYS)
    hit = None if refresh else AiAskRecord.query.filter(
        AiAskRecord.user_id == user.id,
        AiAskRecord.fingerprint == fp,
        AiAskRecord.created_at >= since).order_by(AiAskRecord.id.desc()).first()
    if hit:
        # 命中不计一次 AI 调用，因此也不写 ai_usage_log：那张表是成本表，
        # 把复用记进去会把「治理页看到的调用数」虚抬成从未发生的外呼。
        hit.hit_count = (hit.hit_count or 1) + 1
        hit.last_hit_at = utcnow()
        db.session.commit()
        return jsonify({
            'analysis': hit.analysis,
            'question_content': hit.question_content or question_content,
            'source': 'cache', 'cached': True, 'ask_id': hit.id,
            'cached_at': iso_local(hit.created_at),
            'message': '七天内问过同样的问题，已回用上次的解析（未消耗今日额度）',
        })

    allowed, _quota = check_ai_quota(user)
    if not allowed:
        return jsonify({'message': '今日 AI 额度已用完，请明天再来或咨询教师调整配额'}), 429

    t0 = time.perf_counter()
    from ai_service.services import ai_generate_analysis
    try:
        analysis = ai_generate_analysis(
            db.session, question.id if question else None, student_answer,
            doubt=doubt, question_content=question_content)
    except ValueError as err:
        return jsonify({'message': str(err)}), 400
    except Exception:
        logger.exception('AI 答疑失败')
        log_ai_usage(user.id, 'ask', 'fail', (time.perf_counter() - t0) * 1000)
        db.session.commit()
        return jsonify({'message': 'AI 服务暂不可用，请稍后重试'}), 500

    charge_ai_quota(user)
    log_ai_usage(user.id, 'ask', 'success', (time.perf_counter() - t0) * 1000)
    rec = AiAskRecord(user_id=user.id, question_id=question.id if question else None,
                      question_content=question_content or None, doubt=doubt or None,
                      student_answer=student_answer or None, analysis=(analysis or '').strip()[:8000],
                      source='ai', fingerprint=fp)
    db.session.add(rec)
    db.session.commit()
    return jsonify({
        'analysis': rec.analysis,
        'question_content': question_content,
        'source': 'ai', 'cached': False, 'ask_id': rec.id,
    })


@api_learning_bp.route('/learning/ai-chat', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_learning_ai_chat():
    """AI 学习助手多轮对话（非流式）：前端只在流式失败时打到这里，v7.20 起这一轮也落库。

    为什么不再保持「无状态」：同一个聊天框里「正常那几轮能回看、兜底那一轮刷新就没」
    比整体无状态更难向用户解释；会话表既然已经有，补平这一条路径比加一层语义便宜。

    历史仍由前端持有（入参不变），服务端只补写**本轮**的用户句与助手句：不能把整段
    messages 重灌，否则一次回退就把已入库的旧消息重复存一遍。
    """
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    messages = data.get('messages')
    context = str(data.get('context') or '').strip()[:600]
    if not isinstance(messages, list):
        return jsonify({'message': '参数错误'}), 400

    # 只保留 user/assistant 两种角色的非空消息，内容截断防超长
    cleaned = [
        {'role': 'user' if m.get('role') == 'user' else 'assistant',
         'content': str(m.get('content') or '').strip()[:4000]}
        for m in messages
        if isinstance(m, dict) and m.get('role') in ('user', 'assistant')
        and str(m.get('content') or '').strip()
    ]
    if not cleaned or cleaned[-1]['role'] != 'user':
        return jsonify({'message': '请输入您的问题'}), 400

    allowed, _quota = check_ai_quota(user)
    if not allowed:
        return jsonify({'message': '今日 AI 额度已用完，请明天再来或咨询教师调整配额'}), 429

    # 会话归属：沿用前端带来的 conversation_id，没有则本轮首句建会话（与流式端点同一套语义）
    cid = data.get('conversation_id')
    conv = db.session.get(AiChatConversation, cid) if cid else None
    if conv and conv.user_id != user.id:
        return jsonify({'message': '会话不存在'}), 404
    if not conv:
        conv = AiChatConversation(user_id=user.id, title=cleaned[-1]['content'][:30],
                                  context=context[:60] or None)
        db.session.add(conv)
        db.session.flush()

    t0 = time.perf_counter()
    try:
        from ai_service.services import ai_chat_reply
        reply = ai_chat_reply(db.session, cleaned, context)
    except Exception:
        logger.exception('AI 学习助手对话失败')
        log_ai_usage(user.id, 'chat', 'fail', (time.perf_counter() - t0) * 1000)
        db.session.commit()
        return jsonify({'message': 'AI 服务暂不可用，请稍后重试'}), 500

    # 流式端点是「先把 user 句落库、再开始流」的，中途挂掉回到这里时本轮用户句已经在库里了，
    # 所以先看尾条：角色与内容都对得上就不重复补一条。不靠时间窗，靠内容，免得到点错位。
    last = sorted(conv.messages, key=lambda m: m.id)[-1] if conv.messages else None
    if not (last and last.role == 'user' and last.content == cleaned[-1]['content']):
        db.session.add(AiChatMessage(conversation_id=conv.id, role='user',
                                     content=cleaned[-1]['content']))
    charge_ai_quota(user)
    log_ai_usage(user.id, 'chat', 'success', (time.perf_counter() - t0) * 1000)
    db.session.add(AiChatMessage(conversation_id=conv.id, role='assistant',
                                 content=(reply or '')[:8000],
                                 degraded=str(reply or '').startswith('【AI 服务暂不可用')))
    conv.updated_at = utcnow()
    db.session.commit()
    return jsonify({'reply': reply, 'conversation_id': conv.id})


# ── 内部同步：考试结束后收录错题 ────────────────────────────────────
# 被 execution_routes.py 的 submit 流程调用
def sync_wrong_from_exam(user_id, exam_id, session_id=None):
    exam = db.session.get(Exam, exam_id)
    if not exam:
        return 0
    # v4.3 多次作答：优先同步本次交卷会话，否则取最近一次已交卷会话
    if session_id:
        session = db.session.get(ExamSession, session_id)
    else:
        session = ExamSession.query.filter_by(
            exam_id=exam_id, student_id=user_id, status='submitted').order_by(ExamSession.id.desc()).first()
    if not session:
        return 0
    qids = {a.question_id for a in Answer.query.filter_by(session_id=session.id).all()}
    answer_map = {q.id: q.answer for q in Question.query.filter(Question.id.in_(qids)).all()} if qids else {}
    wrong = [(a.question_id, a.student_answer, answer_map.get(a.question_id))
             for a in Answer.query.filter_by(session_id=session.id).all()
             if a.is_correct is False and a.question_id in answer_map]
    return sync_wrong_from_answers(user_id, 'exam', exam_id, wrong)


# ── 工具函数 ──────────────────────────────────────────────────────

def _source_still_reanswerable(user_id, source_type, source_id):
    """答案门控（v5.2）：该错题来源当前是否仍可重答。

    仍可重答时错题本暂隐正确答案/AI 归因，防「看答案再重交」：
    - homework：作业仍接收提交且本人提交未批改完成（GRADED 后禁止再交，门控解除）
    - exam：考试发布中未截止且剩余作答次数未用完
    其余来源（practice/competition 等无重答刷分通道）不门控。异常时保守不门控。
    """
    try:
        if source_type == 'homework':
            from homework.models import Homework, HomeworkSubmission, SubmissionStatusEnum
            hw = db.session.get(Homework, source_id)
            if not hw or not hw.accepts_submission:
                return False
            sub = HomeworkSubmission.query.filter_by(
                homework_id=hw.id, student_id=user_id).first()
            return sub is None or sub.status != SubmissionStatusEnum.GRADED
        if source_type == 'exam':
            exam = db.session.get(Exam, source_id)
            if not exam or exam.status != ExamStatusEnum.PUBLISHED:
                return False
            if exam.end_time and utcnow() > exam.end_time:
                return False
            es = ExamStudent.query.filter_by(exam_id=exam.id, student_id=user_id).first()
            max_allowed = (exam.max_attempts or 1) + (es.extra_attempts if es else 0)
            used = ExamSession.query.filter_by(exam_id=exam.id, student_id=user_id) \
                .filter(ExamSession.status.in_(['in_progress', 'submitted'])).count()
            return used < max_allowed
    except Exception:
        logger.warning('[learning] 答案门控判定异常 source=%s/%s', source_type, source_id,
                       exc_info=True)
    return False


def _wrong_record_to_dict(r, hide_answer=False, source_title=None):
    q = r.question
    return {
        'id': r.id, 'question_id': r.question_id,
        'question_content': q.content if q else None,
        'question_type': q.type if q else None,
        'knowledge': q.knowledge if q else None,
        'options': q.options if q else None,
        # v5.2 答案门控：来源仍可重答时不下发正确答案/AI 归因，前端据 answer_hidden 提示
        'correct_answer': None if hide_answer else r.correct_answer,
        'answer_hidden': bool(hide_answer),
        'wrong_answer': r.wrong_answer,
        'is_mastered': r.is_mastered,
        'wrong_count': r.wrong_count,
        'source_type': r.source_type, 'source_id': r.source_id,
        'source_title': source_title,   # v5.9 作业来源标题，用于回链
        'ai_analysis': None if hide_answer else r.ai_analysis,
        'ai_analyzed_at': iso_local(r.ai_analyzed_at) if r.ai_analyzed_at else None,
        'last_wrong_at': iso_local(r.last_wrong_at),
        'mastered_at': iso_local(r.mastered_at) if r.mastered_at else None,
    }


def _question_min_dict(q):
    return {
        'id': q.id,
        'content': q.content,
        'type': q.type,
        'options': q.options,
        'difficulty': q.difficulty,
        'knowledge': q.knowledge,
    }


# 客观题白名单：仅此四类可自动判对错，其余（主观/编程无 OJ）返回 None 走人工/自评链路
_OBJECTIVE_TYPES = ('single_choice', 'true_false', 'multiple_choice', 'fill_blank')


def _check_answer(q_type, student_answer, correct_answer):
    """客观题判分：返回 True/False；主观题返回 None（无法自动判对/错）。
    v5.26 起统一委托 exam_engine.check_objective，与考试/作业判分口径一致
    （多选提取字母+去重归一，脏格式存量答案不再误判），不另一套实现。"""
    if q_type not in _OBJECTIVE_TYPES:
        return None
    ok, _ratio = check_objective(q_type, student_answer, correct_answer)
    return ok


# ── 专业学习路径 + 知识图谱（一期 MVP） ─────────────────────────────

_EDGE_RELATION_TYPES = ('prerequisite', 'related', 'derived')
_RESOURCE_TYPES = ('text', 'video', 'exercise', 'external_link')
_PROGRESS_STATUSES = ('not_started', 'in_progress', 'mastered', 'skipped')


def _require_login():
    """登录校验（全民学习：自我学习模块不区分教师/学生角色，每个登录用户都可为自己学习）：
    返回 (user, None) 或 (None, error_response)"""
    user = verify_token()
    if not user:
        return None, (jsonify({'message': '请先登录'}), 401)
    return user, None


def _parse_plan_date(value):
    """解析前端 'YYYY-MM-DD' 计划日期；空值返回 None；非法值抛 ValueError"""
    if value in (None, ''):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _can_view_path(path, user_id, enrollment=None):
    """路径可见性：已发布全员可见；草稿/归档仅创建者本人或已选课者可见
    （学习路径是给自己学的个人规划，草稿不公开）"""
    if path.status == 'published' or path.creator_id == user_id:
        return True
    return enrollment is not None


def _enroll_creator(path, user_id):
    """创建路径后创建者自动加入（自己的学习路径无需再点「加入学习」）；幂等"""
    existing = UserPathEnrollment.query.filter_by(user_id=user_id, path_id=path.id).first()
    if existing:
        if existing.status == 'abandoned':
            existing.status = 'active'
        return existing
    first_node = path.nodes[0] if path.nodes else None
    enr = UserPathEnrollment(
        user_id=user_id, path_id=path.id,
        total_count=len(path.nodes),
        current_node_id=first_node.id if first_node else None,
    )
    db.session.add(enr)
    return enr


def _sync_enrollment_totals(path_id):
    """节点增删后同步所有选课记录的节点总数快照；已完成的选课因新增节点回到进行中"""
    total = db.session.query(func.count(LearningPathNode.id)).filter_by(path_id=path_id).scalar() or 0
    enrs = UserPathEnrollment.query.filter_by(path_id=path_id).all()
    for enr in enrs:
        enr.total_count = total
        if total > (enr.completed_count or 0) and enr.status == 'completed':
            enr.status = 'active'
            enr.completed_at = None


def _kp_to_dict(kp, with_chapter=True):
    d = {
        'id': kp.id, 'chapter_id': kp.chapter_id, 'name': kp.name,
        'description': kp.description, 'order_num': kp.order_num,
        'difficulty': kp.difficulty, 'status': kp.status,
    }
    if with_chapter and kp.chapter:
        d['chapter_name'] = kp.chapter.name
        d['course_id'] = kp.chapter.course_id
    return d


def _node_to_dict(n, progress=None):
    kp = n.knowledge_point
    chapter = n.chapter
    d = {
        'id': n.id, 'path_id': n.path_id, 'node_type': n.node_type,
        'knowledge_point_id': n.knowledge_point_id, 'chapter_id': n.chapter_id,
        'title': kp.name if kp else (chapter.name if chapter else '未命名节点'),
        'description': kp.description if kp else (chapter.description if chapter else None),
        'difficulty': kp.difficulty if kp else None,
        'order_num': n.order_num, 'role': n.role,
        'estimated_minutes': n.estimated_minutes,
        'notebook_id': n.notebook_id,
        'notebook_title': n.notebook.title if n.notebook else None,
        'progress_status': progress.status if progress else None,
    }
    return d


def _path_to_dict(p, enrollment=None, current_user_id=None):
    nodes = p.nodes
    d = {
        'id': p.id, 'major_id': p.major_id,
        'major_name': p.major.name if p.major else None,
        'title': p.title, 'description': p.description,
        'learning_goal': p.learning_goal,
        'start_date': p.start_date.isoformat() if p.start_date else None,
        'target_end_date': p.target_end_date.isoformat() if p.target_end_date else None,
        'target_hours': p.target_hours, 'difficulty': p.difficulty,
        'version': p.version, 'status': p.status,
        'creator_id': p.creator_id,
        'creator_name': p.creator.username if p.creator else None,
        'is_creator': bool(current_user_id and p.creator_id == current_user_id),
        'created_at': iso_local(p.created_at),
        'updated_at': iso_local(p.updated_at) if p.updated_at else None,
        'nodes_count': len(nodes),
        'total_minutes': sum(n.estimated_minutes or 0 for n in nodes),
    }
    if enrollment:
        total = enrollment.total_count or 0
        d['my_enrollment'] = {
            'id': enrollment.id, 'status': enrollment.status,
            'completed_count': enrollment.completed_count or 0,
            'total_count': total,
            'current_node_id': enrollment.current_node_id,
            'progress': round((enrollment.completed_count or 0) / total * 100, 1) if total else 0,
        }
    return d


# ── 知识点 CRUD（登录可读写，全民共建） ────────────────────────────

@api_learning_bp.route('/learning/knowledge-points', methods=['GET'])
def api_kp_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    chapter_id = request.args.get('chapter_id', type=int)
    major_id = request.args.get('major_id', type=int)
    show_all = request.args.get('all') == '1'  # 全民共建：含已下线知识点管理视图

    q = KnowledgePoint.query
    if chapter_id:
        q = q.filter(KnowledgePoint.chapter_id == chapter_id)
    elif major_id:
        q = q.join(Chapter, KnowledgePoint.chapter_id == Chapter.id) \
             .join(Course, Chapter.course_id == Course.id) \
             .filter(Course.major_id == major_id)
    if not show_all:
        q = q.filter(KnowledgePoint.status == 'active')

    kps = q.order_by(KnowledgePoint.chapter_id, KnowledgePoint.order_num, KnowledgePoint.id).all()
    return jsonify([_kp_to_dict(kp) for kp in kps])


@api_learning_bp.route('/learning/knowledge-points', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_kp_create():
    user, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    chapter_id = data.get('chapter_id')
    name = (data.get('name') or '').strip()
    if not chapter_id or not name:
        return jsonify({'message': '章节与知识点名称不能为空'}), 400
    if not db.session.get(Chapter, chapter_id):
        return jsonify({'message': '章节不存在'}), 404

    kp = KnowledgePoint(
        chapter_id=chapter_id, name=name[:80],
        description=(data.get('description') or '').strip() or None,
        order_num=int(data.get('order_num', 0) or 0),
        difficulty=data.get('difficulty', 'easy'),
    )
    db.session.add(kp)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'message': '该章节下已存在同名知识点'}), 400
    return jsonify({'id': kp.id, 'message': '创建成功'})


@api_learning_bp.route('/learning/knowledge-points/<int:kp_id>', methods=['PUT'])
def api_kp_update(kp_id):
    user, err = _require_login()
    if err:
        return err

    kp = db.session.get(KnowledgePoint, kp_id)
    if not kp:
        return jsonify({'message': '知识点不存在'}), 404

    data = request.get_json(silent=True) or {}
    for k in ('name', 'description', 'order_num', 'difficulty', 'status'):
        if k in data:
            setattr(kp, k, data[k])
    if 'chapter_id' in data and data['chapter_id']:
        if not db.session.get(Chapter, data['chapter_id']):
            return jsonify({'message': '目标章节不存在'}), 404
        kp.chapter_id = data['chapter_id']
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'message': '该章节下已存在同名知识点'}), 400
    return jsonify({'message': '已更新'})


@api_learning_bp.route('/learning/knowledge-points/<int:kp_id>', methods=['DELETE'])
def api_kp_delete(kp_id):
    user, err = _require_login()
    if err:
        return err

    kp = db.session.get(KnowledgePoint, kp_id)
    if not kp:
        return jsonify({'message': '知识点不存在'}), 404

    kp.status = 'deprecated'  # 软删，保留历史路径/图谱引用
    db.session.commit()
    return jsonify({'message': '已下线（软删除）'})


@api_learning_bp.route('/learning/knowledge-points/<int:kp_id>/questions', methods=['GET'])
def api_kp_questions(kp_id):
    """知识点关联题目列表（_question_min_dict 不含答案/解析，学生可安全查看）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    kp = db.session.get(KnowledgePoint, kp_id)
    if not kp:
        return jsonify({'message': '知识点不存在'}), 404
    return jsonify([_question_min_dict(q) for q in kp.questions])


@api_learning_bp.route('/learning/knowledge-points/<int:kp_id>/questions', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_kp_bind_questions(kp_id):
    """绑定题目到知识点（全量同步：question_ids 为最终关联集合）"""
    user, err = _require_login()
    if err:
        return err

    kp = db.session.get(KnowledgePoint, kp_id)
    if not kp:
        return jsonify({'message': '知识点不存在'}), 404

    data = request.get_json(silent=True) or {}
    qids = data.get('question_ids') or []
    if not isinstance(qids, list):
        return jsonify({'message': 'question_ids 须为数组'}), 400

    questions = Question.query.filter(Question.id.in_(qids)).all() if qids else []
    kp.questions = questions
    db.session.commit()
    return jsonify({'message': '已更新关联题目', 'count': len(questions)})


# ── 知识点关系边 CRUD（登录可读写，全民共建） ──────────────────────

@api_learning_bp.route('/learning/knowledge-edges', methods=['GET'])
def api_edge_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    major_id = request.args.get('major_id', type=int)
    q = KnowledgeEdge.query
    if major_id:
        q = q.join(KnowledgePoint, KnowledgeEdge.source_id == KnowledgePoint.id) \
             .join(Chapter, KnowledgePoint.chapter_id == Chapter.id) \
             .join(Course, Chapter.course_id == Course.id) \
             .filter(Course.major_id == major_id)

    edges = q.all()
    return jsonify([{
        'id': e.id, 'source_id': e.source_id, 'target_id': e.target_id,
        'source_name': e.source.name if e.source else None,
        'target_name': e.target.name if e.target else None,
        'relation_type': e.relation_type, 'weight': e.weight,
    } for e in edges])


@api_learning_bp.route('/learning/knowledge-edges', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_edge_create():
    user, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    source_id = data.get('source_id')
    target_id = data.get('target_id')
    relation_type = data.get('relation_type', 'prerequisite')
    if not source_id or not target_id:
        return jsonify({'message': 'source_id 与 target_id 不能为空'}), 400
    if source_id == target_id:
        return jsonify({'message': '不允许自环关系'}), 400
    if relation_type not in _EDGE_RELATION_TYPES:
        return jsonify({'message': '无效的关系类型'}), 400
    if not db.session.get(KnowledgePoint, source_id) or not db.session.get(KnowledgePoint, target_id):
        return jsonify({'message': '知识点不存在'}), 404

    edge = KnowledgeEdge(
        source_id=source_id, target_id=target_id,
        relation_type=relation_type,
        weight=float(data.get('weight', 1.0) or 1.0),
    )
    db.session.add(edge)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'message': '该关系已存在'}), 400
    return jsonify({'id': edge.id, 'message': '创建成功'})


@api_learning_bp.route('/learning/knowledge-edges/<int:edge_id>', methods=['DELETE'])
def api_edge_delete(edge_id):
    user, err = _require_login()
    if err:
        return err

    edge = db.session.get(KnowledgeEdge, edge_id)
    if not edge:
        return jsonify({'message': '关系不存在'}), 404
    db.session.delete(edge)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ── 学习路径 CRUD（登录可读写，全民共建） ──────────────────────────

@api_learning_bp.route('/learning/paths', methods=['GET'])
def api_path_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    major_id = request.args.get('major_id', type=int)
    status = request.args.get('status')

    q = LearningPath.query
    if major_id:
        q = q.filter(LearningPath.major_id == major_id)
    if status:
        q = q.filter(LearningPath.status == status)

    # 个人学习路径：已发布对所有人可见；草稿/归档仅创建者本人或已选课者可见
    enr_map = {e.path_id: e for e in UserPathEnrollment.query.filter_by(user_id=user.id).all()}
    visible = [LearningPath.status == 'published', LearningPath.creator_id == user.id]
    enrolled_ids = {pid for pid, e in enr_map.items() if e.status != 'abandoned'}
    if enrolled_ids:
        visible.append(LearningPath.id.in_(enrolled_ids))
    q = q.filter(or_(*visible))

    paths = q.order_by(LearningPath.created_at.desc()).all()
    return jsonify([_path_to_dict(p, enr_map.get(p.id), user.id) for p in paths])


@api_learning_bp.route('/learning/paths', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_path_create():
    user, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    major_id = data.get('major_id')
    title = (data.get('title') or '').strip()
    if not major_id or not title:
        return jsonify({'message': '专业与路径标题不能为空'}), 400
    if not db.session.get(Major, major_id):
        return jsonify({'message': '专业不存在'}), 404

    try:
        start_date = _parse_plan_date(data.get('start_date'))
        end_date = _parse_plan_date(data.get('target_end_date'))
    except ValueError:
        return jsonify({'message': '计划日期格式应为 YYYY-MM-DD'}), 400
    if start_date and end_date and end_date < start_date:
        return jsonify({'message': '计划完成日期不能早于开始日期'}), 400

    path = LearningPath(
        major_id=major_id, title=title[:100],
        description=(data.get('description') or '').strip() or None,
        learning_goal=(data.get('learning_goal') or '').strip() or None,
        start_date=start_date, target_end_date=end_date,
        target_hours=int(data.get('target_hours') or 0) or None,
        difficulty=data.get('difficulty', 'medium'),
        creator_id=user.id,
    )
    db.session.add(path)
    # 自己的学习路径：创建即加入
    db.session.flush()
    _enroll_creator(path, user.id)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'message': '同专业下已存在同名同版本路径'}), 400
    return jsonify({'id': path.id, 'message': '创建成功，已加入我的学习路径'})


@api_learning_bp.route('/learning/paths/ai-generate', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_path_ai_generate():
    """AI 生成路径骨架：按章节拆解知识点+依赖边+推荐顺序，落库为草稿路径（全民可用）"""
    user, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    major_id = data.get('major_id')
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip() or None
    learning_goal = (data.get('learning_goal') or '').strip() or None
    chapter_ids = data.get('chapter_ids')
    if not major_id or not title:
        return jsonify({'message': '专业与路径标题不能为空'}), 400
    if not isinstance(chapter_ids, list) or not chapter_ids:
        return jsonify({'message': '请至少选择一个章节'}), 400
    try:
        chapter_ids = [int(c) for c in chapter_ids]
    except (TypeError, ValueError):
        return jsonify({'message': '章节参数错误'}), 400
    try:
        start_date = _parse_plan_date(data.get('start_date'))
        end_date = _parse_plan_date(data.get('target_end_date'))
    except ValueError:
        return jsonify({'message': '计划日期格式应为 YYYY-MM-DD'}), 400
    if start_date and end_date and end_date < start_date:
        return jsonify({'message': '计划完成日期不能早于开始日期'}), 400

    try:
        from ai_service.services import ai_generate_path_skeleton
        path, stats = ai_generate_path_skeleton(
            db.session, major_id, title[:100], chapter_ids,
            description=description, creator_id=user.id,
            learning_goal=learning_goal,
            start_date=start_date, target_end_date=end_date,
        )
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    except Exception:
        logger.exception('AI 生成路径骨架失败')
        return jsonify({'message': 'AI 生成失败，请稍后重试'}), 500

    # 自己的学习路径：生成后自动加入
    _enroll_creator(path, user.id)
    db.session.commit()

    return jsonify({
        'id': path.id, 'title': path.title,
        'kp_created': stats['kp_created'], 'kp_existing': stats['kp_existing'],
        'edges_created': stats['edges_created'], 'nodes_created': stats['nodes_created'],
        'message': 'AI 生成完成，已创建草稿路径',
    })


# 自我学习「自由主题」命名空间容器：知识点/路径的 FK 硬约束需要一个专业+课程+章节作落点。
# 该专业由自我学习子系统在服务端代建，并对教师/学生一视同仁（不分角色），
# 同时从考试侧专业/课程列表过滤掉（见 major_routes/course_routes），以免污染考试目录。
SELF_LEARN_MAJOR_NAME = '自由学习空间'


def _get_or_create_topic_container(topic_title):
    """为自由主题取得/创建「专业→课程→章节」命名空间容器（幂等、服务端代建，无角色门禁）。"""
    major = Major.query.filter_by(name=SELF_LEARN_MAJOR_NAME).first()
    if not major:
        major = Major(name=SELF_LEARN_MAJOR_NAME[:50],
                      description='自我学习：用户自定义主题自动生成的学习空间')
        db.session.add(major)
        db.session.flush()
    course_name = (topic_title or '自由主题')[:50]
    course = Course.query.filter_by(major_id=major.id, name=course_name).first()
    if not course:
        course = Course(name=course_name, major_id=major.id)
        db.session.add(course)
        db.session.flush()
    chapter = Chapter.query.filter_by(course_id=course.id, name='核心知识体系').first()
    if not chapter:
        chapter = Chapter(name='核心知识体系', course_id=course.id, order_num=1)
        db.session.add(chapter)
        db.session.flush()
    return major, course, chapter


@api_learning_bp.route('/learning/topics/plan-full', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_topic_plan_full():
    """自由主题一键闭环：任意主题→服务端建命名空间容器→AI 生成学习路径+知识点+依赖边（知识图谱）
    →据这些真实知识点建学习计划+任务（任务绑定知识点→打通掌握度/错题本）。全民可用，不分教师/学生。"""
    user, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    desc = (data.get('description') or '').strip()
    if not title and not desc:
        return jsonify({'message': '请填写学习主题或描述'}), 400
    topic = (title or desc)[:60]
    desc = desc or topic

    try:
        start = date.fromisoformat(data['start_date']) if data.get('start_date') else local_today()
    except (ValueError, TypeError):
        start = local_today()
    end = None
    if data.get('end_date'):
        try:
            end = date.fromisoformat(data['end_date'])
        except (ValueError, TypeError):
            return jsonify({'message': '结束日期格式错误'}), 400
    if end and end < start:
        return jsonify({'message': '结束日期不能早于开始日期'}), 400
    if not end:
        end = start + timedelta(days=56)  # 未选周期默认两个月（八周）
    days = max(1, (end - start).days)

    # 1) 命名空间容器（专业→课程→章节）
    major, course, chapter = _get_or_create_topic_container(topic)

    # 2) 复用现成引擎生成路径骨架（知识点+依赖边+节点），AI 不可用则报错降级
    try:
        from ai_service.services import ai_generate_path_skeleton
        path, stats = ai_generate_path_skeleton(
            db.session, major.id, topic, [chapter.id],
            description=desc, creator_id=user.id, learning_goal=desc,
            start_date=start, target_end_date=end,
        )
    except Exception:
        logger.exception('自由主题闭环：AI 生成路径骨架失败')
        return jsonify({'message': 'AI 生成失败，请稍后重试，或改用“基于已有课程”模式'}), 502

    _enroll_creator(path, user.id)   # 自己的路径：生成即加入

    # 3) 学习计划：任务直接绑定骨架生成的知识点，与路径节点/图谱/掌握度同源
    plan = StudyPlan(user_id=user.id, title=topic, description=desc,
                     start_date=start, end_date=end, status='active')
    db.session.add(plan)
    db.session.flush()
    nodes = [n for n in path.nodes if n.node_type == 'knowledge_point' and n.knowledge_point_id]
    step = max(1, round(days / len(nodes))) if nodes else days
    order = 0
    for i, n in enumerate(nodes):
        kp = db.session.get(KnowledgePoint, n.knowledge_point_id)
        if not kp:
            continue
        order += 1
        due = start + timedelta(days=min(days, (i + 1) * step) - 1)
        db.session.add(StudyPlanTask(
            plan_id=plan.id, order_num=order,
            title=f'掌握「{kp.name}」并完成配套练习', task_type='knowledge_point',
            knowledge_point_id=kp.id, estimated_minutes=n.estimated_minutes or 45,
            question_count=5, due_date=due))
    path_id, plan_id, tasks_total = path.id, plan.id, order
    db.session.commit()

    # v7.18 需求 a：这类一键闭环要等 AI 30–60 秒，用户很可能已切页/刷新，
    # 仅靠当场 ElMessage 根本看不到；异常单独裹，不让通知写挂把已成功的生成报成失败
    try:
        create_notification(
            user.id, '学习规划已应用',
            f'主题《{topic}》已形成为你的学习计划：{tasks_total} 个任务，'
            f'同时生成学习路径与知识图谱（{stats["kp_created"] + stats["kp_existing"]} 个知识点'
            f'/{stats["edges_created"]} 条关联）。',
            type='success', related_type='plan', related_id=plan_id)
    except Exception:
        db.session.rollback()
        logger.exception('[learning] 自由主题闭环应用通知创建失败 plan_id=%s', plan_id)

    return jsonify({
        'path_id': path_id, 'plan_id': plan_id, 'course_id': course.id,
        'kp_created': stats['kp_created'], 'kp_existing': stats['kp_existing'],
        'edges_created': stats['edges_created'], 'nodes_created': stats['nodes_created'],
        'tasks_total': tasks_total,
        'graph_url': f'/learning/graph?path_id={path_id}',
        'message': (f'已闭环生成：学习路径 + 知识图谱（{stats["kp_created"] + stats["kp_existing"]} 个知识点'
                    f'/{stats["edges_created"]} 条关联）+ 学习计划（{tasks_total} 个任务）'),
    })


# ── v7.9 批量讲义：一条计划任务一份详细文档（后台队列，不同步等 AI）──

def _get_own_plan(user, plan_id):
    plan = db.session.get(StudyPlan, plan_id)
    if not plan or plan.user_id != user.id:
        return None, (jsonify({'message': '学习计划不存在'}), 404)
    return plan, None


@api_learning_bp.route('/learning/plans/<int:plan_id>/materials/batch', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_batch(plan_id):
    """为计划的每条任务投一份文档生成作业，立即返回 batch_id 由前端轮询进度。

    不在请求里做 AI 调用：8 条任务×单次 4000 token 输出，同步必然超过前端/网关超时。
    额度只做「今日完全用尽」拦截，不够跑完整批时照收——未跑的作业留在 pending，
    次日额度惰性重置后自动续跑，比拒绝受理对用户更有利。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    plan, err = _get_own_plan(user, plan_id)
    if err:
        return err
    if not (plan.tasks or []):
        return jsonify({'message': '该计划还没有任务条目，无需生成文档'}), 400

    allowed, _quota = check_ai_quota(user)
    if not allowed:
        return jsonify({'message': '今日 AI 额度已用完，请明天再来或咨询教师调整配额'}), 429

    data = request.get_json(silent=True) or {}
    force = bool(data.get('force'))

    from ai_service import material_queue as mq
    from ai_service.services import MATERIAL_TEMPLATES
    kind = str(data.get('kind') or mq.DEFAULT_KIND)
    if kind not in MATERIAL_TEMPLATES:
        # 形态传错属于调用方 bug，静默换成别的形态会让用户拿到不看的东西
        return jsonify({'message': '未知文档形态：' + kind,
                        'kinds': sorted(MATERIAL_TEMPLATES)}), 400
    batch_id, queued, skipped = mq.enqueue(user, plan, kind=kind, force=force)
    name = mq.kind_name(kind)
    if not queued:
        # 上一批还在后台跑时（pending/running），告诉前端「正在生成」而不是「已生成」，
        # 否则用户以为文档丢了、还会误点「强制重做」白花额度
        from database.models import MaterialGenJob
        waiting = db.session.query(MaterialGenJob.id).filter(
            MaterialGenJob.plan_id == plan.id, MaterialGenJob.kind == kind,
            MaterialGenJob.status.in_([mq.PENDING, mq.RUNNING])).count()
        # 只挡同形态：已有讲义不该拦住生成教案（v7.18 需求 c），文案得把「哪一形态」说清；
        # 全部在排队时（后台还没跑完）也不能说「已生成」，否则用户以为文档丢了
        return jsonify({'message': f'每条任务的「{name}」都已生成或正在后台生成，无需重复提交；'
                                   f'如需重新请确认强制重做，换其他形态会另起一份、不动已有文档',
                        'batch_id': batch_id, 'queued': 0, 'skipped': skipped,
                        'waiting': waiting, 'kind': kind, 'kind_name': name}), 200
    mq.wake()
    quota = get_quota_info(user)
    need, remain = queued, quota.get('remaining')
    note = (None if remain is None or remain >= need
            else f'今日剩余 AI 额度 {remain} 次，不足 {need} 份，未跑完的部分将在次日自动续跑')
    return jsonify({'batch_id': batch_id, 'queued': queued, 'skipped': skipped,
                    'total_tasks': len(plan.tasks), 'kind': kind, 'kind_name': name,
                    'quota_remaining': remain, 'note': note,
                    'message': f'已受理 {queued} 份「{name}」生成，后台逐份进行中'}), 202


@api_learning_bp.route('/learning/material-jobs/<string:batch_id>', methods=['GET'])
def api_material_batch_progress(batch_id):
    """批次进度轮询：{total, pending, running, done, failed, items}。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    from ai_service.material_queue import batch_info
    info = batch_info(batch_id, user.id)
    info['finished'] = (info['total'] == 0
                        or (info['pending'] == 0 and info['running'] == 0))
    return jsonify(info)


@api_learning_bp.route('/learning/material-jobs/<string:batch_id>/retry', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_batch_retry(batch_id):
    """重试批内失败项（超限终态不自动复活，靠这里人工重放）。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    from ai_service.material_queue import retry_failed
    n = retry_failed(batch_id, user.id)
    return jsonify({'retried': n, 'message': f'已重投 {n} 份失败作业' if n else '没有失败项'})


@api_learning_bp.route('/learning/plans/<int:plan_id>/materials', methods=['GET'])
def api_plan_materials(plan_id):
    """本计划已产出的文档清单（计划页就地列出，不必去资料库翻）。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    plan, err = _get_own_plan(user, plan_id)
    if err:
        return err
    from ai_service.material_queue import plan_documents
    mats = plan_documents(plan.id, user.id)
    task_titles = {t.id: t.title for t in (plan.tasks or [])}
    items = []
    for m in mats:
        d = _material_to_dict(m, current_user_id=user.id)
        d['task_title'] = task_titles.get(m.task_id)
        items.append(d)
    return jsonify({'items': items, 'total': len(items)})


@api_learning_bp.route('/learning/paths/<int:path_id>', methods=['GET'])
def api_path_detail(path_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    path = db.session.get(LearningPath, path_id)
    if not path:
        return jsonify({'message': '学习路径不存在'}), 404

    enrollment = UserPathEnrollment.query.filter_by(user_id=user.id, path_id=path_id).first()
    # 个人学习路径：草稿/归档仅创建者本人或已选课者可见
    if not _can_view_path(path, user.id, enrollment):
        return jsonify({'message': '该路径未公开，无法查看'}), 403

    progs = {p.node_id: p for p in UserNodeProgress.query.filter_by(user_id=user.id, path_id=path_id).all()}
    d = _path_to_dict(path, enrollment, user.id)
    d['nodes'] = [_node_to_dict(n, progs.get(n.id)) for n in path.nodes]
    return jsonify(d)


@api_learning_bp.route('/learning/paths/<int:path_id>', methods=['PUT'])
def api_path_update(path_id):
    user, err = _require_login()
    if err:
        return err

    path = db.session.get(LearningPath, path_id)
    if not path:
        return jsonify({'message': '学习路径不存在'}), 404
    if path.creator_id != user.id:
        return jsonify({'message': '只有路径创建者可以修改'}), 403

    data = request.get_json(silent=True) or {}
    for k in ('title', 'description', 'learning_goal', 'target_hours', 'difficulty'):
        if k in data:
            setattr(path, k, data[k])
    # 计划周期（校验格式与先后顺序）
    if 'start_date' in data or 'target_end_date' in data:
        try:
            start_date = _parse_plan_date(data.get('start_date', path.start_date))
            end_date = _parse_plan_date(data.get('target_end_date', path.target_end_date))
        except ValueError:
            return jsonify({'message': '计划日期格式应为 YYYY-MM-DD'}), 400
        if start_date and end_date and end_date < start_date:
            return jsonify({'message': '计划完成日期不能早于开始日期'}), 400
        path.start_date = start_date
        path.target_end_date = end_date

    # 状态流转：published → draft 禁止（会破坏已选课学生的可见性）
    if 'status' in data:
        new_status = data['status']
        allowed = {'draft': {'published', 'archived'},
                   'published': {'draft', 'archived'},
                   'archived': {'published', 'draft'}}
        if new_status not in ('draft', 'published', 'archived'):
            return jsonify({'message': '无效的状态'}), 400
        if new_status == 'draft' and path.status == 'published':
            return jsonify({'message': '已发布路径不能退回草稿，请改为归档'}), 400
        if new_status == 'published' and len(path.nodes) == 0:
            return jsonify({'message': '发布前请先添加至少一个节点'}), 400
        if new_status in allowed.get(path.status, set()):
            path.status = new_status

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'message': '同专业下已存在同名同版本路径'}), 400
    return jsonify({'message': '已更新', 'status': path.status})


@api_learning_bp.route('/learning/paths/<int:path_id>', methods=['DELETE'])
def api_path_delete(path_id):
    user, err = _require_login()
    if err:
        return err

    path = db.session.get(LearningPath, path_id)
    if not path:
        return jsonify({'message': '学习路径不存在'}), 404
    if path.creator_id != user.id:
        return jsonify({'message': '只有路径创建者可以删除'}), 403

    if path.status == 'draft':
        # 草稿可硬删（防御性清理进度/选课，避免孤儿行）
        UserNodeProgress.query.filter_by(path_id=path_id).delete()
        UserPathEnrollment.query.filter_by(path_id=path_id).delete()
        db.session.delete(path)
        db.session.commit()
        return jsonify({'message': '草稿已删除'})
    # 已发布/归档路径不可删（用户进度挂在上面），转为归档
    path.status = 'archived'
    db.session.commit()
    return jsonify({'message': '已发布路径不可删除，已转为归档'})


# ── 路径节点 CRUD ──────────────────────────────────────────────────

@api_learning_bp.route('/learning/paths/<int:path_id>/nodes', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_node_create(path_id):
    user, err = _require_login()
    if err:
        return err

    path = db.session.get(LearningPath, path_id)
    if not path:
        return jsonify({'message': '学习路径不存在'}), 404
    if path.creator_id != user.id:
        return jsonify({'message': '只有路径创建者可以管理节点'}), 403

    data = request.get_json(silent=True) or {}
    node_type = data.get('node_type', 'knowledge_point')
    kp_id = data.get('knowledge_point_id')
    chapter_id = data.get('chapter_id')

    if node_type == 'knowledge_point':
        if not kp_id or not db.session.get(KnowledgePoint, kp_id):
            return jsonify({'message': '知识点不存在'}), 404
        chapter_id = None
    elif node_type == 'chapter':
        if not chapter_id or not db.session.get(Chapter, chapter_id):
            return jsonify({'message': '章节不存在'}), 404
        kp_id = None
    else:
        return jsonify({'message': '无效的节点类型'}), 400

    notebook_id = data.get('notebook_id')
    if notebook_id and not db.session.get(Notebook, notebook_id):
        return jsonify({'message': '笔记本不存在'}), 404

    max_order = db.session.query(func.max(LearningPathNode.order_num)) \
        .filter_by(path_id=path_id).scalar() or 0
    node = LearningPathNode(
        path_id=path_id, node_type=node_type,
        knowledge_point_id=kp_id, chapter_id=chapter_id,
        order_num=max_order + 1,
        role=data.get('role', 'core'),
        estimated_minutes=int(data.get('estimated_minutes', 30) or 30),
        notebook_id=notebook_id,
    )
    db.session.add(node)
    db.session.flush()
    _sync_enrollment_totals(path_id)
    db.session.commit()
    return jsonify({'id': node.id, 'order_num': node.order_num, 'message': '已添加节点'})


@api_learning_bp.route('/learning/paths/<int:path_id>/nodes/<int:node_id>', methods=['PUT'])
def api_node_update(path_id, node_id):
    user, err = _require_login()
    if err:
        return err

    path = db.session.get(LearningPath, path_id)
    if not path:
        return jsonify({'message': '学习路径不存在'}), 404
    if path.creator_id != user.id:
        return jsonify({'message': '只有路径创建者可以管理节点'}), 403
    node = db.session.get(LearningPathNode, node_id)
    if not node or node.path_id != path_id:
        return jsonify({'message': '节点不存在'}), 404

    data = request.get_json(silent=True) or {}
    for k in ('role', 'estimated_minutes', 'node_type'):
        if k in data:
            setattr(node, k, data[k])
    if 'knowledge_point_id' in data:
        if data['knowledge_point_id'] and not db.session.get(KnowledgePoint, data['knowledge_point_id']):
            return jsonify({'message': '知识点不存在'}), 404
        node.knowledge_point_id = data['knowledge_point_id']
    if 'chapter_id' in data:
        if data['chapter_id'] and not db.session.get(Chapter, data['chapter_id']):
            return jsonify({'message': '章节不存在'}), 404
        node.chapter_id = data['chapter_id']
    if 'notebook_id' in data:
        if data['notebook_id'] and not db.session.get(Notebook, data['notebook_id']):
            return jsonify({'message': '笔记本不存在'}), 404
        node.notebook_id = data['notebook_id']
    if not node.knowledge_point_id and not node.chapter_id:
        return jsonify({'message': '节点必须挂知识点或章节'}), 400

    # 位置调整：先置负数临时值再落最终值（规避顺序号唯一约束的换位冲突）
    if 'order_num' in data:
        try:
            new_pos = max(int(data['order_num']), 1)
        except (TypeError, ValueError):
            return jsonify({'message': '无效的顺序号'}), 400
        siblings = [n for n in path.nodes if n.id != node_id]
        new_pos = min(new_pos, len(siblings) + 1)
        siblings.insert(new_pos - 1, node)
        for i, n in enumerate(siblings):
            n.order_num = -(i + 1)
        db.session.flush()
        for i, n in enumerate(siblings):
            n.order_num = i + 1

    db.session.commit()
    return jsonify({'message': '已更新'})


@api_learning_bp.route('/learning/paths/<int:path_id>/nodes/<int:node_id>', methods=['DELETE'])
def api_node_delete(path_id, node_id):
    user, err = _require_login()
    if err:
        return err

    path = db.session.get(LearningPath, path_id)
    if not path:
        return jsonify({'message': '学习路径不存在'}), 404
    if path.creator_id != user.id:
        return jsonify({'message': '只有路径创建者可以管理节点'}), 403
    node = db.session.get(LearningPathNode, node_id)
    if not node or node.path_id != path_id:
        return jsonify({'message': '节点不存在'}), 404

    if path.status != 'draft':
        # 已发布路径节点上有用户进度，禁止直接删（防破坏进度）；先归档再调整
        return jsonify({'message': '已发布路径不可删除节点，请先归档'}), 400

    UserNodeProgress.query.filter_by(node_id=node_id).delete()
    db.session.delete(node)
    db.session.flush()
    _sync_enrollment_totals(path_id)
    db.session.commit()
    return jsonify({'message': '节点已删除'})


# ── 用户选课与节点进度 ─────────────────────────────────────────────

@api_learning_bp.route('/learning/paths/enrollments/mine', methods=['GET'])
def api_my_enrollments():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    enrs = UserPathEnrollment.query.filter_by(user_id=user.id) \
        .order_by(UserPathEnrollment.enrolled_at.desc()).all()
    out = []
    for e in enrs:
        if not e.path:
            continue
        d = _path_to_dict(e.path, e, user.id)
        d['enrollment_id'] = e.id
        d['my_enrollment'] = {
            'status': e.status,
            'completed_count': e.completed_count or 0,
            'total_count': e.total_count or 0,
            'current_node_id': e.current_node_id,
            'enrolled_at': iso_local(e.enrolled_at),
        }
        out.append(d)
    return jsonify(out)


@api_learning_bp.route('/learning/paths/<int:path_id>/enrollments', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_path_enroll(path_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    path = db.session.get(LearningPath, path_id)
    if not path:
        return jsonify({'message': '学习路径不存在'}), 404
    # 未发布路径仅创建者本人可加入（自己的草稿随时可以学）
    if path.status != 'published' and path.creator_id != user.id:
        return jsonify({'message': '该路径未发布，暂不可加入'}), 400

    existing = UserPathEnrollment.query.filter_by(user_id=user.id, path_id=path_id).first()
    if existing:
        if existing.status == 'abandoned':
            existing.status = 'active'
            db.session.commit()
            return jsonify({'id': existing.id, 'message': '已重新加入'})
        return jsonify({'id': existing.id, 'message': '已加入该路径', 'idempotent': True})

    enr = _enroll_creator(path, user.id)
    db.session.commit()
    return jsonify({'id': enr.id, 'message': '加入成功'})


@api_learning_bp.route('/learning/paths/<int:path_id>/abandon', methods=['POST'])
def api_path_abandon(path_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    enr = UserPathEnrollment.query.filter_by(user_id=user.id, path_id=path_id).first()
    if not enr:
        return jsonify({'message': '未加入该路径'}), 404
    enr.status = 'abandoned'
    db.session.commit()
    return jsonify({'message': '已退出该路径'})


@api_learning_bp.route('/learning/enrollments/<int:eid>/progress', methods=['GET'])
def api_enrollment_progress(eid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    enr = db.session.get(UserPathEnrollment, eid)
    if not enr or enr.user_id != user.id:
        return jsonify({'message': '选课记录不存在'}), 404

    progs = {p.node_id: p for p in
             UserNodeProgress.query.filter_by(user_id=user.id, path_id=enr.path_id).all()}
    nodes = LearningPathNode.query.filter_by(path_id=enr.path_id) \
        .order_by(LearningPathNode.order_num).all()

    return jsonify({
        'enrollment': {
            'id': enr.id, 'path_id': enr.path_id, 'status': enr.status,
            'completed_count': enr.completed_count or 0,
            'total_count': enr.total_count or 0,
            'current_node_id': enr.current_node_id,
            'enrolled_at': iso_local(enr.enrolled_at),
        },
        'nodes': [_node_to_dict(n, progs.get(n.id)) for n in nodes],
    })


@api_learning_bp.route('/learning/enrollments/<int:eid>/nodes/<int:node_id>/progress', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_node_progress(eid, node_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    enr = db.session.get(UserPathEnrollment, eid)
    if not enr or enr.user_id != user.id:
        return jsonify({'message': '选课记录不存在'}), 404
    node = db.session.get(LearningPathNode, node_id)
    if not node or node.path_id != enr.path_id:
        return jsonify({'message': '节点不属于该学习路径'}), 400

    data = request.get_json(silent=True) or {}
    status = data.get('status', '')
    if status not in _PROGRESS_STATUSES:
        return jsonify({'message': '无效的节点状态'}), 400
    try:
        time_spent = max(int(data.get('time_spent_sec', 0) or 0), 0)
    except (TypeError, ValueError):
        time_spent = 0

    _apply_node_status(user, enr, node, status, time_spent)
    db.session.commit()
    return jsonify({
        'message': '进度已更新',
        'node_status': status,
        'completed_count': enr.completed_count,
        'total_count': enr.total_count,
        'current_node_id': enr.current_node_id,
        'enrollment_status': enr.status,
    })


def _apply_node_status(user, enr, node, status, time_spent=0):
    """节点状态流转核心（供手动进度更新与小测通过自动置掌握共用）：
    写 UserNodeProgress、重算选课进度与 current/completed 状态；
    status=mastered 时联动知识点掌握度抬升、计划任务自动核销与打卡。不 commit。
    """
    now = utcnow()
    prog = UserNodeProgress.query.filter_by(user_id=user.id, node_id=node.id).first()
    if not prog:
        prog = UserNodeProgress(user_id=user.id, path_id=enr.path_id, node_id=node.id)
        db.session.add(prog)
    prog.status = status
    if status == 'in_progress':
        prog.started_at = prog.started_at or now
    elif status == 'mastered':
        prog.started_at = prog.started_at or now
        prog.mastered_at = now
    else:  # not_started 重置 / skipped 跳过
        prog.mastered_at = None
    if time_spent > 0:
        prog.time_spent_sec = (prog.time_spent_sec or 0) + time_spent
    prog.attempts_count = (prog.attempts_count or 0) + 1
    db.session.flush()

    # 以 DB 实况重算选课进度（避免增量维护的并发误差）
    mastered_ids = {p.node_id for p in UserNodeProgress.query.filter_by(
        user_id=user.id, path_id=enr.path_id, status='mastered').all()}
    enr.completed_count = len(mastered_ids)
    all_nodes = LearningPathNode.query.filter_by(path_id=enr.path_id) \
        .order_by(LearningPathNode.order_num).all()
    next_node = next((n for n in all_nodes if n.id not in mastered_ids), None)
    enr.current_node_id = next_node.id if next_node else None
    just_completed = False
    if not next_node and all_nodes:
        if enr.status != 'completed':
            enr.status = 'completed'
            enr.completed_at = now
            just_completed = True
    elif enr.status == 'completed':
        enr.status = 'active'
        enr.completed_at = None

    # 掌握联动：节点掌握的知识点抬到已掌握线，并尝试自动核销计划任务
    if status == 'mastered' and node.knowledge_point_id:
        eng.bump_mastery_floor(user.id, node.knowledge_point_id, eng.MASTERED_LEVEL)
        eng.auto_complete_tasks(user.id, kp_ids=[node.knowledge_point_id])
        eng.touch_checkin(user.id, minutes=max(1, round((time_spent or 0) / 60)))
    if just_completed:
        # 路径首次全部掌握：发放「首程抵达」徽章（幂等，静默降级）
        eng.grant_learning_badges(user.id)
    return just_completed


# ── 知识图谱查询 ───────────────────────────────────────────────────

@api_learning_bp.route('/learning/knowledge-graph', methods=['GET'])
def api_knowledge_graph():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    path_id = request.args.get('path_id', type=int)
    major_id = request.args.get('major_id', type=int)

    if path_id:
        path = db.session.get(LearningPath, path_id)
        if not path:
            return jsonify({'message': '学习路径不存在'}), 404
        enrollment = UserPathEnrollment.query.filter_by(user_id=user.id, path_id=path_id).first()
        if not _can_view_path(path, user.id, enrollment):
            return jsonify({'message': '该路径未公开，无法查看'}), 403
        kp_ids = {n.knowledge_point_id for n in path.nodes
                  if n.node_type == 'knowledge_point' and n.knowledge_point_id}
    elif major_id:
        kp_ids = {row[0] for row in db.session.query(KnowledgePoint.id)
                  .join(Chapter, KnowledgePoint.chapter_id == Chapter.id)
                  .join(Course, Chapter.course_id == Course.id)
                  .filter(Course.major_id == major_id,
                          KnowledgePoint.status == 'active').all()}
    else:
        return jsonify({'message': '请提供 major_id 或 path_id'}), 400

    if not kp_ids:
        return jsonify({'nodes': [], 'edges': []})

    kps = KnowledgePoint.query.filter(KnowledgePoint.id.in_(kp_ids)).all()
    edges = KnowledgeEdge.query.filter(
        KnowledgeEdge.source_id.in_(kp_ids),
        KnowledgeEdge.target_id.in_(kp_ids)).all()

    # mine=1：为节点叠加当前用户掌握度/笔记/进度着色信息（个人掌握地图）
    mine = request.args.get('mine') in ('1', 'true', 'True')
    mmap = nmap = pmap = None
    if mine:
        now = utcnow()
        mmap = {m.knowledge_point_id: m for m in KnowledgeMastery.query.filter_by(user_id=user.id).all()}
        nmap = {n.knowledge_point_id for n in UserKpNote.query.filter_by(user_id=user.id).all()}
        if path_id:
            pmap = {p.node_id: p.status for p in UserNodeProgress.query.filter_by(
                user_id=user.id, path_id=path_id).all()}

    def _node_extra(kp):
        if not mine:
            return {}
        m = mmap.get(kp.id)
        raw = (m.level if m else 0) or 0.0
        shown = eng.decayed_level(raw, m.last_verified_at if m else None, now)
        return {
            'mastery': shown,
            'mastery_raw': round(raw, 1),
            'level_status': ('mastered' if shown >= eng.MASTERED_LEVEL else
                             'learning' if shown > 0 else 'untouched'),
            'decay_risk': raw >= eng.DECAY_RISK_RAW and shown < eng.DECAY_RISK_SHOWN,
            'has_note': kp.id in nmap,
        }

    return jsonify({
        'nodes': [dict({
            'id': kp.id, 'name': kp.name, 'description': kp.description,
            'difficulty': kp.difficulty, 'chapter_id': kp.chapter_id,
            'chapter_name': kp.chapter.name if kp.chapter else None,
        }, **_node_extra(kp)) for kp in kps],
        'edges': [{
            'id': e.id, 'source': e.source_id, 'target': e.target_id,
            'relation_type': e.relation_type, 'weight': e.weight,
        } for e in edges],
    })


# ── 学习资源 CRUD（登录可读写，全民共建） ──────────────────────────

@api_learning_bp.route('/learning/resources', methods=['GET'])
def api_resource_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    kp_id = request.args.get('knowledge_point_id', type=int)
    chapter_id = request.args.get('chapter_id', type=int)
    if not kp_id and not chapter_id:
        return jsonify({'message': '请提供 knowledge_point_id 或 chapter_id'}), 400

    q = LearningResource.query
    if kp_id:
        q = q.filter(LearningResource.knowledge_point_id == kp_id)
    if chapter_id:
        q = q.filter(LearningResource.chapter_id == chapter_id)

    resources = q.order_by(LearningResource.order_num, LearningResource.id).all()
    return jsonify([{
        'id': r.id, 'title': r.title, 'type': r.type, 'content': r.content,
        'url': r.url, 'knowledge_point_id': r.knowledge_point_id,
        'chapter_id': r.chapter_id, 'order_num': r.order_num,
    } for r in resources])


@api_learning_bp.route('/learning/resources', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_resource_create():
    user, err = _require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    r_type = data.get('type', 'text')
    kp_id = data.get('knowledge_point_id')
    chapter_id = data.get('chapter_id')
    if not title:
        return jsonify({'message': '资源标题不能为空'}), 400
    if r_type not in _RESOURCE_TYPES:
        return jsonify({'message': '无效的资源类型'}), 400
    if not kp_id and not chapter_id:
        return jsonify({'message': '资源必须挂到知识点或章节'}), 400
    if kp_id and not db.session.get(KnowledgePoint, kp_id):
        return jsonify({'message': '知识点不存在'}), 404
    if chapter_id and not db.session.get(Chapter, chapter_id):
        return jsonify({'message': '章节不存在'}), 404

    res = LearningResource(
        title=title[:120], type=r_type,
        content=(data.get('content') or '').strip() or None,
        url=(data.get('url') or '').strip() or None,
        knowledge_point_id=kp_id, chapter_id=chapter_id,
        creator_id=user.id,
        order_num=int(data.get('order_num', 0) or 0),
    )
    db.session.add(res)
    db.session.commit()
    return jsonify({'id': res.id, 'message': '创建成功'})


@api_learning_bp.route('/learning/resources/<int:res_id>', methods=['PUT'])
def api_resource_update(res_id):
    user, err = _require_login()
    if err:
        return err

    res = db.session.get(LearningResource, res_id)
    if not res:
        return jsonify({'message': '资源不存在'}), 404

    data = request.get_json(silent=True) or {}
    for k in ('title', 'type', 'content', 'url', 'order_num'):
        if k in data:
            setattr(res, k, data[k])
    if 'type' in data and data['type'] not in _RESOURCE_TYPES:
        return jsonify({'message': '无效的资源类型'}), 400
    db.session.commit()
    return jsonify({'message': '已更新'})


@api_learning_bp.route('/learning/resources/<int:res_id>', methods=['DELETE'])
def api_resource_delete(res_id):
    user, err = _require_login()
    if err:
        return err

    res = db.session.get(LearningResource, res_id)
    if not res:
        return jsonify({'message': '资源不存在'}), 404
    db.session.delete(res)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ══════════════════════════════════════════════════════════════════
#  学习闭环：今日学习 / 复习调度 / 节点小测 / 知识库 / 证书
# ══════════════════════════════════════════════════════════════════

# 客观题白名单复用文件前部的 _OBJECTIVE_TYPES（v5.26 收敛，不再重复定义）


# ── 今日学习聚合页 ────────────────────────────────────────────────
@api_learning_bp.route('/learning/today', methods=['GET'])
def api_today():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    now = utcnow()
    today = local_today()

    # 1) 打卡与连击
    streak = eng.compute_streak(user.id, today)
    week = eng.week_checkin_days(user.id, today)
    today_ci = StudyCheckin.query.filter_by(user_id=user.id, day=today).first()

    # 1.1) v4.4 今日专注计时概览（进行中会话 + 今日完成总时长；日窗口与打卡同为本地日历日）
    running_focus = FocusSession.query.filter_by(user_id=user.id, status='running') \
        .order_by(FocusSession.id.desc()).first()
    day_start = local_day_start(today)
    today_focus = FocusSession.query.filter_by(user_id=user.id, status='finished') \
        .filter(FocusSession.started_at >= day_start,
                FocusSession.started_at < day_start + timedelta(days=1)).all()
    focus_today_sec = sum(f.actual_sec or 0 for f in today_focus)

    # 2) 今日待办任务：active 计划未完成任务，按 order 取前 8
    plans = StudyPlan.query.filter_by(user_id=user.id, status='active').all()
    todo = []
    for p in plans:
        for t in p.tasks:
            if t.status != 'done':
                todo.append({
                    'task_id': t.id, 'plan_id': p.id, 'plan_title': p.title,
                    'title': t.title, 'task_type': t.task_type,
                    'knowledge_point_id': t.knowledge_point_id,
                    'question_count': t.question_count,
                    'progress_count': t.progress_count or 0,
                    'estimated_minutes': t.estimated_minutes,
                    'due_date': t.due_date.isoformat() if t.due_date else None,
                    'overdue': bool(t.due_date and t.due_date < today),
                })
                if len(todo) >= 8:
                    break
        if len(todo) >= 8:
            break

    # 3) 到期复习队列（前 10 概览，完整队列走 /reviews/due）
    due_items = ReviewItem.query.filter_by(user_id=user.id, status='pending') \
        .filter(ReviewItem.due_at <= now).order_by(ReviewItem.due_at.asc()).limit(10).all()
    due_reviews = [{
        'review_id': r.id, 'question_id': r.question_id,
        'question_content': r.question.content if r.question else None,
        'question_type': r.question.type if r.question else None,
        'source_type': r.source_type,
    } for r in due_items]
    due_count = eng.due_review_count(user.id, now)

    # 4) 当前在读路径的下一个未掌握节点
    next_node = None
    enr = UserPathEnrollment.query.filter_by(user_id=user.id, status='active') \
        .order_by(UserPathEnrollment.enrolled_at.desc()).first()
    if enr:
        nid = enr.current_node_id
        if nid:
            node = db.session.get(LearningPathNode, nid)
            if node:
                next_node = {
                    'enrollment_id': enr.id, 'path_id': enr.path_id,
                    'path_title': enr.path.title if enr.path else None,
                    'node_id': node.id,
                    'title': (node.knowledge_point.name if node.knowledge_point_id and node.knowledge_point
                              else (node.chapter.name if node.chapter_id and node.chapter else '未命名节点')),
                    'order_num': node.order_num,
                }

    # 5) 每日任务（用户自建 + AI 建议采纳）
    daily_tasks = DailyTask.query.filter_by(user_id=user.id, day=today) \
        .order_by(DailyTask.id).all()

    # 6) 薄弱知识点自适应推荐：推已有题（非动态生成），异常不阻断整页
    try:
        weak_recommendations = eng.recommend_practice_questions(user.id, limit=5)
    except Exception:  # noqa: BLE001 推荐为非关键路径
        logger.exception('薄弱点推荐失败 user_id=%s', user.id)
        weak_recommendations = []

    return jsonify({
        'date': today.isoformat(),
        'streak_days': streak,
        'checked_in_today': bool(today_ci),
        'today_minutes': (today_ci.minutes if today_ci else 0),
        'today_mood': today_ci.mood if today_ci else None,
        'today_note': today_ci.content if today_ci else None,
        'focus_today_sec': focus_today_sec,
        'running_focus': _focus_to_dict(running_focus) if running_focus else None,
        'week_days': week,
        'todo_tasks': todo,
        'daily_tasks': [_daily_task_to_dict(t) for t in daily_tasks],
        'due_reviews': due_reviews,
        'due_review_count': due_count,
        'next_node': next_node,
        'active_plans': len(plans),
        'weak_recommendations': weak_recommendations,
    })


# ── 每日任务（用户自建 + AI 学习建议） ────────────────────────────

def _daily_task_to_dict(t):
    return {'id': t.id, 'day': t.day.isoformat(), 'title': t.title,
            'source': t.source, 'status': t.status,
            'done_at': iso_local(t.done_at) if t.done_at else None}


def _parse_day(raw):
    """解析 YYYY-MM-DD；缺省/非法均回退到今天"""
    if raw:
        try:
            return date.fromisoformat(raw)
        except (ValueError, TypeError):
            pass
    return local_today()


def _today_snapshot(user):
    """聚合用户学习现状：返回（供 AI 的上下文文本，规则兑底建议列表）"""
    now = utcnow()
    today = local_today()
    lines = []
    fallback = []

    streak = eng.compute_streak(user.id, today)
    checked = StudyCheckin.query.filter_by(user_id=user.id, day=today).first() is not None
    lines.append(f"连续学习打卡 {streak} 天，今日{'已' if checked else '未'}打卡")
    if not checked:
        fallback.append("做 10 道自由刷题，完成今日打卡")

    due = eng.due_review_count(user.id, now)
    if due:
        lines.append(f"今日到期复习题 {due} 道")
        fallback.append(f"完成 {min(due, 20)} 道到期复习题")

    plans = StudyPlan.query.filter_by(user_id=user.id, status='active').all()
    todo_titles = [t.title for p in plans for t in p.tasks if t.status != 'done'][:5]
    if todo_titles:
        lines.append("学习计划未完成任务：" + "；".join(todo_titles))
        fallback.append(f"推进计划任务：{todo_titles[0][:30]}")

    enr = UserPathEnrollment.query.filter_by(user_id=user.id, status='active') \
        .order_by(UserPathEnrollment.enrolled_at.desc()).first()
    if enr and enr.current_node_id:
        node = db.session.get(LearningPathNode, enr.current_node_id)
        if node:
            name = (node.knowledge_point.name if node.knowledge_point_id and node.knowledge_point
                    else (node.chapter.name if node.chapter_id and node.chapter else '未命名节点'))
            lines.append(f"在读路径「{enr.path.title if enr.path else ''}」下一个节点：{name}")
            fallback.append(f"学完路径节点「{name[:20]}」")

    # 遗忘风险知识点：原始掌握达标但衰减跌破警戒线
    risks = []
    for m in KnowledgeMastery.query.filter_by(user_id=user.id) \
            .filter(KnowledgeMastery.level >= eng.DECAY_RISK_RAW).all():
        if eng.decayed_level(m.level, m.last_verified_at, now) < eng.DECAY_RISK_SHOWN:
            kp = db.session.get(KnowledgePoint, m.knowledge_point_id)
            if kp:
                risks.append(kp.name)
    if risks:
        lines.append("遗忘风险知识点：" + "；".join(risks[:5]))
        fallback.append(f"复刷遗忘风险知识点：{risks[0][:30]}")

    if not lines:
        lines.append("近期无活跃学习数据，建议从选一条专业学习路径开始")
        fallback.append("挑选一条专业学习路径并开始首个节点")
    fallback.append("自由刷题 15 分钟并整理错题笔记")
    return "\n".join(lines), fallback[:5]


@api_learning_bp.route('/learning/daily-tasks', methods=['GET'])
def api_daily_task_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    day = _parse_day(request.args.get('date'))
    items = DailyTask.query.filter_by(user_id=user.id, day=day) \
        .order_by(DailyTask.id).all()
    return jsonify({'day': day.isoformat(),
                    'items': [_daily_task_to_dict(t) for t in items]})


@api_learning_bp.route('/learning/daily-tasks', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_daily_task_create():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '任务标题不能为空'}), 400
    t = DailyTask(user_id=user.id, day=_parse_day(data.get('date')),
                  title=title[:200], source='manual')
    db.session.add(t)
    db.session.commit()
    return jsonify({'message': '已添加', 'task': _daily_task_to_dict(t)})


@api_learning_bp.route('/learning/daily-tasks/<int:tid>/toggle', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_daily_task_toggle(tid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    t = db.session.get(DailyTask, tid)
    if not t or t.user_id != user.id:
        return jsonify({'message': '任务不存在'}), 404
    if t.status == 'done':
        t.status = 'pending'
        t.done_at = None
    else:
        t.status = 'done'
        t.done_at = utcnow()
        # 完成当日任务计一次有效学习（打卡 tasks_done 累加）
        if t.day == local_today():
            eng.touch_checkin(user.id, tasks_delta=1)
    db.session.commit()
    return jsonify({'message': '已更新', 'status': t.status})


@api_learning_bp.route('/learning/daily-tasks/<int:tid>', methods=['DELETE'])
def api_daily_task_delete(tid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    t = db.session.get(DailyTask, tid)
    if not t or t.user_id != user.id:
        return jsonify({'message': '任务不存在'}), 404
    db.session.delete(t)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_learning_bp.route('/learning/daily-tasks/ai-suggest', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_daily_task_ai_suggest():
    """AI 学习建议：基于今日学习状态生成任务建议（不直接入库，前端勾选后 batch 采纳）；
    AI 不可用时降级为规则建议"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    context, fallback = _today_snapshot(user)
    source = 'rule'
    suggestions = fallback
    try:
        from ai_service.services import ai_suggest_daily_tasks
        suggestions = ai_suggest_daily_tasks(db.session, context)
        source = 'ai'
    except Exception:
        logger.exception('AI 每日任务建议失败，降级规则建议')
    return jsonify({'basis': context, 'suggestions': suggestions, 'source': source})


@api_learning_bp.route('/learning/daily-tasks/batch', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_daily_task_batch():
    """批量采纳建议（source=ai）：按天去重，单次上限 10 条"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    items = data.get('items')
    if not isinstance(items, list) or not items:
        return jsonify({'message': '请提供 items 建议列表'}), 400
    day = _parse_day(data.get('date'))
    existing = {t.title for t in DailyTask.query.filter_by(user_id=user.id, day=day).all()}
    added = 0
    for raw in items[:10]:
        title = str(raw or '').strip()[:200]
        if not title or title in existing:
            continue
        db.session.add(DailyTask(user_id=user.id, day=day, title=title, source='ai'))
        existing.add(title)
        added += 1
    db.session.commit()
    out = DailyTask.query.filter_by(user_id=user.id, day=day).order_by(DailyTask.id).all()
    return jsonify({'added': added, 'items': [_daily_task_to_dict(t) for t in out]})


# ── 间隔复习 ──────────────────────────────────────────────────────
@api_learning_bp.route('/learning/reviews/due', methods=['GET'])
def api_reviews_due():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    now = utcnow()
    items = ReviewItem.query.filter_by(user_id=user.id, status='pending') \
        .filter(ReviewItem.due_at <= now).order_by(ReviewItem.due_at.asc()).limit(20).all()
    return jsonify({
        'total': eng.due_review_count(user.id, now),
        'items': [{
            'review_id': r.id,
            'question': _question_min_dict(r.question) if r.question else None,
            'interval_days': r.interval_days, 'repetitions': r.repetitions,
            'source_type': r.source_type,
            'due_at': iso_local(r.due_at),
        } for r in items]
    })


@api_learning_bp.route('/learning/reviews/answer', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_review_answer():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    ri = db.session.get(ReviewItem, data.get('review_id'))
    if not ri or ri.user_id != user.id:
        return jsonify({'message': '复习卡不存在'}), 404
    q = db.session.get(Question, ri.question_id)
    if not q:
        return jsonify({'message': '题目不存在'}), 404

    student_answer = (data.get('student_answer') or '').strip()
    is_correct = _check_answer(q.type, student_answer, q.answer)
    # 主观题无法本地判分：前端须回传 self_correct（自评），否则拒绝
    if is_correct is None:
        self_correct = data.get('self_correct')
        if self_correct is None:
            return jsonify({'message': '主观题请自评（self_correct true/false）'}), 400
        is_correct = bool(self_correct)

    eng.schedule_next_review(ri, is_correct)

    # 掌握度 + 错题本联动
    kp_ids = eng.kp_ids_of_question(q.id)
    if kp_ids:
        eng.update_mastery(user.id, kp_ids, 1.0 if is_correct else 0.0)
    if is_correct:
        wr = WrongAnswerRecord.query.filter_by(user_id=user.id, question_id=q.id).first()
        if wr and not wr.is_mastered:
            wr.is_mastered = True
            wr.mastered_at = utcnow()
    eng.touch_checkin(user.id)
    db.session.commit()

    return jsonify({
        'is_correct': is_correct,
        'correct_answer': q.answer,
        'analysis': q.analysis,
        'next_interval_days': ri.interval_days,
        'next_due_at': iso_local(ri.due_at),
        'status': ri.status,
        'repetitions': ri.repetitions,
    })


# ── 节点小测 / 路径终测 ───────────────────────────

def _kp_objective_question_ids(kp_id, limit):
    ids = [row[0] for row in db.session.query(question_knowledge_point.c.question_id)
           .filter(question_knowledge_point.c.knowledge_point_id == kp_id).all()]
    qs = Question.query.filter(Question.id.in_(ids), Question.type.in_(_OBJECTIVE_TYPES)).all() \
        if ids else []
    import random
    random.shuffle(qs)
    return [q.id for q in qs[:limit]]


@api_learning_bp.route('/learning/quizzes/start', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_quiz_start():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    node_id = data.get('node_id')
    path_id = data.get('path_id')

    question_ids = []
    if node_id:
        node = db.session.get(LearningPathNode, node_id)
        if not node:
            return jsonify({'message': '节点不存在'}), 404
        if not node.knowledge_point_id:
            return jsonify({'message': '章节型节点不支持小测，请用配套练习'}), 400
        question_ids = _kp_objective_question_ids(node.knowledge_point_id, 8)
        if len(question_ids) < 3:
            return jsonify({'message': '该知识点关联客观题不足 3 道，暂不能组卷小测'}), 409
        scope_type, path_id_ = 'node', node.path_id
    elif path_id:
        path = db.session.get(LearningPath, path_id)
        if not path:
            return jsonify({'message': '学习路径不存在'}), 404
        enr = UserPathEnrollment.query.filter_by(user_id=user.id, path_id=path_id).first()
        if not enr:
            return jsonify({'message': '请先加入该学习路径'}), 400
        seen = set()
        for n in path.nodes:
            if n.role != 'core' or not n.knowledge_point_id:
                continue
            for qid in _kp_objective_question_ids(n.knowledge_point_id, 2):
                if qid not in seen:
                    seen.add(qid)
                    question_ids.append(qid)
        if len(question_ids) < 3:
            return jsonify({'message': '路径核心知识点客观题不足，暂不能生成终测'}), 409
        question_ids = question_ids[:20]
        scope_type, path_id_ = 'path_final', path_id
    else:
        return jsonify({'message': '需提供 node_id 或 path_id'}), 400

    attempt = QuizAttempt(user_id=user.id, scope_type=scope_type,
                         node_id=node_id, path_id=path_id_,
                         question_ids=question_ids, questions_count=len(question_ids))
    db.session.add(attempt)
    db.session.commit()

    qs = Question.query.filter(Question.id.in_(question_ids)).all()
    qmap = {q.id: q for q in qs}
    ordered = [qmap[qid] for qid in question_ids if qid in qmap]
    return jsonify({
        'attempt_id': attempt.id, 'scope_type': scope_type,
        'questions': [_question_min_dict(q) for q in ordered],
    })


@api_learning_bp.route('/learning/quizzes/<int:attempt_id>/answer', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_quiz_answer(attempt_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    att = db.session.get(QuizAttempt, attempt_id)
    if not att or att.user_id != user.id:
        return jsonify({'message': '小测不存在'}), 404
    if att.status != 'in_progress':
        return jsonify({'message': '该小测已交卷'}), 400

    data = request.get_json(silent=True) or {}
    q = db.session.get(Question, data.get('question_id'))
    if not q or q.id not in (att.question_ids or []):
        return jsonify({'message': '题目不在本次小测范围'}), 400

    student_answer = (data.get('student_answer') or '').strip()
    is_correct = _check_answer(q.type, student_answer, q.answer)

    qa = QuizAttemptAnswer.query.filter_by(attempt_id=att.id, question_id=q.id).first()
    if qa:
        qa.student_answer, qa.is_correct, qa.answered_at = student_answer, is_correct, utcnow()
    else:
        db.session.add(QuizAttemptAnswer(attempt_id=att.id, question_id=q.id,
                                        student_answer=student_answer, is_correct=is_correct))
    db.session.commit()
    return jsonify({'is_correct': is_correct, 'question_id': q.id})


@api_learning_bp.route('/learning/quizzes/<int:attempt_id>/submit', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_quiz_submit(attempt_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    att = db.session.get(QuizAttempt, attempt_id)
    if not att or att.user_id != user.id:
        return jsonify({'message': '小测不存在'}), 404
    if att.status == 'completed':
        return jsonify({'message': '已交卷', 'score_ratio': att.score_ratio,
                       'passed': (att.score_ratio or 0) >= eng.PASS_RATIO})

    answers = QuizAttemptAnswer.query.filter_by(attempt_id=att.id).all()
    answered_ids = {a.question_id for a in answers}
    total = att.questions_count or len(att.question_ids or [])
    correct = sum(1 for a in answers if a.is_correct)
    # 未作答的题计入总题数（得 0）
    ratio = round(correct / total, 4) if total else 0
    passed = ratio >= eng.PASS_RATIO

    att.correct_count = correct
    att.score_ratio = ratio
    att.status = 'completed'
    att.completed_at = utcnow()

    # 逐题更新掌握度
    from collections import defaultdict
    kp_hits = defaultdict(lambda: [0, 0])
    for a in answers:
        if a.is_correct is None:
            continue
        for kp in eng.kp_ids_of_question(a.question_id):
            kp_hits[kp][1] += 1
            if a.is_correct:
                kp_hits[kp][0] += 1
    for kp, (c, t) in kp_hits.items():
        eng.update_mastery(user.id, [kp], c / t if t else 0)

    node_title = None
    enrolled_completed = False
    if att.scope_type == 'node' and att.node_id:
        node = db.session.get(LearningPathNode, att.node_id)
        enr = UserPathEnrollment.query.filter_by(user_id=user.id, path_id=att.path_id).first()
        if node and enr and passed:
            _apply_node_status(user, enr, node, 'mastered')
            node_title = node.knowledge_point.name if node.knowledge_point else None
    elif att.scope_type == 'path_final' and passed:
        enr = UserPathEnrollment.query.filter_by(user_id=user.id, path_id=att.path_id).first()
        if enr and enr.status == 'completed':
            cert = _issue_certificate(user, att.path_id, ratio)
            enrolled_completed = bool(cert)

    eng.auto_complete_tasks(user.id, kp_ids=set(kp_hits.keys()))
    eng.touch_checkin(user.id)
    db.session.commit()

    return jsonify({
        'message': '已交卷', 'correct_count': correct, 'total': total,
        'score_ratio': ratio, 'passed': passed,
        'node_title': node_title,
        'certificate_issued': enrolled_completed,
    })


@api_learning_bp.route('/learning/quizzes/attempts', methods=['GET'])
def api_quiz_attempts():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    scope = request.args.get('scope_type')
    q = QuizAttempt.query.filter_by(user_id=user.id)
    if scope:
        q = q.filter_by(scope_type=scope)
    items = q.order_by(QuizAttempt.started_at.desc()).limit(30).all()
    return jsonify([{
        'id': a.id, 'scope_type': a.scope_type, 'node_id': a.node_id,
        'path_id': a.path_id, 'status': a.status,
        'correct_count': a.correct_count, 'questions_count': a.questions_count,
        'score_ratio': a.score_ratio,
        'passed': (a.score_ratio or 0) >= eng.PASS_RATIO,
        'started_at': iso_local(a.started_at), 'completed_at': iso_local(a.completed_at) if a.completed_at else None,
    } for a in items])


def _issue_certificate(user, path_id, final_score):
    """颁发路径证书（幂等）：已存在则只更新最高终测分，返回证书或 None"""
    path = db.session.get(LearningPath, path_id)
    if not path:
        return None
    cert = PathCertificate.query.filter_by(user_id=user.id, path_id=path_id).first()
    kps = {n.knowledge_point_id for n in path.nodes if n.knowledge_point_id}
    minutes = sum((p.time_spent_sec or 0) for p in UserNodeProgress.query.filter_by(
        user_id=user.id, path_id=path_id).all()) // 60
    summary = {
        'path_title': path.title,
        'major_name': path.major.name if path.major else None,
        'nodes': len(path.nodes), 'kps': len(kps), 'minutes': minutes,
        'earned_date': local_today().isoformat(),
    }
    if cert:
        if (final_score or 0) > (cert.final_score or 0):
            cert.final_score = final_score
            cert.summary = summary
        return cert
    cert = PathCertificate(user_id=user.id, path_id=path_id,
                          serial_no=eng.gen_serial_no(), final_score=final_score,
                          summary=summary)
    db.session.add(cert)
    db.session.flush()
    try:
        create_notification(user.id, f'恭喜获得结业证书：{path.title}',
                           f'您已完成学习路径「{path.title}」并通过结业测评（{round((final_score or 0)*100)}%）。',
                           type='success', related_type='certificate', related_id=cert.id, commit=False)
    except Exception:
        logger.exception('证书通知创建失败')
    return cert


# ── 知识库：我的知识点 / 笔记 / 证书 / 图谱着色 ──────────────

# 单个知识点卡片携带的资料条数上限：总数由 material_count 给出，列表只截最近几条
_KNOWLEDGE_MATERIAL_LIMIT = 8

@api_learning_bp.route('/learning/my-knowledge', methods=['GET'])
def api_my_knowledge():
    """我沉淀过的一切知识点（掌握度/笔记/关联资料/错题数），按 专业→课程→章节 层级"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    masteries = KnowledgeMastery.query.filter_by(user_id=user.id).all()
    mmap = {m.knowledge_point_id: m for m in masteries}
    notes = UserKpNote.query.filter_by(user_id=user.id).all()
    nmap = {n.knowledge_point_id: n for n in notes}

    # 预加载涉及的知识点及其章节/课程/专业链。
    # 入口不只掌握度：写过笔记、沉淀过资料的知识点同样是“我的知识资产”——
    # 只用 AI 生成过教案、还没刷过题的账号，以前整页是空的，资料在库里却看不见。
    own_kp_rows = db.session.query(StudyMaterial.knowledge_point_id).filter(
        StudyMaterial.user_id == user.id,
        StudyMaterial.status == 'active',
        StudyMaterial.knowledge_point_id.isnot(None)).distinct().all()
    kp_ids = sorted(set(mmap) | set(nmap) | {r[0] for r in own_kp_rows})
    if not kp_ids:
        return jsonify({'majors': [], 'total': 0})
    kps = KnowledgePoint.query.filter(KnowledgePoint.id.in_(kp_ids)).all()

    # 资料库反向索引：我的 active 资料按知识点归组（v7.14 打通知识库↔资料库）。
    # 只取本人资料，他人公开资料不混进「我的」；单 KP 截断避免树里塞长篇目录。
    mat_map = defaultdict(list)
    mats = StudyMaterial.query.filter(
        StudyMaterial.user_id == user.id,
        StudyMaterial.status == 'active',
        StudyMaterial.knowledge_point_id.in_(kp_ids)
    ).order_by(StudyMaterial.updated_at.desc()).all()
    for mt in mats:
        mat_map[mt.knowledge_point_id].append({'id': mt.id, 'kind': mt.kind, 'title': mt.title})

    now = utcnow()
    # 未掌握错题总数（按题目→KP 映射累加，仅作风险参考）
    wrong_qids = [w.question_id for w in WrongAnswerRecord.query.filter_by(
        user_id=user.id, is_mastered=False).all()]
    wrong_kp_count = defaultdict(int)
    if wrong_qids:
        rows = db.session.query(question_knowledge_point.c.question_id,
                               question_knowledge_point.c.knowledge_point_id) \
            .filter(question_knowledge_point.c.question_id.in_(wrong_qids)).all()
        wq2kp = defaultdict(list)
        for qid, kp in rows:
            wq2kp[qid].append(kp)
        counted = set()
        for qid in wrong_qids:
            for kp in wq2kp.get(qid, []):
                if (qid, kp) not in counted:
                    wrong_kp_count[kp] += 1
                    counted.add((qid, kp))

    tree = {}
    for kp in kps:
        ch = kp.chapter
        course = ch.course if ch else None
        major = course.major if course else None
        m = mmap.get(kp.id)
        raw = (m.level if m else 0) or 0.0
        shown = eng.decayed_level(raw, m.last_verified_at if m else None, now)
        risk = raw >= eng.DECAY_RISK_RAW and shown < eng.DECAY_RISK_SHOWN
        major_key = (major.id if major else 0, major.name if major else '未分类')
        course_key = (course.id if course else 0, course.name if course else '未分类')
        chapter_key = (ch.id if ch else 0, ch.name if ch else '未分类')
        tree.setdefault(major_key, {}).setdefault(course_key, {}).setdefault(chapter_key, []).append({
            'knowledge_point_id': kp.id, 'name': kp.name,
            'difficulty': kp.difficulty,
            'mastery_raw': round(raw, 1), 'mastery_shown': shown,
            'level_status': ('mastered' if shown >= eng.MASTERED_LEVEL else
                             'learning' if shown > 0 else 'untouched'),
            'decay_risk': risk,
            'has_note': kp.id in nmap,
            'note_excerpt': (nmap[kp.id].content[:80] if kp.id in nmap else None),
            'materials': mat_map.get(kp.id, [])[:_KNOWLEDGE_MATERIAL_LIMIT],
            'material_count': len(mat_map.get(kp.id, [])),
            'wrong_count': wrong_kp_count.get(kp.id, 0),
            'last_verified_at': iso_local(m.last_verified_at) if m else None,
        })

    out = []
    total = 0
    for (mid, mname), courses in tree.items():
        courses_out = []
        for (cid, cname), chapters in courses.items():
            chapters_out = []
            for (hid, hname), kp_list in chapters.items():
                kp_list.sort(key=lambda x: -x['mastery_shown'])
                total += len(kp_list)
                chapters_out.append({'chapter_id': hid, 'name': hname,
                                     'knowledge_points': kp_list})
            courses_out.append({'course_id': cid, 'name': cname, 'chapters': chapters_out})
        out.append({'major_id': mid, 'major_name': mname, 'courses': courses_out})
    out.sort(key=lambda x: x['major_name'])
    return jsonify({'majors': out, 'total': total})


@api_learning_bp.route('/learning/kp-notes', methods=['GET'])
def api_note_get():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    kp_id = request.args.get('knowledge_point_id', type=int)
    if not kp_id:
        return jsonify({'message': '请提供 knowledge_point_id'}), 400
    note = UserKpNote.query.filter_by(user_id=user.id, knowledge_point_id=kp_id).first()
    return jsonify({
        'knowledge_point_id': kp_id,
        'content': note.content if note else '',
        'updated_at': iso_local(note.updated_at) if note else None,
    })


@api_learning_bp.route('/learning/kp-notes/<int:kp_id>', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_note_upsert(kp_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    if not db.session.get(KnowledgePoint, kp_id):
        return jsonify({'message': '知识点不存在'}), 404
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if len(content) > 5000:
        return jsonify({'message': '笔记内容不能超过 5000 字'}), 400
    note = UserKpNote.query.filter_by(user_id=user.id, knowledge_point_id=kp_id).first()
    if not note:
        note = UserKpNote(user_id=user.id, knowledge_point_id=kp_id, content=content)
        db.session.add(note)
    else:
        note.content = content
    db.session.commit()
    return jsonify({'message': '已保存', 'updated_at': iso_local(note.updated_at)})


@api_learning_bp.route('/learning/kp-notes/<int:kp_id>/ai-polish', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_note_polish(kp_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    kp = db.session.get(KnowledgePoint, kp_id)
    if not kp:
        return jsonify({'message': '知识点不存在'}), 404
    data = request.get_json(silent=True) or {}
    text = (data.get('content') or '').strip()
    if not text:
        return jsonify({'message': '请先输入笔记内容'}), 400
    try:
        from ai_service.services import ai_polish_note
        polished = ai_polish_note(db.session, kp.name, text)
    except Exception:
        logger.exception('AI 润色笔记失败')
        return jsonify({'message': 'AI 服务暂不可用，请稍后重试'}), 500
    return jsonify({'polished': polished})


@api_learning_bp.route('/learning/certificates/mine', methods=['GET'])
def api_certificates_mine():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    certs = PathCertificate.query.filter_by(user_id=user.id) \
        .order_by(PathCertificate.earned_at.desc()).all()
    return jsonify([_certificate_to_dict(c, brief=True) for c in certs])


@api_learning_bp.route('/learning/certificates/<int:cert_id>', methods=['GET'])
def api_certificate_detail(cert_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    cert = db.session.get(PathCertificate, cert_id)
    if not cert or cert.user_id != user.id:
        return jsonify({'message': '证书不存在'}), 404
    return jsonify(_certificate_to_dict(cert, brief=False))


def _certificate_to_dict(c, brief=False):
    d = {
        'id': c.id, 'serial_no': c.serial_no,
        'path_id': c.path_id, 'path_title': (c.summary or {}).get('path_title') if c.summary else None,
        'final_score': c.final_score,
        'earned_at': iso_local(c.earned_at),
    }
    if not brief:
        d['summary'] = c.summary or {}
        d['username'] = c.user.username if c.user else None
    return d


# ════════════════════════════════════════════════════════════
#  v6.4 证书中心：多源聚合（系统结业 + 跨模块赛季 + 社会第三方）
# ════════════════════════════════════════════════════════════

_SEASON_GRADE_LABELS = {'gold': '金奖', 'silver': '银奖', 'bronze': '铜奖', 'merit': '纪念奖'}


def _get_competition_cert_model():
    """防御性导入赛季证书模型（独立模块，缺失时证书墙降级为不含跨模块证书）。"""
    try:
        from competition.models import CompetitionCertificate
        return CompetitionCertificate
    except Exception:
        logger.exception('赛季证书模型导入失败，证书墙降级为不含跨模块证书')
        return None


def _wall_item_system(c):
    s = c.summary or {}
    return {
        'kind': 'system', 'id': c.id, 'uid': f'system-{c.id}', 'group': 'system',
        'category': 'system', 'category_label': '系统结业',
        'title': s.get('path_title') or '学习路径结业证书',
        'subtitle': f"终测 {(c.final_score or 0) * 100:.0f} 分",
        'serial_no': c.serial_no, 'earned_at': iso_local(c.earned_at),
        'verify_status': 'verified', 'verify_label': '已核验',
        'extra': {'final_score': c.final_score, 'major_name': s.get('major_name')},
    }


def _wall_item_module(c):
    s = c.summary or {}
    grade_label = s.get('grade_label') or _SEASON_GRADE_LABELS.get(c.grade, c.grade)
    sub = f'段位 {c.tier} · 第 {c.rank} 名' if c.rank else (c.tier or '')
    return {
        'kind': 'module', 'id': c.id, 'uid': f'module-{c.id}', 'group': 'module',
        'category': 'module', 'category_label': '跨模块',
        'title': f'{c.season} 赛季 · {grade_label}',
        'subtitle': sub,
        'serial_no': c.serial_no, 'earned_at': iso_local(c.earned_at),
        'verify_status': 'verified', 'verify_label': '已核验',
        'extra': {'grade': c.grade, 'grade_label': grade_label, 'tier': c.tier,
                  'rank': c.rank, 'points': c.points, 'total_players': c.total_players},
    }


def _wall_item_social(c, with_owner=False):
    d = {
        'kind': 'social', 'id': c.id, 'uid': f'social-{c.id}', 'group': 'social',
        'category': c.category, 'category_label': CERT_CATEGORY_LABELS.get(c.category, c.category),
        'title': c.title,
        'subtitle': ' · '.join(x for x in [c.issuer, c.grade] if x),
        'serial_no': c.serial_no, 'earned_at': iso_local(c.earned_date or c.created_at),
        'verify_status': c.verify_status,
        'verify_label': CERT_VERIFY_LABELS.get(c.verify_status, c.verify_status),
        'has_file': bool(c.file_name),
        'extra': {'cert_no': c.cert_no, 'verify_note': c.verify_note},
    }
    if with_owner and c.owner is not None:
        d['owner'] = {'id': c.user_id, 'username': c.owner.username}
    return d


def _social_detail(c):
    d = _wall_item_social(c, with_owner=True)
    d.update({
        'issuer': c.issuer, 'cert_no': c.cert_no, 'grade': c.grade, 'note': c.note,
        'verify_note': c.verify_note,
        'earned_date': iso_local(c.earned_date) if c.earned_date else None,
        'created_at': iso_local(c.created_at),
        'verified_at': iso_local(c.verified_at) if c.verified_at else None,
        'file': {'orig': c.file_orig, 'size': c.file_size,
                 'url': f'/api/learning/certificates/social/{c.id}/file'} if c.file_name else None,
        'username': c.owner.username if c.owner else None,
    })
    return d


@api_learning_bp.route('/learning/certificates/wall', methods=['GET'])
def api_certificates_wall():
    """证书墙：聚合系统结业/跨模块赛季/社会第三方三类，按获证时间倒序；返回各分类计数。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    items = []

    sys_certs = PathCertificate.query.filter_by(user_id=user.id) \
        .order_by(PathCertificate.earned_at.desc()).all()
    items += [_wall_item_system(c) for c in sys_certs]

    CC = _get_competition_cert_model()
    mod_certs = []
    if CC is not None:
        mod_certs = CC.query.filter_by(user_id=user.id).order_by(CC.earned_at.desc()).all()
        items += [_wall_item_module(c) for c in mod_certs]

    soc_certs = UserCertificate.query.filter_by(user_id=user.id) \
        .order_by(UserCertificate.created_at.desc()).all()
    items += [_wall_item_social(c) for c in soc_certs]

    # v7.19 展示态：公开开关/浏览数/已分享的社区帖都在旁表里，一次取回按 (kind, id) 并进
    # 各行（逐行查会打成 N+1）；没有展示行的证书就是私有，缺省口径不写库也能正确展示
    displays = _display_map(user.id)
    for it in items:
        _apply_display(it, displays.get((it['kind'], it['id'])))

    items.sort(key=lambda x: x.get('earned_at') or '', reverse=True)
    pending = sum(1 for c in soc_certs if c.verify_status == 'pending')
    tabs = {'all': len(items), 'system': len(sys_certs),
            'module': len(mod_certs), 'social': len(soc_certs)}
    return jsonify({'items': items, 'tabs': tabs, 'pending_mine': pending,
                    'is_teacher': user.role == 'teacher',
                    'category_labels': CERT_CATEGORY_LABELS,
                    'kind_labels': CERT_KIND_LABELS})


@api_learning_bp.route('/learning/certificates/<kind>/<int:cid>', methods=['GET'])
def api_certificate_unified(kind, cid):
    """统一证书详情：按 kind 分发（system/module/social）。

    v7.19 加了对外可见的一层：本人开了「公开」的证书，他人也能读，但走脱敏视图且
    计一次浏览；本人/教师仍看原来的完整视图（证书编号、核验意见、佐证附件都在）。
    """
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    if kind in CERT_KIND_LABELS:
        cert = _cert_obj(kind, cid)
        if cert is None:
            return jsonify({'message': '证书不存在'}), 404
        if cert.user_id != user.id and user.role != 'teacher':
            d = CertificateDisplay.query.filter_by(cert_kind=kind, cert_id=cid).first()
            if d is None or not d.is_public:
                # 未公开的证书对外与「不存在」同口径：不透露它存在过，免得公开开关变成探测点
                return jsonify({'message': '证书不存在'}), 404
            d.views = (d.views or 0) + 1
            db.session.commit()
            return jsonify(_certificate_public(kind, cert, d))
        # 本人/教师看完整视图：展示态也得跟着回来，否则前端的公开开关一刷新就弹回关
        mine = _display_map(cert.user_id).get((kind, cid))
    if kind == 'system':
        cert = db.session.get(PathCertificate, cid)
        if not cert or cert.user_id != user.id:
            return jsonify({'message': '证书不存在'}), 404
        data = _certificate_to_dict(cert, brief=False)
        data['kind'] = 'system'
        data['is_mine'] = cert.user_id == user.id
        return jsonify(_apply_display(data, mine))
    if kind == 'module':
        CC = _get_competition_cert_model()
        if CC is None:
            return jsonify({'message': '证书不存在'}), 404
        cert = db.session.get(CC, cid)
        if not cert or cert.user_id != user.id:
            return jsonify({'message': '证书不存在'}), 404
        s = cert.summary or {}
        grade_label = s.get('grade_label') or _SEASON_GRADE_LABELS.get(cert.grade, cert.grade)
        data = {
            'kind': 'module', 'id': cert.id, 'serial_no': cert.serial_no,
            'season': cert.season, 'grade': cert.grade, 'grade_label': grade_label,
            'tier': cert.tier, 'rank': cert.rank, 'points': cert.points,
            'total_players': cert.total_players, 'earned_at': iso_local(cert.earned_at),
            'username': cert.author.username if cert.author else None, 'summary': s,
            'is_mine': cert.user_id == user.id,
        }
        return jsonify(_apply_display(data, mine))
    if kind == 'social':
        cert = db.session.get(UserCertificate, cid)
        if not cert or (cert.user_id != user.id and user.role != 'teacher'):
            return jsonify({'message': '证书不存在'}), 404
        data = _social_detail(cert)
        data['is_mine'] = cert.user_id == user.id
        return jsonify(_apply_display(data, mine))
    return jsonify({'message': '未知证书类型'}), 400


@api_learning_bp.route('/learning/certificates/social', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_certificate_social_create():
    """登记社会/第三方证书：表单字段 + 可选佐证附件（multipart），提交后为待核验。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    title = (request.form.get('title') or '').strip()
    if not title:
        return jsonify({'message': '请填写证书名称'}), 400
    category = (request.form.get('category') or 'other').strip()
    if category not in CERT_CATEGORY_LABELS:
        category = 'other'
    cert = UserCertificate(
        user_id=user.id, category=category, title=title[:200],
        issuer=(request.form.get('issuer') or '').strip()[:120] or None,
        cert_no=(request.form.get('cert_no') or '').strip()[:80] or None,
        grade=(request.form.get('grade') or '').strip()[:60] or None,
        note=(request.form.get('note') or '').strip()[:2000] or None,
        serial_no=eng.gen_serial_no(), verify_status='pending',
    )
    try:
        cert.earned_date = parse_dt((request.form.get('earned_date') or '').strip())
    except (ValueError, TypeError):
        cert.earned_date = None
    file = request.files.get('file')
    if file and file.filename:
        try:
            stored, size = save_upload(file, 'cert', _UPLOAD_DIR)
        except ValueError as e:
            return jsonify({'message': str(e)}), 400
        cert.file_name, cert.file_orig, cert.file_size = stored, file.filename[:200], size
    db.session.add(cert)
    db.session.commit()
    return jsonify({'message': '已提交，等待教师核验', 'certificate': _social_detail(cert)}), 201


@api_learning_bp.route('/learning/certificates/social/<int:cid>', methods=['DELETE'])
def api_certificate_social_delete(cid):
    """删除社会证书：本人可删自己的；教师可删任意（驳回后清理）。附件一并清理。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    cert = db.session.get(UserCertificate, cid)
    if not cert:
        return jsonify({'message': '证书不存在'}), 404
    if cert.user_id != user.id and user.role != 'teacher':
        return jsonify({'message': '无权删除'}), 403
    if cert.file_name:
        try:
            os.remove(os.path.join(_UPLOAD_DIR, cert.file_name))
        except OSError:
            pass
    # 展示态旁表跟着清：不留「证书没了、广场里还挂着一行公开记录」的孤儿
    # 逐行 db.session.delete 而非 query.delete()：bulk 写不进 PG→SQLite 实时镜像（v7.5 实锤坑）
    for d in CertificateDisplay.query.filter_by(cert_kind='social', cert_id=cid).all():
        db.session.delete(d)
    db.session.delete(cert)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_learning_bp.route('/learning/certificates/social/pending', methods=['GET'])
def api_certificate_social_pending():
    """教师：全站待核验社会证书列表。"""
    user, err = require_teacher()
    if err:
        return err
    certs = UserCertificate.query.filter_by(verify_status='pending') \
        .order_by(UserCertificate.created_at.asc()).all()
    return jsonify({'items': [_social_detail(c) for c in certs]})


@api_learning_bp.route('/learning/certificates/social/<int:cid>/verify', methods=['POST'])
def api_certificate_social_verify(cid):
    """教师核验：action=verify|reject，附意见；结果通知提交人。"""
    user, err = require_teacher()
    if err:
        return err
    cert = db.session.get(UserCertificate, cid)
    if not cert:
        return jsonify({'message': '证书不存在'}), 404
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()
    if action not in ('verify', 'reject'):
        return jsonify({'message': 'action 需为 verify 或 reject'}), 400
    cert.verify_status = 'verified' if action == 'verify' else 'rejected'
    cert.verify_note = (data.get('note') or '').strip()[:200] or None
    cert.verified_by = user.id
    cert.verified_at = utcnow()
    db.session.commit()
    result = '已通过核验' if cert.verify_status == 'verified' else '未通过核验'
    create_notification(
        cert.user_id, '证书核验结果',
        f'你提交的「{cert.title}」{result}。' + (f'教师意见：{cert.verify_note}' if cert.verify_note else ''),
        type='success' if cert.verify_status == 'verified' else 'warning',
        related_type='certificate', related_id=cert.id,
    )
    return jsonify({'message': f'已{result}', 'certificate': _social_detail(cert)})


@api_learning_bp.route('/learning/certificates/social/<int:cid>/file', methods=['GET'])
def api_certificate_social_file(cid):
    """下载社会证书佐证附件：本人或教师可取。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    cert = db.session.get(UserCertificate, cid)
    if not cert or not cert.file_name:
        return jsonify({'message': '附件不存在'}), 404
    if cert.user_id != user.id and user.role != 'teacher':
        return jsonify({'message': '无权下载该附件'}), 403
    return send_from_directory(_UPLOAD_DIR, cert.file_name,
                               as_attachment=True, download_name=cert.file_orig)


# ══ v7.19 证书公开与分享：展示态旁表 / 证书广场 / 一键发到社区中心 ══

def _cert_model_of(kind):
    """kind -> 证书模型；赛季证书走防御性导入，拿不到就是 None（该 kind 整体降级）。"""
    if kind == 'system':
        return PathCertificate
    if kind == 'module':
        return _get_competition_cert_model()
    if kind == 'social':
        return UserCertificate
    return None


def _cert_obj(kind, cid):
    """三源证书统一取实体，取不到返回 None（调用方一律当「不存在」处理）。"""
    model = _cert_model_of(kind)
    return db.session.get(model, cid) if model is not None else None


def _display_map(user_id):
    """一次取回本人全部展示态，按 (cert_kind, cert_id) 建索引供证书墙并入。"""
    return {(d.cert_kind, d.cert_id): d for d in
            db.session.query(CertificateDisplay).filter_by(user_id=user_id).all()}


def _ensure_display(user_id, kind, cid):
    """get-or-create 展示态行（只 flush 不 commit，由调用方统一提交）。

    并发双插靠 (cert_kind, cert_id) 唯一约束兜住：撞了就取已存在的那行，不把
    「同时点了两次公开」变成 500。"""
    d = CertificateDisplay.query.filter_by(cert_kind=kind, cert_id=cid).first()
    if d is None:
        d = CertificateDisplay(user_id=user_id, cert_kind=kind, cert_id=cid,
                               is_public=False, views=0)
        db.session.add(d)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            d = CertificateDisplay.query.filter_by(cert_kind=kind, cert_id=cid).first()
    return d


def _apply_display(item, d):
    """把展示态并进展示字典；d 为 None（从没设置过）时按私有零浏览零分享。"""
    item['is_public'] = bool(d.is_public) if d is not None else False
    item['views'] = int(d.views or 0) if d is not None else 0
    item['share_post_id'] = d.share_post_id if d is not None else None
    return item


def _public_cert_item(kind, cert):
    """对外视图：复用各自序列化后剪掉个人材料。

    证书编号（现实证件号）、教师核验意见、佐证附件都属于证书本体之外的东西，
    公开一张证书不等于公开这些；系统编号留着，那正是站内可核验的意义。"""
    if kind == 'system':
        item = _wall_item_system(cert)
    elif kind == 'module':
        item = _wall_item_module(cert)
    elif kind == 'social':
        item = _wall_item_social(cert)
        item['extra'] = {}
        item.pop('has_file', None)
    else:
        return None
    item['cert_kind_label'] = CERT_KIND_LABELS.get(kind, kind)
    return item


def _certificate_public(kind, cert, display):
    """他人读公开证书的完整响应：脱敏正文 + 属主名字 + 展示态。"""
    data = _public_cert_item(kind, cert)
    if kind == 'social':
        data['issuer'] = cert.issuer
        data['grade'] = cert.grade
        data['earned_date'] = iso_local(cert.earned_date) if cert.earned_date else None
    owner = db.session.get(User, cert.user_id)
    data['owner'] = {'id': cert.user_id, 'username': owner.username if owner else None}
    return _apply_display(data, display)


@api_learning_bp.route('/learning/certificates/<kind>/<int:cid>/display', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_certificate_display(kind, cid):
    """公开 / 取消公开一份证书（仅本人）。

    登记即可公开：教师核验状态只作为角标跟着展示，不当公开门禁——现实里大量证书
    （校内奖/公司证/旧证）根本不会来走这套核验，卡住只会把功能堵死。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    if kind not in CERT_KIND_LABELS:
        return jsonify({'message': '未知证书类型：' + kind, 'kinds': sorted(CERT_KIND_LABELS)}), 400
    cert = _cert_obj(kind, cid)
    if not cert or cert.user_id != user.id:
        return jsonify({'message': '证书不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'is_public' not in data:
        return jsonify({'message': '请提供 is_public'}), 400
    on = bool(data.get('is_public'))
    d = _ensure_display(user.id, kind, cid)
    d.is_public = on
    db.session.commit()
    return jsonify({'message': '已公开到证书广场' if on else '已从证书广场撤下',
                    'is_public': on, 'views': int(d.views or 0),
                    'share_post_id': d.share_post_id})


@api_learning_bp.route('/learning/certificates/square', methods=['GET'])
@limiter.limit('60/minute')
def api_certificate_square():
    """证书广场：全站公开证书的卡片墙，可按类型/类别/关键词筛，按最新/最热排。

    展示态与证书本体分家后，这里必须自己拼「取公开行 -> 回源取证书 -> 脱敏」这一段；
    候选集每类上限 500 份（荣誉类内容量级远小于此），换来的是三类证书共用一套
    公开/浏览/分享语义，且系统颁发的证书行始终不被写。

    owner=<uid> 用于他人主页拉「他公开的证书」：仍只给脱敏视图，不因为走了主页就多出什么。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    kind = (request.args.get('kind') or '').strip()
    category = (request.args.get('category') or '').strip()
    q = (request.args.get('q') or '').strip()
    sort = request.args.get('sort') or 'latest'
    try:
        owner = int(request.args.get('owner') or 0) or None
    except (TypeError, ValueError):
        owner = None
    try:
        page = max(1, int(request.args.get('page', 1)))
        size = min(60, max(1, int(request.args.get('size', 24))))
    except (TypeError, ValueError):
        page, size = 1, 24

    kinds = [kind] if kind in CERT_KIND_LABELS else list(CERT_KIND_LABELS)
    items = []
    for k in kinds:
        model = _cert_model_of(k)
        if model is None:
            continue
        displays = (db.session.query(CertificateDisplay)
                    .filter(CertificateDisplay.cert_kind == k,
                            CertificateDisplay.is_public.is_(True))
                    .limit(500).all())
        if not displays:
            continue
        shown = {d.cert_id: d for d in displays}
        certs = model.query.filter(model.id.in_(list(shown))).all()
        for c in certs:
            d = shown.get(c.id)
            # 展示行记的属主与证书对不上就是脏数据（证书被删后重建撞了 id 之类），不参与公开
            if d is None or d.user_id != c.user_id:
                continue
            item = _public_cert_item(k, c)
            if item is None:
                continue
            if category and item.get('category') != category:
                continue
            if q and q.lower() not in ((item.get('title') or '') + (item.get('subtitle') or '')).lower():
                continue
            _apply_display(item, d)
            item['owner'] = {'id': d.user_id, 'username': d.user.username if d.user else None}
            if owner and item['owner']['id'] != owner:
                continue
            items.append(item)

    if sort == 'hot':
        items.sort(key=lambda x: (-x['views'], x.get('earned_at') or ''))
    else:
        items.sort(key=lambda x: x.get('earned_at') or '', reverse=True)
    total = len(items)
    start = (page - 1) * size
    return jsonify({'items': items[start:start + size], 'total': total, 'page': page,
                    'size': size, 'kind_labels': CERT_KIND_LABELS,
                    'category_labels': CERT_CATEGORY_LABELS})


@api_learning_bp.route('/learning/certificates/<kind>/<int:cid>/share', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_certificate_share(kind, cid):
    """把一份证书发成社区经验帖，并顺带公开到证书广场。

    分享即公开：帖子里已经写着证书名称与获证时间，本体还留在私有就是「帖能看、
    证不能看」的割裂。已分享过且原帖还在时直接回原帖 id，避免连点两次在社区里
    刷出两串一模一样的荣誉帖。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    if kind not in CERT_KIND_LABELS:
        return jsonify({'message': '未知证书类型：' + kind}), 400
    cert = _cert_obj(kind, cid)
    if not cert or cert.user_id != user.id:
        return jsonify({'message': '证书不存在'}), 404

    display = _ensure_display(user.id, kind, cid)
    if display.share_post_id:
        from database.models import CommunityPost
        alive = db.session.get(CommunityPost, display.share_post_id)
        if alive is not None and not alive.deleted:
            db.session.commit()
            return jsonify({'message': '这份证书已经分享过了', 'post_id': alive.id,
                            'existed': True, 'is_public': bool(display.is_public)}), 200
        display.share_post_id = None

    item = _public_cert_item(kind, cert)
    data = request.get_json(silent=True) or {}
    lines = [f'> 来自为学空间·我的证书（{CERT_KIND_LABELS.get(kind, kind)}）', '',
             f'**{item["title"]}**', '']
    for label, value in (('详情', item.get('subtitle')),
                         ('获证时间', (item.get('earned_at') or '')[:10]),
                         ('系统编号', f'{item["serial_no"]}（站内可核验）'),
                         ('核验状态', item.get('verify_label'))):
        if value:
            lines.append(f'- {label}：{value}')
    note = str(data.get('note') or '').strip()[:500]
    if note:
        lines += ['', f'**我想说的话**：{note}']
    lines += ['', '（证书本体与佐证材料不随帖外发，可在「我的证书」里查看）']

    from utils.community_bridge import sync_to_community
    post = sync_to_community(
        actor_id=user.id,
        category='experience',
        title=f'[荣誉证书] {item["title"]}',
        content='\n'.join(lines),
        tags=CERT_KIND_LABELS.get(kind, kind),
        anonymous=bool(data.get('anonymous')),
    )
    display.is_public = True
    display.share_post_id = post.id
    db.session.commit()

    # 通知是旁路：帖已发成、库已落，写挂不能反过来把分享报成失败（同 v7.12 AI 出题那次教训）
    try:
        create_notification(user.id, '证书已分享到社区',
                            f'「{item["title"]}」已发布为社区经验帖，同时公开在证书广场。',
                            type='success', related_type='community_post', related_id=post.id)
    except Exception:
        db.session.rollback()
        logger.exception('[learning] 证书分享通知创建失败 post_id=%s', post.id)
    return jsonify({'message': '已分享到社区中心', 'post_id': post.id, 'is_public': True}), 201


# ══ v7.19 学习心得：固定三段（感悟与收获 / 心得与总结 / 反思创造）+ 周期归档 ══

_INSIGHT_SECTION_MAX = 4000      # 单段字数上限，与 ai_generate_insight_draft 的截断同档
_INSIGHT_TAG_MAX = 8


def _insight_range(period_type, start=None, end=None, note=None):
    """周期起止 -> (aware UTC 起点, aware UTC 终点, 阶段说明)

    day/week/month 不给起止就按本地日历倒推一个整周期：日界必须走本地，按 UTC 日切会在
    本地 00:00-07:59 少算一天（v5.35 打卡那次的坑）。终点取末日 23:59:59.999999，这样
    iso_local 截前 10 位显示的就是末日而不是次日，前端不必再减一天。
    """
    if period_type not in INSIGHT_PERIOD_LABELS:
        raise ValueError(f'未知周期类型：{period_type}，可选 {sorted(INSIGHT_PERIOD_LABELS)}')
    span = {'day': 1, 'week': 7, 'month': 30}.get(period_type)
    note = (note or '').strip()[:80] or None
    if span:
        today = local_today()
        s = parse_dt(start) if start else local_day_start(today - timedelta(days=span - 1))
        e = parse_dt(end) if end else (local_day_start(today) + timedelta(days=1)
                                       - timedelta(microseconds=1))
        if e < s:
            raise ValueError('周期终点不能早于起点')
        return s, e, note
    s = parse_dt(start) if start else None
    e = parse_dt(end) if end else None
    # 阶段/自定义是「本人自己划的一段」，服务端猜不出来：至少要说清起止或这段叫什么
    if not note and not (s and e):
        raise ValueError('阶段/自定义周期请填写起止日期，或写明阶段名称')
    if s and e and e < s:
        raise ValueError('周期终点不能早于起点')
    return s, e, note


def _insight_period_text(i):
    """周期的中文描述：起止日期或阶段名。卡片与分享正文都取它，免得各处各拼一套。"""
    text = ''
    if i.period_start and i.period_end:
        s, e = fmt_local(i.period_start, '%Y-%m-%d'), fmt_local(i.period_end, '%Y-%m-%d')
        text = s if s == e else f'{s} ~ {e}'
    elif i.period_start:
        text = f'{fmt_local(i.period_start, "%Y-%m-%d")} 起'
    if i.period_note:
        text = f'{i.period_note}（{text}）' if text else i.period_note
    return text or INSIGHT_PERIOD_LABELS.get(i.period_type, i.period_type)


def _insight_to_dict(i, with_content=True):
    """心得序列化：列表只给三段前 60 字预览 + 字数，详情给全文与关联的计划/知识点。"""
    d = {
        'id': i.id, 'title': i.title,
        'period_type': i.period_type,
        'period_label': INSIGHT_PERIOD_LABELS.get(i.period_type, i.period_type),
        'period_start': iso_local(i.period_start), 'period_end': iso_local(i.period_end),
        'period_note': i.period_note, 'period_text': _insight_period_text(i),
        'tags': list(i.tags or []), 'source': i.source,
        'plan_id': i.plan_id, 'knowledge_point_id': i.knowledge_point_id,
        'is_public': bool(i.is_public), 'views': int(i.views or 0),
        'share_post_id': i.share_post_id,
        'created_at': iso_local(i.created_at), 'updated_at': iso_local(i.updated_at),
        'word_count': sum(len(getattr(i, k) or '') for k in INSIGHT_SECTION_LABELS),
    }
    for key in INSIGHT_SECTION_LABELS:
        text = getattr(i, key) or ''
        if with_content:
            d[key] = text
        else:
            d.setdefault('previews', {})[key] = text[:60]
    if with_content:
        d['section_labels'] = INSIGHT_SECTION_LABELS
        d['plan_title'] = i.plan.title if i.plan else None
        d['kp_name'] = i.knowledge_point.name if i.knowledge_point else None
    return d


def _clean_insight_sections(data):
    """三段清洗：逐段限长，三段全空直接拒——一条心得至少得说出点东西来。

    「至少两段」这种要求会把人挡在门口：现实里很多人只写反思那一栏，那也是一条心得。
    """
    sections = {}
    for key in INSIGHT_SECTION_LABELS:
        text = str(data.get(key) or '').strip()
        if len(text) > _INSIGHT_SECTION_MAX:
            raise ValueError(f'{INSIGHT_SECTION_LABELS[key]} 过长（单段上限 {len(text)} 字，'
                             f'限 {_INSIGHT_SECTION_MAX} 字）')
        sections[key] = text
    if not any(sections.values()):
        raise ValueError('三段里至少要填写一段')
    return sections


def _clean_insight_tags(value):
    """标签口径同笔记与社区：单项 ≤20 字、总数 ≤8、去重、拒含斜杠的（斜杠是路由分隔符）。"""
    if not value:
        return []
    if isinstance(value, str):
        value = value.replace('，', ',').replace('、', ',').split(',')
    if not isinstance(value, (list, tuple)):
        return []
    tags = []
    for item in value:
        t = str(item or '').strip().lstrip('#')[:20]
        if not t or '/' in t or t in tags:
            continue
        tags.append(t)
        if len(tags) >= _INSIGHT_TAG_MAX:
            break
    return tags


def _insight_facts(user_id, days=7):
    """把一段周期的学习数据压成给 AI 的事实清单（纯文本，供 ai_generate_insight_draft）

    只给聚合数字与知识点名字：题目正文、笔记与资料原文一概不外传——AI 需要知道的是
    「做了什么、做到什么程度」，怎么看待这些必须由用户自己写。数据薄也照常出清单，
    服务端把 0 也写进去，模型那边就会转成引导式提问而不是编一段假的努力出来。
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 120))     # 不能写 days or 7：0 会被悄悄换成 7
    ov = _report_overview_payload(user_id, days)
    cutoff = utcnow() - timedelta(days=days)
    lines = [f'统计区间：最近 {days} 天（截至 {fmt_local(utcnow(), "%Y-%m-%d")}）']
    if ov['total_questions']:
        lines.append(f"- 练习题量 {ov['total_questions']} 道，答对 {ov['correct_count']} 道，"
                     f"正确率 {ov['score_ratio'] * 100:.0f}%")
    else:
        lines.append('- 区间内没有练习题量')
    lines.append(f"- 有效学习时长 {ov['total_time_sec'] // 60} 分钟，学习会话 {ov['sessions_count']} 次")
    lines.append(f"- 错题本累计 {ov['wrong_total']} 条，已攻克 {ov['wrong_mastered']} 条，"
                 f"未攻克 {ov['wrong_unmastered']} 条")
    lines.append(f"- 进行中的学习计划 {ov['active_plans']} 个")

    checkins = StudyCheckin.query.filter_by(user_id=user_id).filter(
        StudyCheckin.day >= local_today() - timedelta(days=days - 1)).all()
    lines.append(f'- 打卡 {len(checkins)} 天，累计 {sum(c.minutes or 0 for c in checkins)} 分钟，'
                 f'完成任务 {sum(c.tasks_done or 0 for c in checkins)} 项')
    moods = [c.mood for c in checkins if c.mood]
    if moods:
        top = max(set(moods), key=moods.count)
        lines.append(f'- 打卡心情出现最多的是 {top}（{moods.count(top)}/{len(moods)} 次）')

    tasks = (db.session.query(StudyPlanTask)
             .join(StudyPlan, StudyPlanTask.plan_id == StudyPlan.id)
             .filter(StudyPlan.user_id == user_id).all())
    done_cnt = sum(1 for t in tasks
                   if t.status == 'done' and t.done_at and t.done_at >= cutoff)
    open_cnt = sum(1 for t in tasks if t.status != 'done')
    lines.append(f'- 计划任务：区间内完成 {done_cnt} 项，仍待办 {open_cnt} 项')

    mat_q = StudyMaterial.query.filter(StudyMaterial.user_id == user_id,
                                       StudyMaterial.updated_at >= cutoff,
                                       StudyMaterial.status == 'active')
    lines.append(f'- 区间内新增或更新学习资料 {mat_q.count()} 份，'
                 f'学习笔记 {StudyNote.query.filter(StudyNote.user_id == user_id, StudyNote.updated_at >= cutoff).count()} 篇')
    from ai_service.services import MATERIAL_KIND_NAMES
    kind_rows = (db.session.query(StudyMaterial.kind, func.count(StudyMaterial.id))
                 .filter(StudyMaterial.user_id == user_id,
                         StudyMaterial.updated_at >= cutoff,
                         StudyMaterial.status == 'active')
                 .group_by(StudyMaterial.kind).all())
    if kind_rows:
        lines.append('- 资料构成：' + '、'.join(
            f'{MATERIAL_KIND_NAMES.get(k, k)} {n} 份' for k, n in kind_rows))

    masteries = (KnowledgeMastery.query.filter_by(user_id=user_id)
                 .order_by(KnowledgeMastery.level.asc()).limit(5).all())
    weak = [f'{m.knowledge_point.name}（原始掌握度 {m.level:.0f}）'
            for m in masteries if m.knowledge_point]
    if weak:
        lines.append('- 掌握度最低的知识点：' + '、'.join(weak))
    return '\n'.join(lines)


@api_learning_bp.route('/learning/insights', methods=['GET'])
def api_insight_list():
    """我的心得列表：按周期/标签/关键词筛选，返回三段预览与各周期计数（不随筛选变）。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    period = (request.args.get('period') or '').strip()
    tag = (request.args.get('tag') or '').strip()
    q = (request.args.get('q') or '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
        size = min(50, max(1, int(request.args.get('size', 10))))
    except (TypeError, ValueError):
        page, size = 1, 10

    rows = StudyInsight.query.filter_by(user_id=user.id).order_by(
        StudyInsight.updated_at.desc()).all()
    tabs = {k: 0 for k in INSIGHT_PERIOD_LABELS}
    for r in rows:
        tabs[r.period_type] = tabs.get(r.period_type, 0) + 1
    tabs['all'] = len(rows)

    items = []
    for r in rows:
        if period and period != 'all' and r.period_type != period:
            continue
        if tag and tag not in (r.tags or []):
            continue
        if q:
            hay = ' '.join([r.title, _insight_period_text(r), ' '.join(r.tags or [])]
                           + [getattr(r, k) or '' for k in INSIGHT_SECTION_LABELS])
            if q.lower() not in hay.lower():
                continue
        items.append(_insight_to_dict(r, with_content=False))
    total = len(items)
    start = (page - 1) * size
    return jsonify({'items': items[start:start + size], 'total': total, 'page': page,
                    'size': size, 'tabs': tabs,
                    'period_labels': INSIGHT_PERIOD_LABELS,
                    'section_labels': INSIGHT_SECTION_LABELS})


@api_learning_bp.route('/learning/insights', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_insight_create():
    """新建心得：标题留空时按周期自动起名（先让人写下来，标题不是门槛）。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    period_type = (data.get('period_type') or 'week').strip()
    try:
        sections = _clean_insight_sections(data)
        s, e, note = _insight_range(period_type, data.get('period_start'),
                                    data.get('period_end'), data.get('period_note'))
    except ValueError as err:
        return jsonify({'message': str(err)}), 400
    i = StudyInsight(
        user_id=user.id,
        title=str(data.get('title') or '').strip()[:200] or f'{INSIGHT_PERIOD_LABELS[period_type]}学习心得',
        period_type=period_type, period_start=s, period_end=e, period_note=note,
        tags=_clean_insight_tags(data.get('tags')),
        plan_id=data.get('plan_id') or None,
        knowledge_point_id=data.get('knowledge_point_id') or None,
        source='ai_draft' if data.get('source') == 'ai_draft' else 'manual',
        is_public=False, views=0, **sections,
    )
    db.session.add(i)
    db.session.commit()
    return jsonify({'message': '心得已保存', 'insight': _insight_to_dict(i)}), 201


@api_learning_bp.route('/learning/insights/ai-draft', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_insight_ai_draft():
    """AI 心得初稿：按最近 N 天学习数据生成三段草稿，不落库，回前端编辑后再保存。

    额度三步走与讲解卡同构；AI 挂掉时 services 内部降级成「把真实数据列出来 + 留待填写」
    的框架而不是报错——初稿本来就是给人改的，给不出漂亮话也不能把入口堵死。
    """
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    try:
        days = max(1, min(int(data.get('days') or 7), 120))
    except (TypeError, ValueError):
        days = 7
    focus = str(data.get('focus') or '').strip()[:200] or None

    allowed, _quota = check_ai_quota(user)
    if not allowed:
        return jsonify({'message': '今日 AI 额度已用完，请明天再来或咨询教师调整配额'}), 429
    t0 = time.perf_counter()
    try:
        facts = _insight_facts(user.id, days)
    except Exception:
        logger.exception('[learning] 心得数据摘要拼装失败')
        return jsonify({'message': '学习数据读取失败，请稍后重试'}), 500
    from ai_service.services import ai_generate_insight_draft
    try:
        draft, degraded = ai_generate_insight_draft(db.session, facts, focus)
    except ValueError as err:
        return jsonify({'message': str(err)}), 400
    charge_ai_quota(user)
    log_ai_usage(user.id, 'insight', 'degraded' if degraded else 'success',
                 (time.perf_counter() - t0) * 1000)
    db.session.commit()
    return jsonify({'draft': draft, 'degraded': degraded, 'facts': facts, 'days': days,
                    'section_labels': INSIGHT_SECTION_LABELS,
                    'message': '已生成初稿，请修改后再保存' if not degraded
                               else 'AI 暂不可用，已按你的学习数据列出待填写框架'})


@api_learning_bp.route('/learning/insights/user/<int:uid>', methods=['GET'])
def api_insight_user_public(uid):
    """他人主页：某人公开的心得列表（只给预览，正文仍走详情接口）。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    rows = (StudyInsight.query.filter_by(user_id=uid, is_public=True)
            .order_by(StudyInsight.updated_at.desc()).limit(50).all())
    owner = db.session.get(User, uid)
    return jsonify({'items': [_insight_to_dict(r, with_content=False) for r in rows],
                    'username': owner.username if owner else None,
                    'section_labels': INSIGHT_SECTION_LABELS})


@api_learning_bp.route('/learning/insights/<int:iid>', methods=['GET'])
def api_insight_detail(iid):
    """心得详情：本人全量；他人只能读已公开的，并计一次浏览。

    未公开对外与「不存在」同口径，不回「无权限」——否则公开开关就成了探测别人
    写过哪些心得的探针。教师也没有默认读权：心得是私人复盘，不是作业。
    """
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    i = db.session.get(StudyInsight, iid)
    if not i:
        return jsonify({'message': '心得不存在'}), 404
    if i.user_id != user.id:
        if not i.is_public:
            return jsonify({'message': '心得不存在'}), 404
        i.views = int(i.views or 0) + 1
        db.session.commit()
        owner = db.session.get(User, i.user_id)
        data = _insight_to_dict(i)
        # 公开心得不外显关联的计划标题以外的私人线索：知识点与预览都是本人写的内容，保留
        data['owner'] = {'id': i.user_id, 'username': owner.username if owner else None}
        return jsonify(data)
    return jsonify(_insight_to_dict(i))


@api_learning_bp.route('/learning/insights/<int:iid>', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_insight_update(iid):
    """修改心得（仅本人）：三段、周期、标签、关联项都可改，公开状态另走 public 接口。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    i = db.session.get(StudyInsight, iid)
    if not i or i.user_id != user.id:
        return jsonify({'message': '心得不存在'}), 404
    data = request.get_json(silent=True) or {}
    period_type = (data.get('period_type') or i.period_type).strip()
    try:
        sections = _clean_insight_sections(data) if any(
            k in data for k in INSIGHT_SECTION_LABELS) else None
        s, e, note = _insight_range(period_type, data.get('period_start') or (i.period_start and iso_local(i.period_start)),
                                    data.get('period_end') or (i.period_end and iso_local(i.period_end)),
                                    data.get('period_note', i.period_note))
    except ValueError as err:
        return jsonify({'message': str(err)}), 400
    if 'title' in data:
        t = str(data.get('title') or '').strip()[:200]
        if not t:
            return jsonify({'message': '标题不能为空'}), 400
        i.title = t
    i.period_type, i.period_start, i.period_end, i.period_note = period_type, s, e, note
    if 'tags' in data:
        i.tags = _clean_insight_tags(data.get('tags'))
    if 'plan_id' in data:
        i.plan_id = data.get('plan_id') or None
    if 'knowledge_point_id' in data:
        i.knowledge_point_id = data.get('knowledge_point_id') or None
    if sections:
        for key, text in sections.items():
            setattr(i, key, text)
    db.session.commit()
    return jsonify({'message': '已保存', 'insight': _insight_to_dict(i)})


@api_learning_bp.route('/learning/insights/<int:iid>', methods=['DELETE'])
def api_insight_delete(iid):
    """删除心得（仅本人）。已分享出去的社区帖不跟着删：帖子在社区有独立的删除流程。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    i = db.session.get(StudyInsight, iid)
    if not i or i.user_id != user.id:
        return jsonify({'message': '心得不存在'}), 404
    db.session.delete(i)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_learning_bp.route('/learning/insights/<int:iid>/public', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_insight_public(iid):
    """公开 / 撤下心得（仅本人）：公开后他人可在其主页与详情读到全文。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    i = db.session.get(StudyInsight, iid)
    if not i or i.user_id != user.id:
        return jsonify({'message': '心得不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'is_public' not in data:
        return jsonify({'message': '请提供 is_public'}), 400
    i.is_public = bool(data.get('is_public'))
    db.session.commit()
    return jsonify({'message': '已公开' if i.is_public else '已设为私有',
                    'is_public': i.is_public, 'views': int(i.views or 0)})


@api_learning_bp.route('/learning/insights/<int:iid>/share', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_insight_share(iid):
    """把心得发成社区经验帖，并顺带公开。

    分享即公开：正文都整篇贴到社区里了，本体还标私有就是「帖能看、心得不能看」的割裂，
    浏览数也无处累计。原帖还在时直接回原帖 id，连点两次不会刷出两串一样的经验帖。
    """
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    i = db.session.get(StudyInsight, iid)
    if not i or i.user_id != user.id:
        return jsonify({'message': '心得不存在'}), 404
    if i.share_post_id:
        from database.models import CommunityPost
        alive = db.session.get(CommunityPost, i.share_post_id)
        if alive is not None and not alive.deleted:
            return jsonify({'message': '这篇心得已经分享过了', 'post_id': alive.id,
                            'existed': True, 'is_public': bool(i.is_public)}), 200
        i.share_post_id = None

    text = _insight_to_dict(i)
    body = [f'> 来自为学空间·学习心得（{text["period_text"]}）', '']
    for key, label in INSIGHT_SECTION_LABELS.items():
        seg = (text.get(key) or '').strip()
        if seg:
            body += [f'## {label}', '', seg, '']
    if not any((text.get(k) or '').strip() for k in INSIGHT_SECTION_LABELS):
        return jsonify({'message': '心得还是空的，先写点内容再分享'}), 400
    data = request.get_json(silent=True) or {}
    note = str(data.get('note') or '').strip()[:300]
    if note:
        body += ['---', '', note]

    from utils.community_bridge import sync_to_community
    post = sync_to_community(
        actor_id=user.id,
        category='experience',
        title=f'[学习心得] {i.title}',
        content='\n'.join(body),
        tags=list(i.tags or []) + [text['period_label']],
        anonymous=bool(data.get('anonymous')),
    )
    i.is_public = True
    i.share_post_id = post.id
    db.session.commit()

    # 通知是旁路：帖已发成、库已落，写挂不能反过来把分享报成失败
    try:
        create_notification(user.id, '心得已分享到社区',
                            f'「{i.title}」已发布为社区经验帖。',
                            type='success', related_type='community_post', related_id=post.id)
    except Exception:
        db.session.rollback()
        logger.exception('[learning] 心得分享通知创建失败 post_id=%s', post.id)
    return jsonify({'message': '已分享到社区中心', 'post_id': post.id, 'is_public': True}), 201


# ══ v4.4 学习体验升级：AI 会话持久化/流式 · 错题归因 · 专注计时 · 打卡心情 · 自由笔记 · 讲解卡 · 图片上传 ══

# ── AI 学习助手会话 ──────────────────────────────────────────────

def _conversation_to_dict(c, with_unread=False):
    return {'id': c.id, 'title': c.title, 'context': c.context,
            'message_count': len(c.messages),
            'created_at': iso_local(c.created_at), 'updated_at': iso_local(c.updated_at)}


@api_learning_bp.route('/learning/ai-conversations', methods=['GET'])
def api_ai_conversation_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    convs = AiChatConversation.query.filter_by(user_id=user.id) \
        .order_by(AiChatConversation.updated_at.desc()).limit(50).all()
    return jsonify({'items': [_conversation_to_dict(c) for c in convs]})


@api_learning_bp.route('/learning/ai-conversations', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_ai_conversation_create():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    conv = AiChatConversation(
        user_id=user.id,
        title=(str(data.get('title') or '').strip() or '新的对话')[:100],
        context=str(data.get('context') or '').strip()[:60] or None,
    )
    db.session.add(conv)
    db.session.commit()
    return jsonify({'message': '已创建', 'conversation': _conversation_to_dict(conv)})


@api_learning_bp.route('/learning/ai-conversations/<int:cid>/messages', methods=['GET'])
def api_ai_conversation_messages(cid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    conv = db.session.get(AiChatConversation, cid)
    if not conv or conv.user_id != user.id:
        return jsonify({'message': '会话不存在'}), 404
    items = sorted(conv.messages, key=lambda m: m.id)
    return jsonify({
        'conversation': _conversation_to_dict(conv),
        'items': [{'id': m.id, 'role': m.role, 'content': m.content,
                   'degraded': m.degraded, 'created_at': iso_local(m.created_at)} for m in items],
    })


@api_learning_bp.route('/learning/ai-conversations/<int:cid>', methods=['DELETE'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_ai_conversation_delete(cid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    conv = db.session.get(AiChatConversation, cid)
    if not conv or conv.user_id != user.id:
        return jsonify({'message': '会话不存在'}), 404
    db.session.delete(conv)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_learning_bp.route('/learning/ai-chat/stream', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_learning_ai_chat_stream():
    """SSE 流式学习助手对话：逐 token 推送 delta，完成后双端消息落库；
    AI 不可用时推送规则化降级回复并标记 degraded"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    message = str(data.get('message') or '').strip()[:4000]
    context = str(data.get('context') or '').strip()[:600]
    if not message:
        return jsonify({'message': '请输入您的问题'}), 400

    allowed, _quota = check_ai_quota(user)
    if not allowed:
        return jsonify({'message': '今日 AI 额度已用完，请明天再来或咨询教师调整配额'}), 429
    t0 = time.perf_counter()

    cid = data.get('conversation_id')
    conv = db.session.get(AiChatConversation, cid) if cid else None
    if conv and conv.user_id != user.id:
        return jsonify({'message': '会话不存在'}), 404
    if not conv:
        conv = AiChatConversation(user_id=user.id, title=message[:30],
                                  context=context[:60] or None)
        db.session.add(conv)
        db.session.flush()

    history = [{'role': m.role, 'content': m.content}
               for m in sorted(conv.messages, key=lambda m: m.id)]
    window = (history + [{'role': 'user', 'content': message}])[-12:]
    db.session.add(AiChatMessage(conversation_id=conv.id, role='user', content=message))
    db.session.commit()   # 用户消息先落库，流式期间不持有事务

    from ai_service.services import build_chat_system, chat_stream_iter
    system = build_chat_system(context)

    def event_gen():
        pieces = []
        yield f"data: {json.dumps({'conversation_id': conv.id}, ensure_ascii=False)}\n\n"
        try:
            for delta in chat_stream_iter(window, system):
                pieces.append(delta)
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        finally:
            full = ''.join(pieces)
            degraded = full.startswith('【AI 服务暂不可用')
            if full:
                db.session.add(AiChatMessage(conversation_id=conv.id, role='assistant',
                                             content=full[:8000], degraded=degraded))
                charge_ai_quota(user)
            log_ai_usage(user.id, 'chat_stream',
                         'degraded' if degraded else ('success' if full else 'fail'),
                         (time.perf_counter() - t0) * 1000)
            conv.updated_at = utcnow()
            db.session.commit()
            yield f"data: {json.dumps({'done': True, 'degraded': degraded}, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(event_gen()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ── 错题逐题 AI 归因 ────────────────────────────────────────

def _rule_wrong_analysis(question, wrong_answer, wrong_count):
    """AI 不可用时的规则化归因兑底：基于错答形态给出通用建议"""
    objective = question.type in ('single_choice', 'multiple_choice', 'true_false', 'fill_blank')
    lines = [f"本题考察：{question.knowledge or question.type}。"]
    if not (wrong_answer or '').strip():
        lines.append('本次未作答，建议优先补学时并重新挑战本题。')
    elif objective:
        lines.append('答案与正确答案不一致，常见原因是概念辨析不清或审题疏漏，' '请逐条对照解析排查干扰项。')
    else:
        lines.append('主观题作答与参考答案存在差距，建议对照解析拆解得分点，组齐答题提纲。')
    if (wrong_count or 1) >= 2:
        lines.append('该题已多次答错，建议加入今日复习队列重点攻克。')
    return '\n'.join(lines)


@api_learning_bp.route('/learning/wrong-records/<int:wr_id>/analyze', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_wrong_analyze(wr_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    rec = db.session.get(WrongAnswerRecord, wr_id)
    if not rec or rec.user_id != user.id:
        return jsonify({'message': '错题记录不存在'}), 404
    # v5.2 答案门控：来源仍可重答时归因可能泄露答案，暂不提供
    if _source_still_reanswerable(user.id, rec.source_type, rec.source_id):
        return jsonify({'message': '当前来源仍可重答，AI 归因在作答截止/批改完成后开放',
                        'answer_hidden': True}), 403
    question = rec.question
    if not question:
        return jsonify({'message': '关联题目已不存在，无法分析'}), 400

    source = 'ai'
    t0 = time.perf_counter()
    try:
        from ai_service.services import ai_analyze_wrong_answer
        analysis = ai_analyze_wrong_answer(db.session, question,
                                           rec.wrong_answer, rec.wrong_count or 1)
    except Exception:
        logger.exception('错题 AI 归因失败，降级规则建议')
        analysis = _rule_wrong_analysis(question, rec.wrong_answer, rec.wrong_count or 1)
        source = 'rule'
    log_ai_usage(user.id, 'wrong_analyze',
                 'degraded' if source == 'rule' else 'success',
                 (time.perf_counter() - t0) * 1000)
    rec.ai_analysis = (analysis or '').strip()[:4000]
    rec.ai_analyzed_at = utcnow()
    db.session.commit()
    return jsonify({'analysis': rec.ai_analysis, 'source': source,
                    'ai_analyzed_at': iso_local(rec.ai_analyzed_at)})


# ── 专注计时（番茄钟/正计时） ──────────────────────────────────

_FOCUS_MAX_MIN = 180   # 单次计划上限 3 小时


def _focus_to_dict(f):
    elapsed = None
    if f.status == 'running' and f.started_at:
        elapsed = max(0, int((utcnow() - f.started_at).total_seconds()))
    return {'id': f.id, 'topic': f.topic, 'mode': f.mode,
            'planned_min': f.planned_min, 'actual_sec': f.actual_sec,
            'status': f.status, 'elapsed_sec': elapsed,
            'started_at': iso_local(f.started_at),
            'ended_at': iso_local(f.ended_at) if f.ended_at else None}


@api_learning_bp.route('/learning/focus/sessions', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_focus_start():
    """开始专注会话：已有进行中会话则自动作废（dropped）后新建"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    mode = data.get('mode') if data.get('mode') in ('pomodoro', 'stopwatch') else 'pomodoro'
    try:
        planned = int(data.get('planned_min') or 25)
    except (TypeError, ValueError):
        planned = 25
    planned = max(1, min(planned, _FOCUS_MAX_MIN))

    stale = FocusSession.query.filter_by(user_id=user.id, status='running').all()
    now = utcnow()
    for s in stale:
        s.status = 'dropped'
        s.actual_sec = max(0, int((now - s.started_at).total_seconds()))
        s.ended_at = now
    f = FocusSession(user_id=user.id, topic=str(data.get('topic') or '').strip()[:200] or None,
                     mode=mode, planned_min=planned)
    db.session.add(f)
    db.session.commit()
    return jsonify({'message': '已开始', 'session': _focus_to_dict(f)})


@api_learning_bp.route('/learning/focus/sessions/<int:fid>/finish', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_focus_finish(fid):
    """结束专注会话：服务端按起止时间结算时长；有效专注（≥1分钟）计入当日打卡分钟数"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    f = db.session.get(FocusSession, fid)
    if not f or f.user_id != user.id:
        return jsonify({'message': '专注会话不存在'}), 404
    if f.status != 'running':
        return jsonify({'message': '该会话已结束', 'session': _focus_to_dict(f)})
    data = request.get_json(silent=True) or {}
    abort_early = bool(data.get('abandoned'))
    now = utcnow()
    f.actual_sec = max(0, int((now - f.started_at).total_seconds()))
    f.ended_at = now
    f.status = 'dropped' if abort_early else 'finished'
    minutes = f.actual_sec // 60
    if f.status == 'finished' and minutes >= 1:
        eng.touch_checkin(user.id, minutes=minutes)
    db.session.commit()
    return jsonify({'message': '已结束', 'session': _focus_to_dict(f),
                    'checkin_minutes': minutes if f.status == 'finished' else 0})


@api_learning_bp.route('/learning/focus/stats', methods=['GET'])
def api_focus_stats():
    """近 N 日专注时长统计（默认 14 天）：每日分钟数 + 计划达成率"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    try:
        days = max(1, min(int(request.args.get('days') or 14), 90))
    except (TypeError, ValueError):
        days = 14
    since = utcnow() - timedelta(days=days)
    items = FocusSession.query.filter_by(user_id=user.id, status='finished') \
        .filter(FocusSession.started_at >= since).all()
    per_day = defaultdict(lambda: {'sec': 0, 'planned_sec': 0, 'sessions': 0})
    for f in items:
        # 与打卡一致：UTC 日口径
        key = f.started_at.astimezone(timezone.utc).date().isoformat() if f.started_at else None
        if not key:
            continue
        per_day[key]['sec'] += f.actual_sec or 0
        per_day[key]['planned_sec'] += (f.planned_min or 0) * 60
        per_day[key]['sessions'] += 1
    total_sec = sum(v['sec'] for v in per_day.values())
    return jsonify({'days': days, 'total_min': total_sec // 60,
                    'per_day': [{'day': k, 'minutes': v['sec'] // 60,
                                 'planned_minutes': v['planned_sec'] // 60,
                                 'sessions': v['sessions']} for k, v in sorted(per_day.items())]})


# ── 打卡心情与日志 ──────────────────────────────────────

_MOODS = ('happy', 'calm', 'tired', 'frustrated')


@api_learning_bp.route('/learning/checkin-feel', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_checkin_feel():
    """提交/更新今日打卡心情与总结（行为打卡之外的主动记录，可反复修改）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    mood = str(data.get('mood') or '').strip()
    content = str(data.get('content') or '').strip()
    if mood and mood not in _MOODS:
        return jsonify({'message': '心情取值不合法'}), 400
    if len(content) > 1000:
        return jsonify({'message': '今日总结不能超过 1000 字'}), 400
    if not mood and not content:
        return jsonify({'message': '请至少选择心情或填写总结'}), 400
    c = eng.touch_checkin(user.id)
    if mood:
        c.mood = mood
    if content:
        c.content = content[:1000]
    db.session.commit()
    return jsonify({'message': '已记录', 'day': c.day.isoformat(),
                    'mood': c.mood, 'content': c.content})


@api_learning_bp.route('/learning/checkin-calendar', methods=['GET'])
def api_checkin_calendar():
    """月度打卡日历：每日分钟数/心情/是否打卡，驱动热力图与心情趋势"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    raw = request.args.get('month') or local_today().strftime('%Y-%m')
    try:
        y, m = (int(x) for x in raw.split('-')[:2])
        first = date(y, m, 1)
    except (ValueError, TypeError):
        return jsonify({'message': 'month 格式应为 YYYY-MM'}), 400
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    rows = StudyCheckin.query.filter_by(user_id=user.id) \
        .filter(StudyCheckin.day >= first, StudyCheckin.day < nxt).all()
    return jsonify({'month': raw, 'days': [{
        'day': c.day.isoformat(), 'minutes': c.minutes or 0,
        'tasks_done': c.tasks_done or 0, 'mood': c.mood,
        'content': (c.content or '')[:120] or None,
    } for c in sorted(rows, key=lambda x: x.day)]})


# ── 自由学习笔记 ──────────────────────────────────────

_NOTE_CONTENT_MAX = 20000

_MD_LINK_RE = re.compile(r'!?\[([^\]]*)\]\(([^)\s]*)\)')


def _md_excerpt(text, limit=100):
    """把 Markdown 正文压成卡片摘要：去图片/链接语法（保留链接文字）、代码块、
    标题/列表/引用符号与强调星号，公式折叠为「[公式]」，并压缩空白。

    旧实现 `re.sub('[#*`>-]', '')` 会把正文里的连字符一并删掉，却管不住
    `![图](/uploads/x.png)` 与 `$$\\lim\\dots$$` 这种源码噪声直接露到卡片上，故收敛为专用函数。
    """
    s = text or ''
    s = re.sub(r'```[\s\S]*?```', ' ', s)                    # 代码块整体去掉
    # 公式（先于行内码处理，统一折叠为一个标记，不致摘要被 LaTeX 源码占满）
    s = re.sub(r'\$\$[\s\S]+?\$\$', '[公式]', s)
    s = re.sub(r'\\\([\s\S]+?\\\)', '[公式]', s)
    s = re.sub(r'\\\[([\s\S]+?)\\\]', '[公式]', s)
    # 行内 $...$：沿用 RichContent 的严格口径（首尾不得为空白），避免「$10 与 $20」这类金额被误折叠
    s = re.sub(r'\$([^\s$](?:[^$]*?[^\s$])?)\$', '[公式]', s)
    s = _MD_LINK_RE.sub(lambda m: m.group(1) or ' ', s)      # [文字](链) / ![](链) → 文字
    s = re.sub(r'`([^`]*)`', r'\1', s)                       # 行内码
    s = re.sub(r'^\s{0,3}#{1,6}\s*', '', s, flags=re.M)      # 标题
    s = re.sub(r'^\s{0,3}(?:[-*+]|\d+[.、])\s+', '', s, flags=re.M)  # 列表符号
    s = re.sub(r'^\s{0,3}>\s?', '', s, flags=re.M)           # 引用
    s = re.sub(r'\*\*|\*|~~|==', '', s)                      # 强调/删除线（不动下划线，避免碎标识符）
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:limit]


def _note_to_dict(n, brief=False):
    d = {'id': n.id, 'title': n.title, 'category': n.category,
         'tags': n.tags or [], 'pinned': bool(n.pinned), 'source': n.source,
         'attachments': [{'filename': a.get('filename'), 'size': a.get('size', 0)}
                         for a in (n.attachment_json or [])],
         'created_at': iso_local(n.created_at), 'updated_at': iso_local(n.updated_at)}
    if brief:
        d['excerpt'] = _md_excerpt(n.content, 100)
    else:
        d['content'] = n.content
    return d


def _clean_note_tags(raw):
    """标签列表清洗：去重、去空、每项≤20字、最多 8 个"""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for t in raw:
        t = str(t or '').strip()[:20]
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:8]


@api_learning_bp.route('/learning/notes', methods=['GET'])
def api_note_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    kw = (request.args.get('q') or '').strip()
    tag = (request.args.get('tag') or '').strip()
    category = (request.args.get('category') or '').strip()
    query = StudyNote.query.filter_by(user_id=user.id)
    if kw:
        like = f'%{kw}%'
        query = query.filter(or_(StudyNote.title.like(like), StudyNote.content.like(like)))
    if tag:
        # tags 为 JSON 字符串数组，用序列化后的带引号片段精确匹配元素
        query = query.filter(StudyNote.tags.like(f'%"{tag}"%'))
    if category:
        query = query.filter_by(category=category)
    items = query.order_by(StudyNote.pinned.desc(), StudyNote.updated_at.desc()).limit(200).all()
    all_tags = sorted({t for n in StudyNote.query.filter_by(user_id=user.id).all()
                       for t in (n.tags or [])})
    categories = sorted({n.category for n in StudyNote.query.filter_by(user_id=user.id).all()
                         if n.category})
    return jsonify({'total': len(items),
                    'items': [_note_to_dict(n, brief=True) for n in items],
                    'tags': all_tags, 'categories': categories})


@api_learning_bp.route('/learning/notes', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_note_create():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    content = str(data.get('content') or '').strip()
    if not title:
        return jsonify({'message': '笔记标题不能为空'}), 400
    if len(content) > _NOTE_CONTENT_MAX:
        return jsonify({'message': f'笔记内容不能超过 {_NOTE_CONTENT_MAX} 字'}), 400
    n = StudyNote(user_id=user.id, title=title[:200], content=content,
                  category=str(data.get('category') or '').strip()[:50] or None,
                  tags=_clean_note_tags(data.get('tags')))
    db.session.add(n)
    db.session.commit()
    return jsonify({'message': '已创建', 'note': _note_to_dict(n)})


@api_learning_bp.route('/learning/notes/<int:nid>', methods=['GET'])
def api_note_detail(nid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    n = db.session.get(StudyNote, nid)
    if not n or n.user_id != user.id:
        return jsonify({'message': '笔记不存在'}), 404
    return jsonify(_note_to_dict(n))


@api_learning_bp.route('/learning/notes/<int:nid>', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_note_update(nid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    n = db.session.get(StudyNote, nid)
    if not n or n.user_id != user.id:
        return jsonify({'message': '笔记不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        title = str(data.get('title') or '').strip()
        if not title:
            return jsonify({'message': '笔记标题不能为空'}), 400
        n.title = title[:200]
    if 'content' in data:
        content = str(data.get('content') or '')
        if len(content) > _NOTE_CONTENT_MAX:
            return jsonify({'message': f'笔记内容不能超过 {_NOTE_CONTENT_MAX} 字'}), 400
        n.content = content
    if 'category' in data:
        n.category = str(data.get('category') or '').strip()[:50] or None
    if 'tags' in data:
        n.tags = _clean_note_tags(data.get('tags'))
    if 'pinned' in data:
        n.pinned = bool(data.get('pinned'))
    db.session.commit()
    return jsonify({'message': '已保存', 'note': _note_to_dict(n)})


@api_learning_bp.route('/learning/notes/<int:nid>', methods=['DELETE'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_note_delete(nid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    n = db.session.get(StudyNote, nid)
    if not n or n.user_id != user.id:
        return jsonify({'message': '笔记不存在'}), 404
    db.session.delete(n)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ── 知识点讲解卡 ──────────────────────────────────────

def _explain_to_dict(e):
    kp = e.knowledge_point
    return {'id': e.id, 'topic': e.topic, 'content': e.content,
            'knowledge_point_id': e.knowledge_point_id,
            'knowledge_point_name': kp.name if kp else None,
            'created_at': iso_local(e.created_at)}


@api_learning_bp.route('/learning/explain', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_explain_generate():
    """即问即讲：输入任意主题生成讲解卡并持久化；AI 不可用时降级为框架性提示"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    topic = str(data.get('topic') or '').strip()
    if not topic:
        return jsonify({'message': '请输入讲解主题'}), 400
    topic = topic[:200]

    allowed, _quota = check_ai_quota(user)
    if not allowed:
        return jsonify({'message': '今日 AI 额度已用完，请明天再来或咨询教师调整配额'}), 429

    # 命中库内知识点时把描述作为术语对齐提示传给 AI
    kp = KnowledgePoint.query.filter(func.lower(KnowledgePoint.name) == topic.lower()).first() \
        or KnowledgePoint.query.filter(KnowledgePoint.name.like(f'%{topic}%')).first()
    source = 'ai'
    t0 = time.perf_counter()
    try:
        from ai_service.services import ai_explain_topic
        content = ai_explain_topic(db.session, topic, kp.description if kp else None)
    except Exception:
        logger.exception('AI 讲解卡生成失败，降级框架提示')
        content = (
            f"## 一句话说清楚\n「{topic}」的准确定义建议查阅课程资料或问 AI 学习助手获取。\n\n"
            "## 建议行动\n- 在错题本搜索相关题目，从解析中反向理解概念\n"
            "- 到学习路径中找到对应节点完成系统学习\n- AI 恢复后重新生成完整讲解卡\n\n"
            "（AI 服务暂不可用，本卡片为系统自动生成的框架提示）"
        )
        source = 'rule'
    charge_ai_quota(user)
    log_ai_usage(user.id, 'explain',
                 'degraded' if source == 'rule' else 'success',
                 (time.perf_counter() - t0) * 1000)
    card = ExplainCard(user_id=user.id, topic=topic, content=content[:8000],
                       knowledge_point_id=kp.id if kp else None)
    db.session.add(card)
    db.session.commit()
    return jsonify({'card': _explain_to_dict(card), 'source': source})


@api_learning_bp.route('/learning/explain/list', methods=['GET'])
def api_explain_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    items = ExplainCard.query.filter_by(user_id=user.id) \
        .order_by(ExplainCard.created_at.desc()).limit(50).all()
    return jsonify({'items': [_explain_to_dict(e) for e in items]})


@api_learning_bp.route('/learning/explain/<int:eid>', methods=['DELETE'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_explain_delete(eid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    card = db.session.get(ExplainCard, eid)
    if not card or card.user_id != user.id:
        return jsonify({'message': '讲解卡不存在'}), 404
    db.session.delete(card)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_learning_bp.route('/learning/explain/<int:eid>/to-note', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_explain_to_note(eid):
    """讲解卡一键转存为学习笔记"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    card = db.session.get(ExplainCard, eid)
    if not card or card.user_id != user.id:
        return jsonify({'message': '讲解卡不存在'}), 404
    n = StudyNote(user_id=user.id, title=f"讲解卡·{card.topic}",
                  content=card.content, category='讲解卡',
                  tags=[card.knowledge_point.name] if card.knowledge_point else [],
                  source='explain')
    db.session.add(n)
    db.session.commit()
    return jsonify({'message': '已转存为笔记', 'note': _note_to_dict(n, brief=True)})


# ── 学习附件上传（v4.6 统一白名单：文档/表格/压缩包/图片/视频/代码）────

_UPLOAD_DIR = UPLOAD_DIR  # 与竞赛/悬/作业共用 utils/uploads 公共落盘目录

# 笔记配图内嵌仍限图片、≤5MB（统一白名单的子集）
_NOTE_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
_NOTE_IMAGE_MAX_BYTES = 5 * 1024 * 1024


@api_learning_bp.route('/learning/upload', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_learning_upload():
    """笔记配图内嵌上传：仅限图片、单文件≤5MB，UUID 命名存入 uploads/，复用 /uploads 静态通道"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'message': '请选择文件'}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _NOTE_IMAGE_EXTS:
        return jsonify({'message': '仅支持 png/jpg/jpeg/gif/webp 图片'}), 400
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > _NOTE_IMAGE_MAX_BYTES:
        return jsonify({'message': '图片大小不能超过 5MB'}), 400
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    name = f"note_{uuid.uuid4().hex}{ext}"
    file.save(os.path.join(_UPLOAD_DIR, name))
    return jsonify({'message': '已上传', 'url': f'/uploads/{name}', 'name': file.filename})


@api_learning_bp.route('/learning/attachments', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_learning_attachment():
    """学习附件上传（v4.6）：文档/表格(csv/xls/xlsx)/压缩包/图片/视频/代码，≤50MB；
    传 note_id 时挂到本人笔记附件；否则仅落盘返回下载 url（供资料等场景引用）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    file = request.files.get('file')
    try:
        stored, size = save_upload(file, 'learn_att', _UPLOAD_DIR)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    note_id = (request.form.get('note_id') or '').strip()
    if note_id:
        note = db.session.get(StudyNote, int(note_id or 0))
        if not note or note.user_id != user.id:
            return jsonify({'message': '笔记不存在'}), 404
        if len(note.attachment_json or []) >= 9:
            return jsonify({'message': '单条笔记最多 9 个附件'}), 400
        atts = list(note.attachment_json or [])
        atts.append({'filename': file.filename, 'stored_name': stored, 'size': size,
                     'uploaded_at': utcnow().isoformat()})
        note.attachment_json = atts
        db.session.commit()
        return jsonify({'message': '附件已上传', 'attachments': len(atts),
                        'url': f'/learning/attachments/{note.id}/0/download'}), 201
    return jsonify({'message': '已上传', 'url': f'/uploads/{stored}',
                    'stored_name': stored, 'ext': os.path.splitext(file.filename)[1].lower(),
                    'name': file.filename, 'size': size}), 201


@api_learning_bp.route('/learning/attachments/<int:nid>/<int:idx>/download', methods=['GET'])
def api_learning_attachment_download(nid, idx):
    """笔记附件下载：仅本人（note 为个人资产）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    note = db.session.get(StudyNote, nid)
    if not note or note.user_id != user.id:
        return jsonify({'message': '无权下载该附件'}), 403
    atts = note.attachment_json or []
    if idx < 0 or idx >= len(atts):
        return jsonify({'message': '附件不存在'}), 404
    att = atts[idx]
    return send_from_directory(_UPLOAD_DIR, att['stored_name'],
                               as_attachment=True, download_name=att.get('filename'))


@api_learning_bp.route('/learning/attachments/<int:nid>/<int:idx>', methods=['DELETE'])
def api_learning_attachment_delete(nid, idx):
    """删除本人笔记附件"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    note = db.session.get(StudyNote, nid)
    if not note or note.user_id != user.id:
        return jsonify({'message': '笔记不存在'}), 404
    atts = list(note.attachment_json or [])
    if idx < 0 or idx >= len(atts):
        return jsonify({'message': '附件不存在'}), 404
    atts.pop(idx)
    note.attachment_json = atts
    db.session.commit()
    return jsonify({'message': '已删除附件', 'attachments': len(atts)})


# ═══════════ v4.5 学习社区：个人资料库 / 广场 / 社交 / AI 治理 ═══════════

# 资料形态全集：AI 可生成的形态（见 services.MATERIAL_TEMPLATES）+ 手写。新增 AI
# 形态需同时改模板、models 的 _material_kind_ck 与一条改 CHECK 的迁移（有护栏用例）。
_MATERIAL_KINDS = ('video_script', 'mindmap', 'lecture', 'summary', 'quiz',
                   'lesson_plan', 'manual')

# ── v7.18 资料附件：用户自行添加文档/链接/视频/图片/思维导图 ──
# 一条资料最多 20 个附件（笔记那边是 9，资料常是「一节课全套素材」故放宽）
_MATERIAL_ATT_MAX = 20
# 后缀 → 展示类型（前端据此选渲染器：图/视频/PDF 内联， Office 文档只给下载）
_ATT_TYPE_BY_EXT = {
    '.doc': 'doc', '.docx': 'doc', '.txt': 'text', '.md': 'text', '.markdown': 'text',
    '.pdf': 'pdf',
    '.xls': 'sheet', '.xlsx': 'sheet', '.csv': 'sheet',
    '.ppt': 'slide', '.pptx': 'slide',
    '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.gif': 'image', '.webp': 'image',
    '.mp4': 'video', '.webm': 'video',
    '.zip': 'archive', '.rar': 'archive', '.7z': 'archive',
    '.py': 'code', '.java': 'code', '.c': 'code', '.cpp': 'code',
    '.js': 'code', '.ts': 'code', '.css': 'code', '.sql': 'code', '.html': 'code',
}
# 链接类附件允许声明的展示形态（外链不下载，按类型内嵌/新开窗口）
_ATT_LINK_TYPES = ('link', 'video', 'image', 'mindmap')
# 内联可读的纯文本类后缀（思维导图的 mermaid/markdown 源文件走这一路）
_ATT_TEXT_EXTS = ('.txt', '.md', '.markdown')


def _att_type(ext, declared=None):
    """附件展示类型：优先用户指定（link/mindmap 等无后缀形态），否则按后缀查表。"""
    if declared in ('link', 'mindmap'):
        return declared
    return _ATT_TYPE_BY_EXT.get((ext or '').lower(), 'doc')


def _normalize_attachments(raw):
    """校验并规范化附件列表（写库前唯一入口，不接受裸传结构直接落库）。

    两类条目：
    - 文件类：{stored_name|filename,size,ext} —— stored_name 必须是单个路径段（挡目录穿越），
      后缀必须在上传白名单内（与 utils/uploads.py 同一口径，防绕过前端直传）；
    - 链接类：{url} —— 只收 http(s)，javascript:/data: 一律拒。
    非法条目直接丢弃（不整批报错）：用户粘了一堆链接不该因为其中一条格式不对就全存不下。
    """
    if not isinstance(raw, list):
        return []
    out = []
    for it in raw[:_MATERIAL_ATT_MAX]:
        if not isinstance(it, dict):
            continue
        url = str(it.get('url') or '').strip()[:1000]
        stored = os.path.basename(str(it.get('stored_name') or '').strip())
        name = str(it.get('name') or it.get('filename') or '').strip()[:200]
        if url and not stored:
            if not url.lower().startswith(('http://', 'https://')):
                continue
            declared = str(it.get('type') or 'link')
            if declared not in _ATT_LINK_TYPES:
                declared = 'link'
            out.append({'name': name or url[:80], 'type': declared, 'ext': '',
                        'url': url, 'size': 0,
                        'uploaded_at': str(it.get('uploaded_at') or '')[:32] or utcnow().isoformat()})
            continue
        if not stored:
            continue
        ext = os.path.splitext(stored)[1].lower()
        if ext not in _UPLOAD_EXTS:
            continue                      # 白名单外后缀：不落库，免得留下一条点不开的附件
        try:
            size = int(it.get('size') or 0)
        except (TypeError, ValueError):
            size = 0
        out.append({'name': name or stored, 'type': _att_type(ext, str(it.get('type') or '')),
                    'ext': ext, 'stored_name': stored, 'size': size,
                    'uploaded_at': str(it.get('uploaded_at') or '')[:32] or utcnow().isoformat()})
    return out


def _attachments_out(m):
    """附件输出：补上前端直接可用的 url 与受控下载/预览地址。

    图片/视频/PDF 走 /uploads/（UUID 名不可枚举，与笔记插图、题面图同一口径）；
    Office 文档与压缩包只给 API 下载地址（浏览器开不了 docx，内联只会是个碎图）。
    .html 附件不给内联预览：上传白名单里 html 属「代码」类，同源内联别人写的 html
    等于把存储型 XSS 请进来，故只下载（思维导图请用 mermaid/markdown 源文件或图片）。"""
    out = []
    for i, a in enumerate(m.attachment_json or []):
        if not isinstance(a, dict):
            continue
        d = dict(a)
        stored = d.get('stored_name')
        if stored:
            d['url'] = f'/uploads/{stored}'
            d['download_url'] = f'/api/learning/materials/{m.id}/attachments/{i}/download'
            d['inline_url'] = (f'/api/learning/materials/{m.id}/attachments/{i}/download?inline=1'
                               if d.get('type') in ('image', 'video', 'pdf', 'text') else None)
        else:
            d['url'] = d.get('url') or ''
            d['download_url'] = d['url']
            d['inline_url'] = d['url'] if d.get('type') in ('image', 'video') else None
        out.append(d)
    return out


def _material_to_dict(m, with_content=False, current_user_id=None):
    d = {'id': m.id, 'title': m.title, 'kind': m.kind, 'subject': m.subject,
         'difficulty': m.difficulty, 'folder_id': m.folder_id, 'source': m.source,
         'is_public': bool(m.is_public), 'views': m.views,
         'status': m.status, 'knowledge_point_id': m.knowledge_point_id,
         'plan_id': m.plan_id, 'task_id': m.task_id,
         'author': m.user.username if m.user else None, 'owner_id': m.user_id,
         'fav_count': len(m.favorites),
         'attachments': _attachments_out(m),
         'excerpt': _md_excerpt(m.content, 80),
         'created_at': iso_local(m.created_at), 'updated_at': iso_local(m.updated_at)}
    if current_user_id is not None:
        d['is_favorited'] = any(f.user_id == current_user_id for f in m.favorites)
    if with_content:
        d['content'] = m.content
    return d


def _get_own_material(user, mid):
    m = db.session.get(StudyMaterial, mid)
    if not m or m.user_id != user.id:
        return None, (jsonify({'message': '资料不存在'}), 404)
    return m, None


@api_learning_bp.route('/learning/materials/generate', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_material_generate():
    """AI 多形态资料生成：kind=auto 时先判体量再选形态；生成后自动入库（私有）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    prompt = str(data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'message': '请输入知识点主题'}), 400
    prompt = prompt[:500]
    kind = str(data.get('kind') or 'auto')
    subject = str(data.get('subject') or '').strip()[:50] or None
    difficulty = str(data.get('difficulty') or '').strip()[:20] or None

    allowed, _quota = check_ai_quota(user)
    if not allowed:
        return jsonify({'message': '今日 AI 额度已用完，请明天再来或咨询教师调整配额'}), 429

    from ai_service.services import ai_generate_material, ai_decide_material_kind
    t0 = time.perf_counter()
    decided_by = kind
    if kind == 'auto':
        kind = ai_decide_material_kind(db.session, prompt)
    content, degraded = ai_generate_material(db.session, prompt, kind, subject, difficulty)

    kp = KnowledgePoint.query.filter(func.lower(KnowledgePoint.name) == prompt.lower()).first()
    m = StudyMaterial(user_id=user.id,
                      folder_id=data.get('folder_id') or None,
                      kind=kind, title=prompt[:200], content=content[:30000],
                      subject=subject, difficulty=difficulty,
                      knowledge_point_id=kp.id if kp else None, source='ai')
    if m.folder_id:
        folder = db.session.get(StudyFolder, m.folder_id)
        if not folder or folder.user_id != user.id:
            m.folder_id = None
    db.session.add(m)
    charge_ai_quota(user)
    log_ai_usage(user.id, 'material:' + kind,
                 'degraded' if degraded else 'success',
                 (time.perf_counter() - t0) * 1000)
    db.session.commit()
    # v7.18 需求 b：单份生成也要进消息提示。用户点「开始生成」后动辄十几秒，
    # 中途切页/刷新就错过当场 toast；降级（AI 不可用）不发通知，否则是在误报成功
    if not degraded:
        try:
            from ai_service.services import MATERIAL_KIND_NAMES
            create_notification(
                user.id, f'{MATERIAL_KIND_NAMES.get(kind, "学习资料")}已生成',
                f'「{m.title}」已存入资料库，可在线阅读或继续公开到学习广场。',
                type='success', related_type='material', related_id=m.id)
        except Exception:
            db.session.rollback()
            logger.exception('[learning] 资料生成通知创建失败 material_id=%s', m.id)
    return jsonify({'material': _material_to_dict(m, with_content=True),
                    'kind': kind, 'decided_by': decided_by,
                    'source': 'rule' if degraded else 'ai'})


@api_learning_bp.route('/learning/materials', methods=['GET'])
def api_material_list():
    """我的资料库：支持关键词/类型/文件夹/收藏（favorite=1 看收藏）筛选"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    q = (request.args.get('q') or '').strip()
    kind = request.args.get('kind')
    folder_id = request.args.get('folder_id', type=int)
    fav_only = request.args.get('favorite') == '1'

    if fav_only:
        items = (MaterialFavorite.query.filter_by(user_id=user.id)
                 .order_by(MaterialFavorite.id.desc()).all())
        mats = [f.material for f in items
                if f.material and (f.material.status == 'active' or f.material.user_id == user.id)]
    else:
        query = StudyMaterial.query.filter(StudyMaterial.user_id == user.id,\
                                           StudyMaterial.status == 'active')
        if q:
            query = query.filter(or_(StudyMaterial.title.like(f'%{q}%'),
                                     StudyMaterial.content.like(f'%{q}%')))
        if kind in _MATERIAL_KINDS:
            query = query.filter(StudyMaterial.kind == kind)
        if folder_id is not None:
            query = query.filter(StudyMaterial.folder_id == folder_id)
        mats = query.order_by(StudyMaterial.updated_at.desc()).limit(200).all()
    return jsonify({'items': [_material_to_dict(m, current_user_id=user.id) for m in mats],
                    'total': len(mats), 'kind_groups': _kind_groups(user)})


# 归档顺序与「生成学习文档」下拉一致（v7.18 需求 i）：教案一栏、练习题集一栏……
# 名字一律取自 ai_service.services.MATERIAL_KIND_NAMES，不在前端再抄一份，
# 免得改了模板显示名后两边对不上（用户看到的分栏和下拉说的不是一回事）。
_KIND_ORDER = ('mindmap', 'lesson_plan', 'lecture', 'summary', 'quiz', 'video_script', 'manual')


def _kind_groups(user):
    """按形态分组计数：[{kind, name, count}]，含 0 的档也返回。

    统计口径是「本人全部有效资料」，不随搜索词/文件夹/收藏变化：左侧分栏是导航
    骨架，数字乱跳会让人怀疑自己点错了。库里出现表外形态（历史数据或新增形态
    未入顺序表）也要尾随露出来，不能静默吞掉（资产驱动收录的同一条教训）。
    """
    from ai_service.services import MATERIAL_KIND_NAMES
    rows = (db.session.query(StudyMaterial.kind, func.count(StudyMaterial.id))
            .filter(StudyMaterial.user_id == user.id,
                    StudyMaterial.status == 'active')
            .group_by(StudyMaterial.kind).all())
    counts = dict(rows)
    names = dict(MATERIAL_KIND_NAMES)
    names['manual'] = '手写资料'
    out = [{'kind': k, 'name': names.get(k, k), 'count': counts.get(k, 0)}
           for k in _KIND_ORDER]
    out += [{'kind': k, 'name': names.get(k, k), 'count': c}
            for k, c in counts.items() if k not in _KIND_ORDER]
    return out


@api_learning_bp.route('/learning/materials', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_create():
    """手写资料入库"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '资料标题不能为空'}), 400
    kind = data.get('kind') if data.get('kind') in _MATERIAL_KINDS else 'manual'
    folder_id = data.get('folder_id') or None
    if folder_id:
        folder = db.session.get(StudyFolder, folder_id)
        if not folder or folder.user_id != user.id:
            folder_id = None
    m = StudyMaterial(user_id=user.id, folder_id=folder_id, kind=kind,
                      title=title[:200], content=str(data.get('content') or '')[:30000],
                      subject=str(data.get('subject') or '').strip()[:50] or None,
                      difficulty=str(data.get('difficulty') or '').strip()[:20] or None,
                      attachment_json=_normalize_attachments(data.get('attachments')) or None,
                      source='manual')
    db.session.add(m)
    db.session.commit()
    return jsonify({'message': '已保存', 'material': _material_to_dict(m)})


@api_learning_bp.route('/learning/materials/<int:mid>', methods=['GET'])
def api_material_detail(mid):
    """资料详情：本人可看私有；他人仅可看公开且浏览数 +1；教师可监管看 active"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    m = db.session.get(StudyMaterial, mid)
    if not m or m.status != 'active':
        return jsonify({'message': '资料不存在'}), 404
    is_owner = m.user_id == user.id
    if not is_owner and not m.is_public and not user.is_teacher():
        return jsonify({'message': '资料不存在'}), 404
    if not is_owner:
        m.views = (m.views or 0) + 1
        db.session.commit()
    return jsonify({'material': _material_to_dict(m, with_content=True,
                                                  current_user_id=user.id)})


@api_learning_bp.route('/learning/materials/<int:mid>/attachments/<int:idx>/download',
                       methods=['GET'])
def api_material_attachment_download(mid, idx):
    """资料附件下载/预览（v7.18）：本人永久可用；公开资料任何登录用户可用。

    inline=1 时不给 Content-Disposition: attachment，让浏览器就地开 PDF/图片/视频/
    纯文本（mermaid 导图源文件）；Office 文档不带 inline 语义，统一走下载。
    不直接返 /uploads/ 路径是为了能卡权限：私有资料的附件不该被知道 UUID 的人拿走。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    m = db.session.get(StudyMaterial, mid)
    if not m or m.status != 'active':
        return jsonify({'message': '资料不存在'}), 404
    if m.user_id != user.id and not (m.is_public or user.is_teacher()):
        return jsonify({'message': '无权访问该附件'}), 403
    atts = m.attachment_json or []
    if idx < 0 or idx >= len(atts):
        return jsonify({'message': '附件不存在'}), 404
    att = atts[idx] if isinstance(atts[idx], dict) else {}
    stored = os.path.basename(str(att.get('stored_name') or ''))
    if not stored:
        # 链接类附件没有本体文件：前端应直接开 url，走到这里当作参数错误
        return jsonify({'message': '该附件是链接，请直接打开网址'}), 400
    inline = request.args.get('inline') == '1'
    return send_from_directory(_UPLOAD_DIR, stored, as_attachment=not inline,
                               download_name=att.get('name') or stored)


@api_learning_bp.route('/learning/materials/<int:mid>', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_update(mid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    m, err = _get_own_material(user, mid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        t = str(data.get('title') or '').strip()
        if not t:
            return jsonify({'message': '资料标题不能为空'}), 400
        m.title = t[:200]
    if 'content' in data:
        m.content = str(data.get('content') or '')[:30000]
    if 'folder_id' in data:
        fid = data.get('folder_id') or None
        if fid:
            folder = db.session.get(StudyFolder, fid)
            if not folder or folder.user_id != user.id:
                return jsonify({'message': '文件夹不存在'}), 400
        m.folder_id = fid
    if 'subject' in data:
        m.subject = str(data.get('subject') or '').strip()[:50] or None
    if 'difficulty' in data:
        m.difficulty = str(data.get('difficulty') or '').strip()[:20] or None
    if 'is_public' in data:
        m.is_public = bool(data.get('is_public'))
    if 'attachments' in data:
        # 整列重写而非追加：附件增删都走这里，避免两套口径（前端传全量列表）
        m.attachment_json = _normalize_attachments(data.get('attachments')) or None
    db.session.commit()
    return jsonify({'message': '已保存', 'material': _material_to_dict(m)})


@api_learning_bp.route('/learning/materials/<int:mid>', methods=['DELETE'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_delete(mid):
    """删资料：收藏、举报与生成作业的反向引用一并清理（无级联，手动删）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    m, err = _get_own_material(user, mid)
    if err:
        return err
    MaterialFavorite.query.filter_by(material_id=m.id).delete(synchronize_session=False)
    MaterialReport.query.filter_by(material_id=m.id).delete(synchronize_session=False)
    # v7.9 批量队列的 material_gen_job.material_id 反向指着本行：不清空则 PG 直接
    # ForeignKeyViolation（删一份批量生成的教案就 500）。SQLite 不强制外键，测试门里
    # 一直看不见——与隐患 #23 同形状。这里逐条改 ORM 对象而非 Query.update()，
    # 因为 bulk 写进不了实时镜像（#24），会让拷走的 SQLite 里留下一批指向空号的作业行。
    from database.models import MaterialGenJob
    for job in MaterialGenJob.query.filter_by(material_id=m.id).all():
        job.material_id = None
    db.session.delete(m)
    db.session.commit()
    return jsonify({'message': '已删除'})


@api_learning_bp.route('/learning/materials/<int:mid>/favorite', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_favorite_toggle(mid):
    """收藏/取消收藏：仅对公开且未下架的资料生效，自己的资料不可收藏"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    m = db.session.get(StudyMaterial, mid)
    if not m or m.status != 'active' or not m.is_public:
        return jsonify({'message': '资料不存在或未公开'}), 404
    if m.user_id == user.id:
        return jsonify({'message': '不能收藏自己的资料'}), 400
    exist = MaterialFavorite.query.filter_by(user_id=user.id, material_id=mid).first()
    if exist:
        db.session.delete(exist)
        db.session.commit()
        return jsonify({'message': '已取消收藏', 'favorited': False,
                        'fav_count': len(m.favorites)})
    db.session.add(MaterialFavorite(user_id=user.id, material_id=mid))
    db.session.commit()
    return jsonify({'message': '已收藏', 'favorited': True, 'fav_count': len(m.favorites)})


# ── 资料库文件夹 ────────────────────────────────

def _folder_to_dict(f, count_map=None):
    d = {'id': f.id, 'name': f.name, 'parent_id': f.parent_id,
         'created_at': iso_local(f.created_at)}
    if count_map is not None:
        d['material_count'] = count_map.get(f.id, 0)
    return d


@api_learning_bp.route('/learning/folders', methods=['GET'])
def api_folder_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    folders = StudyFolder.query.filter_by(user_id=user.id).order_by(StudyFolder.id).all()
    rows = db.session.query(StudyMaterial.folder_id, func.count(StudyMaterial.id)) \
        .filter(StudyMaterial.user_id == user.id,
                StudyMaterial.status == 'active',
                StudyMaterial.folder_id.isnot(None)) \
        .group_by(StudyMaterial.folder_id).all()
    count_map = {r[0]: r[1] for r in rows}
    return jsonify({'items': [_folder_to_dict(f, count_map) for f in folders]})


@api_learning_bp.route('/learning/folders', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_folder_create():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    if not name:
        return jsonify({'message': '文件夹名称不能为空'}), 400
    parent_id = data.get('parent_id') or None
    if parent_id:
        parent = db.session.get(StudyFolder, parent_id)
        if not parent or parent.user_id != user.id:
            return jsonify({'message': '父文件夹不存在'}), 400
    f = StudyFolder(user_id=user.id, name=name[:50], parent_id=parent_id)
    db.session.add(f)
    db.session.commit()
    return jsonify({'message': '已创建', 'folder': _folder_to_dict(f)})


@api_learning_bp.route('/learning/folders/<int:fid>', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_folder_update(fid):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    f = db.session.get(StudyFolder, fid)
    if not f or f.user_id != user.id:
        return jsonify({'message': '文件夹不存在'}), 404
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()
    if name:
        f.name = name[:50]
    db.session.commit()
    return jsonify({'message': '已保存', 'folder': _folder_to_dict(f)})


@api_learning_bp.route('/learning/folders/<int:fid>', methods=['DELETE'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_folder_delete(fid):
    """删文件夹：子文件夹提根，夹内资料归根不连带删"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    f = db.session.get(StudyFolder, fid)
    if not f or f.user_id != user.id:
        return jsonify({'message': '文件夹不存在'}), 404
    StudyFolder.query.filter_by(parent_id=fid, user_id=user.id) \
        .update({'parent_id': f.parent_id}, synchronize_session=False)
    StudyMaterial.query.filter_by(folder_id=fid, user_id=user.id) \
        .update({'folder_id': None}, synchronize_session=False)
    db.session.delete(f)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ── 公开资料广场与举报 ────────────────────────────

@api_learning_bp.route('/learning/explore', methods=['GET'])
def api_material_explore():
    """资料广场：全员浏览公开且未下架的资料，支持搜索/筛选/最热最新排序"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    q = (request.args.get('q') or '').strip()
    kind = request.args.get('kind')
    subject = (request.args.get('subject') or '').strip()
    sort = request.args.get('sort') or 'latest'

    query = StudyMaterial.query.filter(StudyMaterial.is_public.is_(True),
                                       StudyMaterial.status == 'active')
    if q:
        query = query.filter(or_(StudyMaterial.title.like(f'%{q}%'),
                                 StudyMaterial.content.like(f'%{q}%')))
    if kind in _MATERIAL_KINDS:
        query = query.filter(StudyMaterial.kind == kind)
    if subject:
        query = query.filter(StudyMaterial.subject == subject)
    if sort == 'hot':
        # 热度 = 浏览量 + 收藏数×5，在应用层算（量级小，避免复杂 SQL）
        mats = query.limit(500).all()
        mats.sort(key=lambda m: (m.views or 0) + len(m.favorites) * 5,
                  reverse=True)
        mats = mats[:60]
    else:
        mats = query.order_by(StudyMaterial.updated_at.desc()).limit(60).all()
    subjects = [r[0] for r in db.session.query(StudyMaterial.subject)
                .filter(StudyMaterial.is_public.is_(True),
                        StudyMaterial.status == 'active',
                        StudyMaterial.subject.isnot(None)).distinct().limit(50).all()]
    return jsonify({'items': [_material_to_dict(m, current_user_id=user.id) for m in mats],
                    'subjects': subjects})


@api_learning_bp.route('/learning/materials/<int:mid>/report', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_report(mid):
    """举报公开资料：同一人对同一资料待处理举报幂等"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    m = db.session.get(StudyMaterial, mid)
    if not m or m.status != 'active' or not m.is_public:
        return jsonify({'message': '资料不存在或未公开'}), 404
    if m.user_id == user.id:
        return jsonify({'message': '不能举报自己的资料'}), 400
    exist = MaterialReport.query.filter_by(material_id=mid, reporter_id=user.id,
                                           status='pending').first()
    if exist:
        return jsonify({'message': '您已举报过该资料，正在处理中'}), 409
    data = request.get_json(silent=True) or {}
    r = MaterialReport(material_id=mid, reporter_id=user.id,
                       reason=str(data.get('reason') or '').strip()[:200])
    db.session.add(r)
    db.session.commit()
    return jsonify({'message': '举报已提交，教师会尽快处理', 'report_id': r.id})


@api_learning_bp.route('/learning/material-reports', methods=['GET'])
def api_material_report_list():
    """教师端：举报列表（默认待处理）"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='未登录')
    if err:
        return err
    status = request.args.get('status') or 'pending'
    rows = (MaterialReport.query.filter_by(status=status)
            .order_by(MaterialReport.created_at.desc()).limit(100).all())
    items = [{'id': r.id, 'material_id': r.material_id,
              'material_title': r.material.title if r.material else None,
              'author': r.material.user.username if r.material and r.material.user else None,
              'reporter': r.reporter.username if r.reporter else None,
              'reason': r.reason, 'status': r.status,
              'note': r.note, 'created_at': iso_local(r.created_at)}
             for r in rows]
    return jsonify({'items': items})


@api_learning_bp.route('/learning/material-reports/<int:rid>/handle', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_report_handle(rid):
    """教师处理举报：remove 下架资料并通知作者；reject 驳回"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='未登录')
    if err:
        return err
    r = db.session.get(MaterialReport, rid)
    if not r or r.status != 'pending':
        return jsonify({'message': '举报不存在或已处理'}), 404
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('remove', 'reject'):
        return jsonify({'message': '参数错误：action 须为 remove/reject'}), 400
    note = str(data.get('note') or '').strip()[:200]
    r.status = 'removed' if action == 'remove' else 'rejected'
    r.handler_id = user.id
    r.note = note
    r.handled_at = utcnow()
    if action == 'remove' and r.material:
        r.material.status = 'removed'
        r.material.is_public = False
        create_notification(r.material.user_id, '您的公开资料已被下架',
                            '《' + (r.material.title or '') + '》因举报经核实被下架，原因：'
                            + (note or '违规内容') + '。修改后可重新公开。',
                            type='warning',
                            related_type='material', related_id=r.material.id, commit=False)
    db.session.commit()
    return jsonify({'message': '已下架' if action == 'remove' else '已驳回举报'})


# ── 关注体系与公开主页 ──────────────────────────

def _user_public_dict(target, viewer):
    following = UserFollow.query.filter_by(follower_id=viewer.id,
                                           followee_id=target.id).first() is not None
    mutual = following and UserFollow.query.filter_by(follower_id=target.id,
                                                      followee_id=viewer.id).first() is not None
    return {'user_id': target.id, 'username': target.username,
            'role': target.role, 'is_following': following, 'is_mutual': mutual,
            'following_count': UserFollow.query.filter_by(follower_id=target.id).count(),
            'fans_count': UserFollow.query.filter_by(followee_id=target.id).count()}


@api_learning_bp.route('/learning/users/search', methods=['GET'])
def api_user_search():
    """按用户名搜索用户（排除机器人），附关注状态"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'items': []})
    from database.models import RoleEnum
    users = User.query.filter(User.role != RoleEnum.BOT,
                              User.username.like(f'%{q}%')).limit(20).all()
    items = []
    for tu in users:
        if tu.id == user.id:
            continue
        d = {'user_id': tu.id, 'username': tu.username, 'role': tu.role,
             'public_count': StudyMaterial.query.filter_by(
                 user_id=tu.id, is_public=True, status='active').count()}
        d['is_following'] = UserFollow.query.filter_by(
            follower_id=user.id, followee_id=tu.id).first() is not None
        items.append(d)
    return jsonify({'items': items})


@api_learning_bp.route('/learning/users/<int:uid>/follow', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_follow_toggle(uid):
    """关注/取关：同一接口 toggle，互相关注即好友"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    if uid == user.id:
        return jsonify({'message': '不能关注自己'}), 400
    target = db.session.get(User, uid)
    if not target or target.role == 'bot':
        return jsonify({'message': '用户不存在'}), 404
    exist = UserFollow.query.filter_by(follower_id=user.id, followee_id=uid).first()
    if exist:
        db.session.delete(exist)
        db.session.commit()
        return jsonify({'message': '已取消关注', 'following': False})
    db.session.add(UserFollow(follower_id=user.id, followee_id=uid))
    db.session.commit()
    # 互动通知：被关注→通知本人（取关不发；经 ORM 事件实时推送）
    create_notification(target.id, '有人关注了你',
                        f'{user.username} 关注了你，可去对方主页看看。',
                        type='info', related_type='user', related_id=user.id)
    return jsonify({'message': '已关注', 'following': True})


@api_learning_bp.route('/learning/users/<int:uid>/profile', methods=['GET'])
def api_user_public_profile(uid):
    """用户公开主页：关注信息 + 公开资料列表"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    target = db.session.get(User, uid)
    if not target or target.role == 'bot':
        return jsonify({'message': '用户不存在'}), 404
    data = _user_public_dict(target, user)
    if target.id != user.id:
        mats = StudyMaterial.query.filter_by(user_id=uid, is_public=True, status='active') \
            .order_by(StudyMaterial.updated_at.desc()).limit(50).all()
    else:
        mats = StudyMaterial.query.filter_by(user_id=uid) \
            .order_by(StudyMaterial.updated_at.desc()).limit(50).all()
    data['materials'] = [_material_to_dict(m, current_user_id=user.id) for m in mats]
    return jsonify(data)


@api_learning_bp.route('/learning/users/<int:uid>/follows', methods=['GET'])
def api_user_follows(uid):
    """v7.7 关注/粉丝列表：type=following|fans|mutual；限本人查看，他人只能看公开资料"""
    viewer = verify_token()
    if not viewer:
        return jsonify({'message': '未登录'}), 401
    if viewer.id != uid:
        return jsonify({'message': '仅可查看自己的关注关系'}), 403
    ftype = request.args.get('type', 'following')
    if ftype == 'fans':
        # 粉丝列表：谁关注了我
        ids = [r.follower_id for r in UserFollow.query.filter_by(followee_id=uid).all()]
    elif ftype == 'mutual':
        # 互相关注：我关注的人里同时也关注了我的
        my_follows = {r.followee_id for r in UserFollow.query.filter_by(follower_id=uid).all()}
        ids = [r.followee_id for r in UserFollow.query.filter_by(follower_id=uid).all()
               if r.followee_id in my_follows]
    else:
        # 我关注的人（默认）
        ids = [r.followee_id for r in UserFollow.query.filter_by(follower_id=uid).all()]
    users = db.session.query(User).filter(User.id.in_(ids)).all() if ids else []
    return jsonify({'items': [
        {'id': u.id, 'username': u.username, 'role': u.role} for u in users
    ]})


# ── AI 额度与治理（教师） ──────────────────────

@api_learning_bp.route('/learning/ai-quota', methods=['GET'])
def api_ai_quota_mine():
    """任意登录用户查自己当日 AI 额度"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    return jsonify(get_quota_info(user))


@api_learning_bp.route('/learning/ai-governance/summary', methods=['GET'])
def api_ai_governance_summary():
    """教师端：近 N 天 AI 用量按天聚合 + 额度占用 TOP 用户"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='未登录')
    if err:
        return err
    days = min(max(request.args.get('days', type=int) or 14, 1), 90)
    since = utcnow() - timedelta(days=days)
    logs = AiUsageLog.query.filter(AiUsageLog.created_at >= since).all()
    per_day = defaultdict(lambda: {'total': 0, 'success': 0, 'degraded': 0, 'fail': 0,
                                   'avg_cost_ms': 0, '_sum': 0})
    by_user = defaultdict(int)
    for lg in logs:
        d = per_day[local_date(lg.created_at).isoformat()]
        d['total'] += 1
        d[lg.status if lg.status in ('success', 'degraded', 'fail') else 'fail'] += 1
        d['_sum'] += lg.cost_ms or 0
        by_user[lg.user_id] += 1
    day_list = []
    for day in sorted(per_day):
        v = per_day[day]
        day_list.append({'day': day, 'total': v['total'], 'success': v['success'],
                         'degraded': v['degraded'], 'fail': v['fail'],
                         'avg_cost_ms': round(v['_sum'] / v['total']) if v['total'] else 0})
    top_users = []
    for uid, cnt in sorted(by_user.items(), key=lambda kv: -kv[1])[:10]:
        tu = db.session.get(User, uid)
        quota = db.session.get(AiQuota, uid)
        top_users.append({'user_id': uid,
                          'username': tu.username if tu else str(uid),
                          'calls': cnt,
                          'daily_limit': quota.daily_limit if quota else 30})
    return jsonify({'per_day': day_list, 'top_users': top_users,
                    'total_calls': len(logs), 'days': days})


@api_learning_bp.route('/learning/ai-governance/logs', methods=['GET'])
def api_ai_governance_logs():
    """教师端：AI 调用日志分页明细，可按用户/动作筛"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='未登录')
    if err:
        return err
    page = max(request.args.get('page', type=int) or 1, 1)
    size = min(max(request.args.get('size', type=int) or 20, 1), 100)
    query = AiUsageLog.query
    uid = request.args.get('user_id', type=int)
    action = request.args.get('action')
    if uid:
        query = query.filter(AiUsageLog.user_id == uid)
    if action:
        query = query.filter(AiUsageLog.action.like(f'{action}%'))
    total = query.count()
    rows = query.order_by(AiUsageLog.id.desc()).offset((page - 1) * size).limit(size).all()
    items = [{'id': lg.id, 'user': lg.user.username if lg.user else None,
              'user_id': lg.user_id, 'action': lg.action, 'status': lg.status,
              'cost_ms': lg.cost_ms, 'created_at': iso_local(lg.created_at)}
             for lg in rows]
    return jsonify({'items': items, 'total': total, 'page': page, 'size': size})


@api_learning_bp.route('/learning/ai-governance/quota/<int:uid>', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_ai_governance_quota(uid):
    """教师端：调整指定用户的每日 AI 生成上限"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='未登录')
    if err:
        return err
    target = db.session.get(User, uid)
    if not target:
        return jsonify({'message': '用户不存在'}), 404
    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get('daily_limit'))
    except (TypeError, ValueError):
        return jsonify({'message': 'daily_limit 必须为整数'}), 400
    limit = min(max(limit, 0), 1000)
    quota = db.session.get(AiQuota, uid)
    if quota is None:
        quota = AiQuota(user_id=uid, daily_limit=limit, used_today=0,
                        reset_date=local_today())
        db.session.add(quota)
    else:
        quota.daily_limit = limit
    db.session.commit()
    return jsonify({'message': '已更新', 'user': target.username,
                    'daily_limit': quota.daily_limit})
