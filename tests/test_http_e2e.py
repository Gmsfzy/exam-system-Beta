# -*- coding: utf-8 -*-
"""HTTP 层 E2E（v4.9）：真实 Flask app + test_client 走完整请求链。

定位：补函数层测试罩不到的主动脉——
  认证链（注册/登录/Bearer 解析/登出吊销/角色门禁/CSRF 前置门）、
  钱链（充值→发布托管→交叉审核→投稿→采纳释放→钱包账单形状，
        含赛事竞赛版：冻结→审核→结算释放/驳回退回）、
  分链（建卷→组卷→邀请→发布→开考→作答→交卷→成绩 HTTP 往返，
        含 PK 对战建房→应战→逐题→双方交卷→Elo/积分镜像、
        自由练习编程题 OJ 自动评测 AC/WA/CE、
        作业练习全链：发布→通知→作答脱敏→自动判分→重交→人工批改→成绩）。
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
        import homework.models        # noqa: F401
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

    # 师生互动：学生交卷 → 教师（创建者 t1）收到铃铛通知
    from database.models import Notification
    with a.app_context():
        assert Notification.query.filter_by(
            user_id=ctx['t1_id'], related_type='exam', related_id=exam_id,
            title='学生交卷：E2E 测验').count() == 1

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


# ─────────────────────────── 作业链（v5.0） ───────────────────────────

def test_homework_full_chain(ctx):
    """发布→通知→作答脱敏→自动判分→重交→人工批改→成绩→积分入账（提交 10 + 质量补发）→时效边界。"""
    from datetime import timedelta
    from database import db
    from database.models import Question, Notification
    from ledger.models import LedgerTxn
    from utils.timeutil import utcnow, iso_local
    from homework.models import Homework, HomeworkSubmission
    c = ctx['_client']
    with ctx['_app'].app_context():
        # s1 可能已有 PK/竞赛积分镜像流水：取基准值，作业链应零增量
        ledger_base = LedgerTxn.query.filter_by(user_id=ctx['s1_id']).count()

    # 造题：编程（OJ 用例）+ 简答（主观）；单选复用 ctx['question_id']
    with ctx['_app'].app_context():
        q_prog = Question(content='读入 n 输出 n+1', answer='', type='programming',
                          difficulty='easy', major_id=ctx['major_id'],
                          test_cases=[{'input': '3', 'expected': '4'}])
        q_short = Question(content='简述快排思想', answer='分治', type='short_answer',
                           difficulty='easy', major_id=ctx['major_id'])
        db.session.add_all([q_prog, q_short])
        db.session.commit()
        prog_id, short_id = q_prog.id, q_short.id

    # 权限：student 建作业 → 403
    assert c.post('/api/homeworks', json={'title': 'x'},
                  headers=_auth(ctx['s1'])).status_code == 403

    # 教师建草稿（题集式：单选5 + 编程10 + 简答6）→ 发布通知 s1
    # 注：parse_dt 对 naive 输入按上海墙上时间解释（全系统约定），故用 iso_local 产串
    deadline = iso_local(utcnow() + timedelta(hours=6))
    r = c.post('/api/homeworks', json={
        'title': 'E2E 作业', 'deadline': deadline, 'student_ids': [ctx['s1_id']],
        'questions': [{'question_id': ctx['question_id'], 'score': 5},
                      {'question_id': prog_id, 'score': 10},
                      {'question_id': short_id, 'score': 6}]},
        headers=_auth(ctx['t1']))
    assert r.status_code == 201, r.get_json()
    hw_id = r.get_json()['homework']['id']
    r = c.post(f'/api/homeworks/{hw_id}/publish', headers=_auth(ctx['t1']))
    assert r.status_code == 200 and '通知 1 名学生' in r.get_json()['message']

    # 学生收发布通知
    with ctx['_app'].app_context():
        assert Notification.query.filter_by(
            user_id=ctx['s1_id'], related_type='homework', related_id=hw_id).count() == 1

    # 名单边界：非名单学生 s2 → 403；学生 take 序列化不得下发答案/解析
    assert c.get(f'/api/homeworks/{hw_id}/take', headers=_auth(ctx['s2'])).status_code == 403
    r = c.get(f'/api/homeworks/{hw_id}/take', headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.get_json()['editable'] is True
    qs = r.get_json()['questions']
    assert len(qs) == 3
    flat = str(qs)
    assert '分治' not in flat and '"answer"' not in flat

    # 自动保存草稿作答 → 首次提交：单选+编程自动判分，简答待人工
    answers = {str(ctx['question_id']): 'B', str(prog_id): 'print(int(input())+1)',
               str(short_id): '分治递归'}
    r = c.post(f'/api/homeworks/{hw_id}/answers', json={'answers': answers},
               headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.get_json()['saved'] == 3
    r = c.post(f'/api/homeworks/{hw_id}/submit', json={'answers': answers},
               headers=_auth(ctx['s1']))
    assert r.status_code == 201, r.get_json()
    sub = r.get_json()['submission']
    sub_id = sub['id']
    assert sub['status'] == 'submitted' and sub['version'] == 1 and sub['max_score'] == 21.0

    # 重交：version+1，人工痕迹清零、自动判分重跑
    r = c.post(f'/api/homeworks/{hw_id}/submit', json={'answers': answers},
               headers=_auth(ctx['s1']))
    assert r.status_code == 201 and r.get_json()['submission']['version'] == 2

    # 师生互动：提交/重交各给教师发一条通知
    with ctx['_app'].app_context():
        assert Notification.query.filter_by(
            user_id=ctx['t1_id'], related_type='homework', related_id=hw_id,
            title='收到作业提交').count() == 1
        assert Notification.query.filter_by(
            user_id=ctx['t1_id'], related_type='homework', related_id=hw_id,
            title='收到作业重交').count() == 1

    # 教师列表：s1 已交、s2 不在名单（not_submitted 只含名单内未交者，此处为空）
    r = c.get(f'/api/homeworks/{hw_id}/submissions', headers=_auth(ctx['t1']))
    body = r.get_json()
    assert body['student_count'] == 1 and len(body['items']) == 1
    assert body['items'][0]['status'] == 'submitted'

    # 批改视图 → 给主观 4 分 + 总评 → pending=0 转 graded
    r = c.get(f'/api/homeworks/{hw_id}/grade/{sub_id}', headers=_auth(ctx['t1']))
    g = r.get_json()
    short_row = next(a for a in g['answers'] if a['question_id'] == short_id)
    assert short_row['needs_manual_grade'] is True
    r = c.post(f'/api/homeworks/{hw_id}/grade/{sub_id}', json={
        'answers': [{'answer_id': short_row['id'], 'score': 4, 'comment': '思路正确'}],
        'comment': '整体不错'}, headers=_auth(ctx['t1']))
    body = r.get_json()
    assert body['graded'] is True and body['submission']['total_score'] == 19.0

    # 成绩公布通知 + 学生查成绩
    with ctx['_app'].app_context():
        assert Notification.query.filter_by(
            user_id=ctx['s1_id'], related_type='homework',
            related_id=hw_id, title='作业已批改').count() == 1
    r = c.get(f'/api/homeworks/{hw_id}/result', headers=_auth(ctx['s1']))
    body = r.get_json()
    assert body['submission']['status'] == 'graded' and body['submission']['total_score'] == 19.0

    # graded 后锁定：再提交 → 400
    assert c.post(f'/api/homeworks/{hw_id}/submit', json={'answers': answers},
                  headers=_auth(ctx['s1'])).status_code == 400

    # v5.10 作业入账：两次最终提交只发 1 次基础分，批改完成再按得分率补发质量分
    with ctx['_app'].app_context():
        rows = (LedgerTxn.query.filter_by(user_id=ctx['s1_id'], ref_type='homework',
                                          ref_id=hw_id)
                .order_by(LedgerTxn.id).all())
        assert len(rows) == 2 and LedgerTxn.query.filter_by(user_id=ctx['s1_id']).count() == ledger_base + 2
        assert rows[0].currency == 'points' and rows[0].delta == 10    # 提交基础分
        assert rows[1].delta == 18                                     # 19/21 × 20 ≈ 18
        assert rows[0].idempotency_key == f'homework-submit:{hw_id}:{ctx["s1_id"]}'
        assert rows[1].idempotency_key == f'homework-grade:{hw_id}:{ctx["s1_id"]}'

    # 时效边界：先正常发布，再直改库把截止拨到过去模拟过期（publish 有未过期护栏）
    future = iso_local(utcnow() + timedelta(hours=6))
    hids = []
    for allow_late in (False, True):
        r = c.post('/api/homeworks', json={
            'title': f'E2E 时效{allow_late}', 'deadline': future, 'allow_late': allow_late,
            'student_ids': [ctx['s1_id']],
            'questions': [{'question_id': ctx['question_id'], 'score': 1}]},
            headers=_auth(ctx['t1']))
        hid = r.get_json()['homework']['id']
        assert c.post(f'/api/homeworks/{hid}/publish',
                      headers=_auth(ctx['t1'])).status_code == 200
        with ctx['_app'].app_context():
            hw = db.session.get(Homework, hid)
            hw.deadline = utcnow() - timedelta(hours=1)
            db.session.commit()
        hids.append(hid)

    # 过期禁迟交 → 403；允许迟交 → 提交成功且标记 is_late
    r = c.post(f'/api/homeworks/{hids[0]}/submit',
               json={'answers': {str(ctx['question_id']): 'B'}}, headers=_auth(ctx['s1']))
    assert r.status_code == 403
    r = c.post(f'/api/homeworks/{hids[1]}/submit',
               json={'answers': {str(ctx['question_id']): 'B'}}, headers=_auth(ctx['s1']))
    assert r.status_code == 201 and r.get_json()['submission']['is_late'] is True

    # 教师关闭作业 → 再提交 400
    hid = hids[0]
    assert c.post(f'/api/homeworks/{hid}/close', headers=_auth(ctx['t1'])).status_code == 200
    assert c.post(f'/api/homeworks/{hid}/submit',
                  json={'answers': {str(ctx['question_id']): 'B'}},
                  headers=_auth(ctx['s1'])).status_code == 400
    with ctx['_app'].app_context():
        assert db.session.get(Homework, hid).status == 'closed'


def test_homework_open_grading(ctx):
    """开放式作业：正文提交→整体待批→教师给总分转 graded→学生可查分。"""
    from datetime import timedelta
    from utils.timeutil import utcnow, iso_local
    c = ctx['_client']
    deadline = iso_local(utcnow() + timedelta(hours=6))

    # 开放式无正文不可发布（需填 description）
    r = c.post('/api/homeworks', json={
        'title': 'E2E 小论文', 'hw_type': 'open', 'deadline': deadline,
        'student_ids': [ctx['s1_id']]}, headers=_auth(ctx['t1']))
    assert r.status_code == 201, r.get_json()
    hid = r.get_json()['homework']['id']
    assert c.post(f'/api/homeworks/{hid}/publish',
                  headers=_auth(ctx['t1'])).status_code == 400   # 缺说明拦截
    c.put(f'/api/homeworks/{hid}', json={'description': '写一篇学习总结'},
          headers=_auth(ctx['t1']))
    assert c.post(f'/api/homeworks/{hid}/publish',
                  headers=_auth(ctx['t1'])).status_code == 200

    # 空内容提交被拒 → 填正文后提交成功（整体待批）
    assert c.post(f'/api/homeworks/{hid}/submit', json={'content': ''},
                  headers=_auth(ctx['s1'])).status_code == 400
    r = c.post(f'/api/homeworks/{hid}/submit', json={'content': '我的学习总结正文'},
               headers=_auth(ctx['s1']))
    assert r.status_code == 201, r.get_json()
    sub = r.get_json()['submission']
    assert sub['status'] == 'submitted' and sub['total_score'] is None

    # 未给分只存评语：保持待批；给分后转 graded
    r = c.post(f'/api/homeworks/{hid}/grade/{sub["id"]}',
               json={'comment': '再补充点数据'}, headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['graded'] is False
    r = c.post(f'/api/homeworks/{hid}/grade/{sub["id"]}',
               json={'score': 88, 'max_score': 100, 'comment': '优秀'},
               headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['graded'] is True
    assert r.get_json()['submission']['total_score'] == 88.0

    # 分数越界拒绝
    assert c.post(f'/api/homeworks/{hid}/grade/{sub["id"]}',
                  json={'score': 200}, headers=_auth(ctx['t1'])).status_code == 400

    # 学生查成绩可见总分与评语
    body = c.get(f'/api/homeworks/{hid}/result', headers=_auth(ctx['s1'])).get_json()
    assert body['submission']['status'] == 'graded' and body['submission']['total_score'] == 88.0
    assert body['submission']['comment'] == '优秀'


def test_homework_v51_features(ctx):
    """v5.1 增强：截止时间可选 + 及格线统计 + 导出 + 复制 + 随机抽题 + 参考资料 + 催交。"""
    import io
    from datetime import timedelta
    from database import db
    from database.models import Notification
    from homework.models import Homework
    from utils.timeutil import utcnow, iso_local
    c = ctx['_client']

    # 1) 无截止时间：缺省 deadline → has_deadline False，可发布/作答/永不判过期
    r = c.post('/api/homeworks', json={
        'title': 'E2E 无截止', 'student_ids': [ctx['s1_id']], 'pass_score': 6,
        'questions': [{'question_id': ctx['question_id'], 'score': 10}]},
        headers=_auth(ctx['t1']))
    assert r.status_code == 201, r.get_json()
    hw = r.get_json()['homework']
    hid = hw['id']
    assert hw['has_deadline'] is False and hw['deadline'] is None
    assert hw['pass_score'] == 6 and hw['is_expired'] is False
    assert c.post(f'/api/homeworks/{hid}/publish', headers=_auth(ctx['t1'])).status_code == 200
    r = c.get(f'/api/homeworks/{hid}/take', headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.get_json()['editable'] is True
    r = c.post(f'/api/homeworks/{hid}/submit',
               json={'answers': {str(ctx['question_id']): 'B'}}, headers=_auth(ctx['s1']))
    assert r.status_code == 201 and r.get_json()['submission']['is_late'] is False
    sub_id = r.get_json()['submission']['id']

    # 纯客观题批改（pending=0 直接转 graded）→ 满分 10
    r = c.post(f'/api/homeworks/{hid}/grade/{sub_id}', json={'comment': '全对'},
               headers=_auth(ctx['t1']))
    assert r.get_json()['graded'] is True and r.get_json()['submission']['total_score'] == 10.0

    # 2) 成绩统计：及格率/优秀率（pass_score=6，满分 10）
    st = c.get(f'/api/homeworks/{hid}/stats', headers=_auth(ctx['t1'])).get_json()['stats']
    assert st['student_count'] == 1 and st['submitted_count'] == 1 and st['graded_count'] == 1
    assert st['avg_score'] == 10.0 and st['full_score'] == 10.0
    assert st['pass_rate'] == 100.0 and st['excellent_rate'] == 100.0

    # 3) 导出 CSV：含表头与已批改行
    r = c.get(f'/api/homeworks/{hid}/export', headers=_auth(ctx['t1']))
    assert r.status_code == 200 and 'csv' in r.content_type
    body = r.data.decode('utf-8-sig')
    assert '学生' in body and '已批改' in body

    # 4) 复制为草稿：题量/及格线/无截止一并带走
    r = c.post(f'/api/homeworks/{hid}/copy', headers=_auth(ctx['t1']))
    assert r.status_code == 201
    cp = r.get_json()['homework']
    assert cp['status'] == 'draft' and cp['title'].endswith('（副本）')
    assert cp['question_count'] == 1 and cp['pass_score'] == 6 and cp['has_deadline'] is False

    # 5) 随机抽题：按专业抽题，返回可预填题单
    r = c.get(f'/api/homeworks/random_questions?count=3&major_id={ctx["major_id"]}',
              headers=_auth(ctx['t1']))
    assert r.status_code == 200 and len(r.get_json()['items']) >= 1

    # 6) 参考资料：教师上传→名单内学生下载→非名单 403
    r = c.post(f'/api/homeworks/{hid}/reference',
               data={'file': (io.BytesIO(b'reference-material'), 'note.txt')},
               content_type='multipart/form-data', headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['reference']['filename'] == 'note.txt'
    r = c.get(f'/api/homeworks/{hid}/reference', headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.data == b'reference-material'
    assert c.get(f'/api/homeworks/{hid}/reference', headers=_auth(ctx['s2'])).status_code == 403

    # 7) 催交：仅提醒未交学生（s1 已交、s2 未交）
    r = c.post('/api/homeworks', json={
        'title': 'E2E 催交', 'student_ids': [ctx['s1_id'], ctx['s2_id']],
        'questions': [{'question_id': ctx['question_id'], 'score': 1}]},
        headers=_auth(ctx['t1']))
    uh = r.get_json()['homework']['id']
    c.post(f'/api/homeworks/{uh}/publish', headers=_auth(ctx['t1']))
    c.post(f'/api/homeworks/{uh}/submit', json={'answers': {str(ctx['question_id']): 'B'}},
           headers=_auth(ctx['s1']))
    r = c.post(f'/api/homeworks/{uh}/urge', headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['urged'] == 1
    with ctx['_app'].app_context():
        assert Notification.query.filter_by(
            user_id=ctx['s2_id'], related_type='homework', related_id=uh,
            title='作业催交提醒').count() == 1
        assert Notification.query.filter_by(
            user_id=ctx['s1_id'], related_type='homework', related_id=uh,
            title='作业催交提醒').count() == 0

    # 8) 改期：无截止→设截止；再取消回无截止
    future = iso_local(utcnow() + timedelta(hours=3))
    c.put(f'/api/homeworks/{uh}', json={'deadline': future}, headers=_auth(ctx['t1']))
    with ctx['_app'].app_context():
        assert db.session.get(Homework, uh).deadline is not None
    c.put(f'/api/homeworks/{uh}', json={'deadline': ''}, headers=_auth(ctx['t1']))
    with ctx['_app'].app_context():
        assert db.session.get(Homework, uh).deadline is None


def test_homework_learning_sync_chain(ctx):
    """v5.2 作业→学习闭环全链：答错自动收错题本（<60% 阈值）→ 未批改门控隐藏答案
    → AI 归因 403 → 批改 GRADED 后门控解除、答案与归因可见。"""
    from datetime import timedelta
    from database import db
    from database.models import WrongAnswerRecord
    from utils.timeutil import utcnow, iso_local
    c = ctx['_client']

    # 布置纯客观作业（单选 10 分）→ 学生答错提交
    deadline = iso_local(utcnow() + timedelta(hours=6))
    r = c.post('/api/homeworks', json={
        'title': 'E2E 学习闭环', 'deadline': deadline, 'student_ids': [ctx['s1_id']],
        'questions': [{'question_id': ctx['question_id'], 'score': 10}]},
        headers=_auth(ctx['t1']))
    assert r.status_code == 201, r.get_json()
    hw_id = r.get_json()['homework']['id']
    assert c.post(f'/api/homeworks/{hw_id}/publish', headers=_auth(ctx['t1'])).status_code == 200
    r = c.post(f'/api/homeworks/{hw_id}/submit',
               json={'answers': {str(ctx['question_id']): 'A'}},  # 正确答案 B
               headers=_auth(ctx['s1']))
    assert r.status_code == 201, r.get_json()
    sub_id = r.get_json()['submission']['id']

    # 错题本：source_type=homework 收录（得分率 0 < 0.6）
    r = c.get('/api/learning/wrong-records?source_type=homework', headers=_auth(ctx['s1']))
    assert r.status_code == 200
    items = [i for i in r.get_json()['items'] if i['source_id'] == hw_id]
    assert len(items) == 1
    rec = items[0]
    assert rec['question_id'] == ctx['question_id'] and rec['wrong_count'] == 1
    # 门控：作业仍可重交（未批改）→ 答案/归因隐藏
    assert rec['answer_hidden'] is True and rec['correct_answer'] is None
    # 门控期间 AI 归因 → 403（防借归因泄露答案）
    r = c.post(f"/api/learning/wrong-records/{rec['id']}/analyze", headers=_auth(ctx['s1']))
    assert r.status_code == 403 and r.get_json()['answer_hidden'] is True

    # 教师批改（纯客观无需给分，空保存即转 GRADED）→ 门控解除
    r = c.post(f'/api/homeworks/{hw_id}/grade/{sub_id}', json={'answers': []},
               headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['graded'] is True
    r = c.get('/api/learning/wrong-records?source_type=homework', headers=_auth(ctx['s1']))
    rec = next(i for i in r.get_json()['items'] if i['source_id'] == hw_id)
    assert rec['answer_hidden'] is False and rec['correct_answer'] == 'B'
    # 错题仍单条（GRADED 触发 final scope 为空集，不双计）
    with ctx['_app'].app_context():
        assert WrongAnswerRecord.query.filter_by(
            user_id=ctx['s1_id'], source_type='homework', source_id=hw_id).count() == 1


def test_homework_ai_review_chain(ctx, monkeypatch):
    """v5.3 AI 讲评 HTTP 全链：班级分析生成/幂等/发布门控 + 单份讲评 + 权限。"""
    from datetime import timedelta
    from database import db
    from homework.models import HomeworkAiReview
    from utils.timeutil import utcnow, iso_local
    from ai_service.services import ai_client

    c = ctx['_client']
    monkeypatch.setattr(ai_client, 'generate_json', lambda *a, **kw: __import__(
        'json').dumps({
            'summary': 'E2E 班级讲评', 'common_mistakes': [
                {'question': '1+1=?', 'mistake': '粗心', 'advice': '课堂重讲'}],
            'weak_points': ['加法'], 'teaching_suggestions': ['变式练习'],
            'strengths': ['基础扎实'], 'improvements': [
                {'point': '进位加法', 'advice': '多练'}], 'next_steps': ['重做错题'],
        }, ensure_ascii=False))

    # 建纯客观作业（单选 10 分）→ 发布 → 学生答错提交 → 教师空保存转 graded
    deadline = iso_local(utcnow() + timedelta(hours=6))
    r = c.post('/api/homeworks', json={
        'title': 'E2E AI讲评', 'deadline': deadline, 'student_ids': [ctx['s1_id']],
        'questions': [{'question_id': ctx['question_id'], 'score': 10}]},
        headers=_auth(ctx['t1']))
    assert r.status_code == 201, r.get_json()
    hw_id = r.get_json()['homework']['id']
    assert c.post(f'/api/homeworks/{hw_id}/publish',
                  headers=_auth(ctx['t1'])).status_code == 200
    r = c.post(f'/api/homeworks/{hw_id}/submit',
               json={'answers': {str(ctx['question_id']): 'A'}}, headers=_auth(ctx['s1']))
    sub_id = r.get_json()['submission']['id']
    assert c.post(f'/api/homeworks/{hw_id}/grade/{sub_id}', json={'answers': []},
                  headers=_auth(ctx['t1'])).status_code == 200

    # 未生成前：GET → exists False；学生无权生成 → 403
    body = c.get(f'/api/homeworks/{hw_id}/ai_review', headers=_auth(ctx['t1'])).get_json()
    assert body['exists'] is False and body['review'] is None
    assert c.post(f'/api/homeworks/{hw_id}/ai_review',
                  headers=_auth(ctx['s1'])).status_code == 403

    # 生成班级讲评：统计完整 + AI 内容 + 默认未发布
    r = c.post(f'/api/homeworks/{hw_id}/ai_review', headers=_auth(ctx['t1']))
    assert r.status_code == 200, r.get_json()
    rev = r.get_json()['review']
    assert r.get_json()['degraded'] is False
    assert rev['content']['summary'] == 'E2E 班级讲评'
    assert rev['stats']['submitted'] == 1 and rev['stats']['weak_questions'][0]['avg_ratio'] == 0.0
    assert rev['published'] is False

    # 重复生成 → 覆盖同一行，不新增
    assert c.post(f'/api/homeworks/{hw_id}/ai_review',
                  headers=_auth(ctx['t1'])).status_code == 200
    with ctx['_app'].app_context():
        assert HomeworkAiReview.query.filter_by(
            homework_id=hw_id, scope_key='class').count() == 1

    # 未发布：学生 result 看不到班级讲评
    body = c.get(f'/api/homeworks/{hw_id}/result', headers=_auth(ctx['s1'])).get_json()
    assert body['class_review'] is None

    # 发布 → 学生可见
    r = c.post(f'/api/homeworks/{hw_id}/ai_review/publish',
               json={'published': True}, headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['review']['published'] is True
    body = c.get(f'/api/homeworks/{hw_id}/result', headers=_auth(ctx['s1'])).get_json()
    assert body['class_review']['content']['summary'] == 'E2E 班级讲评'

    # 单份讲评：生成 → 学生 result 可见；未批改提交 → 400
    r = c.post(f'/api/homeworks/{hw_id}/grade/{sub_id}/ai_review',
               headers=_auth(ctx['t1']))
    assert r.status_code == 200 and r.get_json()['degraded'] is False
    body = c.get(f'/api/homeworks/{hw_id}/result', headers=_auth(ctx['s1'])).get_json()
    assert body['ai_review']['content']['summary'] == 'E2E 班级讲评'
    assert body['ai_review']['stats']['questions'][0]['correct_answer'] == 'B'

    # 非创建教师/非名单学生不可见批改视图
    assert c.get(f'/api/homeworks/{hw_id}/grade/{sub_id}/ai_review',
                 headers=_auth(ctx['s2'])).status_code == 403

    # 撤回发布 → 学生重新不可见
    assert c.post(f'/api/homeworks/{hw_id}/ai_review/publish',
                  json={'published': False},
                  headers=_auth(ctx['t1'])).status_code == 200
    body = c.get(f'/api/homeworks/{hw_id}/result', headers=_auth(ctx['s1'])).get_json()
    assert body['class_review'] is None


def test_notification_realtime_push(ctx, monkeypatch):
    """全局通知实时推送（ORM 事件层）：任何模块通知 commit 后自动推 new_notification，
    覆盖 commit=True 单发与 commit=False 批量；回滚不推（防幽灵推送）。
    锁死「Notification 无 to_dict 导致推送静默失败」这类回归。"""
    import competition.realtime as rt
    from database import db
    from database.models import Notification
    from api.notification_routes import create_notification
    from utils.timeutil import utcnow, iso_local
    from datetime import timedelta
    c = ctx['_client']

    pushed = []
    monkeypatch.setattr(rt, 'notify_user',
                        lambda uid, ev, payload: pushed.append((uid, ev, payload)))

    # 1) commit=True 单发：直接经全局助手创建通知 → 立即推送，负载形状与轮询一致
    with ctx['_app'].app_context():
        create_notification(ctx['s1_id'], '推送机制直发', '正文', type='success',
                            related_type='exam', related_id=999, commit=True)
    hit = [p for p in pushed if p[0] == ctx['s1_id'] and p[2]['title'] == '推送机制直发']
    assert hit, f'commit=True 未实时推送: {pushed}'
    assert hit[0][1] == 'new_notification'
    pl = hit[0][2]
    assert pl['read'] is False and pl['id'] and pl['related_type'] == 'exam'
    assert 'created_at' in pl and 'time_ago' in pl and pl['type'] == 'success'

    # 2) commit=False 批量：教师发布作业（名单学生通知走批量路径）→ 学生收到推送
    pushed.clear()
    deadline = iso_local(utcnow() + timedelta(hours=6))
    r = c.post('/api/homeworks', json={
        'title': '推送验证作业', 'deadline': deadline, 'student_ids': [ctx['s1_id']],
        'questions': [{'question_id': ctx['question_id'], 'score': 5}]},
        headers=_auth(ctx['t1']))
    hw_id = r.get_json()['homework']['id']
    assert c.post(f'/api/homeworks/{hw_id}/publish',
                  headers=_auth(ctx['t1'])).status_code == 200
    pub = [p for p in pushed if p[0] == ctx['s1_id']
           and p[2].get('related_type') == 'homework' and p[2].get('related_id') == hw_id]
    assert pub, f'发布(批量路径)未实时推送: {pushed}'

    # 3) 回滚不推送：flush 暂存后 rollback，负载应被丢弃
    pushed.clear()
    with ctx['_app'].app_context():
        ghost = Notification(user_id=ctx['s1_id'], title='幽灵通知', content='', type='info')
        db.session.add(ghost)
        db.session.flush()          # after_insert 暂存
        db.session.rollback()       # after_rollback 丢弃
    assert [p for p in pushed if p[2].get('title') == '幽灵通知'] == []


def test_follow_notification(ctx):
    """学习模块互动：A 关注 B → B 收到“有人关注了你”；取关不新增。"""
    from database.models import Notification
    c = ctx['_client']
    fa, _ = _register(c, 'e2e_follow_a', 'student')
    fb, fbu = _register(c, 'e2e_follow_b', 'student')
    r = c.post(f'/api/learning/users/{fbu["id"]}/follow', headers=_auth(fa))
    assert r.status_code == 200 and r.get_json()['following'] is True
    with ctx['_app'].app_context():
        assert Notification.query.filter_by(
            user_id=fbu['id'], related_type='user', title='有人关注了你').count() == 1
    # 取关：不新增通知
    assert c.post(f'/api/learning/users/{fbu["id"]}/follow',
                  headers=_auth(fa)).get_json()['following'] is False
    with ctx['_app'].app_context():
        assert Notification.query.filter_by(
            user_id=fbu['id'], related_type='user', title='有人关注了你').count() == 1


def test_homework_social_chain(ctx):
    """v5.4 讨论区 + v5.5 生生互评 HTTP 全链：
    发帖/回复/通知/软删权限 → 教师分配互评 → 匿名详情 → 提交/重复提交拦截
    → 汇总完成率 → 批改后学生匿名可见互评结果。"""
    from datetime import timedelta
    from database import db
    from database.models import Notification
    from homework.models import Homework, HomeworkPeerReview
    from utils.timeutil import utcnow, iso_local

    c = ctx['_client']
    deadline = iso_local(utcnow() + timedelta(hours=6))
    r = c.post('/api/homeworks', json={
        'title': 'E2E 社交作业', 'deadline': deadline,
        'student_ids': [ctx['s1_id'], ctx['s2_id']],
        'questions': [{'question_id': ctx['question_id'], 'score': 10}]},
        headers=_auth(ctx['t1']))
    assert r.status_code == 201, r.get_json()
    hw_id = r.get_json()['homework']['id']
    assert c.post(f'/api/homeworks/{hw_id}/publish',
                  headers=_auth(ctx['t1'])).status_code == 200

    r = c.post(f'/api/homeworks/{hw_id}/submit',
               json={'answers': {str(ctx['question_id']): 'B'}}, headers=_auth(ctx['s1']))
    sub1_id = r.get_json()['submission']['id']
    assert c.post(f'/api/homeworks/{hw_id}/submit',
                  json={'answers': {str(ctx['question_id']): 'A'}},
                  headers=_auth(ctx['s2'])).status_code == 201

    # ── 讨论区：学生发主楼 → 学生回复 → 教师回复 ──
    r = c.post(f'/api/homeworks/{hw_id}/comments',
               json={'content': '这道题为什么选 B？'}, headers=_auth(ctx['s1']))
    assert r.status_code == 201, r.get_json()
    c1 = r.get_json()
    assert c1['parent_id'] is None and c1['is_teacher'] is False and c1['mine'] is True

    r = c.post(f'/api/homeworks/{hw_id}/comments',
               json={'content': '因为 B 是正确答案', 'parent_id': c1['id']},
               headers=_auth(ctx['s2']))
    assert r.status_code == 201
    reply_s2 = r.get_json()

    r = c.post(f'/api/homeworks/{hw_id}/comments',
               json={'content': '可以看一下运算过程', 'parent_id': c1['id']},
               headers=_auth(ctx['t1']))
    assert r.status_code == 201 and r.get_json()['is_teacher'] is True
    reply_teacher = r.get_json()

    # 列表：主楼 1 条 + 回复 2 条（按时间升序）
    body = c.get(f'/api/homeworks/{hw_id}/comments', headers=_auth(ctx['s1'])).get_json()
    assert body['total'] == 1 and body['can_moderate'] is False
    assert [x['id'] for x in body['items'][0]['replies']] == [reply_s2['id'], reply_teacher['id']]

    # 通知：教师收新提问，s1 收两次回复
    with ctx['_app'].app_context():
        assert Notification.query.filter_by(
            user_id=ctx['t1_id'], related_type='homework', related_id=hw_id,
            title='作业讨论有新提问').count() == 1
        assert Notification.query.filter_by(
            user_id=ctx['s1_id'], related_type='homework', related_id=hw_id,
            title='作业讨论有新回复').count() == 2

    # 权限：非创建教师不可见；学生删教师回复 403；教师可删
    assert c.get(f'/api/homeworks/{hw_id}/comments',
                 headers=_auth(ctx['t2'])).status_code == 404
    assert c.delete(f'/api/homeworks/{hw_id}/comments/{reply_teacher["id"]}',
                    headers=_auth(ctx['s2'])).status_code == 403
    assert c.delete(f'/api/homeworks/{hw_id}/comments/{reply_s2["id"]}',
                    headers=_auth(ctx['t1'])).status_code == 200
    body = c.get(f'/api/homeworks/{hw_id}/comments', headers=_auth(ctx['s1'])).get_json()
    deleted = next(x for x in body['items'][0]['replies'] if x['id'] == reply_s2['id'])
    assert deleted['deleted'] is True and deleted['content'] == '该评论已删除'

    # ── 互评：学生不可分配；教师分配 2 份（每人 1 份）──
    assert c.post(f'/api/homeworks/{hw_id}/peer_reviews/distribute',
                  json={'per_submission': 2}, headers=_auth(ctx['s1'])).status_code == 403
    r = c.post(f'/api/homeworks/{hw_id}/peer_reviews/distribute',
               json={'per_submission': 2}, headers=_auth(ctx['t1']))
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['created'] == 2
    assert r.get_json()['summary']['total'] == 2

    mine1 = c.get('/api/homeworks/peer_reviews/mine', headers=_auth(ctx['s1'])).get_json()
    mine2 = c.get('/api/homeworks/peer_reviews/mine', headers=_auth(ctx['s2'])).get_json()
    assert mine1['pending_count'] == 1 and mine2['pending_count'] == 1
    rev1 = mine1['items'][0]['review']
    rev2 = mine2['items'][0]['review']
    assert rev1['reviewer_id'] == ctx['s1_id'] and rev1['submission_id'] != sub1_id

    # 匿名详情：无作者字段、无正确答案/解析，仅含被评作答
    detail = c.get(f'/api/homeworks/{hw_id}/peer_reviews/{rev1["id"]}',
                   headers=_auth(ctx['s1'])).get_json()
    assert 'username' not in detail['submission']
    assert detail['questions'][0]['peer_answer'] == 'A'
    assert 'answer' not in detail['questions'][0] and 'analysis' not in detail['questions'][0]
    # 非该任务评审人不可查看
    assert c.get(f'/api/homeworks/{hw_id}/peer_reviews/{rev1["id"]}',
                 headers=_auth(ctx['s2'])).status_code == 403

    # s1 评 s2：75 分；重复提交拦截；s2 评 s1：90 分
    r = c.post(f'/api/homeworks/{hw_id}/peer_reviews/{rev1["id"]}',
               json={'score': 75, 'comment': '步骤可再展开'}, headers=_auth(ctx['s1']))
    assert r.status_code == 200 and r.get_json()['status'] == 'submitted'
    assert c.post(f'/api/homeworks/{hw_id}/peer_reviews/{rev1["id"]}',
                  json={'score': 60}, headers=_auth(ctx['s1'])).status_code == 400
    assert c.post(f'/api/homeworks/{hw_id}/peer_reviews/{rev2["id"]}',
                  json={'score': 90, 'comment': '思路清晰'}, headers=_auth(ctx['s2'])).status_code == 200
    # 边界：越界分数（已提交后仍先被状态拦下 → 400）
    assert c.post(f'/api/homeworks/{hw_id}/peer_reviews/{rev1["id"]}',
                  json={'score': 101}, headers=_auth(ctx['s1'])).status_code == 400

    # 教师汇总：完成率 100%，每份均分可见，评审人进度完整
    summary = c.get(f'/api/homeworks/{hw_id}/peer_reviews',
                    headers=_auth(ctx['t1'])).get_json()
    assert summary['total'] == 2 and summary['submitted'] == 2
    assert summary['completion_rate'] == 100.0
    row1 = next(x for x in summary['per_submission'] if x['submission_id'] == sub1_id)
    assert row1['avg_score'] == 90.0 and row1['submitted_count'] == 1
    assert len(summary['reviewers']) == 2

    # 未批改：学生 result 不披露互评；批改后匿名可见
    body = c.get(f'/api/homeworks/{hw_id}/result', headers=_auth(ctx['s1'])).get_json()
    assert body['peer_review'] is None
    assert c.post(f'/api/homeworks/{hw_id}/grade/{sub1_id}', json={'answers': []},
                  headers=_auth(ctx['t1'])).status_code == 200
    body = c.get(f'/api/homeworks/{hw_id}/result', headers=_auth(ctx['s1'])).get_json()
    assert body['peer_review']['count'] == 1
    assert body['peer_review']['avg_score'] == 90.0
    assert body['peer_review']['comments'][0]['comment'] == '思路清晰'
    assert 'reviewer_id' not in body['peer_review']['comments'][0]

    # 非创建教师不能看互评汇总
    assert c.get(f'/api/homeworks/{hw_id}/peer_reviews',
                 headers=_auth(ctx['t2'])).status_code == 403

    # 数据落库核对：2 条互评且均 submitted
    with ctx['_app'].app_context():
        assert HomeworkPeerReview.query.filter_by(
            homework_id=hw_id, status='submitted').count() == 2
        assert db.session.get(Homework, hw_id).status == 'published'


# ═══════════════ v5.11 作业批改提效与防抄 HTTP 链 ═══════════════

def test_homework_batch_grading_http(ctx):
    """v5.11 同题批量给分：一道主观题统一分数套到多份提交，批量转 GRADED。"""
    from database import db
    from database.models import Question
    from homework.models import HomeworkSubmission
    c = ctx['_client']
    with ctx['_app'].app_context():
        qs = Question(content='简答批量', answer='分治', type='short_answer',
                      difficulty='easy', major_id=ctx['major_id'])
        db.session.add(qs)
        db.session.commit()
        sid = qs.id
    r = c.post('/api/homeworks', json={
        'title': '批量作业', 'student_ids': [ctx['s1_id'], ctx['s2_id']],
        'questions': [{'question_id': sid, 'score': 6}]}, headers=_auth(ctx['t1']))
    hw_id = r.get_json()['homework']['id']
    assert c.post(f'/api/homeworks/{hw_id}/publish', headers=_auth(ctx['t1'])).status_code == 200
    for tok in (ctx['s1'], ctx['s2']):
        assert c.post(f'/api/homeworks/{hw_id}/submit',
                      json={'answers': {str(sid): '我的分治答案'}},
                      headers=_auth(tok)).status_code == 201
    r = c.post(f'/api/homeworks/{hw_id}/grade/batch',
               json={'question_id': sid, 'score': 5, 'comment': '一致给分'},
               headers=_auth(ctx['t1']))
    body = r.get_json()
    assert body['applied'] == 2 and body['graded'] == 2 and body['still_pending'] == 0
    # 非本人教师 → 403
    assert c.post(f'/api/homeworks/{hw_id}/grade/batch',
                  json={'question_id': sid, 'score': 5},
                  headers=_auth(ctx['t2'])).status_code == 403
    with ctx['_app'].app_context():
        subs = HomeworkSubmission.query.filter_by(homework_id=hw_id).all()
        assert len(subs) == 2 and all(s.status == 'graded' and s.total_score == 5.0 for s in subs)


def test_homework_late_penalty_http(ctx):
    """v5.11 迟交扣分：过截止迟交，批改完成按比例扣分并保留原始分。"""
    from utils.timeutil import utcnow, iso_local
    from homework.models import Homework
    from database import db
    c = ctx['_client']
    future = iso_local(utcnow() + timedelta(hours=1))
    r = c.post('/api/homeworks', json={
        'title': '迟交扣分', 'deadline': future, 'allow_late': True, 'late_penalty_pct': 20,
        'student_ids': [ctx['s1_id']],
        'questions': [{'question_id': ctx['question_id'], 'score': 10}]},
        headers=_auth(ctx['t1']))
    hw_id = r.get_json()['homework']['id']
    assert c.post(f'/api/homeworks/{hw_id}/publish', headers=_auth(ctx['t1'])).status_code == 200
    # 发布后将截止改到过去，触发迟交通道
    with ctx['_app'].app_context():
        h = db.session.get(Homework, hw_id)
        h.deadline = utcnow() - timedelta(hours=1)
        db.session.commit()
    r = c.post(f'/api/homeworks/{hw_id}/submit',
               json={'answers': {str(ctx['question_id']): 'B'}}, headers=_auth(ctx['s1']))
    assert r.status_code == 201 and r.get_json()['submission']['is_late'] is True
    sub_id = r.get_json()['submission']['id']
    # 纯客观：批改 POST 空给分单触发 recompute → pending 0 → 转 GRADED 并扣分
    body = c.post(f'/api/homeworks/{hw_id}/grade/{sub_id}', json={'answers': []},
                  headers=_auth(ctx['t1'])).get_json()
    assert body['graded'] is True
    assert body['submission']['total_score'] == 8.0
    assert body['submission']['score_before_penalty'] == 10.0
    assert body['submission']['late_deducted'] == 2.0


def test_homework_shuffle_http(ctx):
    """v5.11 选项乱序全链：学生按显示位选正确项 → 反归存原始位 → 自动判满分。"""
    from database import db
    from database.models import Question
    c = ctx['_client']
    with ctx['_app'].app_context():
        q = Question(content='乱序单选', answer='C', type='single_choice', difficulty='easy',
                     major_id=ctx['major_id'], options=['A. 甲', 'B. 乙', 'C. 丙', 'D. 丁'])
        db.session.add(q)
        db.session.commit()
        qid = q.id
    r = c.post('/api/homeworks', json={
        'title': '乱序作业', 'student_ids': [ctx['s1_id']], 'shuffle_options': True,
        'questions': [{'question_id': qid, 'score': 5}]}, headers=_auth(ctx['t1']))
    hw_id = r.get_json()['homework']['id']
    assert c.post(f'/api/homeworks/{hw_id}/publish', headers=_auth(ctx['t1'])).status_code == 200
    # take：拿到（可能乱序后的）展示选项，定位正确项“丙”对应的显示字母
    opts = c.get(f'/api/homeworks/{hw_id}/take', headers=_auth(ctx['s1'])).get_json()['questions'][0]['options']
    disp = next(o for o in opts if '丙' in str(o))[0]   # 'X. ...' 首字母即显示位
    r = c.post(f'/api/homeworks/{hw_id}/submit',
               json={'answers': {str(qid): disp}}, headers=_auth(ctx['s1']))
    assert r.status_code == 201
    sub_id = r.get_json()['submission']['id']
    # 教师批改视图：存的是规范化字母 C（反归成功），得分满分
    body = c.post(f'/api/homeworks/{hw_id}/grade/{sub_id}', json={'answers': []},
                  headers=_auth(ctx['t1'])).get_json()
    assert body['graded'] is True and body['submission']['total_score'] == 5.0
    # 存储已反归为原始位字母 C（自动判满分的根因）
    from homework.models import HomeworkAnswer, HomeworkSubmission
    with ctx['_app'].app_context():
        row = (HomeworkAnswer.query.join(HomeworkSubmission)
               .filter(HomeworkSubmission.homework_id == hw_id,
                       HomeworkAnswer.question_id == qid).first())
        assert row is not None and row.answer == 'C'


def test_homework_grading_queue_http(ctx):
    """v5.12 批改工作台：跨作业聚合待批队列，批改后减一，按作业过滤，教师隔离，学生 403，盲审隐名。"""
    from database import db
    from database.models import Question
    c = ctx['_client']

    def _new_hw(title, blind=False):
        with ctx['_app'].app_context():
            q = Question(content=f'简答{title}', answer='分治', type='short_answer',
                         difficulty='easy', major_id=ctx['major_id'])
            db.session.add(q)
            db.session.commit()
            qid = q.id
        payload = {'title': title, 'student_ids': [ctx['s1_id'], ctx['s2_id']],
                   'questions': [{'question_id': qid, 'score': 6}]}
        if blind:
            payload['blind_grading'] = True
        r = c.post('/api/homeworks', json=payload, headers=_auth(ctx['t1']))
        hw_id = r.get_json()['homework']['id']
        c.post(f'/api/homeworks/{hw_id}/publish', headers=_auth(ctx['t1']))
        for tok in (ctx['s1'], ctx['s2']):
            c.post(f'/api/homeworks/{hw_id}/submit',
                   json={'answers': {str(qid): '我的答案'}}, headers=_auth(tok))
        return hw_id, qid

    hw1, _q1 = _new_hw('队列作业一')
    hw2, _q2 = _new_hw('队列作业二')

    # 学生无权访问教师工作台
    assert c.get('/api/homeworks/grading-queue', headers=_auth(ctx['s1'])).status_code == 403

    # 队列跨作业聚合：以本测试自建的 hw1/hw2 为准（ctx 为 module 共享，其它测试或有遗留待批，故按 id 界定）
    body = c.get('/api/homeworks/grading-queue', headers=_auth(ctx['t1'])).get_json()
    mine = [it for it in body['items'] if it['homework_id'] in (hw1, hw2)]
    assert len(mine) == 4                      # 两份作业 × 两份未批提交
    assert set(body['items'][0].keys()) >= {'sub_id', 'homework_id', 'username', 'pending', 'hw_type'}
    assert all(it['pending'] >= 1 for it in mine)
    assert {it['homework_id'] for it in mine} == {hw1, hw2}

    # 按作业过滤（filter 后 total 仅计该作业，确定值）
    one = c.get(f'/api/homeworks/grading-queue?homework_id={hw1}', headers=_auth(ctx['t1'])).get_json()
    assert one['total'] == 2 and all(it['homework_id'] == hw1 for it in one['items'])

    # 批完 hw1 两份 → hw1 退出队列，hw2 仍在
    for it in one['items']:
        c.post(f"/api/homeworks/{hw1}/grade/batch",
               json={'question_id': _q1, 'score': 5}, headers=_auth(ctx['t1']))
    after = c.get('/api/homeworks/grading-queue', headers=_auth(ctx['t1'])).get_json()
    mine_after = [it for it in after['items'] if it['homework_id'] in (hw1, hw2)]
    assert len(mine_after) == 2 and all(it['homework_id'] == hw2 for it in mine_after)

    # 教师隔离：t2 看不到 t1 的待批
    t2body = c.get('/api/homeworks/grading-queue', headers=_auth(ctx['t2'])).get_json()
    assert t2body['total'] == 0

    # 盲审：开启匿名后队列隐去真名/student_id
    hwb, _qb = _new_hw('盲审队列', blind=True)
    bb = c.get(f'/api/homeworks/grading-queue?homework_id={hwb}', headers=_auth(ctx['t1'])).get_json()
    assert bb['total'] == 2
    assert all(it['blind'] is True and it['student_id'] is None
               and str(it['username']).startswith('匿名') for it in bb['items'])

