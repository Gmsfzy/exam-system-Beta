# -*- coding: utf-8 -*-
"""v7.19 学习心得 E2E：固定三段 + 周期归档 → 公开/分享社区 → AI 初稿。

走真实 app + test_client，conftest 已把库指向会话临时 sqlite。覆盖：三段至少填一段、
单段限长、周期默认按本地日历整周期倒推（日界不能按 UTC 切）、阶段/自定义周期必须说清
起止或阶段名、标签清洗（去重/限数/拒斜杠）、列表预览与周期计数、他人读公开心得计浏览
且私有对外 404、分享到社区经验帖与幂等回原帖、AI 初稿的额度三步与降级/失败分支、
数据摘要 _insight_facts 只用聚合数字不外传原文。
"""
import pytest


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _register(client, username, role='student'):
    r = client.post('/api/register', json={
        'username': username, 'password': 'ins-pw-123', 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    return body['token'], body['user']


@pytest.fixture(scope='module')
def ins_ctx():
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


def test_create_requires_at_least_one_section(ins_ctx):
    db = ins_ctx['db']
    from database.models import StudyInsight
    c = ins_ctx['c']
    tok, _ = _register(c, 'ins_owner')

    # 三段全空：拒绝——一条心得至少要说出一段东西
    r = c.post('/api/learning/insights', json={'title': '空的心得'}, headers=_auth(tok))
    assert r.status_code == 400 and '至少' in r.get_json()['message']

    # 单段过长：拒绝并点名是哪一段
    r = c.post('/api/learning/insights',
               json={'gains': '长' * 4001}, headers=_auth(tok))
    assert r.status_code == 400 and '学习感悟与收获' in r.get_json()['message']

    # 只写反思那一栏也算一条心得（不能要求三段齐）
    r = c.post('/api/learning/insights',
               json={'title': '第一周复盘', 'period_type': 'week',
                     'reflection': '把错题按知识点重做了一遍，下一步给自己出 10 道题。',
                     'tags': ['#刷题', '刷题', '矩阵/特征值', '线性代数']},
               headers=_auth(tok))
    assert r.status_code == 201, r.get_json()
    i = r.get_json()['insight']
    assert i['gains'] == '' and i['reflection'].startswith('把错题')
    assert i['summary'] == '' and i['word_count'] > 0
    # 标签清洗：去井号、去重、含斜杠的丢弃
    assert i['tags'] == ['刷题', '线性代数']


def test_default_period_follows_local_calendar(ins_ctx):
    """不给起止日期时按本地日历倒推整周期：日界走本地，按 UTC 切会在凌晨少算一天。"""
    from utils.timeutil import local_today
    from datetime import timedelta
    c = ins_ctx['c']
    tok, _ = _register(c, 'ins_period')
    today = local_today()

    for pt, span in (('day', 1), ('week', 7), ('month', 30)):
        r = c.post('/api/learning/insights',
                   json={'period_type': pt, 'gains': '今天把第 3 章过了一遍'},
                   headers=_auth(tok))
        assert r.status_code == 201, r.get_json()
        i = r.get_json()['insight']
        assert i['period_start'][:10] == (today - timedelta(days=span - 1)).isoformat()
        assert i['period_end'][:10] == today.isoformat()
        # 标题留空自动起名，卡片仍有周期可读
        assert i['title'].endswith('学习心得') and i['period_text']
        assert i['period_label'] in ('按日', '按周', '按月')


def test_period_validation(ins_ctx):
    c = ins_ctx['c']
    tok, _ = _register(c, 'ins_period_bad')

    assert c.post('/api/learning/insights',
                  json={'period_type': 'hour', 'gains': 'x'},
                  headers=_auth(tok)).status_code == 400
    # 阶段/自定义既没起止也没阶段名 → 服务端猜不出这段是什么
    assert c.post('/api/learning/insights',
                  json={'period_type': 'stage', 'gains': 'x'},
                  headers=_auth(tok)).status_code == 400
    r = c.post('/api/learning/insights',
               json={'period_type': 'stage', 'period_note': '期末冲刺两周',
                     'gains': '把历年真题按题型刷了一遍'}, headers=_auth(tok))
    assert r.status_code == 201, r.get_json()
    assert r.get_json()['insight']['period_text'].startswith('期末冲刺两周')

    assert c.post('/api/learning/insights',
                  json={'period_type': 'custom',
                        'period_start': '2026-11-10T00:00:00',
                        'period_end': '2026-11-01T00:00:00', 'gains': 'x'},
                  headers=_auth(tok)).status_code == 400


def test_list_previews_and_filters(ins_ctx):
    c = ins_ctx['c']
    tok, _ = _register(c, 'ins_list')
    for pt, gains in (('day', '今天只把上一章的错题重做了一遍，收获是把公式重新推了一遍。'),
                      ('week', '本周把线性代数推进了两节，卡在特征值那部分。'),
                      ('month', '这个月主要在做题，正确率从六成爬到七成五。')):
        assert c.post('/api/learning/insights',
                      json={'period_type': pt, 'gains': gains, 'tags': ['复盘']},
                      headers=_auth(tok)).status_code == 201

    r = c.get('/api/learning/insights', headers=_auth(tok))
    assert r.status_code == 200
    body = r.get_json()
    assert body['total'] == 3 and body['tabs']['all'] == 3
    assert body['tabs']['day'] == body['tabs']['week'] == body['tabs']['month'] == 1
    assert body['section_labels']['reflection'] == '反思创造'
    it = body['items'][0]
    assert 'gains' not in it and set(it['previews']) == {'gains', 'summary', 'reflection'}
    assert len(it['previews']['gains']) <= 60 and it['word_count'] > 0

    # 筛选：周期 / 标签 / 关键词（正文也参与匹配）
    assert c.get('/api/learning/insights', query_string={'period': 'week'},
                 headers=_auth(tok)).get_json()['total'] == 1
    assert c.get('/api/learning/insights', query_string={'tag': '复盘'},
                 headers=_auth(tok)).get_json()['total'] == 3
    assert c.get('/api/learning/insights', query_string={'tag': '没这个标签'},
                 headers=_auth(tok)).get_json()['total'] == 0
    got = c.get('/api/learning/insights', query_string={'q': '特征值'},
                headers=_auth(tok)).get_json()
    assert got['total'] == 1 and got['tabs']['all'] == 3   # 计数不随筛选变


def test_public_detail_visibility_and_views(ins_ctx):
    db = ins_ctx['db']
    from database.models import StudyInsight
    c = ins_ctx['c']
    owner_tok, owner = _register(c, 'ins_pub_owner')
    peer_tok, peer = _register(c, 'ins_pub_peer')
    r = c.post('/api/learning/insights',
               json={'title': '关于错题的一点点想法', 'period_type': 'week',
                     'gains': '把错题按知识点归档后，重做效率明显高了。',
                     'reflection': '下一步：把每道错题改造成一道可以自己出的题。'},
               headers=_auth(owner_tok))
    iid = r.get_json()['insight']['id']

    # 私有：他人读 = 404（不回「无权限」，免得公开开关变成探测点）
    assert c.get(f'/api/learning/insights/{iid}', headers=_auth(peer_tok)).status_code == 404
    # 教师也没有默认读权：心得是私人复盘，不是作业
    t_tok, _ = _register(c, 'ins_pub_teacher', 'teacher')
    assert c.get(f'/api/learning/insights/{iid}', headers=_auth(t_tok)).status_code == 404

    assert c.put(f'/api/learning/insights/{iid}/public', json={'is_public': True},
                 headers=_auth(owner_tok)).status_code == 200

    d = c.get(f'/api/learning/insights/{iid}', headers=_auth(peer_tok))
    assert d.status_code == 200
    body = d.get_json()
    assert body['owner'] == {'id': owner['id'], 'username': 'ins_pub_owner'}
    assert body['gains'].startswith('把错题') and body['section_labels']['summary']
    assert body['views'] == 1
    assert db.session.get(StudyInsight, iid).views == 1

    # 他人主页只列公开的
    lst = c.get(f"/api/learning/insights/user/{owner['id']}",
                headers=_auth(peer_tok)).get_json()
    assert lst['username'] == 'ins_pub_owner' and [x['id'] for x in lst['items']] == [iid]
    c.post('/api/learning/insights', json={'period_type': 'day', 'gains': '今天不想公开的一条'},
           headers=_auth(owner_tok))
    lst2 = c.get(f"/api/learning/insights/user/{owner['id']}",
                 headers=_auth(peer_tok)).get_json()
    assert [x['id'] for x in lst2['items']] == [iid]

    # 撤销公开后他人再读就 404
    c.put(f'/api/learning/insights/{iid}/public', json={'is_public': False},
          headers=_auth(owner_tok))
    assert c.get(f'/api/learning/insights/{iid}', headers=_auth(peer_tok)).status_code == 404


def test_update_and_delete_permissions(ins_ctx):
    db = ins_ctx['db']
    from database.models import StudyInsight
    c = ins_ctx['c']
    owner_tok, _ = _register(c, 'ins_ed_owner')
    peer_tok, _ = _register(c, 'ins_ed_peer')

    iid = c.post('/api/learning/insights',
                 json={'title': '第 5 周', 'period_type': 'week',
                       'gains': '原始收获'}, headers=_auth(owner_tok)
                 ).get_json()['insight']['id']

    # 标题不能改成空；三段不能全改空
    assert c.put(f'/api/learning/insights/{iid}', json={'title': '  '},
                 headers=_auth(owner_tok)).status_code == 400
    assert c.put(f'/api/learning/insights/{iid}',
                 json={'gains': '', 'summary': '', 'reflection': ''},
                 headers=_auth(owner_tok)).status_code == 400

    r = c.put(f'/api/learning/insights/{iid}',
              json={'title': '第 5 周（改）', 'period_type': 'month',
                    'gains': '改过的收获', 'summary': '新增的一段总结',
                    'tags': ['周', '月']}, headers=_auth(owner_tok))
    assert r.status_code == 200
    i = r.get_json()['insight']
    assert i['summary'] == '新增的一段总结' and i['gains'] == '改过的收获'
    assert i['period_type'] == 'month' and i['period_start'][:10]
    # 没传起止时保留原周期含义（month 由旧起止补齐，不静默跳到最新 30 天窗口）
    assert i['period_end'] and i['tags'] == ['周', '月']

    # 他人改不了也删不了：一律 404（不透露存在）
    assert c.put(f'/api/learning/insights/{iid}', json={'gains': 'x'},
                 headers=_auth(peer_tok)).status_code == 404
    assert c.delete(f'/api/learning/insights/{iid}', headers=_auth(peer_tok)).status_code == 404
    assert c.get('/api/learning/insights/999999', headers=_auth(owner_tok)).status_code == 404

    assert c.delete(f'/api/learning/insights/{iid}', headers=_auth(owner_tok)).status_code == 200
    assert db.session.get(StudyInsight, iid) is None


def test_share_to_community_once(ins_ctx):
    db = ins_ctx['db']
    from database.models import CommunityPost, Notification, StudyInsight
    c = ins_ctx['c']
    tok, user = _register(c, 'ins_share_owner')

    iid = c.post('/api/learning/insights',
                 json={'title': '把错题变成题', 'period_type': 'week',
                       'gains': '重做错题比刷新题划算。',
                       'reflection': '自己出一套 10 题的周练，找同学互批。'},
                 headers=_auth(tok)).get_json()['insight']['id']

    r = c.post(f'/api/learning/insights/{iid}/share',
               json={'note': '欢迎评论区交流'}, headers=_auth(tok))
    assert r.status_code == 201, r.get_json()
    post = db.session.get(CommunityPost, r.get_json()['post_id'])
    assert post.category == 'experience' and post.title == '[学习心得] 把错题变成题'
    assert '## 学习感悟与收获' in post.content and '## 反思创造' in post.content
    assert '## 我的心得与总结' not in post.content      # 空段不进帖子
    assert '欢迎评论区交流' in post.content and '按周' in (post.tags or '')
    assert post.is_anonymous is False

    i = db.session.get(StudyInsight, iid)
    assert i.is_public is True and i.share_post_id == post.id     # 分享即公开
    n = (Notification.query.filter_by(user_id=user['id'], related_type='community_post')
         .order_by(Notification.id.desc()).first())
    assert n is not None and n.related_id == post.id

    r2 = c.post(f'/api/learning/insights/{iid}/share', json={}, headers=_auth(tok))
    assert r2.status_code == 200 and r2.get_json()['existed'] is True
    assert r2.get_json()['post_id'] == post.id
    assert CommunityPost.query.filter_by(title='[学习心得] 把错题变成题').count() == 1

    # 原帖被删后再分享：清死引用重发新帖
    post.deleted = True
    db.session.commit()
    r3 = c.post(f'/api/learning/insights/{iid}/share', json={}, headers=_auth(tok))
    assert r3.status_code == 201 and r3.get_json()['post_id'] != post.id

    # 删心得不连带删帖：帖子在社区有独立的删除流程
    c.delete(f'/api/learning/insights/{iid}', headers=_auth(tok))
    assert db.session.get(CommunityPost, r3.get_json()['post_id']).deleted is False


def test_insight_facts_only_aggregates(ins_ctx):
    """喂给 AI 的事实清单只用聚合数字与资料类型，不含笔记/资料原文。"""
    from database import db
    from database.models import StudyLog, StudyCheckin, StudyNote, StudyMaterial
    from api.learning_routes import _insight_facts
    from utils.timeutil import utcnow, local_today

    c = ins_ctx['c']
    tok, user = _register(c, 'ins_facts')
    uid = user['id']

    db.session.add(StudyLog(user_id=uid, log_type='practice', total_questions=20,
                            correct_count=15, score_ratio=0.75, time_spent_sec=1200,
                            studied_at=utcnow()))
    db.session.add(StudyCheckin(user_id=uid, day=local_today(), minutes=35,
                                tasks_done=3, mood='calm'))
    db.session.add(StudyNote(user_id=uid, title='课堂笔记',
                             content='这段原文不该出现在事实清单里'))
    db.session.add(StudyMaterial(user_id=uid, kind='lesson_plan',
                                 title='教案一份', content='这段原文也不该出现',
                                 status='active'))
    db.session.commit()

    facts = _insight_facts(uid, 7)
    assert '练习题量 20 道' in facts and '正确率 75%' in facts
    assert '打卡 1 天' in facts and '教案（教学设计） 1 份' in facts
    assert '这段原文不该出现在事实清单里' not in facts
    assert '这段原文也不该出现' not in facts
    # days 越界夹紧，不接受前端传来的负数/超大值
    assert '最近 1 天' in _insight_facts(uid, 0)
    assert '最近 120 天' in _insight_facts(uid, 9999)


def test_ai_draft_quota_and_degrade_paths(ins_ctx, monkeypatch):
    db = ins_ctx['db']
    from database.models import AiQuota, AiUsageLog
    import ai_service.services as svc
    c = ins_ctx['c']
    tok, user = _register(c, 'ins_ai')

    calls = {}

    def fake_draft(session, facts, focus=None):
        calls['facts'] = facts
        calls['focus'] = focus
        return ({'title': '这周的复盘', 'gains': '完成 20 道题。',
                 'summary': '', 'reflection': '下周给自己出十道题。'}, False)

    monkeypatch.setattr(svc, 'ai_generate_insight_draft', fake_draft)

    r = c.post('/api/learning/insights/ai-draft',
               json={'days': 7, 'focus': '卡在矩阵'}, headers=_auth(tok))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body['degraded'] is False and body['draft']['gains'] == '完成 20 道题。'
    assert body['facts'].startswith('统计区间：最近 7 天')
    assert calls['focus'] == '卡在矩阵' and '练习题量' in calls['facts']
    # AI 初稿不落库：只回草稿，等用户改完自己保存
    from database.models import StudyInsight
    assert StudyInsight.query.filter_by(user_id=user['id']).count() == 0

    q = db.session.query(AiQuota).filter_by(user_id=user['id']).first()
    assert q is not None and q.used_today == 1     # 新用户当日首次调用：额度扣 1 次
    log = (AiUsageLog.query.filter_by(user_id=user['id'], action='insight')
           .order_by(AiUsageLog.id.desc()).first())
    assert log is not None and log.status == 'success'

    # 降级：services 内部返回 degraded 时额度照扣、日志记 degraded（与资料生成同档处理）
    monkeypatch.setattr(svc, 'ai_generate_insight_draft',
                        lambda s, f, fc=None: ({'title': '框架', 'gains': '待填写'}, True))
    r2 = c.post('/api/learning/insights/ai-draft', json={'days': 7}, headers=_auth(tok))
    assert r2.status_code == 200 and r2.get_json()['degraded'] is True
    assert '待填写框架' in r2.get_json()['message']
    assert AiUsageLog.query.filter_by(user_id=user['id'], status='degraded').count() == 1

    # 没有可用数据时 services 抛 ValueError → 400，不该记成功日志
    def boom(session, facts, focus=None):
        raise ValueError('没有可用的学习数据，无需生成初稿')
    monkeypatch.setattr(svc, 'ai_generate_insight_draft', boom)
    r3 = c.post('/api/learning/insights/ai-draft', json={'days': 7}, headers=_auth(tok))
    assert r3.status_code == 400 and '没有可用' in r3.get_json()['message']

    # 额度用完：429 且不碰 AI
    q.used_today = q.daily_limit
    db.session.commit()
    monkeypatch.setattr(svc, 'ai_generate_insight_draft', fake_draft)
    r4 = c.post('/api/learning/insights/ai-draft', json={'days': 7}, headers=_auth(tok))
    assert r4.status_code == 429 and '额度' in r4.get_json()['message']


def test_unauthorized_access_blocked(ins_ctx):
    c = ins_ctx['c']
    assert c.get('/api/learning/insights').status_code == 401
    assert c.get('/api/learning/insights/user/1').status_code == 401
    # 未登录的 POST 先被 CSRF 拦下（400），拿到 token 但没权限才走 401/404 分支
    assert c.post('/api/learning/insights', json={'gains': 'x'}).status_code in (400, 401)
    tok, _ = _register(c, 'ins_guard')
    assert c.put('/api/learning/insights/1/public',
                 json={'is_public': True}, headers=_auth(tok)).status_code == 404
