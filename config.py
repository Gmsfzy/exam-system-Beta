import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # 调试模式：生产必须为 false（Werkzeug 调试器可致远程代码执行）
    # 本地开发在 .env 中设 FLASK_DEBUG=true 开启
    DEBUG = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'

    # 服务监听地址/端口（生产环境局域网/外网访问可设 HOST=0.0.0.0）
    HOST = os.getenv('FLASK_HOST', '127.0.0.1')
    PORT = int(os.getenv('FLASK_PORT', '5000'))

    # 跨域白名单（HTTP API 与 Socket.IO 共用）。
    # 生产部署通过环境变量 CORS_ORIGINS 配置前端地址，逗号分隔，例如：
    # CORS_ORIGINS=https://exam.example.com,https://www.example.com
    _DEV_ORIGINS = [
        'http://localhost:5173', 'http://localhost:5174',
        'http://localhost:5175', 'http://localhost:5176',
        'http://127.0.0.1:5173', 'http://127.0.0.1:5174',
        'http://127.0.0.1:5175', 'http://127.0.0.1:5176',
        'http://localhost:5000', 'http://172.16.10.172:5000',
    ]
    _env_origins = [
        o.strip() for o in os.getenv('CORS_ORIGINS', '').split(',') if o.strip()
    ]
    if _env_origins:
        # 显式配置优先（生产部署必须设置为前端实际域名）
        CORS_ORIGINS = _env_origins
    elif DEBUG:
        # 仅开发模式预置本地 Vite/局域网源
        CORS_ORIGINS = _DEV_ORIGINS
    else:
        # 生产模式默认不开放任何跨域源（同源访问不受影响）；
        # 前后端分离部署时必须显式配置 CORS_ORIGINS，避免 localhost 源带入生产
        CORS_ORIGINS = []

    # 密钥：用于会话签名与 JWT 签发。开发环境缺失时回落默认值；
    # 生产环境（DEBUG=false）缺失或仍为开发默认值时 fail-fast 拒绝启动，
    # 避免 JWT 可被伪造、会话可被篡改。
    _DEV_SECRET = 'dev-secret-key-change-in-production'
    SECRET_KEY = os.getenv('SECRET_KEY') or _DEV_SECRET
    if not DEBUG and (not os.getenv('SECRET_KEY') or SECRET_KEY == _DEV_SECRET):
        raise RuntimeError(
            '生产环境（FLASK_DEBUG 未设为 true）必须在环境变量/.env 中设置强随机 SECRET_KEY，'
            '禁止使用开发默认值。可用 python -c "import secrets;print(secrets.token_hex(32))" 生成。'
        )
    SQLALCHEMY_DATABASE_URI = 'sqlite:///exam_system.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SQLite 锁超时时间（秒），避免 AI 调用期间数据库锁报错
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30}}
    # 火山引擎豆包配置
    DOUBAN_API_KEY = os.getenv('DOUBAN_API_KEY', '')
    DOUBAN_API_URL = os.getenv('DOUBAN_API_URL')
    DOUBAN_ENDPOINT_ID = os.getenv('DOUBAN_ENDPOINT_ID')

    # Redis 缓存配置
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_TIMEOUT = int(os.getenv('REDIS_TIMEOUT', 10))

    # CSRF 防护配置
    CSRF_ENABLED = True
    # 未配置时显式回落到 SECRET_KEY（Flask-WTF 对显式 None 不回落，必须给真值）
    WTF_CSRF_SECRET_KEY = os.getenv('WTF_CSRF_SECRET_KEY') or \
        (os.getenv('SECRET_KEY') or 'dev-secret-key-change-in-production')
    WTF_CSRF_TIME_LIMIT = 3600

    # Rate Limiting 配置
    RATE_LIMIT_STORAGE_URI = os.getenv('RATE_LIMIT_STORAGE_URI', 'memory://')
    RATE_LIMIT_DEFAULT = os.getenv('RATE_LIMIT_DEFAULT', '60 per minute')
    RATE_LIMIT_HEADERS_ENABLED = True
