import redis
import json
import functools
import logging
from config import Config

logger = logging.getLogger(__name__)

redis_client = None

def init_redis():
    global redis_client
    try:
        if Config.REDIS_PASSWORD:
            redis_client = redis.Redis(
                host=Config.REDIS_HOST,
                port=Config.REDIS_PORT,
                password=Config.REDIS_PASSWORD,
                db=Config.REDIS_DB,
                socket_timeout=Config.REDIS_TIMEOUT,
                decode_responses=True
            )
        else:
            redis_client = redis.Redis(
                host=Config.REDIS_HOST,
                port=Config.REDIS_PORT,
                db=Config.REDIS_DB,
                socket_timeout=Config.REDIS_TIMEOUT,
                decode_responses=True
            )
        redis_client.ping()
        logger.info(f"Redis 连接成功: {Config.REDIS_HOST}:{Config.REDIS_PORT}/db{Config.REDIS_DB}")
        return True
    except Exception as e:
        redis_client = None
        logger.warning(f"Redis 连接失败: {e}，将使用数据库查询")
        return False

def get_redis():
    return redis_client

def is_redis_available():
    return redis_client is not None

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
    if not is_redis_available():
        return
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
        logger.info("所有缓存已清除")
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
        # 匹配旧无后缀 key 及按角色隔离的 :t/:s 缓存
        delete_pattern(f"{CacheKey.EXAM}:{exam_id}*")
        delete_cache(f"{CacheKey.EXAM_QUESTIONS}:{exam_id}")
        delete_cache(f"{CacheKey.EXAM_STUDENTS}:{exam_id}")

def invalidate_result_cache(exam_id=None):
    delete_pattern(f"{CacheKey.RESULTS}:*")
    if exam_id:
        delete_cache(CacheKey.result_analysis_key(exam_id))