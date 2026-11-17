from flask import Blueprint, request, jsonify
from database.models import User
from database import db
from config import Config
from utils.logger import logger
from utils.decorators import log_errors, log_performance
from utils.security import limiter, RateLimitConfig, verify_token
from utils.timeutil import utcnow
import jwt
import datetime as dt

api_auth_bp = Blueprint('api_auth', __name__)

# 字段上限，和 User 模型保持同源（改模型时这里必须同步）。
_USERNAME_MIN, _USERNAME_MAX = 2, 20
_PASSWORD_MIN = 6
_EMAIL_MAX = 120
_ROLE_ALLOWED = frozenset(('student', 'teacher', 'admin'))


def generate_token(user):
    payload = {
        'user_id': user.id,
        'username': user.username,
        'role': user.role,
        # iat 供吊销水位比对（v4.6.1）：早于 user.token_valid_at 签发的令牌登出后失效
        'iat': int(utcnow().timestamp()),
        'exp': utcnow() + dt.timedelta(days=7)
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm='HS256')

@api_auth_bp.route('/login', methods=['POST'])
@limiter.limit(RateLimitConfig.AUTH)
@log_errors
@log_performance
def api_login():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'message': '用户名和密码不能为空'}), 400
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        token = generate_token(user)
        logger.info(f"User {user.id} ({username}) logged in via API")
        return jsonify({
            'token': token,
            'user': {'id': user.id, 'username': user.username, 'role': user.role}
        })
    logger.warning(f"Failed login attempt for username: {username}")
    return jsonify({'message': '用户名或密码错误'}), 401

@api_auth_bp.route('/register', methods=['POST'])
@limiter.limit(RateLimitConfig.AUTH)
@log_errors
@log_performance
def api_register():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    # 开发阶段保留自选角色（测试需要）；上线前必须收紧为强制 student 或管理员审批，否则可自助提权教师
    role = (data.get('role') or 'student').strip().lower()
    email = (data.get('email') or '').strip() or None

    # ── 输入长度/格式校验（v7.24.2，和 User 模型字段保持同源，防止 DB 截断） ──
    if not username:
        return jsonify({'message': '用户名不能为空'}), 400
    if len(username) < _USERNAME_MIN or len(username) > _USERNAME_MAX:
        return jsonify({'message': f'用户名长度需 {_USERNAME_MIN}-{_USERNAME_MAX} 字符'}), 400
    if not password:
        return jsonify({'message': '密码不能为空'}), 400
    if len(password) < _PASSWORD_MIN:
        return jsonify({'message': f'密码至少 {_PASSWORD_MIN} 位'}), 400
    if role not in _ROLE_ALLOWED:
        return jsonify({'message': '角色非法（仅支持 student/teacher/admin）'}), 400
    if email:
        if len(email) > _EMAIL_MAX:
            return jsonify({'message': f'邮箱长度不能超过 {_EMAIL_MAX} 字符'}), 400
        if '@' not in email or '.' not in email.split('@')[-1]:
            return jsonify({'message': '邮箱格式不正确'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'message': '用户名已存在'}), 400

    if email and User.query.filter_by(email=email).first():
        return jsonify({'message': '邮箱已被注册'}), 400

    user = User(username=username, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = generate_token(user)
    return jsonify({
        'token': token,
        'user': {'id': user.id, 'username': user.username, 'role': user.role},
        'message': '注册成功'
    })

@api_auth_bp.route('/user/me', methods=['GET'])
def api_current_user():
    user = verify_token()
    if user:
        return jsonify({'id': user.id, 'username': user.username, 'role': user.role, 'email': user.email,
                        'is_study_report_public': bool(user.is_study_report_public)})
    return jsonify({'message': '未登录'}), 401


@api_auth_bp.route('/user/me', methods=['PUT'])
@log_errors
def api_update_current_user():
    """v7.7 个人资料更新：当前可改邮箱（后续可扩展 nickname/avatar 等）。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    if 'email' in data:
        new_email = (data.get('email') or '').strip() or None
        if new_email:
            # 长度先卡，防止超过 db.String(120) 被 PostgreSQL 拒掉
            if len(new_email) > _EMAIL_MAX:
                return jsonify({'message': f'邮箱长度不能超过 {_EMAIL_MAX} 字符'}), 400
            # 格式最基本校验（含 @ 和顶级域名的点）
            if '@' not in new_email or '.' not in new_email.split('@')[-1]:
                return jsonify({'message': '邮箱格式不正确'}), 400
            # 唯一性校验（排除自己）
            dup = User.query.filter_by(email=new_email).filter(User.id != user.id).first()
            if dup:
                return jsonify({'message': '该邮箱已被其他用户使用'}), 400
        user.email = new_email
    if 'is_study_report_public' in data:
        user.is_study_report_public = bool(data.get('is_study_report_public'))
    db.session.commit()
    return jsonify({'id': user.id, 'username': user.username, 'role': user.role, 'email': user.email,
                    'is_study_report_public': bool(user.is_study_report_public)})


@api_auth_bp.route('/change-password', methods=['POST'])
@limiter.limit(RateLimitConfig.AUTH)
@log_errors
def api_change_password():
    """修改密码：验证旧密码 → 更新 hash → 自动吊销所有旧 token（立即生效）。v7.7 新增。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    old_pwd = (data.get('old_password') or '').strip()
    new_pwd = (data.get('new_password') or '').strip()
    if not old_pwd or not new_pwd:
        return jsonify({'message': '旧密码和新密码不能为空'}), 400
    if len(new_pwd) < _PASSWORD_MIN:
        return jsonify({'message': f'新密码至少 {_PASSWORD_MIN} 位'}), 400
    if old_pwd == new_pwd:
        return jsonify({'message': '新密码不能与旧密码相同'}), 400
    if not user.check_password(old_pwd):
        return jsonify({'message': '旧密码不正确'}), 400
    user.set_password(new_pwd)
    # 吊销水位前进 1 秒，保证所有之前签发的 JWT 立即失效（包括当前请求的 token）
    user.token_valid_at = utcnow().replace(microsecond=0) + dt.timedelta(seconds=1)
    db.session.commit()
    logger.info('User %s changed password (tokens revoked)', user.id)
    return jsonify({'message': '密码修改成功，请重新登录'})


@api_auth_bp.route('/logout', methods=['POST'])
@log_errors
def api_logout():
    """登出吊销（v4.6.1）：置吊销水位，此前签发的全部 JWT 即时失效（多端同踢）。"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    # 水位对齐到下一整秒：iat 同为秒精度，若截断到当前秒则“签发与登出同秒”的旧 token 会同秒相等而漏吊销；
    # 进位到下一秒同时保证登出后下一秒内重新登录的新令牌不被误杀
    user.token_valid_at = utcnow().replace(microsecond=0) + dt.timedelta(seconds=1)
    db.session.commit()
    logger.info(f"User {user.id} ({user.username}) logged out (tokens revoked)")
    return jsonify({'message': '已登出'})