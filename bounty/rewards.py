# -*- coding: utf-8 -*-
"""征集悬赏模块的奖励结算（独立于竞赛模块）。

- 积分：复用全局积分账户 UserPointsProfile（ensure_profile 来自积分引擎，
  如同复用 db 一样属于底层能力），悬赏采纳/落选给投稿人加竞技积分。
- 勋章：悬赏模块自定义阶梯勋章（BOUNTY_BADGES），自行发放，不侵入竞赛勋章注册表；
  全局勋章墙接口会合并本模块勋章定义用于展示。
- 历史：采纳加分后同步积分历史快照（段位页历史曲线一致）。
"""
from sqlalchemy.exc import IntegrityError

from database import db
from utils.timeutil import utcnow
# 积分引擎底层能力（账户/段位/推送/历史），跨模块复用
from competition.gamification import (
    ensure_profile, tier_of, tier_progress, current_season, upsert_points_history,
)
from competition.realtime import notify_user
from competition.models import UserBadge, UserPointsProfile
from ledger import core as ledger


# 悬赏模块专属勋章（code -> 定义）；均为终身勋章（season=''）
BOUNTY_BADGES = {
    'bounty_first_accept': {'name': '悬赏新星', 'description': '悬赏投稿首次被采纳', 'icon': '🪙'},
    'bounty_accept_5':     {'name': '金牌答主', 'description': '悬赏投稿累计被采纳 5 次', 'icon': '🏅'},
    'bounty_accept_20':    {'name': '悬赏翘楚', 'description': '悬赏投稿累计被采纳 20 次', 'icon': '🌟'},
    'bounty_publisher_10': {'name': '悬赏达人', 'description': '累计发布 10 条悬赏', 'icon': '📯'},
    'bounty_thanks_giver': {'name': '乐于分享', 'description': '累计投稿 10 次（含未采纳）', 'icon': '🤝'},
}

# 采纳数阶梯阈值 -> 勋章 code
_ACCEPT_TIERS = [(1, 'bounty_first_accept'), (5, 'bounty_accept_5'), (20, 'bounty_accept_20')]


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


def accept_count(user_id):
    """投稿被采纳数"""
    from bounty.models import BountySubmission, SubmissionStatusEnum
    return BountySubmission.query.filter_by(
        submitter_id=user_id, status=SubmissionStatusEnum.ACCEPTED).count()


def _submission_count(user_id):
    from bounty.models import BountySubmission
    return BountySubmission.query.filter_by(submitter_id=user_id).count()


def _publish_count(user_id):
    from bounty.models import Bounty
    return Bounty.query.filter_by(publisher_id=user_id).count()


def _grant_submission_badges(user_id, related_id=None):
    """投稿人相关的终身阶梯勋章校验发放（不 commit）。返回新发放 payload 列表。"""
    granted = []
    ac = accept_count(user_id)
    for need, code in _ACCEPT_TIERS:
        if ac >= need and _grant_badge(user_id, code, '', related_id):
            granted.append(_badge_payload(code, '', related_id))
    if _submission_count(user_id) >= 10 and _grant_badge(user_id, 'bounty_thanks_giver', '', related_id):
        granted.append(_badge_payload('bounty_thanks_giver', '', related_id))
    return granted


def _push_points(user_id, gained, season, old_tier):
    p = ensure_profile(user_id, season)
    progress = tier_progress(p.points)
    notify_user(user_id, 'profile_update', {
        'reason': 'bounty', 'gained': gained, 'points': p.points,
        'tier': progress['tier'], 'tier_changed': progress['tier'] != old_tier,
        'old_tier': old_tier, 'granted_badges': [],
    })
    return progress


def award_bounty(submitter_id, points, related_id=None):
    """悬赏投稿被采纳：加竞技积分 + 阶梯勋章，同步积分历史，Socket 推送。
    独立事务（调用方应先 commit 投稿状态/题目入库等业务改动）。
    积分发放为主、必须成功；勋章并发冲突时回滚后只补发积分。返回 info dict。
    """
    season = current_season()
    try:
        p = ensure_profile(submitter_id, season)
        old_tier = tier_of(p.points)
        p.points += int(points or 0)
        ledger.post(submitter_id, 'points', int(points or 0), 'award', scope=season,
                    ref_type='submission', ref_id=related_id, memo='悬赏投稿中标赏金')
        p.last_played_at = utcnow()
        upsert_points_history(submitter_id, season, p.points)

        granted = _grant_submission_badges(submitter_id, related_id)
        db.session.commit()
    except IntegrityError:
        # 勋章唯一约束并发冲突：回滚后只补发积分（勋章视为已被另一请求发放）
        db.session.rollback()
        p = ensure_profile(submitter_id, season)
        old_tier = tier_of(p.points)
        p.points += int(points or 0)
        ledger.post(submitter_id, 'points', int(points or 0), 'award', scope=season,
                    ref_type='submission', ref_id=related_id, memo='悬赏投稿中标赏金')
        p.last_played_at = utcnow()
        upsert_points_history(submitter_id, season, p.points)
        granted = []
        db.session.commit()

    _push_points(submitter_id, int(points or 0), season, old_tier)
    for badge in granted:
        notify_user(submitter_id, 'badge_granted', badge)
    return {'gained': int(points or 0), 'before_tier': old_tier,
            'profile': p, 'granted': granted, 'reason': 'bounty'}


def award_publisher_badge(publisher_id, related_id=None):
    """发布悬赏累计达标的终身勋章（在发布成功处调用，独立提交）。"""
    granted = []
    if _publish_count(publisher_id) >= 10 and \
            _grant_badge(publisher_id, 'bounty_publisher_10', '', related_id):
        granted.append(_badge_payload('bounty_publisher_10', '', related_id))
        db.session.commit()
    for badge in granted:
        notify_user(publisher_id, 'badge_granted', badge)
    return granted


def thank_you(submitter_id, points, related_id=None):
    """落选感谢积分：鼓励参与，独立事务，不加勋章。"""
    points = int(points or 0)
    if points <= 0:
        return None
    season = current_season()
    p = ensure_profile(submitter_id, season)
    old_tier = tier_of(p.points)
    p.points += points
    ledger.post(submitter_id, 'points', points, 'thanks', scope=season,
                ref_type='submission', ref_id=related_id, memo='悬赏落选感谢积分')
    p.last_played_at = utcnow()
    upsert_points_history(submitter_id, season, p.points)
    db.session.commit()
    _push_points(submitter_id, points, season, old_tier)
    return {'gained': points, 'reason': 'bounty_thanks'}
