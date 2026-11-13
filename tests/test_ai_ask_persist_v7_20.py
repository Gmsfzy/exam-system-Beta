# -*- coding: utf-8 -*-
"""v7.20 AI 输出留痕（HTTP 层，会话临时库）：答疑解析入库带复用 + 聊天回退分支补落库。

答疑此前是「算完就丢」：同一道错题反复点就反复烧额度、反复等十几秒外呼，而 doubt
被路由收下后根本不进 prompt——写不写疑问结果一模一样。现在锁住七件事：
① doubt 真的拼进 prompt；② 解析落 ai_ask_record，同指纹在窗口内命中回旧解，
且不扣额度、不写成本日志；③ refresh / 换疑问 / 换作答 / 超出窗口都会 miss；
④ 没 question_id 的拍题提问不再得到空字符串（旧代码那句 `if question_id else ''`）；
⑤ 端点不再下发 question_answer（它没有错题归因那套答案门控）；⑥ 额度用完 429 且不碰 AI；
⑦ 非流式 ai-chat 这一轮的用户句与助手句落库，流式已写过的尾条不重复补，他人会话 404。
"""
from datetime import timedelta

import pytest


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _register(client, username, role='student'):
    r = client.post('/api/register', json={
        'username': username, 'password': 'ask-pw-123', 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    return body['token'], body['user']


@pytest.fixture(scope='module')
def ask_ctx():
    import app as prod
    from database import db

    prod._boot_done.set()
    prod.app.config['TESTING'] = True
    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False

    with prod.app.app_context():
        import database.models        # noqa: F401
        db.create_all()
        yield {'c': prod.app.test_client(), 'db': db}
        db.session.remove()


@pytest.fixture(scope='module')
def ask_q(ask_ctx):
    """两道题：一题有标准答案，一题故意没有（拍题/无答案题的 prompt 不能拼出「标准答案：None」）。"""
    db = ask_ctx['db']
    from database.models import Major, Question

    major = Major(name='答疑留痕专业')
    db.session.add(major)
    db.session.flush()
    q1 = Question(content='设 f(x)=x^2，求 f(2)。', answer='4', type='subjective',
                  difficulty='easy', major_id=major.id)
    q2 = Question(content='矩阵 A 的秩怎么求？', answer='', type='subjective',
                  difficulty='medium', major_id=major.id)
    db.session.add_all([q1, q2])
    db.session.commit()
    return {'q1': q1, 'q2': q2, 'major': major}


def _fake_ark(store):
    """替身传输层：收下真实拼好的 prompt，返回固定解析。

    补在 client 最底层而不是 services 那层，是为了让「doubt 到底进没进 prompt」
    这条断言打到真实拼装逻辑上——打桩在 generate_analysis 就等于自己验自己。
    """
    def send(prompt, *a, **kw):
        store.append(prompt)
        return '先按定义代入 x=2，考点是函数求值，别把平方漏掉。'
    return send


def test_ask_doubt_reaches_prompt_and_persists(ask_ctx, ask_q, monkeypatch):
    db = ask_ctx['db']
    from database.models import AiAskRecord, AiQuota, AiUsageLog
    import ai_service.services as svc

    c = ask_ctx['c']
    tok, me = _register(c, 'ask_owner')
    calls = []
    monkeypatch.setattr(svc.ai_client, '_send_ark_request', _fake_ark(calls))

    r = c.post('/api/learning/ask', json={
        'question_id': ask_q['q1'].id, 'doubt': '卡在第二步移项',
        'student_answer': '我写成 f(2)=2 了'}, headers=_auth(tok))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body['source'] == 'ai' and body['cached'] is False
    assert body['analysis'].startswith('先按定义代入')
    # 该端点没有 _source_still_reanswerable 那套答案门控，源仍可重答时它等于直接发答案
    assert 'question_answer' not in body

    assert len(calls) == 1
    assert '学生的疑问：卡在第二步移项' in calls[0]
    assert '请先直接回答学生的疑问' in calls[0]
    assert '学生作答：我写成' in calls[0]
    assert '标准答案：None' not in calls[0]

    rec = AiAskRecord.query.filter_by(user_id=me['id']).one()
    assert rec.question_id == ask_q['q1'].id
    assert rec.doubt == '卡在第二步移项' and rec.student_answer == '我写成 f(2)=2 了'
    assert rec.question_content.startswith('设 f(x)') and rec.source == 'ai'
    assert len(rec.fingerprint) == 40 and rec.hit_count == 1
    assert rec.analysis == body['analysis']        # 库里存的正是回给前端的那份

    quota = db.session.query(AiQuota).filter_by(user_id=me['id']).first()
    assert quota is not None and quota.used_today == 1
    assert AiUsageLog.query.filter_by(user_id=me['id'], action='ask').count() == 1


def test_ask_reuse_window_costs_nothing(ask_ctx, ask_q, monkeypatch):
    from database.models import AiAskRecord, AiQuota, AiUsageLog
    import ai_service.services as svc

    c = ask_ctx['c']
    tok, me = _register(c, 'ask_reuse')
    calls = []
    monkeypatch.setattr(svc.ai_client, '_send_ark_request', _fake_ark(calls))

    payload = {'question_id': ask_q['q1'].id, 'doubt': '为什么可以直接代入', 'student_answer': ''}
    r1 = c.post('/api/learning/ask', json=payload, headers=_auth(tok))
    assert r1.status_code == 200 and r1.get_json()['cached'] is False
    assert AiQuota.query.filter_by(user_id=me['id']).first().used_today == 1

    r2 = c.post('/api/learning/ask', json=payload, headers=_auth(tok))
    assert r2.status_code == 200, r2.get_json()
    body2 = r2.get_json()
    assert body2['cached'] is True and body2['source'] == 'cache'
    assert body2['analysis'] == r1.get_json()['analysis']
    assert '未消耗今日额度' in body2['message']
    # 复用没打外呼，就不该出现在成本表里：否则治理页的调用数会被虚抬成从未发生的外呼
    assert len(calls) == 1
    assert AiAskRecord.query.filter_by(user_id=me['id']).count() == 1
    assert AiAskRecord.query.filter_by(user_id=me['id']).first().hit_count == 2
    assert AiQuota.query.filter_by(user_id=me['id']).first().used_today == 1
    assert AiUsageLog.query.filter_by(user_id=me['id'], action='ask').count() == 1

    # refresh=true：想换个思路再问一次的人，不该被自己的历史回答挡着
    r3 = c.post('/api/learning/ask', json=dict(payload, refresh=True), headers=_auth(tok))
    assert r3.status_code == 200 and r3.get_json()['cached'] is False
    assert len(calls) == 2 and AiQuota.query.filter_by(user_id=me['id']).first().used_today == 2
    assert AiAskRecord.query.filter_by(user_id=me['id']).count() == 2


def test_ask_miss_on_every_key_change(ask_ctx, ask_q, monkeypatch):
    """四元组任一维变了就 miss：换疑问、换作答、超出窗口，都不能把旧解析硬套上去。"""
    from database.models import AiAskRecord
    from utils.timeutil import utcnow
    from api.learning_routes import ASK_REUSE_DAYS
    import ai_service.services as svc

    db = ask_ctx['db']
    c = ask_ctx['c']
    tok, me = _register(c, 'ask_miss')
    calls = []
    monkeypatch.setattr(svc.ai_client, '_send_ark_request', _fake_ark(calls))
    base = {'question_id': ask_q['q1'].id, 'doubt': '移项为什么变号', 'student_answer': '3'}

    assert c.post('/api/learning/ask', json=base, headers=_auth(tok)).get_json()['cached'] is False
    for changed in ({'doubt': '那定义域要不要管'}, {'student_answer': '我把平方漏了'}):
        r = c.post('/api/learning/ask', json=dict(base, **changed), headers=_auth(tok))
        assert r.status_code == 200 and r.get_json()['cached'] is False, changed
    assert len(calls) == 3

    # 超出复用窗口：同指纹也不再回用（历史答案不该被当成今天的解析）
    rec = AiAskRecord.query.filter_by(user_id=me['id']).order_by(AiAskRecord.id).first()
    rec.created_at = utcnow() - timedelta(days=ASK_REUSE_DAYS + 1)
    db.session.commit()
    r = c.post('/api/learning/ask', json=base, headers=_auth(tok))
    assert r.status_code == 200 and r.get_json()['cached'] is False
    assert len(calls) == 4


def test_ask_photo_question_without_id(ask_ctx, ask_q, monkeypatch):
    """拍题提问：没有 question_id 也要出解析。旧代码那句 `if question_id else ''` 只会回空串。"""
    db = ask_ctx['db']
    from database.models import AiAskRecord
    import ai_service.services as svc

    c = ask_ctx['c']
    tok, me = _register(c, 'ask_photo')
    calls = []
    monkeypatch.setattr(svc.ai_client, '_send_ark_request', _fake_ark(calls))

    r = c.post('/api/learning/ask', json={
        'question_content': '矩阵 A 的秩怎么求？', 'doubt': '行变换到什么时候算完'}, headers=_auth(tok))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['analysis']
    assert len(calls) == 1
    assert '题目：矩阵 A 的秩怎么求' in calls[0]
    assert '标准答案' not in calls[0]      # 无标准答案时不能拼出脏行

    rec = AiAskRecord.query.filter_by(user_id=me['id']).one()
    assert rec.question_id is None and rec.question_content.startswith('矩阵')
    assert rec.student_answer is None      # 空串入库前归一成 NULL，不给以后统计添一种「空但有值」

    # 既没题面又没疑问：400，且不碰 AI 也不扣额度
    before = db.session.query(AiAskRecord).filter_by(user_id=me['id']).count()
    r2 = c.post('/api/learning/ask', json={'doubt': ''}, headers=_auth(tok))
    assert r2.status_code == 400 and '疑问' in r2.get_json()['message']
    assert len(calls) == 1 and before == 1

    # 题号不存在时不能当成拍题提问静默通过：services 抛 ValueError → 400，仍然没打外呼
    r3 = c.post('/api/learning/ask', json={'question_id': 999999, 'doubt': '这题怎么做'},
                headers=_auth(tok))
    assert r3.status_code == 400 and '缺少题目内容' in r3.get_json()['message']
    assert len(calls) == 1


def test_ask_quota_exhausted_skips_ai(ask_ctx, ask_q, monkeypatch):
    from database.models import AiQuota
    import ai_service.services as svc

    c = ask_ctx['c']
    tok, me = _register(c, 'ask_quota')
    calls = []
    monkeypatch.setattr(svc.ai_client, '_send_ark_request', _fake_ark(calls))

    db = ask_ctx['db']
    q = db.session.query(AiQuota).filter_by(user_id=me['id']).first()
    if q is None:                      # 额度行是首次调用时才建的，先烧一次把它建出来
        assert c.post('/api/learning/ask', json={'question_id': ask_q['q1'].id},
                      headers=_auth(tok)).status_code == 200
        q = db.session.query(AiQuota).filter_by(user_id=me['id']).first()
        assert len(calls) == 1
    q.used_today = q.daily_limit
    db.session.commit()

    r = c.post('/api/learning/ask', json={'question_id': ask_q['q2'].id, 'doubt': '秩怎么求'},
               headers=_auth(tok))
    assert r.status_code == 429 and '额度' in r.get_json()['message']
    assert len(calls) == 1             # 额度门控在 AI 之前，用完就不该再外呼


def test_ask_fingerprint_keys():
    """指纹只认这四元组：None 与空串同形，任何一维变化都换指纹。"""
    from api.learning_routes import _ask_fingerprint

    a = _ask_fingerprint(7, 3, '怎么移项', '')
    assert a == _ask_fingerprint(7, 3, '怎么移项', None)
    assert a != _ask_fingerprint(7, 3, '怎么移项', '空作答')
    assert a != _ask_fingerprint(7, 4, '怎么移项', '')
    assert a != _ask_fingerprint(8, 3, '怎么移项', '')
    assert a != _ask_fingerprint(7, 3, '怎么移项。', '')


def test_ai_chat_fallback_round_persists(ask_ctx, monkeypatch):
    """非流式这一轮要落库：前端只在流式失败时打到这里，同一聊天框「正常那几轮能回看、
    兜底那一轮刷新就没」比整体无状态更难解释。"""
    db = ask_ctx['db']
    from database.models import AiChatConversation, AiChatMessage, AiUsageLog

    c = ask_ctx['c']
    tok, me = _register(c, 'chat_fallback')
    got = []

    def fake_reply(session, messages, context=None):
        got.append(list(messages))
        return '我们先从特征值的定义入手。'

    import ai_service.services as svc
    monkeypatch.setattr(svc, 'ai_chat_reply', fake_reply)

    history = [{'role': 'user', 'content': '我第三章没学明白'},
               {'role': 'assistant', 'content': '先说下卡在哪一小节？'},
               {'role': 'user', 'content': '卡在特征值'}]
    r = c.post('/api/learning/ai-chat', json={'messages': history, 'context': '错题本'},
               headers=_auth(tok))
    assert r.status_code == 200, r.get_json()
    cid = r.get_json()['conversation_id']
    assert r.get_json()['reply'].startswith('我们先从特征值')

    conv = db.session.get(AiChatConversation, cid)
    assert conv.user_id == me['id'] and conv.title.startswith('卡在特征值')
    assert conv.context == '错题本'
    assert [m.role for m in sorted(conv.messages, key=lambda x: x.id)] == ['user', 'assistant']
    # 服务端只补本轮，历史仍由前端持有：不能把整段 messages 重灌一遍
    assert sorted(conv.messages, key=lambda x: x.id)[0].content == '卡在特征值'
    assert len(got[0]) == 3

    # 同一会话续聊：新的一句追加在旧的两条之后，不新建会话也不重复旧句
    r2 = c.post('/api/learning/ai-chat', json={
        'conversation_id': cid,
        'messages': history + [{'role': 'assistant', 'content': '定义式那块看过吗？'},
                               {'role': 'user', 'content': '看过但不会求特征多项式'}]},
        headers=_auth(tok))
    assert r2.status_code == 200 and r2.get_json()['conversation_id'] == cid
    msgs = sorted(AiChatMessage.query.filter_by(conversation_id=cid).all(), key=lambda x: x.id)
    assert len(msgs) == 4 and msgs[2].content == '看过但不会求特征多项式'
    assert [m.role for m in msgs] == ['user', 'assistant', 'user', 'assistant']

    # 流式端点是「先把 user 句落库、再开始流」的，中途挂掉回到这里时本轮用户句已在库里：
    # 尾条角色与内容都对得上就不能再补一条（靠内容而不是时间窗，免得到点错位）
    db.session.add(AiChatMessage(conversation_id=cid, role='user', content='半路断掉的提问'))
    db.session.commit()
    r3 = c.post('/api/learning/ai-chat', json={
        'conversation_id': cid,
        'messages': [{'role': 'user', 'content': '半路断掉的提问'}]}, headers=_auth(tok))
    assert r3.status_code == 200
    msgs = sorted(AiChatMessage.query.filter_by(conversation_id=cid).all(), key=lambda x: x.id)
    assert len(msgs) == 6
    assert [m.role for m in msgs[-2:]] == ['user', 'assistant']
    assert AiChatMessage.query.filter_by(conversation_id=cid, role='user',
                                         content='半路断掉的提问').count() == 1
    assert AiUsageLog.query.filter_by(user_id=me['id'], action='chat').count() == 3


def test_ai_chat_degrade_flag_and_guards(ask_ctx, monkeypatch):
    db = ask_ctx['db']
    from database.models import AiChatConversation, AiChatMessage

    c = ask_ctx['c']
    tok, me = _register(c, 'chat_guard')
    tok2, _ = _register(c, 'chat_other')
    import ai_service.services as svc

    monkeypatch.setattr(svc, 'ai_chat_reply',
                        lambda s, m, ctx=None: '【AI 服务暂不可用，以下为系统自动建议】\n先去错题本回顾')
    r = c.post('/api/learning/ai-chat', json={'messages': [{'role': 'user', 'content': '这题怎么做'}]},
               headers=_auth(tok))
    assert r.status_code == 200
    cid = r.get_json()['conversation_id']
    # 非流式今天失败就直接 500，这条分支是照着流式端点同一套语义补的：降级回复要能筛出来
    assert AiChatMessage.query.filter_by(conversation_id=cid, role='assistant').first().degraded is True

    # 别人的会话：404，不往里塞消息
    r2 = c.post('/api/learning/ai-chat', json={
        'conversation_id': cid, 'messages': [{'role': 'user', 'content': '借用一下'}]},
        headers=_auth(tok2))
    assert r2.status_code == 404 and db.session.get(AiChatConversation, cid).user_id == me['id']
    assert AiChatMessage.query.filter_by(role='user', content='借用一下').count() == 0

    # 参数与末条角色校验：都不该落到 AI
    assert c.post('/api/learning/ai-chat', json={'messages': 'x'}, headers=_auth(tok)).status_code == 400
    assert c.post('/api/learning/ai-chat', json={
        'messages': [{'role': 'assistant', 'content': '自问自答'}]}, headers=_auth(tok)).status_code == 400
    assert c.post('/api/learning/ai-chat', json={'messages': []}, headers=_auth(tok)).status_code == 400
    assert c.post('/api/learning/ai-chat', json={'messages': [{'role': 'user', 'content': '  '}]},
                  headers=_auth(tok)).status_code == 400
