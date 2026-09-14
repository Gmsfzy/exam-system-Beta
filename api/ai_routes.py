from flask import Blueprint, request, jsonify
from database.models import User, Major, Course, QuestionTypeEnum, DifficultyEnum
from database import db
from ai_service.services import ai_generate_questions
from utils.security import limiter, RateLimitConfig, verify_token
from utils.logger import logger

api_ai_bp = Blueprint('api_ai', __name__)

@api_ai_bp.route('/ai/generate', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_ai_generate():
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    data = request.get_json()
    major_name = data.get('major_name', '').strip()
    course_name = data.get('course_name', '').strip()
    question_type = data.get('type')
    difficulty = data.get('difficulty')
    try:
        count = int(data.get('count', 5))
    except (TypeError, ValueError):
        count = 5
    count = max(1, min(count, 20))
    description = data.get('description', '').strip()
    question_mode = data.get('question_mode', 'ai')
    source = 'past' if question_mode == 'past' else 'ai'
    
    if not major_name:
        return jsonify({'message': '请输入专业名称'}), 400
    
    major = Major.query.filter_by(name=major_name).first()
    if not major:
        major = Major(name=major_name)
        db.session.add(major)
        db.session.commit()
        db.session.refresh(major)
        logger.info("AI 出题自动创建专业: %s", major_name)
    
    course = None
    if course_name:
        course = Course.query.filter_by(name=course_name, major_id=major.id).first()
        if not course:
            course = Course(name=course_name, major_id=major.id)
            db.session.add(course)
            db.session.commit()
            db.session.refresh(course)
            logger.info("AI 出题自动创建课程: %s", course_name)

    try:
        questions = ai_generate_questions(db.session, major.id, question_type, difficulty, count, description, course.id if course else None, source)
        return jsonify({'message': f'成功生成{len(questions)}道题目', 'count': len(questions)})
    except Exception:
        logger.exception("AI 生成题目失败 major=%s type=%s", major_name, question_type)
        return jsonify({'message': 'AI 生成失败，请稍后重试或检查 AI 服务配置'}), 500

@api_ai_bp.route('/question-types', methods=['GET'])
def api_question_types():
    types = []
    for t in dir(QuestionTypeEnum):
        if not t.startswith('_') and isinstance(getattr(QuestionTypeEnum, t), str):
            types.append({
                'value': getattr(QuestionTypeEnum, t),
                'label': QuestionTypeEnum.label(getattr(QuestionTypeEnum, t))
            })
    return jsonify(types)

@api_ai_bp.route('/difficulties', methods=['GET'])
def api_difficulties():
    diffs = []
    for d in dir(DifficultyEnum):
        if not d.startswith('_') and isinstance(getattr(DifficultyEnum, d), str):
            diffs.append({
                'value': getattr(DifficultyEnum, d),
                'label': getattr(DifficultyEnum, d).replace('easy', '简单').replace('medium', '中等').replace('hard', '困难')
            })
    return jsonify(diffs)