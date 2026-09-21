from database import db
from database.types import UTCDateTime, JSONType
from utils.timeutil import utcnow, iso_local


class CompetitionTypeEnum:
    TIMED = "timed"              # 限时积分赛
    PROJECT = "project"          # 作品提交型竞赛（v4.5：上传作品+教师评审）
    DS = "ds"                    # 数据科学赛（v4.11：数据集+在线运行+自动指标+公私榜）
    PK = "pk"                    # 实时对战（预留）
    QUICK_ANSWER = "quick_answer"  # 抢答赛（预留）


class CompetitionStatusEnum:
    DRAFT = "draft"
    REVIEWING = "reviewing"      # 发布待审核（v4.5 审核门禁）
    REJECTED = "rejected"        # 审核驳回，回退修改后可重提
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
    # 多轮系列赛与快速对战（迁移 0009 加列）
    series_id = db.Column(db.Integer)          # 所属 CompetitionSeries（无 FK 约束，应用层维护）
    series_round = db.Column(db.Integer)       # 系列赛中的轮次（1..N）
    is_quick = db.Column(db.Boolean, nullable=False, default=False)  # 快速 PK 隐藏题源竞赛，不在广场展示
    # 运营能力（迁移 0010 加列）：开赛提醒 + 邀请码门禁
    remind_before = db.Column(db.Integer, nullable=False, default=0)  # 开赛前 N 分钟提醒，0=关闭
    remind_sent_at = db.Column(UTCDateTime)                           # 提醒已发时间戳（NULL=未发，幂等标记）
    access_mode = db.Column(db.String(10), nullable=False, default='public')  # public | restricted
    invite_code = db.Column(db.String(16))                            # 受限竞赛邀请码（public 为 NULL）
    # v4.5 发布审核门禁与作品赛积分托管（迁移 0014 加列）
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))     # 审核人
    reviewed_at = db.Column(UTCDateTime)
    review_reason = db.Column(db.String(200))                         # 驳回理由
    prize_points = db.Column(db.Integer, nullable=False, default=0)   # 冠军奖金（积分为 0 则纯荣誉赛）
    frozen_points = db.Column(db.Integer, nullable=False, default=0)  # 发布时已从钱包冻结的托管积分
    # v4.11 数据科学赛（DS 型专用，其它类型留空；迁移 0019 加列）
    ds_metric = db.Column(db.String(20))                        # accuracy/f1_macro/rmse/mae/auc/custom
    ds_higher_is_better = db.Column(db.Boolean)                # custom 时教师显式设定；预置指标由 metrics 内置方向
    ds_id_column = db.Column(db.String(50))                    # 预测对齐主键列名
    ds_target_column = db.Column(db.String(50))                # 预测目标列名
    ds_public_ratio = db.Column(db.Float, nullable=False, default=0.3)   # 公榜占比（隐藏 1-ratio 为私榜）
    ds_daily_limit = db.Column(db.Integer, nullable=False, default=5)    # 每人每日提交上限
    ds_scorer_code = db.Column(db.Text)                        # 自定义 scorer（metric=custom 时启用）
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    creator = db.relationship('User', foreign_keys=[creator_id], backref='competitions', lazy=True)
    reviewer = db.relationship('User', foreign_keys=[reviewer_id])
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
    flagged = db.Column(db.Boolean, nullable=False, default=False)  # 公平性异常标记
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
    flagged = db.Column(db.Boolean, nullable=False, default=False)   # 反作弊：反应时异常
    flag_reason = db.Column(db.String(20))                          # 如 'fast'
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
    # 快速 PK 与 Elo / 机器人（迁移 0009 加列）
    is_bot = db.Column(db.Boolean, nullable=False, default=False)   # 对手为训练机器人
    quick = db.Column(db.Boolean, nullable=False, default=False)    # 由 /pk/quick 发起
    bot_plan = db.Column(db.Text)                                   # 机器人逐题计划 JSON：[{cq_id, will_correct, at_sec}]
    delta_challenger = db.Column(db.Integer, nullable=False, default=0)  # 本场 Elo 变化
    delta_opponent = db.Column(db.Integer, nullable=False, default=0)

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
    flagged = db.Column(db.Boolean, nullable=False, default=False)   # 反作弊：反应时异常
    flag_reason = db.Column(db.String(20))
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


# ═══════════════ 竞技内核升级（第一批）：Elo / 积分历史 / 系列赛 ═══════════════

class ArenaRating(db.Model):
    """跨赛季持久化对战等级分（Elo），独立于赛季积分，月度不清零"""
    __tablename__ = 'arena_rating'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    elo = db.Column(db.Integer, nullable=False, default=1200)
    peak_elo = db.Column(db.Integer, nullable=False, default=1200)
    games = db.Column(db.Integer, nullable=False, default=0)   # 已计入 Elo 的对战场次（定 K 值）
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    user = db.relationship('User', backref='arena_rating')

    def to_dict(self):
        return {'elo': self.elo, 'peak_elo': self.peak_elo, 'games': self.games}


class PointsHistory(db.Model):
    """竞技积分 / Elo 按天快照，用于个人主页与段位页的历史曲线（每天 upsert）"""
    __tablename__ = 'points_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    season = db.Column(db.String(7), nullable=False)     # 'YYYY-MM'
    day = db.Column(db.String(10), nullable=False)       # 'YYYY-MM-DD'
    points = db.Column(db.Integer, nullable=False, default=0)
    elo = db.Column(db.Integer, nullable=False, default=1200)
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    user = db.relationship('User', backref='points_histories')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'season', 'day', name='_points_history_uc'),
    )


class CompetitionSeries(db.Model):
    """多轮系列赛：把若干场竞赛归为一个赛季系列，按 best_n 或 sum 结算总冠军"""
    __tablename__ = 'competition_series'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    scoring_mode = db.Column(db.String(10), nullable=False, default='best_n')  # sum / best_n
    best_n = db.Column(db.Integer, nullable=False, default=0)   # scoring_mode=best_n 时取最佳 N 场，0=全部
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    creator = db.relationship('User', backref='created_series')

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'description': self.description or '',
            'scoring_mode': self.scoring_mode, 'best_n': self.best_n,
            'creator_id': self.creator_id,
            'created_at': iso_local(self.created_at),
        }


# ═══════════════ 竞技内核升级（第二批）：赛后讨论区 ═══════════════

class DiscussionPost(db.Model):
    """赛后讨论区：以竞赛为单元的帖子/回复（一层线程，回复指向顶层帖）。"""
    __tablename__ = 'discussion_post'

    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'),
                               nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('discussion_post.id'))  # 回复的顶层帖 id
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    author = db.relationship('User', backref='discussion_posts', lazy=True)
    competition = db.relationship('Competition', backref='discussions')
    parent = db.relationship('DiscussionPost', remote_side=[id],
                             backref='reply_list', lazy=True)


# ═══════════════ 竞技内核升级（第三批）：赛季分等级证书 ═══════════════

class CompetitionCertificate(db.Model):
    """赛季证书：赛季归档时按最终积分分等级颁发，幂等（一人一赛季一份）。"""
    __tablename__ = 'competition_certificate'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    season = db.Column(db.String(7), nullable=False)          # 'YYYY-MM'
    serial_no = db.Column(db.String(32), nullable=False, unique=True)
    grade = db.Column(db.String(10), nullable=False)          # gold/silver/bronze/merit
    tier = db.Column(db.String(10))                           # 最终段位快照
    rank = db.Column(db.Integer)                              # 赛季名次
    points = db.Column(db.Integer, nullable=False, default=0)
    total_players = db.Column(db.Integer, nullable=False, default=0)
    summary = db.Column(JSONType)   # {season_label, grade_label, pk_total, timed_finished, earned_date}
    earned_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    author = db.relationship('User', backref='season_certificates', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'season', name='_season_cert_uc'),
    )


# ═══════════════ v4.5 学习社区升级：赛事运营与作品赛道 ═══════════════

class CompetitionAnnouncement(db.Model):
    """赛事公告：发布后向全体参赛者广播，竞赛详情页置顶展示"""
    __tablename__ = 'competition_announcement'
    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), nullable=False, index=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False, default='')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    competition = db.relationship('Competition', backref='announcements')
    author = db.relationship('User', backref='competition_announcements')


class CompetitionResource(db.Model):
    """赛事资料包：赛题附件/参考材料，参赛者统一下载"""
    __tablename__ = 'competition_resource'
    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200), nullable=False)      # 原始文件名
    stored_name = db.Column(db.String(200), nullable=False)   # uploads 下存储名
    size = db.Column(db.Integer, nullable=False, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    competition = db.relationship('Competition', backref='resources')
    uploader = db.relationship('User', backref='competition_resources')


class CompetitionWork(db.Model):
    """作品提交（project 型竞赛）：一人一份，重复提交覆盖升版；教师评分后同分取最早提交排冠军"""
    __tablename__ = 'competition_work'
    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    description = db.Column(db.Text, nullable=False, default='')   # 作品说明
    filename = db.Column(db.String(200))                           # 作品文件（可空=仅文字说明）
    stored_name = db.Column(db.String(200))
    size = db.Column(db.Integer, nullable=False, default=0)
    version = db.Column(db.Integer, nullable=False, default=1)     # 提交次数（每次重交 +1）
    score = db.Column(db.Float)                                    # 教师评审分（NULL=未评）
    review_note = db.Column(db.Text)
    scored_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    scored_at = db.Column(UTCDateTime)
    submitted_at = db.Column(UTCDateTime, nullable=False, default=utcnow)  # 首次提交时间（同分 tiebreak）
    updated_at = db.Column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    competition = db.relationship('Competition', backref='works')
    user = db.relationship('User', foreign_keys=[user_id], backref='competition_works')
    scorer = db.relationship('User', foreign_keys=[scored_by])

    __table_args__ = (
        db.UniqueConstraint('competition_id', 'user_id', name='_comp_work_uc'),
    )