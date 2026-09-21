from flask import Blueprint, request, jsonify, Response
import io
import json
import random
from database.models import (
    User, Exam, ExamQuestion, ExamStudent, ExamSession, Answer, Result,
    Question, Notification, ExamStatusEnum, KnowledgePoint, question_knowledge_point,
)
from database import db

from utils.timeutil import iso_local, parse_dt
from utils.redis_cache import (
    get_cache, set_cache, invalidate_exam_cache, invalidate_result_cache,
    CacheKey, delete_cache,
)
from utils.security import limiter, RateLimitConfig, verify_token
from utils.permissions import require_teacher

api_exam_bp = Blueprint('api_exam', __name__)


# ── v4.3 考务配置字段：读取校验 + 序列化 ─────────────────────────────

_SCORE_STRATEGIES = ('last', 'best')
_PAPER_MODES = ('unified', 'random')
_MULTI_RULES = ('all_or_nothing', 'partial')


def _apply_exam_config(exam, data):
    """从请求体读取 v4.3 考务配置（仅处理出现的键），非法值抛 ValueError"""
    if 'results_published' in data:
        exam.results_published = bool(data['results_published'])
    if 'max_attempts' in data:
        try:
            n = int(data['max_attempts'])
        except (TypeError, ValueError):
            raise ValueError('作答次数必须为整数')
        if not 1 <= n <= 10:
            raise ValueError('作答次数须在 1-10 之间')
        exam.max_attempts = n
    if 'score_strategy' in data:
        if data['score_strategy'] not in _SCORE_STRATEGIES:
            raise ValueError('成绩策略仅支持 last/best')
        exam.score_strategy = data['score_strategy']
    if 'paper_mode' in data:
        if data['paper_mode'] not in _PAPER_MODES:
            raise ValueError('组卷模式仅支持 unified/random')
        exam.paper_mode = data['paper_mode']
    if 'random_count' in data:
        try:
            rc = int(data['random_count'])
        except (TypeError, ValueError):
            raise ValueError('抽题数必须为整数')
        if rc < 0:
            raise ValueError('抽题数不能为负')
        exam.random_count = rc
    if 'shuffle_options' in data:
        exam.shuffle_options = bool(data['shuffle_options'])
    if 'multi_score_rule' in data:
        if data['multi_score_rule'] not in _MULTI_RULES:
            raise ValueError('多选得分规则仅支持 all_or_nothing/partial')
        exam.multi_score_rule = data['multi_score_rule']
    if 'anonymous_grading' in data:
        exam.anonymous_grading = bool(data['anonymous_grading'])


def _exam_config(exam):
    """考务配置序列化（list/detail 共用）"""
    return {
        'results_published': bool(exam.results_published),
        'max_attempts': exam.max_attempts or 1,
        'score_strategy': exam.score_strategy or 'last',
        'paper_mode': exam.paper_mode or 'unified',
        'random_count': exam.random_count or 0,
        'shuffle_options': bool(exam.shuffle_options),
        'multi_score_rule': exam.multi_score_rule or 'all_or_nothing',
        'anonymous_grading': bool(exam.anonymous_grading),
    }


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
        'created_at': iso_local(e.created_at),
        'results_published': bool(e.results_published),
    } for e in exams]
    
    set_cache(cache_key, result, expires=120)
    return jsonify(result)

@api_exam_bp.route('/exams', methods=['POST'])
@limiter.limit(RateLimitConfig.DATA_WRITE)
def api_create_exam():
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
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
    try:
        _apply_exam_config(exam, data)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
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
    # v4.3 学生门控：仅受邀（或有作答记录）的学生可查看本场考试
    if not is_teacher:
        involved = ExamStudent.query.filter_by(exam_id=id, student_id=user.id).first() \
            or ExamSession.query.filter_by(exam_id=id, student_id=user.id).first()
        if not involved:
            return jsonify({'message': '您未被邀请参加此考试'}), 403

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
        result.update(_exam_config(exam))
    else:
        result['invitation_code'] = None
        result['invitation_url'] = None
        # 成绩是否已发布：学生端据此决定是否展示分数入口
        result['results_published'] = bool(exam.results_published)

    set_cache(cache_key, result, expires=120)
    return jsonify(result)

@api_exam_bp.route('/exams/<int:id>', methods=['PUT'])
def api_update_exam(id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
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
    try:
        _apply_exam_config(exam, data)
    except ValueError as e:
        db.session.rollback()
        return jsonify({'message': str(e)}), 400
    db.session.commit()
    invalidate_exam_cache(id)
    return jsonify({'message': '更新成功'})

@api_exam_bp.route('/exams/<int:id>/publish', methods=['POST'])
def api_publish_exam(id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
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
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
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
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
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
    # 该接口为教师组卷管理用途，响应包含正确答案；学生答题走 /api/exam/<id>/take（不返回答案）。鉴权必须先于缓存读取。
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='未登录')
    if err:
        return err

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
            'order': eq.order,
            'knowledge': q.knowledge,
            'material': q.material,                # v4.3 材料题共享材料
            'material_group': q.material_group,    # v4.3 同组共享同一材料
        })
    
    set_cache(cache_key, questions, expires=60)
    return jsonify(questions)

@api_exam_bp.route('/exams/<int:id>/add_questions', methods=['POST'])
def api_add_exam_questions(id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
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
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err

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
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
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
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err

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


# ── v4.3 成绩发布控制 / 补考授权 / 实时监控 ────────────────────────

def _get_owned_exam(user, id):
    """教师创建者归属校验，返回 (exam, err_response)"""
    if not user or not user.is_teacher():
        return None, (jsonify({'message': '无权访问'}), 403)
    exam = db.session.get(Exam, id)
    if not exam:
        return None, (jsonify({'message': '考试不存在'}), 404)
    if exam.creator_id != user.id:
        return None, (jsonify({'message': '无权操作'}), 403)
    return exam, None


@api_exam_bp.route('/exams/<int:id>/publish_results', methods=['POST'])
def api_publish_results(id):
    """成绩发布开关：首次发布时对全部成绩统一补发通知 + Socket 推送"""
    user = verify_token()
    exam, err = _get_owned_exam(user, id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    published = bool(data.get('published', True))
    exam.results_published = published

    if published:
        from api.notification_routes import create_exam_result_notification
        from api.exam_engine import notify_student_result_published
        for r in Result.query.filter_by(exam_id=id).all():
            # 幂等：交卷时已单独通知过的成绩不重发
            exists = Notification.query.filter_by(
                user_id=r.student_id, related_type='result', related_id=r.id).first()
            if not exists:
                create_exam_result_notification(r, commit=False)
            notify_student_result_published(r.student_id, id, r.id)

    db.session.commit()
    invalidate_exam_cache(id)
    invalidate_result_cache(id)
    return jsonify({'message': '成绩已发布' if published else '成绩已撤回（学生不可见）'})


@api_exam_bp.route('/exams/<int:id>/grant_attempt', methods=['POST'])
def api_grant_attempt(id):
    """补考授权：设置某学生额外作答次数 extra_attempts（0 撤销）"""
    user = verify_token()
    exam, err = _get_owned_exam(user, id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    try:
        student_id = int(data.get('student_id'))
        extra = int(data.get('extra', 1))
    except (TypeError, ValueError):
        return jsonify({'message': '参数错误：student_id/extra 须为整数'}), 400
    if not 0 <= extra <= 10:
        return jsonify({'message': '额外次数须在 0-10 之间'}), 400

    invited = ExamStudent.query.filter_by(exam_id=id, student_id=student_id).first()
    if not invited:
        return jsonify({'message': '该学生未参加此考试'}), 404

    invited.extra_attempts = extra
    db.session.commit()
    allowance = max(1, (exam.max_attempts or 1)) + extra
    return jsonify({'message': f'已授权额外作答 {extra} 次', 'extra_attempts': extra,
                    'allowance': allowance})


@api_exam_bp.route('/exams/<int:id>/monitor', methods=['GET'])
def api_exam_monitor(id):
    """监考实时视图：逐受邀学生 轮次/状态/答题进度/切屏次数/得分"""
    user = verify_token()
    exam, err = _get_owned_exam(user, id)
    if err:
        return err

    from api.exam_engine import session_question_ids

    sessions = ExamSession.query.filter_by(exam_id=id).all()
    by_student = {}
    for s in sessions:
        by_student.setdefault(s.student_id, []).append(s)

    # 进行中会话的已答题数（逐会话计数，考试规模下开销可忽略）
    running_ids = [s.id for s in sessions if s.status == 'in_progress']
    answered_map = {}
    for sid in running_ids:
        answered_map[sid] = Answer.query.filter(
            Answer.session_id == sid,
            Answer.student_answer.isnot(None),
            Answer.student_answer != '').count()

    result_map = {r.student_id: r for r in Result.query.filter_by(exam_id=id).all()}

    students = []
    seen = set()
    for es in ExamStudent.query.filter_by(exam_id=id).all():
        seen.add(es.student_id)
        ss = sorted(by_student.get(es.student_id, []), key=lambda x: x.id)
        running = next((x for x in ss if x.status == 'in_progress'), None)
        submitted = [x for x in ss if x.status != 'in_progress']
        if running:
            status, cur = 'in_progress', running
        elif submitted:
            status, cur = 'submitted', submitted[-1]
        else:
            status, cur = 'absent', None
        total_q = len(session_question_ids(cur, exam)) if cur else len(exam.exam_questions)
        r = result_map.get(es.student_id)
        students.append({
            'student_id': es.student_id,
            'username': es.student.username if es.student else None,
            'status': status,
            'attempts_used': len(ss),
            'allowance': max(1, exam.max_attempts or 1) + (es.extra_attempts or 0),
            'extra_attempts': es.extra_attempts or 0,
            'switch_count': sum((x.switch_count or 0) for x in ss),
            'answered': answered_map.get(running.id, 0) if running else (total_q if submitted else 0),
            'total_questions': total_q,
            'last_score': cur.score if (cur and status == 'submitted') else None,
            'result_score': r.score if r else None,
            'needs_manual': bool(r and Answer.query.filter_by(
                session_id=r.session_id, needs_manual_grade=True).first()) if r and r.session_id else False,
        })
    # 有会话但不在受邀表的历史异常数据也纳入监控，避免监考盲区
    for sid, ss in by_student.items():
        if sid in seen:
            continue
        students.append({'student_id': sid, 'username': None, 'status': 'in_progress' if any(
            x.status == 'in_progress' for x in ss) else 'submitted',
            'attempts_used': len(ss), 'allowance': None, 'extra_attempts': None,
            'switch_count': sum((x.switch_count or 0) for x in ss),
            'answered': None, 'total_questions': None, 'last_score': None,
            'result_score': result_map[sid].score if sid in result_map else None,
            'needs_manual': False})

    return jsonify({
        'exam': {'id': exam.id, 'title': exam.title, 'status': exam.status,
                 'results_published': bool(exam.results_published)},
        'summary': {
            'total': len(students),
            'in_progress': sum(1 for x in students if x['status'] == 'in_progress'),
            'submitted': sum(1 for x in students if x['status'] == 'submitted'),
            'absent': sum(1 for x in students if x['status'] == 'absent'),
        },
        'students': students,
    })


# ── v4.3 成绩导出 / AI 试卷质检 / 试题分析 ──────────────────────

@api_exam_bp.route('/exams/<int:id>/results/export', methods=['GET'])
def api_export_results(id):
    """成绩导出 Excel（openpyxl）：排名/得分/得分率/申诉状态"""
    user = verify_token()
    exam, err = _get_owned_exam(user, id)
    if err:
        return err

    try:
        from openpyxl import Workbook
    except ImportError:
        return jsonify({'message': '服务器未安装 openpyxl，无法导出 Excel'}), 500

    results = Result.query.filter_by(exam_id=id).order_by(Result.score.desc()).all()
    user_map = {u.id: u.username for u in User.query.filter(
        User.id.in_([r.student_id for r in results])).all()} if results else {}

    wb = Workbook()
    ws = wb.active
    ws.title = '成绩'
    ws.append(['排名', '学生账号', '得分', '总分', '得分率(%)', '交卷时间', '作答轮次', '申诉状态'])
    _review_labels = {'none': '', 'requested': '待复核', 'resolved': '申诉成立', 'rejected': '申诉驳回'}
    for rank, r in enumerate(results, 1):
        rate = round((r.score or 0) / r.total_score * 100, 1) if r.total_score else 0
        sess = db.session.get(ExamSession, r.session_id) if r.session_id else None
        ws.append([
            rank,
            user_map.get(r.student_id, str(r.student_id)),
            r.score,
            r.total_score,
            rate,
            iso_local(r.submitted_at) or '',
            (sess.attempt_no or 1) if sess else 1,
            _review_labels.get(r.review_status or 'none', ''),
        ])
    ws.column_dimensions['B'].width = 20

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        buf.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename=exam_{id}_results.xlsx'}
    )


@api_exam_bp.route('/exams/<int:id>/ai_inspect', methods=['POST'])
def api_ai_inspect_exam(id):
    """AI 试卷质检：整卷送 AI 审查答案正确性/选项互斥/歧义/难度合理性"""
    user = verify_token()
    exam, err = _get_owned_exam(user, id)
    if err:
        return err
    if not exam.exam_questions:
        return jsonify({'message': '考试尚未组卷，无需质检'}), 400

    from ai_service.services import ai_client, clean_json_text

    lines = []
    total = 0
    for eq in sorted(exam.exam_questions, key=lambda x: x.order):
        q = eq.question
        if not q:
            continue
        total += eq.score or 0
        opts = q.options if isinstance(q.options, str) else json.dumps(q.options, ensure_ascii=False)
        lines.append(f"[{eq.order}] 题型={q.type} 分值={eq.score} 难度={q.difficulty}\n"
                     f"题干：{q.content}\n选项：{opts}\n答案：{q.answer}\n解析：{q.analysis or '无'}")
    paper_text = f"试卷：{exam.title}（满分约 {total} 分，共 {len(lines)} 题）\n\n" + "\n\n".join(lines)

    system = ('你是资深考试命题质检专家。请对整卷逐题审查：答案是否正确、选项是否互斥且无漏选、'
              '题干是否有歧义或泄题、分值与难度是否匹配、解析与答案是否一致。'
              '只输出标准 JSON：{"overall_score": 0-100 整数, "summary": "总体结论", '
              '"issues": [{"question_id": 数字, "severity": "high|medium|low", '
              '"problem": "问题描述", "suggestion": "修改建议"}]}，无问题时 issues 为空数组。')
    try:
        raw = ai_client.generate_json(system, paper_text, temp=0.3, max_tok=3000)
        data = json.loads(clean_json_text(raw))
    except Exception as e:
        return jsonify({'message': f'AI 质检失败：{str(e)[:200]}'}), 502
    return jsonify({'success': True, 'inspection': data})


@api_exam_bp.route('/exams/<int:id>/item_analysis', methods=['GET'])
def api_item_analysis(id):
    """试题分析：逐题得分率/高低分组区分度（27% 法）/选项分布 + 知识点聚合。
    仅统计每位学生有效成绩（Result.session_id）对应的那次作答。"""
    user = verify_token()
    exam, err = _get_owned_exam(user, id)
    if err:
        return err

    import re as _re
    from api.exam_engine import session_question_ids

    results = Result.query.filter_by(exam_id=id).all()
    if not results:
        return jsonify({'participants': 0, 'questions': [], 'knowledge': []})

    # 有效会话：优先成绩来源会话；历史数据无 session_id 时回退到最近一次已交卷会话
    valid = {}   # student_id -> (session_id, percent)
    fallback = {}
    for s in ExamSession.query.filter_by(exam_id=id).filter(
            ExamSession.status != 'in_progress').order_by(ExamSession.id).all():
        fallback[s.student_id] = s.id
    for r in results:
        sid = r.session_id or fallback.get(r.student_id)
        if sid:
            percent = (r.score or 0) / r.total_score if r.total_score else 0
            valid[r.student_id] = (sid, percent)
    sids = sorted({sid for sid, _ in valid.values()})
    if not sids:
        return jsonify({'participants': 0, 'questions': [], 'knowledge': []})

    answers = Answer.query.filter(Answer.session_id.in_(sids)).all()
    ans_by_q = {}
    for a in answers:
        ans_by_q.setdefault(a.question_id, []).append(a)

    eqs = [eq for eq in sorted(exam.exam_questions, key=lambda x: x.order) if eq.question]
    # 逐人有效题单交集（random 模式不同学生题单不同）
    per_session_qids = {}
    for sid in sids:
        sess = db.session.get(ExamSession, sid)
        if sess:
            per_session_qids[sid] = set(session_question_ids(sess, exam))

    def _ratio(a, full):
        return min(1.0, (a.effective_score or 0) / full) if full else (1.0 if a.is_correct else 0.0)

    # 高低分组（按总分百分比，各取前/后 27%，至少 1 人）
    percents = sorted((p for _, p in valid.values()), reverse=True)
    n = len(percents)
    g = max(1, round(n * 0.27))
    hi_sids = {sid for sid, (_, p) in valid.items() if p >= percents[g - 1]} if n <= 2 * g else set(
        sid for sid, p in sorted(((sid, p) for sid, (_, p) in valid.items()),
                                 key=lambda x: -x[1])[:g])
    lo_sids = set() if n <= 2 * g else set(
        sid for sid, p in sorted(((sid, p) for sid, (_, p) in valid.items()),
                                 key=lambda x: x[1])[:g])

    q_cache = {eq.question_id: eq.question for eq in eqs}
    # 知识点主数据（v4.6.1 联动）：一次批量查 question_knowledge_point 多对多表，避免逐题懒加载 N+1
    kp_map = {}   # question_id -> [(kp_id, kp_name), ...]
    _kp_rows = db.session.execute(
        db.select(question_knowledge_point.c.question_id, KnowledgePoint.id, KnowledgePoint.name)
        .join(KnowledgePoint, KnowledgePoint.id == question_knowledge_point.c.knowledge_point_id)
        .where(question_knowledge_point.c.question_id.in_([eq.question_id for eq in eqs]))
    ).all()
    for _qid, _kid, _kname in _kp_rows:
        kp_map.setdefault(_qid, []).append((_kid, _kname))

    def _q_kps(qid):
        """知识点集合：多对多主数据优先；旧逗号分隔字符串拆分兜底（全角逗号兼容）"""
        if kp_map.get(qid):
            return kp_map[qid]
        raw = (q_cache[qid].knowledge or '').replace('，', ',')
        parts = [p.strip() for p in raw.split(',') if p.strip()]
        return [(None, p) for p in parts] or [(None, '未标注知识点')]

    sid_to_student = {sid: st for st, (sid, _) in valid.items()}
    questions_out = []
    kp_bucket = {}
    for eq in eqs:
        q = q_cache[eq.question_id]
        in_count = sum(1 for sid in sids if sid in per_session_qids and eq.question_id in per_session_qids[sid])
        alist = ans_by_q.get(eq.question_id, [])
        if not alist:
            questions_out.append({'question_id': q.id, 'order': eq.order, 'type': q.type,
                                  'content': (q.content or '')[:60],
                                  'knowledge': '，'.join(n for _, n in _q_kps(q.id) if n != '未标注知识点') or q.knowledge,
                                  'answers': 0, 'score_rate': None, 'discrimination': None,
                                  'option_dist': []})
            continue
        ratios = [_ratio(a, eq.score) for a in alist]
        score_rate = sum(ratios) / len(ratios)
        # 区分度：高分组得分率 - 低分组得分率（按会话归属学生）
        hi = [_ratio(a, eq.score) for a in alist if sid_to_student.get(a.session_id) in hi_sids]
        lo = [_ratio(a, eq.score) for a in alist if sid_to_student.get(a.session_id) in lo_sids]
        disc = (sum(hi) / len(hi) - sum(lo) / len(lo)) if hi and lo else None
        # 选择题选项分布（选中人数，原始字母）
        option_dist = []
        if q.type in ('single_choice', 'multiple_choice'):
            counts = {}
            for a in alist:
                for ch in set(_re.findall(r'[A-Za-z]', (a.student_answer or '').upper())):
                    counts[ch] = counts.get(ch, 0) + 1
            option_dist = [{'option': k, 'count': counts[k]} for k in sorted(counts)]
        questions_out.append({
            'question_id': q.id, 'order': eq.order, 'type': q.type, 'score': eq.score,
            'content': (q.content or '')[:60],
            'knowledge': '，'.join(n for _, n in _q_kps(q.id) if n != '未标注知识点') or q.knowledge,
            'difficulty': q.difficulty,
            'answers': len(alist), 'in_paper_students': in_count,
            'score_rate': round(score_rate, 4),
            'discrimination': round(disc, 4) if disc is not None else None,
            'option_dist': option_dist,
        })
        # 聚合桶按知识点实体键（有主数据 id 用 id，无则用名字）：同名不同题归一，多值逗号字段拆开归位
        for kid, kname in _q_kps(q.id):
            b = kp_bucket.setdefault((kid, kname), {'rates': [], 'discs': [], 'qids': set()})
            b['rates'].append(score_rate)
            if disc is not None:
                b['discs'].append(disc)
            b['qids'].add(q.id)

    knowledge_out = [{
        'knowledge_point_id': kid,
        'knowledge': kname,
        'question_count': len(b['rates']),
        'avg_score_rate': round(sum(b['rates']) / len(b['rates']), 4),
        'avg_discrimination': round(sum(b['discs']) / len(b['discs']), 4) if b['discs'] else None,
        'question_ids': sorted(b['qids']),
    } for (kid, kname), b in sorted(kp_bucket.items(),
                                    key=lambda x: sum(x[1]['rates']) / len(x[1]['rates']))]
    return jsonify({'participants': n, 'questions': questions_out, 'knowledge': knowledge_out})
