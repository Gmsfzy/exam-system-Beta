from functools import wraps
from utils.logger import logger
from flask import jsonify

def log_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {f.__name__}: {str(e)}", exc_info=True)
            return jsonify({"message": "操作失败，请稍后重试"}), 500
    return decorated_function

def log_performance(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        import time
        start_time = time.time()
        try:
            return f(*args, **kwargs)
        finally:
            elapsed = time.time() - start_time
            if elapsed > 1.0:
                logger.warning(f"Slow request: {f.__name__} took {elapsed:.2f}s")
            else:
                logger.debug(f"Request {f.__name__} took {elapsed:.2f}s")
    return decorated_function