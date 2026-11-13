# -*- coding: utf-8 -*-
"""AI 出题完成站内通知回归（HTTP 层，真实 app + test_client）。

覆盖：
  POST /api/ai/generate 成功 → 给操作教师落一条 success 通知
  （related_type='question'，前端点击直达题库页）
  生成失败（AI 服务异常）→ 不发通知，避免误导
  通知自身异常 → 仍返 200，不把已入库误报成失败
  非教师 → 403 且不发通知

说明：AI 外呼以 monkeypatch 替身，只验证通知装配链路；
复用 conftest 已改指的临时库，绝不触碰 instance 真库。
"""
import pytest

from database import db


@pytest.fixture(scope='module')
def ai_app():
    """真实 app 单例：跳过 bootstrap、关闭限流、建全表。"""
    import app as prod

    prod._boot_done.set()
    prod.app.config['TESTING'] = True

    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False

    with prod.app.app_context():
        import database.models      # noqa: F401
        import competition.models   # noqa: F401
        import bounty.models        # noqa: F401
        import ledger.models        # noqa: F401
        import dsci.models          # noqa: F401
        import homework.models      # noqa: F401
        db.create_all()
        yield prod.app
        db.session.remove()


@pytest.fixture()
def client(ai_app):
    return ai_app.test_client()


def _register(client, username, role):
    r = client.post('/api/register', json={'username': username,
                                           'password': 'pw-123456', 'role': role})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['token']


def _notifications(user_id):
    from database.models import Notification
    return Notification.query.filter_by(user_id=user_id).all()


class TestAiGenerateNotification:
    def _payload(self):
        return {'major_name': '软件工程', 'type': 'single_choice',
                'difficulty': 'easy', 'count': 3, 'description': '链表基本操作'}

    def test_success_creates_notification(self, ai_app, client, monkeypatch):
        token = _register(client, 'ai_notify_tea', 'teacher')

        import api.ai_routes as ai_mod
        fake = [object() for _ in range(3)]
        monkeypatch.setattr(ai_mod, 'ai_generate_questions',
                            lambda *a, **kw: fake)

        r = client.post('/api/ai/generate', json=self._payload(),
                        headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['count'] == 3

        with ai_app.app_context():
            from database.models import User
            tea = User.query.filter_by(username='ai_notify_tea').first()
            notes = _notifications(tea.id)
            assert len(notes) == 1
            n = notes[0]
            assert n.type == 'success'
            assert n.related_type == 'question'
            assert '3' in n.title and '3' in n.content
            assert '单选题' in n.content and '简单' in n.content

    def test_failure_no_notification(self, ai_app, client, monkeypatch):
        token = _register(client, 'ai_notify_tea2', 'teacher')

        import api.ai_routes as ai_mod

        def boom(*a, **kw):
            raise RuntimeError('AI 服务不可用')
        monkeypatch.setattr(ai_mod, 'ai_generate_questions', boom)

        r = client.post('/api/ai/generate', json=self._payload(),
                        headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 500

        with ai_app.app_context():
            from database.models import User
            tea = User.query.filter_by(username='ai_notify_tea2').first()
            assert _notifications(tea.id) == []

    def test_notification_error_does_not_mask_success(self, ai_app, client, monkeypatch):
        """通知是非关键路径：落库报错也不能把「题已入库」误报成「生成失败」。"""
        token = _register(client, 'ai_notify_tea3', 'teacher')

        import api.ai_routes as ai_mod
        monkeypatch.setattr(ai_mod, 'ai_generate_questions',
                            lambda *a, **kw: [object() for _ in range(2)])

        def boom(*a, **kw):
            raise RuntimeError('通知表写入失败')
        monkeypatch.setattr(ai_mod, 'create_notification', boom)

        r = client.post('/api/ai/generate', json=self._payload(),
                        headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['count'] == 2

    def test_student_denied_no_notification(self, ai_app, client):
        token = _register(client, 'ai_notify_stu', 'student')
        r = client.post('/api/ai/generate', json=self._payload(),
                        headers={'Authorization': f'Bearer {token}'})
        assert r.status_code == 403

        with ai_app.app_context():
            from database.models import User
            stu = User.query.filter_by(username='ai_notify_stu').first()
            assert _notifications(stu.id) == []
