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

    storage_uri = Config.RATE_LIMIT_STORAGE_URI
    # 限流存储探活：配置指向 Redis 但连不通时回落内存（避免请求期 hits 才爆连接错误全线 500）
    if storage_uri.startswith('redis://'):
        try:
            import redis as _redis
            _probe = _redis.from_url(storage_uri, socket_timeout=3, socket_connect_timeout=3)
            _probe.ping()
        except Exception as e:
            logger.warning(f'限流 Redis 存储不可达（{e}），回落 memory://；多进程部署请确保 Redis 可用')
            storage_uri = 'memory://'
    if storage_uri.startswith('memory') and not Config.DEBUG:
        logger.warning('限流使用进程内 memory:// 存储：仅单进程部署计数准确，'
                       '横向扩容（多 worker）请配置 RATE_LIMIT_STORAGE_URI 指向 Redis')

    limiter = Limiter(
        get_remote_address,
        app=app,
        storage_uri=storage_uri,
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
        # 携带非空 Bearer token 的 API 请求豁免 CSRF（攻击者跨源无法自动附加 Authorization 头）；
        # 伪造/格式不符的 Authorization 头不再享有豁免，回落 CSRF 校验（v4.6.1 收紧）
        auth = request.headers.get('Authorization', '')
        if auth.startswith('Bearer ') and auth[7:].strip():
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
    import datetime as dt
    import jwt
    from database import db
    from database.models import User

    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ')[1]
        try:
            payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        except Exception:
            return None
        user = db.session.get(User, payload['user_id'])
        if user is None:
            return None
        # 吊销水位（v4.6.1）：登出前签发（iat 早于 token_valid_at）的令牌一律失效；
        # 无 iat 的历史令牌在用户登出后同样视为失效（下次登录起携带 iat）
        valid_at = getattr(user, 'token_valid_at', None)
        if valid_at is not None:
            iat = payload.get('iat')
            if iat is None:
                return None
            issued = dt.datetime.fromtimestamp(int(iat), tz=dt.timezone.utc)
            if issued < valid_at:
                return None
        return user
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