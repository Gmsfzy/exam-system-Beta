"""Redis 缓存层 —— 分层降级设计。

四种运行时状态（healthz 会暴露）：
  +----------+-------------------+----------------------------------------+
  | redis 值 | 后端              | 说明                                   |
  +----------+-------------------+----------------------------------------+
  | "real"   | 真实 Redis 服务   | Memurai / 原生 Redis；支持持久化、集群 |
  | "fake"   | Fakeredis         | pip install fakeredis；纯 Python 内存 |
  | false    | 不可达/连接失败   | 之前真实 Redis 断了，当前 fakeredis 也没装 |
  | None     | 后端未配置        | REDIS_BACKEND=disabled 或全部探测失败 |
  +----------+-------------------+----------------------------------------+

初始化链路（Config.REDIS_BACKEND 控制）：
  auto       → 真实 Redis → Fakeredis → 全穿透 DB
  real       → 真实 Redis 连不上则告警 + 全穿透 DB
  fakeredis  → 强制 Fakeredis，没装则全穿透 DB
  disabled   → 直接全穿透 DB

所有业务函数（get_cache / set_cache / delete_pattern / @cached）内部都先调
is_redis_available() 做了 None 守卫，后端切换对调用方完全透明。
"""
import json
import functools
import logging
from config import Config

logger = logging.getLogger(__name__)

# redis_client 可能是 redis.Redis 或 fakeredis.FakeRedis，API 完全兼容
redis_client = None
# 当前后端类型：'real' / 'fake' / None（未启用）
_current_backend = None


def _try_real_redis():
    """尝试连接真实 Redis 服务（Memurai / 原生 Redis）。"""
    import redis as _redis
    try:
        if Config.REDIS_PASSWORD:
            client = _redis.Redis(
                host=Config.REDIS_HOST, port=Config.REDIS_PORT,
                password=Config.REDIS_PASSWORD, db=Config.REDIS_DB,
                socket_timeout=Config.REDIS_TIMEOUT, decode_responses=True,
            )
        else:
            client = _redis.Redis(
                host=Config.REDIS_HOST, port=Config.REDIS_PORT,
                db=Config.REDIS_DB, socket_timeout=Config.REDIS_TIMEOUT,
                decode_responses=True,
            )
        client.ping()
        return client
    except Exception as e:
        logger.debug(f"真实 Redis 连接失败: {e}")
        return None


def _try_fakeredis():
    """尝试加载 Fakeredis（纯 Python，pip 装即用，无服务进程）。"""
    try:
        from fakeredis import FakeRedis
        client = FakeRedis(decode_responses=True)
        client.ping()  # fakeredis 本身不会失败，ping 只是证明对象活着
        return client
    except ImportError:
        logger.debug("Fakeredis 未安装（pip install fakeredis 可启用）")
        return None
    except Exception as e:
        logger.debug(f"Fakeredis 初始化失败: {e}")
        return None


def init_redis():
    """按 Config.REDIS_BACKEND 选择缓存后端，分层降级。

    返回值：True = 有缓存后端（真实或 fake），False = 全穿透 DB。
    """
    global redis_client, _current_backend

    mode = Config.REDIS_BACKEND
    redis_client = None
    _current_backend = None

    if mode == 'disabled':
        logger.info("[缓存] REDIS_BACKEND=disabled，完全关闭缓存（所有 @cached 直接穿透 DB）")
        return False

    if mode == 'real':
        client = _try_real_redis()
        if client:
            redis_client, _current_backend = client, 'real'
            logger.info(f"[缓存] 真实 Redis 连接成功: {Config.REDIS_HOST}:{Config.REDIS_PORT}/db{Config.REDIS_DB}")
            return True
        logger.warning("[缓存] REDIS_BACKEND=real 但真实 Redis 连不通 → 全穿透 DB。"
                       "请检查 Memurai/Redis 服务是否启动、端口是否放通。")
        return False

    if mode == 'fakeredis':
        client = _try_fakeredis()
        if client:
            redis_client, _current_backend = client, 'fake'
            logger.info("[缓存] Fakeredis 已启用（纯 Python 内存缓存，无服务进程）")
            return True
        logger.warning("[缓存] REDIS_BACKEND=fakeredis 但 fakeredis 未安装 → 全穿透 DB。"
                       "请 pip install fakeredis")
        return False

    # mode == 'auto'（默认）：先真实 → 再 fake → 最后 DB 穿透
    client = _try_real_redis()
    if client:
        redis_client, _current_backend = client, 'real'
        logger.info(f"[缓存] 真实 Redis 连接成功: {Config.REDIS_HOST}:{Config.REDIS_PORT}/db{Config.REDIS_DB}")
        return True

    client = _try_fakeredis()
    if client:
        redis_client, _current_backend = client, 'fake'
        logger.info("[缓存] 真实 Redis 不可达，已自动切换到 Fakeredis（纯 Python 内存缓存）。"
                    "生产环境建议安装 Memurai/Redis 以获得持久化和高可用。")
        return True

    logger.warning("[缓存] 真实 Redis 不可达，Fakeredis 也未安装 → 全穿透 DB。"
                   "生产环境建议安装 Memurai（Windows 下的 Redis 服务）；"
                   "开发环境可 pip install fakeredis 获得零依赖缓存。")
    return False


def get_redis():
    return redis_client


def is_redis_available():
    return redis_client is not None


def current_backend():
    """返回当前缓存后端类型字符串，供 /healthz 使用：
    'real' | 'fake' | None"""
    return _current_backend


def cache_key(prefix, *args):
    parts = [str(a) for a in args if a is not None]
    return f"{prefix}:{':'.join(parts)}" if parts else prefix


def get_cache(key):
    if not is_redis_available():
        return None
    try:
        value = redis_client.get(key)
        if value:
            return json.loads(value)
        return None
    except Exception:
        return None


def set_cache(key, value, expires=300):
    if not is_redis_available():
        return
    try:
        redis_client.setex(key, expires, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass


def delete_cache(key):
    if not is_redis_available():
        return
    try:
        redis_client.delete(key)
    except Exception:
        pass


def delete_pattern(pattern):
    """按模式批量删缓存键。

    真实 Redis 上用 scan_iter（增量迭代，不阻塞 O(N)），
    Fakeredis 上 fakeredis 的 scan_iter 实现同样走迭代器协议，无需特殊分支。
    """
    if not is_redis_available():
        return
    try:
        for key in redis_client.scan_iter(match=pattern, count=500):
            try:
                redis_client.delete(key)
            except Exception:
                pass
    except Exception:
        # 兜底：scan_iter 失败（旧版 fakeredis 可能没实现）时降级 keys()
        try:
            keys = redis_client.keys(pattern)
            if keys:
                redis_client.delete(*keys)
        except Exception:
            pass


def clear_all_cache():
    if not is_redis_available():
        return
    try:
        redis_client.flushdb()
        logger.info("[缓存] 所有缓存已清除")
    except Exception:
        pass


def cached(expires=300, key_prefix=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not is_redis_available():
                return func(*args, **kwargs)

            if key_prefix:
                key = cache_key(key_prefix)
            else:
                key_parts = [func.__name__]
                for arg in args:
                    if isinstance(arg, (int, str)):
                        key_parts.append(str(arg))
                    elif hasattr(arg, 'id'):
                        key_parts.append(str(arg.id))

                for k, v in sorted(kwargs.items()):
                    if isinstance(v, (int, str)):
                        key_parts.append(f"{k}={v}")

                key = cache_key(*key_parts)

            cached_result = get_cache(key)
            if cached_result is not None:
                logger.debug(f"缓存命中: {key}")
                return cached_result

            result = func(*args, **kwargs)
            if result is not None:
                set_cache(key, result, expires)
                logger.debug(f"缓存设置: {key}, 过期时间: {expires}秒")

            return result
        return wrapper
    return decorator


class CacheKey:
    QUESTIONS = "questions"
    QUESTIONS_BY_MAJOR = "questions:major"
    QUESTIONS_BY_COURSE = "questions:course"
    QUESTIONS_BY_TYPE = "questions:type"

    MAJORS = "majors"
    MAJOR = "major"

    COURSES = "courses"
    COURSES_BY_MAJOR = "courses:major"
    COURSE = "course"

    CHAPTERS = "chapters"
    CHAPTERS_BY_COURSE = "chapters:course"
    CHAPTER = "chapter"

    EXAMS = "exams"
    EXAM = "exam"
    EXAM_QUESTIONS = "exam:questions"
    EXAM_STUDENTS = "exam:students"

    RESULTS = "results"
    RESULT_ANALYSIS = "result:analysis"

    NOTIFICATIONS = "notifications"

    def questions_key(major_id=None, course_id=None, q_type=None):
        parts = [CacheKey.QUESTIONS]
        if major_id:
            parts.append(f"major={major_id}")
        if course_id:
            parts.append(f"course={course_id}")
        if q_type:
            parts.append(f"type={q_type}")
        return ":".join(parts)

    def exams_key(user_id=None):
        if user_id:
            return f"{CacheKey.EXAMS}:user={user_id}"
        return CacheKey.EXAMS

    def result_analysis_key(exam_id):
        return f"{CacheKey.RESULT_ANALYSIS}:{exam_id}"


def invalidate_question_cache(major_id=None, course_id=None):
    delete_pattern(f"{CacheKey.QUESTIONS}:*")
    if major_id:
        delete_pattern(f"{CacheKey.QUESTIONS_BY_MAJOR}:{major_id}:*")
    if course_id:
        delete_pattern(f"{CacheKey.QUESTIONS_BY_COURSE}:{course_id}:*")


def invalidate_major_cache(major_id=None):
    delete_cache(CacheKey.MAJORS)
    if major_id:
        delete_cache(f"{CacheKey.MAJOR}:{major_id}")
        delete_pattern(f"{CacheKey.COURSES_BY_MAJOR}:{major_id}:*")


def invalidate_course_cache(course_id=None):
    delete_pattern(f"{CacheKey.COURSES}:*")
    if course_id:
        delete_cache(f"{CacheKey.COURSE}:{course_id}")
        delete_pattern(f"{CacheKey.CHAPTERS_BY_COURSE}:{course_id}:*")


def invalidate_chapter_cache(chapter_id=None, course_id=None):
    delete_pattern(f"{CacheKey.CHAPTERS}:*")
    if chapter_id:
        delete_cache(f"{CacheKey.CHAPTER}:{chapter_id}")
    if course_id:
        delete_pattern(f"{CacheKey.CHAPTERS_BY_COURSE}:{course_id}:*")


def invalidate_exam_cache(exam_id=None):
    delete_pattern(f"{CacheKey.EXAMS}:*")
    if exam_id:
        delete_pattern(f"{CacheKey.EXAM}:{exam_id}*")
        delete_cache(f"{CacheKey.EXAM_QUESTIONS}:{exam_id}")
        delete_cache(f"{CacheKey.EXAM_STUDENTS}:{exam_id}")


def invalidate_result_cache(exam_id=None):
    delete_pattern(f"{CacheKey.RESULTS}:*")
    if exam_id:
        delete_cache(CacheKey.result_analysis_key(exam_id))
