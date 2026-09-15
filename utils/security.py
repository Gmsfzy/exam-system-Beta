from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask import request, jsonify, current_app
from config import Config
import logging

logger = logging.getLogger(__name__)

limiter = None
csrf = None

def init_security(app):
    global limiter, csrf

    limiter = Limiter(
        get_remote_address,
        app=app,
        storage_uri=Config.RATE_LIMIT_STORAGE_URI,
        default_limits=[Config.RATE_LIMIT_DEFAULT],
        headers_enabled=Config.RATE_LIMIT_HEADERS_ENABLED
    )

    # 关闭默认 CSRF 检查，改为手动智能检查：
    # - 带 Authorization header（Bearer token）的 API 请求自动豁免
    # - 其余请求（表单/cookie 会话）要求 CSRF token
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False
    csrf = CSRFProtect(app)

    # 无需 CSRF 保护的公开接口（登录/注册/获取 token 等，认证前无 session）；
    # 日志上报接口也在此豁免——未登录请求由视图内 verify_token 返回 401
    _CSRF_EXEMPT_PATHS = ('/api/login', '/api/register', '/api/csrf-token', '/api/logs', '/api/logs/vue')

    @app.before_request
    def _smart_csrf_check():
        # Bearer token 认证的 API 请求不受 CSRF 影响，自动豁免
        if request.headers.get('Authorization'):
            return
        # 公开认证接口（登录/注册/拿 token）豁免
        if request.path in _CSRF_EXEMPT_PATHS:
            return
        # 其余请求（HTML 表单、cookie 会话）执行 CSRF 校验
        try:
            csrf.protect()
        except Exception as e:
            logger.warning(f"CSRF 验证失败: {str(e)}")
            return jsonify({'error': 'CSRF 验证失败', 'message': str(e)}), 400

    # 注：400 错误页统一由 app.py 的 errorhandler 处理，此处不再重复注册

    @app.route('/api/csrf-token', methods=['GET'])
    @limiter.exempt
    def get_csrf_token():
        token = generate_csrf()
        return jsonify({'csrf_token': token})

def verify_token():
    """从 Authorization: Bearer <JWT> 解析并返回当前用户，失败返回 None。"""
    import jwt
    from database import db
    from database.models import User

    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
            return db.session.get(User, payload['user_id'])
        except Exception:
            return None
    return None

def get_limiter():
    return limiter

def get_csrf():
    return csrf

def validate_csrf_token():
    if not Config.CSRF_ENABLED:
        return True
    
    csrf_token = request.headers.get('X-CSRF-TOKEN') or \
                 request.args.get('csrf_token') or \
                 request.form.get('csrf_token')
    
    if not csrf_token:
        return False
    
    from flask_wtf.csrf import validate_csrf
    try:
        validate_csrf(csrf_token)
        return True
    except Exception as e:
        logger.warning(f"CSRF Token 验证失败: {e}")
        return False

def require_csrf_token(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not Config.CSRF_ENABLED:
            return f(*args, **kwargs)
        
        if not validate_csrf_token():
            return jsonify({'error': 'CSRF 验证失败'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

class RateLimitConfig:
    AUTH = "5 per minute"
    AI_GENERATE = "3 per minute"
    QUESTION_QUERY = "60 per minute"
    EXAM_SUBMIT = "1 per 30 seconds"
    RESULT_QUERY = "30 per minute"
    DATA_WRITE = "20 per minute"
    LOG_REPORT = "30 per minute"  # 前端日志上报：落盘类接口，严于全局默认 60/min 防灌日志
    DEFAULT = "60 per minute"