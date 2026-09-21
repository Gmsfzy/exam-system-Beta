# -*- coding: utf-8 -*-
"""HTTP 层 E2E（v4.9）：真实 Flask app + test_client 走完整请求链。

定位：补函数层测试罩不到的主动脉——
  认证链（注册/登录/Bearer 解析/登出吊销/角色门禁/CSRF 前置门）、
  钱链（充值→发布托管→交叉审核→投稿→采纳释放→钱包账单形状，
        含赛事竞赛版：冻结→审核→结算释放/驳回退回）、
  分链（建卷→组卷→邀请→发布→开考→作答→交卷→成绩 HTTP 往返，
        含 PK 对战建房→应战→逐题→双方交卷→Elo/积分镜像、
        自由练习编程题 OJ 自动评测 AC/WA/CE）。
边界：限流非被测目标（fixture 关闭）；判分数值语义由函数层判分矩阵测试
负责，这里只保证端到端连通与响应形状；全程走 conftest 改指后的临时库，
绝不触碰 instance 真库。
"""
import os
from datetime import datetime, timedelta

import pytest


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _register(client, username, role, password='e2e-pw-123'):
    r = client.post('/api/register', json={
        'username': username, 'password': password, 'role': role})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert 'token' in body and body['user']['role'] == role
    return body['token'], body['user']


def _bal(client, token):
    """当前赏金币种余额（钱包 GET 兼作断言锚点；跨测试余额累加，只断增量）。"""
    return client.get('/api/bounty/wallet', headers=_auth(token)).get_json()['balance']


@pytest.fixture(scope='module')
def ctx(app_module):
    """模块级共享身份与基础数据（真实 app + 临时库），一次装配全 session 复用。"""
    from database import db
    from database.models import Major, Question

    client = app_module.app.test_client()
    c = {'_client': client, '_app': app_module.app}
    c['t1'], t1u = _register(client, 'e2e_teacher_1', 'teacher')
    c['t2'], _ = _register(client, 'e2e_teacher_2', 'teacher')
    c['s1'], s1u = _register(client, 'e2e_student_1', 'student')
    c['s2'], s2u = _register(client, 'e2e_student_2', 'student')
    c['t1_id'], c['s1_id'], c['s2_id'] = t1u['id'], s1u['id'], s2u['id']
    c['pw'] = 'e2e-pw-123'

    with app_module.app.app_context():
        major = Major(name='E2E专业')
        db.session.add(major)
        db.session.flush()
        q = Question(content='1+1=?', options=['A. 1', 'B. 2', 'C. 3', 'D. 4'],
                     answer='B', type='single_choice', difficulty='easy',
                     major_id=major.id)
        db.session.add(q)
        db.session.commit()
        c['major_id'], c['question_id'] = major.id, q.id
    return c


@pytest.fixture(scope='module')
def app_module():
    """真实 app 单例 + 安全装配：跳过 bootstrap（不跑迁移/不起调度），
    关闭限流，固定开启托管，create_all 建全表。"""
    import app as prod
    from database import db

    # 兜底保险：即便误触发也只 set 不执行；本 fixture 手动建表
    prod._boot_done.set()
    prod.app.config['TESTING'] = True

    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False   # 限流非被测目标（且有 AUTH 5/min 会被本测试打爆）
    os.environ['BOUNTY_ESCROW'] = 'true'  # 固定走托管全链（escrow_enabled 动态读）

    with prod.app.app_context():
        import database.models        # noqa: F401
        import competition.models     # noqa: F401
        import bounty.models          # noqa: F401
        import ledger.models          # noqa: F401
        import dsci.models            # noqa: F401
        db.create_all()
        yield prod
        db.session.remove()


# ─────────────────────────── 认证链 ───────────────────────────

def test_auth_chain_http(ctx):
    """匿名/伪造/角色门禁/登出吊销水位——RBAC 38 处收敛后的 HTTP 侧护栏。"""
    client = ctx['_client']  # noqa: F841  可读性别名
    c = ctx['_client']
    # 无 token：GET 受保护 API → 401
    assert c.get('/api/bounty/wallet').status_code == 401
    # 无 token 的写请求：CSRF 前置门拦下（实际行为是 400 而非 401，钉死现状）
    assert c.post('/api/bounty/wallet/topup', json={'amount': 1}).status_code == 400
    # 伪造 Bearer：过 CSRF 豁免但 verify_token 解析失败 → 401
    assert c.get('/api/user/me', headers=_auth('Bearer garbage')).status_code == 401
    # 正常注册 token 可换取身份
    r = c.get('/api/user/me', headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.get_json()['id'] == ctx['s1_id']
    # 密码错误 → 401
    assert c.post('/api/login', json={
        'username': 'e2e_student_1', 'password': 'wrong'}).status_code == 401
    # 角色门禁抽样：student 建考试 → 403
    assert c.post('/api/exams', json={}, headers=_auth(ctx['s1'])).status_code == 403
    # 登出吊销水位（v4.6.1）：登出后旧 token 即时失效，重新登录的新 token 可用
    tmp_token, _ = _register(c, 'e2e_logout_probe', 'student')
    assert c.get('/api/user/me', headers=_auth(tmp_token)).status_code == 200
    assert c.post('/api/logout', headers=_auth(tmp_token)).status_code == 200
    assert c.get('/api/user/me', headers=_auth(tmp_token)).status_code == 401


# ─────────────────────────── 钱链 ───────────────────────────

def test_bounty_money_chain(ctx):
    """充值→发布冻结→交叉审核→投稿→采纳释放→钱包账单形状→账本守恒。"""
    from ledger import core as ledger
    from database import db
    from competition.models import UserPointsProfile
    c = ctx['_client']

    # 充值 200
    r = c.post('/api/bounty/wallet/topup', json={'amount': 200},
               headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['balance'] == 200

    # 发布 QUESTION 悬赏：存在其他教师 → 进入交叉审核；托管即冻结 50
    r = c.post('/api/bounties', json={
        'title': 'E2E 征集Python题', 'bounty_type': 'question',
        'major_id': ctx['major_id'], 'reward_points': 50, 'max_accepts': 1},
        headers=_auth(ctx['t1']))
    assert r.status_code == 201, r.get_json()
    bounty = r.get_json()
    assert bounty['status'] == 'reviewing'
    assert c.get(f"/api/bounty/wallet", headers=_auth(ctx['t1'])).get_json()['balance'] == 150

    # 发布者自审 → 403；他人教师审核通过 → open
    url = f"/api/bounties/{bounty['id']}/review"
    assert c.post(url, json={'action': 'approve'},
                  headers=_auth(ctx['t1'])).status_code == 403
    r = c.post(url, json={'action': 'approve'}, headers=_auth(ctx['t2']))
    assert r.status_code == 200 and r.get_json()['bounty']['status'] == 'open'

    # 学生投稿（题干+答案）
    r = c.post(f"/api/bounties/{bounty['id']}/submissions", json={
        'q_content': '下列哪个是Python可变类型？', 'q_answer': 'B',
        'q_type': 'single_choice', 'ignore_dup': True},
        headers=_auth(ctx['s1']))
    assert r.status_code == 201, r.get_json()
    sid = r.get_json()['id']

    # 采纳：全额 50 从托管池释放给投稿人钱包，另结竞技积分
    r = c.post(f'/api/submissions/{sid}/accept', json={'reward_share': 50},
               headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['reward_share'] == 50, r.get_json()

    # 钱包账单：形状（v4.8 新增 currency/scope 字段）与余额
    w = c.get('/api/bounty/wallet', headers=_auth(ctx['s1'])).get_json()
    assert w['enabled'] is True and w['balance'] == 50
    kinds = [t['kind'] for t in w['transactions']]
    assert 'release' in kinds
    for t in w['transactions']:
        assert t['currency'] == 'bounty'
        assert {'delta', 'balance_after', 'kind', 'created_at'} <= set(t)
    assert (c.get('/api/bounty/wallet', headers=_auth(ctx['t1']))
            .get_json()['balance'] == 150)

    # 竞技积分镜像：投稿人积分 +50（独立于钱包赏金）
    with ctx['_app'].app_context():
        pts = db.session.query(UserPointsProfile).filter_by(
            user_id=ctx['s1_id']).all()
        assert sum(p.points for p in pts) == 50
        assert ledger.assert_conservation() == []   # HTTP 全链后账本守恒


# ─────────────────────────── 分链 ───────────────────────────

def test_exam_score_chain(ctx):
    """建卷→组卷→邀请→发布→开考→作答→交卷→成绩 HTTP 往返。"""
    c = ctx['_client']
    a = ctx['_app']
    now = datetime.now()
    fmt = '%Y-%m-%dT%H:%M:%S'

    r = c.post('/api/exams', json={
        'title': 'E2E 测验', 'duration': 60,
        'start_time': (now - timedelta(hours=1)).strftime(fmt),
        'end_time': (now + timedelta(hours=2)).strftime(fmt)},
        headers=_auth(ctx['t1']))
    assert r.status_code == 200, r.get_json()
    exam_id = r.get_json()['id']

    assert c.post(f'/api/exams/{exam_id}/add_questions',
                  json={'question_ids': [ctx['question_id']]},
                  headers=_auth(ctx['t1'])).status_code == 200
    assert c.post(f'/api/exams/{exam_id}/invite',
                  json={'student_ids': [ctx['s2_id']]},
                  headers=_auth(ctx['t1'])).status_code == 200
    assert c.post(f'/api/exams/{exam_id}/publish',
                  headers=_auth(ctx['t1'])).status_code == 200

    # 未被邀请学生开考 → 400；受邀学生开考 → 会话
    assert c.post(f'/api/exam/{exam_id}/start', headers=_auth(ctx['s1'])).status_code == 400
    r = c.post(f'/api/exam/{exam_id}/start', headers=_auth(ctx['s2']))
    assert r.status_code == 200, r.get_json()
    session_id = r.get_json()['session_id']

    # 拉题→作答（正确项 B）→交卷
    r = c.get(f'/api/exam/{exam_id}/take?session_id={session_id}',
              headers=_auth(ctx['s2']))
    assert r.status_code == 200
    assert [q['id'] for q in r.get_json()['questions']] == [ctx['question_id']]
    assert c.post(f'/api/exam/{exam_id}/save_answer', json={
        'session_id': session_id, 'question_id': ctx['question_id'],
        'answer': 'B'}, headers=_auth(ctx['s2'])).status_code == 200
    assert c.post(f'/api/exam/{exam_id}/submit',
                  json={'session_id': session_id},
                  headers=_auth(ctx['s2'])).status_code == 200
    # 重复交卷被拒（防重复批改）
    assert c.post(f'/api/exam/{exam_id}/submit',
                  json={'session_id': session_id},
                  headers=_auth(ctx['s2'])).status_code == 400

    # 教师侧成绩：已提交会话 + 客观题自动判分（答对得满分）
    r = c.get(f'/api/results/exam/{exam_id}', headers=_auth(ctx['t1']))
    assert r.status_code == 200
    rows = r.get_json()
    assert len(rows) == 1 and rows[0]['student_id'] == ctx['s2_id']
    assert rows[0]['total_score'] and rows[0]['score'] == rows[0]['total_score']
    # 交卷后禁止再改答案（会话已 submitted）
    assert c.post(f'/api/exam/{exam_id}/save_answer', json={
        'session_id': session_id, 'question_id': ctx['question_id'],
        'answer': 'A'}, headers=_auth(ctx['s2'])).status_code == 400

    # 学生侧成绩视图（results_published 默认发布）
    r = c.get('/api/results/me', headers=_auth(ctx['s2']))
    assert r.status_code == 200
    mine = r.get_json()
    assert len(mine) == 1 and mine[0]['published'] is True
    assert mine[0]['score'] == mine[0]['total_score'] > 0


# ─────────────────── 钱链·竞赛托管版 / PK 对战 / 练习 OJ ───────────────────

_FMT = '%Y-%m-%dT%H:%M:%S'


def _make_ongoing_comp(ctx, title, prize, allow_pk):
    """教师建赛→加题→发布（经 t2 交叉审核）→进入进行中窗口。返回 comp_id。"""
    c = ctx['_client']
    now = datetime.now()
    r = c.post('/api/competitions', json={
        'title': title, 'duration': 30, 'prize_points': prize, 'allow_pk': allow_pk,
        'start_time': (now - timedelta(hours=1)).strftime(_FMT),
        'end_time': (now + timedelta(hours=3)).strftime(_FMT)},
        headers=_auth(ctx['t1']))
    assert r.status_code == 200, r.get_json()
    cid = r.get_json()['id']
    assert c.post(f'/api/competitions/{cid}/questions',
                  json={'question_ids': [ctx['question_id']], 'score': 2.0},
                  headers=_auth(ctx['t1'])).status_code == 200
    r = c.post(f'/api/competitions/{cid}/publish', headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['status'] == 'reviewing'
    r = c.post(f'/api/competitions/{cid}/review', json={'action': 'approve'},
               headers=_auth(ctx['t2']))
    # 审核通过路由内即 sync_status：start_time 已过直接转 ongoing（可答）
    assert r.status_code == 200 and r.get_json()['status'] in ('published', 'ongoing')
    return cid


def test_competition_hosted_chain(ctx):
    """赛事托管全链：发布冻结→参赛交卷→结算释放冠军；驳回路径退回托管。"""
    from ledger import core as ledger
    c = ctx['_client']

    t1_topup = c.post('/api/bounty/wallet/topup', json={'amount': 300},
                      headers=_auth(ctx['t1']))
    assert t1_topup.status_code == 200
    cid = _make_ongoing_comp(ctx, 'E2E 限时赛', prize=100, allow_pk=False)
    # 发布即冻结：冠军奖金 100 从发布者钱包划入托管
    assert _bal(c, ctx['t1']) == t1_topup.get_json()['balance'] - 100

    # s2 报名→开考（sync_status 使 PUBLISHED 进入 ONGOING）→作答→交卷
    assert c.post(f'/api/competitions/{cid}/join',
                  headers=_auth(ctx['s2'])).status_code == 200
    r = c.post(f'/api/competitions/{cid}/start', headers=_auth(ctx['s2']))
    assert r.status_code == 200, r.get_json()
    cq_id = r.get_json()['questions'][0]['id']
    r = c.post(f'/api/competitions/{cid}/answer',
               json={'cq_id': cq_id, 'answer': 'B'}, headers=_auth(ctx['s2']))
    assert r.status_code == 200 and r.get_json()['is_correct'] is True
    assert r.get_json()['gained_score'] > 0
    r = c.post(f'/api/competitions/{cid}/finish', headers=_auth(ctx['s2']))
    assert r.status_code == 200 and r.get_json()['my'] is not None

    # 重复作答被拒（防刷分）
    assert c.post(f'/api/competitions/{cid}/answer',
                  json={'cq_id': cq_id, 'answer': 'B'},
                  headers=_auth(ctx['s2'])).status_code == 400

    # 结束→结算：唯一有效完成者夺冠，托管 100 释放进其赏金钱包
    assert c.post(f'/api/competitions/{cid}/end',
                  headers=_auth(ctx['t1'])).status_code == 200
    s2_before = _bal(c, ctx['s2'])
    r = c.post(f'/api/competitions/{cid}/settle', headers=_auth(ctx['t1']))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['winner_id'] == ctx['s2_id'] and r.get_json()['released'] == 100
    assert _bal(c, ctx['s2']) == s2_before + 100
    # 幂等：重复结算无待发放托管
    assert '无待发放' in c.post(f'/api/competitions/{cid}/settle',
                              headers=_auth(ctx['t1'])).get_json()['message']

    # 驳回退回路径：再赛一场发布冻结 40，t2 驳回 → 全额退回
    b0 = _bal(c, ctx['t1'])
    cid2 = None
    now = datetime.now()
    r = c.post('/api/competitions', json={
        'title': 'E2E 驳回赛', 'duration': 30, 'prize_points': 40,
        'start_time': (now - timedelta(hours=1)).strftime(_FMT),
        'end_time': (now + timedelta(hours=3)).strftime(_FMT)},
        headers=_auth(ctx['t1']))
    cid2 = r.get_json()['id']
    assert c.post(f'/api/competitions/{cid2}/questions',
                  json={'question_ids': [ctx['question_id']], 'score': 2.0},
                  headers=_auth(ctx['t1'])).status_code == 200
    assert c.post(f'/api/competitions/{cid2}/publish',
                  headers=_auth(ctx['t1'])).status_code == 200
    assert _bal(c, ctx['t1']) == b0 - 40
    r = c.post(f'/api/competitions/{cid2}/review',
               json={'action': 'reject', 'reason': '题意不清'}, headers=_auth(ctx['t2']))
    assert r.status_code == 200 and r.get_json()['status'] == 'rejected'
    assert _bal(c, ctx['t1']) == b0          # 驳回足额退回，托管不留死账

    with ctx['_app'].app_context():
        assert ledger.assert_conservation() == []


def test_pk_battle_chain(ctx):
    """PK 对战全链：建房→应战→逐题即时判分→双方交卷→结算与积分镜像。"""
    from ledger import core as ledger
    from database import db
    from ledger.models import LedgerTxn
    c = ctx['_client']

    cid = _make_ongoing_comp(ctx, 'E2E PK 赛', prize=0, allow_pk=True)
    r = c.post(f'/api/competitions/{cid}/pk', headers=_auth(ctx['s1']))
    assert r.status_code == 200, r.get_json()
    bid = r.get_json()['battle_id']

    # 自己不应自己的战；s2 应战进入 PLAYING
    assert c.post(f'/api/pk/{bid}/accept',
                  headers=_auth(ctx['s1'])).status_code == 400
    assert c.post(f'/api/pk/{bid}/accept',
                  headers=_auth(ctx['s2'])).status_code == 200

    r = c.get(f'/api/pk/{bid}/state', headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.get_json()['role'] == 'challenger'
    cq_id = r.get_json()['questions'][0]['id']

    for tok in (ctx['s1'], ctx['s2']):
        r = c.post(f'/api/pk/{bid}/answer',
                   json={'cq_id': cq_id, 'answer': 'B'}, headers=_auth(tok))
        assert r.status_code == 200 and r.get_json()['is_correct'] is True
    # 重复作答拦截
    assert c.post(f'/api/pk/{bid}/answer', json={'cq_id': cq_id, 'answer': 'B'},
                  headers=_auth(ctx['s1'])).status_code == 400

    # 双方交卷：先交的一方等待，后交触发即时结算（CAS 只结算一次）
    r = c.post(f'/api/pk/{bid}/finish', headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.get_json()['settled'] is False
    r = c.post(f'/api/pk/{bid}/finish', headers=_auth(ctx['s2']))
    body = r.get_json()
    assert r.status_code == 200 and body['settled'] is True
    assert body['result'] in ('win', 'lose')            # 双方均交卷必分胜负（同分先完成者胜）

    r = c.get(f'/api/pk/{bid}/state', headers=_auth(ctx['s1']))
    st = r.get_json()
    assert st['battle']['status'] == 'finished' and st.get('winner')
    # 交卷后不可再答题
    assert c.post(f'/api/pk/{bid}/answer', json={'cq_id': cq_id, 'answer': 'B'},
                  headers=_auth(ctx['s1'])).status_code == 400

    # 积分镜像：双方均发 battle 类型流水（胜/负皆有分），kind 白名单内
    with ctx['_app'].app_context():
        for uid in (ctx['s1_id'], ctx['s2_id']):
            txns = [t for t in ledger.txns_of(uid, 'points') if t.kind == 'battle']
            assert txns and all(t.delta > 0 for t in txns)
        assert ledger.assert_conservation() == []


def test_practice_oj_http(ctx):
    """自由练习编程题 OJ 自动评测（v4.10）：AC 判对 / WA 判错 / 空码 CE。"""
    from database import db
    from database.models import Major, Question

    c = ctx['_client']
    with ctx['_app'].app_context():
        m2 = Major(name='E2E-OJ专业')
        db.session.add(m2)
        db.session.flush()
        q = Question(content='输出 3+4 的值', answer='print(3+4)',
                     type='programming', difficulty='easy', major_id=m2.id,
                     test_cases=[{'input': '', 'expected': '7'},
                                 {'input': '', 'expected': '7'}])
        db.session.add(q)
        db.session.commit()
        oj_qid, m2_id = q.id, m2.id

    r = c.post('/api/learning/practice/start',
               json={'major_id': m2_id, 'count': 5}, headers=_auth(ctx['s1']))
    assert r.status_code == 200, r.get_json()
    sess_id = r.get_json()['session_id']
    assert [q['id'] for q in r.get_json()['questions']] == [oj_qid]

    # 正确代码 → AC
    r = c.post(f'/api/learning/practice/{sess_id}/answer',
               json={'question_id': oj_qid, 'student_answer': 'print(3 + 4)'},
               headers=_auth(ctx['s1']))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body['is_correct'] is True
    assert body['oj']['verdict'] == 'AC' and body['oj']['passed'] == 2

    # 错误代码可覆盖重答 → WA（题不匹配不送分）
    r = c.post(f'/api/learning/practice/{sess_id}/answer',
               json={'question_id': oj_qid, 'student_answer': 'print(0)'},
               headers=_auth(ctx['s1']))
    assert r.get_json()['is_correct'] is False
    assert r.get_json()['oj']['verdict'] == 'WA'

    # 空代码 → CE 直接判未通过（不起子进程）
    r = c.post(f'/api/learning/practice/{sess_id}/answer',
               json={'question_id': oj_qid, 'student_answer': '   '},
               headers=_auth(ctx['s1']))
    assert r.get_json()['is_correct'] is False
    assert r.get_json()['oj']['verdict'] == 'CE'

    # 危险代码被 runner 静态拦截 → SE 类降级不判对（评测链异常也不白给分）
    r = c.post(f'/api/learning/practice/{sess_id}/answer',
               json={'question_id': oj_qid, 'student_answer': 'import os; os.system("dir")'},
               headers=_auth(ctx['s1']))
    assert r.get_json()['is_correct'] is False


# ─────────────────── 数据科学竞赛全链（v4.11）───────────────────

def _upload_ds_file(c, token, cid, role, name, text):
    import io
    return c.post(f'/api/ds/competitions/{cid}/datasets',
                  data={'file': (io.BytesIO(text.encode('utf-8')), name), 'role': role},
                  content_type='multipart/form-data', headers=_auth(token))

def _make_ds_comp(ctx, title, prize):
    """教师建 DS 赛→配 accuracy→上传 train/gold/sample→发布冻结→t2 审核→进行中。"""
    c = ctx['_client']
    now = datetime.now()
    r = c.post('/api/competitions', json={
        'title': title, 'competition_type': 'ds', 'prize_points': prize,
        'start_time': (now - timedelta(hours=1)).strftime(_FMT),
        'end_time': (now + timedelta(hours=3)).strftime(_FMT)},
        headers=_auth(ctx['t1']))
    assert r.status_code == 200, r.get_json()
    cid = r.get_json()['id']
    # 配指标：id 列 / label 目标列 / 公榜比例 0.3 / 每日 5 次
    r = c.post(f'/api/ds/competitions/{cid}/config', json={
        'metric': 'accuracy', 'id_column': 'id', 'target_column': 'label',
        'public_ratio': 0.3, 'daily_limit': 5}, headers=_auth(ctx['t1']))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['config']['configured'] is True
    # 20 个样本，label = id % 2；train 全标注供学生直接复用产出预测
    rows = [{'id': i, 'label': i % 2} for i in range(20)]
    body = 'id,label\n' + '\n'.join(f"{r['id']},{r['label']}" for r in rows)
    for role in ('train', 'gold', 'sample'):
        up = _upload_ds_file(c, ctx['t1'], cid, role, f'{role}.csv', body)
        assert up.status_code == 201, up.get_json()
    # 发布→交叉审核→进行中
    r = c.post(f'/api/competitions/{cid}/publish', headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['status'] == 'reviewing'
    r = c.post(f'/api/competitions/{cid}/review', json={'action': 'approve'},
               headers=_auth(ctx['t2']))
    assert r.status_code == 200 and r.get_json()['status'] in ('published', 'ongoing')
    return cid


def test_ds_competition_chain(ctx):
    """DS 全链：建赛配指标→上传数据→冻结→在线运行→提交双榜→排名→按私榜结算→流标退回。"""
    import io
    from ledger import core as ledger
    c = ctx['_client']

    topup = c.post('/api/bounty/wallet/topup', json={'amount': 400},
                   headers=_auth(ctx['t1']))
    assert topup.status_code == 200
    b_before = topup.get_json()['balance']
    cid = _make_ds_comp(ctx, 'E2E 数据科学赛', prize=120)
    # 发布即冻结 120 进托管
    assert _bal(c, ctx['t1']) == b_before - 120

    # gold 不可下载；学生报名后可下 train
    files = c.get(f'/api/ds/competitions/{cid}/datasets',
                  headers=_auth(ctx['s1'])).get_json()['items']
    gold = next(f for f in files if f['role'] == 'gold')
    train = next(f for f in files if f['role'] == 'train')
    assert c.get(f"/api/ds/files/{gold['id']}/download",
                 headers=_auth(ctx['s1'])).status_code == 403
    assert c.get(f"/api/ds/files/{train['id']}/download",
                 headers=_auth(ctx['s1'])).status_code == 403  # 未报名拒绝
    assert c.post(f'/api/competitions/{cid}/join',
                  headers=_auth(ctx['s1'])).status_code == 200
    assert c.get(f"/api/ds/files/{train['id']}/download",
                 headers=_auth(ctx['s1'])).status_code == 200

    # 在线运行：读 train.csv 产出 submission.csv（与 gold 同形→预测全对）
    code = ("import pandas as pd\n"
            "df = pd.read_csv('train.csv')\n"
            "df.to_csv('submission.csv', index=False)\n")
    r = c.post(f'/api/ds/competitions/{cid}/notebook/run', json={'code': code},
               headers=_auth(ctx['s1']))
    assert r.status_code == 200, r.get_json()
    run = r.get_json()
    assert run['status'] == 'ok' and run['has_submission'] is True
    run_id = run['run_id']

    # 危险代码被静态拒绝（不执行）
    r = c.post(f'/api/ds/competitions/{cid}/notebook/run',
               json={'code': 'import os\nos.system("dir")'}, headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.get_json()['status'] == 'rejected'

    # 用在线产出提交→public+private 均 1.0
    r = c.post(f'/api/ds/competitions/{cid}/submit', json={'from_run_id': run_id},
               headers=_auth(ctx['s1']))
    assert r.status_code == 201, r.get_json()
    sub = r.get_json()['submission']
    assert sub['status'] == 'scored' and sub['public_score'] == 1.0
    # s2 上传预测文件提交（预测全错→accuracy 0.0），制造排名差异
    assert c.post(f'/api/competitions/{cid}/join',
                  headers=_auth(ctx['s2'])).status_code == 200
    bad = 'id,label\n' + '\n'.join(f"{i},{(i + 1) % 2}" for i in range(20))
    r = c.post(f'/api/ds/competitions/{cid}/submit',
               data={'file': (io.BytesIO(bad.encode()), 'prediction.csv')},
               content_type='multipart/form-data', headers=_auth(ctx['s2']))
    assert r.status_code == 201, r.get_json()
    assert r.get_json()['submission']['public_score'] == 0.0

    # 公榜：s1 第 1、s2 第 2；学生看不到 private_score
    lb = c.get(f'/api/ds/competitions/{cid}/leaderboard?scope=public',
               headers=_auth(ctx['s1'])).get_json()
    assert [r['user_id'] for r in lb['items']] == [ctx['s1_id'], ctx['s2_id']]
    assert lb['items'][0]['rank'] == 1 and lb['items'][0]['public_score'] == 1.0

    # 进行中私榜不对学生/非结束开放
    assert c.get(f'/api/ds/competitions/{cid}/leaderboard?scope=private',
                 headers=_auth(ctx['s1'])).status_code == 403

    # 结束→结算：按私榜分夺冠（s1），120 释放进 s1 钱包；账本守恒
    assert c.post(f'/api/competitions/{cid}/end',
                  headers=_auth(ctx['t1'])).status_code == 200
    s2_before = _bal(c, ctx['s1'])
    r = c.post(f'/api/competitions/{cid}/settle', headers=_auth(ctx['t1']))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['winner_id'] == ctx['s1_id'] and r.get_json()['released'] == 120
    assert _bal(c, ctx['s1']) == s2_before + 120
    # 结束后教师可读私榜
    lb_p = c.get(f'/api/ds/competitions/{cid}/leaderboard?scope=private',
                 headers=_auth(ctx['t1'])).get_json()
    assert lb_p['items'][0]['user_id'] == ctx['s1_id']

    with ctx['_app'].app_context():
        assert ledger.assert_conservation() == []

    # 流标退回：无任何有效提交的 DS 赛结束后结算→全额退创建者
    b0 = _bal(c, ctx['t1'])
    cid2 = _make_ds_comp(ctx, 'E2E 数据科学流标赛', prize=60)
    assert _bal(c, ctx['t1']) == b0 - 60
    assert c.post(f'/api/competitions/{cid2}/end',
                  headers=_auth(ctx['t1'])).status_code == 200
    r = c.post(f'/api/competitions/{cid2}/settle', headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json().get('refunded') == 60
    assert _bal(c, ctx['t1']) == b0
    with ctx['_app'].app_context():
        assert ledger.assert_conservation() == []
