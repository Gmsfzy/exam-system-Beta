# -*- coding: utf-8 -*-
"""征集悬赏模块数据模型：Bounty（悬赏单）/ BountySubmission（投稿）"""
from database import db
from database.types import UTCDateTime, JSONType
from utils.timeutil import utcnow, iso_local


class BountyTypeEnum:
    QUESTION = 'question'   # 题目征集：投稿人提交自编题目
    ANSWER = 'answer'       # 答案征集：投稿人提交答案/解析


class BountyStatusEnum:
    REVIEWING = 'reviewing'   # 发布待审核（v4.5 审核门禁）
    REJECTED = 'rejected'     # 审核驳回，托管赏金已退回
    OPEN = 'open'           # 征集中
    CLOSED = 'closed'       # 已采纳关闭
    EXPIRED = 'expired'     # 已过期
    CANCELLED = 'cancelled' # 发布者主动撤销/关闭 (P0)


class SubmissionStatusEnum:
    PENDING = 'pending'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    WITHDRAWN = 'withdrawn'  # 投稿人主动撤回 (P0)


class Bounty(db.Model):
    """悬赏单：师生均可发布"""
    id = db.Column(db.Integer, primary_key=True)
    publisher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    bounty_type = db.Column(db.String(20), nullable=False, default=BountyTypeEnum.QUESTION)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    # 答案悬赏：针对题库已有题（二选一，或都为空表示纯描述）
    target_question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    # 答案悬赏：自带题目快照 {content, options, answer}
    target_question_snapshot = db.Column(JSONType)

    # 题目悬赏：期望的专业/题型/难度（题目投稿入库用 major_id）
    major_id = db.Column(db.Integer, db.ForeignKey('major.id'))
    q_type = db.Column(db.String(20))
    q_difficulty = db.Column(db.String(20))

    reward_points = db.Column(db.Integer, nullable=False, default=10)
    status = db.Column(db.String(20), nullable=False, default=BountyStatusEnum.OPEN)
    deadline = db.Column(UTCDateTime)

    # 被采纳的投稿 id（普通 Integer，避免与 submissions 表循环 FK）
    accepted_submission_id = db.Column(db.Integer)

    # 多档采纳（迁移 0011）：最多可采纳数，1=单一中标；accept_count 记录已采纳数
    max_accepts = db.Column(db.Integer, nullable=False, default=1)
    accept_count = db.Column(db.Integer, nullable=False, default=0)
    # 搜索与发现 (P1)：逗号分隔标签
    tags = db.Column(db.String(200))
    # 定向悬赏 (P3)：public 全体可见 / targeted 仅 target_json 指定人群
    visibility = db.Column(db.String(10), nullable=False, default='public')
    target_json = db.Column(JSONType)        # {major_ids:[], user_ids:[]}
    # 赏金托管 (P3)：发布冻结、采纳释放、过期/取消退回（0=未启用托管）
    frozen_points = db.Column(db.Integer, nullable=False, default=0)
    # v4.5 发布审核门禁（迁移 0014 加列）
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewed_at = db.Column(UTCDateTime)
    review_reason = db.Column(db.String(200))

    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    closed_at = db.Column(UTCDateTime)

    publisher = db.relationship('User', foreign_keys=[publisher_id], backref='bounties', lazy=True)
    target_question = db.relationship('Question', foreign_keys=[target_question_id], lazy=True)
    major = db.relationship('Major', foreign_keys=[major_id], lazy=True)
    submissions = db.relationship(
        'BountySubmission', backref='bounty', lazy=True,
        cascade='all, delete-orphan', foreign_keys='BountySubmission.bounty_id')
    comments = db.relationship(
        'BountyComment', backref='bounty', lazy=True,
        cascade='all, delete-orphan', order_by='BountyComment.created_at')
    reports = db.relationship(
        'BountyReport', backref='bounty', lazy=True,
        cascade='all, delete-orphan', foreign_keys='BountyReport.bounty_id')

    @property
    def is_expired(self):
        return (self.status == BountyStatusEnum.OPEN
                and self.deadline is not None
                and utcnow() > self.deadline)

    def effective_status(self):
        """读取时惰性反映过期（不落库，由后台/读取方决定是否持久化）"""
        if self.is_expired:
            return BountyStatusEnum.EXPIRED
        return self.status

    def accepts_remaining(self):
        """还剩多少可采纳名额（>= 未达上限时为正）"""
        return max(0, (self.max_accepts or 1) - (self.accept_count or 0))

    def visible_to(self, user):
        """定向悬赏可见性判定：public 人人可见；targeted 仅发布者/指定专业/指定用户。"""
        if user is not None and self.publisher_id == user.id:
            return True
        if (self.visibility or 'public') != 'targeted':
            return True
        tgt = self.target_json or {}
        if user is None:
            return False
        if user.id in (tgt.get('user_ids') or []):
            return True
        major_ids = tgt.get('major_ids') or []
        if major_ids and getattr(user, 'major_id', None) in major_ids:
            return True
        return False

    def to_dict(self, current_user_id=None):
        accepted_list = [s for s in self.submissions
                         if s.status == SubmissionStatusEnum.ACCEPTED]
        is_pub = (current_user_id is not None and self.publisher_id == current_user_id)
        # 自带题目快照：题干/选项公开供投稿参考，但快照中的答案仅发布者本人可见
        snapshot = self.target_question_snapshot
        if isinstance(snapshot, dict) and not is_pub:
            snapshot = {k: v for k, v in snapshot.items() if k != 'answer'}
        data = {
            'id': self.id,
            'publisher_id': self.publisher_id,
            'publisher_name': self.publisher.username if self.publisher else '',
            'bounty_type': self.bounty_type,
            'title': self.title,
            'description': self.description,
            'target_question_id': self.target_question_id,
            'target_question_snapshot': snapshot,
            'major_id': self.major_id,
            'major_name': self.major.name if self.major else '',
            'q_type': self.q_type,
            'q_difficulty': self.q_difficulty,
            'tags': self.tags or '',
            'reward_points': self.reward_points,
            'max_accepts': self.max_accepts or 1,
            'accept_count': self.accept_count or 0,
            'visibility': self.visibility or 'public',
            'frozen_points': self.frozen_points or 0,
            'status': self.effective_status(),
            'review_reason': self.review_reason,
            'deadline': iso_local(self.deadline),
            'accepted_submission_id': self.accepted_submission_id,
            'accepted_submissions': [s.to_dict(current_user_id, is_pub) for s in accepted_list],
            'created_at': iso_local(self.created_at),
            'updated_at': iso_local(self.updated_at),
            'closed_at': iso_local(self.closed_at),
            'submission_count': len(self.submissions),
            'pending_count': sum(1 for s in self.submissions
                                 if s.status == SubmissionStatusEnum.PENDING),
            'comment_count': len(self.comments) if self.comments else 0,
        }
        if accepted_list:
            data['accepted_submission'] = accepted_list[0].to_dict(current_user_id, is_pub)
        if current_user_id is not None:
            data['is_publisher'] = is_pub
            data['my_submission'] = next(
                (s.to_dict(current_user_id, is_pub) for s in self.submissions
                 if s.submitter_id == current_user_id),
                None)
        return data


class BountySubmission(db.Model):
    """投稿：不能投给自己发布的悬赏，每人每悬赏一条（唯一约束）"""
    id = db.Column(db.Integer, primary_key=True)
    bounty_id = db.Column(db.Integer, db.ForeignKey('bounty.id'), nullable=False)
    submitter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # 答案投稿：答案/解析正文
    content = db.Column(db.Text)

    # 题目投稿：结构化题目字段
    q_content = db.Column(db.Text)
    q_options = db.Column(JSONType)
    q_answer = db.Column(db.Text)
    q_analysis = db.Column(db.Text)
    q_type = db.Column(db.String(20))
    q_difficulty = db.Column(db.String(20))
    q_knowledge = db.Column(db.String(200))

    status = db.Column(db.String(20), nullable=False, default=SubmissionStatusEnum.PENDING)
    review_comment = db.Column(db.Text)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    # 题目投稿被采纳后入库的 Question id
    accepted_question_id = db.Column(db.Integer, db.ForeignKey('question.id'))

    # 多档采纳实得赏金 / 匿名投稿 / 改投时间（迁移 0011）
    reward_share = db.Column(db.Integer, nullable=False, default=0)
    is_anonymous = db.Column(db.Boolean, nullable=False, default=False)
    edited_at = db.Column(UTCDateTime)

    # 投稿附件（v4.6，迁移 0015）：[{filename, stored_name, size, uploaded_at}]
    attachment_json = db.Column(JSONType)

    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    reviewed_at = db.Column(UTCDateTime)

    submitter = db.relationship('User', foreign_keys=[submitter_id], lazy=True)
    reviewer = db.relationship('User', foreign_keys=[reviewer_id], lazy=True)
    accepted_question = db.relationship('Question', foreign_keys=[accepted_question_id], lazy=True)
    votes = db.relationship('BountyVote', backref='submission', lazy=True,
                            cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('bounty_id', 'submitter_id', name='_bounty_submitter_uc'),
    )

    def to_dict(self, viewer_id=None, is_publisher=False):
        """序列化。viewer_id/is_publisher 用于：
        - 匿名投稿对非发布者/非本人隐去身份；
        - 未采纳投稿的题目答案仅发布者/本人可见（防兵库）。"""
        owner = (viewer_id is not None and viewer_id == self.submitter_id)
        anon = self.is_anonymous and not (is_publisher or owner)
        show_answer = is_publisher or owner or self.status == SubmissionStatusEnum.ACCEPTED
        return {
            'id': self.id,
            'bounty_id': self.bounty_id,
            'submitter_id': None if anon else self.submitter_id,
            'submitter_name': '匿名用户' if anon else (self.submitter.username if self.submitter else ''),
            'is_anonymous': bool(self.is_anonymous),
            'content': self.content,
            'q_content': self.q_content,
            'q_options': self.q_options,
            'q_answer': self.q_answer if show_answer else None,
            'q_analysis': self.q_analysis,
            'q_type': self.q_type,
            'q_difficulty': self.q_difficulty,
            'q_knowledge': self.q_knowledge,
            'status': self.status,
            'review_comment': self.review_comment,
            'reviewer_id': self.reviewer_id,
            'accepted_question_id': self.accepted_question_id,
            'reward_share': self.reward_share or 0,
            'vote_count': len(self.votes) if self.votes else 0,
            # 附件仅披露存在性与下载 id，原始文件名隐去防匿名泄露
            'attachments': [{'id': i, 'size': a.get('size', 0),
                             'ext': (a.get('stored_name') or '')[(a.get('stored_name') or '').rfind('.'):]}
                            for i, a in enumerate(self.attachment_json or [])],
            'created_at': iso_local(self.created_at),
            'edited_at': iso_local(self.edited_at),
            'reviewed_at': iso_local(self.reviewed_at),
        }


# ═════════════ 悬赏社区化升级（P2/P3）：评论 / 投票 / 举报（钱包/流水已迁至统一账本 ledger/models.py） ═════════════

class BountyComment(db.Model):
    """悬赏/投稿讨论区：一层沟通，可针对整个悬赏或某条投稿。"""
    __tablename__ = 'bounty_comment'
    id = db.Column(db.Integer, primary_key=True)
    bounty_id = db.Column(db.Integer, db.ForeignKey('bounty.id'), nullable=False, index=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('bounty_submission.id'))  # 可空：针对投稿
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    author = db.relationship('User', backref='bounty_comments', lazy=True)
    submission = db.relationship('BountySubmission', backref='comments')

    def to_dict(self):
        return {
            'id': self.id, 'bounty_id': self.bounty_id, 'submission_id': self.submission_id,
            'user_id': self.user_id,
            'user_name': self.author.username if self.author else '',
            'content': self.content, 'created_at': iso_local(self.created_at),
        }


class BountyVote(db.Model):
    """投稿社区投票（同行评审/点赞）：一人一投稿一票，value 为 +1。"""
    __tablename__ = 'bounty_vote'
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('bounty_submission.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    value = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    voter = db.relationship('User', backref='bounty_votes', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('submission_id', 'user_id', name='_bounty_vote_uc'),
    )


class BountyReport(db.Model):
    """举报（P3 治理）：针对悬赏或投稿，待管理员处理。"""
    __tablename__ = 'bounty_report'
    id = db.Column(db.Integer, primary_key=True)
    bounty_id = db.Column(db.Integer, db.ForeignKey('bounty.id'))        # 可空，二选一
    submission_id = db.Column(db.Integer, db.ForeignKey('bounty_submission.id'))
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/resolved/dismissed
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    reporter = db.relationship('User', foreign_keys=[reporter_id], backref='bounty_reports')
    submission = db.relationship('BountySubmission', backref='reports')

    __table_args__ = (
        db.CheckConstraint('(bounty_id IS NOT NULL) OR (submission_id IS NOT NULL)',
                           name='_report_target_ck'),
    )

    def to_dict(self):
        return {
            'id': self.id, 'bounty_id': self.bounty_id, 'submission_id': self.submission_id,
            'reporter_id': self.reporter_id,
            'reporter_name': self.reporter.username if self.reporter else '',
            'reason': self.reason, 'status': self.status,
            'created_at': iso_local(self.created_at),
        }


# 赏金钱包与流水（原 BountyWallet/BountyTxn）已于 v4.8 迁移至统一账本内核：
# 见 ledger/models.py（LedgerAccount/LedgerTxn，currency='bounty'）与 bounty/wallet.py 门面。
# 旧表由迁移 0018 改名为 bounty_wallet_legacy / bounty_txn_legacy 原位留存备查。
