# -*- coding: utf-8 -*-
"""v7.25 社区微博化：私信 / 拉黑 / 举报留痕回归。"""
import pytest

from database import db


@pytest.fixture(scope='module')
def dm_app():
    import app as prod

    prod._boot_done.set()
    prod.app.config['TESTING'] = True

    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False

    with prod.app.app_context():
        import database.models  # noqa: F401
        db.create_all()
        yield prod.app
        db.session.remove()


@pytest.fixture(autouse=True)
def _reset(dm_app):
    from database.models import (
        CommunityDmAccessLog, CommunityDmMessage, CommunityDmConversation,
        CommunityUserBlock, CommunityReport, UserFollow, Notification,
    )

    with dm_app.app_context():
        CommunityDmAccessLog.query.delete()
        CommunityDmMessage.query.delete()
        CommunityReport.query.delete()
        CommunityDmConversation.query.delete()
        CommunityUserBlock.query.delete()
        UserFollow.query.delete()
        Notification.query.delete()
        db.session.commit()
    yield


@pytest.fixture()
def client(dm_app):
    return dm_app.test_client()


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


_SEQ = {'n': 0}


def _register(client, role='student'):
    _SEQ['n'] += 1
    username = f'dm{_SEQ["n"]:04d}'
    r = client.post('/api/register', json={
        'username': username, 'password': 'dm-password', 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    return body['token'], body['user']


def test_dm_flow_unread_read_and_hide(client):
    t_a, a = _register(client)
    t_b, b = _register(client)

    r = client.post('/api/community/dm/conversations',
                    json={'peer_id': b['id'], 'content': '在吗？'}, headers=_auth(t_a))
    assert r.status_code == 201, r.get_json()
    conv_id = r.get_json()['conversation']['id']

    # B 的未读与全局通知
    unread = client.get('/api/community/dm/unread-count', headers=_auth(t_b)).get_json()
    assert unread['unread'] == 1
    notes = client.get('/api/notifications', headers=_auth(t_b)).get_json()
    titles = [n['title'] for n in (notes.get('items') or notes.get('notifications') or [])]
    assert any('私信' in t for t in titles)

    # B 回复（不同发送方向，不受 1 分钟频控影响）
    r = client.post(f'/api/community/dm/conversations/{conv_id}/messages',
                    json={'content': '在的'}, headers=_auth(t_b))
    assert r.status_code == 201, r.get_json()

    # A 刚刚发过，再发触发非互关频控
    r = client.post(f'/api/community/dm/conversations/{conv_id}/messages',
                    json={'content': '再说一句'}, headers=_auth(t_a))
    assert r.status_code == 429

    # 已读清零
    r = client.put(f'/api/community/dm/conversations/{conv_id}/read', headers=_auth(t_a))
    assert r.get_json()['unread'] == 0
    msgs = client.get(f'/api/community/dm/conversations/{conv_id}/messages',
                      headers=_auth(t_a)).get_json()
    assert [m['content'] for m in msgs['items']] == ['在吗？', '在的']

    # 隐藏只影响本人
    client.delete(f'/api/community/dm/conversations/{conv_id}', headers=_auth(t_a))
    assert client.get('/api/community/dm/conversations', headers=_auth(t_a)).get_json()['items'] == []
    assert len(client.get('/api/community/dm/conversations', headers=_auth(t_b)).get_json()['items']) == 1


def test_block_prevents_dm(client):
    t_a, a = _register(client)
    t_b, b = _register(client)

    r = client.post('/api/community/dm/conversations',
                    json={'peer_id': b['id']}, headers=_auth(t_a))
    conv_id = r.get_json()['conversation']['id']

    r = client.post(f'/api/community/users/{b["id"]}/block',
                    json={'reason': '骚扰'}, headers=_auth(t_a))
    assert r.get_json()['blocked'] is True

    # A 拉黑 B：B 无法继续发
    r = client.post(f'/api/community/dm/conversations/{conv_id}/messages',
                    json={'content': '你好'}, headers=_auth(t_b))
    assert r.status_code == 403

    blocks = client.get('/api/community/dm/blocks', headers=_auth(t_a)).get_json()
    assert blocks[0]['blocked_id'] == b['id']

    client.delete(f'/api/community/users/{b["id"]}/block', headers=_auth(t_a))
    r = client.post(f'/api/community/dm/conversations/{conv_id}/messages',
                    json={'content': '你好'}, headers=_auth(t_b))
    assert r.status_code == 201


def test_dm_report_and_teacher_context(client):
    t_a, a = _register(client)
    t_b, b = _register(client)
    t_t, teacher = _register(client, role='teacher')

    r = client.post('/api/community/dm/conversations',
                    json={'peer_id': b['id'], 'content': '不当内容'}, headers=_auth(t_a))
    conv_id = r.get_json()['conversation']['id']
    msg_id = r.get_json()['message']['id']

    # B 举报私信
    r = client.post('/api/community/reports', json={
        'target_type': 'dm_message', 'target_id': msg_id, 'reason': '辱骂',
    }, headers=_auth(t_b))
    assert r.status_code == 201, r.get_json()
    report_id = r.get_json()['report']['id']

    # 普通学生不能看上下文
    r = client.get(f'/api/community/dm/conversations/{conv_id}/context?report_id={report_id}',
                   headers=_auth(t_b))
    assert r.status_code == 403

    # 教师凭举报可看，并写入留痕
    r = client.get(f'/api/community/dm/conversations/{conv_id}/context?report_id={report_id}',
                   headers=_auth(t_t))
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data['messages'][0]['content'] == '不当内容'
    assert data['access_log_id']

    from database.models import CommunityDmAccessLog
    with client.application.app_context():
        log = db.session.get(CommunityDmAccessLog, data['access_log_id'])
        assert log.admin_id == teacher['id']
        assert log.report_id == report_id
