"""自我学习模块 API

蓝图前缀：/api/learning
功能：错题本、自由刷题、学习计划、学习报告聚合、AI 答疑、
     专业学习路径 + 知识图谱（知识点/边/路径/选课/进度/资源）
"""
import math
from datetime import date, datetime

from flask import Blueprint, request, jsonify
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
    question_knowledge_point,
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
        'estimated_minutes': t.estimated_minutes,
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
    return {
        'id': p.id, 'title': p.title, 'description': p.description,
        'status': p.status,
        'tasks_done': done, 'tasks_total': total,
        'progress': round(done / total * 100, 1) if total else 0,
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
    task = StudyPlanTask(
        plan_id=plan_id, title=title[:200], task_type=task_type,
        knowledge_point_id=kp_id, resource_id=res_id,
        question_count=data.get('question_count'),
        estimated_minutes=data.get('estimated_minutes'),
        order_num=max_order + 1,
    )
    db.session.add(task)
    if plan.status == 'completed':
        plan.status = 'active'  # 加了新任务，计划重新激活
    db.session.commit()
    return jsonify({'id': task.id, 'message': '任务已添加'})


@api_learning_bp.route('/learning/plans/<int:plan_id>/tasks/<int:task_id>', methods=['PUT'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_plan_task_toggle(plan_id, task_id):
    """任务打卡：done ↔ pending，同步流转计划状态"""
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
    if status not in ('pending', 'done'):
        return jsonify({'message': 'status 须为 pending 或 done'}), 400

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
        'message': '已打卡' if status == 'done' else '已取消打卡',
        'status': task.status,
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

    try:
        from ai_service.services import ai_chat_reply
        reply = ai_chat_reply(db.session, cleaned, context)
    except Exception:
        logger.exception('AI 学习助手对话失败')
        return jsonify({'message': 'AI 服务暂不可用，请稍后重试'}), 500
    return jsonify({'reply': reply})


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

    now = utcnow()
    prog = UserNodeProgress.query.filter_by(user_id=user.id, node_id=node_id).first()
    if not prog:
        prog = UserNodeProgress(user_id=user.id, path_id=enr.path_id, node_id=node_id)
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

    try:
        db.session.flush()  # 提前触发唯一约束校验
    except IntegrityError:
        db.session.rollback()
        return jsonify({'message': '操作冲突，请重试'}), 409

    # 以 DB 实况重算选课进度（避免增量维护的并发误差）
    mastered_ids = {p.node_id for p in UserNodeProgress.query.filter_by(
        user_id=user.id, path_id=enr.path_id, status='mastered').all()}
    enr.completed_count = len(mastered_ids)
    all_nodes = LearningPathNode.query.filter_by(path_id=enr.path_id) \
        .order_by(LearningPathNode.order_num).all()
    next_node = next((n for n in all_nodes if n.id not in mastered_ids), None)
    enr.current_node_id = next_node.id if next_node else None
    if not next_node and all_nodes:
        if enr.status != 'completed':
            enr.status = 'completed'
            enr.completed_at = now
    elif enr.status == 'completed':
        enr.status = 'active'
        enr.completed_at = None

    db.session.commit()
    return jsonify({
        'message': '进度已更新',
        'node_status': status,
        'completed_count': enr.completed_count,
        'total_count': enr.total_count,
        'current_node_id': enr.current_node_id,
        'enrollment_status': enr.status,
    })


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

    return jsonify({
        'nodes': [{
            'id': kp.id, 'name': kp.name, 'description': kp.description,
            'difficulty': kp.difficulty, 'chapter_id': kp.chapter_id,
            'chapter_name': kp.chapter.name if kp.chapter else None,
        } for kp in kps],
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
