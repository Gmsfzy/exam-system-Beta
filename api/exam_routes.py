from flask import Blueprint, request, jsonify
import random
from database.models import User, Exam, ExamQuestion, ExamStudent, Question, ExamStatusEnum
from database import db

from utils.timeutil import iso_local, parse_dt
from utils.redis_cache import get_cache, set_cache, invalidate_exam_cache, CacheKey
from utils.security import limiter, RateLimitConfig, verify_token

api_exam_bp = Blueprint('api_exam', __name__)

@api_exam_bp.route('/exams', methods=['GET'])
def api_list_exams():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    
    cache_key = CacheKey.exams_key(user.id)
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return jsonify(cached_data)
    
    if user.is_teacher():
        exams = Exam.query.filter_by(creator_id=user.id).all()
    else:
        exam_ids = [es.exam_id for es in ExamStudent.query.filter_by(student_id=user.id).all()]
        exams = Exam.query.filter(Exam.id.in_(exam_ids)).all()
    
    result = [{
        'id': e.id,
        'title': e.title,
        'description': e.description,
        'start_time': iso_local(e.start_time),
        'end_time': iso_local(e.end_time),
        'duration': e.duration,
        'status': e.status,
        'question_count': len(e.exam_questions),
        'student_count': len(e.exam_students),
        'created_at': iso_local(e.created_at)
    } for e in exams]
    
    set_cache(cache_key, result, expires=120)
    return jsonify(result)

@api_exam_bp.route('/exams', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_create_exam():
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    data = request.get_json()
    try:
        start_time = parse_dt(data['start_time'])
        end_time = parse_dt(data['end_time'])
    except:
        return jsonify({'message': '时间格式错误'}), 400
    
    if start_time >= end_time:
        return jsonify({'message': '开始时间必须早于结束时间'}), 400
    
    exam = Exam(
        title=data['title'],
        description=data.get('description', ''),
        start_time=start_time,
        end_time=end_time,
        duration=data['duration'],
        creator_id=user.id,
        status=ExamStatusEnum.DRAFT
    )
    db.session.add(exam)
    db.session.commit()
    invalidate_exam_cache(user.id)
    return jsonify({'message': '创建成功', 'id': exam.id})

@api_exam_bp.route('/exams/<int:id>', methods=['GET'])
def api_get_exam(id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    is_teacher = user.is_teacher()
    # 缓存按角色隔离：教师视角含邀请码，学生视角不含
    cache_key = f"{CacheKey.EXAM}:{id}:{'t' if is_teacher else 's'}"
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return jsonify(cached_data)

    exam = Exam.query.get_or_404(id)
    if is_teacher and exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403

    result = {
        'id': exam.id,
        'title': exam.title,
        'description': exam.description,
        'start_time': iso_local(exam.start_time),
        'end_time': iso_local(exam.end_time),
        'duration': exam.duration,
        'status': exam.status,
        'question_count': len(exam.exam_questions),
        'student_count': len(exam.exam_students),
    }
    # 邀请码/邀请链接仅创建教师可见，防止学生自行邀请他人参考
    if is_teacher:
        result['invitation_code'] = exam.invitation_code
        result['invitation_url'] = exam.invitation_url
    else:
        result['invitation_code'] = None
        result['invitation_url'] = None

    set_cache(cache_key, result, expires=120)
    return jsonify(result)

@api_exam_bp.route('/exams/<int:id>', methods=['PUT'])
def api_update_exam(id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = Exam.query.get_or_404(id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权修改'}), 403
    
    data = request.get_json()
    try:
        start_time = parse_dt(data['start_time'])
        end_time = parse_dt(data['end_time'])
    except:
        return jsonify({'message': '时间格式错误'}), 400
    
    if start_time >= end_time:
        return jsonify({'message': '开始时间必须早于结束时间'}), 400
    
    exam.title = data['title']
    exam.description = data.get('description', '')
    exam.start_time = start_time
    exam.end_time = end_time
    exam.duration = data['duration']
    db.session.commit()
    invalidate_exam_cache(id)
    return jsonify({'message': '更新成功'})

@api_exam_bp.route('/exams/<int:id>/publish', methods=['POST'])
def api_publish_exam(id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = db.session.get(Exam, id)
    if not exam:
        return jsonify({'message': '考试不存在'}), 404
    if exam.creator_id != user.id:
        return jsonify({'message': '无权发布'}), 403
    
    if exam.status not in [ExamStatusEnum.DRAFT, ExamStatusEnum.ENDED]:
        return jsonify({'message': '只能发布草稿或已结束的考试'}), 400
    
    if not exam.exam_questions:
        return jsonify({'message': '考试必须至少包含一道题目'}), 400
    
    exam.status = ExamStatusEnum.PUBLISHED
    db.session.commit()
    invalidate_exam_cache(id)
    return jsonify({'message': '发布成功'})

@api_exam_bp.route('/exams/<int:id>', methods=['DELETE'])
def api_delete_exam(id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = db.session.get(Exam, id)
    if not exam:
        return jsonify({'message': '考试不存在'}), 404
    if exam.creator_id != user.id:
        return jsonify({'message': '无权删除'}), 403
    
    db.session.delete(exam)
    db.session.commit()
    invalidate_exam_cache(id)
    return jsonify({'message': '删除成功'})

@api_exam_bp.route('/exams/<int:id>/end', methods=['POST'])
def api_end_exam(id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = db.session.get(Exam, id)
    if not exam:
        return jsonify({'message': '考试不存在'}), 404
    if exam.creator_id != user.id:
        return jsonify({'message': '无权结束'}), 403
    
    if exam.status != ExamStatusEnum.PUBLISHED:
        return jsonify({'message': '只能结束已发布的考试'}), 400
    
    exam.status = ExamStatusEnum.ENDED
    db.session.commit()
    invalidate_exam_cache(id)
    return jsonify({'message': '结束成功'})

@api_exam_bp.route('/exams/<int:id>/questions', methods=['GET'])
def api_exam_questions(id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    # 该接口为教师组卷管理用途，响应包含正确答案，仅允许考试创建者访问；
    # 学生答题走 /api/exam/<id>/take（不返回答案）。鉴权必须先于缓存读取。
    if not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403

    exam = db.session.get(Exam, id)
    if not exam:
        return jsonify({'message': '考试不存在'}), 404
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403

    cache_key = f"{CacheKey.EXAM_QUESTIONS}:{id}"
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return jsonify(cached_data)

    questions = []
    for eq in sorted(exam.exam_questions, key=lambda x: x.order):
        q = eq.question
        if q is None:
            continue
        questions.append({
            'id': q.id,
            'content': q.content,
            'type': q.type,
            'difficulty': q.difficulty,
            'options': q.options,
            'answer': q.answer,
            'score': eq.score or 0,
            'order': eq.order
        })
    
    set_cache(cache_key, questions, expires=60)
    return jsonify(questions)

@api_exam_bp.route('/exams/<int:id>/add_questions', methods=['POST'])
def api_add_exam_questions(id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = db.session.get(Exam, id)
    if not exam:
        return jsonify({'message': '考试不存在'}), 404
    if exam.creator_id != user.id:
        return jsonify({'message': '无权修改'}), 403
    
    data = request.get_json()
    question_ids = data.get('question_ids', [])
    for q_id in question_ids:
        existing = ExamQuestion.query.filter_by(exam_id=id, question_id=q_id).first()
        if not existing:
            max_order = ExamQuestion.query.filter_by(exam_id=id).count()
            eq = ExamQuestion(exam_id=id, question_id=q_id, order=max_order+1)
            db.session.add(eq)
    
    db.session.commit()
    invalidate_exam_cache(id)
    return jsonify({'message': '添加成功'})

@api_exam_bp.route('/exams/<int:id>/generate_invitation', methods=['POST'])
def api_generate_invitation(id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403

    exam = db.session.get(Exam, id)
    if not exam:
        return jsonify({'message': '考试不存在'}), 404
    if exam.creator_id != user.id:
        return jsonify({'message': '无权修改'}), 403

    data = request.get_json()
    generate_code = data.get('generate_code', False)
    generate_url = data.get('generate_url', False)
    generate_qr = data.get('generate_qr', False)

    result = {'success': True, 'invitation_code': None, 'invitation_url': None, 'qr_code_data': None}

    if generate_code and not exam.invitation_code:
        exam.generate_invitation_code()

    if (generate_url or generate_qr) and exam.invitation_code and not exam.invitation_url:
        exam.generate_invitation_url(request.host_url)

    db.session.commit()

    if generate_code and exam.invitation_code:
        result['invitation_code'] = exam.invitation_code

    if (generate_url or generate_qr) and exam.invitation_url:
        result['invitation_url'] = exam.invitation_url

    if generate_qr and exam.invitation_url:
        try:
            import qrcode
            import io
            import base64
            img = qrcode.make(exam.invitation_url)
            buf = io.BytesIO()
            img.save(buf)
            buf.seek(0)
            result['qr_code_data'] = base64.b64encode(buf.read()).decode('utf-8')
        except ImportError:
            pass

    return jsonify(result)

@api_exam_bp.route('/exams/<int:id>/remove_question/<int:q_id>', methods=['POST'])
def api_remove_exam_question(id, q_id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    exam = db.session.get(Exam, id)
    if not exam:
        return jsonify({'message': '考试不存在'}), 404
    if exam.creator_id != user.id:
        return jsonify({'message': '无权修改'}), 403
    
    eq = ExamQuestion.query.filter_by(exam_id=id, question_id=q_id).first()
    if eq:
        db.session.delete(eq)
        remaining = ExamQuestion.query.filter_by(exam_id=id).order_by(ExamQuestion.order).all()
        for i, r in enumerate(remaining, 1):
            r.order = i
        db.session.commit()
        invalidate_exam_cache(id)
        return jsonify({'message': '移除成功'})
    return jsonify({'message': '题目不存在'}), 400

_QUESTION_TYPES = ['single_choice', 'multiple_choice', 'fill_blank', 'true_false',
                   'short_answer', 'programming', 'application', 'calculation']

@api_exam_bp.route('/exams/<int:id>/smart_composition', methods=['POST'])
def api_smart_composition(id):
    """智能组卷：按题型数量与难度比例从题库随机抽题加入考试"""
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403

    exam = db.session.get(Exam, id)
    if not exam:
        return jsonify({'message': '考试不存在'}), 404
    if exam.creator_id != user.id:
        return jsonify({'message': '无权修改'}), 403

    data = request.get_json(silent=True) or {}
    major_id = data.get('major_id')
    try:
        total_questions = int(data.get('total_questions', 10))
    except (TypeError, ValueError):
        total_questions = 10
    source_filter = data.get('source_filter', 'all')
    warnings = []

    type_counts = {}
    for qt in _QUESTION_TYPES:
        try:
            count = int(data.get(f'type_{qt}') or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            type_counts[qt] = count

    difficulty_dist = {}
    for diff in ('easy', 'medium', 'hard'):
        try:
            percent = int(data.get(f'diff_{diff}') or 0)
        except (TypeError, ValueError):
            percent = 0
        if percent > 0:
            difficulty_dist[diff] = percent

    added_ids = [eq.question_id for eq in exam.exam_questions]
    base_query = Question.query.filter(Question.id.notin_(added_ids))
    if major_id:
        base_query = base_query.filter_by(major_id=major_id)
    if source_filter != 'all':
        base_query = base_query.filter_by(source=source_filter)

    selected_questions = []
    if type_counts:
        for q_type, count in type_counts.items():
            pool = base_query.filter_by(type=q_type).all()
            if len(pool) < count:
                warnings.append(f'该题型题目不足，期望{count}道，实际{len(pool)}道')
                count = len(pool)
            if difficulty_dist:
                total_diff = sum(difficulty_dist.values())
                picked = []
                for diff, percent in difficulty_dist.items():
                    diff_pool = [q for q in pool if q not in picked and q.difficulty == diff]
                    need = min(max(1, round(count * percent / total_diff)), len(diff_pool))
                    if diff_pool and need:
                        picked.extend(random.sample(diff_pool, need))
                if len(picked) < count and pool:
                    remain = [q for q in pool if q not in picked]
                    picked.extend(random.sample(remain, min(count - len(picked), len(remain))))
                selected_questions.extend(picked[:count])
            elif pool:
                selected_questions.extend(random.sample(pool, count))
    else:
        pool = base_query.all()
        selected_count = min(total_questions, len(pool))
        if difficulty_dist:
            total_diff = sum(difficulty_dist.values())
            picked = []
            for diff, percent in difficulty_dist.items():
                diff_pool = [q for q in pool if q not in picked and q.difficulty == diff]
                need = min(max(1, round(selected_count * percent / total_diff)), len(diff_pool))
                if diff_pool and need:
                    picked.extend(random.sample(diff_pool, need))
            if len(picked) < selected_count and pool:
                remain = [q for q in pool if q not in picked]
                picked.extend(random.sample(remain, min(selected_count - len(picked), len(remain))))
            selected_questions = picked[:selected_count]
        else:
            selected_questions = random.sample(pool, selected_count) if pool else []

    max_order = ExamQuestion.query.filter_by(exam_id=id).count()
    added = 0
    for i, q in enumerate(selected_questions):
        existing = ExamQuestion.query.filter_by(exam_id=id, question_id=q.id).first()
        if not existing:
            db.session.add(ExamQuestion(exam_id=id, question_id=q.id, order=max_order + added + 1))
            added += 1
    db.session.commit()
    invalidate_exam_cache(id)

    return jsonify({'message': f'智能组卷完成，新添加 {added} 道题目', 'added': added, 'warnings': warnings})