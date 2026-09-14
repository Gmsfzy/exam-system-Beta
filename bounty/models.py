# -*- coding: utf-8 -*-
"""征集悬赏模块数据模型：Bounty（悬赏单）/ BountySubmission（投稿）"""
from database import db
from database.types import UTCDateTime, JSONType
from utils.timeutil import utcnow, iso_local


class BountyTypeEnum:
    QUESTION = 'question'   # 题目征集：投稿人提交自编题目
    ANSWER = 'answer'       # 答案征集：投稿人提交答案/解析


class BountyStatusEnum:
    OPEN = 'open'           # 征集中
    CLOSED = 'closed'       # 已采纳关闭
    EXPIRED = 'expired'     # 已过期


class SubmissionStatusEnum:
    PENDING = 'pending'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'


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

    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    closed_at = db.Column(UTCDateTime)

    publisher = db.relationship('User', foreign_keys=[publisher_id], backref='bounties', lazy=True)
    target_question = db.relationship('Question', foreign_keys=[target_question_id], lazy=True)
    major = db.relationship('Major', foreign_keys=[major_id], lazy=True)
    submissions = db.relationship(
        'BountySubmission', backref='bounty', lazy=True,
        cascade='all, delete-orphan', foreign_keys='BountySubmission.bounty_id')

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

    def to_dict(self, current_user_id=None):
        accepted = next((s for s in self.submissions
                         if s.id == self.accepted_submission_id), None)
        # 自带题目快照：题干/选项公开供投稿参考，但快照中的答案仅发布者本人可见
        snapshot = self.target_question_snapshot
        if isinstance(snapshot, dict) and self.publisher_id != current_user_id:
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
            'reward_points': self.reward_points,
            'status': self.effective_status(),
            'deadline': iso_local(self.deadline),
            'accepted_submission_id': self.accepted_submission_id,
            'created_at': iso_local(self.created_at),
            'closed_at': iso_local(self.closed_at),
            'submission_count': len(self.submissions),
            'pending_count': sum(1 for s in self.submissions
                                 if s.status == SubmissionStatusEnum.PENDING),
        }
        if accepted:
            data['accepted_submission'] = accepted.to_dict()
        if current_user_id is not None:
            data['is_publisher'] = (self.publisher_id == current_user_id)
            data['my_submission'] = next(
                (s.to_dict() for s in self.submissions if s.submitter_id == current_user_id),
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

    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    reviewed_at = db.Column(UTCDateTime)

    submitter = db.relationship('User', foreign_keys=[submitter_id], lazy=True)
    reviewer = db.relationship('User', foreign_keys=[reviewer_id], lazy=True)
    accepted_question = db.relationship('Question', foreign_keys=[accepted_question_id], lazy=True)

    __table_args__ = (
        db.UniqueConstraint('bounty_id', 'submitter_id', name='_bounty_submitter_uc'),
    )

    def to_dict(self, include_contact=False):
        return {
            'id': self.id,
            'bounty_id': self.bounty_id,
            'submitter_id': self.submitter_id,
            'submitter_name': self.submitter.username if self.submitter else '',
            'content': self.content,
            'q_content': self.q_content,
            'q_options': self.q_options,
            'q_answer': self.q_answer,
            'q_analysis': self.q_analysis,
            'q_type': self.q_type,
            'q_difficulty': self.q_difficulty,
            'q_knowledge': self.q_knowledge,
            'status': self.status,
            'review_comment': self.review_comment,
            'reviewer_id': self.reviewer_id,
            'accepted_question_id': self.accepted_question_id,
            'created_at': iso_local(self.created_at),
            'reviewed_at': iso_local(self.reviewed_at),
        }
