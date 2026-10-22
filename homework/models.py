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
    is_group = db.Column(db.Boolean, nullable=False, default=False)  # v5.7 小组作业：发布时教师勾选
    series_id = db.Column(db.Integer, db.ForeignKey('homework_series.id'), nullable=True, index=True)  # v5.8 系列生成的作业
    # v5.9 深度互评：互评截止时间 + 互评分权重（0=不计入总分视图，独立字段展示，不改 total_score）
    peer_review_deadline = db.Column(UTCDateTime)
    peer_review_weight = db.Column(db.Float, nullable=False, default=0.0)
    peer_review_reminded_at = db.Column(UTCDateTime)
    # v5.11 批改提效与防抄
    late_penalty_pct = db.Column(db.Float, nullable=False, default=0.0)  # 迟交扣分百分比（0-100，0=不扣）
    blind_grading = db.Column(db.Boolean, nullable=False, default=False)  # 匿名批改：批完前隐藏学生身份
    shuffle_questions = db.Column(db.Boolean, nullable=False, default=False)  # 题目乱序（每生固定题序）
    shuffle_options = db.Column(db.Boolean, nullable=False, default=False)    # 选择题选项乱序
    remind_levels_json = db.Column(JSONType)  # 分级提醒档位 [{minutes,label}]；空=沿用 remind_before 单档
    reminded_json = db.Column(JSONType)       # 各档已发标记 {str(minutes): ISO}
    # v5.14 多种评分制（仅显示层派生，不改 total_score/积分/错题口径）
    grade_mode = db.Column(db.String(10), nullable=False, default='numeric')  # numeric|level|comment
    grade_scale_json = db.Column(JSONType)    # 自定义等级档位 [{label,min}]；空=内置 优/良/中/差 阈值

    teacher = db.relationship('User', foreign_keys=[teacher_id], backref='homeworks')
    hw_questions = db.relationship('HomeworkQuestion', backref='homework', lazy=True,
                                   cascade='all, delete-orphan')
    hw_students = db.relationship('HomeworkStudent', backref='homework', lazy=True,
                                  cascade='all, delete-orphan')
    submissions = db.relationship('HomeworkSubmission', backref='homework', lazy=True,
                                  cascade='all, delete-orphan')
    ai_reviews = db.relationship('HomeworkAiReview', backref='homework', lazy=True,
                                 cascade='all, delete-orphan')
    comments = db.relationship('HomeworkComment', backref='homework', lazy=True,
                               cascade='all, delete-orphan')
    peer_reviews = db.relationship('HomeworkPeerReview', backref='homework', lazy=True,
                                   cascade='all, delete-orphan')
    groups = db.relationship('HomeworkGroup', backref='homework', lazy=True,
                             cascade='all, delete-orphan')
    # v5.8 系列关联通过 HomeworkSeries.homeworks 的 backref=series_obj 暴露，避免重复 relationship 冲突

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

    def remind_levels(self):
        """分级提醒档位列表；为空时回落到 remind_before 单档（保持旧行为）。"""
        levels = self.remind_levels_json
        if isinstance(levels, list) and levels:
            return levels
        if self.remind_before and self.remind_before > 0:
            return [{'minutes': int(self.remind_before), 'label': ''}]
        return []

    # ── v5.14 多种评分制：仅显示层派生，不改 total_score/积分/错题口径 ──
    _DEFAULT_SCALE = [{'label': '优', 'min': 0.9}, {'label': '良', 'min': 0.8},
                      {'label': '中', 'min': 0.6}, {'label': '差', 'min': 0.0}]

    def grade_scale(self):
        """等级阀值列表（按 min 降序）。自定义 grade_scale_json 非法/空时回落内置四档。"""
        s = self.grade_scale_json
        if isinstance(s, list) and s:
            try:
                items = [{'label': str(x.get('label') or ''), 'min': float(x.get('min'))}
                         for x in s if isinstance(x, dict)]
                if items:
                    return sorted(items, key=lambda k: k['min'], reverse=True)
            except (TypeError, ValueError):
                pass
        return sorted(self._DEFAULT_SCALE, key=lambda k: k['min'], reverse=True)

    def level_for_ratio(self, ratio):
        """得分率→等级标签：取首个 min<=ratio 的档位（降序遍历）。"""
        scale = self.grade_scale()
        for it in scale:
            if ratio >= it['min']:
                return it['label']
        return scale[-1]['label'] if scale else ''

    def to_dict(self, for_teacher=False, stats=None):
        d = {'id': self.id, 'title': self.title, 'description': self.description or '',
             'hw_type': self.hw_type, 'teacher_id': self.teacher_id, 'status': self.status,
             'deadline': iso_local(self.deadline) if self.deadline else None,
             'has_deadline': self.deadline is not None,
             'allow_late': bool(self.allow_late),
             'allow_resubmit': bool(self.allow_resubmit), 'remind_before': self.remind_before or 0,
             'pass_score': self.pass_score,
             'late_penalty_pct': float(self.late_penalty_pct or 0.0),
             'reference': self.reference_meta(),
             'is_expired': self.is_expired,
             'created_at': iso_local(self.created_at),
             'published_at': iso_local(self.published_at) if self.published_at else None,
             'question_count': len(self.hw_questions),
             'total_score': self.max_score(),
             'is_group': bool(self.is_group),
             'series_id': self.series_id,
             'peer_review_deadline': iso_local(self.peer_review_deadline)
             if self.peer_review_deadline else None,
             'peer_review_weight': float(self.peer_review_weight or 0.0),
             'grade_mode': self.grade_mode or 'numeric'}
        if for_teacher:
            d['teacher_name'] = self.teacher.username if self.teacher else ''
            d['grade_scale'] = list(self.grade_scale_json or [])
            d['blind_grading'] = bool(self.blind_grading)
            d['shuffle_questions'] = bool(self.shuffle_questions)
            d['shuffle_options'] = bool(self.shuffle_options)
            d['remind_levels'] = list(self.remind_levels_json or [])
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
    group_id = db.Column(db.Integer, db.ForeignKey('homework_group.id'), nullable=True, index=True)  # v5.7 小组提交
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
    # v5.11 批改提效与防抄
    score_before_penalty = db.Column(db.Float)             # 迟交扣分前总分（None=未扣分）
    assigned_order_json = db.Column(JSONType)  # 该生题序 [question_id...]（乱序时持久化）
    option_map_json = db.Column(JSONType)      # 选项乱序映射 {str(qid): [perm]}

    student = db.relationship('User', foreign_keys=[student_id], backref='homework_submissions')
    grader = db.relationship('User', foreign_keys=[graded_by])
    group = db.relationship('HomeworkGroup', foreign_keys=[group_id])
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
            # v5.11 迟交扣分透明化：扣分前原始分 / 实扣分 / 扣分率
            if self.score_before_penalty is not None:
                d['score_before_penalty'] = self.score_before_penalty
                d['late_deducted'] = round(self.score_before_penalty - (self.total_score or 0.0), 2)
                d['late_penalty_pct'] = float(self.homework.late_penalty_pct or 0.0) if self.homework else 0.0
        else:
            d['total_score'] = None
            d['comment'] = ''
        # v5.14 多种评分制：派生展示字段（不改 total_score 数值口径，仅影响呈现）
        hw = self.homework
        mode = (getattr(hw, 'grade_mode', 'numeric') if hw else 'numeric') or 'numeric'
        graded = self.status == SubmissionStatusEnum.GRADED
        max_sc = self.max_score if self.max_score is not None else (hw.max_score() if hw else None)
        d['grade_mode'] = mode
        if mode == 'level':
            ratio = (self.total_score / max_sc) if (graded and max_sc and self.total_score is not None) else None
            d['grade_display'] = hw.level_for_ratio(ratio) if (hw and ratio is not None) else None
        elif mode == 'comment':
            d['grade_display'] = (self.comment or '') if graded else ''
            if not for_teacher:
                d['total_score'] = None      # 学生侧仅显评语，不下发数值分
        else:  # numeric：原样等于数值总分（未批/隐藏时为 None）
            d['grade_display'] = d.get('total_score')
        if for_teacher and self.student:
            d['username'] = self.student.username
        if self.group_id and self.group:
            d['group_id'] = self.group_id
            d['group_name'] = self.group.name
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


class HomeworkAiReview(db.Model):
    """作业 AI 讲评（v5.3）：班级共性分析 + 单份讲评，落库缓存可重复查看。

    scope='class'      ：整班共性分析，scope_key='class'，每份作业一行；
    scope='submission' ：学生单份讲评，scope_key='sub:<submission_id>'。
    content_json 存 AI 结构化结果；stats_json 存生成时统计快照（AI 失败时仍可供教师查看）。
    班级讲评默认仅教师可见，published_at 非空才对学生开放。
    """
    __tablename__ = 'homework_ai_review'
    __table_args__ = (db.UniqueConstraint('homework_id', 'scope_key',
                                          name='uq_hw_ai_review_scope'),)

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey('homework.id'),
                            nullable=False, index=True)
    scope = db.Column(db.String(20), nullable=False)          # class / submission
    scope_key = db.Column(db.String(40), nullable=False)      # class / sub:<id>
    submission_id = db.Column(db.Integer,
                              db.ForeignKey('homework_submission.id'), nullable=True)
    content_json = db.Column(JSONType)                        # AI 讲评结构化内容
    stats_json = db.Column(JSONType)                          # 生成时统计快照
    model = db.Column(db.String(50))                          # 生成模型/降级标记
    degraded = db.Column(db.Boolean, nullable=False, default=False)  # AI 失败走规则降级
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
    published_at = db.Column(UTCDateTime)                     # 班级讲评发布给学生时间

    submission = db.relationship('HomeworkSubmission')
    creator = db.relationship('User', foreign_keys=[created_by])

    def to_dict(self, for_student=False):
        d = {'id': self.id, 'homework_id': self.homework_id, 'scope': self.scope,
             'submission_id': self.submission_id,
             'content': self.content_json or {}, 'stats': self.stats_json or {},
             'degraded': bool(self.degraded), 'model': self.model,
             'created_at': iso_local(self.created_at),
             'updated_at': iso_local(self.updated_at),
             'published_at': iso_local(self.published_at) if self.published_at else None,
             'published': self.published_at is not None}
        if for_student:
            # 学生视角不披露创建者与内部 submission 关联之外的信息
            d.pop('model', None)
        return d


class HomeworkComment(db.Model):
    """作业讨论区（v5.4）：作业级 + 可选按题讨论，支持一层回复与软删除。

    parent_id 为空即主楼；回复统一挂主楼（二层以上扁平化，避免无限嵌套）。
    is_teacher 为发帖时快照：教师身份不随角色变更影响历史展示。
    软删除保留楼层结构，内容替换为「该评论已删除」。
    """
    __tablename__ = 'homework_comment'

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey('homework.id'),
                            nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=True, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('homework_comment.id'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False, default='')
    is_teacher = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    deleted_at = db.Column(UTCDateTime)

    user = db.relationship('User', foreign_keys=[user_id])
    question = db.relationship('Question')
    replies = db.relationship('HomeworkComment', backref=db.backref('parent', remote_side=[id]),
                              lazy=True, foreign_keys=[parent_id])

    @property
    def deleted(self):
        return self.deleted_at is not None

    def to_dict(self, current_user_id=None, for_teacher=False):
        d = {'id': self.id, 'homework_id': self.homework_id,
             'question_id': self.question_id, 'parent_id': self.parent_id,
             'user_id': self.user_id,
             'username': self.user.username if self.user else '已注销用户',
             'is_teacher': bool(self.is_teacher),
             'content': '该评论已删除' if self.deleted else (self.content or ''),
             'deleted': self.deleted,
             'mine': bool(current_user_id and self.user_id == current_user_id),
             'created_at': iso_local(self.created_at)}
        if for_teacher:
            d['can_moderate'] = True
        return d


class PeerReviewStatusEnum:
    PENDING = 'pending'      # 待互评
    SUBMITTED = 'submitted'  # 已提交互评

    ALL = (PENDING, SUBMITTED)


class PeerReviewAuditEnum:
    """v5.9 教师审核：未审核 / 采纳（计入加权分）/ 驳回（不计入）。"""
    PENDING = 'pending'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'

    ALL = (PENDING, ACCEPTED, REJECTED)


class HomeworkPeerReview(db.Model):
    """生生互评（v5.5，v5.9 深度互评）：教师按份分配，学生在匿名视角下打分与评语。

    score 为维度加权后的 0-100 百分制总分，scores_json 保存各维度原始分；
    默认仅作形成性参考，不写入 HomeworkSubmission.total_score。
    教师可审核采纳/驳回，采纳后的均分按作业 peer_review_weight 生成
    「互评加权分」独立字段（peer_review_received），仍不改官方 total_score。
    匿名规则：仅被评学生不可见 reviewer 身份；教师端完整可见。
    """
    __tablename__ = 'homework_peer_review'
    __table_args__ = (db.UniqueConstraint('submission_id', 'reviewer_id',
                                          name='uq_hw_peer_review_sub_reviewer'),)

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey('homework.id'),
                            nullable=False, index=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('homework_submission.id'),
                              nullable=False, index=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=PeerReviewStatusEnum.PENDING)
    score = db.Column(db.Float)                 # 0-100 百分制（维度加权总分）
    scores_json = db.Column(JSONType)           # v5.9 各维度原始分 {accuracy: 90, ...}
    comment = db.Column(db.Text)                # 互评评语
    audit_status = db.Column(db.String(20), nullable=False,
                             default=PeerReviewAuditEnum.PENDING)  # v5.9 教师审核
    teacher_comment = db.Column(db.Text)        # v5.9 教师审核意见
    audited_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    audited_at = db.Column(UTCDateTime)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    submitted_at = db.Column(UTCDateTime)

    reviewer = db.relationship('User', foreign_keys=[reviewer_id])
    auditor = db.relationship('User', foreign_keys=[audited_by])
    submission = db.relationship('HomeworkSubmission')

    def to_dict(self, for_teacher=False):
        d = {'id': self.id, 'homework_id': self.homework_id,
             'submission_id': self.submission_id, 'reviewer_id': self.reviewer_id,
             'status': self.status, 'score': self.score,
             'scores': self.scores_json or {},
             'audit_status': self.audit_status or PeerReviewAuditEnum.PENDING,
             'teacher_comment': self.teacher_comment or '',
             'comment': self.comment or '',
             'created_at': iso_local(self.created_at),
             'submitted_at': iso_local(self.submitted_at) if self.submitted_at else None,
             'audited_at': iso_local(self.audited_at) if self.audited_at else None}
        return d


# ═══════════════════════ v5.7 小组作业 ═══════════════════════

class HomeworkGroup(db.Model):
    """小组作业的小组：一份小组作业可含多个小组，每组一份提交。"""
    __tablename__ = 'homework_group'

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey('homework.id'),
                            nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, default='小组')
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    members = db.relationship('HomeworkGroupMember', backref='group', lazy=True,
                              cascade='all, delete-orphan')

    def to_dict(self, include_members=True):
        d = {'id': self.id, 'homework_id': self.homework_id, 'name': self.name,
             'member_count': len(self.members)}
        if include_members:
            d['members'] = [{'student_id': m.student_id,
                             'username': m.student.username if m.student else None}
                            for m in self.members]
        return d


class HomeworkGroupMember(db.Model):
    """小组成员（student 只属于该作业下的一个小组）。"""
    __tablename__ = 'homework_group_member'
    __table_args__ = (db.UniqueConstraint('group_id', 'student_id',
                                          name='uq_hw_group_member_group_student'),)

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('homework_group.id'),
                         nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'),
                           nullable=False, index=True)
    joined_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    student = db.relationship('User')


# ═══════════════════════ v5.8 作业模板与系列化 ═══════════════════════

class HomeworkSeriesStatusEnum:
    DRAFT = 'draft'        # 草稿：未开始生成
    ACTIVE = 'active'      # 进行中：按计划自动生成
    COMPLETED = 'completed'  # 已完成：全部生成完毕
    PAUSED = 'paused'      # 暂停

    ALL = (DRAFT, ACTIVE, COMPLETED, PAUSED)


class HomeworkTemplate(db.Model):
    """作业模板（v5.8）：定义题集式作业的抽题规则与默认设置，供系列化批量生成复用。

    config_json 结构：
      filters: {major_id, course_id?, chapter_id?, difficulty?, types:[...]}
      count: 抽取题数
      default_score: 每题默认分值
      distribution: [{difficulty, count}] 难度分布（可选，覆盖 count）
    settings_json 结构：{allow_late, allow_resubmit, remind_before, pass_score, deadline_hours}
    """
    __tablename__ = 'homework_template'

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default='')
    config_json = db.Column(JSONType, nullable=False, default=dict)
    settings_json = db.Column(JSONType, nullable=False, default=dict)
    roster_json = db.Column(JSONType)            # 默认发布名单 [student_id]
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    teacher = db.relationship('User', foreign_keys=[teacher_id])

    def to_dict(self):
        return {'id': self.id, 'teacher_id': self.teacher_id,
                'title': self.title, 'description': self.description or '',
                'config': self.config_json or {}, 'settings': self.settings_json or {},
                'roster': self.roster_json or [],
                'created_at': iso_local(self.created_at),
                'updated_at': iso_local(self.updated_at)}


class HomeworkSeries(db.Model):
    """作业系列（v5.8）：从模板按计划自动生成多份作业（如周练每日一份）。

    生成逻辑：第 n 份（n 从 0 起）计划发布时间 = start_at + n * interval_hours；
    scheduler tick 扫描已到期未生成的，逐份生成并发布，generated_count 累加。
    """
    __tablename__ = 'homework_series'

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey('homework_template.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default='')
    start_at = db.Column(UTCDateTime, nullable=False)        # 第一份发布时间
    interval_hours = db.Column(db.Integer, nullable=False, default=24)  # 每份间隔小时
    count = db.Column(db.Integer, nullable=False, default=5)            # 总份数
    generated_count = db.Column(db.Integer, nullable=False, default=0)  # 已生成份数
    status = db.Column(db.String(20), nullable=False, default=HomeworkSeriesStatusEnum.DRAFT)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    teacher = db.relationship('User', foreign_keys=[teacher_id])
    template = db.relationship('HomeworkTemplate', foreign_keys=[template_id])
    homeworks = db.relationship('Homework', foreign_keys=[Homework.series_id],
                                backref='series_obj', lazy=True)

    def planned_at(self, n):
        """第 n 份（0-based）的计划发布时间。"""
        from datetime import timedelta
        return self.start_at + timedelta(hours=self.interval_hours * n)

    def to_dict(self, include_homeworks=False):
        d = {'id': self.id, 'teacher_id': self.teacher_id,
             'template_id': self.template_id,
             'template_title': self.template.title if self.template else '',
             'title': self.title, 'description': self.description or '',
             'start_at': iso_local(self.start_at),
             'interval_hours': self.interval_hours, 'count': self.count,
             'generated_count': self.generated_count, 'status': self.status,
             'created_at': iso_local(self.created_at)}
        if include_homeworks:
            d['homeworks'] = [{'id': h.id, 'title': h.title, 'status': h.status,
                               'published_at': iso_local(h.published_at) if h.published_at else None}
                              for h in sorted(self.homeworks, key=lambda x: x.published_at or x.created_at)]
        return d

