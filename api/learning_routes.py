"""自我学习模块 API

蓝图前缀：/api/learning
功能：错题本、自由刷题、学习计划、学习报告聚合、AI 答疑、
     专业学习路径 + 知识图谱（知识点/边/路径/选课/进度/资源）
"""
import json
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
    Exam, ExamSession, Answer, Result,
    KnowledgePoint, KnowledgeEdge,
    LearningPath, LearningPathNode,
    UserPathEnrollment, UserNodeProgress, LearningResource,
    KnowledgeMastery, UserKpNote, QuizAttempt, QuizAttemptAnswer,
    ReviewItem, StudyCheckin, PathCertificate, DailyTask,
    AiChatConversation, AiChatMessage, FocusSession, StudyNote, ExplainCard,
    StudyFolder, StudyMaterial, MaterialFavorite, MaterialReport, UserFollow,
    AiUsageLog, AiQuota,
    question_knowledge_point,
)
from utils.security import limiter, RateLimitConfig, verify_token
from utils.uploads import save_upload, ALLOWED_EXTENSIONS as _UPLOAD_EXTS
from utils.timeutil import utcnow, iso_local, parse_dt
from utils.logger import logger
from api import learning_engine as eng
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

    return jsonify({
        'total': total,
        'page': page,
        'per_page': per_page,
        'items': [_wrong_record_to_dict(r) for r in records]
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
        user_id=user.id, title=title or f'练习 {utcnow().strftime("%m-%d %H:%M")}',
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
    # 未作答判 CE；无用例/非 Python 语言回落原链路（主观题 is_correct=None 待人工）
    oj_info = None
    is_correct = None
    if question.type == 'programming' and getattr(question, 'test_cases', None):
        from oj.services import grade as oj_grade
        if not student_answer:
            oj_info = {'verdict': 'CE', 'passed': 0,
                       'total': len(question.test_cases), 'score_ratio': 0}
            is_correct = False
        else:
            r = oj_grade(student_answer, 'python', question.test_cases)
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
        'overdue': bool(t.due_date and t.status != 'done' and t.due_date < utcnow().date()),
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
    today = utcnow().date()
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
            d = t.done_at.date()
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
        start_date = date.fromisoformat(start_raw) if start_raw else date.today()
    except (ValueError, TypeError):
        start_date = date.today()
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
        start_date=date.today(),
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
    """批量添加任务（AI 拆解建议采纳）：单次上限 10 条，按标题去重"""
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
    return jsonify({'added': len(added), 'tasks': [_task_to_dict(t) for t in added]})


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
        start = date.fromisoformat(data['start_date']) if data.get('start_date') else date.today()
    except (ValueError, TypeError):
        start = date.today()
    days = 14
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

@api_learning_bp.route('/learning/report/overview', methods=['GET'])
def api_report_overview():
    """学习概览：最近 30 天聚合 + 统计指标"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    days = int(request.args.get('days', 30))
    cutoff = utcnow() - __import__('datetime').timedelta(days=days)

    # 练习/考试/竞赛聚合
    logs = StudyLog.query.filter_by(user_id=user.id).filter(StudyLog.studied_at >= cutoff).all()
    log_total = sum(l.total_questions for l in logs)
    log_correct = sum(l.correct_count for l in logs)

    # 错题统计
    wrong_total = WrongAnswerRecord.query.filter_by(user_id=user.id).count()
    wrong_unmastered = WrongAnswerRecord.query.filter_by(user_id=user.id, is_mastered=False).count()
    wrong_mastered = wrong_total - wrong_unmastered

    # 活跃学习计划
    active_plans = StudyPlan.query.filter_by(user_id=user.id, status='active').count()

    # 最近 7 天每日学习时长聚合（从 StudyLog 逐日求和）
    daily = db.session.query(
        func.date(StudyLog.studied_at).label('day'),
        func.sum(StudyLog.time_spent_sec).label('time_sec'),
        func.sum(StudyLog.total_questions).label('total'),
        func.sum(StudyLog.correct_count).label('correct'),
    ).filter(
        StudyLog.user_id == user.id,
        StudyLog.studied_at >= utcnow() - __import__('datetime').timedelta(days=7),
    ).group_by(func.date(StudyLog.studied_at)).all()

    daily_map = {str(r.day): {'time_sec': int(r.time_sec or 0),
                               'total': int(r.total or 0),
                               'correct': int(r.correct or 0)} for r in daily}

    return jsonify({
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
    })


@api_learning_bp.route('/learning/report/daily', methods=['GET'])
def api_report_daily():
    """最近 N 天的每日学习记录明细（含错题/练习详情）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    days = int(request.args.get('days', 30))
    cutoff = utcnow() - __import__('datetime').timedelta(days=days)

    logs = StudyLog.query.filter_by(user_id=user.id) \
        .filter(StudyLog.studied_at >= cutoff) \
        .order_by(StudyLog.studied_at.desc()).all()

    return jsonify([{
        'id': l.id, 'log_type': l.log_type, 'reference_id': l.reference_id,
        'total_questions': l.total_questions, 'correct_count': l.correct_count,
        'score_ratio': l.score_ratio, 'time_spent_sec': l.time_spent_sec,
        'studied_at': iso_local(l.studied_at),
    } for l in logs])


# ── AI 答疑 ────────────────────────────────────────────────────────

@api_learning_bp.route('/learning/ask', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_learning_ask():
    """AI 答疑：传入题目 id（或题目内容）+ 用户疑问，返回解析"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    question_id = data.get('question_id')
    question_content = data.get('question_content', '').strip()
    student_answer = (data.get('student_answer') or '').strip()
    doubt = data.get('doubt', '').strip()

    question = None
    if question_id:
        question = db.session.get(Question, question_id)
        if question:
            question_content = question.content
            if not student_answer and question.answer:
                student_answer = question.answer

    if not question_content and not doubt:
        return jsonify({'message': '请提供题目内容或您的疑问'}), 400

    try:
        from ai_service.services import ai_generate_analysis
        analysis = ai_generate_analysis(db.session, question_id, student_answer) if question_id else ''
    except Exception:
        logger.exception('AI 答疑失败')
        return jsonify({'message': 'AI 服务暂不可用，请稍后重试'}), 500

    # 额外用 doubt 字段扩展解析（若有独立客户端能处理更好）
    return jsonify({
        'analysis': analysis,
        'question_content': question_content,
        'question_answer': question.answer if question else None,
    })


@api_learning_bp.route('/learning/ai-chat', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_learning_ai_chat():
    """AI 学习助手多轮对话：历史由前端持有，服务端无状态；context 注入页面背景"""
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

    t0 = time.perf_counter()
    try:
        from ai_service.services import ai_chat_reply
        reply = ai_chat_reply(db.session, cleaned, context)
    except Exception:
        logger.exception('AI 学习助手对话失败')
        log_ai_usage(user.id, 'chat', 'fail', (time.perf_counter() - t0) * 1000)
        db.session.commit()
        return jsonify({'message': 'AI 服务暂不可用，请稍后重试'}), 500
    charge_ai_quota(user)
    log_ai_usage(user.id, 'chat', 'success', (time.perf_counter() - t0) * 1000)
    db.session.commit()
    return jsonify({'reply': reply})


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

def _wrong_record_to_dict(r):
    q = r.question
    return {
        'id': r.id, 'question_id': r.question_id,
        'question_content': q.content if q else None,
        'question_type': q.type if q else None,
        'knowledge': q.knowledge if q else None,
        'options': q.options if q else None,
        'correct_answer': r.correct_answer,
        'wrong_answer': r.wrong_answer,
        'is_mastered': r.is_mastered,
        'wrong_count': r.wrong_count,
        'source_type': r.source_type, 'source_id': r.source_id,
        'ai_analysis': r.ai_analysis,
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


def _check_answer(q_type, student_answer, correct_answer):
    """客观题判分：返回 True/False；主观题返回 None（无法自动判对/错）"""
    if q_type in ('single_choice', 'true_false'):
        # 单项/判断：直接比对（去空格、统一大小写）
        return (student_answer or '').strip().upper() == (correct_answer or '').strip().upper()
    if q_type == 'multiple_choice':
        # 多项：排序后比对
        s = ''.join(sorted((student_answer or '').strip().upper()))
        c = ''.join(sorted((correct_answer or '').strip().upper()))
        return s == c
    if q_type == 'fill_blank':
        # 填空：大小写不敏感
        return (student_answer or '').strip().lower() == (correct_answer or '').strip().lower()
    # 主观题无法自动判对错（返回 None，错题收录时跳过）
    return None


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

    max_order = db.session.query(func.max(LearningPathNode.order_num)) \
        .filter_by(path_id=path_id).scalar() or 0
    node = LearningPathNode(
        path_id=path_id, node_type=node_type,
        knowledge_point_id=kp_id, chapter_id=chapter_id,
        order_num=max_order + 1,
        role=data.get('role', 'core'),
        estimated_minutes=int(data.get('estimated_minutes', 30) or 30),
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

_OBJECTIVE_TYPES = ('single_choice', 'multiple_choice', 'true_false', 'fill_blank')


# ── 今日学习聚合页 ────────────────────────────────────────────────
@api_learning_bp.route('/learning/today', methods=['GET'])
def api_today():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    now = utcnow()
    today = now.date()

    # 1) 打卡与连击
    streak = eng.compute_streak(user.id, today)
    week = eng.week_checkin_days(user.id, today)
    today_ci = StudyCheckin.query.filter_by(user_id=user.id, day=today).first()

    # 1.1) v4.4 今日专注计时概览（进行中会话 + 今日完成总时长，UTC 日口径与打卡一致）
    running_focus = FocusSession.query.filter_by(user_id=user.id, status='running') \
        .order_by(FocusSession.id.desc()).first()
    day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
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
    return utcnow().date()


def _today_snapshot(user):
    """聚合用户学习现状：返回（供 AI 的上下文文本，规则兑底建议列表）"""
    now = utcnow()
    today = now.date()
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
        if t.day == utcnow().date():
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
        'earned_date': utcnow().date().isoformat(),
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
        from api.notification_routes import create_notification
        create_notification(user.id, f'恭喜获得结业证书：{path.title}',
                           f'您已完成学习路径「{path.title}」并通过结业测评（{round((final_score or 0)*100)}%）。',
                           type='success', related_type='certificate', related_id=cert.id, commit=False)
    except Exception:
        logger.exception('证书通知创建失败')
    return cert


# ── 知识库：我的知识点 / 笔记 / 证书 / 图谱着色 ──────────────

@api_learning_bp.route('/learning/my-knowledge', methods=['GET'])
def api_my_knowledge():
    """我学过的一切知识点（掌握度/笔记/错题数），按 专业→课程→章节 层级"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    masteries = KnowledgeMastery.query.filter_by(user_id=user.id).all()
    mmap = {m.knowledge_point_id: m for m in masteries}
    notes = UserKpNote.query.filter_by(user_id=user.id).all()
    nmap = {n.knowledge_point_id: n for n in notes}

    # 预加载涉及的知识点及其章节/课程/专业链
    kp_ids = list(mmap.keys())
    if not kp_ids:
        return jsonify({'majors': [], 'total': 0})
    kps = KnowledgePoint.query.filter(KnowledgePoint.id.in_(kp_ids)).all()

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
    raw = request.args.get('month') or utcnow().strftime('%Y-%m')
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


def _note_to_dict(n, brief=False):
    d = {'id': n.id, 'title': n.title, 'category': n.category,
         'tags': n.tags or [], 'pinned': bool(n.pinned), 'source': n.source,
         'attachments': [{'filename': a.get('filename'), 'size': a.get('size', 0)}
                         for a in (n.attachment_json or [])],
         'created_at': iso_local(n.created_at), 'updated_at': iso_local(n.updated_at)}
    if brief:
        d['excerpt'] = re.sub(r'[#*`>\-]', '', n.content or '')[:100]
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

_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')

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

_MATERIAL_KINDS = ('video_script', 'mindmap', 'lecture', 'summary', 'quiz', 'manual')


def _material_to_dict(m, with_content=False, current_user_id=None):
    d = {'id': m.id, 'title': m.title, 'kind': m.kind, 'subject': m.subject,
         'difficulty': m.difficulty, 'folder_id': m.folder_id, 'source': m.source,
         'is_public': bool(m.is_public), 'views': m.views,
         'status': m.status, 'knowledge_point_id': m.knowledge_point_id,
         'author': m.user.username if m.user else None, 'owner_id': m.user_id,
         'fav_count': len(m.favorites),
         'excerpt': re.sub(r'[#*`>\-\n]', '', m.content or '')[:80],
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
                    'total': len(mats)})


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
    db.session.commit()
    return jsonify({'message': '已保存', 'material': _material_to_dict(m)})


@api_learning_bp.route('/learning/materials/<int:mid>', methods=['DELETE'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_material_delete(mid):
    """删资料：收藏与举报记录一并清理（无级联，手动删）"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    m, err = _get_own_material(user, mid)
    if err:
        return err
    MaterialFavorite.query.filter_by(material_id=m.id).delete(synchronize_session=False)
    MaterialReport.query.filter_by(material_id=m.id).delete(synchronize_session=False)
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
    from api.notification_routes import create_notification
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
        d = per_day[lg.created_at.strftime('%Y-%m-%d')]
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
                        reset_date=utcnow().date())
        db.session.add(quota)
    else:
        quota.daily_limit = limit
    db.session.commit()
    return jsonify({'message': '已更新', 'user': target.username,
                    'daily_limit': quota.daily_limit})
