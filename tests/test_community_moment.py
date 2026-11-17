# -*- coding: utf-8 -*-
"""v7.25 社区微博化：动态（moment）HTTP 层回归。

覆盖：发布/列表/详情、501 字拒绝、点赞幂等、评论通知、收藏、
转发引用快照与转发-转发拒绝、匿名不可转发、关注流、可见范围、话题上限。
"""
import pytest

from database import db


@pytest.fixture(scope='module')
def comm_app():
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
def _reset(comm_app):
    from database.models import (
        CommunityReport, CommunityNotification, CommunityMomentFavorite,
        CommunityLike, CommunityMomentTopic, CommunityMomentComment,
        CommunityMoment, CommunityTopic, UserFollow,
    )
    from utils.redis_cache import delete_pattern

    with comm_app.app_context():
        CommunityReport.query.delete()
        CommunityNotification.query.delete()
        CommunityMomentFavorite.query.delete()
        CommunityLike.query.delete()
        CommunityMomentTopic.query.delete()
        CommunityMomentComment.query.delete()
        CommunityMoment.query.delete()
        CommunityTopic.query.delete()
        UserFollow.query.delete()
        db.session.commit()
    delete_pattern('community:like:*')
    yield


@pytest.fixture()
def client(comm_app):
    return comm_app.test_client()


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


_SEQ = {'n': 0}


def _register(client, role='student', prefix='mom'):
    _SEQ['n'] += 1
    username = f'{prefix}{_SEQ["n"]:04d}'
    r = client.post('/api/register', json={
        'username': username, 'password': 'moment-pw', 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    return body['token'], body['user']


def _post_moment(client, token, content='第一条动态', **kw):
    payload = {'content': content}
    payload.update(kw)
    r = client.post('/api/community/moments', json=payload, headers=_auth(token))
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def test_create_feed_detail_and_length_guard(client):
    t1, u1 = _register(client)

    m = _post_moment(client, t1, content='你好，社区', topics=['数学', '数学'])
    assert m['content'] == '你好，社区'
    assert [t['name'] for t in m['topics']] == ['数学']

    feed = client.get('/api/community/feed').get_json()
    assert [x['id'] for x in feed['items']] == [m['id']]
    assert feed['items'][0]['display_username'] == u1['username']

    detail = client.get(f"/api/community/moments/{m['id']}").get_json()
    assert detail['content'] == '你好，社区'
    assert detail['comments'] == []

    # 短正文越界一律 400，不静默截断
    r = client.post('/api/community/moments', json={'content': 'x' * 501},
                    headers=_auth(t1))
    assert r.status_code == 400

    # 长文允许 content 为空，但 long_body 必填
    long_m = _post_moment(client, t1, content='', long_body='长文正文' * 10)
    assert long_m['is_long'] is True
    assert client.post('/api/community/moments', json={'content': ''},
                       headers=_auth(t1)).status_code == 400

    # 最多 4 个话题
    r = client.post('/api/community/moments',
                    json={'content': '话题太多', 'topics': ['a', 'b', 'c', 'd', 'e']},
                    headers=_auth(t1))
    assert r.status_code == 400


def test_like_comment_and_notification(client):
    t_author, _ = _register(client)
    t_fan, _ = _register(client)
    m = _post_moment(client, t_author)

    assert client.post(f"/api/community/moments/{m['id']}/like",
                       headers=_auth(t_fan)).status_code == 200
    r = client.post(f"/api/community/moments/{m['id']}/like", headers=_auth(t_fan))
    assert r.get_json()['like_count'] == 1  # 幂等

    r = client.post(f"/api/community/moments/{m['id']}/comments",
                    json={'content': '说得好'}, headers=_auth(t_fan))
    assert r.status_code == 201

    detail = client.get(f"/api/community/moments/{m['id']}").get_json()
    assert detail['comment_count'] == 1
    assert len(detail['comments']) == 1

    notes = client.get('/api/community/notifications', headers=_auth(t_author)).get_json()
    assert any(n['type'] == 'moment_comment' for n in notes['items'])


def test_favorite_idempotent_and_list(client):
    t_author, _ = _register(client)
    t_fan, _ = _register(client)
    m = _post_moment(client, t_author)

    r1 = client.post(f"/api/community/moments/{m['id']}/favorite", headers=_auth(t_fan))
    r2 = client.post(f"/api/community/moments/{m['id']}/favorite", headers=_auth(t_fan))
    assert r1.get_json()['favorite_count'] == 1
    assert r2.get_json()['favorite_count'] == 1

    favs = client.get('/api/community/moments/favorites', headers=_auth(t_fan)).get_json()
    assert [x['id'] for x in favs['items']] == [m['id']]

    r = client.delete(f"/api/community/moments/{m['id']}/favorite", headers=_auth(t_fan))
    assert r.get_json()['favorited'] is False


def test_repost_snapshot_and_guard(client):
    t_author, author = _register(client)
    t_other, _ = _register(client)
    m = _post_moment(client, t_author, content='原始内容')

    r = client.post(f"/api/community/moments/{m['id']}/repost",
                    json={'quote': '我同意'}, headers=_auth(t_other))
    assert r.status_code == 201, r.get_json()
    repost = r.get_json()
    assert repost['repost_type'] == 'quote'
    assert repost['repost_snapshot']['content'] == '原始内容'
    assert repost['repost_snapshot']['display_username'] == author['username']

    # 转发一条转发 → 400
    r = client.post(f"/api/community/moments/{repost['id']}/repost",
                    json={}, headers=_auth(t_author))
    assert r.status_code == 400

    # 取消本人转发
    r = client.delete(f"/api/community/moments/{m['id']}/repost", headers=_auth(t_other))
    assert r.status_code == 200
    detail = client.get(f"/api/community/moments/{m['id']}").get_json()
    assert detail['repost_count'] == 0

    # 匿名动态不可转发
    anon = _post_moment(client, t_author, content='匿名说', is_anonymous=True)
    r = client.post(f"/api/community/moments/{anon['id']}/repost",
                    json={}, headers=_auth(t_other))
    assert r.status_code == 400
    assert '匿名' in r.get_json()['message']


def test_follow_feed_and_visibility(client):
    t_a, a = _register(client)
    t_b, b = _register(client)
    t_c, _ = _register(client)

    public_m = _post_moment(client, t_b, content='公开动态')
    follower_m = _post_moment(client, t_b, content='仅关注者', visibility='followers')
    private_m = _post_moment(client, t_b, content='仅自己', visibility='private')

    # 未关注：公开可见，其余不可见
    feed = client.get('/api/community/feed').get_json()
    ids = {x['id'] for x in feed['items']}
    assert public_m['id'] in ids
    assert follower_m['id'] not in ids
    assert private_m['id'] not in ids

    # 关注 B 后：关注流出现公开 + 仅关注者
    r = client.post(f"/api/learning/users/{b['id']}/follow", headers=_auth(t_a))
    assert r.status_code in (200, 201), r.get_json()

    follow_feed = client.get('/api/community/feed?tab=follow', headers=_auth(t_a)).get_json()
    ids = {x['id'] for x in follow_feed['items']}
    assert public_m['id'] in ids and follower_m['id'] in ids
    assert private_m['id'] not in ids

    # 未登录访问关注流 → 401
    assert client.get('/api/community/feed?tab=follow').status_code == 401

    # 第三方看不到 follower 可见的动态，关注关系接口自洽
    ids_c = {x['id'] for x in client.get('/api/community/feed', headers=_auth(t_c)).get_json()['items']}
    assert follower_m['id'] not in ids_c

    stats = client.get(f"/api/community/users/{b['id']}/follow-stats",
                       headers=_auth(t_a)).get_json()
    assert stats['fans_count'] == 1
    assert stats['is_following'] is True
