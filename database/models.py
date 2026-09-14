from database import db
from database.types import UTCDateTime, JSONType
from utils.timeutil import utcnow

class RoleEnum:
    TEACHER = "teacher"
    STUDENT = "student"

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
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

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
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        while Exam.query.filter_by(invitation_code=code).first():
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        self.invitation_code = code

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
    """学习计划：按专业/章节设定目标题数与完成进度"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    target_count = db.Column(db.Integer, nullable=False, default=50)  # 目标练习题数
    completed_count = db.Column(db.Integer, nullable=False, default=0)
    major_id = db.Column(db.Integer, db.ForeignKey('major.id'))
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'))
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default='active')  # active / completed / paused
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='study_plans', lazy=True)


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