# -*- coding: utf-8 -*-
"""v7.5 auto 档「视情降级」的判定矩阵单测。

要守住的口径有两条，方向相反：
- 没有 PG 的机器（老师/教授的本本）必须能起来，读到与 PG 一致的镜像数据；
- 装了 PG 只是连不上（服务停了/密码错/库没建/远程不可达）绝不能静默回落，
  那正是 v6.8 的双库分叉事故：看着在用 PG，新数据全落在本地 SQLite 里且不报错。

测试不连真 PG：探活、端口、服务与二进制探测全部 monkeypatch 掉，只验判定逻辑本身。
"""
import os

import pytest
from sqlalchemy import create_engine, text

import config as cfgmod


FAKE_PG_URL = 'postgresql+psycopg2://exam:pw@127.0.0.1:5432/exam_system'
FAKE_REMOTE_URL = 'postgresql+psycopg2://exam:pw@pgm-x.pg.rds.aliyuncs.com:5432/exam_system'


@pytest.fixture(autouse=True)
def _clean_offline_state():
    cfgmod._OFFLINE_FALLBACK.clear()
    yield
    cfgmod._OFFLINE_FALLBACK.clear()


@pytest.fixture()
def env(monkeypatch):
    """把 DB_BACKEND / DATABASE_URL 设成用例需要的值（绕开 .env 的 override 干扰）。"""
    def _set(backend='auto', url=FAKE_PG_URL):
        monkeypatch.setenv('DB_BACKEND', backend)
        monkeypatch.setenv('DATABASE_URL', url or '')
        return monkeypatch
    return _set


@pytest.fixture()
def probe_fail(monkeypatch):
    """探活必失败，并给出一个真实世界常见的错因文案。"""
    def _raise(_url, timeout=3):
        raise OSError('connection to server at 127.0.0.1 failed: Connection refused')
    monkeypatch.setattr(cfgmod, '_probe_postgres', _raise)
    return monkeypatch


@pytest.fixture()
def probe_ok(monkeypatch):
    monkeypatch.setattr(cfgmod, '_probe_postgres', lambda _url, timeout=3: None)
    return monkeypatch


def _no_pg_here(monkeypatch):
    """伪装成「这台机器压根没装 PG」：端口没人听、无服务、无二进制。"""
    monkeypatch.setattr(cfgmod, '_tcp_open', lambda h, p, timeout=0.6: False)
    monkeypatch.setattr(cfgmod, '_pg_service_names', lambda: [])
    monkeypatch.setattr(cfgmod, '_pg_service_units', lambda: [])
    monkeypatch.setattr(cfgmod, '_pg_binary_present', lambda: False)


# ────────────────────────── 「没装 PG」的识别 ──────────────────────────

def test_installed_probe_prefers_tcp_listener(monkeypatch):
    """端口上有监听就是「PG 装着」，不必再去看服务与二进制（也是最直接的一条）。"""
    calls = []
    monkeypatch.setattr(cfgmod, '_tcp_open', lambda h, p, timeout=0.6: True)
    monkeypatch.setattr(cfgmod, '_pg_service_names', lambda: calls.append(1) or ['postgresql-x64-17'])
    absent, detail = cfgmod._pg_installed_on_this_machine('127.0.0.1', 5432)
    assert absent is False
    assert '监听' in detail
    assert not calls, 'TCP 已判定存在就不该再花一次注册表枚举'


def test_installed_probe_reads_service_registry(monkeypatch):
    """端口没人听但服务键还在 = 服务被停了，同样不能当成「没装」。"""
    _no_pg_here(monkeypatch)
    monkeypatch.setattr(cfgmod, '_pg_service_names', lambda: ['postgresql-x64-17'])
    absent, detail = cfgmod._pg_installed_on_this_machine('127.0.0.1', 5432)
    assert absent is False
    assert 'postgresql-x64-17' in detail and '停止' in detail


def test_installed_probe_accepts_binary_as_evidence(monkeypatch):
    """没有服务记录但 PATH/安装目录里有 PG（源码安装、便携版）也算装了。"""
    _no_pg_here(monkeypatch)
    monkeypatch.setattr(cfgmod, '_pg_binary_present', lambda: True)
    assert cfgmod._pg_installed_on_this_machine('127.0.0.1', 5432)[0] is False


def test_installed_probe_true_only_when_all_evidence_missing(monkeypatch):
    _no_pg_here(monkeypatch)
    absent, detail = cfgmod._pg_installed_on_this_machine('127.0.0.1', 5432)
    assert absent is True
    assert '未检测到' in detail


@pytest.mark.parametrize('host', ['pgm-x.pg.rds.aliyuncs.com', '192.168.1.20', '10.0.0.5'])
def test_remote_target_is_never_treated_as_absent(monkeypatch, host):
    """远程/云端目标不可达时不能推断「对方没装 PG」：本机证据对远程毫无意义。"""
    _no_pg_here(monkeypatch)
    absent, detail = cfgmod._pg_installed_on_this_machine(host, 5432)
    assert absent is False
    assert '不是本机' in detail


@pytest.mark.parametrize('host', ['127.0.0.1', 'localhost', '::1'])
def test_loopback_hosts_are_eligible_for_the_absence_check(host):
    assert host in cfgmod._LOCAL_HOSTS


# ────────────────────────── 镜像可用性 ──────────────────────────

def _make_mirror(path, users=('teacher_offline',)):
    """造一份「像完整库」的镜像：全量 create_all + alembic_version + user 行。

    插行走 Table 对象而不是裸 SQL：列默认值（如 created_at）得让元数据自己带上，
    手写 SQL 漏一个 NOT NULL 列就会把测试理由带偏。
    """
    from database import db
    uri = 'sqlite:///' + str(path).replace(os.sep, '/')
    eng = create_engine(uri, future=True)
    db.metadata.create_all(bind=eng)
    user_t = db.metadata.tables['user']
    with eng.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS alembic_version '
                       '(version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
        c.execute(text('INSERT INTO alembic_version VALUES (:v)'),
                  {'v': '0046_answer_oj_status'})
        for name in users:
            c.execute(user_t.insert().values(username=name, password_hash='x',
                                             role='teacher'))
    eng.dispose()
    return str(path)


def test_mirror_readable_accepts_full_copy(app, tmp_path):
    path = _make_mirror(tmp_path / 'exam_system.db')
    ok, why = cfgmod._mirror_readable('sqlite:///' + path.replace(os.sep, '/'))
    assert ok is True
    assert 'version=0046_answer_oj_status' in why


def test_mirror_readable_rejects_missing_file(tmp_path):
    ok, why = cfgmod._mirror_readable(
        'sqlite:///' + str(tmp_path / 'nope.db').replace(os.sep, '/'))
    assert ok is False and '不存在' in why


def test_mirror_readable_rejects_empty_db(app, tmp_path):
    """只有几张空表的可疑文件必须拒：拿它起服务是「页面能开但处处空白」。"""
    eng = create_engine('sqlite:///' + str(tmp_path / 'thin.db').replace(os.sep, '/'),
                        future=True)
    with eng.begin() as c:
        for i in range(5):
            c.execute(text(f'CREATE TABLE t{i} (id INTEGER PRIMARY KEY)'))
    eng.dispose()
    ok, why = cfgmod._mirror_readable(
        'sqlite:///' + str(tmp_path / 'thin.db').replace(os.sep, '/'))
    assert ok is False and '不是份完整库' in why


def test_mirror_readable_rejects_non_sqlite_uri():
    """误传 PG URI 时 .database 是库名不是路径，必须给一句说得通的话。"""
    ok, why = cfgmod._mirror_readable(FAKE_PG_URL)
    assert ok is False and '不是 SQLite' in why


# ────────────────────────── 三档最终行为 ──────────────────────────

def test_auto_uses_pg_when_probe_ok(env, probe_ok):
    env('auto', FAKE_PG_URL)
    assert cfgmod._resolve_database_uri() == FAKE_PG_URL
    assert not cfgmod._OFFLINE_FALLBACK, '连上 PG 就不该标记离线'


def test_auto_falls_back_when_pg_absent_and_mirror_ready(env, probe_fail, monkeypatch,
                                                         tmp_path, app):
    env('auto', FAKE_PG_URL)
    _no_pg_here(monkeypatch)
    path = _make_mirror(tmp_path / 'exam_system.db')
    monkeypatch.setattr(cfgmod, '_INSTANCE_DIR', str(tmp_path))
    monkeypatch.setattr(cfgmod, '_build_sqlite_uri',
                        lambda p: 'sqlite:///' + p.replace(os.sep, '/'))
    result = cfgmod._resolve_database_uri()
    assert result == 'sqlite:///' + path.replace(os.sep, '/')
    assert cfgmod._OFFLINE_FALLBACK.get('mirror') == '1', '降级必须留下可观测标记'


def test_fallback_does_not_touch_the_mirror_file(env, probe_fail, monkeypatch, tmp_path, app):
    """可用性校验必须只读打开：降级过程中就把镜像改了，交付件不再等于主库副本。"""
    env('auto', FAKE_PG_URL)
    _no_pg_here(monkeypatch)
    path = _make_mirror(tmp_path / 'exam_system.db')
    stamp = lambda p: (os.stat(p).st_size, os.stat(p).st_mtime_ns)   # noqa: E731
    before = stamp(path)
    monkeypatch.setattr(cfgmod, '_INSTANCE_DIR', str(tmp_path))
    monkeypatch.setattr(cfgmod, '_build_sqlite_uri',
                        lambda p: 'sqlite:///' + p.replace(os.sep, '/'))
    cfgmod._resolve_database_uri()
    assert stamp(path) == before
    assert not [p for p in os.listdir(tmp_path) if p.endswith(('-wal', '-shm'))], \
        '不许给镜像文件留下 WAL 侧车（拷一个文件就走全量的前提）'


def test_auto_refuses_when_pg_installed_but_unreachable(env, probe_fail, monkeypatch):
    """本机装了 PG 只是连不上：必须拒起服务，绝不静默写到本地镜像上。"""
    env('auto', FAKE_PG_URL)
    monkeypatch.setattr(cfgmod, '_tcp_open', lambda h, p, timeout=0.6: False)
    monkeypatch.setattr(cfgmod, '_pg_service_names', lambda: ['postgresql-x64-17'])
    with pytest.raises(RuntimeError) as e:
        cfgmod._resolve_database_uri()
    msg = str(e.value)
    assert '不能降级' in msg and 'postgresql-x64-17' in msg
    assert not cfgmod._OFFLINE_FALLBACK


def test_auto_refuses_remote_unreachable(env, probe_fail, monkeypatch):
    env('auto', FAKE_REMOTE_URL)
    _no_pg_here(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        cfgmod._resolve_database_uri()
    assert '不是本机' in str(e.value)


def test_auto_falls_back_only_to_usable_mirror(env, probe_fail, monkeypatch, tmp_path):
    """没装 PG 但镜像也不可用：拒起并指出去有 PG 的机器跑 --resync，而不是起个空站。"""
    env('auto', FAKE_PG_URL)
    _no_pg_here(monkeypatch)
    monkeypatch.setattr(cfgmod, '_INSTANCE_DIR', str(tmp_path))
    monkeypatch.setattr(cfgmod, '_build_sqlite_uri',
                        lambda p: 'sqlite:///' + p.replace(os.sep, '/'))
    with pytest.raises(RuntimeError) as e:
        cfgmod._resolve_database_uri()
    assert '--resync' in str(e.value)


def test_postgres_backend_still_fail_fast(env, probe_fail, monkeypatch):
    """本机正式档语义不变：没 PG 也不降级，用户选的就是 fail-fast。"""
    env('postgres', FAKE_PG_URL)
    _no_pg_here(monkeypatch)
    with pytest.raises(RuntimeError) as e:
        cfgmod._resolve_database_uri()
    assert 'DB_BACKEND=postgres' in str(e.value)
    assert not cfgmod._OFFLINE_FALLBACK


def test_postgres_backend_requires_database_url(env, probe_ok):
    env('postgres', '')
    with pytest.raises(RuntimeError):
        cfgmod._resolve_database_uri()


def test_sqlite_backend_with_pg_url_marks_offline(env, monkeypatch):
    """老师侧「改一行 DB_BACKEND=sqlite」的常规交付形态：可写、需要归并，标记为离线。"""
    env('sqlite', FAKE_PG_URL)
    assert cfgmod._resolve_database_uri().startswith('sqlite:///')
    assert cfgmod._OFFLINE_FALLBACK.get('mirror') == '1'


def test_sqlite_backend_without_pg_url_is_plain_single_machine(env, monkeypatch):
    """从没配过 PG 的单机部署不是「离线副本」，不该抓基线、不该提示归并。"""
    env('sqlite', '')
    cfgmod._resolve_database_uri()
    assert not cfgmod._OFFLINE_FALLBACK
