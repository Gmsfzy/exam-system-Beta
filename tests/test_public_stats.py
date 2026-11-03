# -*- coding: utf-8 -*-
"""v6.1 首页公开统计端点回归（HTTP 层，真实 app + test_client）。

覆盖：
  GET /api/stats/public 零鉴权可达 + 响应形状
  六模块条顺序与首页 modules 口径一致
  聚合数随真实数据增长（题库/帖子/评论/作业提交）
  软删与折叠内容不进公开计数
  今日窗口按本地日历日切（昨日打卡不计入 today）
  只出聚合、不出个体（响应体不含任何可识别字段）
  60s 缓存命中标记

说明：复用 conftest 已改指的临时库；conftest 的 user_factory/app 夹具走的是另一个
空壳 Flask + 内存库，会把 db 引擎切走，故本文件的行一律在 stats_app 上下文内手建。
"""
from datetime import timedelta

import pytest

from database import db
from utils.timeutil import utcnow, local_today


@pytest.fixture(scope='module')
def stats_app():
    """真实 app 单例：跳过 bootstrap、关闭限流、建全表。"""
    import app as prod

    prod._boot_done.set()
    prod.app.config['TESTING'] = True

    from utils import security as sec
    if sec.limiter is not None:
        sec.limiter.enabled = False

    with prod.app.app_context():
        import database.models      # noqa: F401
        import competition.models   # noqa: F401
        import bounty.models        # noqa: F401
        import ledger.models        # noqa: F401
        import dsci.models          # noqa: F401
        import homework.models      # noqa: F401
        db.create_all()
        yield prod.app
        db.session.remove()


@pytest.fixture()
def client(stats_app):
    """缓存跨用例残留会让断言看到上一个用例的数字，每次先清掉。"""
    from utils.redis_cache import delete_cache
    from api.stats_routes import _CACHE_KEY

    with stats_app.app_context():
        delete_cache(_CACHE_KEY)
    return stats_app.test_client()


def _mk_user(username, role='student'):
    from database.models import User
    u = User(username=username, role=role)
    u.set_password('test-pw')
    db.session.add(u)
    db.session.commit()
    return u


def _get(client):
    r = client.get('/api/stats/public')
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_public_stats_no_auth_and_shape(client):
    """零鉴权可达，且 counters / today / ai / modules 四段齐全。"""
    body = _get(client)

    for k in ('users', 'questions', 'public_questions', 'exams', 'answers',
              'homework_submissions', 'bounties', 'pk_battles', 'wrong_records',
              'posts', 'comments', 'materials'):
        assert k in body['counters'], k
        assert isinstance(body['counters'][k], int)

    for k in ('checkins', 'ai_calls', 'results', 'new_posts', 'new_submissions'):
        assert isinstance(body['today'][k], int), k

    assert isinstance(body['ai']['avg_cost_ms'], int)
    assert body['ai']['calls_today'] == body['today']['ai_calls']
    assert body['local_day'] == local_today().isoformat()
    assert body['server_time']           # iso_local 非空
    assert body['cached'] is False


def test_public_stats_six_modules_in_order(client):
    """六模块条顺序与首页 modules 口径一致（考试/竞赛/悬赏/学习/作业/社区）。"""
    mods = _get(client)['modules']
    assert [m['key'] for m in mods] == [
        'exam', 'competition', 'bounty', 'learning', 'homework', 'community']
    assert [m['label'] for m in mods] == [
        '在线考试', '答题竞赛', '征集悬赏', '自主学习', '作业练习', '社区中心']
    for m in mods:
        assert isinstance(m['value'], int) and m['hint']


def test_public_stats_aggregates_real_rows(stats_app, client):
    """写入真实行后聚合数跟着涨：验证统计口径确实打到这些表。"""
    from database.models import Major, Question, CommunityPost, CommunityComment
    from homework.models import HomeworkSubmission
    from utils.redis_cache import delete_cache
    from api.stats_routes import _CACHE_KEY

    before = _get(client)['counters']

    with stats_app.app_context():
        t = _mk_user('stats_teacher_1', 'teacher')
        s = _mk_user('stats_student_1', 'student')
        m = Major(name='统计看板测试专业')
        db.session.add(m)
        db.session.commit()          # 先落 Major 拿到自增 id，再建题（避免 autoflush 时 major_id 仍为 None）
        db.session.add(Question(content='1+1=?', answer='2', type='single_choice',
                                difficulty='easy', major_id=m.id,
                                creator_id=t.id, is_public=True))
        db.session.add(CommunityPost(title='求助', content='内容', author_id=s.id))
        db.session.commit()
        p = CommunityPost.query.filter_by(deleted=False).first()
        db.session.add(CommunityComment(post_id=p.id, content='回帖', author_id=t.id))
        db.session.add(HomeworkSubmission(homework_id=1, student_id=s.id,
                                         status='submitted', submitted_at=utcnow()))
        db.session.commit()

    delete_cache(_CACHE_KEY)
    after = _get(client)['counters']
    assert after['users'] == before['users'] + 2
    assert after['questions'] == before['questions'] + 1
    assert after['public_questions'] == before['public_questions'] + 1
    assert after['posts'] == before['posts'] + 1
    assert after['comments'] == before['comments'] + 1
    assert after['homework_submissions'] == before['homework_submissions'] + 1


def test_public_stats_excludes_hidden_and_deleted(stats_app, client):
    """软删/折叠内容不进公开计数（与社区管理后台口径一致）。"""
    from database.models import CommunityPost
    from utils.redis_cache import delete_cache
    from api.stats_routes import _CACHE_KEY

    with stats_app.app_context():
        seed = CommunityPost.query.filter_by(deleted=False).first()
        if seed is None:
            author = _mk_user('stats_seed_1')
            db.session.add(CommunityPost(title='底帖', content='x', author_id=author.id))
            db.session.commit()
            seed = CommunityPost.query.filter_by(deleted=False).first()
        db.session.add(CommunityPost(title='已删', content='x',
                                     author_id=seed.author_id, deleted=True))
        db.session.add(CommunityPost(title='折叠', content='x',
                                     author_id=seed.author_id, hidden=True))
        db.session.commit()

    posts_before = _get(client)['counters']['posts']   # 走缓存前已含新帖
    delete_cache(_CACHE_KEY)
    assert _get(client)['counters']['posts'] == posts_before


def test_public_stats_today_window_respects_local_day(stats_app, client):
    """昨日打卡不计进 today.checkins（本地日历日切，非 UTC 日）。

    临时库全模块共享，E2E 也可能写入当日打卡，故只断增量不断绝对值。"""
    from database.models import User, StudyCheckin
    from utils.redis_cache import delete_cache
    from api.stats_routes import _CACHE_KEY

    checkins_before = _get(client)['today']['checkins']
    delete_cache(_CACHE_KEY)

    with stats_app.app_context():
        u = User.query.filter_by(role='student').first()
        if u is None:
            u = _mk_user('stats_ck_student', 'student')
        today = local_today()
        db.session.add(StudyCheckin(user_id=u.id, day=today, minutes=12))
        db.session.add(StudyCheckin(user_id=u.id, day=today - timedelta(days=1),
                                    minutes=30))
        db.session.commit()

    delete_cache(_CACHE_KEY)
    body = _get(client)
    assert body['today']['checkins'] == checkins_before + 1   # 只多今天这一条
    assert body['local_day'] == today.isoformat()


def test_public_stats_no_pii_leak(client):
    """响应体只含聚合数字：不得出现任何个体标识/内容字段。"""
    blob = str(_get(client))
    for forbidden in ('author_id', 'student_id', 'username', 'title',
                      'content', 'email', 'password', 'token'):
        assert forbidden not in blob, forbidden


def test_public_stats_cache_hit(client):
    """连续两次请求：第二次走缓存（缓存后端不可用时两次均为 False，不判红）。"""
    from utils.redis_cache import is_redis_available

    first = _get(client)
    second = _get(client)
    assert first['cached'] is False
    assert second['cached'] is (True if is_redis_available() else False)
    assert second['counters'] == first['counters']
