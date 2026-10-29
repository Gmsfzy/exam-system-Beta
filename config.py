import os
import sys
from urllib.parse import quote_plus
from dotenv import load_dotenv


def _get_app_dir():
    """返回应用真实根目录。

    - PyInstaller frozen 模式下，sys.executable 所在目录是用户可写目录，
      数据文件（instance/、uploads/、.env）必须落在这里；
      sys._MEIPASS 是临时解压目录（只读、进程退出即清理），仅用于 SPA dist 等资源。
    - 开发模式下 __file__ 所在目录就是项目根。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.dirname(__file__))


# 应用根目录（frozen = exe 所在目录；dev = 项目根）
APP_DIR = _get_app_dir()

# .env 加载：优先从 exe/项目根读取；frozen 模式下 PyInstaller 打包的 .env
# 若放在 _MEIPASS 里也会被 dotenv 搜索到，但 exe 旁的同名文件优先级更高
load_dotenv(os.path.join(APP_DIR, '.env'), override=True)

# instance 目录（数据库真实存放位置，可写）
_INSTANCE_DIR = os.path.join(APP_DIR, 'instance')
os.makedirs(_INSTANCE_DIR, exist_ok=True)


def _build_sqlite_uri(db_path):
    """把绝对路径拼成 SQLAlchemy 可用的 sqlite URI。

    统一转正斜杠：Windows 得到 sqlite:///D:/... ，POSIX 得到 sqlite:////abs/... ，
    两者均为 SQLAlchemy 认可的绝对路径写法。
    """
    return 'sqlite:///' + os.path.abspath(db_path).replace('\\', '/')


class Config:
    # 应用根目录（frozen = exe 所在目录；dev = 项目根）—— instance/uploads/.env 均基于此
    APP_DIR = _get_app_dir()

    # ── 前端 SPA 托管（可选）──
    # 默认启用：Flask 直接托管 frontend/dist 构建产物；
    # 设 ENABLE_SPA_HOSTING=false 时关闭 SPA 路由，适合前端独立部署到 CDN/Nginx 的场景。
    ENABLE_SPA_HOSTING = os.getenv('ENABLE_SPA_HOSTING', 'true').lower() == 'true'
    # SPA dist 目录覆盖：生产部署时如需覆盖默认路径可在此显式指定，
    # 例如 FRONTEND_DIST=/var/www/exam-frontend/dist
    FRONTEND_DIST = os.getenv('FRONTEND_DIST', '')

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
        'http://localhost:5000', 'http://127.0.0.1:5000', 'http://172.16.10.172:5000',
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
    # 数据库定时备份（utils.backup，由后台调度线程按日执行）：
    # 默认开启，每天最多一份，轮转保留最近 N 份（仅清理自动备份，不动手工 .bak_*）。
    DB_BACKUP_ENABLED = os.getenv('DB_BACKUP_ENABLED', 'true').lower() == 'true'
    DB_BACKUP_KEEP = int(os.getenv('DB_BACKUP_KEEP', '7'))

    # 通知外部渠道旁路投递（utils.notify_channels）：默认关闭，开启后按事件
    # 白名单将站内通知镜像投递到邮件/企微钉钉群机器人 webhook。
    NOTIFY_EXTERNAL_ENABLED = os.getenv('NOTIFY_EXTERNAL_ENABLED', 'false').lower() == 'true'
    # 逗号分隔的可外发 related_type 白名单，默认仅成绩公布（防群发刷屏）
    NOTIFY_EXTERNAL_RELATED_TYPES = os.getenv('NOTIFY_EXTERNAL_RELATED_TYPES', 'result')
    # SMTP 发件（收件人本人邮箱）
    NOTIFY_SMTP_HOST = os.getenv('NOTIFY_SMTP_HOST', '')
    NOTIFY_SMTP_PORT = int(os.getenv('NOTIFY_SMTP_PORT', '465'))
    NOTIFY_SMTP_USER = os.getenv('NOTIFY_SMTP_USER', '')
    NOTIFY_SMTP_PASSWORD = os.getenv('NOTIFY_SMTP_PASSWORD', '')
    NOTIFY_SMTP_FROM = os.getenv('NOTIFY_SMTP_FROM', '')
    NOTIFY_SMTP_SSL = os.getenv('NOTIFY_SMTP_SSL', 'true').lower() == 'true'
    NOTIFY_SMTP_STARTTLS = os.getenv('NOTIFY_SMTP_STARTTLS', 'false').lower() == 'true'
    # 群机器人 webhook（generic/wechat/dingtalk）
    NOTIFY_WEBHOOK_URL = os.getenv('NOTIFY_WEBHOOK_URL', '')
    NOTIFY_WEBHOOK_KIND = os.getenv('NOTIFY_WEBHOOK_KIND', 'generic')
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
    # ── 缓存后端选择 ──
    # auto       : 先试真实 Redis（localhost:6379），连不上再试 Fakeredis
    #              （pip install fakeredis 即启用，纯 Python 无服务进程），
    #              都没有则完全降级 DB 穿透。推荐开发机/其他电脑。
    # real       : 必须真实 Redis，连不上直接告警 + 降级 DB。推荐生产。
    # fakeredis  : 强制用 Fakeredis（不连真实 Redis），用于离线/测试环境。
    # disabled   : 完全关闭缓存，所有 @cached 装饰器直接穿透 DB。
    REDIS_BACKEND = os.getenv('REDIS_BACKEND', 'auto').lower()

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
