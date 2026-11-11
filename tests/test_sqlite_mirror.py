# -*- coding: utf-8 -*-
"""v7.4 PG→SQLite 镜像同步单测。

测试不依赖 PG：把「主库」当成待镜像的库（conftest 的内存/临时 SQLite），镜像目标
指向另一个临时文件。验证的是同步机制本身——变更捕获、主键回读覆盖写、中间表补齐、
对账自愈、失败不伤业务——这些与源库方言无关，用 SQLite 冒充 PG 同样成立。
"""
import os
import sqlite3
import threading
import time

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from database import db
from utils import sqlite_mirror as sm


def _tbl(name):
    return db.metadata.tables[name]


def _mirror_count(name):
    t = _tbl(name)
    with sm.get_mirror_engine().connect() as c:
        return c.execute(select(db.func.count()).select_from(t)).scalar()


def _mirror_pks(name):
    t = _tbl(name)
    cols = list(t.primary_key.columns)
    with sm.get_mirror_engine().connect() as c:
        return {tuple(r) for r in c.execute(select(*cols))}


def _src_pks(name):
    t = _tbl(name)
    cols = list(t.primary_key.columns)
    with db.engine.connect() as c:
        return {tuple(r) for r in c.execute(select(*cols))}


@pytest.fixture()
def mirror_env(app, tmp_path):
    """把测试主库伪装成「需要镜像的 PG」：只翻后端标记 + 指定镜像文件。

    结束后复位进程内单例与事件监听，避免污染同会话内其它 ORM 测试（事件挂在
    Session 基类上，是全进程范围，不复位会把别的测试写入也镜像到已删除的临时文件）。
    """
    app.config['DB_ACTIVE_BACKEND'] = 'postgresql'
    app.config['SQLITE_MIRROR_ENABLED'] = True
    app.config['SQLITE_MIRROR_DB'] = str(tmp_path / 'mirror.db')
    sm.reset_state()
    sm.register_events()
    yield app
    sm.reset_state()


@pytest.fixture()
def bootstrapped(mirror_env):
    """镜像文件已按主库现状建好表并铺满存量（等价于服务首启后的状态）。"""
    sm.ensure_bootstrap()
    return mirror_env


def test_disabled_when_primary_is_sqlite(app):
    """主库本身就是 SQLite 时必须整条链路空转，否则自己往自己身上写。"""
    app.config['DB_ACTIVE_BACKEND'] = 'sqlite'
    app.config['SQLITE_MIRROR_DB'] = str(db.engine.url.database or 'x.db')
    assert sm.mirror_enabled() is False


def test_mirror_disabled_by_switch(mirror_env):
    mirror_env.config['SQLITE_MIRROR_ENABLED'] = False
    assert sm.mirror_enabled() is False
    # 关掉的真实主库（非 PG）场景也要能给出原因，供 healthz 区分「没镜像」与「开关关了」
    assert sm.mirror_status()['enabled'] is False


def test_mirror_target_defaults_to_instance_db():
    """默认镜像目标仍是 instance/exam_system.db：他人机器零配置才能读到。"""
    import os
    from config import Config
    assert os.path.normcase(Config.SQLITE_MIRROR_DB).endswith(
        os.path.join('instance', 'exam_system.db'))


def test_bootstrap_copies_existing_rows(bootstrapped):
    from database.models import User
    for i in range(3):
        u = User(username=f'u{i}', role='student')
        u.set_password('pw')
        db.session.add(u)
    db.session.commit()

    sm.resync_all(db.engine, sm.get_mirror_engine(), backup=False)
    assert _mirror_count('user') == 3


def test_realtime_insert_update_delete(bootstrapped):
    from database.models import User
    assert _mirror_count('user') == 0

    u = User(username='live', role='teacher')
    u.set_password('pw')
    db.session.add(u)
    db.session.commit()
    assert _mirror_count('user') == 1, '提交后镜像应立刻出现该行'

    u.username = 'renamed'
    db.session.commit()
    with sm.get_mirror_engine().connect() as c:
        got = c.execute(select(_tbl('user').c.username)).scalars().all()
    assert got == ['renamed'], 'UPDATE 应按主键覆盖镜像行'

    db.session.delete(u)
    db.session.commit()
    assert _mirror_count('user') == 0, 'DELETE 应在镜像中同样消失'


def test_rollback_is_not_mirrored(bootstrapped):
    """flush 后回滚：捕获必须丢弃，绝不能把未提交的数据写进镜像。"""
    from database.models import User
    u = User(username='ghost', role='student')
    u.set_password('pw')
    db.session.add(u)
    db.session.flush()          # 触发 after_flush 捕获
    db.session.rollback()
    assert _mirror_count('user') == 0


def test_secondary_collection_is_synced(bootstrapped):
    """多对多中间表行不出现在 session.new/dirty/deleted，必须靠主键集合比对补齐。"""
    from database.models import Chapter, KnowledgePoint, Question
    ch = Chapter(name='章一', course_id=1)
    kp = KnowledgePoint(name='知识点A', chapter=ch)
    q1 = Question(content='题干1', answer='A', type='single', difficulty='easy', major_id=1)
    q2 = Question(content='题干2', answer='B', type='single', difficulty='easy', major_id=1)
    db.session.add_all([ch, kp, q1, q2])
    db.session.commit()

    kp.questions.append(q1)
    db.session.commit()
    assert _mirror_pks('question_knowledge_point') == _src_pks('question_knowledge_point')
    assert len(_mirror_pks('question_knowledge_point')) == 1

    # 换成另一道题：行数不变、主键集合变了，逐行捕获漏掉它，靠集合比对必须追上
    kp.questions.remove(q1)
    kp.questions.append(q2)
    db.session.commit()
    assert _mirror_pks('question_knowledge_point') == _src_pks('question_knowledge_point')


def test_reconcile_repairs_direct_drift(bootstrapped):
    """绕过实时链路（直接改镜像）造成的漂移，应由每日对账整表重刷修掉。"""
    from database.models import User
    u = User(username='real', role='student')
    u.set_password('pw')
    db.session.add(u)
    db.session.commit()

    t = _tbl('user')
    payload = {'username': 'ghost_in_mirror', 'password_hash': 'x', 'role': 'student'}
    with sm.get_mirror_engine().begin() as d:
        d.execute(t.insert(), payload)
    assert _mirror_count('user') == 2, '镜像被手工多写一行'

    sm._last_reconcile[0] = None
    sm.sqlite_mirror_tick()
    assert _mirror_count('user') == 1, '对账应把多出来的行重刷掉'
    assert not sm._degraded.is_set()


def test_reconcile_reports_missing_table(bootstrapped):
    """镜像缺表时以 None 报出差异（不是按 0 蒙混），调用方据此整表重刷。"""
    with sm.get_mirror_engine().begin() as d:
        d.exec_driver_sql('DROP TABLE IF EXISTS notebook')
    diff = dict((n, (s, t)) for n, s, t in sm.reconcile_counts(db.engine, sm.get_mirror_engine()))
    assert 'notebook' in diff and diff['notebook'][1] is None


def test_mirror_write_failure_does_not_break_business(bootstrapped, monkeypatch):
    """镜像写失败只能记账：业务事务已提交，请求绝不能因此 500。"""
    from database.models import User

    def boom(*a, **kw):
        raise RuntimeError('镜像盘只读')

    monkeypatch.setattr(sm, 'apply_ops', boom)
    u = User(username='ok', role='student')
    u.set_password('pw')
    db.session.add(u)
    db.session.commit()                      # 不应抛
    assert _src_count('user') == 1
    assert sm._degraded.is_set(), '失败需置降级标记等对账修复'


def _src_count(name):
    t = _tbl(name)
    with db.engine.connect() as c:
        return c.execute(select(db.func.count()).select_from(t)).scalar()


def test_mirror_status_reports_file_and_flag(bootstrapped):
    st = sm.mirror_status()
    assert st['enabled'] is True and st['backend'] == 'postgresql'
    assert st['bootstrapped'] is True
    assert st['file'] == 'mirror.db'
    assert st['mtime'], '镜像文件 mtime 是「实时同步真的在写」的关键信号'


def test_apply_ops_survices_source_row_gone(bootstrapped):
    """捕获到的主键在源库已不存在（同轮内插入又删除）时，目标侧也不得留残留行。"""
    from database.models import User
    u = User(username='flash', role='student')
    u.set_password('pw')
    db.session.add(u)
    db.session.commit()
    ops = {'user': {'u': {(u.id,)}, 'd': set()}}
    # 造一个源库已无该主键的 ops：先删源，再按旧主键镜像
    db.session.delete(u)
    db.session.commit()
    written, deleted = sm.apply_ops(ops, db.engine, sm.get_mirror_engine())
    assert _mirror_count('user') == 0
    assert (written, deleted) == (0, 1)


def test_capture_gets_pk_without_attribute_load(mirror_env):
    """回归钉：after_flush 时 SQLAlchemy 2.1 交回的是对象不是 state，直接取
    state.mapper 会永远拿到 None（镜像不报错但一行也不同步）；而主键不能靠
    读对象属性拿（惰取会再触发 autoflush），必须走 identity key / 实例字典。"""
    from sqlalchemy.orm import Session as ORMSession
    from sqlalchemy import inspect as sa_inspect
    from database.models import User

    seen = {}

    def spy(session, ctx):
        objs = list(session.new)
        seen['n'] = len(objs)
        seen['state'] = sm._state_of(objs[0]) if objs else None
        sm._capture(session, ctx)
        seen['ops'] = dict(session.info.get('_mirror_ops') or {})

    from sqlalchemy.event import listen, remove
    listen(ORMSession, 'after_flush', spy)
    try:
        u = User(username='cap', role='student')
        u.set_password('pw')
        db.session.add(u)
        db.session.flush()
    finally:
        remove(ORMSession, 'after_flush', spy)
    assert seen['n'] == 1, 'session.new 应看到一个对象'
    st = seen['state']
    assert st is not None and sa_inspect(u) is st, '_state_of 必须把对象转成 InstanceState'
    assert seen['ops'].get('user', {}).get('u') == {(u.id,)}, '主键必须不靠惰取拿到'


def test_events_are_registered_once(bootstrapped):
    """register_events 幂等，且 reset 后确实摘干净，不叠重复监听。"""
    from sqlalchemy.event import contains
    from sqlalchemy.orm import Session as ORMSession
    sm.register_events()
    sm.register_events()
    assert contains(ORMSession, 'after_commit', sm._on_commit) is True
    sm.reset_state()
    assert contains(ORMSession, 'after_commit', sm._on_commit) is False


# ────────────────── 单文件可拷语义（v7.4 部署口径） ──────────────────

def test_mirror_writes_land_in_main_file_not_wal(bootstrapped):
    """镜像必须做到「拷走一个 .db 就是全部数据」：文件不许持久停在 WAL 模式。

    回归背景：instance/exam_system.db 当过主库，库头持久记着 WAL，镜像写入全进了
    -wal 侧车（主文件 mtime 停在切换时刻、-wal 一直在涨）。老师只拷 .db 就会静默
    读到旧数据——这类数据错最难发现，必须在测试里钉住。
    """
    from database.models import User
    u = User(username='wal_probe', role='student')
    u.set_password('pw')
    db.session.add(u)
    db.session.commit()

    path = str(make_url(sm.mirror_uri(bootstrapped.config)).database)
    assert sm._journal_mode[0] == 'delete', \
        f'镜像库日志模式应为 delete，实际={sm._journal_mode[0]}'
    wal = path + '-wal'
    assert not (os.path.isfile(wal) and os.path.getsize(wal) > 0), \
        '实时镜像写不应在 -wal 里留下未检查点的数据'
    assert 'wal_pending' not in sm.mirror_status()
    # 绕开 ORM 直接读主文件，模拟对方机器拿到单文件后的读法
    raw = sqlite3.connect(path)
    try:
        got = raw.execute('select count(*) from "user" where username=?',
                          ('wal_probe',)).fetchall()
    finally:
        raw.close()
    assert got == [(1,)], '单文件必须自带最新数据'


def test_flush_wal_checkpoints_legacy_file(mirror_env, tmp_path):
    """历史遗留的 WAL 文件：flush_wal 要把侧车内容检查点回主文件并缩到 0。

    故意留一个连接不关：否则会触发 SQLite “最后一条连接关闭时自动检查点”，
    把 -wal 直接删掉，测不到我们主动检查点这条路径。
    """
    p = str(tmp_path / 'legacy_wal.db')
    holder = sqlite3.connect(p)
    try:
        holder.execute('PRAGMA journal_mode=WAL')
        holder.execute('create table t (id integer primary key, v text)')
        holder.execute("insert into t (v) values ('x')")
        holder.commit()
        wal = p + '-wal'
        assert os.path.isfile(wal) and os.path.getsize(wal) > 0, \
            '前置：数据应还停在 WAL 侧车里'
        sm.flush_wal(create_engine('sqlite:///' + p.replace('\\', '/'), future=True))
        assert os.path.getsize(wal) == 0, 'flush_wal 应把侧车检查点回主文件并缩容'
    finally:
        holder.close()


def test_status_reports_wal_pending(mirror_env, tmp_path):
    """监控面必须能看出“数据还压在 -wal 里”：否则运维只看主文件 mtime 会误判同步死了。"""
    with sm.get_mirror_engine().connect() as c:   # 触发 connect 监听，落实 delete 模式
        c.execute(text('select 1'))
    (tmp_path / 'mirror.db-wal').write_bytes(b'0123456789')
    st = sm.mirror_status()
    assert st['journal'] == 'delete'
    assert st['wal_pending'] == 10
    assert 'wal' in st['copy_hint']


def test_cli_fix_implies_reconcile():
    """--fix 单用必须等价于 --reconcile --fix（曾静默落到打印状态分支）。"""
    from scripts.mirror_pg_to_sqlite import _build_parser, _normalize
    assert _normalize(_build_parser().parse_args(['--fix'])).reconcile is True
    assert _normalize(_build_parser().parse_args(['--status'])).reconcile is False


def _dst_columns(name):
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(sm.get_mirror_engine())
    if name not in insp.get_table_names():
        return None
    return {c['name'] for c in insp.get_columns(name)}


def _dst_indexes(name):
    from sqlalchemy import inspect as sa_inspect
    return {i['name'] for i in sa_inspect(sm.get_mirror_engine()).get_indexes(name)}


def _orm_indexes(name):
    return {i.name for i in _tbl(name).indexes if i.name}


def test_realtime_write_creates_missing_table(bootstrapped):
    """未来加了新表：镜像文件里还没有这张表，业务首次写入就该当场建表并落数据。

    不能等一天的对账：老师拿项目的时机可能就在这一天内，缺表会让对方直接报表不存在。
    """
    from database.models import Chapter
    with sm.get_mirror_engine().begin() as d:
        d.exec_driver_sql('DROP TABLE IF EXISTS chapter')
    ch = Chapter(name='新表首写', course_id=1)
    db.session.add(ch)
    db.session.commit()
    assert _dst_columns('chapter') is not None, '缺表应在实时路径上自动建出来'
    assert _mirror_count('chapter') == _src_count('chapter'), '建表后该表存量也要补齐'
    assert not sm._degraded.is_set(), '自动建表成功就不该留下降级标记'


def test_tick_repairs_missing_table(bootstrapped):
    """对账发现「目标缺表」（reconcile_counts 报 None）必须重建该表，不是反复重刷失败。"""
    with sm.get_mirror_engine().begin() as d:
        d.exec_driver_sql('DROP TABLE IF EXISTS notebook')
    sm._last_reconcile[0] = None
    sm.sqlite_mirror_tick()
    assert 'notebook' in sm._table_names(sm.get_mirror_engine()), '对账应把缺的表建出来'
    assert _mirror_count('notebook') == _src_count('notebook')


def test_tick_repairs_stale_schema_after_new_column(bootstrapped):
    """新字段场景：PG 加了列而镜像还是旧结构，行数一致对账抓不到，靠结构比对追上。"""
    with sm.get_mirror_engine().begin() as d:
        d.exec_driver_sql('ALTER TABLE notebook RENAME TO notebook_old')
        d.exec_driver_sql('CREATE TABLE notebook (id INTEGER PRIMARY KEY, title VARCHAR)')
    assert _dst_columns('notebook') == {'id', 'title'}
    sm._last_reconcile[0] = None
    sm.sqlite_mirror_tick()
    assert _dst_columns('notebook') == {c.name for c in _tbl('notebook').columns}, \
        '镜像列集应追平代码（= PG）结构'


def test_ensure_dst_table_detects_missing_and_stale(bootstrapped):
    """结构核对的两面：一致时不动 DDL，缺表/缺列时重建并补齐列。"""
    eng = sm.get_mirror_engine()
    assert sm._ensure_dst_table(_tbl('user'), db.engine, eng) is False, '结构已一致不该重建'
    with sm.get_mirror_engine().begin() as d:
        d.exec_driver_sql('DROP TABLE IF EXISTS "user"')
    assert sm._ensure_dst_table(_tbl('user'), db.engine, eng) is True
    assert _dst_columns('user') == {c.name for c in _tbl('user').columns}
    # 多一列（镜像侧残留旧结构留下的多余列）同样要追平
    with sm.get_mirror_engine().begin() as d:
        d.exec_driver_sql('ALTER TABLE notebook ADD COLUMN ghost_col VARCHAR')
    assert sm._ensure_dst_table(_tbl('notebook'), db.engine, eng) is True
    assert 'ghost_col' not in _dst_columns('notebook')


def test_ensure_dst_table_rebuild_keeps_indexes(bootstrapped):
    """重建必须把索引一起带回来：旧写法 DROP/CREATE 分两个事务发，并发时
    会把表建回来但索引全光（且不报错），拷走的库从此没有索引。"""
    eng = sm.get_mirror_engine()
    assert _dst_indexes('notebook') == _orm_indexes('notebook'), '前置：初始索引齐备'
    with eng.begin() as d:
        d.exec_driver_sql('ALTER TABLE notebook ADD COLUMN ghost_col VARCHAR')
    assert sm._ensure_dst_table(_tbl('notebook'), db.engine, eng) is True
    assert 'ghost_col' not in _dst_columns('notebook')
    assert _dst_indexes('notebook') == _orm_indexes('notebook'), '重建后索引不能丢'


def test_ensure_dst_table_concurrent_rebuild_is_atomic(bootstrapped):
    """并发重建同一张结构落后的表：既不能报 index already exists，
    也不能静默把索引删光（两条都是旧写法的实测坏相）。"""
    eng = sm.get_mirror_engine()
    src = db.engine          # db.engine 需要应用上下文，工作线程拿不到，先取好再开线程
    errs = []
    stop = time.time() + 2.0

    def one():
        while time.time() < stop:
            try:
                with eng.begin() as c:
                    c.exec_driver_sql('ALTER TABLE notebook ADD COLUMN ghost_x TEXT')
            except Exception:
                time.sleep(0.005)
                continue      # 该列已在 = 上一轮重建还没结束，重试
            try:
                sm._ensure_dst_table(_tbl('notebook'), src, eng)
            except Exception as e:
                errs.append(str(e).splitlines()[0][:120])

    ths = [threading.Thread(target=one) for _ in range(4)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    assert not errs, f'并发重建报错：{errs[:3]}'
    assert 'ghost_x' not in _dst_columns('notebook'), '收尾必须是新结构'
    assert _dst_indexes('notebook') == _orm_indexes('notebook'), '收尾索引不能丢'


def test_reconcile_indexes_detects_and_repairs(bootstrapped):
    """列集相同、仅索引缺失：列对账看不见，索引对账要能报出来并只补建不重刷。"""
    eng = sm.get_mirror_engine()
    with eng.begin() as d:
        d.exec_driver_sql('DROP INDEX IF EXISTS ix_notebook_ctx')
    assert _dst_columns('notebook') == {c.name for c in _tbl('notebook').columns}, \
        '列集仍一致——证明列对账拦不住这类漂移'
    assert not sm.reconcile_schema(db.engine, eng), '列对账确实看不见索引'
    bad = sm.reconcile_indexes(db.engine, eng)
    assert 'notebook' in bad and bad['notebook'] == ['ix_notebook_ctx'], bad
    rows_before = _mirror_count('notebook')
    done = sm.repair_indexes(db.engine, eng)
    assert done.get('notebook') == ['ix_notebook_ctx']
    assert _mirror_count('notebook') == rows_before, '补索引不该动数据'
    assert not sm.reconcile_indexes(db.engine, eng), '补完就该收敛'


def test_tick_repairs_missing_index(bootstrapped):
    """每日对账把缺的索引自愈回来（交付前只跑服务不跑 CLI 也要能收敛）。"""
    with sm.get_mirror_engine().begin() as d:
        d.exec_driver_sql('DROP INDEX IF EXISTS ix_notebook_user')
    assert 'notebook' in sm.reconcile_indexes(db.engine, sm.get_mirror_engine())
    sm._last_reconcile[0] = None
    sm.sqlite_mirror_tick()
    assert not sm.reconcile_indexes(db.engine, sm.get_mirror_engine())


# ────────────────── 无 ORM 模型的表（EXTRA_TABLES） ──────────────────

def _make_modelless_table(name='ops_metric', rows=3):
    """在主库里建一张没有 ORM 模型的表：模拟「只写了迁移、没改 models.py」。

    这张表在 db.metadata 里找不到，拿它验证镜像清单之外的表会不会被静默漏掉。
    """
    with db.engine.begin() as c:
        c.execute(text(f'DROP TABLE IF EXISTS {name}'))
        c.execute(text(f'CREATE TABLE {name} (id INTEGER PRIMARY KEY, '
                       f'name TEXT, value INTEGER)'))
        for i in range(rows):
            c.execute(text(f'INSERT INTO {name} (id, name, value) '
                           f'VALUES (:i, :n, :v)'),
                      {'i': i + 1, 'n': f'm{i}', 'v': i * 10})
    return name


def _mirror_rows(name):
    with sm.get_mirror_engine().connect() as c:
        return c.execute(text(f'SELECT id, name, value FROM {name} ORDER BY id')).all()


def test_modelless_table_is_silently_skipped_and_reported(bootstrapped, monkeypatch):
    """没登记的无模型表：不报错、不同步，但必须被 unknown_extra_tables 说在明处。"""
    name = _make_modelless_table()
    monkeypatch.setattr(sm, 'EXTRA_TABLES', ())
    assert name not in db.metadata.tables, '前置条：这张表确实没有 ORM 模型'
    per, _ = sm.resync_all(db.engine, sm.get_mirror_engine(), backup=False)
    assert name not in per, '没登记的表不该被镜像（这是既定口径，不是 bug）'
    assert name not in sm._table_names(sm.get_mirror_engine())
    assert name in sm.unknown_extra_tables(db.engine), '但必须提醒它没进清单'


def test_registered_extra_table_is_mirrored(bootstrapped, monkeypatch):
    """登记进 EXTRA_TABLES 后，整库重刷要把它建出来并灌入全量行。"""
    name = _make_modelless_table(rows=4)
    monkeypatch.setattr(sm, 'EXTRA_TABLES', (name,))
    per, _ = sm.resync_all(db.engine, sm.get_mirror_engine(), backup=False)
    assert per.get(name) == 4, '额外表要进重刷清单并回报行数'
    assert _mirror_rows(name) == [(1, 'm0', 0), (2, 'm1', 10),
                                 (3, 'm2', 20), (4, 'm3', 30)]
    assert name not in sm.unknown_extra_tables(db.engine), '已登记就不该再提醒'
    assert not sm.reconcile_counts(db.engine, sm.get_mirror_engine())
    assert not sm.reconcile_schema(db.engine, sm.get_mirror_engine())


def test_tick_repairs_missing_extra_table(bootstrapped, monkeypatch):
    """额外表在镜像侧被删：每日对账要按反射结构把它重建回来（与 ORM 表同口径）。"""
    name = _make_modelless_table()
    monkeypatch.setattr(sm, 'EXTRA_TABLES', (name,))
    sm.resync_all(db.engine, sm.get_mirror_engine(), backup=False)
    with sm.get_mirror_engine().begin() as d:
        d.exec_driver_sql(f'DROP TABLE IF EXISTS {name}')
    sm._last_reconcile[0] = None
    sm.sqlite_mirror_tick()
    assert name in sm._table_names(sm.get_mirror_engine()), '对账应把缺的额外表建回来'
    assert len(_mirror_rows(name)) == 3


def test_unresolvable_extra_table_does_not_break_resync(bootstrapped, monkeypatch):
    """登记了一个 PG 里并不存在的表名：只告警跳过，不能把正常的整库重刷带崩。"""
    monkeypatch.setattr(sm, 'EXTRA_TABLES', ('ops_metric', 'no_such_extra_table'))
    _make_modelless_table()
    per, _ = sm.resync_all(db.engine, sm.get_mirror_engine(), backup=False)
    assert 'no_such_extra_table' not in per
    assert 'user' in per and 'ops_metric' in per


def test_mirror_tables_skips_reflection_without_source(bootstrapped, monkeypatch):
    """实时写路径不传 src：只给 ORM 清单，不能为了反射多连一条库。"""
    name = _make_modelless_table()
    monkeypatch.setattr(sm, 'EXTRA_TABLES', (name,))
    assert name not in sm._mirror_tables(), 'src=None 时不应去反射'
    assert name in sm._mirror_tables(db.engine)

