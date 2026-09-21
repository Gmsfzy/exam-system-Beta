from flask import Blueprint, request, jsonify
from database.models import User, Exam, ExamSession, ExamStudent, Answer, ExamQuestion, Question, ExamStatusEnum
from database import db
from ai_service.services import ai_grade_exam
from api.exam_engine import (
    build_session_paper, session_question_ids, session_option_map,
    canonical_answer, display_answer, display_options, _as_list,
    apply_exam_result, update_mastery_from_exam, notify_teacher,
    notify_student_result_published,
)
from utils.security import limiter, RateLimitConfig, verify_token
from utils.timeutil import utcnow, iso_local
from utils.logger import logger

api_execution_bp = Blueprint('api_execution', __name__)


def _allowance(exam, invited):
    """允许作答次数 = max_attempts + 补考授权"""
    return max(1, (exam.max_attempts or 1) + ((invited.extra_attempts or 0) if invited else 0))


def _finalize_submission(sess):
    """交卷结算（手动交卷 / 切屏 3 次强制交卷 / 超时收卷共用入口）：
    1. AI 批改（v4.3：按会话题单，含逐人随机卷；多选遵循 multi_score_rule）；
    2. 记录本次得分 session.score，按 best/last 策略幂等落 Result；
    3. 成绩已发布才发成绩通知（含 Socket 推送），未发布留待教师统一发布时通知；
    4. 自动收录错题 + 知识点掌握度联动（非关键，异常不阻塞）。
    返回 Result。
    """
    from database.models import Result
    from api.notification_routes import create_exam_result_notification
    from api.learning_routes import sync_wrong_from_exam

    exam = db.session.get(Exam, sess.exam_id)
    earned_score, total_score = ai_grade_exam(db.session, sess.id)
    sess.score = earned_score

    result, created, changed = apply_exam_result(sess, earned_score, total_score)
    if (created or changed) and exam is not None and exam.results_published:
        create_exam_result_notification(result, commit=False)
        notify_student_result_published(sess.student_id, sess.exam_id, result.id)
    db.session.commit()

    # 自动收录错题（批改已提交、Answer.is_correct 已落库；非关键路径）
    try:
        sync_wrong_from_exam(sess.student_id, sess.exam_id, session_id=sess.id)
    except Exception:
        logger.exception("错题自动收录失败（非关键）exam_id=%s", sess.exam_id)
    # v4.3 知识点掌握度联动
    try:
        update_mastery_from_exam(sess.student_id, sess.id)
    except Exception:
        logger.exception("掌握度联动失败（非关键）session_id=%s", sess.id)
    return result


@api_execution_bp.route('/exam/<int:exam_id>/start', methods=['POST'])
def api_start_exam(exam_id):
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403

    exam = Exam.query.get_or_404(exam_id)
    if exam.status != ExamStatusEnum.PUBLISHED:
        return jsonify({'message': '考试未发布'}), 400

    now = utcnow()
    if now < exam.start_time or now > exam.end_time:
        return jsonify({'message': '不在考试时间内'}), 400

    invited = ExamStudent.query.filter_by(exam_id=exam_id, student_id=user.id).first()
    if not invited:
        return jsonify({'message': '未被邀请参加此考试'}), 400

    # 已有进行中的会话：直接返回（断线恢复）
    running = ExamSession.query.filter_by(
        exam_id=exam_id, student_id=user.id, status='in_progress').first()
    if running:
        return jsonify({'message': '考试会话已存在', 'session_id': running.id,
                        'attempt_no': running.attempt_no or 1})

    used = ExamSession.query.filter_by(exam_id=exam_id, student_id=user.id).count()
    allowance = _allowance(exam, invited)
    if used >= allowance:
        return jsonify({'message': f'已达最大作答次数（{allowance} 次），如需补考请联系教师授权'}), 400

    session = ExamSession(
        exam_id=exam_id,
        student_id=user.id,
        start_time=now,
        status='in_progress',
        attempt_no=used + 1,
    )
    # v4.3 逐人随机卷 / 选项乱序：开考即固化本次题单与映射，防刷新变动
    if exam.paper_mode == 'random' or exam.shuffle_options:
        ids, option_map = build_session_paper(exam)
        session.assigned_question_ids = ids
        session.option_map = option_map
    db.session.add(session)
    db.session.commit()
    notify_teacher(exam, {'type': 'started', 'exam_id': exam_id,
                          'student': user.username, 'attempt_no': session.attempt_no})
    return jsonify({'message': '开始成功', 'session_id': session.id,
                    'attempt_no': session.attempt_no, 'allowance': allowance})


@api_execution_bp.route('/exam/<int:exam_id>/take', methods=['GET'])
def api_take_exam(exam_id):
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403

    exam = Exam.query.get_or_404(exam_id)
    sid = request.args.get('session_id', type=int)
    if sid:
        session = db.session.get(ExamSession, sid)
        if not session or session.exam_id != exam_id or session.student_id != user.id:
            return jsonify({'message': '无效会话'}), 400
    else:
        # 多轮次下优先取进行中会话，否则取最近一次（供已交卷页回看）
        session = ExamSession.query.filter_by(
            exam_id=exam_id, student_id=user.id, status='in_progress').first() \
            or ExamSession.query.filter_by(exam_id=exam_id, student_id=user.id) \
                 .order_by(ExamSession.id.desc()).first()
    if not session:
        return jsonify({'message': '未开始考试'}), 400

    option_map = session_option_map(session)
    q_ids = session_question_ids(session, exam)
    eq_map = {eq.question_id: eq for eq in exam.exam_questions}
    questions = []
    for qid in q_ids:
        q = db.session.get(Question, qid)
        if q is None:
            continue
        eq = eq_map.get(qid)
        answer = Answer.query.filter_by(session_id=session.id, question_id=qid).first()
        perm = option_map.get(str(qid))
        raw_display = display_options(q, perm) if perm else q.options
        student_answer = answer.student_answer if answer else ''
        if perm and student_answer and q.type in ('single_choice', 'multiple_choice'):
            student_answer = display_answer(session, qid, student_answer)
        questions.append({
            'id': q.id,
            'content': q.content,
            'type': q.type,
            'options': _as_list(raw_display) or raw_display,
            'student_answer': student_answer,
            'material': q.material,
            'material_group': q.material_group,
            'score': eq.score if eq else None,
        })

    invited = ExamStudent.query.filter_by(exam_id=exam_id, student_id=user.id).first()
    used = ExamSession.query.filter_by(exam_id=exam_id, student_id=user.id).count()
    return jsonify({
        'exam': {
            'title': exam.title,
            'description': exam.description,
            'duration': exam.duration,
            'start_time': iso_local(exam.start_time),
            'end_time': iso_local(exam.end_time),
        },
        'session_id': session.id,
        'session_status': session.status,
        'attempt_no': session.attempt_no or 1,
        'allowance': _allowance(exam, invited),
        'attempts_used': used,
        'questions': questions,
    })


@api_execution_bp.route('/exam/<int:exam_id>/save_answer', methods=['POST'])
def api_save_answer(exam_id):
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    question_id = data.get('question_id')
    student_answer = data.get('answer')

    session = db.session.get(ExamSession, session_id)
    if not session or session.student_id != user.id:
        return jsonify({'message': '无效会话'}), 400
    # 会话必须属于路径中的考试
    if session.exam_id != exam_id:
        return jsonify({'message': '会话与考试不匹配'}), 400
    # 交卷后禁止修改答案（防止教师批改前篡改作答）
    if session.status != 'in_progress':
        return jsonify({'message': '考试已提交，不能再修改答案'}), 400
    # v4.3：题目必须在本会话题单内（随机卷收敛到个人考卷范围）
    exam = db.session.get(Exam, exam_id)
    if question_id not in session_question_ids(session, exam):
        return jsonify({'message': '题目不属于该考试'}), 400
    # 选项乱序：显示字母答案 → 原始字母（仅选择题，非字母答案原样存）
    q = db.session.get(Question, question_id)
    if q is not None and q.type in ('single_choice', 'multiple_choice'):
        student_answer = canonical_answer(session, question_id, student_answer)

    answer = Answer.query.filter_by(session_id=session_id, question_id=question_id).first()
    if answer:
        answer.student_answer = student_answer
    else:
        answer = Answer(session_id=session_id, question_id=question_id, student_answer=student_answer)
        db.session.add(answer)

    db.session.commit()
    return jsonify({'message': '保存成功'})


@api_execution_bp.route('/exam/<int:exam_id>/submit', methods=['POST'])
@limiter.limit(RateLimitConfig.EXAM_SUBMIT)
def api_submit_exam(exam_id):
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403

    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')

    session = db.session.get(ExamSession, session_id)
    if not session or session.student_id != user.id:
        return jsonify({'message': '无效会话'}), 400
    if session.exam_id != exam_id:
        return jsonify({'message': '会话与考试不匹配'}), 400
    # 防重复提交：仅进行中的会话可交卷（重复提交不再触发批改）
    if session.status != 'in_progress':
        return jsonify({'message': '试卷已提交，请勿重复操作'}), 400

    session.end_time = utcnow()
    session.status = 'submitted'
    db.session.commit()

    exam = db.session.get(Exam, exam_id)
    notify_teacher(exam, {'type': 'submitted', 'exam_id': exam_id,
                          'student': user.username, 'attempt_no': session.attempt_no or 1})
    try:
        _finalize_submission(session)
        return jsonify({'message': '提交成功，正在批改...'})
    except Exception:
        logger.exception("AI 批改异常 session_id=%s", session.id)
        return jsonify({'message': '提交已保存，批改处理中，请稍后刷新查看成绩'}), 200


@api_execution_bp.route('/exam/<int:exam_id>/report_switch', methods=['POST'])
@limiter.limit("10 per minute")
def api_report_switch(exam_id):
    """学生端切屏上报接口（防作弊）"""
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403

    session = ExamSession.query.filter_by(exam_id=exam_id, student_id=user.id, status='in_progress').first()
    if not session:
        return jsonify({'message': '无进行中的考试会话'}), 400

    # 增加切屏次数
    session.switch_count = (session.switch_count or 0) + 1

    # 切屏达到 3 次：服务端强制交卷并立即结算（本地判分，不等待后续提交）
    force_submitted = session.switch_count >= 3
    if force_submitted:
        session.end_time = utcnow()
        session.status = 'submitted'
    db.session.commit()

    exam = db.session.get(Exam, exam_id)
    if force_submitted:
        notify_teacher(exam, {'type': 'force_submitted', 'exam_id': exam_id,
                              'student': user.username, 'switch_count': session.switch_count})
        try:
            _finalize_submission(session)
        except Exception:
            logger.exception("切屏强制交卷批改异常 session_id=%s", session.id)
    else:
        # 实时同步监考视图
        notify_teacher(exam, {'type': 'switch', 'exam_id': exam_id,
                              'student': user.username, 'switch_count': session.switch_count})

    return jsonify({
        'message': '已记录' if not force_submitted else '切屏次数已达上限，系统已强制交卷',
        'switch_count': session.switch_count,
        'force_submitted': force_submitted
    })


@api_execution_bp.route('/exam/join/<string:code>', methods=['POST'])
def api_join_exam(code):
    """学生通过邀请码（或邀请链接）主动加入已发布考试"""
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '仅学生可加入考试'}), 403

    exam = Exam.query.filter_by(invitation_code=(code or '').strip().upper()).first()
    if not exam:
        return jsonify({'message': '邀请码无效'}), 404
    if exam.status != ExamStatusEnum.PUBLISHED:
        return jsonify({'message': '考试尚未发布'}), 400

    existing = ExamStudent.query.filter_by(exam_id=exam.id, student_id=user.id).first()
    if not existing:
        db.session.add(ExamStudent(exam_id=exam.id, student_id=user.id))
        db.session.commit()
        return jsonify({'message': f'成功加入考试「{exam.title}」', 'exam_id': exam.id, 'joined': True})
    return jsonify({'message': f'您已加入考试「{exam.title}」', 'exam_id': exam.id, 'joined': False})


@api_execution_bp.route('/exam/<int:exam_id>/report', methods=['GET'])
def api_exam_report(exam_id):
    """学生查看自己的考试报告（成绩未发布时隐藏分数，v4.3）"""
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403

    from database.models import Result
    result = Result.query.filter_by(exam_id=exam_id, student_id=user.id).first()
    if not result:
        return jsonify({'message': '无成绩记录'}), 404

    exam = db.session.get(Exam, exam_id)
    published = bool(exam is None or exam.results_published)
    if not published:
        return jsonify({
            'exam_id': exam_id, 'published': False,
            'message': '成绩尚未发布，请耐心等待教师公布',
        })
    return jsonify({
        'exam_id': exam_id,
        'published': True,
        'score': result.score,
        'total_score': result.total_score,
        'submitted_at': iso_local(result.submitted_at),
        'ai_analysis': result.ai_analysis,
        'review_status': result.review_status or 'none',
        'review_reply': result.review_reply,
    })
