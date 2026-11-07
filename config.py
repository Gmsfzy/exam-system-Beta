import os
import sys
import logging
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

# config 模块级探活日志，直接用标准库 logging 避免依赖 utils.logger 造成循环导入
logger = logging.getLogger(__name__)


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


def redact_url(url):
    """连接串去密码展示形式（日志/启动横幅专用，严禁把带密码的 URI 写进日志）。"""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return '<无法解析的连接串>'


def backend_of(url):
    """按 URI 判定实际生效后端方言（sqlite / postgresql）；无法解析时当 sqlite。"""
    try:
        return make_url(url).get_backend_name()
    except Exception:
        return 'sqlite'


def resolve_engine_options(uri):
    """由「实际生效 URI」推导引擎 connect_args，与 URI 始终一致。

    为什么不直接拿 Config.SQLALCHEMY_ENGINE_OPTIONS 用了就完事：外部（如 tests/conftest.py）
    会在 import app 前只改 Config.SQLALCHEMY_DATABASE_URI 指向临时库，并不会同步重写
    引擎选项；若选项在类体里按 PG 分支定死，sqlite 引擎会收到 client_encoding 参数而招
    TypeError（sqlite3 不认），故 app 启动时必须用本函数按真实 URI 重算一次。

    - postgresql：client_encoding=UTF8 强制服务端消息用 UTF-8（中文 Windows 本机 locale
      为 GBK，否则运行期报错会以 GBK 下发并触发解码异常，见 _decode_server_message）；
      不带 SQLite 专属参数，探活用的 connect_timeout 也不进常驻引擎。
    - sqlite    ：busy_timeout=30s，避免 AI 调用期间数据库锁报错。
    """
    if backend_of(uri) == 'postgresql':
        return {'connect_args': {'client_encoding': 'UTF8'}}
    return {'connect_args': {'timeout': 30}}


def _decode_server_message(exc):
    """把异常里「非 UTF-8 的服务端消息字节」还原成可读文本。

    背景：中文 Windows 上 PG 服务端的本机 locale 为 zh_CN.936（GBK），认证阶段
    （scram 密码错误/角色不存在）返回的错误消息按 GBK 编码下发，而 client_encoding
    参数在建连握手后才生效、管不到这一段，psycopg2 固定按 UTF-8 解码 → 抛
    UnicodeDecodeError 并把真实原因（如「用户 "exam" Password 认证失败」）整个掩盖。
    UnicodeDecodeError 自带 .object（原始字节），据此按 GBK → mbcs → replace 兜底解码。
    """
    if isinstance(exc, UnicodeDecodeError) and getattr(exc, 'object', None):
        raw = exc.object or b''
        for enc in ('gbk', 'mbcs', 'cp936'):
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode('utf-8', errors='replace')
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _probe_postgres(database_url, timeout=3):
    """带短 connect_timeout 的 PostgreSQL 探活；连不上抛异常。

    仅用于启动时一次性探测，探测引擎随即 dispose，其 connect_args 不会进常驻引擎。
    client_encoding=UTF8：让建连成功后的服务端消息（含迁移期报错）统一 UTF-8，
    不再在中文 Windows 上以 GBK 下发而触发解码异常。
    """
    from sqlalchemy import create_engine
    probe = create_engine(
        database_url,
        connect_args={'connect_timeout': timeout, 'client_encoding': 'UTF8'})
    try:
        with probe.connect() as conn:
            conn.exec_driver_sql('SELECT 1')
    finally:
        probe.dispose()


# 只有指向这些地址时，才有条件判断「这台机器没装 PG」：远程目标无法从本机推断
_LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1', '0.0.0.0', ''}

# 镜像至少要这么多张表才像份完整库（本仓实际 108）：拿半截文件起服务，页面能开
# 但处处空白，比直接起不来难排查得多
_MIN_MIRROR_TABLES = 20

_OFFLINE_FALLBACK = {}      # 判定为离线交付模式时写入，供 Config 暴露给运行时


def _tcp_open(host, port, timeout=0.6):
    """端口上是否真有服务在监听（只看 TCP 能否建立，不做协议握手）。"""
    import socket
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _pg_service_names():
    """本机已安装的 PostgreSQL Windows 服务名（直读注册表，不需管理员权限）。

    不用 `Get-Service`/`sc query`：那要起外部进程，在容器/精简系统上未必可用，
    而服务安装必然在 Services 注册表项下留键。
    """
    if os.name != 'nt':
        return []
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r'SYSTEM\CurrentControlSet\Services')
        try:
            return [name for i in range(winreg.QueryInfoKey(key)[0])
                    if (name := winreg.EnumKey(key, i)).lower().startswith('postgres')]
        finally:
            winreg.CloseKey(key)
    except Exception:
        return []


def _pg_service_units():
    """非 Windows：systemd unit 文件里有没有 postgresql（装了服务就会有 unit 文件）。"""
    if os.name == 'nt':
        return []
    import glob
    patterns = ['/etc/systemd/system/postgresql*.service',
                '/usr/lib/systemd/system/postgresql*.service',
                '/lib/systemd/system/postgresql*.service']
    return [os.path.basename(p) for pat in patterns for p in glob.glob(pat)]


def _pg_binary_present():
    """PATH 或默认安装目录里能找到 PG 可执行文件，就算这台机器装过 PG。"""
    import shutil
    if any(shutil.which(exe) for exe in ('pg_ctl', 'psql', 'postgres')):
        return True
    roots = [r'C:\Program Files\PostgreSQL', r'C:\Program Files (x86)\PostgreSQL'] \
        if os.name == 'nt' else \
        ['/usr/lib/postgresql', '/usr/pgsql-16', '/usr/pgsql-15', '/var/lib/pgsql']
    return any(os.path.isdir(r) for r in roots)


def _pg_installed_on_this_machine(host, port):
    """判断「这台机器是不是压根没装 PostgreSQL」，返回 (没装, 依据说明)。

    只给 auto 档的视情降级用，判断必须保守：任何一项存在迹象都返回 False（→ 拒起服务）。
    把「PG 只是没启动/密码错」误判成「没装」，等于回到 v6.8 那个静默分叉事故：
    看着在用 PG，新数据全部落在本地 SQLite 里，而且不报错。
    """
    if str(host or '').lower() not in _LOCAL_HOSTS:
        return False, f'目标 {host}:{port} 不是本机，无法据此判断对方是否装有 PG'
    if _tcp_open(host, port):
        return False, f'{host}:{port} 有服务在监听（PG 装着，只是连接/认证失败）'
    services = _pg_service_names() or _pg_service_units()
    if services:
        return False, f'本机检测到 PostgreSQL 服务 {services}（很可能是服务已停止）'
    if _pg_binary_present():
        return False, '本机 PATH 或默认安装目录里存在 PostgreSQL'
    return True, '本机未检测到 PostgreSQL 服务、端口监听与可执行文件'


def _mirror_readable(sqlite_uri):
    """回落前确认项目内的镜像文件真能当库用：存在 + 表数够 + 版本号与数据都在。

    必须以只读方式打开：本函数跑在建 engine 之前，拿读写句柄去探会留下锁与 -wal 侧车。
    """
    import sqlite3
    url = make_url(sqlite_uri)
    if url.get_backend_name() != 'sqlite':
        # 不是 SQLite 时 .database 是库名不是路径，不拦住会报出一句看不懂的「文件不存在」
        return False, f'待校验的不是 SQLite 镜像文件：{redact_url(sqlite_uri)}'
    path = url.database
    if not path or not os.path.isfile(str(path)):
        return False, f'镜像文件不存在：{path}'
    try:
        con = sqlite3.connect(
            'file:' + os.path.abspath(path).replace(os.sep, '/') + '?mode=ro', uri=True)
    except sqlite3.Error as e:
        return False, f'镜像文件无法以只读打开：{e}'
    try:
        cur = con.cursor()
        tables = cur.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        if tables < _MIN_MIRROR_TABLES:
            return False, f'镜像里只有 {tables} 张表，不是份完整库'
        try:
            ver = cur.execute('SELECT version_num FROM alembic_version').fetchall()
        except sqlite3.Error:
            ver = []
        if not ver:
            return False, '镜像里没有 alembic_version，启动会去重放整条迁移历史'
        try:
            users = cur.execute('SELECT count(*) FROM "user"').fetchone()[0]
        except sqlite3.Error:
            users = 0
        if not users:
            return False, '镜像里 user 表为空，这份库没有可用数据'
        return True, f'{tables} 张表 / version={ver[0][0]} / user={users}'
    except sqlite3.Error as e:
        return False, f'镜像内容校验失败：{e}'
    finally:
        con.close()


def _mark_offline(reason):
    """记下「这台机器在用镜像而非 PG」，供 Config / healthz / 离线补丁使用。"""
    _OFFLINE_FALLBACK['mirror'] = '1'
    _OFFLINE_FALLBACK.setdefault('reasons', []).append(reason)


def _resolve_database_uri():
    """根据 DB_BACKEND / DATABASE_URL 解析最终 SQLALCHEMY_DATABASE_URI（模块加载时定一次）。

    分层降级口径对齐 NOTEBOOK_BACKEND / REDIS_BACKEND：
    - sqlite   : 强制 SQLite，指向 instance/exam_system.db。
    - postgres : 强制 PostgreSQL；DATABASE_URL 缺失或连不上即 RuntimeError，绝不静默降级。
    - auto     : **视情降级**（v7.5）。探活失败时先判这台机器是否根本没装 PG：
                 没装 → 校验镜像可用后回落到只读镜像（离线交付场景，数据与 PG 一致）；
                 装了却连不上（服务停/密码错/库不存在/远程不可达）→ 拒起服务，
                 绝不静默写本地——那会造成双库分叉（v6.8 踩过）。
    """
    db_backend = os.getenv('DB_BACKEND', 'auto').lower()
    database_url = os.getenv('DATABASE_URL', '').strip()
    sqlite_uri = _build_sqlite_uri(os.path.join(_INSTANCE_DIR, 'exam_system.db'))

    if db_backend == 'sqlite':
        if database_url:
            # 配了 PG 链接却强制跑 SQLite：就是离线机器的常规形态，计入离线模式
            _mark_offline('DB_BACKEND=sqlite 且项目配有 DATABASE_URL')
        return sqlite_uri

    if db_backend == 'postgres':
        if not database_url:
            raise RuntimeError(
                'DB_BACKEND=postgres 必须设置 DATABASE_URL，形如 '
                'postgresql+psycopg2://user:pass@host:5432/dbname')
        try:
            _probe_postgres(database_url)  # 连不上直接抛错，不静默降级
        except Exception as exc:
            raise RuntimeError(
                f'DB_BACKEND=postgres 但 PostgreSQL 连接失败：{_decode_server_message(exc)}；'
                f'目标 {redact_url(database_url)}') from exc
        return database_url

    # auto（默认）：视情降级
    if database_url:
        try:
            _probe_postgres(database_url)
            return database_url
        except Exception as e:
            reason = _decode_server_message(e)
            url = make_url(database_url)
            absent, detail = _pg_installed_on_this_machine(url.host or '127.0.0.1',
                                                           url.port or 5432)
            if not absent:
                # 本机确实有 PG，只是连不上：静默回落就是双库分叉，必须拒起
                raise RuntimeError(
                    f'DB_BACKEND=auto 但 PostgreSQL 连接失败：{reason}；'
                    f'目标 {redact_url(database_url)}。{detail}，'
                    '所以不能降级到 SQLite：写进去的新数据会留在本地、回不到 PG。'
                    '请先恢复 PG（启动服务 / 核对密码 / 确认库已建）；'
                    '确实要在无 PG 的机器上离线读，请把 DB_BACKEND 设为 sqlite。') from e
            ok, why = _mirror_readable(sqlite_uri)
            if not ok:
                raise RuntimeError(
                    f'DB_BACKEND=auto：{detail}，本该回落到项目内的 SQLite 镜像，'
                    f'但镜像不可用：{why}。请先在装有 PG 的机器上跑 '
                    f'`python scripts/mirror_pg_to_sqlite.py --resync` 生成最新镜像，'
                    f'再把整个项目目录拷过来。') from e
            _mark_offline(detail)
            logger.warning('[db] 本机无 PostgreSQL（%s），视情降级到项目内 SQLite 镜像'
                           '（离线交付模式，只读为主）：镜像=%s；原 PG 目标=%s；'
                           '本次连接原因=%s', detail, why, redact_url(database_url), reason)
    return sqlite_uri


def resolve_rate_limit_uri(host=None, port=None, db=None, password=None, explicit=None):
    """限流存储 URI 派生：显式 URI 优先 → 配了 Redis 跟随之 → 回落 memory://。

    缺省参数一律从环境变量取，与 Config 类体原口径逐位一致
    （tests/test_rate_limit_uri.py 四条断言锁死，改动前先看那个文件）。
    之所以抽成函数而不是写死在类体里：v7.6 便携 Redis 可能在运行期换端口
    （6379 被非 Redis 程序占用时避让到 6380），而 RATE_LIMIT_STORAGE_URI 是
    import 期一次算定的字符串，运行时改 Config.REDIS_PORT 并不会跟着变——
    限流会继续探一个没人监听的端口，然后静默回落 memory://，多进程计数被稀释
    却毫无察觉。故这里必须支持「按最终生效值重建」。
    """
    explicit = os.getenv('RATE_LIMIT_STORAGE_URI') if explicit is None else explicit
    if explicit:
        return explicit
    env_host = os.getenv('REDIS_HOST')
    env_port = os.getenv('REDIS_PORT')
    # 显式传参（运行期重建）等同于「配了 Redis」；否则沿用 env 判据
    if not (host or port or env_host or env_port):
        return 'memory://'
    host = host or env_host or 'localhost'
    port = port or env_port or '6379'
    db = os.getenv('REDIS_DB', '0') if db is None else db
    password = os.getenv('REDIS_PASSWORD', '') if password is None else password
    auth = (':' + quote_plus(password) + '@') if password else ''
    return 'redis://{}{}:{}/{}'.format(auth, host, port, db)


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
    # ── 双后端自动适配（v6.8）──
    # DB_BACKEND=auto/postgres/sqlite（默认 auto）；DATABASE_URL 为 PG 连接串。
    # 最终 URI 由 _resolve_database_uri() 依上述降级策略确定（模块加载时探活一次）。
    DB_BACKEND = os.getenv('DB_BACKEND', 'auto').lower()
    DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
    SQLALCHEMY_DATABASE_URI = _resolve_database_uri()
    # 依最终 URI 判定实际生效后端（供日志/healthz 与引擎选项分支使用）
    DB_ACTIVE_BACKEND = make_url(SQLALCHEMY_DATABASE_URI).get_backend_name()
    # 去密码展示串：供启动横幅/healthz 输出「现在到底连的是哪个库」，日志永不落密码
    DB_URL_SAFE = redact_url(SQLALCHEMY_DATABASE_URI)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 引擎选项按选定后端方言分支（口径见 resolve_engine_options）；
    # app.py 装配时还会用实际生效 URI 重算一次，防外部只改 URI 不改选项的错配。
    SQLALCHEMY_ENGINE_OPTIONS = resolve_engine_options(SQLALCHEMY_DATABASE_URI)
    # 数据库定时备份（utils.backup，由后台调度线程按日执行）：
    # 默认开启，每天最多一份，轮转保留最近 N 份（仅清理自动备份，不动手工 .bak_*）。
    DB_BACKUP_ENABLED = os.getenv('DB_BACKUP_ENABLED', 'true').lower() == 'true'
    DB_BACKUP_KEEP = int(os.getenv('DB_BACKUP_KEEP', '7'))

    # PG 主库 → SQLite 只读镜像实时同步（utils.sqlite_mirror，v7.4）：
    # 本机以 PG 为正式主库，但每次提交后把变更行同步回项目内 SQLite，使没有 PG 的
    # 机器（老师/教授自己的电脑）拷走项目目录就能读到最新数据。
    # 仅当主库真是 postgresql 时生效（主库为 SQLite 时自动失效，避免自我镜像写）。
    SQLITE_MIRROR_ENABLED = os.getenv('SQLITE_MIRROR_ENABLED', 'true').lower() == 'true'
    # 镜像目标文件：默认仍是 instance/exam_system.db，保证他人机器零配置可读
    SQLITE_MIRROR_DB = os.getenv(
        'SQLITE_MIRROR_DB', os.path.join(_INSTANCE_DIR, 'exam_system.db'))
    # 每日行数对账 + 差异表整表重刷（撑住实时链路遗留/绕过 ORM 的写）
    SQLITE_MIRROR_RECONCILE = os.getenv('SQLITE_MIRROR_RECONCILE', 'true').lower() == 'true'
    # 整库重刷前的旧镜像快照轮转份数（*.bak_pre_mirror_*，不动手工 .bak_*）
    SQLITE_MIRROR_BACKUP_KEEP = int(os.getenv('SQLITE_MIRROR_BACKUP_KEEP', '3'))

    # ── 离线交付模式（v7.5）──
    # 判定为「这台机器在用项目内 SQLite 镜像而非 PG」时为 True：
    # auto 档视情降级成功，或 sqlite 档 + 项目仍配有 DATABASE_URL（老师侧改一行后的常规形态）。
    # 这个标记是离线变更补丁的前提：启动时按它抓基线快照，回本机时只导出「基线→现在」的差异，
    # 否则区分不开「老师在离线机上改的」与「本机这段时间改的」（三方合并必须有基线）。
    DB_OFFLINE_MODE = bool(_OFFLINE_FALLBACK.get('mirror'))
    DB_OFFLINE_REASON = '; '.join(_OFFLINE_FALLBACK.get('reasons', []))
    # 基线快照与补丁文件目录（随项目目录走，方便拷来拷去）
    OFFLINE_PATCH_DIR = os.getenv(
        'OFFLINE_PATCH_DIR', os.path.join(_INSTANCE_DIR, 'offline'))
    # 离线模式下启动即抓基线（关掉则只依赖手工 scripts/offline_merge.py --export）
    OFFLINE_BASELINE_ON_START = os.getenv(
        'OFFLINE_BASELINE_ON_START', 'true').lower() == 'true'

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

    # ── v7.6 便携 Redis（像 tools/mingw64 那样随项目走）──
    # 发现顺序与 oj/adapters/_toolchain.py 一致：显式路径 → 项目内目录 → 系统 PATH。
    # 只做「本机没装 Redis 时把缓存跑起来」，不改变「Redis 是可丢依赖」的定性：
    # 找不到/拉不起来一律退回原有 fake / DB 穿透降级链，绝不因此拒绝启动服务。
    # 可写绝对路径，也可写能被 which 到的命令名；留空则直接走项目内目录探测。
    REDIS_SERVER_PATH = os.getenv('REDIS_SERVER_PATH', '')
    # 项目内便携 Redis 根目录：解压 Redis-8.x-Windows-x64-msys2.zip 后把
    # redis-server.exe 放到这里（根目录或 bin/ 子目录都能被发现）
    REDIS_PORTABLE_DIR = os.getenv(
        'REDIS_PORTABLE_DIR', os.path.join(APP_DIR, 'tools', 'redis'))
    # 便携实例的数据/日志/pid 目录（在 instance/ 下，已整目录 gitignore）
    REDIS_PORTABLE_DATA = os.getenv(
        'REDIS_PORTABLE_DATA', os.path.join(_INSTANCE_DIR, 'redis'))
    # 目标端口被非 Redis 程序占用时的避让端口（按序找空闲口，全占用则放弃拉起）
    REDIS_ALT_PORTS = [int(x) for x in os.getenv('REDIS_ALT_PORTS', '6380,6381,6382').split(',')
                       if x.strip().isdigit()]
    # 等便携实例就绪（RESP PING 通）的秒数，超时即杀掉进程并回落原降级链
    REDIS_START_TIMEOUT = int(os.getenv('REDIS_START_TIMEOUT', 10))
    # 关掉自动拉起（只做发现与复用）。CI/容器里想彻底禁进程时设 false
    REDIS_AUTO_START = os.getenv('REDIS_AUTO_START', 'true').lower() == 'true'

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
    RATE_LIMIT_STORAGE_URI = resolve_rate_limit_uri()
    # 派生时用户是否显式给过 URI：给了就以用户写的为准，便携 Redis 换端口也不回写
    RATE_LIMIT_URI_EXPLICIT = bool(os.getenv('RATE_LIMIT_STORAGE_URI'))
    RATE_LIMIT_DEFAULT = os.getenv('RATE_LIMIT_DEFAULT', '60 per minute')
    RATE_LIMIT_HEADERS_ENABLED = True

    # ── v6.6 代码笔记本（Notebook）kernel 执行后端 ──
    # 后端选择：
    #   auto       : 检测到 docker 则用容器隔离，否则降级子进程（防呆级）。默认。
    #   docker     : 强制容器隔离（需 Docker 主机 + 预装 numpy/pandas/matplotlib 的镜像），
    #                未装 docker 时自动降级 subprocess 并告警。
    #   subprocess : 强制本机子进程（-I 隔离解释器 + 最小 env + 临时 cwd + 静态危险模式拒绝）。
    #   ipython    : 真·Jupyter 消息协议 kernel（v7.0 阶段 6，需 pip install ipykernel），
    #                解锁完整魔法/!shell/display 生态；缺依赖时自动降级 subprocess 并告警。
    #                仅显式指定启用，auto 不自动升级（保持既有部署行为不变）。
    NOTEBOOK_BACKEND = os.getenv('NOTEBOOK_BACKEND', 'auto').lower()
    NOTEBOOK_DOCKER_IMAGE = os.getenv('NOTEBOOK_DOCKER_IMAGE', 'python:3.12-slim')
    # 单 cell 执行超时（秒），超时则强杀并重启 kernel（跨 cell 状态丢失）
    NOTEBOOK_KERNEL_TIMEOUT = float(os.getenv('NOTEBOOK_KERNEL_TIMEOUT', '30'))
    # kernel 会话空闲回收阈值（秒）
    NOTEBOOK_KERNEL_IDLE_TTL = float(os.getenv('NOTEBOOK_KERNEL_IDLE_TTL', '600'))
    # 单 notebook 最大 cell 数 / 单 cell 最大源码长度
    NOTEBOOK_MAX_CELLS = int(os.getenv('NOTEBOOK_MAX_CELLS', '200'))
    NOTEBOOK_MAX_SOURCE = int(os.getenv('NOTEBOOK_MAX_SOURCE', '20000'))

    # ── v6.9 阶段 2：C/C++ OJ 编译器发现（三级优先：显式配置 → 项目内 tools/mingw64/bin → 系统 PATH）
    #    留空即走自动发现；「随项目走」的便携工具链无需配置（自动命中项目内 tools/mingw64）。
    #    如需指定其它编译器，填绝对路径或可 which 的命令名（亦可经同名环境变量注入）。
    OJ_GCC_PATH = os.getenv('OJ_GCC_PATH', '')
    OJ_GPP_PATH = os.getenv('OJ_GPP_PATH', '')
    # v7.0 路线 A：x86-64 汇编（NASM）适配器 assembler 发现（同三级优先；linker 复用 gcc）
    OJ_NASM_PATH = os.getenv('OJ_NASM_PATH', '')

    # ── v7.2 路线 B：AVR 单片机（avr-gcc 交叉编译 + simavr 模拟运行）
    #    与 asm 同走三级发现（显式配置 → 项目内 tools/mingw64/bin → 系统 PATH）；
    #    avr-gcc/simavr 属外部交叉工具链，项目自带 MinGW 不含，需自行安装（如 Atmel/Arduino toolchain）。
    #    ⚠ 裸机固件无 stdin/stdout、无自然退出码，判题依赖「预置输入→跑周期→捕获 UART TX→判定 halt」
    #    harness 契约，本环境无工具链未能实机校准，故默认关；OJ_AVR_ENABLED=false 时 available()=False，
    #    一律回落 AI/人工评分（零误判）。维护者装好工具链并按 simavr 契约校准后，再显式置 true 开启。
    OJ_AVR_PATH = os.getenv('OJ_AVR_PATH', '')          # avr-gcc 可执行（三级发现）
    OJ_SIMAVR_PATH = os.getenv('OJ_SIMAVR_PATH', '')    # simavr 可执行（三级发现）
    OJ_AVR_MCU = os.getenv('OJ_AVR_MCU', 'atmega328p')  # 目标型号（-mmcu=）
    OJ_AVR_ENABLED = os.getenv('OJ_AVR_ENABLED', 'false').lower() in ('1', 'true', 'yes', 'on')

    # ── v7.0 阶段 3：OJ 异步评测队列（默认关：交卷链路保持同步判分既有行为）
    #    开启后交卷命中编程题（有用例且工具链就绪）时置 answer.oj_status=pending 立即返回，
    #    后台线程评测完成后回填 verdict/分数并重算 Result（与 ledger 正交）。
    OJ_ASYNC_GRADING = os.getenv('OJ_ASYNC_GRADING', 'false').lower() in ('1', 'true', 'yes', 'on')
    # 后台评测线程轮询间隔（秒）；被 wake 立即打断，仅兼做崩溃后 pending 重放兜底
    OJ_QUEUE_INTERVAL = float(os.getenv('OJ_QUEUE_INTERVAL', '5'))
