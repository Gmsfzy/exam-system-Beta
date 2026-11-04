# -*- coding: utf-8 -*-
"""v6.4 证书中心 E2E：社会/第三方证书上传 → 待核验 → 教师核验 → 证书墙聚合。

走真实 app + test_client（Bearer token 请求 CSRF 自动豁免），全程 conftest
改指的会话临时库，绝不触碰 instance 真库。覆盖：登记/类别降级/空标题拒绝、
聚合墙分组与核验角标、待核验教师门禁、核验通过落库+通知、删除权限。
"""
import pytest


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _register(client, username, role):
    r = client.post('/api/register', json={
        'username': username, 'password': 'cert-pw-123', 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    return body['token'], body['user']


@pytest.fixture(scope='module')
def cert_ctx():
    import app as prod
    from database import db

    prod._boot_done.set()                 # 跳过 bootstrap：不跑迁移/不起调度
    prod.app.config['TESTING'] = True
    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False       # 限流非被测目标

    with prod.app.app_context():
        import database.models           # noqa: F401
        import competition.models        # noqa: F401
        db.create_all()
        client = prod.app.test_client()
        yield {'c': client, 'app': prod.app}
        db.session.remove()


def test_social_cert_submit_and_verify_flow(cert_ctx):
    from database import db
    from database.models import UserCertificate, Notification
    c = cert_ctx['c']
    t_tok, t_user = _register(c, 'cert_teacher', 'teacher')
    s_tok, s_user = _register(c, 'cert_student', 'student')

    # 学生提交社会证书（无附件）→ 待核验
    r = c.post('/api/learning/certificates/social',
               data={'category': 'language', 'title': '全国大学英语六级证书',
                     'issuer': '教育部教育考试院', 'grade': '520 分',
                     'earned_date': '2024-06-01'},
               headers=_auth(s_tok), content_type='multipart/form-data')
    assert r.status_code == 201, r.get_json()
    cert = r.get_json()['certificate']
    cid = cert['id']
    assert cert['verify_status'] == 'pending'
    assert cert['category'] == 'language'

    # 学生证书墙：social 分组计数 1，带待核验角标
    r = c.get('/api/learning/certificates/wall', headers=_auth(s_tok))
    assert r.status_code == 200
    wall = r.get_json()
    assert wall['tabs']['social'] == 1
    item = next(x for x in wall['items'] if x['kind'] == 'social')
    assert item['group'] == 'social' and item['verify_status'] == 'pending'

    # 学生无权访问全站待核验列表 → 403
    assert c.get('/api/learning/certificates/social/pending',
                 headers=_auth(s_tok)).status_code == 403

    # 教师待核验列表含该条
    r = c.get('/api/learning/certificates/social/pending', headers=_auth(t_tok))
    assert r.status_code == 200
    assert any(x['id'] == cid for x in r.get_json()['items'])

    # 教师核验通过
    r = c.post(f'/api/learning/certificates/social/{cid}/verify',
               json={'action': 'verify', 'note': '已核对原件'}, headers=_auth(t_tok))
    assert r.status_code == 200
    assert r.get_json()['certificate']['verify_status'] == 'verified'

    # 学生墙刷新为已核验
    r = c.get('/api/learning/certificates/wall', headers=_auth(s_tok))
    item = next(x for x in r.get_json()['items'] if x['kind'] == 'social')
    assert item['verify_status'] == 'verified'

    # 统一详情分发：social/{id}
    r = c.get(f'/api/learning/certificates/social/{cid}', headers=_auth(s_tok))
    assert r.status_code == 200 and r.get_json()['verify_status'] == 'verified'

    # 落库 + 核验结果通知
    with cert_ctx['app'].app_context():
        db_cert = db.session.get(UserCertificate, cid)
        assert db_cert.verify_status == 'verified'
        assert db_cert.verified_by == t_user['id']
        assert Notification.query.filter_by(
            user_id=s_user['id'], related_type='certificate').count() == 1


def test_category_downgrade_and_delete_perms(cert_ctx):
    c = cert_ctx['c']
    s_tok, _ = _register(c, 'cert_student2', 'student')
    o_tok, _ = _register(c, 'cert_student3', 'student')

    # 非法类别降级为 other
    r = c.post('/api/learning/certificates/social',
               data={'category': 'nonsense', 'title': '一级建造师'},
               headers=_auth(s_tok), content_type='multipart/form-data')
    assert r.status_code == 201
    assert r.get_json()['certificate']['category'] == 'other'
    cid = r.get_json()['certificate']['id']

    # 空标题拒绝 → 400
    r = c.post('/api/learning/certificates/social', data={'title': '   '},
               headers=_auth(s_tok), content_type='multipart/form-data')
    assert r.status_code == 400

    # 他人无权删除 → 403；本人删除 → 200
    assert c.delete(f'/api/learning/certificates/social/{cid}',
                    headers=_auth(o_tok)).status_code == 403
    assert c.delete(f'/api/learning/certificates/social/{cid}',
                    headers=_auth(s_tok)).status_code == 200
