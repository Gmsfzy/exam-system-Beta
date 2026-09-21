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
        return jsonify({'id': user.id, 'username': user.username, 'role': user.role})
    return jsonify({'message': '未登录'}), 401


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