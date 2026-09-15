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