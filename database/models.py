from database import db
from database.types import UTCDateTime, JSONType
from utils.timeutil import utcnow

class RoleEnum:
    TEACHER = "teacher"
    STUDENT = "student"
    BOT = "bot"  # 系统训练对手（快速 PK 机器人），不可登录、不参与排行/积分入账

class ExamStatusEnum:
    DRAFT = "draft"
    PUBLISHED = "published"
    ENDED = "ended"

class QuestionTypeEnum:
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_BLANK = "fill_blank"
    TRUE_FALSE = "true_false"
    SHORT_ANSWER = "short_answer"
    PROGRAMMING = "programming"       # 编程题
    APPLICATION = "application"       # 应用题
    CALCULATION = "calculation"       # 计算题

    # 主观题集合：这些题型支持教师人工评分
    SUBJECTIVE_TYPES = {SHORT_ANSWER, PROGRAMMING, APPLICATION, CALCULATION}

    @classmethod
    def is_subjective(cls, q_type: str) -> bool:
        """判断是否为需要人工评分的主观题"""
        return q_type in cls.SUBJECTIVE_TYPES

    @classmethod
    def label(cls, q_type: str) -> str:
        """返回题型的中文名称"""
        return _QUESTION_TYPE_LABELS.get(q_type, q_type)


_QUESTION_TYPE_LABELS = {
    'single_choice':   '单选题',
    'multiple_choice': '多选题',
    'fill_blank':      '填空题',
    'true_false':      '判断题',
    'short_answer':    '问答题',
    'programming':     '编程题',
    'application':     '应用题',
    'calculation':     '计算题',
}

class DifficultyEnum:
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True)  # , nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    sanctioned_at = db.Column(UTCDateTime)          # 竞技处罚时间（NULL=正常）
    sanction_reason = db.Column(db.String(200))     # 受限原因公示
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    @property
    def is_sanctioned(self):
        return self.sanctioned_at is not None

    def set_password(self, password):
        from database import bcrypt
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        from database import bcrypt
        return bcrypt.check_password_hash(self.password_hash, password)

    def is_teacher(self):
        return self.role == RoleEnum.TEACHER

    def is_student(self):
        return self.role == RoleEnum.STUDENT

class Department(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)

    majors = db.relationship('Major', backref='department', lazy=True, cascade='all, delete-orphan')

class Major(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    department_id = db.Column(db.Integer, db.ForeignKey('department.id'))

    __table_args__ = (
        db.UniqueConstraint('department_id', 'name', name='_dept_major_uc'),
    )

    courses = db.relationship('Course', backref='major', lazy=True, cascade='all, delete-orphan')
    questions = db.relationship('Question', backref='major', lazy=True)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    major_id = db.Column(db.Integer, db.ForeignKey('major.id'), nullable=False)
    description = db.Column(db.Text)
    credit = db.Column(db.Float)
    semester = db.Column(db.String(20))

    __table_args__ = (
        db.UniqueConstraint('major_id', 'name', name='_major_course_uc'),
    )

    chapters = db.relationship('Chapter', backref='course', lazy=True, cascade='all, delete-orphan')
    questions = db.relationship('Question', backref='course', lazy=True)

class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    description = db.Column(db.Text)
    order_num = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint('course_id', 'name', name='_course_chapter_uc'),
    )

    questions = db.relationship('Question', backref='chapter', lazy=True, cascade='all, delete-orphan')

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    options = db.Column(JSONType)  # JSON 选项列表
    answer = db.Column(db.Text, nullable=False)
    analysis = db.Column(db.Text)
    knowledge = db.Column(db.Text)  # 知识点标签，逗号分隔
    major_id = db.Column(db.Integer, db.ForeignKey('major.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    type = db.Column(db.String(20), nullable=False)
    difficulty = db.Column(db.String(20), nullable=False)
    source = db.Column(db.String(20), nullable=False, default='manual')  # manual/ai/past_exam
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # 创建者（历史题目为 NULL）
    is_public = db.Column(db.Boolean, nullable=False, default=False)  # 是否公开到公共题库
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    creator = db.relationship('User', backref='questions', lazy=True)

class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    start_time = db.Column(UTCDateTime, nullable=False)
    end_time = db.Column(UTCDateTime, nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # 分钟
    status = db.Column(db.String(20), nullable=False, default=ExamStatusEnum.DRAFT)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    invitation_code = db.Column(db.String(20), unique=True)
    invitation_url = db.Column(db.String(500))

    creator = db.relationship('User', backref='exams', lazy=True)
    # 删除考试时 ORM 级联清理题目配置/受邀学生/会话/成绩（依赖记录无独立存在意义）
    exam_questions = db.relationship('ExamQuestion', backref='exam', lazy=True,
                                     cascade='all, delete-orphan')
    exam_students = db.relationship('ExamStudent', backref='exam', lazy=True,
                                    cascade='all, delete-orphan')
    sessions = db.relationship('ExamSession', backref='exam', lazy=True,
                               cascade='all, delete-orphan')
    results = db.relationship('Result', backref='exam', lazy=True,
                              cascade='all, delete-orphan')

    def generate_invitation_code(self):
        import random
        import string
        # 8 位大写字母+数字（36^8 ≈ 2.82 万亿组合）；设最大重试次数防御性兜底，
        # 避免极端情况下 while 查重无限循环（正常碰撞概率可忽略）
        alphabet = string.ascii_uppercase + string.digits
        for _ in range(10):
            code = ''.join(random.choices(alphabet, k=8))
            if not Exam.query.filter_by(invitation_code=code).first():
                self.invitation_code = code
                return
        raise RuntimeError("邀请码生成连续 10 次碰撞，请重试")

    def generate_invitation_url(self, base_url):
        # Vue3 SPA 承接：学生仪表盘读取 ?join= 邀请码后调 /api/exam/join/<code> 加入
        if self.invitation_code:
            self.invitation_url = f"{base_url}student?join={self.invitation_code}"

class ExamQuestion(db.Model):
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), primary_key=True)
    score = db.Column(db.Float, nullable=False, default=1.0)
    order = db.Column(db.Integer, nullable=False)

    question = db.relationship('Question')

class ExamStudent(db.Model):
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    invited_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    student = db.relationship('User')

class ExamSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_time = db.Column(UTCDateTime)
    end_time = db.Column(UTCDateTime)
    status = db.Column(db.String(20), nullable=False, default='in_progress')
    switch_count = db.Column(db.Integer, default=0)  # 切屏次数

    student = db.relationship('User', backref='exam_sessions', lazy=True)
    answers = db.relationship('Answer', backref='session', lazy=True,
                              cascade='all, delete-orphan')

class Answer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('exam_session.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    student_answer = db.Column(db.Text)
    is_correct = db.Column(db.Boolean)
    score = db.Column(db.Float)                  # AI 评分
    manual_score = db.Column(db.Float)           # 教师人工评分（None 表示未人工评分）
    manual_comment = db.Column(db.Text)          # 教师评语
    needs_manual_grade = db.Column(db.Boolean, default=False)  # 是否需要人工评分

    @property
    def effective_score(self):
        """有效得分：有人工评分时取人工，否则取 AI"""
        return self.manual_score if self.manual_score is not None else (self.score or 0)

    @property
    def is_manual_graded(self):
        """是否已人工评分"""
        return self.manual_score is not None

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('exam.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    total_score = db.Column(db.Float, nullable=False)
    submitted_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    ai_analysis = db.Column(db.Text)

    # 同一学生同一考试只允许一条成绩记录，防止并发重复提交
    __table_args__ = (
        db.UniqueConstraint('exam_id', 'student_id', name='_result_exam_student_uc'),
    )

    student = db.relationship('User', backref='results', lazy=True)

class NotificationTypeEnum:
    SUCCESS = "success"
    WARNING = "warning"
    INFO = "info"
    ERROR = "error"

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    type = db.Column(db.String(20), nullable=False, default=NotificationTypeEnum.INFO)
    read = db.Column(db.Boolean, nullable=False, default=False)
    related_type = db.Column(db.String(20))  # exam, result, question 等
    related_id = db.Column(db.Integer)       # 关联的实体ID
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='notifications', lazy=True)


# ── 自我学习模块 ──────────────────────────────────────────────────────
class WrongAnswerRecord(db.Model):
    """错题本：记录用户答错的题目，支持自动收录（考试/竞赛/练习后）"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    # 来源：exam 考试 / competition 竞赛 / practice 自由刷题
    source_type = db.Column(db.String(20), nullable=False)
    source_id = db.Column(db.Integer)
    wrong_answer = db.Column(db.Text)
    correct_answer = db.Column(db.Text)
    # 掌握标记：用户重做改对或手动标记后变 True
    is_mastered = db.Column(db.Boolean, nullable=False, default=False)
    wrong_count = db.Column(db.Integer, nullable=False, default=1)  # 累计答错次数
    last_wrong_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    mastered_at = db.Column(UTCDateTime)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        # 同一用户同一题目保持单条，新增时累加 wrong_count
        db.UniqueConstraint('user_id', 'question_id', name='_wrong_question_uc'),
    )

    user = db.relationship('User', backref='wrong_records', lazy=True)
    question = db.relationship('Question')


class PracticeSession(db.Model):
    """自由刷题会话（不计分/不计时，纯练习）"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100))           # 练习名称（可选）
    major_id = db.Column(db.Integer, db.ForeignKey('major.id'))
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'))
    status = db.Column(db.String(20), nullable=False, default='in_progress')  # in_progress / completed
    questions_count = db.Column(db.Integer, default=0)
    correct_count = db.Column(db.Integer, default=0)
    total_time_sec = db.Column(db.Integer, default=0)
    start_time = db.Column(UTCDateTime, nullable=False, default=utcnow)
    end_time = db.Column(UTCDateTime)

    user = db.relationship('User', backref='practice_sessions', lazy=True)
    answers = db.relationship('PracticeAnswer', backref='session', lazy=True,
                              cascade='all, delete-orphan')


class PracticeAnswer(db.Model):
    """练习会话内单题作答记录"""
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('practice_session.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    student_answer = db.Column(db.Text)
    is_correct = db.Column(db.Boolean)
    time_spent_sec = db.Column(db.Integer, default=0)
    answered_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    question = db.relationship('Question')


class StudyPlan(db.Model):
    """学习计划：由多个具体任务条目组成（学知识点/看资源/刷题/自定义），勾选打卡推进"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    target_count = db.Column(db.Integer, nullable=False, default=50)  # 旧题量式字段，保留兼容（任务清单式下不再使用）
    completed_count = db.Column(db.Integer, nullable=False, default=0)
    major_id = db.Column(db.Integer, db.ForeignKey('major.id'))
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default='active')  # active / completed / paused
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='study_plans', lazy=True)
    tasks = db.relationship('StudyPlanTask', backref='plan', lazy=True,
                            cascade='all, delete-orphan', order_by='StudyPlanTask.order_num, StudyPlanTask.id')


class StudyPlanTask(db.Model):
    """学习计划任务条目：计划的最小执行单元，可勾选打卡"""
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('study_plan.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    task_type = db.Column(db.String(20), nullable=False, default='custom')
    # knowledge_point=学知识点 / resource=看资源 / practice=刷题 / custom=自定义
    knowledge_point_id = db.Column(db.Integer, db.ForeignKey('knowledge_point.id'))
    resource_id = db.Column(db.Integer, db.ForeignKey('learning_resource.id'))
    question_count = db.Column(db.Integer)               # 建议刷题数（practice 型）
    progress_count = db.Column(db.Integer, nullable=False, default=0)  # 已刷题数（practice 型自动核销累计）
    estimated_minutes = db.Column(db.Integer)            # 预计时长
    due_date = db.Column(db.Date)                        # 截止日（可空；逾期前端标红）
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/done
    done_at = db.Column(UTCDateTime)
    auto_done = db.Column(db.Boolean, nullable=False, default=False)  # 是否由系统自动核销（区别于手动打卡）
    order_num = db.Column(db.Integer, default=0)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.Index('ix_plan_task_plan', 'plan_id'),
    )

    knowledge_point = db.relationship('KnowledgePoint')
    resource = db.relationship('LearningResource')


class StudyLog(db.Model):
    """学习日志：每次考试/竞赛/练习结束后聚合写入，供学习报告查询"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    log_type = db.Column(db.String(20), nullable=False)  # exam / competition / practice
    reference_id = db.Column(db.Integer)                  # exam_id / comp_id / session_id
    total_questions = db.Column(db.Integer, default=0)
    correct_count = db.Column(db.Integer, default=0)
    score_ratio = db.Column(db.Float)                     # 正确率 0-1
    time_spent_sec = db.Column(db.Integer, default=0)
    studied_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='study_logs', lazy=True)


# ── 专业学习路径 + 知识图谱 ──────────────────────────────────────────

# 题目-知识点 多对多关联表（新功能主数据源；Question.knowledge 旧字符串字段保留只读兜底）
question_knowledge_point = db.Table(
    'question_knowledge_point',
    db.Column('question_id', db.Integer, db.ForeignKey('question.id'), primary_key=True),
    db.Column('knowledge_point_id', db.Integer, db.ForeignKey('knowledge_point.id'), primary_key=True),
)


class KnowledgePoint(db.Model):
    """知识点：结构化实体，挂到章节下，替代逗号分隔字符串作为知识点主数据源"""
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text)
    order_num = db.Column(db.Integer, default=0)          # 章内顺序
    difficulty = db.Column(db.String(20), nullable=False, default='easy')  # easy/medium/hard
    status = db.Column(db.String(20), nullable=False, default='active')    # active/deprecated（软删）
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.UniqueConstraint('chapter_id', 'name', name='_chapter_kp_uc'),
        db.Index('ix_kp_chapter', 'chapter_id'),
        db.Index('ix_kp_name', 'name'),
    )

    chapter = db.relationship('Chapter', backref='knowledge_points')
    questions = db.relationship('Question', secondary=question_knowledge_point,
                                backref='knowledge_points', lazy=True)


class KnowledgeEdge(db.Model):
    """知识点关系边：prerequisite 前置依赖 / related 关联 / derived 衍生"""
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('knowledge_point.id'), nullable=False)  # 前置/源
    target_id = db.Column(db.Integer, db.ForeignKey('knowledge_point.id'), nullable=False)  # 后继/目标
    relation_type = db.Column(db.String(20), nullable=False, default='prerequisite')
    weight = db.Column(db.Float, default=1.0)             # 关联强度，预留推荐用
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.UniqueConstraint('source_id', 'target_id', 'relation_type', name='_edge_uc'),
        db.Index('ix_edge_source', 'source_id'),
        db.Index('ix_edge_target', 'target_id'),
    )

    source = db.relationship('KnowledgePoint', foreign_keys=[source_id])
    target = db.relationship('KnowledgePoint', foreign_keys=[target_id])


class LearningPath(db.Model):
    """专业学习路径：学习者为自己规划的结构化学习路线（个人学习计划：目标+周期+节点）"""
    id = db.Column(db.Integer, primary_key=True)
    major_id = db.Column(db.Integer, db.ForeignKey('major.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    learning_goal = db.Column(db.Text)                   # 学习目标：学完后希望达到什么程度
    start_date = db.Column(db.Date)                      # 计划开始日期
    target_end_date = db.Column(db.Date)                 # 计划完成日期
    target_hours = db.Column(db.Integer)                  # 预计总学时
    difficulty = db.Column(db.String(20), default='medium')
    version = db.Column(db.String(20), nullable=False, default='v1')
    status = db.Column(db.String(20), nullable=False, default='draft')  # draft/published/archived
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = db.Column(UTCDateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        db.UniqueConstraint('major_id', 'title', 'version', name='_path_uc'),
        db.Index('ix_path_major_status', 'major_id', 'status'),
    )

    creator = db.relationship('User')
    major = db.relationship('Major', backref='learning_paths')
    nodes = db.relationship('LearningPathNode', backref='path', lazy=True,
                            cascade='all, delete-orphan', order_by='LearningPathNode.order_num')


class LearningPathNode(db.Model):
    """路径节点：路径中的一个学习步骤，挂知识点或章节（二选一）"""
    id = db.Column(db.Integer, primary_key=True)
    path_id = db.Column(db.Integer, db.ForeignKey('learning_path.id'), nullable=False)
    node_type = db.Column(db.String(20), nullable=False, default='knowledge_point')  # knowledge_point/chapter
    knowledge_point_id = db.Column(db.Integer, db.ForeignKey('knowledge_point.id'))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    order_num = db.Column(db.Integer, nullable=False, default=0)
    role = db.Column(db.String(20), nullable=False, default='core')  # core/elective/review
    estimated_minutes = db.Column(db.Integer, default=30)

    __table_args__ = (
        # 知识点与章节至少挂一个
        db.CheckConstraint('(knowledge_point_id IS NOT NULL) OR (chapter_id IS NOT NULL)',
                           name='_node_ref_check'),
        # 同一路径内顺序号唯一（重排序时先置负数临时值再落最终值）
        db.UniqueConstraint('path_id', 'order_num', name='_path_node_order_uc'),
        db.Index('ix_path_node_path', 'path_id'),
    )

    knowledge_point = db.relationship('KnowledgePoint')
    chapter = db.relationship('Chapter')


class UserPathEnrollment(db.Model):
    """用户选课：用户加入某条学习路径"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    path_id = db.Column(db.Integer, db.ForeignKey('learning_path.id'), nullable=False)
    enrolled_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    status = db.Column(db.String(20), nullable=False, default='active')  # active/completed/abandoned
    current_node_id = db.Column(db.Integer, db.ForeignKey('learning_path_node.id'))
    completed_count = db.Column(db.Integer, default=0)
    total_count = db.Column(db.Integer, default=0)        # 入学时节点总数快照
    completed_at = db.Column(UTCDateTime)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'path_id', name='_enroll_uc'),
        db.Index('ix_enroll_user', 'user_id'),
    )

    user = db.relationship('User', backref='path_enrollments')
    path = db.relationship('LearningPath', backref='enrollments')
    current_node = db.relationship('LearningPathNode')


class UserNodeProgress(db.Model):
    """用户节点进度：用户在路径节点上的学习状态（同 user+node 仅一条）"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    path_id = db.Column(db.Integer, db.ForeignKey('learning_path.id'), nullable=False)  # 冗余便于按路径聚合
    node_id = db.Column(db.Integer, db.ForeignKey('learning_path_node.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='not_started')  # not_started/in_progress/mastered/skipped
    started_at = db.Column(UTCDateTime)
    mastered_at = db.Column(UTCDateTime)
    time_spent_sec = db.Column(db.Integer, default=0)
    attempts_count = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'node_id', name='_user_node_uc'),
        db.Index('ix_unp_user_path', 'user_id', 'path_id'),
    )

    node = db.relationship('LearningPathNode', backref='user_progress')


class LearningResource(db.Model):
    """学习资源：挂在知识点或章节下的学习材料（文本/视频/练习/外链）"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    type = db.Column(db.String(20), nullable=False, default='text')  # text/video/exercise/external_link
    content = db.Column(db.Text)                          # 文本内容/嵌入代码
    url = db.Column(db.String(500))                       # 视频/外链地址
    knowledge_point_id = db.Column(db.Integer, db.ForeignKey('knowledge_point.id'))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    order_num = db.Column(db.Integer, default=0)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    knowledge_point = db.relationship('KnowledgePoint', backref='resources')


# ── 学习闭环：掌握度/笔记/小测/复习/打卡/证书 ────────────────────────

class KnowledgeMastery(db.Model):
    """知识点掌握度：答题数据驱动的 KP 级别掌握模型（存原始值，展示时按遗忘曲线衰减）"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    knowledge_point_id = db.Column(db.Integer, db.ForeignKey('knowledge_point.id'), nullable=False)
    level = db.Column(db.Float, nullable=False, default=0.0)   # 原始掌握度 0-100
    last_verified_at = db.Column(UTCDateTime, nullable=False, default=utcnow)  # 衰减锚点（最近一次验证时间）
    total_attempts = db.Column(db.Integer, nullable=False, default=0)
    total_correct = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'knowledge_point_id', name='_user_kp_mastery_uc'),
        db.Index('ix_mastery_user', 'user_id'),
    )

    user = db.relationship('User', backref='kp_masteries')
    knowledge_point = db.relationship('KnowledgePoint', backref='masteries')


class UserKpNote(db.Model):
    """个人知识笔记：每个知识点一篇总结笔记（upsert 语义，学完后沉淀为个人知识资产）"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    knowledge_point_id = db.Column(db.Integer, db.ForeignKey('knowledge_point.id'), nullable=False)
    content = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'knowledge_point_id', name='_user_kp_note_uc'),
        db.Index('ix_note_user', 'user_id'),
    )

    user = db.relationship('User', backref='kp_notes')
    knowledge_point = db.relationship('KnowledgePoint', backref='notes')


class QuizAttempt(db.Model):
    """轻量小测尝试：节点小测/路径终测共用（客观题即时判分，不走正式考试体系）"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    scope_type = db.Column(db.String(20), nullable=False)   # node / path_final
    node_id = db.Column(db.Integer, db.ForeignKey('learning_path_node.id'))
    path_id = db.Column(db.Integer, db.ForeignKey('learning_path.id'))
    question_ids = db.Column(JSONType)                       # 组卷快照 [question_id, ...]
    questions_count = db.Column(db.Integer, nullable=False, default=0)
    correct_count = db.Column(db.Integer, nullable=False, default=0)
    score_ratio = db.Column(db.Float)                        # 0-1，完成后写入
    status = db.Column(db.String(20), nullable=False, default='in_progress')  # in_progress/completed
    started_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    completed_at = db.Column(UTCDateTime)

    __table_args__ = (
        db.Index('ix_quiz_user_scope', 'user_id', 'scope_type'),
    )

    user = db.relationship('User', backref='quiz_attempts')
    node = db.relationship('LearningPathNode')
    path = db.relationship('LearningPath')
    answers = db.relationship('QuizAttemptAnswer', backref='attempt', lazy=True,
                              cascade='all, delete-orphan')


class QuizAttemptAnswer(db.Model):
    """小测单题作答"""
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('quiz_attempt.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    student_answer = db.Column(db.Text)
    is_correct = db.Column(db.Boolean)
    answered_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    question = db.relationship('Question')


class ReviewItem(db.Model):
    """间隔复习卡（简化 SM-2）：错题/衰减知识点按遗忘曲线排期，到期进入今日复习队列"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    interval_days = db.Column(db.Integer, nullable=False, default=1)
    repetitions = db.Column(db.Integer, nullable=False, default=0)   # 连续答对次数
    ease = db.Column(db.Float, nullable=False, default=2.5)          # 难度因子 1.3~2.8
    due_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/retired
    source_type = db.Column(db.String(20), nullable=False, default='wrong')  # wrong/mastery_decay
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'question_id', name='_user_review_uc'),
        db.Index('ix_review_user_due', 'user_id', 'status', 'due_at'),
    )

    user = db.relationship('User', backref='review_items')
    question = db.relationship('Question')


class StudyCheckin(db.Model):
    """学习打卡：有效学习行为（交练/核销/小测/复习）自动写入当日记录，驱动连击天数"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day = db.Column(db.Date, nullable=False)
    minutes = db.Column(db.Integer, nullable=False, default=0)   # 当日累计学习分钟数
    tasks_done = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'day', name='_user_day_checkin_uc'),
        db.Index('ix_checkin_user_day', 'user_id', 'day'),
    )

    user = db.relationship('User', backref='checkins')


class PathCertificate(db.Model):
    """路径结业证书：完成全部节点 + 终测通过（>=80%）后颁发，幂等"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    path_id = db.Column(db.Integer, db.ForeignKey('learning_path.id'), nullable=False)
    serial_no = db.Column(db.String(32), nullable=False, unique=True)
    final_score = db.Column(db.Float, nullable=False, default=0.0)  # 终测得分率 0-1
    summary = db.Column(JSONType)   # 快照：{path_title, major_name, nodes, kps, minutes, earned_date}
    earned_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'path_id', name='_user_path_cert_uc'),
    )

    user = db.relationship('User', backref='certificates')
    path = db.relationship('LearningPath', backref='certificates')


class DailyTask(db.Model):
    """每日学习任务：用户自己创建或采纳 AI 学习建议生成，按天归属展示在今日学习页"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day = db.Column(db.Date, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    source = db.Column(db.String(10), nullable=False, default='manual')  # manual=自建 ai=AI建议
    status = db.Column(db.String(10), nullable=False, default='pending')  # pending/done
    done_at = db.Column(UTCDateTime)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        db.CheckConstraint("source IN ('manual', 'ai')", name='_daily_source_ck'),
        db.CheckConstraint("status IN ('pending', 'done')", name='_daily_status_ck'),
        db.Index('ix_daily_task_user_day', 'user_id', 'day'),
    )

    user = db.relationship('User', backref='daily_tasks')