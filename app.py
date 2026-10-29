from flask import Flask, jsonify, request, send_from_directory, abort
from flask_cors import CORS
from flask_migrate import Migrate
from sqlalchemy.exc import IntegrityError
from config import Config
from database import db, bcrypt
from utils.timeutil import utcnow, aware_min
import html
import os
import sys
import threading

from utils.logger import logger, access_logger
from utils.redis_cache import init_redis
from utils.security import init_security, limiter
import utils.security as _security

# 全面接入 Vue3 SPA：禁用 Flask 静态目录与模板目录
app = Flask(__name__, static_folder=None, template_folder=None)
app.config.from_object(Config)
app.url_map.strict_slashes = False
# 全局请求体上限：Flask 在解析前拦截超大上传/请求（413），防止磁盘/内存被灌满
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
# CORS 白名单与 Socket.IO 统一来自 Config.CORS_ORIGINS（环境变量/开发预置/生产空）
CORS(app, supports_credentials=True, origins=Config.CORS_ORIGINS)

db.init_app(app)
migrate = Migrate(app, db)

# SQLite 并发优化（v4.0）：开启 WAL 日志模式——读不再阻塞单写者，
# 缓解后台调度线程/请求线程/SocketIO 线程三方并发时的 database is locked。
# 配合 connect_args timeout=30（busy_timeout）序列化写者竞争；
# synchronous=NORMAL 是 WAL 官方推荐搭配（崩溃不损库，仅断电极端情况可能丢最后一事务）。
from sqlalchemy import event as _sa_event
with app.app_context():
    @_sa_event.listens_for(db.engine, "connect")
    def _sqlite_wal_pragma(dbapi_conn, _record):
        _cur = dbapi_conn.cursor()
        try:
            _cur.execute("PRAGMA journal_mode=WAL")
            _cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            _cur.close()

init_redis()
try:
    init_security(app)
except Exception as _e:
    logger.warning(f"init_security 初始化失败: {_e}，继续启动")

bcrypt.init_app(app)

from api.auth_routes import api_auth_bp
from api.question_routes import api_question_bp
from api.course_routes import api_course_bp
from api.gradebook_routes import api_gradebook_bp
from api.major_routes import api_major_bp
from api.chapter_routes import api_chapter_bp
from api.ai_routes import api_ai_bp
from api.exam_routes import api_exam_bp
from api.student_routes import api_student_bp
from api.execution_routes import api_execution_bp
from api.result_routes import api_result_bp
from api.notification_routes import api_notification_bp
from api.log_routes import api_log_bp
from api.learning_routes import api_learning_bp
from competition.routes import competition_bp
from competition.play_routes import competition_play_bp
from competition.pk_routes import pk_bp
from competition.gamification_routes import gamification_bp
from competition.team_routes import team_bp
from bounty.routes import bounty_bp
from dsci.routes import dsci_bp
from homework.routes import homework_bp
# 注意：api/routes.py 已废弃，路由已拆分到以上独立模块

api_bps = [api_auth_bp,
           api_question_bp,
           api_course_bp,
           api_gradebook_bp,
           api_major_bp,
           api_chapter_bp,
           api_ai_bp,
           api_exam_bp,
           api_student_bp,
           api_execution_bp,
           api_result_bp,
           api_notification_bp,
           api_log_bp,
           api_learning_bp,
           competition_bp,
           competition_play_bp,
           pk_bp,
           gamification_bp,
           team_bp,
           bounty_bp,
           dsci_bp,
           homework_bp]
for bp in api_bps:
    # CSRF 由 security._smart_csrf_check 统一处理：Bearer token 请求自动豁免，其余强制校验
    app.register_blueprint(bp, url_prefix='/api')

# ── Socket.IO（可选加载：未安装 flask-socketio 时自动降级为轮询）──
socketio = None
try:
    from flask_socketio import SocketIO
    from competition.socket_events import register_socket_events
    from competition.realtime import init_realtime
    socketio = SocketIO(app, cors_allowed_origins=Config.CORS_ORIGINS, async_mode='threading')
    register_socket_events(socketio)
    init_realtime(socketio)
    print('[SocketIO] 实时推送已启用')
except ImportError:
    print('[SocketIO] 未安装 flask-socketio，实时推送降级为前端轮询')

# 全局通知实时推送：注册 Notification 的 ORM 事件（commit 后自动推送到个人房间，
# 覆盖五大模块所有通知产生点；无 Socket.IO 时 notify_user 静默降级为轮询）。
import utils.notify_socket  # noqa: E402  (导入即注册 @event.listens_for 监听)

def _wants_json():
    """API 路径或纯 JSON 协商请求返回 JSON 错误；其余（浏览器页面）返回错误页"""
    if request.path.startswith('/api/'):
        return True
    accept = request.headers.get('Accept', '')
    return 'application/json' in accept and 'text/html' not in accept

# 纯静态错误页（占位符字符串替换，不经过模板引擎）
_ERROR_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>__CODE__ - 智汇学场</title>
    <style>
        body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
               background: #f3f4f6; min-height: 100vh; margin: 0;
               display: flex; align-items: center; justify-content: center; }
        .error-card { background: #fff; border-radius: 16px; padding: 3rem 4rem;
                      box-shadow: 0 10px 40px rgba(0,0,0,0.08); text-align: center; }
        .error-code { font-size: 4rem; font-weight: 700; color: #667eea; margin: 0; }
        .error-title { font-size: 1.25rem; color: #1f2937; margin: 0.5rem 0 1rem; }
        .error-msg { color: #6b7280; margin: 0 0 2rem; }
        .error-btn { display: inline-block; padding: 0.6rem 1.6rem; border-radius: 8px;
                     background: #667eea; color: #fff; text-decoration: none; }
        .error-btn:hover { background: #5a6fd6; }
    </style>
</head>
<body>
    <div class="error-card">
        <p class="error-code">__CODE__</p>
        <p class="error-title">__TITLE__</p>
        <p class="error-msg">__MESSAGE__</p>
        <a class="error-btn" href="/">返回首页</a>
    </div>
</body>
</html>"""

def _static_error_page(code, title, message):
    return _ERROR_PAGE_HTML \
        .replace('__CODE__', html.escape(str(code))) \
        .replace('__TITLE__', html.escape(str(title))) \
        .replace('__MESSAGE__', html.escape(str(message))), code

def _error_response(code, title, message):
    if _wants_json():
        return jsonify({"message": message}), code
    return _static_error_page(code, title, message)


@app.route('/healthz', methods=['GET'])
def healthz():
    """轻量健康检查端点（K8s / 负载均衡 / 运维探针通用）。

    仅返回关键依赖的可达性状态，不查库（数据库 ping 由更深层探针处理）：
    - ok          : 服务整体健康，可接受流量
    - db_ok       : SQLAlchemy engine 能执行 SELECT 1
    - redis       : 缓存层连接状态（None=未配置，True=可达，False=不可达）
    - socketio    : 实时推送是否已启用
    - scheduler   : 后台调度线程是否存活
    - spa_hosting : 前端托管开关
    - app_dir     : 应用根目录（方便 frozen/开发模式对比）
    """
    import threading as _threading

    # DB 轻量探针：SELECT 1，不触发 ORM session 初始化
    db_ok = True
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text('SELECT 1'))
    except Exception as e:
        db_ok = False

    # 缓存后端类型（None=完全未启用，'real'=真实 Redis 服务，'fake'=Fakeredis）
    # 不再只给布尔值，生产部署时能一眼看出是哪种后端
    try:
        from utils.redis_cache import current_backend
        redis_status = current_backend()   # None / 'real' / 'fake'
    except Exception:
        redis_status = None

    # scheduler 线程
    try:
        from utils.scheduler import _thread as _sched_thread
        scheduler_alive = bool(_sched_thread and _sched_thread.is_alive())
    except Exception:
        scheduler_alive = False

    # Socket.IO
    socketio_alive = socketio is not None

    payload = {
        'ok': db_ok,                       # 以 DB 可达性为准的核心健康
        'db_ok': db_ok,
        'redis': redis_status,             # None=未配置
        'socketio': socketio_alive,
        'scheduler': scheduler_alive,
        'spa_hosting': Config.ENABLE_SPA_HOSTING,
        'app_dir': Config.APP_DIR,
        'frozen': getattr(sys, 'frozen', False),
    }
    status_code = 200 if db_ok else 503
    return jsonify(payload), status_code


def _is_browser_route(path):
    """浏览器前端路由：GET 且最后一段无文件后缀，且不属于后端保留前缀"""
    if request.method != 'GET':
        return False
    if path.startswith(('/api/', '/socket.io', '/uploads/')):
        return False
    return '.' not in path.rsplit('/', 1)[-1]

@app.errorhandler(400)
def bad_request(error):
    logger.warning(f"400 Bad Request: {request.url} - {request.data}")
    return _error_response(400, "请求参数错误", "请求参数有误，请检查后重试")

@app.errorhandler(401)
def unauthorized(error):
    logger.warning(f"401 Unauthorized: {request.url} - IP: {request.remote_addr}")
    return _error_response(401, "未授权访问", "请先登录后再访问该页面")

@app.errorhandler(403)
def forbidden(error):
    logger.warning(f"403 Forbidden: {request.url} - User: {_request_user_label()}")
    return _error_response(403, "禁止访问", "您没有权限访问该资源")

@app.errorhandler(404)
def not_found(error):
    logger.warning(f"404 Not Found: {request.url}")
    if _wants_json():
        return jsonify({"message": "资源不存在"}), 404
    # 深层前端路由被刷新/直接访问：回退 index.html，由 vue-router 接管
    if _is_browser_route(request.path):
        return _spa_index_response()
    return _static_error_page(404, "页面不存在", "您访问的资源不存在或已被移除")

@app.errorhandler(405)
def method_not_allowed(error):
    logger.warning(f"405 Method Not Allowed: {request.method} {request.url}")
    return _error_response(405, "方法不允许", "请求方法有误")

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 Internal Error: {request.url}", exc_info=True)
    db.session.rollback()
    return _error_response(500, "服务器内部错误", "服务器开小差了，请稍后重试")

# 高频/自激请求不记访问日志：
# - /api/logs* 前端日志上报，写访问日志会形成“上报→记录→再上报”的自激循环
# - /socket.io Socket.IO 轮询/握手，请求频率极高
# - /api/csrf-token 前端高频获取
# - SPA 静态资源（js/css/图片/字体等）
_LOG_SILENT_PREFIXES = ('/healthz', '/api/logs', '/socket.io', '/api/csrf-token', '/assets/')
_LOG_SILENT_SUFFIXES = ('.js', '.css', '.ico', '.png', '.jpg', '.jpeg', '.gif',
                        '.svg', '.woff', '.woff2', '.ttf', '.eot', '.map')


def _request_user_label():
    """访问审计用户标识：从 Bearer JWT 读取 user_id（仅验签解码，不查库）；
    无 token 或非法 token 记为 Anonymous / invalid-token"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        try:
            import jwt
            payload = jwt.decode(auth_header.split(' ', 1)[1],
                                 app.config['SECRET_KEY'], algorithms=['HS256'])
            return f"user:{payload.get('user_id')}"
        except Exception:
            return 'invalid-token'
    return 'Anonymous'


@app.before_request
def log_request_info():
    path = request.path or ''
    if path.startswith(_LOG_SILENT_PREFIXES):
        return
    if path.rsplit('.', 1)[-1].lower() in _LOG_SILENT_SUFFIXES:
        return
    access_logger.info(f"{request.method} {request.url} - IP: {request.remote_addr} - User: {_request_user_label()}")


def auto_end_expired_exams():
    """自动结束已过截止时间的考试，并正确批改已作答的客观题。
    由 utils.scheduler 后台线程周期调用，不再挂在 before_request 上。
    """
    now = utcnow()
    from database.models import Exam, ExamSession, ExamStatusEnum, Answer, ExamQuestion, Result, Question, QuestionTypeEnum
    from sqlalchemy import exc as sa_exc
    from api.exam_engine import check_objective, session_question_ids, apply_exam_result
    try:
        expired_exams = Exam.query.filter(
            Exam.status == ExamStatusEnum.PUBLISHED,
            Exam.end_time < now
        ).all()

        if expired_exams:
            logger.info(f"Found {len(expired_exams)} expired exams to process")

        # 每个考试独立事务：避免单大事务长时间持有 SQLite 写锁阻塞学生交卷，
        # 也避免单个考试处理失败导致整批回滚、每轮重复失败
        for exam in expired_exams:
            try:
                logger.info(f"Auto ending exam: {exam.id} - {exam.title}")
                exam.status = ExamStatusEnum.ENDED
                in_progress_sessions = ExamSession.query.filter_by(
                    exam_id=exam.id, status='in_progress'
                ).all()

                # 批量预载本场考试的题目配置与题目实体，消除逐答案 N+1 查询
                eqs = ExamQuestion.query.filter_by(exam_id=exam.id).all()
                score_map = {eq.question_id: eq.score for eq in eqs}
                q_ids = list(score_map.keys())
                questions = {
                    q.id: q
                    for q in Question.query.filter(Question.id.in_(q_ids)).all()
                } if q_ids else {}
                rule = exam.multi_score_rule or 'all_or_nothing'

                for sess in in_progress_sessions:
                    sess.end_time = now
                    sess.status = 'submitted'
                    # v4.3：按会话题单收卷（含逐人随机卷），未答题补记 0 分空行
                    paper_ids = [qid for qid in session_question_ids(sess, exam) if qid in score_map]
                    answers = {a.question_id: a for a in Answer.query.filter_by(session_id=sess.id).all()}
                    earned = 0.0
                    total = 0.0
                    for qid in paper_ids:
                        eq_score = score_map.get(qid)
                        if eq_score is None:
                            continue
                        total += eq_score
                        question = questions.get(qid)
                        a = answers.get(qid)
                        if a is None:
                            a = Answer(session_id=sess.id, question_id=qid, student_answer='')
                            db.session.add(a)
                        if not question:
                            continue
                        if a.is_correct is None and a.manual_score is None:
                            student_ans = (a.student_answer or '').strip()
                            if QuestionTypeEnum.is_subjective(question.type):
                                if student_ans:
                                    a.needs_manual_grade = True
                                a.is_correct = False
                                a.score = 0
                            else:
                                ok, ratio = check_objective(question.type, student_ans,
                                                            (question.answer or '').strip(), rule)
                                a.is_correct = ok
                                a.score = round(eq_score * ratio, 2)
                        earned += (a.manual_score if a.manual_score is not None else (a.score or 0))
                    sess.score = earned
                    # best/last 成绩策略幂等 upsert（v4.3 多次作答；旧版已有成绩即跳过）
                    result, created, changed = apply_exam_result(sess, earned, total)
                    # flush 提前暴露唯一约束冲突（并发交卷竞态），冲突则整场回滚下轮重试
                    db.session.flush()
                    # 成绩未发布时不发含分通知，留待教师统一发布（v4.3）
                    if (created or changed) and exam.results_published:
                        from api.notification_routes import create_exam_result_notification
                        # 循环内不逐行 commit：通知随本场考试在循环结束后统一提交，
                        # 避免反复争抢 SQLite 写锁，也保证整场考试收卷的事务原子性
                        create_exam_result_notification(result, commit=False)

                db.session.commit()
                logger.info(f"Auto ended exam: {exam.id}")
            except sa_exc.IntegrityError:
                db.session.rollback()
                logger.warning(f"考试 {exam.id} 自动收卷时遇并发冲突（成绩已存在），已回滚，下轮重试")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error auto-ending exam {exam.id}: {str(e)}", exc_info=True)
    except Exception as e:
        logger.error(f"Error auto-ending expired exams: {str(e)}", exc_info=True)
        db.session.rollback()

# ── Vue3 SPA 托管（frontend/dist 构建产物）─────────────────────────────
# 开发时页面由 Vite(5173) 提供并代理 /api 到本服务；生产/单文件部署时 Flask 直接
# 托管 dist：/assets/* 为带哈希的长缓存资源，其余 GET 浏览器路径统一回退
# index.html，由 vue-router 接管（支持深层路由刷新/分享链接直达）。
#
# 启用条件：Config.ENABLE_SPA_HOSTING = true（默认）
#   - 前端独立部署到 CDN/Nginx 时设为 false，不注册 SPA 路由
#
# dist 目录解析顺序（FRONTEND_DIST 最终值）：
#   1. Config.FRONTEND_DIST 显式覆盖（环境变量）
#   2. frozen 模式：_MEIPASS/frontend/dist 或 APP_DIR/frontend/dist
#   3. 开发模式：__file__ 所在目录的 frontend/dist
if Config.ENABLE_SPA_HOSTING:
    if Config.FRONTEND_DIST:
        # 环境变量显式指定了 dist 路径
        FRONTEND_DIST = Config.FRONTEND_DIST
    elif getattr(sys, 'frozen', False):
        _bundle_candidates = [
            os.path.join(getattr(sys, '_MEIPASS', ''), 'frontend', 'dist'),
            os.path.join(Config.APP_DIR, 'frontend', 'dist'),
        ]
        # 找到第一个含 index.html 的候选；都没有就用 _MEIPASS 里的那个（会走到"前端未构建"占位）
        FRONTEND_DIST = next((p for p in _bundle_candidates if os.path.isfile(os.path.join(p, 'index.html'))),
                             _bundle_candidates[0])
    else:
        FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend', 'dist')

    _SPA_MISSING_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>前端未构建</title>
<style>body{font-family:"Microsoft YaHei",sans-serif;background:#f3f4f6;display:flex;
min-height:100vh;align-items:center;justify-content:center;margin:0}
.card{background:#fff;border-radius:16px;padding:3rem 4rem;text-align:center;
box-shadow:0 10px 40px rgba(0,0,0,.08)}code{background:#f3f4f6;padding:2px 6px;border-radius:4px}</style>
</head>
<body><div class="card"><h2>前端页面尚未构建</h2>
<p>开发模式请运行 <code>npm run dev</code> 访问 Vite 开发服务器（默认 5173 端口）；</p>
<p>生产部署请在 <code>frontend</code> 目录执行 <code>npm run build</code> 生成 dist 后重启服务。</p>
<p>若前端已独立部署（CDN/Nginx），请在 .env 中设 <code>ENABLE_SPA_HOSTING=false</code>。</p>
</div></body></html>"""

    def _spa_index_response():
        index_path = os.path.join(FRONTEND_DIST, 'index.html')
        if os.path.isfile(index_path):
            resp = send_from_directory(FRONTEND_DIST, 'index.html')
            # 入口文档禁止长缓存，确保发版后立即拿到最新哈希资源引用
            resp.headers['Cache-Control'] = 'no-cache'
            return resp
        return _SPA_MISSING_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

    @app.route('/assets/<path:filename>')
    def spa_assets(filename):
        resp = send_from_directory(os.path.join(FRONTEND_DIST, 'assets'), filename)
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return resp

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def spa_entry(path):
        # 后端保留前缀未被各自路由匹配时，不做 SPA 回退
        if path.startswith(('api/', 'socket.io', 'uploads/')):
            abort(404)
        # 带文件后缀的路径不属于前端路由（如 favicon.ico），不回退
        if '.' in path.rsplit('/', 1)[-1]:
            abort(404)
        return _spa_index_response()
else:
    # SPA 托管关闭：定义空的 FRONTEND_DIST 供其他模块引用（避免 ImportError）
    FRONTEND_DIST = None

# 用户可写资源根目录（frozen = exe 所在目录；dev = 项目根）
# uploads/ 存放用户上传的图片/视频附件；与 instance/ 一样必须落在 APP_DIR 下
# （PyInstaller _MEIPASS 只读且进程退出即清理，绝不能用作上传目录）
UPLOAD_FOLDER = os.path.join(Config.APP_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    # 文件名均为服务端生成的 UUID（不可枚举），且扩展白名单仅限图片/视频；
    # 加 nosniff 防止浏览器将文件嗅探为可执行/HTML 内容
    resp = send_from_directory(UPLOAD_FOLDER, filename)
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    return resp

def init_database():
    with app.app_context():
        # 全新库：建表；已有库：create_all 幂等（不重建已存在表）
        db.create_all()

        # 表结构变更统一由 Alembic 迁移管理（0001 基线 / 0002 时区 / 0003 结构补全+约束）
        from flask_migrate import upgrade
        upgrade()
        print('[DB] Alembic 迁移已执行至最新版本')

        # 幂等确保快速 PK 训练机器人账号存在（已有库也会补种）
        try:
            from database.init_data import ensure_bot_user
            ensure_bot_user()
        except Exception as e:
            db.session.rollback()
            print(f'[DB] 机器人账号初始化失败: {e}')

        # 幂等数据修正（不影响结构，可重复执行）
        try:
            from database.models import Question
            fixed = 0
            for q in Question.query.all():
                changed = False
                if q.type and q.type != q.type.lower():
                    q.type = q.type.lower()
                    changed = True
                if q.difficulty and q.difficulty != q.difficulty.lower():
                    q.difficulty = q.difficulty.lower()
                    changed = True
                if changed:
                    fixed += 1
            if fixed > 0:
                db.session.commit()
                print(f'[DB] 已修正 {fixed} 道题目的题型/难度值为小写')
        except Exception:
            db.session.rollback()

        course_credit_mapping = {
            '计算机导论': 2.0, '人工智能导论': 2.0, '程序设计基础': 3.0,
            'Python编程': 3.0, 'C语言程序设计': 3.0, 'C++程序设计': 3.0,
            'Java程序设计': 3.0, '数据结构': 4.0, '算法设计': 4.0,
            '算法分析': 3.0, '操作系统': 4.0, '计算机组成原理': 4.0,
            '计算机体系结构': 3.0, '数据库原理': 4.0, '数据库系统': 3.0,
            '软件工程': 3.0, '软件测试': 2.0, '软件测试技术': 2.0,
            '计算机网络': 4.0, '信息安全': 3.0, '网络安全': 3.0,
            '人工智能': 3.0, '机器学习': 4.0, '深度学习': 3.0,
            '数据挖掘': 3.0, '大数据技术': 3.0, '云计算': 3.0,
            '物联网': 3.0, '前端开发': 3.0, '后端开发': 3.0,
            '移动开发': 3.0, '离散数学': 3.0, '数字逻辑': 3.0,
            '编译原理': 3.0, '电路原理': 4.0, '模拟电子技术': 4.0,
            '数字电子技术': 4.0, '信号与系统': 4.0, '数字信号处理': 4.0,
            '通信原理': 4.0, '电磁场理论': 4.0, '集成电路设计': 4.0,
            '电机学': 4.0, '电力系统分析': 4.0, '自动控制原理': 4.0,
            '工程制图': 3.0, '机械原理': 4.0, '机械设计': 4.0,
            '材料力学': 4.0, '理论力学': 4.0, '结构力学': 4.0,
            '土力学': 3.0, '混凝土结构': 4.0, '无机化学': 4.0,
            '有机化学': 4.0, '分析化学': 4.0, '物理化学': 4.0,
            '化工原理': 4.0, '高等数学': 6.0, '线性代数': 3.0,
            '概率论与数理统计': 3.0, '大学物理': 4.0, '量子力学': 4.0,
            '生物化学': 4.0, '微观经济学': 3.0, '宏观经济学': 3.0,
            '管理学原理': 3.0, '会计学': 3.0, '金融学': 3.0,
            '统计学': 3.0, '运筹学': 3.0, '法理学': 3.0,
            '民法学': 4.0, '刑法学': 4.0, '大学英语': 4.0,
            '体育': 1.0, '光纤通信': 3.0, '微波技术': 3.0,
            '数字通信': 3.0, '移动通信': 3.0, '设计模式': 2.0,
            '软件工程导论': 2.0, '软件架构': 3.0, '需求工程': 2.0,
        }

        def get_course_credit(course_name):
            if course_name in course_credit_mapping:
                return course_credit_mapping[course_name]
            for key, credit in course_credit_mapping.items():
                if key in course_name or course_name in key:
                    return credit
            return 3.0

        try:
            from database.models import Course
            from sqlalchemy import or_
            # 同样 SQL 端过滤：只处理学分未设置（NULL/0）的课程
            pending_courses = Course.query.filter(
                or_(Course.credit.is_(None), Course.credit == 0)
            ).all()
            for course in pending_courses:
                course.credit = get_course_credit(course.name)
            if pending_courses:
                db.session.commit()
                print(f'[DB] 已为 {len(pending_courses)} 门课程自动设置学分')
        except Exception as e:
            db.session.rollback()
            print(f'[DB] 设置课程学分时出错: {e}')

# ── 启动装配（幂等）：建库/迁移 + 后台调度线程 ─────────────────────────────
# 原仅随 `python app.py`（__main__）执行；若改用 `flask run`、gunicorn/waitress 以
# app:app 方式导入启动，调度器会静默不启动（过期收卷/竞赛结算/悬赏过期全部失效）。
# 现收敛为幂等的 bootstrap_app()，并由 before_request 钩子对任意入口兜底：
# 第一个请求到达时若尚未装配则补装配（多进程部署时每进程各装配一次，
# init_database 与调度任务均已幂等，重复执行安全）。
_boot_lock = threading.Lock()
_boot_done = threading.Event()


def bootstrap_app():
    """幂等启动装配：init_database + 调度线程；失败不置位，下个请求重试。"""
    if _boot_done.is_set():
        return
    with _boot_lock:
        if _boot_done.is_set():
            return
        init_database()
        from utils.scheduler import start_scheduler
        start_scheduler(app, interval=60)
        _boot_done.set()


@app.before_request
def _bootstrap_once():
    if not _boot_done.is_set():
        bootstrap_app()


if __name__ == '__main__':
    # 启动即装配（提前暴露建库/迁移错误，不等首请求）；before_request 钩子后续为无操作
    bootstrap_app()
    host = app.config['HOST']
    port = app.config['PORT']

    # ── SPA 托管状态打印 ──
    if Config.ENABLE_SPA_HOSTING:
        if FRONTEND_DIST and os.path.isfile(os.path.join(FRONTEND_DIST, 'index.html')):
            print(f'[SPA] Vue3 构建产物托管于: {FRONTEND_DIST}')
        else:
            dist_info = FRONTEND_DIST or '(未配置)'
            print(f'[SPA] 托管已启用但未发现前端构建产物 ({dist_info})：'
                  f'开发请用 Vite(5173)，生产请先在 frontend 目录执行 npm run build；'
                  f'若前端已独立部署，可在 .env 中设 ENABLE_SPA_HOSTING=false')
    else:
        print('[SPA] 前端托管已关闭（ENABLE_SPA_HOSTING=false），请确保前端从 Nginx/CDN 独立提供')

    if app.config['DEBUG']:
        # 开发模式：Werkzeug 开发服务器（threading 模式下 Socket.IO 经 simple-websocket 支持 WebSocket）
        if socketio:
            socketio.run(app, host=host, port=port, debug=True,
                         use_reloader=False, allow_unsafe_werkzeug=True)
        else:
            app.run(host=host, port=port, debug=True, use_reloader=False)
    else:
        # 生产模式：waitress 生产级 WSGI 服务器（纯 Python，Windows/Linux 通用）。
        # Flask-SocketIO 已在 init_app 时将 Socket.IO 中间件挂入 app.wsgi_app，
        # 直接 serve(app) 即可；Socket.IO 以 HTTP 长轮询工作（waitress 不支持
        # WebSocket 升级，客户端自动回退轮询；如需原生 WebSocket 请在 Linux 上
        # 用 gunicorn + eventlet/gevent worker）。
        try:
            from waitress import serve
        except ImportError:
            raise RuntimeError('生产模式需要 waitress，请先执行: pip install waitress')
        print(f'[生产] waitress WSGI 服务器启动: http://{host}:{port}'
              f'（Socket.IO 长轮询模式；调试器已关闭）')
        serve(app, host=host, port=port, threads=16, channel_timeout=120)