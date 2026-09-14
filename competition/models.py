from database import db
from database.types import UTCDateTime, JSONType
from utils.timeutil import utcnow, iso_local


class CompetitionTypeEnum:
    TIMED = "timed"              # 限时积分赛
    PK = "pk"                    # 实时对战（预留）
    QUICK_ANSWER = "quick_answer"  # 抢答赛（预留）


class CompetitionStatusEnum:
    DRAFT = "draft"
    PUBLISHED = "published"      # 已发布，等待开放
    ONGOING = "ongoing"          # 开放中
    ENDED = "ended"


class ParticipantStatusEnum:
    JOINED = "joined"            # 已报名未开始
    PLAYING = "playing"          # 答题中
    FINISHED = "finished"        # 已完成


class Competition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    competition_type = db.Column(db.String(20), nullable=False, default=CompetitionTypeEnum.TIMED)
    status = db.Column(db.String(20), nullable=False, default=CompetitionStatusEnum.DRAFT)
    start_time = db.Column(UTCDateTime, nullable=False)   # 开放窗口开始
    end_time = db.Column(UTCDateTime, nullable=False)     # 开放窗口结束
    duration = db.Column(db.Integer, nullable=False)      # 每人答题时长（分钟）
    draw_count = db.Column(db.Integer, nullable=False, default=0)  # 每人抽题数，0=全部
    scoring_rule = db.Column(db.Text,
                             default='{"base_ratio": 0.7, "speed_ratio": 0.3}')  # JSON
    total_score = db.Column(db.Float, nullable=False, default=0)   # 卷面总分（发布时计算）
    allow_pk = db.Column(db.Boolean, nullable=False, default=True)  # 是否允许基于本题库发起PK
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    creator = db.relationship('User', backref='competitions', lazy=True)
    questions = db.relationship('CompetitionQuestion', backref='competition',
                                lazy=True, cascade='all, delete-orphan',
                                order_by='CompetitionQuestion.order')
    participants = db.relationship('CompetitionParticipant', backref='competition',
                                   lazy=True, cascade='all, delete-orphan')

    @property
    def per_question_seconds(self):
        """每题平均时限（秒），基于全部题目，用于速度得分计算"""
        return self.per_question_seconds_for(len(self.questions))

    def per_question_seconds_for(self, question_count):
        """按实际作答题数计算每题平均时限（抽题模式下各参与者不同）"""
        if question_count <= 0 or not self.duration:
            return 60
        return int(self.duration * 60 / question_count)

    def sync_status(self):
        """根据时间窗口惰性同步竞赛状态"""
        if self.status == CompetitionStatusEnum.ENDED:
            return
        now = utcnow()
        if self.status == CompetitionStatusEnum.PUBLISHED and now >= self.start_time:
            self.status = CompetitionStatusEnum.ONGOING
        if self.status == CompetitionStatusEnum.ONGOING and now > self.end_time:
            self.status = CompetitionStatusEnum.ENDED
            self._finish_all_playing()

    def _finish_all_playing(self):
        """竞赛截止时把仍在答题的参与者按已答题目结算"""
        for p in self.participants:
            if p.status in (ParticipantStatusEnum.JOINED, ParticipantStatusEnum.PLAYING):
                p.status = ParticipantStatusEnum.FINISHED
                p.finished_at = p.finished_at or utcnow()
                if p.started_at:
                    elapsed = (p.finished_at - p.started_at).total_seconds()
                    p.used_time = int(min(elapsed, self.duration * 60))


class CompetitionQuestion(db.Model):
    """竞赛题目快照：发布后与题库解耦，保证竞赛期间公平"""
    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
    q_type = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    options = db.Column(JSONType)         # JSON 快照
    answer = db.Column(db.Text, nullable=False)
    analysis = db.Column(db.Text)
    score = db.Column(db.Float, nullable=False, default=1.0)
    order = db.Column(db.Integer, nullable=False, default=0)

    question = db.relationship('Question')

    def to_public_dict(self):
        """答题端可见字段（不含答案）"""
        return {
            'id': self.id,
            'q_type': self.q_type,
            'content': self.content,
            'options': self.options,
            'score': self.score,
            'order': self.order,
        }


class CompetitionParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=ParticipantStatusEnum.JOINED)
    score = db.Column(db.Float, nullable=False, default=0)       # 总得分（含速度加成）
    used_time = db.Column(db.Integer, nullable=False, default=0)  # 总用时（秒）
    assigned_cq_ids = db.Column(db.Text)   # 抽题防作弊：开始答题时固化的题目ID列表 JSON
    started_at = db.Column(UTCDateTime)
    finished_at = db.Column(UTCDateTime)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='competition_participants', lazy=True)
    answers = db.relationship('CompetitionAnswer', backref='participant',
                              lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('competition_id', 'user_id', name='_comp_participant_uc'),
    )

    def assigned_question_ids(self):
        """解析抽题列表；未抽题（旧数据/全量模式）返回 None 表示答全部"""
        if not self.assigned_cq_ids:
            return None
        import json
        try:
            ids = json.loads(self.assigned_cq_ids)
            return ids if isinstance(ids, list) else None
        except ValueError:
            return None


class CompetitionAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('competition_participant.id'), nullable=False)
    cq_id = db.Column(db.Integer, db.ForeignKey('competition_question.id'), nullable=False)
    answer = db.Column(db.Text)
    is_correct = db.Column(db.Boolean, default=False)
    gained_score = db.Column(db.Float, nullable=False, default=0)
    time_spent = db.Column(db.Integer, nullable=False, default=0)  # 该题用时（秒）
    answered_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    cq = db.relationship('CompetitionQuestion', backref='answers', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('participant_id', 'cq_id', name='_comp_answer_uc'),
    )


class PkBattleStatusEnum:
    WAITING = "waiting"      # 等待对手
    PLAYING = "playing"      # 对战中
    FINISHED = "finished"    # 已结束
    CANCELLED = "cancelled"  # 已取消


class PkBattle(db.Model):
    """1v1 实时对战：以某个已发布竞赛的题库为题源"""
    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), nullable=False)
    challenger_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    opponent_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), nullable=False, default=PkBattleStatusEnum.WAITING)
    challenger_score = db.Column(db.Float, nullable=False, default=0)
    opponent_score = db.Column(db.Float, nullable=False, default=0)
    challenger_answered = db.Column(db.Integer, nullable=False, default=0)
    opponent_answered = db.Column(db.Integer, nullable=False, default=0)
    challenger_finished_at = db.Column(UTCDateTime)
    opponent_finished_at = db.Column(UTCDateTime)
    winner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    started_at = db.Column(UTCDateTime)
    finished_at = db.Column(UTCDateTime)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    competition = db.relationship('Competition', backref='pk_battles')
    challenger = db.relationship('User', foreign_keys=[challenger_id], backref='pk_as_challenger')
    opponent = db.relationship('User', foreign_keys=[opponent_id], backref='pk_as_opponent')
    winner = db.relationship('User', foreign_keys=[winner_id])

    def to_dict(self, include_players=True):
        data = {
            'id': self.id,
            'competition_id': self.competition_id,
            'status': self.status,
            'challenger_score': self.challenger_score,
            'opponent_score': self.opponent_score,
            'challenger_answered': self.challenger_answered,
            'opponent_answered': self.opponent_answered,
            'winner_id': self.winner_id,
            'started_at': iso_local(self.started_at),
            'finished_at': iso_local(self.finished_at),
        }
        if include_players:
            data.update({
                'challenger': self.challenger.username if self.challenger else None,
                'challenger_id': self.challenger_id,
                'opponent': self.opponent.username if self.opponent else None,
                'opponent_id': self.opponent_id,
            })
        return data


class PkAnswer(db.Model):
    """PK 对战逐题作答记录（与竞赛成绩互不影响）"""
    id = db.Column(db.Integer, primary_key=True)
    battle_id = db.Column(db.Integer, db.ForeignKey('pk_battle.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    cq_id = db.Column(db.Integer, db.ForeignKey('competition_question.id'), nullable=False)
    answer = db.Column(db.Text)
    is_correct = db.Column(db.Boolean, default=False)
    gained_score = db.Column(db.Float, nullable=False, default=0)
    time_spent = db.Column(db.Integer, nullable=False, default=0)
    answered_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    battle = db.relationship('PkBattle', backref='answers')
    cq = db.relationship('CompetitionQuestion')

    __table_args__ = (
        db.UniqueConstraint('battle_id', 'player_id', 'cq_id', name='_pk_answer_uc'),
    )


# ═══════════════ 竞技化三期：积分段位 / 赛季 / 勋章 / 战队 ═══════════════

class UserPointsProfile(db.Model):
    """用户竞技档案：按自然月赛季一行，积分驱动段位"""
    __tablename__ = 'user_points_profile'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    season = db.Column(db.String(7), nullable=False)          # 'YYYY-MM'
    points = db.Column(db.Integer, nullable=False, default=0)
    pk_win = db.Column(db.Integer, nullable=False, default=0)
    pk_lose = db.Column(db.Integer, nullable=False, default=0)
    pk_draw = db.Column(db.Integer, nullable=False, default=0)
    streak = db.Column(db.Integer, nullable=False, default=0)      # 当前 PK 连胜
    max_streak = db.Column(db.Integer, nullable=False, default=0)  # 赛季最高连胜
    timed_finished = db.Column(db.Integer, nullable=False, default=0)  # 完赛限时赛场次
    last_played_at = db.Column(UTCDateTime)                   # 同分排名 tiebreak
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow,
                           onupdate=utcnow)

    user = db.relationship('User', backref='points_profiles')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'season', name='_profile_season_uc'),
    )

    def to_dict(self):
        return {
            'season': self.season,
            'points': self.points,
            'pk_win': self.pk_win,
            'pk_lose': self.pk_lose,
            'pk_draw': self.pk_draw,
            'streak': self.streak,
            'max_streak': self.max_streak,
            'timed_finished': self.timed_finished,
        }


class SeasonMeta(db.Model):
    """赛季元信息（归档标记）"""
    __tablename__ = 'season_meta'

    id = db.Column(db.Integer, primary_key=True)
    season = db.Column(db.String(7), nullable=False, unique=True)
    archived = db.Column(db.Boolean, nullable=False, default=False)
    archived_at = db.Column(UTCDateTime)


class SeasonArchive(db.Model):
    """赛季归档快照：赛季结束时的全校排名"""
    __tablename__ = 'season_archive'

    id = db.Column(db.Integer, primary_key=True)
    season = db.Column(db.String(7), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rank = db.Column(db.Integer, nullable=False)
    points = db.Column(db.Integer, nullable=False)
    tier = db.Column(db.String(10), nullable=False)
    pk_win = db.Column(db.Integer, nullable=False, default=0)
    pk_total = db.Column(db.Integer, nullable=False, default=0)
    timed_finished = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='season_archives')

    __table_args__ = (
        db.UniqueConstraint('season', 'user_id', name='_season_archive_uc'),
    )


class UserBadge(db.Model):
    """勋章发放记录；勋章定义见 gamification.BADGE_DEFS（代码常量）"""
    __tablename__ = 'user_badge'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    badge_code = db.Column(db.String(50), nullable=False)
    season = db.Column(db.String(7), nullable=False, default='')  # 非赛季勋章用空串
    related_id = db.Column(db.Integer)
    granted_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='badges')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'badge_code', 'season', name='_user_badge_uc'),
    )


class Team(db.Model):
    """固定战队：战队积分 = 队员当前赛季竞技积分之和（实时计算）"""
    __tablename__ = 'team'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text)
    captain_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    captain = db.relationship('User', foreign_keys=[captain_id], backref='captained_teams')
    members = db.relationship('TeamMember', backref='team',
                              lazy=True, cascade='all, delete-orphan')


class TeamMember(db.Model):
    __tablename__ = 'team_member'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(10), nullable=False, default='member')  # captain / member
    joined_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='team_memberships')

    __table_args__ = (
        db.UniqueConstraint('user_id', name='_team_member_one_uc'),  # 一人同时只属一队
    )