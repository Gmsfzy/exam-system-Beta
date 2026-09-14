from flask import Blueprint, request, jsonify
from database.models import User, Exam, ExamSession, ExamStudent, Answer, ExamQuestion, ExamStatusEnum
from database import db
from ai_service.services import ai_grade_exam
from utils.security import limiter, RateLimitConfig, verify_token
from utils.timeutil import utcnow, iso_local
from utils.logger import logger

api_execution_bp = Blueprint('api_execution', __name__)

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
    
    existing_session = ExamSession.query.filter_by(exam_id=exam_id, student_id=user.id).first()
    if existing_session:
        return jsonify({'message': '考试会话已存在', 'session_id': existing_session.id})
    
    session = ExamSession(
        exam_id=exam_id,
        student_id=user.id,
        start_time=now,
        status='in_progress'
    )
    db.session.add(session)
    db.session.commit()
    return jsonify({'message': '开始成功', 'session_id': session.id})

@api_execution_bp.route('/exam/<int:exam_id>/take', methods=['GET'])
def api_take_exam(exam_id):
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403
    
    exam = Exam.query.get_or_404(exam_id)
    session = ExamSession.query.filter_by(exam_id=exam_id, student_id=user.id).first()
    if not session:
        return jsonify({'message': '未开始考试'}), 400
    
    questions = []
    for eq in sorted(exam.exam_questions, key=lambda x: x.order):
        q = eq.question
        answer = Answer.query.filter_by(session_id=session.id, question_id=q.id).first()
        questions.append({
            'id': q.id,
            'content': q.content,
            'type': q.type,
            'options': q.options,
            'student_answer': answer.student_answer if answer else ''
        })
    
    return jsonify({
        'exam': {
            'title': exam.title,
            'description': exam.description,
            'duration': exam.duration,
            'start_time': iso_local(exam.start_time),
            'end_time': iso_local(exam.end_time)
        },
        'session_id': session.id,
        'questions': questions
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
    # 题目必须属于该考试
    eq = ExamQuestion.query.filter_by(exam_id=exam_id, question_id=question_id).first()
    if not eq:
        return jsonify({'message': '题目不属于该考试'}), 400

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

    try:
        ai_grade_exam(db.session, session.id)
        # 自动收录错题（AI 批改后 Answers 已有 is_correct）
        try:
            from api.learning_routes import sync_wrong_from_exam
            sync_wrong_from_exam(user.id, exam_id)
        except Exception:
            logger.exception("错题自动收录失败（非关键）exam_id=%s", exam_id)
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
    db.session.commit()
    
    return jsonify({
        'message': '已记录',
        'switch_count': session.switch_count
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
    """学生查看自己的考试报告"""
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403
    
    from database.models import Result
    result = Result.query.filter_by(exam_id=exam_id, student_id=user.id).first()
    if not result:
        return jsonify({'message': '无成绩记录'}), 404
    
    return jsonify({
        'exam_id': exam_id,
        'score': result.score,
        'total_score': result.total_score,
        'submitted_at': iso_local(result.submitted_at),
        'ai_analysis': result.ai_analysis
    })