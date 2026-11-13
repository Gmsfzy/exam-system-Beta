from flask import Blueprint, request, jsonify
from database.models import User, Major, Course, QuestionTypeEnum, DifficultyEnum, NotificationTypeEnum
from database import db
from ai_service.client import AITimeoutError, AINetworkError
from ai_service.services import ai_generate_questions
from utils.notify import create_notification
from utils.security import limiter, RateLimitConfig, verify_token
from utils.logger import logger
from utils.permissions import require_teacher
import time

api_ai_bp = Blueprint('api_ai', __name__)

@api_ai_bp.route('/ai/generate', methods=['POST'])
@limiter.limit(RateLimitConfig.AI_GENERATE)
def api_ai_generate():
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
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

    started = time.time()
    try:
        questions = ai_generate_questions(db.session, major.id, question_type, difficulty, count, description, course.id if course else None, source)
        cost = time.time() - started
        logger.info("AI 出题成功 major=%s type=%s count=%d 用时=%.1fs",
                    major_name, question_type, len(questions), cost)
        # 生成成功后给操作教师发站内通知：commit 后由 notify_socket ORM 事件自动实时
        # 推送 new_notification，铃铛角标与弹框即时更新；related_type='question' 前端
        # 点击直达题库页。AI 调用耗时较长，教师切走页面也能回来看到结果。
        # 通知属非关键路径：单独兜异常，不让它把「题已入库」误报成「生成失败」。
        try:
            course_label = course.name if course else major.name
            create_notification(
                user.id,
                f'AI 出题完成：{len(questions)} 道',
                f'「{course_label}」的 {QuestionTypeEnum.label(question_type)}·'
                f'{DifficultyEnum.label(difficulty)} 共 {len(questions)} 道题目已生成，可前往题库查看。',
                type=NotificationTypeEnum.SUCCESS,
                related_type='question',
            )
        except Exception:
            logger.exception("AI 出题成功但完成通知落库失败 major=%s", major_name)
            db.session.rollback()
        return jsonify({'message': f'成功生成{len(questions)}道题目', 'count': len(questions)})
    except AITimeoutError as e:
        # 超时与配置错误分开报：超时是“AI 还没写完”，该减道数或稍后重试；
        # 让用户去翻 AI 服务配置只会白排查一轮密钥。
        cost = time.time() - started
        logger.error("AI 出题超时 major=%s type=%s count=%d 读超时=%ss 实际等待=%.1fs: %s",
                     major_name, question_type, count, e.seconds, cost, e)
        return jsonify({'message': f'AI 响应超时（已等待 {int(cost)}s），可减少题目数量或稍后重试'}), 500
    except AINetworkError as e:
        cost = time.time() - started
        logger.exception("AI 出题网络/密钥异常 major=%s type=%s count=%d 用时=%.1fs",
                         major_name, question_type, count, cost)
        return jsonify({'message': 'AI 服务连接异常（网络或密钥），请检查 AI 服务配置'}), 500
    except Exception:
        cost = time.time() - started
        logger.exception("AI 生成题目失败 major=%s type=%s count=%d 用时=%.1fs",
                         major_name, question_type, count, cost)
        return jsonify({'message': 'AI 生成失败，请稍后重试'}), 500

@api_ai_bp.route('/question-types', methods=['GET'])
def api_question_types():
    # v4.3 鉴权小修：枚举接口不再对未登录者开放
    if not verify_token():
        return jsonify({'message': '未登录'}), 401
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
    if not verify_token():
        return jsonify({'message': '未登录'}), 401
    diffs = []
    for d in dir(DifficultyEnum):
        if not d.startswith('_') and isinstance(getattr(DifficultyEnum, d), str):
            diffs.append({
                'value': getattr(DifficultyEnum, d),
                'label': DifficultyEnum.label(getattr(DifficultyEnum, d))
            })
    return jsonify(diffs)