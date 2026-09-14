from flask import Blueprint, request, jsonify
from database.models import User, Exam, ExamSession, Answer, ExamQuestion, Result, Question, ExamStatusEnum
from database import db

from utils.redis_cache import get_cache, set_cache, invalidate_result_cache, CacheKey
from utils.security import limiter, RateLimitConfig, verify_token
from utils.timeutil import iso_local, utcnow
from utils.logger import logger

api_result_bp = Blueprint('api_result', __name__)

@api_result_bp.route('/results/me', methods=['GET'])
def api_my_results():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    
    results = Result.query.filter_by(student_id=user.id).all()
    return jsonify([{
        'id': r.id,
        'exam_id': r.exam_id,
        'exam_title': db.session.get(Exam, r.exam_id).title,
        'score': r.score,
        'total_score': r.total_score,
        'submitted_at': iso_local(r.submitted_at),
        'ai_analysis': r.ai_analysis
    } for r in results])

@api_result_bp.route('/results/exam/<int:exam_id>', methods=['GET'])
def api_exam_results(exam_id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = Exam.query.get_or_404(exam_id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    
    results = Result.query.filter_by(exam_id=exam_id).all()
    return jsonify([{
        'id': r.id,
        'student_id': r.student_id,
        'student_name': db.session.get(User, r.student_id).username,
        'score': r.score,
        'total_score': r.total_score,
        'submitted_at': iso_local(r.submitted_at)
    } for r in results])

@api_result_bp.route('/results/<int:result_id>', methods=['GET'])
def api_result_detail(result_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    
    result = Result.query.get_or_404(result_id)

    if user.is_student() and result.student_id != user.id:
        return jsonify({'message': '无权访问'}), 403

    exam = db.session.get(Exam, result.exam_id)
    if user.is_teacher() and (not exam or exam.creator_id != user.id):
        return jsonify({'message': '无权访问'}), 403

    # 正确答案/解析公布时机：考试结束（教师手动结束 或 已过截止时间）后才对学生开放，
    # 避免考试进行中提前交卷的学生立即看到答案外传；教师（创建者）不受此限
    answers_released = True
    if user.is_student():
        answers_released = (exam.status == ExamStatusEnum.ENDED) or bool(
            exam.end_time and utcnow() > exam.end_time)

    session = ExamSession.query.filter_by(exam_id=result.exam_id, student_id=result.student_id).first()
    if not session:
        return jsonify({'message': '未找到考试会话'}), 400

    answer_records = Answer.query.filter_by(session_id=session.id).all()

    answers = []
    for ans in answer_records:
        q = db.session.get(Question, ans.question_id)
        if q:
            answers.append({
                'question_id': q.id,
                'content': q.content,
                'type': q.type,
                'options': q.options,
                'correct_answer': q.answer if answers_released else '',
                'student_answer': ans.student_answer,
                'is_correct': ans.is_correct,
                'ai_score': ans.score,
                'manual_score': ans.manual_score,
                'manual_comment': ans.manual_comment,
                'needs_manual_grade': ans.needs_manual_grade,
                'analysis': q.analysis if answers_released else ''
            })
        else:
            answers.append({
                'question_id': ans.question_id,
                'content': '该题目已被删除',
                'type': 'unknown',
                'options': None,
                'correct_answer': '',
                'student_answer': ans.student_answer,
                'is_correct': ans.is_correct,
                'ai_score': ans.score,
                'manual_score': ans.manual_score,
                'manual_comment': ans.manual_comment,
                'needs_manual_grade': ans.needs_manual_grade,
                'analysis': ''
            })

    return jsonify({
        'id': result.id,
        'exam_title': exam.title if exam else '',
        'score': result.score,
        'total_score': result.total_score,
        'submitted_at': iso_local(result.submitted_at),
        'ai_analysis': result.ai_analysis,
        'answers_released': answers_released,
        'answers': answers
    })

@api_result_bp.route('/results/grading/<int:exam_id>', methods=['GET'])
def api_grading_list(exam_id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = Exam.query.get_or_404(exam_id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    
    students = []
    for es in exam.exam_students:
        s = es.student
        result = Result.query.filter_by(exam_id=exam_id, student_id=s.id).first()
        if result:
            session = ExamSession.query.filter_by(exam_id=exam_id, student_id=s.id).first()
            pending = Answer.query.filter_by(session_id=session.id if session else 0, needs_manual_grade=True).count()
            students.append({
                'id': s.id,
                'username': s.username,
                'has_submitted': True,
                'pending_count': pending
            })
        else:
            students.append({
                'id': s.id,
                'username': s.username,
                'has_submitted': False,
                'pending_count': 0
            })
    
    return jsonify(students)

@api_result_bp.route('/results/grading/<int:exam_id>/<int:student_id>', methods=['GET'])
def api_grading_detail(exam_id, student_id):
    try:
        user = verify_token()
        if not user or not user.is_teacher():
            return jsonify({'message': '无权访问'}), 403

        exam = Exam.query.get_or_404(exam_id)
        if exam.creator_id != user.id:
            return jsonify({'message': '无权访问'}), 403
        
        result = Result.query.filter_by(exam_id=exam_id, student_id=student_id).first()
        if not result:
            return jsonify({'message': '该学生未提交答卷'}), 400
        
        session = ExamSession.query.filter_by(exam_id=exam_id, student_id=student_id).first()
        if not session:
            return jsonify({'message': '未找到考试会话'}), 400
        
        answers = []
        for ans in Answer.query.filter_by(session_id=session.id).all():
            q = db.session.get(Question, ans.question_id)
            if not q:
                logging.warning(f"grading_detail: question {ans.question_id} not found")
                continue
            eq = ExamQuestion.query.filter_by(exam_id=exam_id, question_id=q.id).first()
            answers.append({
                'answer_id': ans.id,
                'question_id': q.id,
                'content': q.content,
                'type': q.type,
                'options': q.options,
                'correct_answer': q.answer,
                'student_answer': ans.student_answer,
                'ai_score': ans.score,
                'manual_score': ans.manual_score,
                'manual_comment': ans.manual_comment,
                'needs_manual_grade': ans.needs_manual_grade,
                'score_weight': eq.score if eq else 0
            })
        
        student = db.session.get(User, student_id)
        return jsonify({
            'student_name': student.username if student else '',
            'current_score': result.score,
            'total_score': result.total_score,
            'answers': answers
        })
    except Exception:
        logger.exception("grading_detail 异常 exam_id=%s student_id=%s", exam_id, student_id)
        return jsonify({'message': '服务器内部错误，请稍后重试'}), 500

@api_result_bp.route('/results/grading/<int:exam_id>/<int:student_id>', methods=['POST'])
def api_save_grading(exam_id, student_id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = Exam.query.get_or_404(exam_id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    
    data = request.get_json(silent=True) or {}
    answers = data.get('answers', [])

    # 归属约束：只允许批改该考试该学生会话下的答案，
    # 防止传入其他考试的 answer_id 跨考试篡改分数
    session = ExamSession.query.filter_by(exam_id=exam_id, student_id=student_id).first()
    if not session:
        return jsonify({'message': '该学生在此考试中无作答会话'}), 404

    updated = 0
    for ans_data in answers:
        ans = Answer.query.filter_by(id=ans_data.get('answer_id'), session_id=session.id).first()
        if not ans:
            continue
        raw_score = ans_data.get('manual_score')
        if raw_score is not None:
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                return jsonify({'message': '人工评分必须为数字'}), 400
            if score < 0:
                score = 0
            ans.manual_score = score
        comment = ans_data.get('manual_comment')
        if comment is not None:
            ans.manual_comment = str(comment)[:1000]
        ans.needs_manual_grade = False
        updated += 1

    result = Result.query.filter_by(exam_id=exam_id, student_id=student_id).first()
    if result:
        total = 0
        for ans in Answer.query.filter_by(session_id=session.id).all():
            total += ans.effective_score
        result.score = total

    db.session.commit()
    invalidate_result_cache(exam_id)
    logger.info("教师 %s 保存考试 %s 学生 %s 的人工评分，更新 %d 题", user.id, exam_id, student_id, updated)
    return jsonify({'message': '评分保存成功', 'updated': updated})

@api_result_bp.route('/results/analysis/<int:exam_id>', methods=['GET'])
@limiter.limit(RateLimitConfig.RESULT_QUERY)
def api_result_analysis(exam_id):
    try:
        user = verify_token()
        if not user or not user.is_teacher():
            return jsonify({'message': '无权访问'}), 403
        
        exam = Exam.query.get_or_404(exam_id)
        if exam.creator_id != user.id:
            return jsonify({'message': '无权访问'}), 403
        
        cache_key = CacheKey.result_analysis_key(exam_id)
        cached_data = get_cache(cache_key)
        if cached_data is not None:
            return jsonify(cached_data)
        
        results = Result.query.filter_by(exam_id=exam_id).all()
        if not results:
            result = {
                'total_students': 0,
                'avg_score': 0,
                'highest_score': 0,
                'pass_rate': 0,
                'score_distribution': {},
                'score_segments': {},
                'question_type_analysis': [],
                'rankings': []
            }
            set_cache(cache_key, result, expires=600)
            return jsonify(result)
        
        scores = [r.score for r in results]
        total_score = results[0].total_score if results else 100
        pass_score = total_score * 0.6
        
        total_students = len(results)
        avg_score = round(sum(scores) / total_students) if total_students > 0 else 0
        highest_score = max(scores) if scores else 0
        pass_count = sum(1 for s in scores if s >= pass_score)
        pass_rate = round(pass_count / total_students * 100) if total_students > 0 else 0
        
        score_distribution = {}
        for i in range(0, 101, 10):
            count = sum(1 for s in scores if i <= s < i + 10)
            score_distribution[f'{i}-{i+9}'] = count
        
        score_segments = {
            '90-100分': sum(1 for s in scores if s >= 90),
            '80-89分': sum(1 for s in scores if 80 <= s < 90),
            '70-79分': sum(1 for s in scores if 70 <= s < 80),
            '60-69分': sum(1 for s in scores if 60 <= s < 70),
            '60分以下': sum(1 for s in scores if s < 60)
        }
        
        question_type_analysis = []
        type_scores = {}
        type_totals = {}
        
        for result in results:
            session = ExamSession.query.filter_by(exam_id=exam_id, student_id=result.student_id).first()
            if session:
                for ans in Answer.query.filter_by(session_id=session.id).all():
                    q = db.session.get(Question, ans.question_id)
                    if q:
                        eq = ExamQuestion.query.filter_by(exam_id=exam_id, question_id=q.id).first()
                        score_weight = eq.score if eq else 0
                        type_scores[q.type] = type_scores.get(q.type, 0) + (ans.effective_score if hasattr(ans, 'effective_score') else (ans.score or 0))
                        type_totals[q.type] = type_totals.get(q.type, 0) + score_weight
        
        type_labels = {
            'single_choice': '单选题',
            'multiple_choice': '多选题',
            'true_false': '判断题',
            'fill_blank': '填空题',
            'short_answer': '简答题',
            'essay': '论述题'
        }
        
        for qtype, total in type_totals.items():
            if total > 0:
                question_type_analysis.append({
                    'type': type_labels.get(qtype, qtype),
                    'avg_score_percentage': round(type_scores[qtype] / (total_students * total) * 100) if total_students > 0 else 0
                })
        
        sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
        rankings = []
        for idx, r in enumerate(sorted_results, 1):
            student = db.session.get(User, r.student_id)
            percentage = round(r.score / total_score * 100) if total_score > 0 else 0
            rank_percentage = round((idx / total_students) * 100) if total_students > 0 else 0
            rankings.append({
                'rank': idx,
                'student_name': student.username if student else '',
                'score': r.score,
                'total_score': r.total_score,
                'percentage': f'{percentage}%',
                'rank_percentage': f'超越 {100 - rank_percentage}% 的学生'
            })
        
        result = {
            'total_students': total_students,
            'avg_score': avg_score,
            'highest_score': highest_score,
            'pass_rate': pass_rate,
            'score_distribution': score_distribution,
            'score_segments': score_segments,
            'question_type_analysis': question_type_analysis,
            'rankings': rankings
        }
        
        set_cache(cache_key, result, expires=600)
        return jsonify(result)
    except Exception:
        logger.exception("result_analysis 异常 exam_id=%s", exam_id)
        return jsonify({'error': '成绩分析生成失败，请稍后重试'}), 500