# -*- coding: utf-8 -*-
"""数据科学竞赛数据模型（v4.11）。

全部经由 competition.routes / dsci.routes 读写，不旁路改 ledger；
gold（隐藏答案）文件 is_downloadable=False，任何下载端点均拒绝，仅供评分器读取。
"""
from database import db
from database.types import UTCDateTime
from utils.timeutil import utcnow, iso_local


class DatasetRole:
    """数据集文件角色。train/test/sample 对参赛者可见可下载；gold 为隐藏答案。"""
    TRAIN = 'train'
    TEST = 'test'
    GOLD = 'gold'
    SAMPLE = 'sample'
    VISIBLE = (TRAIN, TEST, SAMPLE)   # 可下载角色
    ALL = (TRAIN, TEST, GOLD, SAMPLE)


class Dataset(db.Model):
    """数据集：一组带角色的文件容器，绑定到某场 DS 竞赛（competition_id 可空以便日后跨赛复用）。"""
    __tablename__ = 'dataset'

    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default='')
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    competition = db.relationship('Competition', backref=db.backref('datasets', lazy=True))
    owner = db.relationship('User', foreign_keys=[owner_id], backref='datasets')
    files = db.relationship('DatasetFile', backref='dataset', lazy=True,
                            cascade='all, delete-orphan')

    def to_dict(self):
        return {'id': self.id, 'competition_id': self.competition_id,
                'name': self.name, 'description': self.description or '',
                'owner_id': self.owner_id, 'version': self.version,
                'created_at': iso_local(self.created_at),
                'files': [f.to_dict() for f in self.files]}


class DatasetFile(db.Model):
    """数据集文件：真实落盘 uploads/，UUID 存储名不可枚举。"""
    __tablename__ = 'dataset_file'

    id = db.Column(db.Integer, primary_key=True)
    dataset_id = db.Column(db.Integer, db.ForeignKey('dataset.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)            # DatasetRole
    filename = db.Column(db.String(200), nullable=False)       # 原始文件名
    stored_name = db.Column(db.String(200), nullable=False)    # uploads 下存储名
    size = db.Column(db.Integer, nullable=False, default=0)
    is_downloadable = db.Column(db.Boolean, nullable=False, default=True)  # gold=False
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    uploader = db.relationship('User', foreign_keys=[uploaded_by])

    def to_dict(self, for_teacher=False):
        d = {'id': self.id, 'dataset_id': self.dataset_id, 'role': self.role,
             'filename': self.filename, 'size': self.size or 0,
             'is_downloadable': bool(self.is_downloadable),
             'created_at': iso_local(self.created_at)}
        # gold 文件名对学生隐藏，避免泄露列结构
        if not for_teacher and self.role == DatasetRole.GOLD:
            d['filename'] = '（隐藏答案，不可见）'
            d['is_downloadable'] = False
        return d


class DsSubmission(db.Model):
    """预测提交：一次评分记录。公榜分实时可见，私榜分结束前仅教师可见。"""
    __tablename__ = 'ds_submission'

    STATUS_PENDING = 'pending'
    STATUS_SCORED = 'scored'
    STATUS_ERROR = 'error'

    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False, default='file')   # file / notebook
    filename = db.Column(db.String(200))
    stored_name = db.Column(db.String(200), nullable=False)           # 预测 csv 落盘名
    public_score = db.Column(db.Float)                                # 公榜分（NULL=未评分）
    private_score = db.Column(db.Float)                               # 私榜分（隐藏比例）
    status = db.Column(db.String(10), nullable=False, default=STATUS_PENDING)
    error_msg = db.Column(db.String(300))
    version = db.Column(db.Integer, nullable=False, default=1)        # 第 N 次提交
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)
    scored_at = db.Column(UTCDateTime)

    competition = db.relationship('Competition', backref=db.backref('ds_submissions', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id], backref='ds_submissions')

    def to_dict(self, with_private=False, with_user=False):
        d = {'id': self.id, 'competition_id': self.competition_id,
             'user_id': self.user_id, 'kind': self.kind,
             'filename': self.filename, 'version': self.version,
             'public_score': self.public_score, 'status': self.status,
             'error_msg': self.error_msg,
             'created_at': iso_local(self.created_at),
             'scored_at': iso_local(self.scored_at) if self.scored_at else None}
        if with_private:
            d['private_score'] = self.private_score
        if with_user and self.user:
            d['username'] = self.user.username
        return d


class DsNotebookRun(db.Model):
    """在线编写运行留痕：单脚本一次执行的代码与输出，供回看与"用运行结果提交"。"""
    __tablename__ = 'ds_notebook_run'

    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competition.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    code = db.Column(db.Text, nullable=False, default='')
    stdout = db.Column(db.Text, nullable=False, default='')
    stderr = db.Column(db.Text, nullable=False, default='')
    exit_code = db.Column(db.Integer)
    timed_out = db.Column(db.Boolean, nullable=False, default=False)
    rejected = db.Column(db.String(200))                             # 静态拒绝原因（非空=未执行）
    produced_submission = db.Column(db.Text)                         # 运行产出的 submission.csv 文本（可空）
    created_at = db.Column(UTCDateTime, nullable=False, default=utcnow)

    competition = db.relationship('Competition', backref=db.backref('ds_runs', lazy=True))
    user = db.relationship('User', foreign_keys=[user_id], backref='ds_runs')
