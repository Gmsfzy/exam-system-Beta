from flask import Blueprint, request, jsonify
from database.models import Major, Question
from database import db

from utils.redis_cache import get_cache, set_cache, invalidate_major_cache, invalidate_question_cache, CacheKey
from utils.security import verify_token

api_major_bp = Blueprint('api_major', __name__)

def _require_teacher():
    user = verify_token()
    if not user:
        return None, (jsonify({'message': '请先登录'}), 401)
    if not user.is_teacher():
        return None, (jsonify({'message': '无权操作，仅教师可管理专业'}), 403)
    return user, None

@api_major_bp.route('/majors', methods=['GET'])
def api_list_majors():
    # 登录即可访问（学生端悬赏等场景需要专业列表）
    if not verify_token():
        return jsonify({'message': '请先登录'}), 401
    cached_data = get_cache(CacheKey.MAJORS)
    if cached_data is not None:
        return jsonify(cached_data)

    majors = Major.query.all()
    result = [{'id': m.id, 'name': m.name, 'description': m.description} for m in majors]
    set_cache(CacheKey.MAJORS, result, expires=600)
    return jsonify(result)

@api_major_bp.route('/majors/<int:id>', methods=['GET'])
def api_get_major(id):
    if not verify_token():
        return jsonify({'message': '请先登录'}), 401
    cache_key = f"{CacheKey.MAJOR}:{id}"
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return jsonify(cached_data)

    m = Major.query.get_or_404(id)
    result = {'id': m.id, 'name': m.name, 'description': m.description}
    set_cache(cache_key, result, expires=300)
    return jsonify(result)

@api_major_bp.route('/majors', methods=['POST'])
def api_add_major():
    user, err = _require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'message': '缺少必要参数（name）'}), 400
    if Major.query.filter_by(name=data['name']).first():
        return jsonify({'message': '专业已存在'}), 400
    m = Major(name=data['name'], description=data.get('description', ''))
    db.session.add(m)
    db.session.commit()
    invalidate_major_cache()
    return jsonify({'message': '添加成功', 'id': m.id})

@api_major_bp.route('/majors/<int:id>', methods=['PUT'])
def api_update_major(id):
    user, err = _require_teacher()
    if err:
        return err
    m = Major.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'message': '缺少必要参数（name）'}), 400
    if Major.query.filter(Major.name == data['name'], Major.id != id).first():
        return jsonify({'message': '专业已存在'}), 400
    m.name = data['name']
    m.description = data.get('description', '')
    db.session.commit()
    invalidate_major_cache(id)
    return jsonify({'message': '更新成功'})

@api_major_bp.route('/majors/<int:id>', methods=['DELETE'])
def api_delete_major(id):
    user, err = _require_teacher()
    if err:
        return err
    m = Major.query.get_or_404(id)
    count = Question.query.filter_by(major_id=id).count()
    if count > 0:
        return jsonify({'message': f'该专业下还有{count}道题目，无法删除'}), 400
    db.session.delete(m)
    db.session.commit()
    invalidate_major_cache(id)
    invalidate_question_cache(major_id=id)
    return jsonify({'message': '删除成功'})
