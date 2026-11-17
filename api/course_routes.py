from flask import Blueprint, request, jsonify
from database.models import Course, Major
from database import db

from utils.redis_cache import get_cache, set_cache, invalidate_course_cache, invalidate_chapter_cache, invalidate_question_cache, CacheKey
from utils.security import verify_token

api_course_bp = Blueprint('api_course', __name__)

# Course / Chapter / Major / Department 四个模型都有 String(50) 名字列；
# 统一常量（major_routes.py 里同名常量也是 50，这里独立避免跨文件 import 循环）。
_NAME_MAX = 50
_SEMESTER_MAX = 20   # db.String(20)
_DESC_SOFT_MAX = 1000   # description 是 db.Text，这里只是展示层软限，非 DB 约束

def _require_teacher():
    """委托 utils.permissions 统一实现（RBAC 收敛）。"""
    from utils.permissions import require_teacher
    return require_teacher(deny_msg='无权操作，仅教师可管理课程')

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
    else:
        # 排除自我学习“自由学习空间”容器下的课程（不污染考试侧全局课程列表）
        self_major_ids = [m.id for m in Major.query.filter_by(name='自由学习空间').all()]
        if self_major_ids:
            query = query.filter(~Course.major_id.in_(self_major_ids))
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
    name = (data.get('name') or '').strip()
    if not name or data.get('major_id') is None:
        return jsonify({'message': '缺少必要参数（name/major_id）'}), 400
    if len(name) > _NAME_MAX:
        return jsonify({'message': f'课程名称长度不能超过 {_NAME_MAX} 字符'}), 400
    semester = (data.get('semester') or '').strip()
    if semester and len(semester) > _SEMESTER_MAX:
        return jsonify({'message': f'学期字段长度不能超过 {_SEMESTER_MAX} 字符'}), 400
    # FK 前置校验：major_id 不存在直接 400，不然 commit 时才 IntegrityError
    major = Major.query.get(data['major_id'])
    if not major:
        return jsonify({'message': '所属专业不存在'}), 400
    course = Course(
        name=name,
        description=(data.get('description') or '').strip(),
        credit=data.get('credit'),
        semester=semester,
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
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'message': '缺少必要参数（name）'}), 400
    if len(name) > _NAME_MAX:
        return jsonify({'message': f'课程名称长度不能超过 {_NAME_MAX} 字符'}), 400
    course.name = name
    course.description = (data.get('description') or '').strip()
    course.credit = data.get('credit')
    if 'semester' in data:
        semester = (data.get('semester') or '').strip()
        if semester and len(semester) > _SEMESTER_MAX:
            return jsonify({'message': f'学期字段长度不能超过 {_SEMESTER_MAX} 字符'}), 400
        course.semester = semester
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