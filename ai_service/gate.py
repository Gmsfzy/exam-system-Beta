# -*- coding: utf-8 -*-
"""AI 用量门禁（v4.5）：每日配额 + 调用日志，供教师治理页做成本管控

策略：
- 学生受每日限额（默认 30 次）约束；教师不限量（仍记日志）
- 配额行跨天惰性重置；日志一次调用一行（success/degraded/fail）
- 均不自动 commit，纳入调用方事务（SSE 端点等在流结束回调里落账）
"""
from database import db
from database.models import AiQuota, AiUsageLog
from utils.timeutil import utcnow

DEFAULT_DAILY_LIMIT = 30


def check_ai_quota(user):
    """用户今日是否还有 AI 调用额度。返回 (allowed, quota)。教师恒放行。"""
    if user.is_teacher():
        return True, None
    today = utcnow().date()
    quota = db.session.get(AiQuota, user.id)
    if quota is None:
        quota = AiQuota(user_id=user.id, daily_limit=DEFAULT_DAILY_LIMIT,
                        used_today=0, reset_date=today)
        db.session.add(quota)
        db.session.commit()
    if quota.reset_date != today:
        quota.reset_date = today
        quota.used_today = 0
        db.session.commit()
    return (quota.used_today or 0) < (quota.daily_limit or 0), quota


def charge_ai_quota(user):
    """消耗一次配额（不 commit，调用方随业务一并提交）。教师免扣。"""
    if user.is_teacher():
        return
    _, quota = check_ai_quota(user)
    if quota is not None:
        quota.used_today = (quota.used_today or 0) + 1


def log_ai_usage(user_id, action, status='success', cost_ms=0):
    """记一笔 AI 调用日志（不 commit）。status: success/degraded/fail"""
    db.session.add(AiUsageLog(user_id=user_id, action=action,
                              status=status, cost_ms=int(cost_ms or 0)))


def get_quota_info(user):
    """前端展示的当日额度信息"""
    if user.is_teacher():
        return {'daily_limit': None, 'used_today': None, 'remaining': None, 'unlimited': True}
    today = utcnow().date()
    quota = db.session.get(AiQuota, user.id)
    if quota is None or quota.reset_date != today:
        limit = quota.daily_limit if quota else DEFAULT_DAILY_LIMIT
        return {'daily_limit': limit, 'used_today': 0, 'remaining': limit, 'unlimited': False}
    remaining = max(0, (quota.daily_limit or 0) - (quota.used_today or 0))
    return {'daily_limit': quota.daily_limit, 'used_today': quota.used_today or 0,
            'remaining': remaining, 'unlimited': False}
