# -*- coding: utf-8 -*-
"""征集悬赏模块的奖励结算（独立于竞赛模块）。

- 积分：复用全局积分账户 UserPointsProfile（ensure_profile 来自积分引擎，
  如同复用 db 一样属于底层能力），悬赏采纳给投稿人加竞技积分。
- 勋章：悬赏模块自定义勋章（BOUNTY_BADGES），自行发放，不侵入竞赛勋章注册表；
  全局勋章墙接口会合并本模块勋章定义用于展示。
"""
from sqlalchemy.exc import IntegrityError

from database import db
from utils.timeutil import utcnow
# 积分引擎底层能力（账户/段位/推送），跨模块复用
from competition.gamification import (
    ensure_profile, tier_of, tier_progress, current_season,
)
from competition.realtime import notify_user
from competition.models import UserBadge, UserPointsProfile


# 悬赏模块专属勋章（code -> 定义）
BOUNTY_BADGES = {
    'bounty_first_accept': {
        'name': '悬赏新星', 'description': '悬赏投稿首次被采纳', 'icon': '🪙',
    },
}


def _grant_badge(user_id, code, season='', related_id=None):
    """发放悬赏勋章（幂等）；唯一约束兜底并发。返回是否新发放。"""
    exists = UserBadge.query.filter_by(
        user_id=user_id, badge_code=code, season=season).first()
    if exists:
        return False
    db.session.add(UserBadge(
        user_id=user_id, badge_code=code, season=season, related_id=related_id))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return False
    return True


def _badge_payload(code, season='', related_id=None):
    d = BOUNTY_BADGES[code]
    return {'code': code, 'name': d['name'], 'description': d['description'],
            'icon': d['icon'], 'season': season, 'related_id': related_id}


def _bounty_accept_count(user_id):
    """投稿被采纳数（用于判断首次采纳勋章）"""
    from bounty.models import BountySubmission, SubmissionStatusEnum
    return BountySubmission.query.filter_by(
        submitter_id=user_id, status=SubmissionStatusEnum.ACCEPTED).count()


def award_bounty(submitter_id, points, related_id=None):
    """悬赏投稿被采纳：加竞技积分 + 首次采纳勋章，Socket 推送。
    独立事务（调用方应先 commit 投稿状态/题目入库等业务改动）。
    积分发放为主、必须成功；勋章并发冲突时回滚后补发积分。返回 info dict。
    """
    season = current_season()
    try:
        p = ensure_profile(submitter_id, season)
        old_tier = tier_of(p.points)
        p.points += points
        p.last_played_at = utcnow()

        granted = []
        if _bounty_accept_count(submitter_id) >= 1 and \
                _grant_badge(submitter_id, 'bounty_first_accept', season, related_id):
            granted.append(_badge_payload('bounty_first_accept', season, related_id))

        db.session.commit()
    except IntegrityError:
        # 勋章唯一约束并发冲突：回滚后只补发积分（勋章视为已被另一请求发放）
        db.session.rollback()
        p = ensure_profile(submitter_id, season)
        old_tier = tier_of(p.points)
        p.points += points
        p.last_played_at = utcnow()
        db.session.commit()
        granted = []

    progress = tier_progress(p.points)
    info = {'gained': points, 'before_tier': old_tier, 'profile': p,
            'granted': granted, 'reason': 'bounty'}
    # 推送积分/段位变化与勋章（与竞赛模块同一事件协议，前端无需改造）
    notify_user(submitter_id, 'profile_update', {
        'reason': 'bounty',
        'gained': points,
        'points': p.points,
        'tier': progress['tier'],
        'tier_changed': progress['tier'] != old_tier,
        'old_tier': old_tier,
        'granted_badges': granted,
    })
    for badge in granted:
        notify_user(submitter_id, 'badge_granted', badge)
    return info
