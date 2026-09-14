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

init_redis()
try:
    init_security(app)
except Exception as _e:
    logger.warning(f"init_security 初始化失败: {_e}，继续启动")

bcrypt.init_app(app)

from api.auth_routes import api_auth_bp
from api.question_routes import api_question_bp
from api.course_routes import api_course_bp
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
# 注意：api/routes.py 已废弃，路由已拆分到以上独立模块

api_bps = [api_auth_bp, api_question_bp, api_course_bp, api_major_bp, api_chapter_bp, api_ai_bp, api_exam_bp, api_student_bp, api_execution_bp, api_result_bp, api_notification_bp, api_log_bp, api_learning_bp, competition_bp, competition_play_bp, pk_bp, gamification_bp, team_bp, bounty_bp]
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
_LOG_SILENT_PREFIXES = ('/api/logs', '/socket.io', '/api/csrf-token', '/assets/')
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
    OBJECTIVE_TYPES = {'single_choice', 'multiple_choice', 'true_false', 'fill_blank'}
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

                for sess in in_progress_sessions:
                    sess.end_time = now
                    sess.status = 'submitted'
                    existing_result = Result.query.filter_by(
                        exam_id=exam.id, student_id=sess.student_id
                    ).first()
                    if existing_result:
                        continue
                    answers = Answer.query.filter_by(session_id=sess.id).all()
                    earned = 0
                    total = 0
                    for a in answers:
                        eq_score = score_map.get(a.question_id)
                        if eq_score is None:
                            continue
                        total += eq_score
                        question = questions.get(a.question_id)
                        if not question:
                            continue
                        if a.is_correct is None:
                            student_ans = (a.student_answer or '').strip()
                            correct_ans = (question.answer or '').strip()
                            if question.type in OBJECTIVE_TYPES:
                                if question.type == 'multiple_choice':
                                    is_correct = ''.join(sorted(student_ans.upper())) == ''.join(sorted(correct_ans.upper()))
                                elif question.type == 'fill_blank':
                                    is_correct = student_ans.lower() == correct_ans.lower()
                                else:
                                    is_correct = student_ans.upper() == correct_ans.upper()
                            else:
                                is_correct = False
                                a.needs_manual_grade = True
                            a.is_correct = is_correct
                            a.score = eq_score if is_correct else 0
                        earned += (a.score or 0)
                    result = Result(
                        exam_id=exam.id,
                        student_id=sess.student_id,
                        score=earned,
                        total_score=total,
                        submitted_at=now
                    )
                    db.session.add(result)
                    # flush 提前暴露唯一约束冲突（并发交卷竞态），冲突则整场回滚下轮重试
                    db.session.flush()
                    from api.notification_routes import create_exam_result_notification
                    create_exam_result_notification(result)

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
if getattr(sys, 'frozen', False):
    _BUNDLE_ROOT = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
    _BUNDLE_ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIST = os.path.join(_BUNDLE_ROOT, 'frontend', 'dist')

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

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
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

if __name__ == '__main__':
    init_database()
    # 启动后台定时调度线程（过期考试结束、竞赛结算、赛季归档）
    from utils.scheduler import start_scheduler
    start_scheduler(app, interval=60)
    host = app.config['HOST']
    port = app.config['PORT']

    if os.path.isfile(os.path.join(FRONTEND_DIST, 'index.html')):
        print(f'[SPA] Vue3 构建产物托管于: {FRONTEND_DIST}')
    else:
        print(f'[SPA] 未发现 {FRONTEND_DIST}\\index.html：'
              f'开发请用 Vite(5173)，生产请先在 frontend 目录执行 npm run build')

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