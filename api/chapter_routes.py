from flask import Blueprint, request, jsonify
from database import db
from database.models import Course, Chapter, User

from utils.redis_cache import get_cache, set_cache, invalidate_chapter_cache, CacheKey
from utils.security import verify_token

api_chapter_bp = Blueprint('api_chapter', __name__)

@api_chapter_bp.route('/chapters', methods=['GET'])
def get_chapters():
    user = verify_token()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if not user.is_teacher():
        return jsonify({'error': '无权访问'}), 403
    
    course_id = request.args.get('course_id')
    if not course_id:
        return jsonify({'error': '缺少course_id参数'}), 400
    
    cache_key = f"{CacheKey.CHAPTERS_BY_COURSE}:{course_id}"
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return jsonify(cached_data)
    
    chapters = Chapter.query.filter_by(course_id=course_id).order_by(Chapter.order_num).all()
    result = []
    for chapter in chapters:
        result.append({
            'id': chapter.id,
            'name': chapter.name,
            'description': chapter.description,
            'course_id': chapter.course_id,
            'order_num': chapter.order_num
        })
    
    set_cache(cache_key, result, expires=300)
    return jsonify(result)

@api_chapter_bp.route('/chapters', methods=['POST'])
def create_chapter():
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'error': '无权访问'}), 403
    
    data = request.get_json()
    name = data.get('name')
    course_id = data.get('course_id')
    
    if not name or not course_id:
        return jsonify({'error': '缺少必要参数'}), 400
    
    course = db.session.get(Course, course_id)
    if not course:
        return jsonify({'error': '课程不存在'}), 404
    
    existing_chapter = Chapter.query.filter_by(course_id=course_id, name=name).first()
    if existing_chapter:
        return jsonify({'error': '章节名称已存在'}), 400
    
    chapter = Chapter(
        name=name,
        course_id=course_id,
        description=data.get('description', ''),
        order_num=data.get('order_num', 0)
    )
    db.session.add(chapter)
    db.session.commit()
    
    invalidate_chapter_cache(course_id=course_id)
    
    return jsonify({
        'id': chapter.id,
        'name': chapter.name,
        'description': chapter.description,
        'course_id': chapter.course_id,
        'order_num': chapter.order_num
    }), 201

@api_chapter_bp.route('/chapters/<int:chapter_id>', methods=['GET'])
def get_chapter(chapter_id):
    user = verify_token()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if not user.is_teacher():
        return jsonify({'error': '无权访问'}), 403
    
    chapter = db.session.get(Chapter, chapter_id)
    if not chapter:
        return jsonify({'error': '章节不存在'}), 404
    
    return jsonify({
        'id': chapter.id,
        'name': chapter.name,
        'description': chapter.description,
        'course_id': chapter.course_id,
        'order_num': chapter.order_num
    })

@api_chapter_bp.route('/chapters/<int:chapter_id>', methods=['PUT'])
def update_chapter(chapter_id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'error': '无权访问'}), 403
    
    chapter = db.session.get(Chapter, chapter_id)
    if not chapter:
        return jsonify({'error': '章节不存在'}), 404
    
    data = request.get_json()
    name = data.get('name')
    
    if name:
        existing_chapter = Chapter.query.filter(
            Chapter.course_id == chapter.course_id,
            Chapter.name == name,
            Chapter.id != chapter_id
        ).first()
        if existing_chapter:
            return jsonify({'error': '章节名称已存在'}), 400
        chapter.name = name
    
    if 'description' in data:
        chapter.description = data['description']
    
    if 'order_num' in data:
        chapter.order_num = data['order_num']
    
    db.session.commit()
    
    invalidate_chapter_cache(course_id=chapter.course_id)
    
    return jsonify({
        'id': chapter.id,
        'name': chapter.name,
        'description': chapter.description,
        'course_id': chapter.course_id,
        'order_num': chapter.order_num
    })

@api_chapter_bp.route('/chapters/<int:chapter_id>', methods=['DELETE'])
def delete_chapter(chapter_id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'error': '无权访问'}), 403
    
    chapter = db.session.get(Chapter, chapter_id)
    if not chapter:
        return jsonify({'error': '章节不存在'}), 404
    
    course_id = chapter.course_id
    db.session.delete(chapter)
    db.session.commit()
    
    invalidate_chapter_cache(course_id=course_id)
    
    return jsonify({'message': '删除成功'}), 200
