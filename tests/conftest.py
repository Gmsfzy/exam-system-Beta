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
