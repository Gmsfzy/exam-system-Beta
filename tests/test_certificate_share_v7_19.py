# -*- coding: utf-8 -*-
"""v7.19 证书公开与分享 E2E：展示态旁表 → 证书广场 → 一键分享社区经验帖。

走真实 app + test_client（Bearer 请求 CSRF 自动豁免），conftest 已把库指向会话
临时 sqlite，绝不触碰 instance 真库。覆盖：公开开关只写旁表不动证书原表、广场筛选
与脱敏（证书编号/核验意见/佐证附件不外发）、他人读公开证书计浏览、未公开对外 404、
分享即公开与幂等回原帖、分享通知旁路、删证书清旁表不留孤儿。
"""
import pytest


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _register(client, username, role='student'):
    r = client.post('/api/register', json={
        'username': username, 'password': 'share-pw-123', 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    return body['token'], body['user']


@pytest.fixture(scope='module')
def share_ctx():
    import app as prod
    from database import db

    prod._boot_done.set()
    prod.app.config['TESTING'] = True
    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False

    with prod.app.app_context():
        import database.models        # noqa: F401
        import competition.models     # noqa: F401
        db.create_all()
        yield {'c': prod.app.test_client(), 'app': prod.app, 'db': db}
        db.session.remove()


def _new_social_cert(client, token, title='全国计算机等级考试二级'):
    r = client.post('/api/learning/certificates/social',
                    data={'category': 'it', 'title': title,
                          'issuer': '教育部考试中心', 'cert_no': 'JT2024001',
                          'grade': '优秀', 'earned_date': '2024-09-01'},
                    headers=_auth(token), content_type='multipart/form-data')
    assert r.status_code == 201, r.get_json()
    return r.get_json()['certificate']


def test_display_toggle_writes_side_table_only(share_ctx):
    """公开开关落在旁表：三张证书原表结构与数据零改动（系统颁发证书是只读资产）。"""
    db = share_ctx['db']
    from database.models import CertificateDisplay, UserCertificate
    c = share_ctx['c']
    tok, owner = _register(c, 'share_owner')

    cert = _new_social_cert(c, tok)
    # 证书墙缺省私有：没有展示行也能正确展示
    wall = c.get('/api/learning/certificates/wall', headers=_auth(tok)).get_json()
    item = next(x for x in wall['items'] if x['id'] == cert['id'])
    assert item['is_public'] is False and item['views'] == 0
    assert item['share_post_id'] is None
    assert wall['kind_labels']['social'] == '社会第三方'

    r = c.put(f'/api/learning/certificates/social/{cert["id"]}/display',
              json={'is_public': True}, headers=_auth(tok))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['is_public'] is True

    d = CertificateDisplay.query.filter_by(cert_kind='social', cert_id=cert['id']).first()
    assert d is not None and d.is_public is True and d.user_id == owner['id']
    assert d.views == 0
    # 证书原表没有被写入公开字段
    row = db.session.get(UserCertificate, cert['id'])
    assert not hasattr(row, 'is_public') and row.verify_status == 'pending'

    wall = c.get('/api/learning/certificates/wall', headers=_auth(tok)).get_json()
    item = next(x for x in wall['items'] if x['id'] == cert['id'])
    assert item['is_public'] is True

    # 本人读详情也要把展示态带回来（否则前端的公开开关一刷新就弹回关）
    mine = c.get(f'/api/learning/certificates/social/{cert["id"]}', headers=_auth(tok)).get_json()
    assert mine['is_mine'] is True and mine['is_public'] is True and mine['views'] == 0

    # 撤下公开：旁表行留着（浏览数不清零，重新公开时接着累计），广场里消失
    c.put(f'/api/learning/certificates/social/{cert["id"]}/display',
          json={'is_public': False}, headers=_auth(tok))
    sq = c.get('/api/learning/certificates/square?q=' + cert['title'],
               headers=_auth(tok)).get_json()
    assert sq['total'] == 0


def test_display_rejects_bad_kind_and_foreign_cert(share_ctx):
    c = share_ctx['c']
    a_tok, _ = _register(c, 'share_kind_a')
    b_tok, _ = _register(c, 'share_kind_b')
    cert = _new_social_cert(c, a_tok, title='英语四级证书')

    assert c.put('/api/learning/certificates/ghost/1/display',
                 json={'is_public': True}, headers=_auth(a_tok)).status_code == 400
    assert c.put('/api/learning/certificates/social/999999/display',
                 json={'is_public': True}, headers=_auth(a_tok)).status_code == 404
    # 他人不能替我把证书公开
    assert c.put(f'/api/learning/certificates/social/{cert["id"]}/display',
                 json={'is_public': True}, headers=_auth(b_tok)).status_code == 404
    assert c.put(f'/api/learning/certificates/social/{cert["id"]}/display',
                 json={}, headers=_auth(a_tok)).status_code == 400


def test_square_desensitizes_and_counts_views(share_ctx):
    db = share_ctx['db']
    from database.models import CertificateDisplay
    c = share_ctx['c']
    owner_tok, owner = _register(c, 'share_sq_owner')
    peer_tok, peer = _register(c, 'share_sq_peer')
    cert = _new_social_cert(c, owner_tok, title='软件设计师证书')

    # 私有阶段：他人读详情 = 404，不透露它存在过
    assert c.get(f'/api/learning/certificates/social/{cert["id"]}',
                 headers=_auth(peer_tok)).status_code == 404

    c.put(f'/api/learning/certificates/social/{cert["id"]}/display',
          json={'is_public': True}, headers=_auth(owner_tok))

    sq = c.get('/api/learning/certificates/square', headers=_auth(peer_tok)).get_json()
    assert sq['total'] >= 1
    hit = next(x for x in sq['items'] if x['kind'] == 'social' and x['id'] == cert['id'])
    assert hit['owner']['username'] == owner['username']
    assert hit['cert_kind_label'] == '社会第三方'
    # 脱敏：证书编号/核验意见不外发，佐证附件标记也摘掉
    assert 'cert_no' not in hit['extra'] and hit['extra'] == {}
    assert 'has_file' not in hit
    assert 'JT2024001' not in str(hit) and '教育部考试中心' in (hit['subtitle'] or '')

    # 筛选：类别 / 关键词 / 类型 / 属主（他人主页拉“他公开的证书”）
    assert c.get('/api/learning/certificates/square?kind=social&category=it',
                 headers=_auth(peer_tok)).get_json()['total'] >= 1
    assert c.get('/api/learning/certificates/square?category=language',
                 headers=_auth(peer_tok)).get_json()['total'] == 0
    mine_sq = c.get('/api/learning/certificates/square',
                    query_string={'owner': owner['id']}, headers=_auth(peer_tok)).get_json()
    assert mine_sq['total'] >= 1 and all(x['owner']['id'] == owner['id'] for x in mine_sq['items'])
    other_sq = c.get('/api/learning/certificates/square',
                     query_string={'owner': peer['id']}, headers=_auth(peer_tok)).get_json()
    assert other_sq['total'] == 0
    assert c.get('/api/learning/certificates/square?q=软件设计师',
                 headers=_auth(peer_tok)).get_json()['total'] >= 1
    assert c.get('/api/learning/certificates/square?q=不存在的关键词',
                 headers=_auth(peer_tok)).get_json()['total'] == 0

    # 他人读公开详情走脱敏视图并累计浏览；本人读仍看完整视图
    before = CertificateDisplay.query.filter_by(cert_kind='social',
                                                cert_id=cert['id']).first().views
    r = c.get(f'/api/learning/certificates/social/{cert["id"]}', headers=_auth(peer_tok))
    assert r.status_code == 200
    assert r.get_json()['owner']['id'] == owner['id']
    assert 'JT2024001' not in (r.get_json().get('extra') or {})
    after = CertificateDisplay.query.filter_by(cert_kind='social',
                                               cert_id=cert['id']).first().views
    assert after == before + 1
    mine = c.get(f'/api/learning/certificates/social/{cert["id"]}', headers=_auth(owner_tok)).get_json()
    assert mine['extra']['cert_no'] == 'JT2024001' and mine['verify_status'] == 'pending'


def test_system_cert_public_without_touching_issued_asset(share_ctx):
    """系统结业证书：公开只挂旁表，颁发行不动（终测分/编号/时间原样）。"""
    db = share_ctx['db']
    from database.models import Major, LearningPath, PathCertificate, CertificateDisplay
    from utils.timeutil import utcnow
    c = share_ctx['c']
    tok, user = _register(c, 'share_sys_owner')
    peer_tok, _ = _register(c, 'share_sys_peer')

    m = Major(name=f'分享测试专业-{user["id"]}')
    db.session.add(m)
    db.session.flush()
    p = LearningPath(major_id=m.id, title='Python 数据分析路径', status='published')
    db.session.add(p)
    db.session.flush()
    cert = PathCertificate(user_id=user['id'], path_id=p.id, serial_no=f'SYS{user["id"]}001',
                          final_score=0.92, summary={'path_title': 'Python 数据分析路径',
                                                     'major_name': m.name},
                          earned_at=utcnow())
    db.session.add(cert)
    db.session.commit()

    r = c.put(f'/api/learning/certificates/system/{cert.id}/display',
              json={'is_public': True}, headers=_auth(tok))
    assert r.status_code == 200, r.get_json()

    sq = c.get('/api/learning/certificates/square?kind=system&sort=hot',
               headers=_auth(peer_tok)).get_json()
    hit = next((x for x in sq['items'] if x['kind'] == 'system' and x['id'] == cert.id), None)
    assert hit is not None and hit['verify_status'] == 'verified'
    assert '92' in (hit['subtitle'] or '') or hit['extra']['final_score'] == 0.92

    # 详情脱敏：他人能读，但走的是广场同款视图
    d = c.get(f'/api/learning/certificates/system/{cert.id}', headers=_auth(peer_tok))
    assert d.status_code == 200
    assert d.get_json()['owner']['username'] == 'share_sys_owner'

    # 颁发资产未被改写：证书表本身仍没有公开列，旁表一行搞定
    assert not hasattr(db.session.get(PathCertificate, cert.id), 'is_public')
    assert CertificateDisplay.query.filter_by(cert_kind='system',
                                              cert_id=cert.id).count() == 1


def test_share_posts_to_community_once(share_ctx):
    db = share_ctx['db']
    from database.models import CommunityPost, Notification, CertificateDisplay
    c = share_ctx['c']
    tok, user = _register(c, 'share_post_owner')
    cert = _new_social_cert(c, tok, title='一级建造师证书')

    r = c.post(f'/api/learning/certificates/social/{cert["id"]}/share',
               json={'note': '备考三个月的一点记录'}, headers=_auth(tok))
    assert r.status_code == 201, r.get_json()
    body = r.get_json()
    post = db.session.get(CommunityPost, body['post_id'])
    assert post.category == 'experience'
    assert post.title.startswith('[荣誉证书] 一级建造师证书')
    assert '我想说的话' in post.content and '证书本体与佐证材料不随帖外发' in post.content
    assert post.is_anonymous is False
    assert '社会第三方' in (post.tags or '')
    # 分享即公开
    assert body['is_public'] is True
    d = CertificateDisplay.query.filter_by(cert_kind='social', cert_id=cert['id']).first()
    assert d.share_post_id == post.id and d.is_public is True

    # 通知是旁路：发了帖就该有一条站内信指向该帖
    n = (Notification.query.filter_by(user_id=user['id'], related_type='community_post')
         .order_by(Notification.id.desc()).first())
    assert n is not None and n.related_id == post.id

    # 连点两次不刷重复帖
    r2 = c.post(f'/api/learning/certificates/social/{cert["id"]}/share',
                json={}, headers=_auth(tok))
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()['existed'] is True and r2.get_json()['post_id'] == post.id
    assert CommunityPost.query.filter(CommunityPost.title.like('%一级建造师证书%')).count() == 1

    # 帖被删掉后再分享：清掉死引用、重新发新帖
    post.deleted = True
    db.session.commit()
    r3 = c.post(f'/api/learning/certificates/social/{cert["id"]}/share',
                json={}, headers=_auth(tok))
    assert r3.status_code == 201, r3.get_json()
    assert r3.get_json()['post_id'] != post.id


def test_delete_cert_leaves_no_square_orphan(share_ctx):
    db = share_ctx['db']
    from database.models import CertificateDisplay
    c = share_ctx['c']
    tok, user = _register(c, 'share_del_owner')
    peer_tok, _ = _register(c, 'share_del_peer')
    cert = _new_social_cert(c, tok, title='日语能力测试N2证书')
    c.put(f'/api/learning/certificates/social/{cert["id"]}/display',
          json={'is_public': True}, headers=_auth(tok))
    assert c.get('/api/learning/certificates/square?q=日语能力测试',
                 headers=_auth(peer_tok)).get_json()['total'] == 1

    assert c.delete(f'/api/learning/certificates/social/{cert["id"]}',
                    headers=_auth(tok)).status_code == 200
    assert c.get('/api/learning/certificates/square?q=日语能力测试',
                 headers=_auth(peer_tok)).get_json()['total'] == 0
    assert CertificateDisplay.query.filter_by(cert_kind='social',
                                              cert_id=cert['id']).count() == 0
