# -*- coding: utf-8 -*-
"""v6.1 首页公开统计 —— 只读聚合端点（零鉴权 / 零迁移 / 零写库）。

挂载：app.py 统一 url_prefix='/api'
端点清单（1 个）：
  GET /stats/public   public   首页「此刻正在发生」实时看板聚合数

设计边界：
- 只返回聚合计数，不含用户标识、帖子标题、题目内容等任何可识别信息；
- 结果 Redis 缓存 60s（首页轮询不打穿 DB），缓存后端不可用时直穿 DB；
- 「今日」口径一律按 Asia/Shanghai 本地日历日（utils/timeutil 契约，v5.36 静态门禁）；
- 聚合失败单点降级为 0，不让首页看板因某张表异常整块 500。
"""
from datetime import timedelta

from flask import Blueprint, jsonify
from sqlalchemy import func

from database import db
from database.models import (
    User, Question, Exam, Answer, Result, WrongAnswerRecord,
    StudyCheckin, StudyMaterial, AiUsageLog,
    CommunityPost, CommunityComment,
)
from competition.models import PkBattle
from bounty.models import Bounty
from homework.models import HomeworkSubmission
from utils.security import limiter
from utils.redis_cache import cache_key, get_cache, set_cache
from utils.timeutil import utcnow, local_today, local_day_start, iso_local

api_stats_bp = Blueprint('api_stats', __name__)

# 缓存键与 TTL：60s 足够让首页"实时"，又能把 COUNT 全表压到每分钟一次
_CACHE_TTL = 60
_CACHE_KEY = cache_key('stats', 'public')


def _count(query):
    """COUNT 单点降级：任何异常（表缺失/连接抖动）返回 0，不拖垮整个看板"""
    try:
        return int(query.count())
    except Exception:
        db.session.rollback()
        return 0


def _scalar(expr):
    try:
        return db.session.query(expr).scalar()
    except Exception:
        db.session.rollback()
        return None


def collect_public_stats():
    """聚合首页看板所需的全部公开数字（纯读，可脱离 Flask request 上下文调用）。"""
    today = local_today()
    day_start = local_day_start(today)
    day_end = day_start + timedelta(days=1)

    # ── 累计计数（平台规模）──
    answers_total = _count(Answer.query)
    posts_total = _count(CommunityPost.query.filter_by(deleted=False, hidden=False))
    comments_total = _count(CommunityComment.query.filter_by(deleted=False, hidden=False))
    submissions_total = _count(HomeworkSubmission.query.filter(
        HomeworkSubmission.submitted_at.isnot(None)))

    counters = {
        'users': _count(User.query),
        'questions': _count(Question.query),
        'public_questions': _count(Question.query.filter_by(is_public=True)),
        'exams': _count(Exam.query),
        'answers': answers_total,
        'homework_submissions': submissions_total,
        'bounties': _count(Bounty.query),
        'pk_battles': _count(PkBattle.query),
        'wrong_records': _count(WrongAnswerRecord.query),
        'posts': posts_total,
        'comments': comments_total,
        'materials': _count(StudyMaterial.query),
    }

    # ── 今日活跃（本地日历日窗口）──
    ai_calls_today = _count(AiUsageLog.query.filter(
        AiUsageLog.created_at >= day_start, AiUsageLog.created_at < day_end))
    ai_success_today = _count(AiUsageLog.query.filter(
        AiUsageLog.created_at >= day_start, AiUsageLog.created_at < day_end,
        AiUsageLog.status == 'success'))
    avg_cost_ms = _scalar(func.coalesce(func.avg(AiUsageLog.cost_ms), 0)) or 0

    today_board = {
        'checkins': _count(StudyCheckin.query.filter_by(day=today)),
        'ai_calls': ai_calls_today,
        'results': _count(Result.query.filter(
            Result.submitted_at >= day_start, Result.submitted_at < day_end)),
        'new_posts': _count(CommunityPost.query.filter(
            CommunityPost.deleted == False,
            CommunityPost.created_at >= day_start,
            CommunityPost.created_at < day_end)),
        'new_submissions': _count(HomeworkSubmission.query.filter(
            HomeworkSubmission.submitted_at >= day_start,
            HomeworkSubmission.submitted_at < day_end)),
    }

    # ── 六模块实时条（首页看板按模块展示）──
    modules = [
        {'key': 'exam', 'label': '在线考试', 'value': answers_total, 'hint': '累计作答'},
        {'key': 'competition', 'label': '答题竞赛', 'value': counters['pk_battles'], 'hint': '1v1 对战'},
        {'key': 'bounty', 'label': '征集悬赏', 'value': counters['bounties'], 'hint': '悬赏话题'},
        {'key': 'learning', 'label': '自主学习', 'value': counters['wrong_records'], 'hint': '错题收录'},
        {'key': 'homework', 'label': '作业练习', 'value': submissions_total, 'hint': '作业提交'},
        {'key': 'community', 'label': '社区中心', 'value': posts_total + comments_total, 'hint': '发帖与评论'},
    ]

    return {
        'counters': counters,
        'today': today_board,
        'ai': {
            'calls_today': ai_calls_today,
            'success_today': ai_success_today,
            'success_rate': round(ai_success_today * 100.0 / ai_calls_today, 1) if ai_calls_today else None,
            'avg_cost_ms': int(round(float(avg_cost_ms))),
        },
        'modules': modules,
        'server_time': iso_local(utcnow()),
        'local_day': today.isoformat(),
    }


@api_stats_bp.route('/stats/public', methods=['GET'])
@limiter.limit('60/minute')
def public_stats():
    """首页公开聚合统计：无鉴权、无个体数据、60s 缓存。"""
    cached = get_cache(_CACHE_KEY)
    if cached is not None:
        cached = dict(cached)
        cached['cached'] = True
        return jsonify(cached)

    data = collect_public_stats()
    data['cached'] = False
    set_cache(_CACHE_KEY, data, _CACHE_TTL)
    return jsonify(data)
