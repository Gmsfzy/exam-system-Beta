# -*- coding: utf-8 -*-
"""社区中心 Phase 1 扩充回归（HTTP 层，真实 app + test_client）。

覆盖：
  帖子 CRUD / 列表搜索正文 / 匿名与权限
  点赞幂等 + Redis 热计数读取
  收藏幂等 + 我的收藏列表
  楼中楼评论（parent_id）+ 删除父评论级联软删
  @提及 / 评论 / 回复通知 + 已读 / 全部已读
  举报（3 条自动折叠、驳回解除折叠、教师删除内容）
  已解决标记与列表过滤
  图片/附件上传（扩展名白名单）
  未登录 / 伪造令牌 401 边界

说明：复用 conftest 已改指的临时库；每个用例前清空社区表与点赞热缓存，
保证自增 id 不复用旧缓存值。
"""
import io

import pytest

from database import db


@pytest.fixture(scope='module')
def comm_app():
    """真实 app 单例：跳过 bootstrap、关闭限流、建全表。"""
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
def _reset_community(comm_app):
    """用例级清理：先清空社区数据，再清 Redis 点赞热计数。"""
    from database.models import (
        CommunityPost, CommunityComment, CommunityLike,
        CommunityFavorite, CommunityNotification, CommunityReport,
        CommunityPollOption, CommunityPollVote,
        CommunityPointLog, CommunityUserStat,
    )
    from utils.redis_cache import delete_pattern

    with comm_app.app_context():
        CommunityReport.query.delete()
        CommunityNotification.query.delete()
        CommunityFavorite.query.delete()
        CommunityLike.query.delete()
        CommunityPollVote.query.delete()
        CommunityPollOption.query.delete()
        CommunityPointLog.query.delete()
        CommunityUserStat.query.delete()
        CommunityComment.query.delete()
        CommunityPost.query.delete()
        db.session.commit()

    delete_pattern('community:like:*')
    yield


@pytest.fixture()
def client(comm_app):
    return comm_app.test_client()


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _register(client, username, role='student'):
    r = client.post('/api/register', json={
        'username': username, 'password': 'community-pw', 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    return body['token'], body['user']


def _create_post(client, token, title='测试帖子', content='正文内容', category='help', **kw):
    payload = {'title': title, 'content': content, 'category': category}
    payload.update(kw)
    r = client.post('/api/community/posts', json=payload, headers=_auth(token))
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _create_comment(client, token, post_id, content, parent_id=None):
    payload = {'content': content}
    if parent_id:
        payload['parent_id'] = parent_id
    r = client.post(f'/api/community/posts/{post_id}/comments',
                    json=payload, headers=_auth(token))
    assert r.status_code == 201, r.get_json()
    return r.get_json()


# ─────────────────────── 帖子 CRUD ───────────────────────

def test_post_crud_search_and_permissions(client):
    author_t, author = _register(client, 'cm_crud_author')
    other_t, other = _register(client, 'cm_crud_other')

    post = _create_post(client, author_t, title='链表反转求助',
                        content='为什么这题总是空指针，唯一线索是 tail 指针')
    assert post['is_author'] is True
    assert post['like_count'] == 0 and post['favorite_count'] == 0

    # 列表：正文关键字也能命中
    r = client.get('/api/community/posts', query_string={'q': 'tail'})
    assert r.status_code == 200
    assert any(p['id'] == post['id'] for p in r.get_json()['items'])

    # 详情
    r = client.get(f"/api/community/posts/{post['id']}")
    assert r.status_code == 200 and r.get_json()['title'] == '链表反转求助'

    # 他人不能编辑 / 删除
    assert client.put(f"/api/community/posts/{post['id']}",
                      json={'title': '篡改'}, headers=_auth(other_t)).status_code == 403
    assert client.delete(f"/api/community/posts/{post['id']}",
                         headers=_auth(other_t)).status_code == 403

    # 作者编辑
    r = client.put(f"/api/community/posts/{post['id']}",
                   json={'title': '链表反转已定位', 'content': '已找到问题'},
                   headers=_auth(author_t))
    assert r.status_code == 200 and r.get_json()['title'] == '链表反转已定位'

    # 作者删除（软删除后详情 404）
    assert client.delete(f"/api/community/posts/{post['id']}",
                         headers=_auth(author_t)).status_code == 200
    assert client.get(f"/api/community/posts/{post['id']}").status_code == 404


def test_post_anonymous_display(client):
    author_t, author = _register(client, 'cm_anon_author')
    teacher_t, teacher = _register(client, 'cm_anon_teacher', role='teacher')

    post = _create_post(client, author_t, title='匿名提问', is_anonymous=True)
    assert post['display_anon'] == '匿名#1'
    assert post['display_username'] is None

    # 老师视角可见真实用户名（display_username 字段回填）
    r = client.get(f"/api/community/posts/{post['id']}", headers=_auth(teacher_t))
    assert r.status_code == 200
    assert r.get_json()['display_username'] == author['username']


# ─────────────────────── 点赞 / 收藏 ───────────────────────

def test_like_and_favorite_idempotent(client):
    u1_t, _ = _register(client, 'cm_like_u1')
    u2_t, _ = _register(client, 'cm_like_u2')
    post = _create_post(client, u1_t, title='点赞测试')

    # 重复点赞幂等：两次 POST 后计数仍为 1
    r1 = client.post(f"/api/community/posts/{post['id']}/like", headers=_auth(u2_t))
    r2 = client.post(f"/api/community/posts/{post['id']}/like", headers=_auth(u2_t))
    assert r1.status_code == r2.status_code == 200
    assert r2.get_json()['like_count'] == 1

    # 第二个人点赞 → 2
    third_t, _ = _register(client, 'cm_like_u3')
    r3 = client.post(f"/api/community/posts/{post['id']}/like", headers=_auth(third_t))
    assert r3.get_json()['like_count'] == 2

    # 热计数读取：详情回填 Redis 缓存值
    detail = client.get(f"/api/community/posts/{post['id']}").get_json()
    assert detail['like_count'] == 2 and detail['liked'] is False

    # 收藏幂等
    f1 = client.post(f"/api/community/posts/{post['id']}/favorite", headers=_auth(u2_t))
    f2 = client.post(f"/api/community/posts/{post['id']}/favorite", headers=_auth(u2_t))
    assert f2.status_code == 200 and f2.get_json()['favorite_count'] == 1
    favs = client.get('/api/community/favorites', headers=_auth(u2_t)).get_json()
    assert favs['total'] == 1 and favs['items'][0]['id'] == post['id']
    assert favs['items'][0]['favorited'] is True

    # 取消收藏
    r = client.delete(f"/api/community/posts/{post['id']}/favorite", headers=_auth(u2_t))
    assert r.get_json()['favorite_count'] == 0

    # 取消点赞后热计数回落
    client.delete(f"/api/community/posts/{post['id']}/like", headers=_auth(u2_t))
    detail = client.get(f"/api/community/posts/{post['id']}").get_json()
    assert detail['like_count'] == 1


# ─────────────────────── 楼中楼评论 ───────────────────────

def test_nested_comments_and_cascade_delete(client):
    author_t, _ = _register(client, 'cm_nest_author')
    u2_t, _ = _register(client, 'cm_nest_u2')
    u3_t, _ = _register(client, 'cm_nest_u3')

    post = _create_post(client, author_t, title='楼中楼测试')
    c1 = _create_comment(client, u2_t, post['id'], '一级评论')
    c2 = _create_comment(client, u3_t, post['id'], '回复一级', parent_id=c1['id'])
    c3 = _create_comment(client, u2_t, post['id'], '回复二级', parent_id=c2['id'])

    detail = client.get(f"/api/community/posts/{post['id']}").get_json()
    assert detail['comment_count'] == 3
    assert len(detail['comments']) == 3
    by_id = {c['id']: c for c in detail['comments']}
    assert by_id[c2['id']]['parent_id'] == c1['id']
    assert by_id[c3['id']]['parent_id'] == c2['id']

    # 跨帖 parent_id 校验
    other_post = _create_post(client, author_t, title='另一帖')
    r = client.post(f"/api/community/posts/{other_post['id']}/comments",
                    json={'content': '错误引用', 'parent_id': c1['id']},
                    headers=_auth(u3_t))
    assert r.status_code == 400

    # 删除一级评论 → 级联软删其下 3 条
    r = client.delete(f"/api/community/comments/{c1['id']}", headers=_auth(u2_t))
    assert r.status_code == 200 and r.get_json()['affected'] == 3
    detail = client.get(f"/api/community/posts/{post['id']}").get_json()
    assert detail['comment_count'] == 0 and detail['comments'] == []


# ─────────────────────── 通知 / @提及 ───────────────────────

def test_notifications_comment_reply_mention(client):
    author_t, author = _register(client, 'cm_nt_author')
    commenter_t, commenter = _register(client, 'cm_nt_commenter')
    mentor_t, mentor = _register(client, 'cm_nt_mentor')

    post = _create_post(client, author_t, title='通知测试',
                        content=f"@{mentor['username']} 帮忙看看这道题")

    # 帖子正文 @mentor → mentor 收到 mention
    n = client.get('/api/community/notifications', headers=_auth(mentor_t)).get_json()
    assert n['total'] == 1 and n['items'][0]['type'] == 'mention'

    # 一级评论 → 帖作者收到 comment
    c1 = _create_comment(client, commenter_t, post['id'], '我也想知道')
    n = client.get('/api/community/notifications', headers=_auth(author_t)).get_json()
    assert any(x['type'] == 'comment' for x in n['items'])

    # 楼中楼回复 → 父评论作者收到 reply
    c2 = _create_comment(client, author_t, post['id'], '谢谢，我再试试', parent_id=c1['id'])
    n = client.get('/api/community/notifications', headers=_auth(commenter_t)).get_json()
    assert any(x['type'] == 'reply' and x['comment_id'] == c2['id'] for x in n['items'])

    # 评论里 @mentor → 再收到一条 mention
    _create_comment(client, commenter_t, post['id'],
                    f"@{mentor['username']} 你觉得呢")
    n = client.get('/api/community/notifications', headers=_auth(mentor_t)).get_json()
    assert n['unread'] >= 2

    # 单条已读
    target = n['items'][0]
    assert client.put(f"/api/community/notifications/{target['id']}/read",
                      headers=_auth(mentor_t)).status_code == 200
    count = client.get('/api/community/notifications/unread-count',
                       headers=_auth(mentor_t)).get_json()['unread']
    assert count == n['unread'] - 1

    # 全部已读
    r = client.put('/api/community/notifications/read-all', headers=_auth(mentor_t))
    assert r.status_code == 200 and r.get_json()['updated'] >= 1
    assert client.get('/api/community/notifications/unread-count',
                      headers=_auth(mentor_t)).get_json()['unread'] == 0

    # 别人的通知不可操作
    own = client.get('/api/community/notifications', headers=_auth(author_t)).get_json()
    if own['items']:
        assert client.put(f"/api/community/notifications/{own['items'][0]['id']}/read",
                          headers=_auth(mentor_t)).status_code == 404


# ─────────────────────── 举报 / 折叠 ───────────────────────

def test_report_auto_fold_and_teacher_handling(client):
    author_t, author = _register(client, 'cm_rep_author')
    teacher_t, teacher = _register(client, 'cm_rep_teacher', role='teacher')
    r1_t, _ = _register(client, 'cm_rep_r1')
    r2_t, _ = _register(client, 'cm_rep_r2')
    r3_t, _ = _register(client, 'cm_rep_r3')

    post = _create_post(client, author_t, title='被举报帖子', content='原文内容')

    # 不能举报自己
    assert client.post('/api/community/reports', json={
        'target_type': 'post', 'target_id': post['id'], 'reason': '自举报',
    }, headers=_auth(author_t)).status_code == 400

    report_ids = []
    for i, t in enumerate((r1_t, r2_t, r3_t), start=1):
        r = client.post('/api/community/reports', json={
            'target_type': 'post', 'target_id': post['id'], 'reason': f'理由{i}',
        }, headers=_auth(t))
        assert r.status_code == 201
        assert r.get_json()['report_count'] == i
        report_ids.append(r.get_json()['report']['id'])

    # 第三条后自动折叠：匿名访客看不到原文
    detail = client.get(f"/api/community/posts/{post['id']}").get_json()
    assert detail['hidden'] is True and detail['can_view_content'] is False
    assert detail['content'] == '该内容因多次举报已被折叠'

    # 作者本人仍可查看
    detail = client.get(f"/api/community/posts/{post['id']}",
                        headers=_auth(author_t)).get_json()
    assert detail['hidden'] is True and detail['can_view_content'] is True
    assert detail['content'] == '原文内容'

    # 重复举报被拒
    assert client.post('/api/community/reports', json={
        'target_type': 'post', 'target_id': post['id'], 'reason': '重复',
    }, headers=_auth(r1_t)).status_code == 400

    # 学生无权查看举报队列
    assert client.get('/api/community/reports', headers=_auth(r1_t)).status_code == 403

    # 教师查看待处理
    r = client.get('/api/community/reports', headers=_auth(teacher_t))
    assert r.status_code == 200 and r.get_json()['total'] == 3

    # 驳回一条 → 待处理降为 2，自动解除折叠
    r = client.put(f"/api/community/reports/{report_ids[0]}",
                   json={'action': 'dismiss'}, headers=_auth(teacher_t))
    assert r.status_code == 200 and r.get_json()['report']['status'] == 'dismissed'
    detail = client.get(f"/api/community/posts/{post['id']}").get_json()
    assert detail['hidden'] is False and detail['can_view_content'] is True

    # 删除内容 → 帖子软删除，作者收到 report 通知
    r = client.put(f"/api/community/reports/{report_ids[1]}",
                   json={'action': 'remove'}, headers=_auth(teacher_t))
    assert r.status_code == 200
    assert client.get(f"/api/community/posts/{post['id']}").status_code == 404
    n = client.get('/api/community/notifications', headers=_auth(author_t)).get_json()
    assert any(x['type'] == 'report' for x in n['items'])

    # 已处理的举报不能二次处理
    assert client.put(f"/api/community/reports/{report_ids[1]}",
                      json={'action': 'dismiss'}, headers=_auth(teacher_t)).status_code == 400


# ─────────────────────── 已解决标记 ───────────────────────

def test_resolve_mark_and_filter(client):
    author_t, author = _register(client, 'cm_res_author')
    teacher_t, teacher = _register(client, 'cm_res_teacher', role='teacher')
    outsider_t, _ = _register(client, 'cm_res_outsider')

    post = _create_post(client, author_t, title='待解决求助')

    # 非作者/非教师无权标记
    assert client.put(f"/api/community/posts/{post['id']}/resolve",
                      json={'resolved': True}, headers=_auth(outsider_t)).status_code == 403

    # 教师标记已解决 → 作者收到 resolve 通知
    r = client.put(f"/api/community/posts/{post['id']}/resolve",
                   json={'resolved': True}, headers=_auth(teacher_t))
    assert r.status_code == 200 and r.get_json()['is_resolved'] is True
    assert r.get_json()['resolved_at'] is not None
    n = client.get('/api/community/notifications', headers=_auth(author_t)).get_json()
    assert any(x['type'] == 'resolve' for x in n['items'])

    # 列表 resolved=1 命中、resolved=0 不命中
    r = client.get('/api/community/posts', query_string={'resolved': '1'})
    assert any(p['id'] == post['id'] for p in r.get_json()['items'])
    r = client.get('/api/community/posts', query_string={'resolved': '0'})
    assert all(p['id'] != post['id'] for p in r.get_json()['items'])

    # 作者取消已解决
    r = client.put(f"/api/community/posts/{post['id']}/resolve",
                   json={'resolved': False}, headers=_auth(author_t))
    assert r.status_code == 200 and r.get_json()['is_resolved'] is False
    assert r.get_json()['resolved_at'] is None


# ─────────────────────── 上传 ───────────────────────

def test_upload_image_and_reject_bad_ext(client):
    token, _ = _register(client, 'cm_upload_user')

    # PNG 扩展名通过（后端只校验扩展名/大小）
    data = {'file': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 32), 'demo.png')}
    r = client.post('/api/community/upload', data=data,
                    content_type='multipart/form-data', headers=_auth(token))
    assert r.status_code == 201
    body = r.get_json()
    assert body['is_image'] is True and body['url'].startswith('/uploads/')

    # 非白名单扩展名被拒
    data = {'file': (io.BytesIO(b'<script>alert(1)</script>'), 'evil.html')}
    r = client.post('/api/community/upload', data=data,
                    content_type='multipart/form-data', headers=_auth(token))
    assert r.status_code == 400

    # 未选文件
    r = client.post('/api/community/upload', data={}, headers=_auth(token))
    assert r.status_code == 400


# ─────────────────────── 认证边界 ───────────────────────

def test_auth_boundaries(client):
    # 无 token：受保护 GET → 401
    assert client.get('/api/community/favorites').status_code == 401
    assert client.get('/api/community/notifications').status_code == 401
    assert client.get('/api/community/reports').status_code == 401
    assert client.get('/api/community/admin/stats').status_code == 401

    # 无 token 的写请求：CSRF 前置门拦截（现状 400）
    assert client.post('/api/community/posts', json={
        'title': 'x', 'content': 'y'}).status_code == 400

    # 伪造 Bearer：过 CSRF 豁免但令牌解析失败 → 401
    assert client.post('/api/community/posts', json={
        'title': 'x', 'content': 'y'
    }, headers={'Authorization': 'Bearer garbage'}).status_code == 401

    # 无效分类 / 标题超长
    token, _ = _register(client, 'cm_auth_user')
    assert client.post('/api/community/posts', json={
        'title': '标题', 'content': '正文', 'category': 'not-exist',
    }, headers=_auth(token)).status_code == 400
    assert client.post('/api/community/posts', json={
        'title': 'x' * 101, 'content': '正文',
    }, headers=_auth(token)).status_code == 400


# ─────────────────────── 第二批：个人主页 ───────────────────────

def test_user_profile_stats_and_anon_visibility(client):
    author_t, author = _register(client, 'cm_prof_author')
    viewer_t, viewer = _register(client, 'cm_prof_viewer')
    teacher_t, teacher = _register(client, 'cm_prof_teacher', role='teacher')

    normal = _create_post(client, author_t, title='公开帖', content='正常内容')
    anon = _create_post(client, author_t, title='匿名帖', content='匿名内容',
                        is_anonymous=True)
    _create_comment(client, author_t, normal['id'], '作者自评')

    url = f"/api/community/users/{author['id']}"

    # 游客视角：匿名帖不计入、不返回
    r = client.get(url)
    assert r.status_code == 200
    data = r.get_json()
    assert data['stats']['post_count'] == 1
    assert all(p['is_anonymous'] is False for p in data['posts']['items'])
    assert data['stats']['comment_count'] == 1

    # 作者本人可见匿名帖
    r = client.get(url, headers=_auth(author_t))
    assert r.get_json()['stats']['post_count'] == 2

    # 教师可见匿名帖（治理需要）
    r = client.get(url, headers=_auth(teacher_t))
    assert r.get_json()['stats']['post_count'] == 2

    # 普通他人不可见
    r = client.get(url, headers=_auth(viewer_t))
    assert r.get_json()['stats']['post_count'] == 1

    # 不存在的用户
    assert client.get('/api/community/users/999999').status_code == 404


# ─────────────────────── 第二批：采纳答案 ───────────────────────

def test_accept_answer_and_notification(client):
    author_t, author = _register(client, 'cm_acc_author')
    helper_t, helper = _register(client, 'cm_acc_helper')
    other_t, _ = _register(client, 'cm_acc_other')

    post = _create_post(client, author_t, title='求最佳解法')
    answer = _create_comment(client, helper_t, post['id'], '这是我的解法')

    # 非作者不能采纳
    assert client.put(f"/api/community/posts/{post['id']}/accept",
                      json={'comment_id': answer['id']},
                      headers=_auth(other_t)).status_code == 403

    # 作者采纳 → 已解决 + 回答者收到 accept 通知
    r = client.put(f"/api/community/posts/{post['id']}/accept",
                   json={'comment_id': answer['id']}, headers=_auth(author_t))
    assert r.status_code == 200
    body = r.get_json()
    assert body['is_resolved'] is True
    assert body['accepted_comment_id'] == answer['id']
    n = client.get('/api/community/notifications', headers=_auth(helper_t)).get_json()
    assert any(x['type'] == 'accept' for x in n['items'])

    # 详情评论带 is_accepted 标识
    detail = client.get(f"/api/community/posts/{post['id']}").get_json()
    assert detail['comments'][0]['is_accepted'] is True

    # 跨帖采纳被拒
    other_post = _create_post(client, author_t, title='另一帖')
    assert client.put(f"/api/community/posts/{other_post['id']}/accept",
                      json={'comment_id': answer['id']},
                      headers=_auth(author_t)).status_code == 404

    # 取消采纳 → 已解决状态同步清除
    r = client.put(f"/api/community/posts/{post['id']}/accept",
                   json={'comment_id': None}, headers=_auth(author_t))
    assert r.status_code == 200
    assert r.get_json()['is_resolved'] is False
    assert r.get_json()['accepted_comment_id'] is None


# ─────────────────────── 第二批：投票帖 ───────────────────────

def test_poll_create_vote_and_change(client):
    author_t, _ = _register(client, 'cm_poll_author')
    u1_t, _ = _register(client, 'cm_poll_u1')
    u2_t, _ = _register(client, 'cm_poll_u2')

    post = _create_post(client, author_t, title='你更喜欢哪种解法？',
                        poll_options=['递归', '迭代', '双指针'])
    assert post['poll'] is not None
    assert len(post['poll']['options']) == 3
    assert post['poll']['total_votes'] == 0

    # 选项数量不合法
    assert client.post('/api/community/posts', json={
        'title': '非法投票', 'content': '正文', 'poll_options': ['只有一个'],
    }, headers=_auth(author_t)).status_code == 400

    opt1, opt2 = post['poll']['options'][0]['id'], post['poll']['options'][1]['id']

    # 用户1 投选项1
    r = client.post(f"/api/community/posts/{post['id']}/vote",
                    json={'option_id': opt1}, headers=_auth(u1_t))
    assert r.status_code == 200
    assert r.get_json()['total_votes'] == 1
    assert r.get_json()['voted_option_id'] == opt1

    # 用户2 投选项2
    client.post(f"/api/community/posts/{post['id']}/vote",
                json={'option_id': opt2}, headers=_auth(u2_t))
    # 用户1 改投选项2 → 总票数不变、选项2 计 2 票
    r = client.post(f"/api/community/posts/{post['id']}/vote",
                    json={'option_id': opt2}, headers=_auth(u1_t))
    poll = r.get_json()
    assert poll['total_votes'] == 2
    assert poll['voted_option_id'] == opt2
    by_id = {o['id']: o for o in poll['options']}
    assert by_id[opt2]['vote_count'] == 2 and by_id[opt1]['vote_count'] == 0

    # 其他帖子的选项无法投票
    other_post = _create_post(client, author_t, title='另一投票',
                              poll_options=['A', 'B'])
    other_opt = other_post['poll']['options'][0]['id']
    assert client.post(f"/api/community/posts/{post['id']}/vote",
                       json={'option_id': other_opt}, headers=_auth(u1_t)).status_code == 404


# ─────────────────────── 第二批：标签 + 热门标签 ───────────────────────

def test_tags_filter_and_hot_tags(client):
    author_t, _ = _register(client, 'cm_tag_author')

    p1 = _create_post(client, author_t, title='链表求助', tags=['链表', '指针'])
    p2 = _create_post(client, author_t, title='链表反转', tags=['链表反转'])
    p3 = _create_post(client, author_t, title='动态规划', tags=['动态规划'])

    # 精确按标签过滤：链表命中 p1，不误伤「链表反转」
    r = client.get('/api/community/posts', query_string={'tag': '链表'})
    ids = [p['id'] for p in r.get_json()['items']]
    assert p1['id'] in ids and p2['id'] not in ids and p3['id'] not in ids

    # 超过 5 个标签被拒
    assert client.post('/api/community/posts', json={
        'title': '标签超限', 'content': '正文',
        'tags': ['a', 'b', 'c', 'd', 'e', 'f'],
    }, headers=_auth(author_t)).status_code == 400

    # 热门标签聚合
    r = client.get('/api/community/tags')
    tags = {t['tag']: t['count'] for t in r.get_json()}
    assert tags.get('链表') == 1 and tags.get('动态规划') == 1

    # 编辑帖子可更新标签
    r = client.put(f"/api/community/posts/{p3['id']}", json={'tags': ['DP']},
                   headers=_auth(author_t))
    assert r.status_code == 200 and r.get_json()['tags'] == ['DP']


# ─────────────────────── 第二批：管理后台 ───────────────────────

def test_admin_stats_and_visibility(client):
    teacher_t, teacher = _register(client, 'cm_admin_teacher', role='teacher')
    student_t, student = _register(client, 'cm_admin_student')

    post = _create_post(client, student_t, title='待治理帖子', content='正常正文')
    comment = _create_comment(client, student_t, post['id'], '待治理评论')

    # 学生无权限
    assert client.get('/api/community/admin/stats',
                      headers=_auth(student_t)).status_code == 403
    assert client.get('/api/community/admin/posts',
                      headers=_auth(student_t)).status_code == 403

    # 教师统计
    r = client.get('/api/community/admin/stats', headers=_auth(teacher_t))
    assert r.status_code == 200
    stats = r.get_json()
    assert stats['total_posts'] == 1 and stats['total_comments'] == 1

    # 管理列表包含折叠 / 删除内容
    client.put(f"/api/community/admin/posts/{post['id']}/visibility",
               json={'hidden': True}, headers=_auth(teacher_t))
    r = client.get('/api/community/admin/posts',
                   query_string={'status': 'hidden'}, headers=_auth(teacher_t))
    assert any(p['id'] == post['id'] and p['hidden'] is True
               for p in r.get_json()['items'])

    # 折叠后游客无法看到正文
    detail = client.get(f"/api/community/posts/{post['id']}").get_json()
    assert detail['can_view_content'] is False

    # 恢复
    r = client.put(f"/api/community/admin/posts/{post['id']}/visibility",
                   json={'hidden': False}, headers=_auth(teacher_t))
    assert r.status_code == 200 and r.get_json()['hidden'] is False

    # 评论折叠 / 恢复
    r = client.put(f"/api/community/admin/comments/{comment['id']}/visibility",
                   json={'hidden': True}, headers=_auth(teacher_t))
    assert r.status_code == 200 and r.get_json()['hidden'] is True
    r = client.put(f"/api/community/admin/comments/{comment['id']}/visibility",
                   json={'hidden': False}, headers=_auth(teacher_t))
    assert r.status_code == 200 and r.get_json()['hidden'] is False

    # 删除后管理列表仍可查到
    client.delete(f"/api/community/posts/{post['id']}", headers=_auth(teacher_t))
    r = client.get('/api/community/admin/posts',
                   query_string={'status': 'deleted'}, headers=_auth(teacher_t))
    assert any(p['id'] == post['id'] and p['deleted'] is True
               for p in r.get_json()['items'])


# ─────────────────────── 第三批：积分等级 ───────────────────────

def _seed_points(comm_app, user_id, points):
    from database.models import CommunityUserStat

    with comm_app.app_context():
        stat = CommunityUserStat.query.filter_by(user_id=user_id).first()
        if not stat:
            stat = CommunityUserStat(user_id=user_id, points=0)
            db.session.add(stat)
        stat.points = points
        db.session.commit()


def test_points_award_level_and_me(client):
    author_t, author = _register(client, 'cm_pts_author')
    other_t, other = _register(client, 'cm_pts_other')

    # 发帖 +5
    p = _create_post(client, author_t, title='积分帖')
    r = client.get('/api/community/me/points', headers=_auth(author_t))
    assert r.status_code == 200
    me = r.get_json()
    assert me['points'] >= 5 and me['level'] >= 1
    assert any(l['reason'] == 'post' for l in me['logs'])

    # 别人评论 +2
    c = _create_comment(client, other_t, p['id'], '我也想知道')
    r = client.get('/api/community/me/points', headers=_auth(other_t))
    assert r.get_json()['points'] >= 2

    # 采纳评论者 +15
    r = client.put(f"/api/community/posts/{p['id']}/accept",
                   json={'comment_id': c['id']}, headers=_auth(author_t))
    assert r.status_code == 200
    r = client.get('/api/community/me/points', headers=_auth(other_t))
    assert r.get_json()['points'] >= 17

    # 点赞作者 +1
    client.post(f"/api/community/posts/{p['id']}/like", headers=_auth(other_t))
    r = client.get('/api/community/me/points', headers=_auth(author_t))
    assert any(l['reason'] == 'like' for l in r.get_json()['logs'])


# ─────────────────────── 第三批：圈子 + 悬赏 + 错题求助 ───────────────────────

def _seed_course_question(comm_app, suffix):
    """建课程 + 题目，返回 (course_id, question_id)。"""
    from database.models import Course, Major, Question

    with comm_app.app_context():
        major = Major.query.filter_by(name=f'社区测试专业{suffix}').first()
        if not major:
            major = Major(name=f'社区测试专业{suffix}')
            db.session.add(major)
            db.session.flush()
        course = Course.query.filter_by(
            name=f'社区测试课{suffix}', major_id=major.id).first()
        if not course:
            course = Course(name=f'社区测试课{suffix}', major_id=major.id)
            db.session.add(course)
            db.session.flush()
        question = Question(
            content=f'求 {suffix} 的值？', answer='B', major_id=major.id,
            course_id=course.id, type='single_choice', difficulty='easy',
            options=['A', 'B', 'C', 'D'], knowledge='加法,基础',
        )
        db.session.add(question)
        db.session.commit()
        return course.id, question.id


def _seed_wrong_record(comm_app, user_id, question_id, wrong_answer='A'):
    from database.models import WrongAnswerRecord

    with comm_app.app_context():
        rec = WrongAnswerRecord(
            user_id=user_id, question_id=question_id,
            source_type='practice', wrong_answer=wrong_answer, correct_answer='B',
        )
        db.session.add(rec)
        db.session.commit()
        return rec.id


def test_circles_list_and_course_filter(client, comm_app):
    author_t, _ = _register(client, 'cm_circle_author')
    course_id, _qid = _seed_course_question(comm_app, 'circle')

    p1 = _create_post(client, author_t, title='圈子内帖子', course_id=course_id)
    assert p1['course_id'] == course_id and p1['course_name']

    p2 = _create_post(client, author_t, title='圈子外帖子')
    r = client.get('/api/community/posts', query_string={'course_id': course_id})
    ids = [p['id'] for p in r.get_json()['items']]
    assert ids == [p1['id']] and p2['id'] not in ids

    r = client.get('/api/community/circles')
    assert r.status_code == 200
    item = next(c for c in r.get_json()['items'] if c['course_id'] == course_id)
    assert item['post_count'] == 1


def test_bounty_hold_reward_and_refund(client, comm_app):
    author_t, author = _register(client, 'cm_bounty_author')
    answerer_t, _ = _register(client, 'cm_bounty_answerer')
    course_id, question_id = _seed_course_question(comm_app, 'bounty')

    _seed_points(comm_app, author['id'], 50)

    p = _create_post(client, author_t, title='悬赏求助', category='help',
                     linked_type='question', linked_id=question_id,
                     bounty_points=10)
    me = client.get('/api/community/me/points', headers=_auth(author_t)).get_json()
    # 发帖 +5 后冻结 10：50 + 5 - 10 = 45
    assert me['points'] == 45
    assert any(l['reason'] == 'bounty_hold' for l in me['logs'])

    c = _create_comment(client, answerer_t, p['id'], '答案是 B')
    r = client.put(f"/api/community/posts/{p['id']}/accept",
                   json={'comment_id': c['id']}, headers=_auth(author_t))
    assert r.status_code == 200

    ans = client.get('/api/community/me/points', headers=_auth(answerer_t)).get_json()
    # 评论 +2、采纳 +15、悬赏 +10
    assert ans['points'] == 27
    assert any(l['reason'] == 'bounty_reward' and l['delta'] == 10
               for l in ans['logs'])

    detail = client.get(f"/api/community/posts/{p['id']}").get_json()
    assert detail['bounty_points'] == 10 and detail['bounty_rewarded'] is True

    # 未发放悬赏的帖子删除后积分退回作者
    p2 = _create_post(client, author_t, title='悬赏撤回', category='help',
                      linked_type='question', linked_id=question_id,
                      bounty_points=5)
    client.delete(f"/api/community/posts/{p2['id']}", headers=_auth(author_t))
    me2 = client.get('/api/community/me/points', headers=_auth(author_t)).get_json()
    assert any(l['reason'] == 'bounty_refund' and l['delta'] == 5
               for l in me2['logs'])
    # 45 + 5(发帖) - 5(冻结) + 5(退回) = 50
    assert me2['points'] == 50


def test_ask_from_wrong_record(client, comm_app):
    author_t, author = _register(client, 'cm_wrong_author')
    other_t, _ = _register(client, 'cm_wrong_other')
    course_id, question_id = _seed_course_question(comm_app, 'wrong')
    rec_id = _seed_wrong_record(comm_app, author['id'], question_id)

    r = client.post('/api/community/ask-from-wrong-record',
                    json={'wrong_record_id': rec_id}, headers=_auth(author_t))
    assert r.status_code == 201, r.get_json()
    post = r.get_json()
    assert post['category'] == 'help'
    assert post['linked_type'] == 'question' and post['linked_id'] == question_id
    assert post['course_id'] == course_id
    assert post['title'].startswith('【错题求助】')
    assert '我的答案：A' in post['content']

    # 不能拿别人的错题记录求助
    r = client.post('/api/community/ask-from-wrong-record',
                    json={'wrong_record_id': rec_id}, headers=_auth(other_t))
    assert r.status_code == 404

    # 悬赏求助：积分不足时拒绝
    _seed_points(comm_app, author['id'], 0)
    r = client.post('/api/community/ask-from-wrong-record',
                    json={'wrong_record_id': rec_id, 'bounty_points': 20},
                    headers=_auth(author_t))
    assert r.status_code == 400
