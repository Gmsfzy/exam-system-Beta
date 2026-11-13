# -*- coding: utf-8 -*-
"""v7.14 自主学习链路打通回归（HTTP 层，真实 app + test_client）。

覆盖走查发现的两个断点：
  GET /api/learning/my-knowledge   知识点卡片带出本人 active 资料（知识库↔资料库）
  GET /api/learning/plans/<id>     单份计划详情（前端 /learning/plan?plan=id 深链的服务端支撑）
全程走 conftest 改指的会话临时库，绝不触碰 instance/exam_system.db。
"""
import pytest


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _register(client, username, role='student'):
    r = client.post('/api/register', json={
        'username': username, 'password': 'link-pw-123', 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    return body['token'], body['user']


@pytest.fixture(scope='module')
def ctx():
    import app as prod
    from database import db

    prod._boot_done.set()                 # 跳过 bootstrap：不跑迁移/不起调度
    prod.app.config['TESTING'] = True
    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False       # 限流非被测目标

    with prod.app.app_context():
        import database.models            # noqa: F401
        db.create_all()
        yield {'c': prod.app.test_client(), 'app': prod.app}
        db.session.remove()


def _seed_knowledge(owner_id, other_id):
    """专业→课程→章节→5 个知识点，配掌握度/笔记/资料（含不该露出的三类）

    故意留两个“只写过资料”与“只记过笔记”的知识点：知识库入口不能只看掌握度，
    否则只用 AI 生成过教案、还没刷过题的账号整页是空的。
    """
    from database import db
    from database.models import (Chapter, Course, KnowledgeMastery, KnowledgePoint,
                                 Major, StudyMaterial, UserKpNote)
    from utils.timeutil import utcnow

    major = Major(name='打通专业')
    course = Course(name='打通课程', major=major)
    chapter = Chapter(name='打通章节', course=course)
    kp_rich = KnowledgePoint(name='循环结构', chapter=chapter)
    kp_many = KnowledgePoint(name='函数定义', chapter=chapter)
    kp_bare = KnowledgePoint(name='异常处理', chapter=chapter)
    kp_doc = KnowledgePoint(name='队列', chapter=chapter)      # 只有教案，无掌握度
    kp_note = KnowledgePoint(name='递归', chapter=chapter)     # 只有笔记，无掌握度
    db.session.add_all([major, course, chapter, kp_rich, kp_many, kp_bare, kp_doc, kp_note])
    db.session.commit()

    for kp, level in ((kp_rich, 62.0), (kp_many, 30.0), (kp_bare, 10.0)):
        db.session.add(KnowledgeMastery(
            user_id=owner_id, knowledge_point_id=kp.id, level=level,
            last_verified_at=utcnow(), total_attempts=5, total_correct=3))

    mats = [
        StudyMaterial(user_id=owner_id, kind='lesson_plan', title='循环结构教案',
                      content='# 教案', knowledge_point_id=kp_rich.id),
        StudyMaterial(user_id=owner_id, kind='lecture', title='循环结构讲义',
                      content='# 讲义', knowledge_point_id=kp_rich.id),
        # 举报下架的资料不该出现在我的知识库里
        StudyMaterial(user_id=owner_id, kind='mindmap', title='已下架导图',
                      content='x', knowledge_point_id=kp_rich.id, status='removed'),
        # 他人公开资料属于广场，不属于「我的」
        StudyMaterial(user_id=other_id, kind='lecture', title='别人的讲义',
                      content='y', knowledge_point_id=kp_rich.id, is_public=True),
        # 未挂知识点的散装资料
        StudyMaterial(user_id=owner_id, kind='manual', title='散装手写', content='z'),
    ]
    # 单 KP 卡片只截最近若干份，总数由 material_count 给（造 10 份压这条上限）
    mats += [StudyMaterial(user_id=owner_id, kind='lecture', title=f'讲义 {i}',
                           content='c', knowledge_point_id=kp_many.id)
             for i in range(10)]
    mats += [StudyMaterial(user_id=owner_id, kind='lesson_plan', title='队列教案',
                           content='q', knowledge_point_id=kp_doc.id)]
    db.session.add_all(mats)
    db.session.add(UserKpNote(user_id=owner_id, knowledge_point_id=kp_note.id,
                              content='递归三要素：出口、自调用、规模缩小'))
    db.session.commit()
    return kp_rich, kp_many, kp_bare, kp_doc, kp_note


def _flat_kps(body):
    out = {}
    for major in body['majors']:
        for course in major['courses']:
            for chapter in course['chapters']:
                for kp in chapter['knowledge_points']:
                    out[kp['knowledge_point_id']] = kp
    return out


def test_my_knowledge_carries_own_materials(ctx):
    c = ctx['c']
    tok, me = _register(c, 'lk_owner')
    _, other = _register(c, 'lk_other')
    kp_rich, kp_many, kp_bare, kp_doc, kp_note = _seed_knowledge(me['id'], other['id'])

    r = c.get('/api/learning/my-knowledge', headers=_auth(tok))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    kps = _flat_kps(body)

    item = kps[kp_rich.id]
    assert item['material_count'] == 2
    assert {m['title'] for m in item['materials']} == {'循环结构教案', '循环结构讲义'}
    assert {m['kind'] for m in item['materials']} == {'lesson_plan', 'lecture'}
    assert all(m['id'] for m in item['materials'])

    # 超上限：列表截断但总数如实，前端才能显示「共 N 份，到资料库看全部」
    many = kps[kp_many.id]
    assert many['material_count'] == 10
    assert len(many['materials']) == 8

    # 零资料：空列表而非缺字段，前端可稳定判空
    bare = kps[kp_bare.id]
    assert bare['materials'] == [] and bare['material_count'] == 0

    # 只有资料、没掌握度的知识点也得收录（资料本身就是资产）
    doc = kps[kp_doc.id]
    assert doc['material_count'] == 1 and doc['mastery_shown'] == 0
    assert doc['level_status'] == 'untouched'
    assert doc['materials'][0]['kind'] == 'lesson_plan'
    # 只有笔记的同样收录，且不会顺手把别人的资料挂上来
    assert kps[kp_note.id]['has_note'] is True and kps[kp_note.id]['material_count'] == 0
    assert body['total'] == 5, body['total']


def test_my_knowledge_requires_login(ctx):
    c = ctx['c']
    assert c.get('/api/learning/my-knowledge').status_code == 401


def test_plan_detail_supports_deep_link(ctx):
    c = ctx['c']
    tok, _ = _register(c, 'plan_owner')
    other_tok, _ = _register(c, 'plan_stranger')

    r = c.post('/api/learning/plans', json={
        'title': '深链计划', 'description': '十一月的 Python 基础',
        'start_date': '2026-11-01', 'end_date': '2026-12-01'}, headers=_auth(tok))
    assert r.status_code == 200, r.get_json()
    pid = r.get_json()['id']
    assert c.post(f'/api/learning/plans/{pid}/tasks', json={
        'title': '看完循环结构', 'task_type': 'knowledge_point',
        'estimated_minutes': 25}, headers=_auth(tok)).status_code == 200

    r = c.get(f'/api/learning/plans/{pid}', headers=_auth(tok))
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    # 字段与列表项同构：前端深链后可直接复用卡片渲染
    assert d['id'] == pid and d['title'] == '深链计划'
    assert d['tasks_total'] == 1 and d['tasks_done'] == 0
    assert d['tasks'][0]['title'] == '看完循环结构'
    assert {'progress', 'heat', 'overdue_count', 'time_pct'} <= set(d)

    # 列表接口仍能找到同一份，两端口径一致
    listed = next(p for p in c.get('/api/learning/plans', headers=_auth(tok)).get_json()
                  if p['id'] == pid)
    assert listed['tasks_total'] == d['tasks_total']
    assert listed['title'] == d['title']


def test_plan_detail_access_control(ctx):
    c = ctx['c']
    tok, _ = _register(c, 'plan_owner2')
    other_tok, _ = _register(c, 'plan_stranger2')
    pid = c.post('/api/learning/plans', json={'title': '私有计划'},
                 headers=_auth(tok)).get_json()['id']

    # 未登录 → 401；别人的计划 → 404（与不存在同口径，不泄漏标题）；不存在的 id → 404
    assert c.get(f'/api/learning/plans/{pid}').status_code == 401
    assert c.get(f'/api/learning/plans/{pid}', headers=_auth(other_tok)).status_code == 404
    assert c.get('/api/learning/plans/99999999', headers=_auth(tok)).status_code == 404
