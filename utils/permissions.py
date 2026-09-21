# -*- coding: utf-8 -*-
"""统一权限助手（RBAC 第一步：声明式收敛散点判断）

背景：v4.6 前全系统 30+ 处视图内联 `if not user or not user.is_teacher(): return 403`，
且 4 个模块各有一份本地 _require_teacher。本模块提供单一实现，各调用点保留原文案
（deny_msg/unauth_msg/unauth_status 参数化），保证迁移前后响应状态码与消息完全等价。

约定：返回 (user, err) 元组——鉴权通过为 (user, None)，失败为 (None, (json, code))，
调用方 `user, err = require_teacher(...); if err: return err`。

后续（RBAC 第二步）：在此层之上建权限矩阵（模块×动作），资源级判断
（creator/owner/visible_to）暂留视图内，待矩阵化后统一收敛。
"""
from flask import jsonify

from utils.security import verify_token


def require_teacher(deny_msg='无权访问', unauth_msg='请先登录', unauth_status=401, key='message'):
    """教师门禁：非教师 deny_msg/403；未登录 unauth_msg/unauth_status（默认 401）。

    key：响应体字段名，兼容个别历史接口的 'error' 键（chapter_routes）。"""
    user = verify_token()
    if not user:
        return None, (jsonify({key: unauth_msg}), unauth_status)
    if not user.is_teacher():
        return None, (jsonify({key: deny_msg}), 403)
    return user, None


def require_login(unauth_msg='请先登录', unauth_status=401):
    """登录门禁：仅校验令牌有效性。"""
    user = verify_token()
    if not user:
        return None, (jsonify({'message': unauth_msg}), unauth_status)
    return user, None
