from flask import Blueprint, request, jsonify
from database.models import User, Exam, ExamSession, Answer, ExamQuestion, Result, Question, ExamStatusEnum, QuestionTypeEnum
from database import db

from utils.redis_cache import get_cache, set_cache, invalidate_result_cache, CacheKey
from utils.security import limiter, RateLimitConfig, verify_token
from utils.timeutil import iso_local, utcnow
from utils.logger import logger
from utils.permissions import require_teacher

api_result_bp = Blueprint('api_result', __name__)


def _effective_session(exam_id, student_id, result=None):
    """成绩有效会话：优先成绩来源会话（best/last 策略随之更新），
    否则取最近一次已交卷会话（v4.3 多次作答适配，修复旧版取首次会话的错位）。"""
    if result is not None and result.session_id:
        s = db.session.get(ExamSession, result.session_id)
        if s:
            return s
    s = ExamSession.query.filter(
        ExamSession.exam_id == exam_id, ExamSession.student_id == student_id,
        ExamSession.status != 'in_progress').order_by(ExamSession.id.desc()).first()
    if s:
        return s
    return ExamSession.query.filter_by(exam_id=exam_id, student_id=student_id) \
        .order_by(ExamSession.id).first()


def _published(exam):
    return True if exam is None else bool(exam.results_published)


def _anon_name(exam, student_id):
    """盲评假名：按受邀顺序编号，不暴露真实账号"""
    ids = sorted(es.student_id for es in exam.exam_students)
    idx = (ids.index(student_id) + 1) if student_id in ids else student_id
    return f'考生{idx:02d}'


@api_result_bp.route('/results/me', methods=['GET'])
def api_my_results():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    
    results = Result.query.filter_by(student_id=user.id).all()
    exams = {e.id: e for e in Exam.query.filter(
        Exam.id.in_([r.exam_id for r in results])).all()} if results else {}
    out = []
    for r in results:
        exam = exams.get(r.exam_id)
        published = _published(exam)
        item = {
            'id': r.id,
            'exam_id': r.exam_id,
            'exam_title': exam.title if exam else '',
            'published': published,
            'submitted_at': iso_local(r.submitted_at),
            'review_status': r.review_status or 'none',
        }
        # v4.3 成绩发布控制：未发布不展示分数与解析
        if published:
            item['score'] = r.score
            item['total_score'] = r.total_score
            item['ai_analysis'] = r.ai_analysis
            item['review_reply'] = r.review_reply
        else:
            item['score'] = None
            item['total_score'] = None
            item['ai_analysis'] = None
            item['review_reply'] = None
        out.append(item)
    return jsonify(out)

@api_result_bp.route('/results/exam/<int:exam_id>', methods=['GET'])
def api_exam_results(exam_id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
    exam = Exam.query.get_or_404(exam_id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    
    results = Result.query.filter_by(exam_id=exam_id).all()
    users = {u.id: u for u in User.query.filter(
        User.id.in_([r.student_id for r in results])).all()} if results else {}
    return jsonify([{
        'id': r.id,
        'student_id': r.student_id,
        'student_name': _anon_name(exam, r.student_id) if exam.anonymous_grading
                        else (users[r.student_id].username if r.student_id in users else ''),
        'score': r.score,
        'total_score': r.total_score,
        'submitted_at': iso_local(r.submitted_at),
        'review_status': r.review_status or 'none',
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

    # v4.3 成绩发布控制：未发布时学生仅可见“已交卷”状态
    if user.is_student() and not _published(exam):
        return jsonify({
            'id': result.id, 'exam_id': result.exam_id,
            'exam_title': exam.title if exam else '',
            'published': False, 'message': '成绩尚未发布，发布后可查看得分与解析',
        })

    # 正确答案/解析公布时机：考试结束（教师手动结束 或 已过截止时间）后才对学生开放，
    # 避免考试进行中提前交卷的学生立即看到答案外传；教师（创建者）不受此限
    answers_released = True
    if user.is_student():
        answers_released = (exam.status == ExamStatusEnum.ENDED) or bool(
            exam.end_time and utcnow() > exam.end_time)

    session = _effective_session(result.exam_id, result.student_id, result)
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
                'oj_verdict': ans.oj_verdict,
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
                'oj_verdict': ans.oj_verdict,
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
        'published': True,
        'review_status': result.review_status or 'none',
        'review_reason': result.review_reason if user.is_teacher() else None,
        'review_reply': result.review_reply,
        'can_review': bool(user.is_student() and (result.review_status or 'none') in ('none', 'rejected')),
        'answers': answers
    })

@api_result_bp.route('/results/grading/<int:exam_id>', methods=['GET'])
def api_grading_list(exam_id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
    exam = Exam.query.get_or_404(exam_id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    
    students = []
    for es in exam.exam_students:
        s = es.student
        result = Result.query.filter_by(exam_id=exam_id, student_id=s.id).first()
        if result:
            session = _effective_session(exam_id, s.id, result)
            pending = Answer.query.filter_by(session_id=session.id if session else 0, needs_manual_grade=True).count()
            students.append({
                'id': s.id,
                'username': _anon_name(exam, s.id) if exam.anonymous_grading else (s.username if s else ''),
                'has_submitted': True,
                'pending_count': pending,
                'review_status': result.review_status or 'none',
            })
        else:
            students.append({
                'id': s.id,
                'username': _anon_name(exam, s.id) if exam.anonymous_grading else (s.username if s else ''),
                'has_submitted': False,
                'pending_count': 0,
                'review_status': 'none',
            })
    
    return jsonify(students)

@api_result_bp.route('/results/grading/<int:exam_id>/<int:student_id>', methods=['GET'])
def api_grading_detail(exam_id, student_id):
    try:
        user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
        if err:
            return err

        exam = Exam.query.get_or_404(exam_id)
        if exam.creator_id != user.id:
            return jsonify({'message': '无权访问'}), 403
        
        result = Result.query.filter_by(exam_id=exam_id, student_id=student_id).first()
        if not result:
            return jsonify({'message': '该学生未提交答卷'}), 400
        
        session = _effective_session(exam_id, student_id, result)
        if not session:
            return jsonify({'message': '未找到考试会话'}), 400
        
        answers = []
        for ans in Answer.query.filter_by(session_id=session.id).all():
            q = db.session.get(Question, ans.question_id)
            if not q:
                logger.warning(f"grading_detail: question {ans.question_id} not found")
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
                'oj_verdict': ans.oj_verdict,
                'score_weight': eq.score if eq else 0
            })
        
        student = db.session.get(User, student_id)
        return jsonify({
            'student_name': _anon_name(exam, student_id) if exam.anonymous_grading
                            else (student.username if student else ''),
            'current_score': result.score,
            'total_score': result.total_score,
            'attempt_no': session.attempt_no or 1,
            'answers': answers
        })
    except Exception:
        logger.exception("grading_detail 异常 exam_id=%s student_id=%s", exam_id, student_id)
        return jsonify({'message': '服务器内部错误，请稍后重试'}), 500

@api_result_bp.route('/results/grading/<int:exam_id>/<int:student_id>', methods=['POST'])
def api_save_grading(exam_id, student_id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
    exam = Exam.query.get_or_404(exam_id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    
    data = request.get_json(silent=True) or {}
    answers = data.get('answers', [])

    # 归属约束：只允许批改该考试该学生会话下的答案，
    # 防止传入其他考试的 answer_id 跨考试篡改分数
    result0 = Result.query.filter_by(exam_id=exam_id, student_id=student_id).first()
    session = _effective_session(exam_id, student_id, result0)
    if not session:
        return jsonify({'message': '该学生在此考试中无作答会话'}), 404

    # v4.3 一键采纳 AI 评分：待人工题全部直接采用 AI 分
    if data.get('accept_ai_all'):
        accepted = 0
        for ans in Answer.query.filter_by(session_id=session.id, needs_manual_grade=True).all():
            ans.manual_score = max(0.0, float(ans.score or 0))
            ans.needs_manual_grade = False
            accepted += 1
        if result0:
            result0.score = sum(a.effective_score for a in
                                Answer.query.filter_by(session_id=session.id).all())
        db.session.commit()
        invalidate_result_cache(exam_id)
        return jsonify({'message': f'已采纳 {accepted} 题 AI 评分', 'updated': accepted})

    # 逐题钳制到本题满分，防手工误填超分
    full_map = {eq.question_id: (eq.score or 0)
                for eq in ExamQuestion.query.filter_by(exam_id=exam_id).all()}
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
            full = full_map.get(ans.question_id) or 0
            if full and score > full:
                score = full
            ans.manual_score = score
        comment = ans_data.get('manual_comment')
        if comment is not None:
            ans.manual_comment = str(comment)[:1000]
        ans.needs_manual_grade = False
        updated += 1

    result = result0
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
        user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
        if err:
            return err
        
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
        
        for qtype, total in type_totals.items():
            if total > 0:
                question_type_analysis.append({
                    # v4.6.1 枚举收敛：题型中文名统一取自 QuestionTypeEnum 单一来源（原本地字典已漂移）
                    'type': QuestionTypeEnum.label(qtype),
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


# ── v4.3 成绩申诉闭环 ──────────────────────────────────────

@api_result_bp.route('/results/<int:result_id>/review', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_request_score_review(result_id):
    """学生成绩申诉：成绩发布后对得分提交复核申请（被驳回后可再次申诉）"""
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '仅学生可申诉'}), 403

    result = Result.query.get_or_404(result_id)
    if result.student_id != user.id:
        return jsonify({'message': '无权访问'}), 403

    exam = db.session.get(Exam, result.exam_id)
    if not _published(exam):
        return jsonify({'message': '成绩尚未发布，暂不可申诉'}), 400
    if (result.review_status or 'none') == 'requested':
        return jsonify({'message': '申诉已在复核中，请耐心等待教师处理'}), 400

    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'message': '请填写申诉理由'}), 400

    result.review_status = 'requested'
    result.review_reason = reason[:500]
    result.review_reply = None
    result.reviewed_at = None

    from api.notification_routes import create_notification
    create_notification(
        user_id=exam.creator_id,
        title='成绩申诉待处理',
        content=f'学生 {user.username} 对「{exam.title}」的成绩提交了复核申请：{reason[:100]}',
        type='warning', related_type='result', related_id=result.id, commit=False)
    db.session.commit()
    invalidate_result_cache(result.exam_id)
    return jsonify({'message': '申诉已提交，教师复核后将通知您'})


@api_result_bp.route('/results/<int:result_id>/review_handle', methods=['POST'])
def api_handle_score_review(result_id):
    """教师处理申诉：approve（可附 new_score 调分）/ reject，结果通知学生"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err

    result = Result.query.get_or_404(result_id)
    exam = db.session.get(Exam, result.exam_id)
    if not exam or exam.creator_id != user.id:
        return jsonify({'message': '无权处理'}), 403
    if (result.review_status or 'none') != 'requested':
        return jsonify({'message': '该成绩没有待处理的申诉'}), 400

    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return jsonify({'message': 'action 仅支持 approve/reject'}), 400
    reply = (data.get('reply') or '').strip()[:500]
    if not reply:
        return jsonify({'message': '请填写复核回复'}), 400

    old_score = result.score
    if action == 'approve':
        if data.get('new_score') is not None:
            try:
                ns = float(data['new_score'])
            except (TypeError, ValueError):
                return jsonify({'message': '新分数必须为数字'}), 400
            result.score = min(max(0.0, ns), result.total_score or ns)
        result.review_status = 'resolved'
    else:
        result.review_status = 'rejected'
    result.review_reply = reply
    result.reviewed_at = utcnow()

    from api.notification_routes import create_notification
    if action == 'approve' and result.score != old_score:
        outcome = f'申诉成立，成绩调整为 {result.score}/{result.total_score}'
    elif action == 'approve':
        outcome = '申诉成立，成绩维持不变'
    else:
        outcome = '申诉未通过，成绩维持原判定'
    create_notification(
        user_id=result.student_id,
        title=f'成绩复核结果：{exam.title}',
        content=f'{outcome}。教师回复：{reply[:200]}',
        type='success' if action == 'approve' else 'info',
        related_type='result', related_id=result.id, commit=False)
    db.session.commit()
    invalidate_result_cache(result.exam_id)
    return jsonify({'message': '已处理', 'review_status': result.review_status, 'score': result.score})


# ── v4.3 批改提效：同题集群视图 + 同题批量给分 ────────────────────

@api_result_bp.route('/results/grading/<int:exam_id>/cluster', methods=['GET'])
def api_grading_cluster(exam_id):
    """同题待批集群：按题目聚合全校待人工题作答，供“同一题批量批”视图"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    exam = Exam.query.get_or_404(exam_id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403

    sess_map = {s.id: s.student_id for s in ExamSession.query.filter_by(exam_id=exam_id).all()}
    if not sess_map:
        return jsonify([])
    pending = Answer.query.filter(
        Answer.session_id.in_(list(sess_map)), Answer.needs_manual_grade == True).all()  # noqa: E712
    full_map = {eq.question_id: (eq.score or 0)
                for eq in ExamQuestion.query.filter_by(exam_id=exam_id).all()}
    groups = {}
    for a in pending:
        g = groups.setdefault(a.question_id, [])
        sid_student = sess_map.get(a.session_id)
        q = db.session.get(Question, a.question_id)
        g.append({
            'answer_id': a.id,
            'session_id': a.session_id,
            'student_id': sid_student,
            'student_name': _anon_name(exam, sid_student) if exam.anonymous_grading
                            else (db.session.get(User, sid_student).username
                                  if sid_student and db.session.get(User, sid_student) else ''),
            'student_answer': a.student_answer,
            'ai_score': a.score,
        })
    out = []
    for qid, items in sorted(groups.items(), key=lambda x: -len(x[1])):
        q = db.session.get(Question, qid)
        out.append({
            'question_id': qid,
            'content': q.content if q else '（题目已删除）',
            'type': q.type if q else '',
            'correct_answer': q.answer if q else '',
            'analysis': q.analysis if q else '',
            'full_score': full_map.get(qid, 0),
            'pending_count': len(items),
            'items': items,
        })
    return jsonify(out)


@api_result_bp.route('/results/grading/<int:exam_id>/question/<int:question_id>/batch', methods=['POST'])
def api_grading_batch(exam_id, question_id):
    """同题批量给分：对该题全部（或勾选的）待批作答统一人工分，并重算受影响成绩"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    exam = Exam.query.get_or_404(exam_id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403

    data = request.get_json(silent=True) or {}
    try:
        score = float(data.get('score'))
    except (TypeError, ValueError):
        return jsonify({'message': 'score 必须为数字'}), 400
    eq = ExamQuestion.query.filter_by(exam_id=exam_id, question_id=question_id).first()
    if not eq:
        return jsonify({'message': '该题不在此考试内'}), 404
    score = min(max(0.0, score), eq.score or score)
    student_ids = data.get('student_ids') or None

    sess_map = {s.id: s.student_id for s in ExamSession.query.filter_by(exam_id=exam_id).all()}
    targets = Answer.query.filter(
        Answer.session_id.in_(list(sess_map)),
        Answer.question_id == question_id,
        Answer.needs_manual_grade == True).all()  # noqa: E712
    if student_ids:
        wanted = {int(x) for x in student_ids}
        targets = [a for a in targets if sess_map.get(a.session_id) in wanted]

    affected_sessions = set()
    for a in targets:
        a.manual_score = score
        a.needs_manual_grade = False
        affected_sessions.add(a.session_id)

    # 重算受影响学生总分（仅当该会话为其成绩有效会话时才有意义，统一重算后写回）
    for sid in affected_sessions:
        student_id = sess_map.get(sid)
        result = Result.query.filter_by(exam_id=exam_id, student_id=student_id).first()
        eff = _effective_session(exam_id, student_id, result)
        if result and eff and eff.id == sid:
            result.score = sum(a.effective_score for a in
                               Answer.query.filter_by(session_id=sid).all())

    db.session.commit()
    invalidate_result_cache(exam_id)
    return jsonify({'message': f'已批量评分 {len(targets)} 份', 'updated': len(targets)})