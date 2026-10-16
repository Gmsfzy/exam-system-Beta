# -*- coding: utf-8 -*-
"""作业练习数据模型（v5.0）。

全部经由 homework.routes / homework.services 读写；序列化按角色分流：
学生视角永不下发题面答案（question.answer）与未批改得分明细。
同表多 user 外键（teacher_id/graded_by/student_id）relationship 均显式
foreign_keys，规避「第二个 user 外键导致歧义崩溃」历史坑。
"""
from database import db
from database.types import UTCDateTime, JSONType
from utils.timeutil import utcnow, iso_local


class HomeworkStatusEnum:
    DRAFT = 'draft'          # 草稿：仅创建教师可见，可全量编辑
    PUBLISHED = 'published'  # 已发布：学生可见可作答，编辑受限
    CLOSED = 'closed'        # 已关闭：手动撤回或到期锁定，不再接收提交

    ALL = (DRAFT, PUBLISHED, CLOSED)


class HomeworkTypeEnum:
    QUESTION_SET = 'question_set'  # 题集式：从题库选题，逐题作答
    OPEN = 'open'                  # 开放式：整段说明 + 文字/附件作答

    ALL = (QUESTION_SET, OPEN)


class SubmissionStatusEnum:
    DRAFT = 'draft'        # 自动保存草稿（承载逐题作答中间态）
    SUBMITTED = 'submitted'  # 已提交待批改（客观/编程已自动判分）
    GRADED = 'graded'        # 已批改（学生可见总分与评语）

    ALL = (DRAFT, SUBMITTED, GRADED)


class Homework(db.Model):
    __tablename__ = 'homework'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default='')   # 作业说明（开放式即题面）
    hw_type = db.Column(db.String(20), nullable=False, default=HomeworkTypeEnum.QUESTION_SET)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=HomeworkStatusEnum.DRAFT)
    deadline = db.Column(UTCDateTime, nullable=True)              # 时效：截止时间（None=不设截止，永不过期）
    allow_late = db.Column(db.Boolean, nullable=False, default=True)     # 逾期是否可交（记 late）
    allow_resubmit = db.Column(db.Boolean, nullable=False, default=True)  # 截止前是否可重交覆盖
    remind_before = db.Column(db.Integer, nullable=False, default=0)      # 到期前 N 分钟提醒未交学生（0=不提醒）
    pass_score = db.Column(db.Float, nullable=True)                       # 及格线（None=不设，用于统计及格/优秀率）
    reference_json = db.Column(JSONType)                                  # 教师参考资料附件 {filename,stored_name,size,ext} 或 None
    reminded_at = db.Column(UTCDateTime)                           # 提醒已发标记（CAS 幂等）
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    published_at = db.Column(UTCDateTime)

    teacher = db.relationship('User', foreign_keys=[teacher_id], backref='homeworks')
    hw_questions = db.relationship('HomeworkQuestion', backref='homework', lazy=True,
                                   cascade='all, delete-orphan')
    hw_students = db.relationship('HomeworkStudent', backref='homework', lazy=True,
                                  cascade='all, delete-orphan')
    submissions = db.relationship('HomeworkSubmission', backref='homework', lazy=True,
                                  cascade='all, delete-orphan')

    @property
    def is_expired(self):
        return self.deadline is not None and utcnow() > self.deadline

    @property
    def accepts_submission(self):
        """当前是否接收（重）提交：已发布 + 未过期，或允许迟交且过期未批。"""
        if self.status != HomeworkStatusEnum.PUBLISHED:
            return False
        if not self.is_expired:
            return True
        return bool(self.allow_late)

    def max_score(self):
        return round(sum(hq.score for hq in self.hw_questions), 2) \
            if self.hw_type == HomeworkTypeEnum.QUESTION_SET else None

    def reference_meta(self):
        """仅披露教师参考资料的 filename/size/ext（stored_name 不外泄，下载走鉴权端点）。"""
        ref = self.reference_json or {}
        if not ref.get('stored_name'):
            return None
        return {'filename': ref.get('filename'), 'size': ref.get('size') or 0,
                'ext': ref.get('ext')}

    def to_dict(self, for_teacher=False, stats=None):
        d = {'id': self.id, 'title': self.title, 'description': self.description or '',
             'hw_type': self.hw_type, 'teacher_id': self.teacher_id, 'status': self.status,
             'deadline': iso_local(self.deadline) if self.deadline else None,
             'has_deadline': self.deadline is not None,
             'allow_late': bool(self.allow_late),
             'allow_resubmit': bool(self.allow_resubmit), 'remind_before': self.remind_before or 0,
             'pass_score': self.pass_score,
             'reference': self.reference_meta(),
             'is_expired': self.is_expired,
             'created_at': iso_local(self.created_at),
             'published_at': iso_local(self.published_at) if self.published_at else None,
             'question_count': len(self.hw_questions),
             'total_score': self.max_score()}
        if for_teacher:
            d['teacher_name'] = self.teacher.username if self.teacher else ''
            if stats:
                d.update(stats)
        return d


class HomeworkQuestion(db.Model):
    """题集式作业的题目配置（镜像 ExamQuestion，复合主键）。"""
    __tablename__ = 'homework_question'

    homework_id = db.Column(db.Integer, db.ForeignKey('homework.id'), primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), primary_key=True)
    score = db.Column(db.Float, nullable=False, default=1.0)
    order = db.Column(db.Integer, nullable=False, default=0)

    question = db.relationship('Question')


class HomeworkStudent(db.Model):
    """作业发布名单（镜像 ExamStudent，不做邀请码）。"""
    __tablename__ = 'homework_student'

    homework_id = db.Column(db.Integer, db.ForeignKey('homework.id'), primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    assigned_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    student = db.relationship('User')


class HomeworkSubmission(db.Model):
    """作业提交：一人一份，截止前重交覆盖（version 递增）；开放式文字+附件同表承载。"""
    __tablename__ = 'homework_submission'
    __table_args__ = (db.UniqueConstraint('homework_id', 'student_id',
                                          name='uq_homework_submission_hw_student'),)

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey('homework.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default=SubmissionStatusEnum.DRAFT)
    content = db.Column(db.Text, nullable=False, default='')            # 开放式正文作答
    attachment_json = db.Column(JSONType)                               # {filename,stored_name,size,ext} 或 None
    version = db.Column(db.Integer, nullable=False, default=1)          # 第 N 次提交（重交覆盖递增）
    is_late = db.Column(db.Boolean, nullable=False, default=False)      # 迟交标记
    submitted_at = db.Column(UTCDateTime)
    total_score = db.Column(db.Float)                                   # 批改/判分后总分
    max_score = db.Column(db.Float)                                     # 提交时全卷满分快照
    comment = db.Column(db.Text)                                        # 教师总评
    graded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    graded_at = db.Column(UTCDateTime)

    student = db.relationship('User', foreign_keys=[student_id], backref='homework_submissions')
    grader = db.relationship('User', foreign_keys=[graded_by])
    answers = db.relationship('HomeworkAnswer', backref='submission', lazy=True,
                              cascade='all, delete-orphan')

    def attachment_meta(self):
        """仅披露文件名/大小/扩展名（stored_name 不外泄，下载走鉴权端点）。"""
        att = self.attachment_json or {}
        if not att.get('stored_name'):
            return None
        return {'filename': att.get('filename'), 'size': att.get('size') or 0,
                'ext': att.get('ext')}

    def to_dict(self, for_teacher=False):
        d = {'id': self.id, 'homework_id': self.homework_id, 'student_id': self.student_id,
             'status': self.status, 'content': self.content or '',
             'attachment': self.attachment_meta(), 'version': self.version,
             'is_late': bool(self.is_late),
             'submitted_at': iso_local(self.submitted_at) if self.submitted_at else None,
             'max_score': self.max_score,
             'graded_at': iso_local(self.graded_at) if self.graded_at else None}
        # 成绩可见性：批改完成后学生才见分数与评语
        if for_teacher or self.status == SubmissionStatusEnum.GRADED:
            d['total_score'] = self.total_score
            d['comment'] = self.comment or ''
        else:
            d['total_score'] = None
            d['comment'] = ''
        if for_teacher and self.student:
            d['username'] = self.student.username
        return d


class HomeworkAnswer(db.Model):
    """逐题作答：客观/编程提交即自动判分（auto_score），主观题人工给分（manual_score）。"""
    __tablename__ = 'homework_answer'

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('homework_submission.id'),
                              nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    answer = db.Column(db.Text, nullable=False, default='')
    auto_score = db.Column(db.Float)          # 客观/OJ 自动分（None=未判或不适用）
    manual_score = db.Column(db.Float)        # 教师人工分（None=未批）
    is_correct = db.Column(db.Boolean)
    oj_verdict = db.Column(db.String(10))     # AC/WA/TLE/RE/CE（仅编程题有用例时写入）
    needs_manual_grade = db.Column(db.Boolean, nullable=False, default=False)
    comment = db.Column(db.Text)              # 逐题评语
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    question = db.relationship('Question')

    @property
    def effective_score(self):
        """有效得分：人工优先，回落自动分。"""
        if self.manual_score is not None:
            return self.manual_score
        return self.auto_score if self.auto_score is not None else 0.0

    def to_dict(self, for_teacher=False, max_score=None):
        d = {'id': self.id, 'submission_id': self.submission_id,
             'question_id': self.question_id, 'answer': self.answer or '',
             'is_correct': self.is_correct, 'oj_verdict': self.oj_verdict,
             'needs_manual_grade': bool(self.needs_manual_grade)}
        if for_teacher:
            d.update({'auto_score': self.auto_score, 'manual_score': self.manual_score,
                      'comment': self.comment or '', 'max_score': max_score,
                      'effective_score': self.effective_score})
        elif not self.needs_manual_grade:
            # 学生可见已自动判分部分（未批改时 total_score 仍隐藏）
            d['auto_score'] = self.auto_score
        return d
