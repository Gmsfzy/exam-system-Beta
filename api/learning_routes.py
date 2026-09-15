"""自我学习模块 API

蓝图前缀：/api/learning
功能：错题本、自由刷题、学习计划、学习报告聚合、AI 答疑
"""
import math
from datetime import date, datetime

from flask import Blueprint, request, jsonify
from sqlalchemy import func

from database import db
from database.models import (
    Question, Major, Course, Chapter, User,
    WrongAnswerRecord, PracticeSession, PracticeAnswer,
    StudyPlan, StudyLog,
    Exam, ExamSession, Answer, Result,
)
from utils.security import limiter, RateLimitConfig, verify_token
from utils.timeutil import utcnow, iso_local, parse_dt
from utils.logger import logger

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
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))

    q = WrongAnswerRecord.query.filter_by(user_id=user.id)
    if is_mastered is not None:
        q = q.filter_by(is_mastered=(is_mastered.lower() == 'true'))
    if source_type:
        q = q.filter_by(source_type=source_type)

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
    count = min(max(int(data.get('count', 10) or 10), 1), 50)

    pool = Question.query
    if major_id:
        pool = pool.filter_by(major_id=major_id)
    if course_id:
        pool = pool.filter_by(course_id=course_id)
    if chapter_id:
        pool = pool.filter_by(chapter_id=chapter_id)

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

    # 自动收录错题（仅客观题）
    if is_correct is False:
        sync_wrong_from_answers(user.id, 'practice', sess.id,
                                 [(question_id, student_answer, question.answer)])
    db.session.commit()

    return jsonify({
        'is_correct': is_correct,
        'correct_answer': question.answer,
        'analysis': question.analysis,
        'knowledge': question.knowledge,
        'type': question.type,
    })


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

    # 学习计划进度
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


# ── 学习计划 ──────────────────────────────────────────────────────

@api_learning_bp.route('/learning/plans', methods=['GET'])
def api_plan_list():
    """学习计划列表"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    plans = StudyPlan.query.filter_by(user_id=user.id) \
        .order_by(StudyPlan.created_at.desc()).all()
    return jsonify([{
        'id': p.id, 'title': p.title, 'description': p.description,
        'target_count': p.target_count, 'completed_count': p.completed_count,
        'progress': round(p.completed_count / p.target_count * 100, 1) if p.target_count else 0,
        'major_id': p.major_id, 'course_id': p.course_id, 'chapter_id': p.chapter_id,
        'major_name': db.session.get(Major, p.major_id).name if p.major_id else None,
        'course_name': db.session.get(Course, p.course_id).name if p.course_id else None,
        'status': p.status,
        'start_date': p.start_date.isoformat() if p.start_date else None,
        'end_date': p.end_date.isoformat() if p.end_date else None,
        'created_at': iso_local(p.created_at),
    } for p in plans])


@api_learning_bp.route('/learning/plans', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_plan_create():
    """创建学习计划"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    start_date_raw = data.get('start_date')
    try:
        start_date = date.fromisoformat(start_date_raw) if start_date_raw else date.today()
    except (ValueError, TypeError):
        start_date = date.today()

    try:
        target = max(int(data.get('target_count', 50) or 50), 1)
    except (TypeError, ValueError):
        target = 50

    plan = StudyPlan(
        user_id=user.id,
        title=data.get('title', '').strip() or '未命名计划',
        description=data.get('description'),
        target_count=target,
        completed_count=0,
        major_id=data.get('major_id'),
        course_id=data.get('course_id'),
        chapter_id=data.get('chapter_id'),
        start_date=start_date,
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
    for k in ('title', 'description', 'target_count', 'major_id',
              'course_id', 'chapter_id', 'end_date'):
        if k in data:
            setattr(plan, k, data[k])

    if data.get('start_date'):
        try:
            plan.start_date = date.fromisoformat(data['start_date'])
        except ValueError:
            pass
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
        plan.status = 'active'
        if plan.completed_count >= plan.target_count:
            plan.status = 'completed'
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


# ── 内部同步：考试结束后收录错题 ────────────────────────────────────
# 被 execution_routes.py 的 submit 流程调用
def sync_wrong_from_exam(user_id, exam_id):
    exam = db.session.get(Exam, exam_id)
    if not exam:
        return 0
    session = ExamSession.query.filter_by(exam_id=exam_id, student_id=user_id, status='submitted').first()
    if not session:
        return 0
    wrong = [(a.question_id, a.student_answer, a.question.answer)
             for a in Answer.query.filter_by(session_id=session.id).all()
             if a.is_correct is False and a.question]
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
