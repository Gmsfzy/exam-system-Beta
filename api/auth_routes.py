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
    username = data.get('username')
    password = data.get('password')
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
    username = data.get('username')
    password = data.get('password')
    # 开发阶段保留自选角色（测试需要）；上线前必须收紧为强制 student 或管理员审批，否则可自助提权教师
    role = data.get('role', 'student')
    email = data.get('email', '').strip() or None

    if not username or not password:
        return jsonify({'message': '用户名和密码不能为空'}), 400

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
            # 格式最基本校验（含 @）
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
    new_pwd = data.get('new_password') or ''
    if not old_pwd or not new_pwd:
        return jsonify({'message': '旧密码和新密码不能为空'}), 400
    if len(new_pwd) < 6:
        return jsonify({'message': '新密码至少 6 位'}), 400
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