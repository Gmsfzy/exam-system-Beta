from flask import Blueprint, request, jsonify
from utils.logger import logger, vue3_logger
from utils.decorators import log_errors
from utils.security import verify_token
import logging

api_log_bp = Blueprint('api_log', __name__)

# 日志上报约束：仅登录用户、级别白名单、长度上限、剥离换行防日志伪造
_LEVELS = {'DEBUG', 'INFO', 'WARNING', 'ERROR'}
_MAX_MSG_LEN = 2000
_MAX_FIELD_LEN = 500


def _clean(value, max_len=_MAX_MSG_LEN):
    """截断长度并把换行/回车替换为空格，防止注入伪造日志行"""
    if value is None:
        return ''
    text = str(value).replace('\r', ' ').replace('\n', ' ')
    return text[:max_len]


@api_log_bp.route('/logs', methods=['POST'])
@log_errors
def receive_frontend_log():
    if not verify_token():
        return jsonify({'message': '请先登录'}), 401
    data = request.get_json(silent=True) or {}
    level = str(data.get('level', 'INFO')).upper()
    if level not in _LEVELS:
        level = 'INFO'
    message = _clean(data.get('message', ''))
    source = _clean(data.get('source', 'vue3'), _MAX_FIELD_LEN)
    frontend_data = data.get('data')
    data_str = _clean(frontend_data, _MAX_FIELD_LEN) if frontend_data else ''

    log_message = f"[Frontend/{source}] {message}"
    if data_str:
        log_message += f" | Data: {data_str}"

    getattr(logger, level.lower(), logger.info)(log_message)
    return jsonify({"message": "日志已接收"}), 200


@api_log_bp.route('/logs/vue', methods=['POST'])
@log_errors
def receive_vue_log():
    if not verify_token():
        return jsonify({'message': '请先登录'}), 401
    data = request.get_json(silent=True) or {}
    level = str(data.get('level', 'INFO')).upper()
    if level not in _LEVELS:
        level = 'INFO'
    message = _clean(data.get('message', ''))
    component = _clean(data.get('component', ''), _MAX_FIELD_LEN)
    url = _clean(data.get('url', ''), _MAX_FIELD_LEN)

    log_message = f"[Vue3] {component} | {message} | URL: {url}"
    getattr(vue3_logger, level.lower(), vue3_logger.info)(log_message)
    return jsonify({"message": "Vue日志已接收"}), 200
