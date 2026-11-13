# -*- coding: utf-8 -*-
"""v7.9 批量讲义生成队列回归门。

锁定语义（一条计划任务 → 一份详细文档，8 条任务就是 8 份）：
- enqueue：一条任务一行作业，同批共用 batch_id；已有成品的任务默认跳过，force 才重做；
- process_once：抢占→AI→落 study_material（带 plan_id/task_id）→done；
- 幂等：条件 UPDATE 抢占，重复排空不双生成、不双写资料；
- 额度阻塞不同于失败：学生当日额度用尽时作业留 pending 且不计 attempts（次日自动续跑）；
- 失败可重放：AI 异常回炉 pending 计 attempts，超限 failed 终态，retry 接口可复活；
- 整批收尾只发一条站内通知（批内仍有 pending 时不发），related_type='material'；
- HTTP 层：受理返 202 + batch_id，进度接口能读到，非本人计划 404，无任务 400，额度耗尽 429。

AI 外呼一律 monkeypatch 替身（本门只验证装配/队列/关联，不打真模型）。
"""
import pytest
from datetime import date

from database import db
from database.models import (
    Major, Course, User, StudyPlan, StudyPlanTask, StudyMaterial, MaterialGenJob,
    KnowledgePoint, Chapter, Notification, AiQuota,
)
from utils.timeutil import local_today

import ai_service.services as svc
import ai_service.material_queue as mq

# autouse 替身会把 svc.ai_generate_material 整个换掉，真函数先存一份给模板用例用
_REAL_AI_GENERATE = svc.ai_generate_material


def _seed_plan(user, n_tasks=3, kp=False, course=True):
    major = Major(name='mb软件')
    db.session.add(major)
    db.session.commit()
    course = Course(name='mb数据结构', major=major) if course else None
    if course:
        db.session.add(course)
        db.session.commit()
    chapter = None
    if kp:
        chapter = Chapter(name='mb章', course_id=course.id)
        db.session.add(chapter)
        db.session.commit()
    plan = StudyPlan(user_id=user.id, title='两周攻克数据结构', start_date=date(2026, 1, 1),
                     major_id=major.id, course_id=course.id if course else None,
                     status='active')
    db.session.add(plan)
    db.session.commit()
    for i in range(n_tasks):
        task = StudyPlanTask(plan_id=plan.id, title=f'任务 {i + 1}', task_type='custom',
                             order_num=i)
        if kp:
            point = KnowledgePoint(chapter_id=chapter.id, name=f'知识点{i + 1}',
                                   description='链表的插入与删除', difficulty='medium')
            db.session.add(point)
            db.session.commit()
            task.task_type = 'knowledge_point'
            task.knowledge_point_id = point.id
        db.session.add(task)
    db.session.commit()
    return plan


def _ok_content(session, prompt, kind, subject, difficulty):
    return f'# {prompt}\n\n（{kind}/{subject}/{difficulty}）正文', False


@pytest.fixture(autouse=True)
def _ai_stub(monkeypatch):
    """默认给一个成功的 AI 替身，单个用例再自行覆盖。"""
    monkeypatch.setattr(svc, 'ai_generate_material', _ok_content)


class TestEnqueue:
    def test_one_job_per_task(self, app, user_factory):
        u = user_factory('mb_enq')
        plan = _seed_plan(u, n_tasks=8)
        batch_id, queued, skipped = mq.enqueue(u, plan)
        assert (queued, skipped) == (8, 0)
        jobs = MaterialGenJob.query.filter_by(batch_id=batch_id).all()
        assert len(jobs) == 8
        assert {j.status for j in jobs} == {'pending'}
        assert {j.task_id for j in jobs} == {t.id for t in plan.tasks}
        assert jobs[0].kind == 'mindmap' and jobs[0].plan_id == plan.id
        # 学科取课程名，供模板拼「学科：xxx」
        assert jobs[0].subject == 'mb数据结构'

    def test_prompt_carries_plan_and_kp_context(self, app, user_factory):
        u = user_factory('mb_prompt')
        plan = _seed_plan(u, n_tasks=1, kp=True)
        _batch, queued, _skipped = mq.enqueue(u, plan)
        job = MaterialGenJob.query.first()
        assert queued == 1
        assert '两周攻克数据结构' in job.prompt      # 计划上下文
        assert '知识点' in job.prompt and '链表的插入与删除' in job.prompt
        assert job.difficulty == 'medium'            # 沿用知识点难度
        assert job.knowledge_point_id == plan.tasks[0].knowledge_point_id

    def test_skip_existing_unless_force(self, app, user_factory):
        u = user_factory('mb_skip')
        plan = _seed_plan(u, n_tasks=3)
        db.session.add(StudyMaterial(user_id=u.id, kind='mindmap', title='旧文档',
                                     content='x', source='ai', plan_id=plan.id,
                                     task_id=plan.tasks[0].id))
        db.session.commit()
        _b1, q1, s1 = mq.enqueue(u, plan)
        assert (q1, s1) == (2, 1)                   # 已有成品的那条不重复产
        _b2, q2, s2 = mq.enqueue(u, plan, force=True)
        assert (q2, s2) == (3, 0)

    def test_unknown_kind_falls_back_to_mindmap(self, app, user_factory):
        u = user_factory('mb_kind')
        plan = _seed_plan(u, n_tasks=1)
        mq.enqueue(u, plan, kind='painting')          # 没有提示词模板的形态（lesson_plan 已转正）
        assert MaterialGenJob.query.first().kind == 'mindmap'


class TestProcessOnce:
    def test_generates_and_links_material(self, app, user_factory):
        u = user_factory('mb_run')
        plan = _seed_plan(u, n_tasks=3)
        batch_id, _q, _s = mq.enqueue(u, plan)
        assert mq.process_once() == 3
        mats = StudyMaterial.query.filter_by(plan_id=plan.id).all()
        assert len(mats) == 3
        assert {m.task_id for m in mats} == {t.id for t in plan.tasks}
        assert {m.source for m in mats} == {'ai'}
        assert mats[0].kind == 'mindmap'
        jobs = MaterialGenJob.query.filter_by(batch_id=batch_id).all()
        assert {j.status for j in jobs} == {'done'}
        assert all(j.material_id in {m.id for m in mats} for j in jobs)
        info = mq.batch_info(batch_id, u.id)
        assert info['done'] == 3 and info['pending'] == 0 and info['failed'] == 0

    def test_idempotent_no_double_material(self, app, user_factory):
        """重复排空不双生成：抢占靠条件 UPDATE，第二轮无 pending 可抢。"""
        u = user_factory('mb_twice')
        plan = _seed_plan(u, n_tasks=2)
        mq.enqueue(u, plan)
        mq.process_once()
        assert mq.process_once() == 0
        assert StudyMaterial.query.filter_by(plan_id=plan.id).count() == 2

    def test_force_redo_replaces_in_place(self, app, user_factory, monkeypatch):
        """force 重做只换正文不添重复行：真机实测曾出过 id 3-7 骨架与 id 8-12 成品共存的成对重复。"""
        u = user_factory('mb_force')
        plan = _seed_plan(u, n_tasks=2)
        mq.enqueue(u, plan)
        mq.process_once()
        old = {m.id: m.content for m in StudyMaterial.query.filter_by(plan_id=plan.id)}
        assert len(old) == 2
        kept = StudyMaterial.query.filter_by(plan_id=plan.id).order_by(StudyMaterial.id).first()
        kept.views = 7                       # 已积累的浏览数不该被重做洗掉
        db.session.commit()

        monkeypatch.setattr(svc, 'ai_generate_material',
                            lambda s, p, k, sub, d: (p + ' 重做版', False))
        batch_id, queued, skipped = mq.enqueue(u, plan, force=True)
        assert (queued, skipped) == (2, 0)   # force 意为重做，这里照投
        assert mq.process_once() == 2

        mats = StudyMaterial.query.filter_by(plan_id=plan.id).all()
        assert {m.id for m in mats} == set(old)             # 仍是原来那两行，未新建
        for m in mats:
            assert m.content.endswith('重做版') and m.content != old[m.id]
        assert db.session.get(StudyMaterial, kept.id).views == 7
        jobs = MaterialGenJob.query.filter_by(batch_id=batch_id).all()
        assert {j.material_id for j in jobs} == {m.id for m in mats}

    def test_claim_is_exclusive(self, app, user_factory):
        u = user_factory('mb_claim')
        plan = _seed_plan(u, n_tasks=1)
        mq.enqueue(u, plan)
        job = MaterialGenJob.query.first()
        assert mq._claim(job.id) is True
        assert mq._claim(job.id) is False
        assert db.session.get(MaterialGenJob, job.id).status == 'running'

    def test_running_residue_reset_each_round(self, app, user_factory):
        """崩溃遗留 running 由轮次开头复位，不会永久卡住。"""
        u = user_factory('mb_residue')
        plan = _seed_plan(u, n_tasks=1)
        mq.enqueue(u, plan)
        job = MaterialGenJob.query.first()
        job.status = 'running'
        db.session.commit()
        assert mq.process_once() == 1
        assert db.session.get(MaterialGenJob, job.id).status == 'done'

    def test_quota_blocked_keeps_pending(self, app, user_factory):
        """额度用尽 ≠ 失败：留 pending、不计 attempts、不产资料（次日自动续跑）。"""
        u = user_factory('mb_quota')
        plan = _seed_plan(u, n_tasks=2)
        db.session.add(AiQuota(user_id=u.id, daily_limit=2, used_today=2,
                               reset_date=local_today()))
        db.session.commit()
        mq.enqueue(u, plan)
        assert mq.process_once() == 0
        jobs = MaterialGenJob.query.all()
        assert {j.status for j in jobs} == {'pending'}
        assert all(j.attempts == 0 for j in jobs)
        assert StudyMaterial.query.count() == 0
        # 额度恢复后同一批可继续跑完
        quota = db.session.get(AiQuota, u.id)
        quota.used_today = 0
        db.session.commit()
        assert mq.process_once() == 2

    def test_failure_retries_then_failed(self, app, user_factory, monkeypatch):
        def boom(session, prompt, kind, subject, difficulty):
            raise RuntimeError('AI 上游 503')
        monkeypatch.setattr(svc, 'ai_generate_material', boom)
        u = user_factory('mb_fail')
        plan = _seed_plan(u, n_tasks=1)
        batch_id, _q, _s = mq.enqueue(u, plan)
        for expect in (1, 2):
            mq.process_once()
            assert db.session.query(MaterialGenJob).filter_by(batch_id=batch_id).one().attempts == expect
        mq.process_once()                                # 第 3 次达上限
        job = db.session.query(MaterialGenJob).filter_by(batch_id=batch_id).one()
        assert job.status == 'failed' and job.attempts == 3
        assert 'AI 调用异常' in (job.error or '')
        assert StudyMaterial.query.count() == 0

    def test_retry_failed_revives(self, app, user_factory, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError('503')
        monkeypatch.setattr(svc, 'ai_generate_material', boom)
        u = user_factory('mb_retry')
        plan = _seed_plan(u, n_tasks=2)
        batch_id, _q, _s = mq.enqueue(u, plan)
        for _ in range(3):
            mq.process_once()
        assert {j.status for j in MaterialGenJob.query.filter_by(batch_id=batch_id)} == {'failed'}
        assert mq.retry_failed(batch_id, u.id) == 2
        assert {j.attempts for j in MaterialGenJob.query.filter_by(batch_id=batch_id)} == {0}
        # 上游恢复后重跑成功
        monkeypatch.setattr(svc, 'ai_generate_material', _ok_content)
        assert mq.process_once() == 2
        assert StudyMaterial.query.filter_by(plan_id=plan.id).count() == 2


class TestBatchNotification:
    def test_one_notification_when_batch_done(self, app, user_factory):
        u = user_factory('mb_note')
        plan = _seed_plan(u, n_tasks=4)
        batch_id, _q, _s = mq.enqueue(u, plan)
        mq.process_once(limit=2)                     # 只跑一半：不该打扰用户
        assert Notification.query.filter_by(user_id=u.id).count() == 0
        mq.process_once()
        notes = Notification.query.filter_by(user_id=u.id).all()
        assert len(notes) == 1
        n = notes[0]
        assert n.related_type == 'material' and n.type == 'success'
        assert '4' in n.title
        assert '两周攻克数据结构' in n.content

    def test_failed_count_mentioned(self, app, user_factory, monkeypatch):
        """一份一直失败一份成功：通知必须把失败份数说出来，不假装全成功。"""
        def half_bad(session, prompt, kind, subject, difficulty):
            if '任务 2' in prompt:
                raise RuntimeError('上游持续 503')
            return _ok_content(session, prompt, kind, subject, difficulty)
        monkeypatch.setattr(svc, 'ai_generate_material', half_bad)
        u = user_factory('mb_note2')
        plan = _seed_plan(u, n_tasks=2)
        batch_id, _q, _s = mq.enqueue(u, plan)
        for _ in range(3):
            mq.process_once()
        info = mq.batch_info(batch_id, u.id)
        assert info['done'] == 1 and info['failed'] == 1
        n = Notification.query.filter_by(user_id=u.id).first()
        assert n is not None
        assert '1 份' in n.content and '失败' in n.content

    def test_teacher_unlimited_no_quota_row(self, app, user_factory):
        u = user_factory('mb_tea', role='teacher')
        plan = _seed_plan(u, n_tasks=5)
        mq.enqueue(u, plan)
        assert mq.process_once() == 5
        assert AiQuota.query.count() == 0              # 教师免额度约束亦不落配额行
        assert StudyMaterial.query.filter_by(plan_id=plan.id).count() == 5


# ── HTTP 层：真实 app + test_client（复用临时库，绝不碰 instance 真库）──
@pytest.fixture(scope='class')
def http_app():
    import app as prod
    prod._boot_done.set()
    prod.app.config['TESTING'] = True
    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False
    with prod.app.app_context():
        import competition.models   # noqa: F401
        import bounty.models        # noqa: F401
        import ledger.models        # noqa: F401
        import dsci.models          # noqa: F401
        import homework.models      # noqa: F401
        db.create_all()
        yield prod.app


@pytest.fixture()
def hclient(http_app):
    return http_app.test_client()


def _hregister(client, username, role='student'):
    r = client.post('/api/register', json={'username': username,
                                           'password': 'pw-123456', 'role': role})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['token']


def _h(hclient, token):
    return {'headers': {'Authorization': f'Bearer {token}'}}


def _make_plan(client, token, n_tasks=8):
    r = client.post('/api/learning/plans', json={'title': '批量文档计划'}, **_h(client, token))
    assert r.status_code == 200, r.get_json()
    plan_id = r.get_json()['id']
    for i in range(n_tasks):
        rr = client.post(f'/api/learning/plans/{plan_id}/tasks',
                         json={'title': f'看第 {i + 1} 章'}, **_h(client, token))
        assert rr.status_code == 200, rr.get_json()
    return plan_id


class TestHttpEndpoints:
    def test_batch_accepted_then_progress(self, http_app, hclient):
        token = _hregister(hclient, 'mb_http1')
        plan_id = _make_plan(hclient, token, n_tasks=8)
        with http_app.app_context():
            uid = User.query.filter_by(username='mb_http1').first().id
        r = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch',
                         json={'kind': 'mindmap'}, **_h(hclient, token))
        assert r.status_code == 202, r.get_json()
        body = r.get_json()
        assert body['queued'] == 8 and body['skipped'] == 0
        assert body['batch_id'] and body['total_tasks'] == 8

        with http_app.app_context():
            assert MaterialGenJob.query.filter_by(batch_id=body['batch_id']).count() == 8
            assert StudyMaterial.query.filter_by(plan_id=plan_id).count() == 0  # 受理不产资料
        p = hclient.get(f"/api/learning/material-jobs/{body['batch_id']}", **_h(hclient, token))
        assert p.status_code == 200
        assert p.get_json()['total'] == 8 and p.get_json()['finished'] is False

    def test_second_click_skips_done_tasks(self, http_app, hclient):
        """受理后再点：队列里未跑完的不重复投，已有成品的报 skipped。"""
        token = _hregister(hclient, 'mb_http2')
        plan_id = _make_plan(hclient, token, n_tasks=2)
        r = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch', json={},
                         **_h(hclient, token))
        assert r.status_code == 202
        first = r.get_json()['batch_id']
        with http_app.app_context():
            for j in MaterialGenJob.query.filter_by(batch_id=first):
                j.status = 'done'
            db.session.commit()
            db.session.add_all([StudyMaterial(user_id=j.user_id, kind='mindmap', title=j.title,
                                              content='x', source='ai', plan_id=j.plan_id,
                                              task_id=j.task_id)
                                for j in MaterialGenJob.query.filter_by(batch_id=first)])
            db.session.commit()
        r2 = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch', json={},
                          **_h(hclient, token))
        assert r2.status_code == 200                     # 无新作业：200 而非 202
        assert r2.get_json()['queued'] == 0 and r2.get_json()['skipped'] == 2

    def test_foreign_plan_404_and_empty_plan_400(self, http_app, hclient):
        t1 = _hregister(hclient, 'mb_http3a')
        t2 = _hregister(hclient, 'mb_http3b')
        plan_id = _make_plan(hclient, t1, n_tasks=1)
        r = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch', json={},
                         **_h(hclient, t2))
        assert r.status_code == 404
        r2 = hclient.post('/api/learning/plans', json={'title': '空计划'}, **_h(hclient, t1))
        empty_id = r2.get_json()['id']
        r3 = hclient.post(f'/api/learning/plans/{empty_id}/materials/batch', json={},
                          **_h(hclient, t1))
        assert r3.status_code == 400

    def test_quota_exhausted_429(self, http_app, hclient):
        token = _hregister(hclient, 'mb_http4')
        plan_id = _make_plan(hclient, token, n_tasks=3)
        with http_app.app_context():
            uid = User.query.filter_by(username='mb_http4').first().id
            db.session.add(AiQuota(user_id=uid, daily_limit=5, used_today=5,
                                   reset_date=local_today()))
            db.session.commit()
        r = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch', json={},
                         **_h(hclient, token))
        assert r.status_code == 429
        with http_app.app_context():
            assert MaterialGenJob.query.filter_by(user_id=uid).count() == 0

    def test_plan_documents_list(self, http_app, hclient):
        token = _hregister(hclient, 'mb_http5')
        plan_id = _make_plan(hclient, token, n_tasks=2)
        with http_app.app_context():
            u = User.query.filter_by(username='mb_http5').first()
            plan = db.session.get(StudyPlan, plan_id)
            db.session.add(StudyMaterial(user_id=u.id, kind='mindmap', title='文档一',
                                         content='# 正文', source='ai', plan_id=plan.id,
                                         task_id=plan.tasks[0].id))
            db.session.commit()
        r = hclient.get(f'/api/learning/plans/{plan_id}/materials', **_h(hclient, token))
        assert r.status_code == 200
        items = r.get_json()['items']
        assert len(items) == 1
        assert items[0]['task_title'] == '看第 1 章'   # 文档回指到具体任务
        assert items[0]['plan_id'] == plan_id

    def test_delete_material_clears_job_reference(self, http_app, hclient):
        """删批量生成的文档：作业行的反向引用要先清空，否则 PG 撞外键直接 500。

        SQLite 不强制外键，真机跑在 PG 上才爆（隐患 #23 同形状），本仓测试门原本
        看不见这个 violation，故这里钉「引用被置空」这一行为本身。"""
        token = _hregister(hclient, 'mb_http6')
        plan_id = _make_plan(hclient, token, n_tasks=1)
        r = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch', json={},
                         **_h(hclient, token))
        assert r.status_code == 202
        with http_app.app_context():
            mq.process_once()                    # 共享临时库，前面用例遗留的 pending 一并被吃掉
            mid = MaterialGenJob.query.filter_by(plan_id=plan_id).first().material_id
            assert mid is not None
        d = hclient.delete(f'/api/learning/materials/{mid}', **_h(hclient, token))
        assert d.status_code == 200, d.get_json()
        with http_app.app_context():
            assert MaterialGenJob.query.filter_by(plan_id=plan_id).first().material_id is None
            assert db.session.get(StudyMaterial, mid) is None

    def test_plan_delete_clears_batch_references(self, http_app, hclient):
        """删一个已出文档的计划：作业行删净、文档作为用户资产保留但摘掉反链。

        PG 上不清反链会直接 `ForeignKeyViolation`（真机取证于 2026-11-12），而
        SQLite 不强制外键，所以必须钉行为而不是依赖数据库报错。"""
        token = _hregister(hclient, 'mb_http7')
        plan_id = _make_plan(hclient, token, n_tasks=2)
        assert hclient.post(f'/api/learning/plans/{plan_id}/materials/batch', json={},
                            **_h(hclient, token)).status_code == 202
        with http_app.app_context():
            mq.process_once()
            uid = User.query.filter_by(username='mb_http7').first().id
            assert StudyMaterial.query.filter_by(plan_id=plan_id).count() == 2
        d = hclient.delete(f'/api/learning/plans/{plan_id}', **_h(hclient, token))
        assert d.status_code == 200, d.get_json()
        with http_app.app_context():
            assert MaterialGenJob.query.filter_by(plan_id=plan_id).count() == 0
            mats = StudyMaterial.query.filter_by(user_id=uid).all()      # 文档还在
            assert len(mats) == 2
            assert all(m.plan_id is None and m.task_id is None for m in mats)

    def test_task_delete_clears_batch_references(self, http_app, hclient):
        """删单条任务同样不能被子表钉住；同一计划其余任务的文档不受影响。"""
        token = _hregister(hclient, 'mb_http8')
        plan_id = _make_plan(hclient, token, n_tasks=2)
        assert hclient.post(f'/api/learning/plans/{plan_id}/materials/batch', json={},
                            **_h(hclient, token)).status_code == 202
        with http_app.app_context():
            mq.process_once()
            tid = StudyPlanTask.query.filter_by(plan_id=plan_id).first().id
            mid = StudyMaterial.query.filter_by(task_id=tid).first().id
        d = hclient.delete(f'/api/learning/plans/{plan_id}/tasks/{tid}',
                           **_h(hclient, token))
        assert d.status_code == 200, d.get_json()
        with http_app.app_context():
            assert MaterialGenJob.query.filter_by(task_id=tid).count() == 0
            kept = db.session.get(StudyMaterial, mid)
            assert kept.task_id is None and kept.plan_id == plan_id       # 只摘 task 链
            assert StudyPlanTask.query.filter_by(plan_id=plan_id).count() == 1


# ── v7.14 教案形态 ──

_LESSON_SECTIONS = ('教学基本信息', '学情分析', '教学目标', '教学重点与难点',
                    '教学准备', '教学过程', '板书设计', '作业布置', '教学反思')


class TestLessonPlanKind:
    def test_template_registered_and_renders(self):
        tpl = svc.MATERIAL_TEMPLATES['lesson_plan']
        assert svc.MATERIAL_KIND_NAMES['lesson_plan'].startswith('教案')
        text = tpl.format(prompt='链表的插入与删除', subject='数据结构', difficulty='medium')
        for seg in _LESSON_SECTIONS:
            assert seg in text, seg
        # 教案不同于讲义的地方：逐环节的时间与师生活动，不给只写“讲解概念”的空话余地
        assert '设计意图' in text and '45 分钟' in text
        assert '{' not in text and '}' not in text, '模板里不留未替换占位符'

    def test_generate_sends_lesson_plan_prompt(self, monkeypatch):
        seen = {}

        def fake_chat(messages, **kw):
            seen['user'] = messages[-1]['content']
            return '# 教案正文'
        monkeypatch.setattr(svc, 'ai_generate_material', _REAL_AI_GENERATE)
        monkeypatch.setattr(svc.ai_client, 'chat', fake_chat)
        content, degraded = svc.ai_generate_material(
            None, '链表的插入与删除', 'lesson_plan', '数据结构', 'medium')
        assert (content, degraded) == ('# 教案正文', False)
        assert '学情分析' in seen['user'] and '链表的插入与删除' in seen['user']
        assert '学科：数据结构' in seen['user']

    def test_degraded_gives_lesson_plan_skeleton_not_lecture(self):
        text = svc._degraded_material('lesson_plan', '链表', '数据结构', 'medium')
        assert text.startswith('【AI 服务暂不可用】')
        assert '环节' in text and '设计意图' in text and '板书设计' in text
        # 降级大纲也得是教案的骨架，不是拿讲义骨架凑数
        assert '概念定义' not in text
        other = svc._degraded_material('mindmap', '链表', '数据结构', 'medium')
        assert '概念定义' in other and '环节' not in other

    def test_db_check_accepts_lesson_plan(self, app, user_factory):
        """models 的 CHECK 真接住新值（本库走 db.create_all，与迁移同口径）。"""
        from sqlalchemy.exc import IntegrityError
        u = user_factory('mb_lp_ck')
        uid = u.id                    # 下面的 session.remove() 会让 u 脱管，先把主键取出来
        m = StudyMaterial(user_id=uid, kind='lesson_plan', title='教案',
                          content='# 教学过程', source='ai')
        db.session.add(m)
        db.session.commit()
        assert m.id is not None
        db.session.remove()
        with pytest.raises(IntegrityError):
            db.session.add(StudyMaterial(user_id=uid, kind='painting', title='x',
                                         content='x', source='ai'))
            db.session.commit()
        db.session.rollback()

    def test_queue_end_to_end_keeps_lesson_plan_kind(self, app, user_factory):
        u = user_factory('mb_lp_run')
        plan = _seed_plan(u, n_tasks=2)
        _b, queued, _s = mq.enqueue(u, plan, kind='lesson_plan')
        assert queued == 2
        assert {j.kind for j in MaterialGenJob.query.filter_by(plan_id=plan.id)} == {'lesson_plan'}
        assert mq.process_once() == 2
        mats = StudyMaterial.query.filter_by(plan_id=plan.id).all()
        assert len(mats) == 2 and {m.kind for m in mats} == {'lesson_plan'}

    def test_batch_endpoint_accepts_lesson_plan_and_rejects_unknown(self, http_app, hclient):
        token = _hregister(hclient, 'mb_lp_http')
        plan_id = _make_plan(hclient, token, n_tasks=2)
        r = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch',
                         json={'kind': 'lesson_plan'}, **_h(hclient, token))
        assert r.status_code == 202, r.get_json()
        assert r.get_json()['kind'] == 'lesson_plan'
        with http_app.app_context():
            assert {j.kind for j in MaterialGenJob.query.filter_by(
                batch_id=r.get_json()['batch_id'])} == {'lesson_plan'}
        bad = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch',
                           json={'kind': 'painting'}, **_h(hclient, token))
        assert bad.status_code == 400               # 未知形态不静默降级成 mindmap
        assert 'lesson_plan' in bad.get_json()['kinds']

    def test_kind_whitelist_single_source(self):
        """形态白名单四处同步护栏：models CHECK / 路由元组 / 模板表 / 迁移 0048。

        kind 上有 DB 级 CHECK，四处任何一处漏改都是运行期才爆的伤：模板有而 CHECK
        无→写库 IntegrityError；CHECK 有而模板无→ai_generate_material 抛 ValueError。
        """
        import importlib.util
        import os
        import re

        from api.learning_routes import _MATERIAL_KINDS

        ck = next(c for c in StudyMaterial.__table__.constraints
                  if type(c).__name__ == 'CheckConstraint' and c.name == '_material_kind_ck')
        allowed = set(re.findall(r"'([^']*)'", str(ck.sqltext)))
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'migrations', 'versions', '0048_material_lesson_plan.py')
        spec = importlib.util.spec_from_file_location('m0048', path)
        m0048 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m0048)

        assert allowed == set(m0048.KINDS_WITH_LESSON), '迁移与 models 的白名单不一致'
        assert set(_MATERIAL_KINDS) == allowed, '路由筛选集与 DB 白名单不一致'
        assert set(svc.MATERIAL_TEMPLATES) <= allowed, '有模板但库里存不下'
        assert set(svc.MATERIAL_TEMPLATES) == set(svc.MATERIAL_KIND_NAMES), '模板与显示名不同步'
        assert 'lesson_plan' in allowed and 'manual' not in svc.MATERIAL_TEMPLATES
