# -*- coding: utf-8 -*-
"""v7.18 回归门：文档形态互不阻挡、应用/生成成功落站内通知、资料附件与类型归档。

锁定语义：
- enqueue 的跳过判据带 kind（需求 c）：生成过讲义不该挡住生成教案，异形态各留一份；
  force 只替换同形态旧文档，不牵连其他形态。
- 文案随形态（需求 b）：批量完成通知标题带该形态中文名，不再一律「批量讲义」。
- 学习规划应用成功落站内通知（需求 a）：tasks/batch 带 notify 才发，related_type='plan'
  + related_id 供铃铛深链；通知写挂不得把已落库的计划报成失败。
- 单份 AI 生成成功落 related_type='material' 通知；降级（AI 不可用）不发，免得误报成功。
- 附件（需求 h）：后缀白名单、目录穿越拦截、只收 http(s) 链接、上限 20；
  下载接口卡归属（私有资料他人 403、公开后放行、链接类无本体返 400）。
- 按类型归档（需求 i）：资料库列表附 kind_groups，名字与生成下拉同源、七档全列。

AI 外呼一律 monkeypatch 替身，不打真模型。
"""
import io
from datetime import date

import pytest

from database import db
from database.models import (
    User, StudyPlan, StudyPlanTask, StudyMaterial, MaterialGenJob, Notification,
)

import ai_service.services as svc
import ai_service.material_queue as mq
from api.learning_routes import (_KIND_ORDER, _MATERIAL_KINDS, _att_type,
                                _normalize_attachments)


def _ok_content(session, prompt, kind, subject, difficulty):
    return f'# {prompt}\n\n（{kind}）正文', False


def _plan_of(user, n_tasks=3):
    plan = StudyPlan(user_id=user.id, title='v718计划', status='active',
                     start_date=date(2026, 1, 1))
    db.session.add(plan)
    db.session.commit()
    for i in range(n_tasks):
        db.session.add(StudyPlanTask(plan_id=plan.id, title=f'任务 {i + 1}',
                                     task_type='custom', order_num=i))
    db.session.commit()
    return plan


@pytest.fixture(autouse=True)
def _ai_stub(monkeypatch):
    monkeypatch.setattr(svc, 'ai_generate_material', _ok_content)


class TestKindIsolation:
    """需求 c：形态之间不该互相挡住，同形态重做才是原地替换。"""

    def test_kind_name_single_source(self):
        assert mq.kind_name('lesson_plan') == svc.MATERIAL_KIND_NAMES['lesson_plan']
        assert mq.kind_name('summary') == '高浓度摘要'
        assert mq.kind_name('painting') == '学习文档'      # 未知形态回落，不抛错

    def test_existing_lecture_does_not_block_lesson_plan(self, app, user_factory):
        u = user_factory('v18_kind')
        plan = _plan_of(u, 3)
        db.session.add(StudyMaterial(user_id=u.id, kind='mindmap', title='旧讲义',
                                     content='x', source='ai', plan_id=plan.id,
                                     task_id=plan.tasks[0].id))
        db.session.commit()
        # 同形态：那条已被成品占位，照旧跳过
        assert mq.enqueue(u, plan, kind='mindmap')[1:] == (2, 1)
        # 换教案：三条全投，一条都不该被跳过（旧口径这里是 0 排队 + 3 跳过）
        assert mq.enqueue(u, plan, kind='lesson_plan')[1:] == (3, 0)
        kinds = {j.kind for j in MaterialGenJob.query.filter_by(plan_id=plan.id)}
        assert kinds == {'mindmap', 'lesson_plan'}

    def test_inflight_jobs_not_queued_twice(self, app, user_factory):
        """连点两次不该投两批：成品是生成完才落库的，只看 study_material 会白跑一次 AI 调用。"""
        u = user_factory('v18_fly')
        plan = _plan_of(u, 2)
        assert mq.enqueue(u, plan, kind='quiz')[1:] == (2, 0)
        assert mq.enqueue(u, plan, kind='quiz')[1:] == (0, 2)      # 还在排队，不重复产
        assert MaterialGenJob.query.filter_by(plan_id=plan.id, kind='quiz').count() == 2
        # 换形态照投、force 照越：去重只管同一形态的在飞作业
        assert mq.enqueue(u, plan, kind='summary')[1:] == (2, 0)
        assert mq.enqueue(u, plan, kind='quiz', force=True)[1:] == (2, 0)

    def test_two_kinds_coexist_and_force_touches_only_its_own(self, app, user_factory):
        u = user_factory('v18_co')
        plan = _plan_of(u, 2)
        mq.enqueue(u, plan, kind='mindmap')
        assert mq.process_once() == 2
        mq.enqueue(u, plan, kind='lesson_plan')
        assert mq.process_once() == 2
        rows = StudyMaterial.query.filter_by(plan_id=plan.id).all()
        assert len(rows) == 4
        assert {r.kind for r in rows} == {'mindmap', 'lesson_plan'}
        mind_ids = {r.id for r in rows if r.kind == 'mindmap'}
        lesson_ids = {r.id for r in rows if r.kind == 'lesson_plan'}

        mq.enqueue(u, plan, kind='mindmap', force=True)
        assert mq.process_once() == 2                    # 两条都已有同形态 → force 照投
        after = StudyMaterial.query.filter_by(plan_id=plan.id).all()
        assert len(after) == 4                           # 没多出重复行
        assert {r.id for r in after if r.kind == 'mindmap'} == mind_ids
        assert {r.id for r in after if r.kind == 'lesson_plan'} == lesson_ids

    def test_batch_notify_title_follows_kind(self, app, user_factory):
        u = user_factory('v18_title')
        plan = _plan_of(u, 2)
        mq.enqueue(u, plan, kind='summary')
        mq.process_once()
        n = Notification.query.filter_by(user_id=u.id).first()
        assert n is not None
        assert '高浓度摘要' in n.title
        assert '讲义' not in n.title and '批量学习文档' not in n.title
        assert n.related_type == 'material' and n.type == 'success'


class TestAttachmentValidation:
    """附件校验口径：非法条目丢弃而不整批报错（用户粘一堆链接不该因一条失败全存不下）。"""

    def test_att_type_by_ext(self):
        assert _att_type('.docx') == 'doc' and _att_type('.DOC') == 'doc'
        assert _att_type('.xlsx') == 'sheet' and _att_type('.csv') == 'sheet'
        assert _att_type('.pptx') == 'slide' and _att_type('.pdf') == 'pdf'
        assert _att_type('.png') == 'image' and _att_type('.mp4') == 'video'
        assert _att_type('.zip') == 'archive' and _att_type('.py') == 'code'
        assert _att_type('') == 'doc' and _att_type('.unknown') == 'doc'
        # 无后缀形态只能由用户声明：link/mindmap 认，其他一律回落查表
        assert _att_type('', 'mindmap') == 'mindmap'
        assert _att_type('.png', 'mindmap') == 'mindmap'
        assert _att_type('.png', 'fancy') == 'image'

    def test_normalize_keeps_legal_files(self):
        out = _normalize_attachments([
            {'name': '课件.pdf', 'stored_name': 'work_abc.pdf', 'size': 12},
            {'name': '数据表.xlsx', 'stored_name': 'work_def.xlsx', 'size': 34},
        ])
        assert len(out) == 2
        assert out[0]['type'] == 'pdf' and out[0]['stored_name'] == 'work_abc.pdf'
        assert out[1]['type'] == 'sheet'
        assert all(o['uploaded_at'] for o in out)

    def test_normalize_rejects_bad_entries(self):
        out = _normalize_attachments([
            {'stored_name': 'virus.exe'},                       # 白名单外后缀
            {'stored_name': '../../etc/passwd.md'},             # 目录穿越 → 只取最后一段
            {'url': 'javascript:alert(1)'},                     # 非 http(s) 链接
            {'name': '空条目'},                                  # 既无本体也无链接
            '不是字典',
        ])
        assert len(out) == 1
        assert out[0]['stored_name'] == 'passwd.md'             # basename 后仍在白名单内
        assert out[0]['type'] == 'text'

    def test_normalize_links(self):
        out = _normalize_attachments([
            {'url': 'https://www.bilibili.com/video/BV1', 'name': '配套视频', 'type': 'video'},
            {'url': 'https://x.mm.com/a', 'type': 'doc'},        # 链接只认 link/mindmap
        ])
        assert len(out) == 2
        assert out[0]['type'] == 'video' and 'stored_name' not in out[0]
        assert out[0]['url'].startswith('https://') and out[0]['size'] == 0
        assert out[1]['type'] == 'link'

    def test_normalize_caps_at_limit(self):
        out = _normalize_attachments([{'url': f'https://a.com/{i}'} for i in range(50)])
        assert len(out) == 20

    def test_normalize_non_list(self):
        assert _normalize_attachments(None) == []
        assert _normalize_attachments({'url': 'https://a.com'}) == []


# ── HTTP 层：真实 app + test_client（复用 conftest 的临时库与 uploads 沙箱）──
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


def _register(client, username, role='student'):
    r = client.post('/api/register', json={'username': username,
                                           'password': 'pw-123456', 'role': role})
    assert r.status_code == 200, r.get_json()
    return r.get_json()['token']


def _h(token):
    return {'headers': {'Authorization': f'Bearer {token}'}}


class TestPlanAppliedNotification:
    """需求 a：应用成功要出现在消息提示里，且通知异常不拖累主流程。"""

    def test_notify_flag_creates_plan_notification(self, http_app, hclient):
        token = _register(hclient, 'v18_ap1')
        plan_id = hclient.post('/api/learning/plans', json={'title': '应用通知'},
                               **_h(token)).get_json()['id']
        r = hclient.post(f'/api/learning/plans/{plan_id}/tasks/batch',
                         json={'items': [{'title': '任务甲'}, {'title': '任务乙'}],
                               'notify': True}, **_h(token))
        assert r.status_code == 200 and r.get_json()['added'] == 2
        with http_app.app_context():
            uid = User.query.filter_by(username='v18_ap1').first().id
            notes = Notification.query.filter_by(user_id=uid).all()
            assert len(notes) == 1
            n = notes[0]
            assert n.related_type == 'plan' and n.related_id == plan_id
            assert n.title == '学习规划已应用' and n.type == 'success'
            assert '应用通知' in n.content and '2 个任务' in n.content

    def test_without_flag_no_notification(self, http_app, hclient):
        """手动新建计划不传 notify：不该产噪音（否则每加一条任务就响一次）。"""
        token = _register(hclient, 'v18_ap2')
        plan_id = hclient.post('/api/learning/plans', json={'title': '静默添加'},
                               **_h(token)).get_json()['id']
        r = hclient.post(f'/api/learning/plans/{plan_id}/tasks/batch',
                         json={'items': [{'title': '任务甲'}]}, **_h(token))
        assert r.get_json()['added'] == 1
        with http_app.app_context():
            uid = User.query.filter_by(username='v18_ap2').first().id
            assert Notification.query.filter_by(user_id=uid, related_type='plan').count() == 0

    def test_no_items_added_skips_notification(self, http_app, hclient):
        token = _register(hclient, 'v18_ap3')
        plan_id = hclient.post('/api/learning/plans', json={'title': '全是重复'},
                               **_h(token)).get_json()['id']
        first = hclient.post(f'/api/learning/plans/{plan_id}/tasks/batch',
                             json={'items': [{'title': '任务甲'}], 'notify': True}, **_h(token))
        assert first.get_json()['added'] == 1
        again = hclient.post(f'/api/learning/plans/{plan_id}/tasks/batch',
                             json={'items': [{'title': '任务甲'}], 'notify': True}, **_h(token))
        assert again.get_json()['added'] == 0
        with http_app.app_context():
            uid = User.query.filter_by(username='v18_ap3').first().id
            assert Notification.query.filter_by(user_id=uid).count() == 1

    def test_notification_failure_does_not_fail_apply(self, http_app, hclient, monkeypatch):
        """通知是旁路：它写挂了也必须照常返回 200（任务已落库，不能假报失败）。"""
        token = _register(hclient, 'v18_ap4')
        plan_id = hclient.post('/api/learning/plans', json={'title': '旁路异常'},
                               **_h(token)).get_json()['id']

        def boom(*a, **kw):
            raise RuntimeError('通知服务炸了')
        monkeypatch.setattr('api.learning_routes.create_notification', boom)
        r = hclient.post(f'/api/learning/plans/{plan_id}/tasks/batch',
                         json={'items': [{'title': '任务甲'}], 'notify': True}, **_h(token))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['added'] == 1
        with http_app.app_context():
            uid = User.query.filter_by(username='v18_ap4').first().id
            assert StudyPlanTask.query.filter_by(plan_id=plan_id).count() == 1


class TestMaterialGenerateNotification:
    """需求 b：单份生成成功落站内通知并带 related_id 供直达；降级不落。"""

    def test_success_notifies_with_related_id(self, http_app, hclient):
        token = _register(hclient, 'v18_g1', role='teacher')     # 教师免额度约束
        r = hclient.post('/api/learning/materials/generate',
                         json={'prompt': '链表的插入与删除', 'kind': 'lesson_plan'},
                         **_h(token))
        assert r.status_code == 200, r.get_json()
        mid = r.get_json()['material']['id']
        with http_app.app_context():
            uid = User.query.filter_by(username='v18_g1').first().id
            n = Notification.query.filter_by(user_id=uid, related_type='material').first()
            assert n is not None
            assert n.related_id == mid
            assert '教案' in n.title and n.type == 'success'
            assert '链表的插入与删除' in n.content

    def test_degraded_result_stays_silent(self, http_app, hclient, monkeypatch):
        """AI 不可用时落的是降级骨架，不该发「已生成」通知误报成功。"""
        token = _register(hclient, 'v18_g2', role='teacher')
        monkeypatch.setattr(svc, 'ai_generate_material',
                            lambda s, p, k, sub, d: ('【AI 服务暂不可用】骨架', True))
        r = hclient.post('/api/learning/materials/generate',
                         json={'prompt': '栈与队列', 'kind': 'summary'}, **_h(token))
        assert r.status_code == 200 and r.get_json()['source'] == 'rule'
        with http_app.app_context():
            uid = User.query.filter_by(username='v18_g2').first().id
            assert Notification.query.filter_by(user_id=uid).count() == 0

    def test_batch_reply_carries_kind_name(self, http_app, hclient):
        token = _register(hclient, 'v18_g3')
        plan_id = hclient.post('/api/learning/plans', json={'title': '形态文案'},
                               **_h(token)).get_json()['id']
        hclient.post(f'/api/learning/plans/{plan_id}/tasks', json={'title': '任务甲'},
                     **_h(token))
        r = hclient.post(f'/api/learning/plans/{plan_id}/materials/batch',
                         json={'kind': 'quiz'}, **_h(token))
        assert r.status_code == 202, r.get_json()
        body = r.get_json()
        assert body['kind_name'] == '练习题集'
        assert '练习题集' in body['message'] and '讲义' not in body['message']


class TestMaterialAttachmentsHttp:
    """需求 h：上传 → 挂到资料 → 受控下载（权限与内联语义）。"""

    def _upload(self, client, token, name='课件.pdf', data=b'%PDF-1.4 stub'):
        r = client.post('/api/learning/attachments',
                        data={'file': (io.BytesIO(data), name, 'application/pdf')},
                        headers={'Authorization': f'Bearer {token}'},
                        content_type='multipart/form-data')
        assert r.status_code == 201, r.get_json()
        return r.get_json()

    def test_upload_returns_stored_name_and_ext(self, http_app, hclient):
        token = _register(hclient, 'v18_at0')
        d = self._upload(hclient, token)
        assert d['stored_name'].endswith('.pdf') and d['ext'] == '.pdf'
        assert d['name'] == '课件.pdf' and d['size'] > 0 and d['url'].startswith('/uploads/')

    def test_owner_reads_public_and_inline_urls(self, http_app, hclient):
        token = _register(hclient, 'v18_at1')
        up = self._upload(hclient, token)
        link = {'name': '思维导图在线版', 'url': 'https://mm.example.com/a', 'type': 'mindmap'}
        r = hclient.post('/api/learning/materials',
                         json={'title': '带附件的资料', 'content': '# 正文',
                               'attachments': [{'name': up['name'],
                                                'stored_name': up['stored_name'],
                                                'size': up['size']}, link]},
                         **_h(token))
        assert r.status_code == 200, r.get_json()
        mat = r.get_json()['material']
        atts = mat['attachments']
        assert len(atts) == 2
        assert atts[0]['type'] == 'pdf' and atts[0]['url'].startswith('/uploads/')
        assert atts[0]['download_url'].endswith('/attachments/0/download')
        assert 'inline=1' in atts[0]['inline_url']
        # 链接类无本体：不拼伪下载地址，inline 只在图片/视频上有值
        assert 'stored_name' not in atts[1] and atts[1]['type'] == 'mindmap'
        assert atts[1]['inline_url'] is None

        d = hclient.get(atts[0]['download_url'], **_h(token))
        assert d.status_code == 200
        assert 'attachment' in (d.headers.get('Content-Disposition') or '')
        i = hclient.get(atts[0]['inline_url'], **_h(token))
        assert i.status_code == 200
        assert 'attachment' not in (i.headers.get('Content-Disposition') or '')

    def test_private_attachment_denied_to_others(self, http_app, hclient):
        owner = _register(hclient, 'v18_at2')
        other = _register(hclient, 'v18_at3')
        up = self._upload(hclient, owner)
        mid = hclient.post('/api/learning/materials',
                           json={'title': '私有附件', 'content': 'x',
                                 'attachments': [{'stored_name': up['stored_name'],
                                                  'name': up['name']}]},
                           **_h(owner)).get_json()['material']['id']
        url = f'/api/learning/materials/{mid}/attachments/0/download'
        assert hclient.get(url, **_h(other)).status_code == 403
        assert hclient.get(url, **_h(owner)).status_code == 200
        # 公开后他人可读（附件随资料一起公开，与正文同口径）
        assert hclient.put(f'/api/learning/materials/{mid}', json={'is_public': True},
                           **_h(owner)).status_code == 200
        assert hclient.get(url, **_h(other)).status_code == 200

    def test_illegal_attachments_are_dropped(self, http_app, hclient):
        token = _register(hclient, 'v18_at4')
        r = hclient.post('/api/learning/materials',
                         json={'title': '脏附件', 'content': 'x',
                               'attachments': [
                                   {'stored_name': 'a.exe', 'name': '木马'},
                                   {'url': 'javascript:alert(1)', 'name': '伪链接'},
                                   {'name': '什么都没有'},
                               ]},
                         **_h(token))
        assert r.status_code == 200
        assert r.get_json()['material']['attachments'] == []
        with http_app.app_context():
            m = db.session.get(StudyMaterial, r.get_json()['material']['id'])
            assert not m.attachment_json           # 全丢后落 None，不留空数组

    def test_update_rewrites_whole_list(self, http_app, hclient):
        token = _register(hclient, 'v18_at5')
        up = self._upload(hclient, token, name='表格.xlsx', data=b'PK\x03\x04stub')
        mid = hclient.post('/api/learning/materials',
                           json={'title': '改附件', 'content': 'x',
                                 'attachments': [{'stored_name': up['stored_name'],
                                                  'name': up['name']}]},
                           **_h(token)).get_json()['material']['id']
        r = hclient.put(f'/api/learning/materials/{mid}', json={'attachments': []}, **_h(token))
        assert r.get_json()['material']['attachments'] == []
        r2 = hclient.put(f'/api/learning/materials/{mid}',
                         json={'attachments': [{'stored_name': up['stored_name'],
                                                'name': up['name']}]}, **_h(token))
        atts = r2.get_json()['material']['attachments']
        assert len(atts) == 1 and atts[0]['type'] == 'sheet'

    def test_link_attachment_has_no_body(self, http_app, hclient):
        token = _register(hclient, 'v18_at6')
        mid = hclient.post('/api/learning/materials',
                           json={'title': '只有链接', 'content': 'x',
                                 'attachments': [{'url': 'https://a.com/b', 'name': '外链'}]},
                           **_h(token)).get_json()['material']['id']
        r = hclient.get(f'/api/learning/materials/{mid}/attachments/0/download', **_h(token))
        assert r.status_code == 400                # 链接类没有本体文件

    def test_missing_index_404(self, http_app, hclient):
        token = _register(hclient, 'v18_at7')
        mid = hclient.post('/api/learning/materials',
                           json={'title': '无附件资料', 'content': 'x'},
                           **_h(token)).get_json()['material']['id']
        assert hclient.get(f'/api/learning/materials/{mid}/attachments/3/download',
                           **_h(token)).status_code == 404


class TestKindGroups:
    """需求 i：资料库按生成文档类型分栏归档（教案一栏、练习题集一栏……）。"""

    def test_group_order_covers_db_whitelist(self):
        """分栏顺序表必须跟 DB 白名单同集：新增形态只改一处，那一栏会默默缺席。"""
        assert set(_KIND_ORDER) == set(_MATERIAL_KINDS)

    def test_list_returns_every_group_with_official_names(self, http_app, hclient):
        token = _register(hclient, 'v18_kg1')
        for kind, title in (('mindmap', '讲义甲'), ('mindmap', '讲义乙'),
                            ('lesson_plan', '教案甲'), ('manual', '手写甲')):
            r = hclient.post('/api/learning/materials',
                             json={'title': title, 'content': 'x', 'kind': kind}, **_h(token))
            assert r.status_code == 200, r.get_json()
        groups = hclient.get('/api/learning/materials', **_h(token)).get_json()['kind_groups']
        assert [g['kind'] for g in groups] == list(_KIND_ORDER)   # 0 份的档也在，分栏骨架不能缺
        counts = {g['kind']: g['count'] for g in groups}
        assert counts['mindmap'] == 2 and counts['lesson_plan'] == 1 and counts['manual'] == 1
        assert counts['quiz'] == 0
        names = {g['kind']: g['name'] for g in groups}
        # 名字与「生成学习文档」下拉同源，不再一边「教案」一边「教案（教学设计）」
        assert names['lesson_plan'] == svc.MATERIAL_KIND_NAMES['lesson_plan']
        assert names['mindmap'] == svc.MATERIAL_KIND_NAMES['mindmap']
        assert names['manual'] == '手写资料'

    def test_counts_ignore_current_filter(self, http_app, hclient):
        """分栏是导航骨架：选了「教案」后其他档的数字不该被筛得乱跳。"""
        token = _register(hclient, 'v18_kg2')
        for kind in ('quiz', 'quiz', 'summary'):
            hclient.post('/api/learning/materials',
                         json={'title': f'{kind}档', 'content': 'x', 'kind': kind}, **_h(token))
        r = hclient.get('/api/learning/materials?kind=quiz', **_h(token))
        body = r.get_json()
        assert body['total'] == 2
        assert {g['kind']: g['count'] for g in body['kind_groups']}['quiz'] == 2
        assert {g['kind']: g['count'] for g in body['kind_groups']}['summary'] == 1

    def test_groups_are_per_user(self, http_app, hclient):
        a = _register(hclient, 'v18_kg3a')
        b = _register(hclient, 'v18_kg3b')
        hclient.post('/api/learning/materials', json={'title': '甲的教案', 'content': 'x',
                                                     'kind': 'lesson_plan'}, **_h(a))
        mine = {g['kind']: g['count'] for g in
                hclient.get('/api/learning/materials', **_h(b)).get_json()['kind_groups']}
        assert mine['lesson_plan'] == 0
