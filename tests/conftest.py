# -*- coding: utf-8 -*-
"""pytest 共享夹具：独立内存库，绝不触碰 instance/exam_system.db。

db 为 database/__init__.py 的惰性 SQLAlchemy 实例，测试内 init_app 到
一次性 Flask app 上；StaticPool 保证内存库在多线程/多 session 下同一连接。
"""
import os
import sys
import tempfile

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402

# 真实应用隔离：import app 时 db.init_app 会把引擎绑到 config.py 的绝对路径真库，
# HTTP 层 E2E（test_http_e2e）要用 test_client 打真路由，必须在 import 前
# 把类属性改指会话级临时库，测试进程物理上不触碰 instance/exam_system.db。
# （既有函数层测试走空壳 app 内存库，与本临时库互不相干）
import config as _config_mod  # noqa: E402

_TMP = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_TMP.close()
_config_mod.Config.SQLALCHEMY_DATABASE_URI = \
    'sqlite:///' + _TMP.name.replace('\\', '/')

import app as _prod_app  # noqa: E402,F401  先装配全局 limiter/csrf（api 路由 import 期装饰器依赖），不触发 bootstrap/建库

# ─────────────── 上传目录隔离（v5.32）───────────────
# 上面的临时库只隔开了数据：上传链路把文件写在库**外**的项目根 uploads/，
# 测试结束 stored_name 随临时库销毁、磁盘文件留下 → 每跑一次全量测试就稳定
# 制造约 60 个孤儿（v5.26.1 清 828、v5.28.1 清 54 后又积 63）。
# 各业务模块是 import 期就把 UPLOAD_DIR 绑成自己的模块属性（且按位置传给
# save_upload），所以只改 utils.uploads.UPLOAD_DIR 完全无效，必须逐个属性替换。
# 新增上传落盘点时同步补这张表，并由下面的差集断言兑底（漏了就变红）。
_UPLOAD_BINDINGS = (
    ('utils.uploads', 'UPLOAD_DIR'),
    ('api.learning_routes', '_UPLOAD_DIR'),
    ('bounty.routes', '_UPLOAD_DIR'),
    ('competition.routes', '_UPLOAD_DIR'),
    ('dsci.routes', '_UPLOAD_DIR'),
    ('homework.routes', '_UPLOAD_DIR'),
    ('api.question_routes', 'UPLOAD_FOLDER'),
    ('app', 'UPLOAD_FOLDER'),          # /uploads/<path> 只读服务路由，一并隔开避免读到真实用户文件
)


def _real_upload_dir():
    import utils.uploads as _u
    return _u.UPLOAD_DIR


@pytest.fixture(scope='session', autouse=True)
def isolate_upload_dir(tmp_path_factory):
    """会话级：把全部上传落盘目录改指 pytest 临时目录，并断言真实 uploads/ 零新增。

    差集断言同时是一道隔离回归门：生产服务在线时测试不应往 uploads/ 写任何文件，
    出现新增即说明有新的上传点没被 _UPLOAD_BINDINGS 覆盖。
    """
    import importlib
    real_dir = _real_upload_dir()
    before = set(os.listdir(real_dir)) if os.path.isdir(real_dir) else set()

    sandbox = str(tmp_path_factory.mktemp('uploads'))
    patched = []
    for mod_name, attr in _UPLOAD_BINDINGS:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, attr) and getattr(mod, attr) != sandbox:
            patched.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, sandbox)
    try:
        yield sandbox
    finally:
        for mod, attr, origin in patched:
            setattr(mod, attr, origin)
        after = set(os.listdir(real_dir)) if os.path.isdir(real_dir) else set()
        leaked = sorted(after - before)
        assert not leaked, (
            '测试运行期间向真实 uploads/ 写了 %d 个文件（上传目录隔离失效，'
            '请把新落盘点补进 tests/conftest.py 的 _UPLOAD_BINDINGS）：%s'
            % (len(leaked), ', '.join(leaked[:10]) + ('...' if len(leaked) > 10 else ''))
        )


@pytest.fixture()
def app():
    a = Flask('exam_test')
    a.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    a.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    a.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    a.config['TESTING'] = True
    db.init_app(a)
    with a.app_context():
        # 注册全部模型元数据：跨包外键（question/user 等）需先 import 再建表
        import database.models        # noqa: F401
        import competition.models     # noqa: F401
        import bounty.models          # noqa: F401
        import ledger.models          # noqa: F401
        import dsci.models            # noqa: F401
        import homework.models        # noqa: F401
        db.create_all()
        yield a
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def user_factory(app):
    """创建带真实 id 的用户行（测试结束随内存库销毁）"""
    from database.models import User

    def make(username, role='student'):
        u = User(username=username, role=role)
        u.set_password('test-pw')
        db.session.add(u)
        db.session.commit()
        return u

    return make
