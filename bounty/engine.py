# -*- coding: utf-8 -*-
"""征集悬赏运营引擎：站内通知 / 过期治理 / 贡献榜 / 相似题查重。

被 bounty.routes 与后台 scheduler 调用。通知统一走 utils.notify.create_notification
（已上移至 utils 稳定层，无循环依赖）；托管退回走 bounty.wallet。
"""
import re

from database import db
from utils.timeutil import utcnow, fmt_local
from utils.notify import create_notification
from bounty.models import (
    Bounty, BountySubmission, BountyStatusEnum, SubmissionStatusEnum,
)


# ═══════════════ 站内通知 ═══════════════

def _notify(user_id, title, content, type='info', related_id=None):
    create_notification(user_id=user_id, title=title[:200], content=content,
                        type=type, related_type='bounty', related_id=related_id, commit=True)


def notify_new_submission(bounty, submission):
    """有新投稿时提醒发布者"""
    _notify(bounty.publisher_id, '收到新的悬赏投稿',
            f'「{bounty.title}」收到 1 条新投稿，快去审阅吧。',
            type='info', related_id=bounty.id)


def notify_decision(bounty, submission, accepted):
    """采纳/拒绝结果提醒投稿人（匿名不影响本人收件）"""
    if accepted:
        _notify(submission.submitter_id, '悬赏投稿已采纳',
                f'恭喜！你在「{bounty.title}」的投稿已被采纳，'
                f'获得 {submission.reward_share or bounty.reward_points} 竞技积分。',
                type='success', related_id=bounty.id)
    else:
        comment = submission.review_comment or ''
        body = f'你在「{bounty.title}」的投稿未入选。'
        if comment:
            body += f' 反馈：{comment}'
        _notify(submission.submitter_id, '悬赏投稿评审结果', body,
                type='info', related_id=bounty.id)


# ═══════════════ 过期治理（后台调度，幂等）═══════════════

def bounty_expiry_tick():
    """扫描已过截止时间但仍 open 的悬赏：持久化 EXPIRED、退回托管、提醒发布者。

    幂等：仅处理 status==OPEN 且 deadline<now 的行，处理后状态迁移不再命中。
    """
    now = utcnow()
    pendings = Bounty.query.filter(
        Bounty.status == BountyStatusEnum.OPEN,
        Bounty.deadline.isnot(None),
        Bounty.deadline < now,
    ).all()
    for b in pendings:
        try:
            _expire_one(b, now)
        except Exception:
            db.session.rollback()
            continue


def _expire_one(bounty, now):
    from bounty import wallet
    bounty.status = BountyStatusEnum.EXPIRED
    bounty.closed_at = now
    if wallet.escrow_enabled() and (bounty.frozen_points or 0) > 0:
        wallet.refund(bounty, commit=False)
    db.session.commit()
    pending = sum(1 for s in bounty.submissions if s.status == SubmissionStatusEnum.PENDING)
    _notify(bounty.publisher_id, '悬赏已截止',
            f'「{bounty.title}」已到截止时间并自动关闭'
            + (f'，仍有 {pending} 条投稿未处理。' if pending else '。'),
            type='warning', related_id=bounty.id)


# ═══════════════ 贡献榜 ═══════════════

def leaderboard(kind='accept', limit=50):
    """悬赏贡献榜：kind=accept(答疑之星，按被采纳数) / publish(悬赏达人，按发布数)。"""
    from database.models import User
    limit = max(1, min(int(limit or 50), 200))
    if kind == 'publish':
        rows = (db.session.query(Bounty.publisher_id, db.func.count(Bounty.id))
                .group_by(Bounty.publisher_id)
                .order_by(db.func.count(Bounty.id).desc()).limit(limit).all())
    else:
        rows = (db.session.query(BountySubmission.submitter_id, db.func.count(BountySubmission.id))
                .filter(BountySubmission.status == SubmissionStatusEnum.ACCEPTED)
                .group_by(BountySubmission.submitter_id)
                .order_by(db.func.count(BountySubmission.id).desc()).limit(limit).all())
    out = []
    for uid, cnt in rows:
        u = db.session.get(User, uid)
        if u is None or u.role == 'bot':
            continue
        out.append({'user_id': uid, 'username': u.username, 'count': int(cnt)})
    return out


# ═══════════════ 相似题查重（软提示，非强制）═════════════

_TOKEN = re.compile(r'[\w\u4e00-\u9fff]+')


def _tokens(s):
    return set(t.lower() for t in _TOKEN.findall(s or '') if len(t) >= 1)


def find_similar_questions(content, major_id=None, top_n=3, threshold=0.5):
    """基于词重合度(Jaccard)在题库中找相似题，供投稿/采纳时软提示去重灌水。"""
    from database.models import Question
    tokens = _tokens(content)
    if not tokens:
        return []
    q = Question.query
    if major_id:
        q = q.filter(Question.major_id == major_id)
    candidates = q.with_entities(Question.id, Question.content).limit(2000).all()
    scored = []
    for qid, qcontent in candidates:
        ct = _tokens(qcontent)
        if not ct:
            continue
        jacc = len(tokens & ct) / len(tokens | ct)
        if jacc >= threshold:
            scored.append((jacc, qid, (qcontent or '')[:60]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{'id': qid, 'score': round(sc, 2), 'preview': prev}
            for sc, qid, prev in scored[:top_n]]
