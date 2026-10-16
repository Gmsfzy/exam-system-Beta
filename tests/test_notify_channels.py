# -*- coding: utf-8 -*-
"""通知外部渠道旁路投递回归门：默认关闭、事件白名单、载荷构建、投递路由。

网络发送（SMTP/HTTP）全部打桩，测试不触真实外网。
"""
import pytest

from database import db
from database.models import User
from utils import notify_channels as nc


class _SyncThread:
    """替身线程：start() 同步执行 target，便于断言投递结果。"""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


@pytest.fixture()
def spy(monkeypatch):
    """拦截真实发送器，记录调用参数。"""
    emails, hooks = [], []
    monkeypatch.setattr(nc, '_send_email',
                        lambda to, subject, text, cfg: emails.append((to, subject, text)))
    monkeypatch.setattr(nc, '_send_webhook', lambda text, cfg: hooks.append(text))
    monkeypatch.setattr(nc.threading, 'Thread', _SyncThread)
    return emails, hooks


def _seed_user(username, email):
    u = User(username=username, role='student', email=email)
    u.set_password('pw')
    db.session.add(u)
    db.session.commit()
    return u


def test_should_dispatch_disabled(app):
    app.config['NOTIFY_EXTERNAL_ENABLED'] = False
    assert nc.should_dispatch('result') is False


def test_should_dispatch_default_whitelist(app):
    app.config['NOTIFY_EXTERNAL_ENABLED'] = True
    app.config['NOTIFY_EXTERNAL_RELATED_TYPES'] = 'result'
    assert nc.should_dispatch('result') is True
    # exam 不在白名单：避免「考试发布」群发刷屏
    assert nc.should_dispatch('exam') is False


def test_dispatch_noop_when_disabled(app, spy):
    _seed_user('u_off', 'off@x.com')
    app.config['NOTIFY_EXTERNAL_ENABLED'] = False
    nc.dispatch(1, '成绩已公布', '内容', 'result')
    emails, hooks = spy
    assert emails == [] and hooks == []


def test_dispatch_skips_type_not_in_whitelist(app, spy):
    u = _seed_user('u_exam', 'exam@x.com')
    app.config['NOTIFY_EXTERNAL_ENABLED'] = True
    app.config['NOTIFY_EXTERNAL_RELATED_TYPES'] = 'result'
    nc.dispatch(u.id, '新考试', '内容', 'exam')
    emails, hooks = spy
    assert emails == [] and hooks == []


def test_dispatch_routes_to_email(app, spy):
    u = _seed_user('u_res', 'res@x.com')
    app.config['NOTIFY_EXTERNAL_ENABLED'] = True
    app.config['NOTIFY_EXTERNAL_RELATED_TYPES'] = 'result'
    # 邮件通道需 smtp_host；webhook 未配置故不发
    app.config['NOTIFY_SMTP_HOST'] = 'smtp.example.com'
    app.config['NOTIFY_WEBHOOK_URL'] = ''
    nc.dispatch(u.id, '考试成绩已公布', '你的成绩为 90/100', 'result')
    emails, hooks = spy
    assert emails == [('res@x.com', '考试成绩已公布',
                       '考试成绩已公布\n你的成绩为 90/100')]
    assert hooks == []


def test_dispatch_routes_to_webhook(app, spy):
    u = _seed_user('u_hook', 'hook@x.com')
    app.config['NOTIFY_EXTERNAL_ENABLED'] = True
    app.config['NOTIFY_EXTERNAL_RELATED_TYPES'] = 'result'
    app.config['NOTIFY_SMTP_HOST'] = ''  # 无 SMTP，不发邮件
    app.config['NOTIFY_WEBHOOK_URL'] = 'https://oapi.example/robot'
    nc.dispatch(u.id, '成绩已公布', '内容', 'result')
    emails, hooks = spy
    assert emails == []
    assert hooks == ['成绩已公布\n内容']


def test_webhook_payload_builders():
    assert nc._WEBHOOK_BUILDERS['generic']('hi') == {'content': 'hi'}
    assert nc._WEBHOOK_BUILDERS['wechat']('hi') == {
        'msgtype': 'text', 'text': {'content': 'hi'}}
    assert nc._WEBHOOK_BUILDERS['dingtalk']('hi') == {
        'msgtype': 'text', 'text': {'content': 'hi'}}


def test_build_text():
    assert nc._build_text('标题', '正文') == '标题\n正文'
    assert nc._build_text('只有标题', '') == '只有标题'
