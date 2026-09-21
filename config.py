import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

# 项目根目录与 instance 目录（数据库真实存放位置）
_BASE_DIR = os.path.abspath(os.path.dirname(__file__))
_INSTANCE_DIR = os.path.join(_BASE_DIR, 'instance')
os.makedirs(_INSTANCE_DIR, exist_ok=True)


def _build_sqlite_uri(db_path):
    """把绝对路径拼成 SQLAlchemy 可用的 sqlite URI。

    统一转正斜杠：Windows 得到 sqlite:///D:/... ，POSIX 得到 sqlite:////abs/... ，
    两者均为 SQLAlchemy 认可的绝对路径写法。
    """
    return 'sqlite:///' + os.path.abspath(db_path).replace('\\', '/')


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
    # 数据库使用绝对路径显式指向 instance/exam_system.db。
    # 旧写法 'sqlite:///exam_system.db' 依赖 Flask-SQLAlchemy 把相对路径隐式解析到 instance/，
    # 一旦有工具/脚本按该相对 URI 在项目根目录直接建连，就会在根目录误建 0 字节空库。
    # 改为绝对路径后，任何读取本配置建连的方式都只会命中 instance 下的真实库。
    SQLALCHEMY_DATABASE_URI = _build_sqlite_uri(os.path.join(_INSTANCE_DIR, 'exam_system.db'))
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
    # 存储选择：显式环境变量优先；否则配了 Redis（REDIS_HOST/PORT）则跟随之
    # （多进程共享计数）；都没配回落 memory://（仅单进程部署下计数准确，
    # 多 worker 横向扩容时限流按进程各自计数会被稀释）。
    _redis_explicit = bool(os.getenv('REDIS_HOST') or os.getenv('REDIS_PORT'))
    _rl_redis_default = 'redis://{}{}:{}/{}'.format(
        (':' + quote_plus(os.getenv('REDIS_PASSWORD')) + '@') if os.getenv('REDIS_PASSWORD') else '',
        os.getenv('REDIS_HOST', 'localhost'), os.getenv('REDIS_PORT', '6379'),
        os.getenv('REDIS_DB', '0'))
    RATE_LIMIT_STORAGE_URI = os.getenv('RATE_LIMIT_STORAGE_URI') or (
        _rl_redis_default if _redis_explicit else 'memory://')
    RATE_LIMIT_DEFAULT = os.getenv('RATE_LIMIT_DEFAULT', '60 per minute')
    RATE_LIMIT_HEADERS_ENABLED = True
