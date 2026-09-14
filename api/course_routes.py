from flask import Blueprint, request, jsonify
from database.models import Course
from database import db

from utils.redis_cache import get_cache, set_cache, invalidate_course_cache, invalidate_chapter_cache, invalidate_question_cache, CacheKey
from utils.security import verify_token

api_course_bp = Blueprint('api_course', __name__)

def _require_teacher():
    user = verify_token()
    if not user:
        return None, (jsonify({'message': '请先登录'}), 401)
    if not user.is_teacher():
        return None, (jsonify({'message': '无权操作，仅教师可管理课程'}), 403)
    return user, None

@api_course_bp.route('/courses', methods=['GET'])
def api_list_courses():
    # 登录即可访问（学生端悬赏等场景需要课程列表）
    if not verify_token():
        return jsonify({'message': '请先登录'}), 401
    major_id = request.args.get('major_id')
    
    if major_id:
        cache_key = f"{CacheKey.COURSES_BY_MAJOR}:{major_id}"
    else:
        cache_key = CacheKey.COURSES
    
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return jsonify(cached_data)
    
    query = Course.query
    if major_id:
        query = query.filter(Course.major_id == int(major_id))
    courses = query.all()
    
    result = [{
        'id': c.id,
        'name': c.name,
        'description': c.description,
        'credit': c.credit,
        'semester': c.semester,
        'major_id': c.major_id
    } for c in courses]
    
    set_cache(cache_key, result, expires=300)
    return jsonify(result)

@api_course_bp.route('/courses', methods=['POST'])
def api_add_course():
    user, err = _require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data.get('name') or data.get('major_id') is None:
        return jsonify({'message': '缺少必要参数（name/major_id）'}), 400
    course = Course(
        name=data['name'],
        description=data.get('description', ''),
        credit=data.get('credit'),
        semester=data.get('semester', ''),
        major_id=data['major_id']
    )
    db.session.add(course)
    db.session.commit()
    invalidate_course_cache()
    return jsonify({'message': '添加成功', 'id': course.id})

@api_course_bp.route('/courses/<int:id>', methods=['PUT'])
def api_update_course(id):
    user, err = _require_teacher()
    if err:
        return err
    course = Course.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'message': '缺少必要参数（name）'}), 400
    course.name = data['name']
    course.description = data.get('description', '')
    course.credit = data.get('credit')
    course.semester = data.get('semester', '')
    db.session.commit()
    invalidate_course_cache(id)
    return jsonify({'message': '更新成功'})

@api_course_bp.route('/courses/<int:id>', methods=['DELETE'])
def api_delete_course(id):
    user, err = _require_teacher()
    if err:
        return err
    course = Course.query.get_or_404(id)
    db.session.delete(course)
    db.session.commit()
    invalidate_course_cache(id)
    invalidate_chapter_cache(course_id=id)
    invalidate_question_cache(course_id=id)
    return jsonify({'message': '删除成功'})