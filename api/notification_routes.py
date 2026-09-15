from flask import Blueprint, request, jsonify, current_app
from database.models import Notification, User, Exam, Result, NotificationTypeEnum
from database import db
from utils.timeutil import utcnow, iso_local, fmt_local
from utils.security import verify_token
from datetime import timedelta

api_notification_bp = Blueprint('api_notification', __name__)

def _current_user():
    """通知接口统一鉴权：身份只认 JWT，不再信任 user_id 参数（防 IDOR）。"""
    user = verify_token()
    if not user:
        return None, (jsonify({'error': '请先登录'}), 401)
    return user, None

def create_notification(user_id, title, content='', type='info', related_type=None, related_id=None, commit=True):
    """创建通知助手函数。

    commit=True（默认）：立即提交，适合请求路径单次调用；
    commit=False：仅 add 不提交，由调用方在外层循环结束后统一 commit
    （如 scheduler 批量收卷，避免循环内逐行提交争抢写锁、提前半提交）。
    """
    notification = Notification(
        user_id=user_id,
        title=title,
        content=content,
        type=type,
        related_type=related_type,
        related_id=related_id
    )
    db.session.add(notification)
    if commit:
        db.session.commit()
    return notification

def create_exam_publish_notification(exam):
    """考试发布时给所有学生发送通知"""
    students = User.query.filter_by(role='student').all()
    for student in students:
        create_notification(
            user_id=student.id,
            title=f'新考试发布：{exam.title}',
            content=f'考试「{exam.title}」已发布，请及时查看并参加。',
            type='info',
            related_type='exam',
            related_id=exam.id
        )

def create_exam_result_notification(result, commit=True):
    """考试成绩发布时给学生发送通知"""
    create_notification(
        user_id=result.student_id,
        title=f'考试成绩已公布：{result.exam.title}',
        content=f'您在「{result.exam.title}」中的成绩为 {result.score}/{result.total_score}。',
        type='success',
        related_type='result',
        related_id=result.id,
        commit=commit
    )

def create_manual_grade_notification(exam_id):
    """有需要人工评分的试卷时给教师发送通知"""
    teachers = User.query.filter_by(role='teacher').all()
    exam = db.session.get(Exam, exam_id)
    exam_title = exam.title if exam else '某次考试'
    
    for teacher in teachers:
        create_notification(
            user_id=teacher.id,
            title=f'有新的试卷需要批改',
            content=f'考试「{exam_title}」有试卷需要人工批改，请及时处理。',
            type='warning',
            related_type='exam',
            related_id=exam_id
        )

@api_notification_bp.route('/notifications', methods=['GET'])
def get_notifications():
    """获取当前用户的通知列表"""
    user, err = _current_user()
    if err:
        return err
    user_id = user.id

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    notifications = Notification.query.filter_by(user_id=user_id)\
        .order_by(Notification.created_at.desc())\
        .paginate(page=page, per_page=per_page)

    return jsonify({
        'notifications': [{
            'id': n.id,
            'title': n.title,
            'content': n.content,
            'type': n.type,
            'read': n.read,
            'related_type': n.related_type,
            'related_id': n.related_id,
            'created_at': iso_local(n.created_at),
            'time_ago': get_time_ago(n.created_at)
        } for n in notifications.items],
        'total': notifications.total,
        'page': page,
        'per_page': per_page
    })

@api_notification_bp.route('/notifications/unread', methods=['GET'])
def get_unread_count():
    """获取未读通知数量"""
    user, err = _current_user()
    if err:
        return err
    count = Notification.query.filter_by(user_id=user.id, read=False).count()
    return jsonify({'unread_count': count})

@api_notification_bp.route('/notifications/<int:id>/read', methods=['PUT'])
def mark_as_read(id):
    """标记单个通知为已读（校验归属）"""
    user, err = _current_user()
    if err:
        return err
    notification = Notification.query.get_or_404(id)
    if notification.user_id != user.id:
        return jsonify({'error': '无权操作他人通知'}), 403
    notification.read = True
    db.session.commit()
    return jsonify({'success': True})

@api_notification_bp.route('/notifications/read_all', methods=['PUT'])
def mark_all_as_read():
    """标记当前用户所有通知为已读"""
    user, err = _current_user()
    if err:
        return err
    Notification.query.filter_by(user_id=user.id, read=False).update({'read': True})
    db.session.commit()
    return jsonify({'success': True})

@api_notification_bp.route('/notifications/<int:id>', methods=['DELETE'])
def delete_notification(id):
    """删除单个通知（校验归属）"""
    user, err = _current_user()
    if err:
        return err
    notification = Notification.query.get_or_404(id)
    if notification.user_id != user.id:
        return jsonify({'error': '无权操作他人通知'}), 403
    db.session.delete(notification)
    db.session.commit()
    return jsonify({'success': True})

@api_notification_bp.route('/notifications/clear_all', methods=['DELETE'])
def clear_all_notifications():
    """清空当前用户所有通知"""
    user, err = _current_user()
    if err:
        return err
    Notification.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    return jsonify({'success': True})

def get_time_ago(dt):
    """计算时间差并返回友好格式"""
    now = utcnow()
    diff = now - dt
    
    if diff < timedelta(minutes=1):
        return '刚刚'
    elif diff < timedelta(hours=1):
        minutes = int(diff.total_seconds() // 60)
        return f'{minutes}分钟前'
    elif diff < timedelta(days=1):
        hours = int(diff.total_seconds() // 3600)
        return f'{hours}小时前'
    elif diff < timedelta(days=7):
        days = diff.days
        return f'{days}天前'
    else:
        return fmt_local(dt, '%Y-%m-%d')