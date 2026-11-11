# -*- coding: utf-8 -*-
"""PG 主库 → SQLite 只读镜像的实时同步（v7.4）。

为什么存在：本机以 PostgreSQL 为主库正式运行，但老师/教授自己的电脑上没有 PG，
只能靠项目内的 SQLite 文件读数据。本模块让每一次业务写入在提交成功后，按行同步
落到 instance/exam_system.db，使「拷走项目目录」= 拷走最新数据。

口径与边界（重要）：
- **单向**：PG → SQLite。SQLite 侧是只读镜像，任何人在 SQLite 上的写入都会在下次
  同步中被 PG 的行覆盖掉（这不是双主复制，不做冲突合并）。
- **不重放 SQL**：PG 与 SQLite 方言不同（RETURNING / :: 转型 / ILIKE / JSON 算子…），
  逐语句重放既不可靠也易静默丢写。改为「捕获变更主键 → 回读 PG 真实行 → 按主键
  覆盖写 SQLite」，最终态一致，中间态不保（对镜像而言无意义）。
- **捕获层选 ORM flush**：实测本仓库业务包内 session.execute(update/delete/insert/text)
  与 bulk_* 命中 0 处（仅 migrations/ 与 scripts/ 有），即业务写入 100% 走 ORM flush，
  故 after_flush 足以覆盖；同时以「每日行数对账 + 差异表整表重刷」兜住未来万一出现的
  绕过 ORM 的写法（那种写不会触发本模块，靠对账发现）。
- **失败不影响业务**：镜像写发生在业务事务已提交之后（after_commit），任何异常只记
  日志并置降级标记，交由调度 tick 对账修复；绝不让请求因镜像失败而 500。
- **零 PG 侧 DDL**：不加触发器、不建变更日志表，主库保持干净。
- **结构也追平**：镜像侧缺表、或列集落后于代码（未来加新表/新字段）时，实时写与
  对账两条路径都会先按 ORM 元数据重建该表再灌数据（_ensure_dst_table）。行数对账
  看不见“加了字段但旧行照旧”这种漂移，故每日对账额外跑一道 reconcile_schema。
- **镜像清单来自代码，不来自 PG**：建表/重灌/对账都以 db.metadata（= models.py 里
  的模型）为清单。一张只在 migrations 里 create_table、没有对应模型的表，镜像既不
  知道它存在、也永远不会同步它，而且不报错不告警（老师侧一读就是 no such table）。
  确实要交付这种表时，把表名登记进 EXTRA_TABLES；对账会顺带把「PG 有但清单里没有」
  的未知表列出来提醒（unknown_extra_tables）。
"""
import os
import threading

from sqlalchemy import create_engine, delete, func, inspect as sa_inspect, select, tuple_
from sqlalchemy.engine import make_url
from sqlalchemy.event import listens_for
from sqlalchemy.orm import Session as _ORMSession

from utils.logger import logger
from utils.timeutil import fmt_local, local_today, utcnow

# 不参与镜像的表：alembic_version 由本模块单独按其语义处理（非 ORM 元数据表）
_SKIP_TABLES = {'alembic_version'}

# 只有迁移、没有 ORM 模型的表：手工登记在这里，镜像才会认识它们。
# 适用场景：运维统计表、只读视图底表这类「不打算写业务模型」的表，又需要随项目
# 目录交付给无 PG 的机器。登记后它们走与 ORM 表相同的建表/重灌/对账路径。
# 边界（如实）：这类表没有 ORM 对象，after_flush 捕获不到，所以**不会被实时同步**，
# 只在整库重刷（--resync / bootstrap）与每日对账时整表重灌，最长滞后一天。
EXTRA_TABLES: tuple = (
    # 'audit_log',
)

# 串行化镜像写（请求线程 + 调度线程可能并发提交）。
# 必须是 RLock：ensure_bootstrap/tick 已持锁时还会经 resync_all 再取 get_mirror_engine()
# 的同一把锁，普通 Lock 不可重入会当场死锁（主线程与调度线程都会被卡住）。
_lock = threading.RLock()
_mirror_engine = None             # 目标 SQLite 引擎（进程内单例）
_events_on = False                # 事件监听只注册一次
_bootstrap_done = threading.Event()
_degraded = threading.Event()     # 有镜像写失败 → 等待对账修复
_last_reconcile = [None]          # 已全表对账的本地日期（每日至少一次）
_sec_cache = {}                   # mapper 类名 -> 其名下中间表名集合
_sec_all = None                   # 全库中间表名集合（对账用，按 metadata 缓存）
_reflected = {}                   # 额外表名 -> 从 PG 反射出的 Table（见 EXTRA_TABLES）
_journal_mode = ['']               # 镜像库实际生效的日志模式（状态展示 + 拷库提醒）
_BATCH = 500


# ────────────────────────── 配置与引擎 ──────────────────────────

def _cfg():
    from flask import current_app
    return current_app.config


def mirror_enabled():
    """仅当「主库是 PG + 开关打开 + 镜像目标不是主库自己」时为 True。

    主库是 SQLite 时必须为 False：否则镜像引擎与主引擎指向同一文件，
    等于把自己的写再往自己身上写一遍（自循环 + 锁竞争）。
    """
    try:
        cfg = _cfg()
    except RuntimeError:           # 无应用上下文（脚本直调时由调用方显式传参）
        return False
    if not cfg.get('SQLITE_MIRROR_ENABLED', True):
        return False
    if cfg.get('DB_ACTIVE_BACKEND') != 'postgresql':
        return False
    main = make_url(cfg['SQLALCHEMY_DATABASE_URI'])
    mir = make_url(mirror_uri(cfg))
    return not (mir.get_backend_name() == 'sqlite'
                and os.path.normcase(str(mir.database or '')) ==
                    os.path.normcase(str(main.database or '')))


def mirror_uri(cfg=None):
    """镜像目标 SQLite 文件 URI：默认 instance/exam_system.db（与切库前路径一致，
    使他人机器 DB_BACKEND=auto/sqlite 零配置即可读到）。"""
    cfg = cfg or _cfg()
    p = cfg.get('SQLITE_MIRROR_DB')
    return 'sqlite:///' + os.path.abspath(p).replace('\\', '/')


def get_mirror_engine(cfg=None):
    """镜像目标引擎（单例）。timeout=30 对齐主 SQLite 口径，避开瞬时锁竞争。

    journal_mode=DELETE 是「拷一个文件就能带走全部数据」的前提：本文件此前当过主库，
    库头里持久记着 WAL，新写入会落在 exam_system.db-wal 侧车文件中，主文件 mtime 停在
    切换时刻（实测踩过）——老师只拷 .db 就会静默读到旧数据。镜像只有本进程这一个写入方
    （全程 _lock 串行）、跨进程读发生在对方机器上，不需要 WAL 的并发读，故显式改回
    回滚日志模式，使每次 commit 都直接落进主文件。若切换失败（同机另有连接占着 WAL），
    只记一条警告继续跑，由 flush_wal() 在对账/重刷末尾把 WAL 检查点回主文件兜底。
    """
    global _mirror_engine
    if _mirror_engine is None:
        with _lock:
            if _mirror_engine is None:
                engine = create_engine(
                    mirror_uri(cfg or _cfg()),
                    connect_args={'timeout': 30}, future=True)

                @listens_for(engine, 'connect')
                def _mirror_pragmas(dbapi_conn, _record):
                    cur = dbapi_conn.cursor()
                    try:
                        cur.execute('PRAGMA journal_mode=DELETE')
                        got = cur.fetchone()
                        _journal_mode[0] = (got[0] if got else '') or ''
                        if _journal_mode[0] != 'delete':
                            logger.warning(f'[mirror] 镜像库未能切到 DELETE 日志模式'
                                           f'（当前={_journal_mode[0]}），写入会先进 -wal '
                                           f'侧车文件；拷库前请跑一次 --resync 或 -wal 一起拷')
                        cur.execute('PRAGMA synchronous=NORMAL')
                    except Exception as e:      # PRAGMA 失败不能让连接不可用
                        logger.warning(f'[mirror] 镜像库 PRAGMA 设置失败: {e}')
                    finally:
                        cur.close()

                _mirror_engine = engine
    return _mirror_engine


def flush_wal(dst=None):
    """把 -wal 侧车内容检查点回主文件并回收（非 WAL 模式下为空操作）。

    只在整库重刷/对账修复这类低频路径末尾调用：使拷走的单个 .db 一定是最新的，
    不必带上 -wal/-shm。
    """
    from sqlalchemy import text
    dst = dst or get_mirror_engine()
    try:
        # AUTOCOMMIT：事务包裹里的 PRAGMA 不保证生效，检查点必须直连执行
        with dst.connect().execution_options(isolation_level='AUTOCOMMIT') as c:
            c.execute(text('PRAGMA wal_checkpoint(TRUNCATE)'))
    except Exception as e:
        logger.warning(f'[mirror] WAL 检查点失败（不影响已提交数据）: {e}')


def dispose_mirror_engine():
    """释放镜像引擎（测试/切库/脚本收尾用），下次调用重建。"""
    global _mirror_engine
    with _lock:
        if _mirror_engine is not None:
            _mirror_engine.dispose()
        _mirror_engine = None


# ────────────────────────── 变更捕获（ORM flush） ──────────────────────────

def _state_of(obj):
    """从 session.new/dirty/deleted 的元素拿 InstanceState。

    重要：本仓库的 SQLAlchemy 2.1 里这三个集合产出的是**映射对象本身**（不是
    InstanceState，早期版本是 state），写成直接取 state.mapper 会永远拿到 None，
    导致“事件触发了、但一行也没捕获”这种最阴的错——镜像不报错但永远陈旧。
    因此两种形态都兼容。
    """
    if hasattr(obj, 'mapper') and hasattr(obj, 'key'):
        return obj                      # 旧形态：直接就是 state
    try:
        state = sa_inspect(obj, raiseerr=False)
    except Exception:
        return None
    return state if hasattr(state, 'mapper') else None


def _pk_of_state(state, table):
    """取实例在某表主键列上的值元组；拿不到返回 None。

    两档取法（实测必要）：
    1) state.key：已入 identity map 的对象（persistent）直接拿得到，最便宜；
       但 after_flush 对刚 INSERT 的新对象还拿不到 key——identity key 是在
       flush_context.finalize_flush_changes()（在 after_flush 之后）才登记的。
    2) 退回直读实例字典 state.dict。绝不写 obj.id：描述器取数对已过期/未加载属性
       会触发惰取查询，在 flush 事件里再引发一次 autoflush（实测会递归回
       after_flush）；dict 是属性实际存放处，不发起任何 IO。
    两档都拿不到（属性已过期且不在 dict）时返回 None 不猜，交给每日对账重刷该表。
    多表继承（joined）各表共用同一套主键列，两种取法都适用。
    """
    cols = list(table.primary_key.columns)
    if not cols:
        return None
    key = state.key
    if key is not None:
        pk = tuple(key[1])
        if len(pk) == len(cols) and not any(v is None for v in pk):
            return pk
    mapper = state.mapper
    inst = state.dict
    vals = []
    for c in cols:
        try:
            prop = mapper.get_property_by_column(c)
        except Exception:
            return None
        v = inst.get(prop.key)
        if v is None:
            return None
        vals.append(v)
    return tuple(vals)


def _secondary_tables_of(mapper):
    """该映射类关系用到的中间表（secondary）表名集合，按 mapper 缓存。

    为何需要单独处理：中间表行（如 exam_question / homework_question /
    question_knowledge_point / homework_student）由 ORM 关系集合 append/remove 写入，
    **不出现在 session.new/dirty/deleted 中**，仅靠逐行捕获会整片漏掉，使镜像里的
    考试无题、作业无题——因此对“本轮动过的类”按其中间表做主键集合比对，不一致就整表重刷。
    """
    key = mapper.class_.__name__
    hit = _sec_cache.get(key)
    if hit is None:
        names = set()
        for prop in mapper.relationships:
            sec = getattr(prop, 'secondary', None)
            if sec is not None and sec.name not in _SKIP_TABLES:
                names.add(sec.name)
        hit = _sec_cache[key] = names
    return hit


def _all_secondary_names():
    """全库中间表名集合（daily 对账用）：缓存到进程内，schema 不变则只算一次。"""
    global _sec_all
    if _sec_all is None:
        from database import db
        names = set()
        for mr in db.Model.registry.mappers:
            for prop in mr.relationships:
                sec = getattr(prop, 'secondary', None)
                if sec is not None and sec.name not in _SKIP_TABLES:
                    names.add(sec.name)
        _sec_all = names
    return _sec_all


def _capture(session, flush_context):
    """after_flush：把本轮涉及的 (表 -> {主键集合, 删除集合}) 暂存到 session.info。

    after_flush 时 INSERT 已执行、identity key 已生成，故 new 对象也拿得到主键。
    """
    bucket = None
    for col, kind in ((session.new, 'u'), (session.dirty, 'u'), (session.deleted, 'd')):
        for obj in col:
            state = _state_of(obj)
            if state is None:
                continue
            mapper = getattr(state, 'mapper', None)
            if mapper is None:
                continue
            if bucket is None:
                bucket = session.info.setdefault('_mirror_ops', {})
            for table in mapper.tables:
                if table.name in _SKIP_TABLES:
                    continue
                pk = _pk_of_state(state, table)
                if pk is None:
                    continue
                slot = bucket.setdefault(table.name, {'u': set(), 'd': set()})
                slot[kind].add(pk)
            # 本轮动过的实体→其名下中间表全部列入“需主键集合比对”集合
            bucket.setdefault('__sec', set()).update(_secondary_tables_of(mapper))


def _on_flush(session, flush_context):
    if not mirror_enabled():
        return
    try:
        _capture(session, flush_context)
    except Exception as e:      # 捕获本身绝不影响主事务
        logger.error(f'[mirror] 变更捕获异常（本次提交不镜像）: {e}', exc_info=True)
        session.info.pop('_mirror_ops', None)


def _on_commit(session):
    """after_commit：Session 的该事件只传 session（不传 transaction），签名写错会当场 TypeError。

    整个函数体都在 try 里：镜像处于业务事务已提交之后的路径上，任何异常透传出去
    都会变成用户看到的 500（写已成功、只是镜像没成），那种错配比镜像落后严重得多。
    """
    try:
        ops = session.info.pop('_mirror_ops', None)
        if not ops:
            return
        if not mirror_enabled():
            return
        from database import db
        sec_names = ops.pop('__sec', set())
        src, dst = db.engine, get_mirror_engine()
        # 与调度线程的整表重刷互斥（否则会拿旧行覆盖新行）；重刷量级在秒级，
        # 请求线程在此最多等一个表的重刷时间，不构成长时间阻塞。
        with _lock:
            apply_ops(ops, src, dst)
            if sec_names:
                sync_secondary(sec_names, src, dst)
    except Exception as e:
        # 业务事务已成功提交，这里只能记账：置降级标记，由调度 tick 对账修复。
        # 不去 rollback 业务 session：镜像写用的是自己另开的连接，不会把主事务标成
        # aborted（那是 migrate 脚本踩过的那个 InFailedSqlTransaction 坑），回滚它只会多伤一层。
        _degraded.set()
        logger.error(f'[mirror] 实时镜像写失败（已置待对账标记）: {e}', exc_info=True)


def _on_rollback(session):
    """after_rollback（同样只传 session）：主事务回滚 → 丢弃本轮捕获，绝不镜像未提交的数据。"""
    session.info.pop('_mirror_ops', None)


def register_events():
    """注册 ORM 会话事件（幂等）。监听基类 Session，Flask-SQLAlchemy 的子类同样命中。"""
    global _events_on
    if _events_on:
        return
    _events_on = True
    listens_for(_ORMSession, 'after_flush')(_on_flush)
    listens_for(_ORMSession, 'after_commit')(_on_commit)
    listens_for(_ORMSession, 'after_rollback')(_on_rollback)


def unregister_events():
    """摘掉事件监听（测试隔离用）。

    没有这一步的话 reset_state 只把 _events_on 改回 False，而监听器仍留在 Session 基类
    上，下次 register_events 会叠一份重复监听——单靠幂等标记防不住。
    """
    global _events_on
    from sqlalchemy.event import remove
    for name, fn in (('after_flush', _on_flush), ('after_commit', _on_commit),
                     ('after_rollback', _on_rollback)):
        try:
            remove(_ORMSession, name, fn)
        except Exception:
            pass
    _events_on = False


# ────────────────────────── 按主键回写 ──────────────────────────

def _chunks(seq, n=_BATCH):
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def _pk_predicate(table, values):
    """单列主键用 IN，复合主键用行值 IN（SQLite ≥3.15 / PG 均支持）。

    单列分支必须把 (1,) 里的标量取出来：直接把元组给 IN 会生成参数 ((1,),)，
    sqlite3 报「type 'tuple' is not supported」（ PG 则能过），等于所有实时镜像写全挂。
    """
    cols = list(table.primary_key.columns)
    vals = list(values)
    if len(cols) == 1:
        return cols[0].in_([v[0] for v in vals])
    return tuple_(*cols).in_(vals)


def _tables_by_name():
    from database import db
    return {t.name: t for t in db.metadata.sorted_tables}


def _reflect_extra(name, src):
    """按源库（PG）真实结构反射一张无 ORM 模型的表；失败返回 None 并告警。

    为何反射而不手拼 Table 对象：这类表没有模型可依据，唯一可信的结构来源就是库里
    实际建出来的那张表。反射一次缓存在进程内，跟代码一起重启，不会拿着旧结构不放。
    """
    t = _reflected.get(name)
    if t is not None:
        return t
    from sqlalchemy import MetaData, Table
    try:
        t = Table(name, MetaData(), autoload_with=src, extend_existing=True)
    except Exception as e:
        logger.warning(f'[mirror] 额外表 {name} 反射失败（迁移未执行到该表？表名拼错？）: {e}')
        return None
    if not list(t.primary_key.columns):
        logger.warning(f'[mirror] 额外表 {name} 无主键，只能整表重灌（无法做行级追平）')
    _reflected[name] = t
    return t


def _mirror_tables(src=None):
    """镜像完整清单 = ORM 模型表 + EXTRA_TABLES 登记的无模型表。

    src 为 None 时只给 ORM 清单：实时写路径（apply_ops）不能为了反射去连库，
    而且捕获只可能来自 ORM，多出来的清单在那个路径上用不上。
    """
    tables = _tables_by_name()
    if src is None:
        return tables
    for name in EXTRA_TABLES:
        if name in _SKIP_TABLES or name in tables:
            continue
        t = _reflect_extra(name, src)
        if t is not None:
            tables[name] = t
    return tables


def unknown_extra_tables(src):
    """PG 里存在、但既无 ORM 模型也未登记进 EXTRA_TABLES 的表名。

    这些表不会被镜像（而且不报错），列出来是给运维的提醒：要么补模型，要么登记。
    不拿它们自动去同步：PG 的系统/扩展表、运维临时表会被一并拖进镜像，风险不可控。
    """
    known = _tables_by_name()
    out = []
    for name in sorted(_table_names(src)):
        if name in _SKIP_TABLES or name in EXTRA_TABLES or name in known:
            continue
        if name.startswith(('pg_', 'sqlalchemy_', '_')):
            continue
        out.append(name)
    return out


def apply_ops(ops, src, dst, tables=None):
    """把捕获到的主键集合镜像到目标库：回读源库真实行 → 覆盖写目标行。

    同一轮内既改又删的主键按删除处理（最终态就是没有这行）。
    清单只用 ORM 表：ops 来自 mapper.tables，额外表没有 ORM 事件不会出现在这里，
    在这里多反射一次只是白白多连一条库（本函数跑在业务提交后的请求路径上）。
    """
    tables = tables or _tables_by_name()
    written = 0
    deleted = 0
    # 结构先追平：镜像缺表 / 停在旧结构时当场重建，并把该表改为整表重灌
    # （只按本轮主键覆盖写会把表里其他存量行丢掉）
    rebuilt = set()
    for name in ops:
        t = tables.get(name)
        if t is not None and _ensure_dst_table(t, src, dst):
            rebuilt.add(name)
    with src.connect() as s:                    # 单连接读，尽量贴近一致性快照
        with dst.begin() as d:
            for name, slot in ops.items():
                t = tables.get(name)
                if t is None:
                    continue
                if name in rebuilt:
                    written += _copy_rows(t, s, d)
                    continue
                up = set(slot.get('u') or ()) - set(slot.get('d') or ())
                de = set(slot.get('d') or ())
                for chunk in _chunks(up):
                    rows = s.execute(select(t).where(_pk_predicate(t, chunk))).all()
                    d.execute(delete(t).where(_pk_predicate(t, chunk)))
                    if rows:
                        payload = [{c.key: row._mapping[c.key] for c in t.columns}
                                   for row in rows]
                        d.execute(t.insert(), payload)
                        written += len(payload)
                    deleted += len(chunk) - len(rows)   # 源库已无此行 → 目标也须无
                for chunk in _chunks(de):
                    d.execute(delete(t).where(_pk_predicate(t, chunk)))
                    deleted += len(chunk)
    return written, deleted


def _pk_tuples(conn, table):
    """读出该表主键列上的全量元组集合（中间表比对用，不拉业务大列）。"""
    cols = list(table.primary_key.columns)
    if not cols:
        return None
    return {tuple(row) for row in conn.execute(select(*cols))}


def sync_secondary(names, src, dst, tables=None):
    """比对给定中间表的主键集合，不一致则整表重刷。返回重刷过的表名列表。

    为何不用行数：把考试的题目 A/B 换成 C/D 时行数不变，行数比对会漏修；
    中间表体量小（考试/作业/知识点关联），拉主键集合精确且廉价。
    """
    names = set(names)
    if not names:
        return []
    tables = tables or _tables_by_name()
    redone = []
    with src.connect() as s, dst.connect() as d:
        for name in names:
            t = tables.get(name)
            if t is None:
                continue
            want = _pk_tuples(s, t)
            if want is None:
                continue
            try:
                have = _pk_tuples(d, t)
            except Exception:      # 目标表还不存在
                have = None
            if have != want:
                redone.append(name)
    for name in redone:
        resync_table(tables[name], src, dst)
    return redone


# ────────────────────────── 整表重刷与对账（兜底） ──────────────────────────

def _table_names(engine):
    from sqlalchemy import inspect as sa_inspect
    return set(sa_inspect(engine).get_table_names())


def _cols_of(bind, name):
    """取该库上这张表的列名集合；表不存在返回 None（bind 可为引擎或连接）。"""
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(bind)
    if name not in insp.get_table_names():
        return None
    return {c['name'] for c in insp.get_columns(name)}


def _ensure_dst_table(t, src, dst):
    """核对镜像侧表结构：缺表或列集与代码不一致 → 按 ORM 元数据重建，返回是否重建。

    为什么必须有这一步：三条修复路径（实时 apply_ops、对账 resync_table、CLI --fix）
    原本都只做 delete+insert，而只有 resync_all 里的 create_all 会发 DDL——于是
    「未来迁移加了新表」之后，镜像缺这张表会被反复 delete 撞 `no such table`，
    对账每天失败一次、永不收敛（实测新表 4 例全红），拷给老师的 SQLite 里永远少这张表。

    结构以 ORM 元数据为准：与 resync_all 的 create_all 同一口径（PG 的 DDL 也不能直接
    搬到 SQLite）。顺带比对 PG 真实列，把 models.py 与迁移没对齐的情况说在日志里。

    这里故意不缓存“已核对”结果：曾加过一份进程内 _schema_ok 缓存，bootstrap 会把全
    表登记进去，之后镜像真被删了表也会被缓存骗成“结构没问题”，实时与对账两条
    路径都不再修——恰好是同类静默失效。每表一次 PRAGMA 比对不到 1ms，不值当拿正确性换。
    """
    name = t.name
    want = {c.name for c in t.columns}
    have = _cols_of(dst, name)
    if have == want:
        return False
    try:
        src_cols = _cols_of(src, name)
    except Exception:
        src_cols = None
    if src_cols is not None and want - src_cols:
        logger.warning(f'[mirror] 表 {name} 有列在 PG 里不存在：{sorted(want - src_cols)}，'
                       f'镜像仍按 ORM 结构重建（models.py 与迁移未对齐，请核对）')
    logger.warning(f'[mirror] 镜像侧表 {name} 结构需重建：'
                   f'{"缺表" if have is None else "缺列 " + str(sorted(want - have)) + " / 多列 " + str(sorted(have - want))}')
    # DDL 单开连接：不能在调用方已持有的 dst 写事务里抢锁。
    # 但 DROP 与 CREATE 必须「同一连接、同一事务」做完，不能分两次 bind=engine 发：
    # 旧写法是两条连接、两个事务，实时 apply_ops（不持 _lock）与每日 tick 撞车时有
    # 两种坏相，都在沙箱实测复现过：
    #   ① 甲 drop→create(表+索引) 期间乙也进来，乙的 create 见「表已在」整块跳过，
    #      而乙的 drop 已把甲建好的索引连带删掉 → 表结构对、索引全光、且不报错
    #      （6 线程 × 12 秒压测：36 次重建 0 报错，收尾索引为空）；
    #   ② 甲的 CREATE INDEX 落在乙已建好同名索引之后 → OperationalError:
    #      index ix_notebook_ctx already exists（2026-11-07 error.log 17 次即此，
    #      当时 notebook 每次对账都修不好，拷给老师的库一直停在旧结构）。
    # 一个事务里做完，外部连接看不到中间态；再套 _lock 让同进程串行（RLock，tick
    # 已持锁时重入无害），两个窗口一起堵死。
    with _lock, dst.begin() as conn:
        conn.exec_driver_sql('DROP TABLE IF EXISTS "%s"' % name.replace('"', '""'))
        t.create(bind=conn, checkfirst=False)
    # 重建顺带把索引带回来；建完仍缺就明说，别让它静默变成「镜像少索引」
    still = _orm_index_names(t) - _dst_index_names(dst, name)
    if still:
        logger.warning(f'[mirror] 表 {name} 重建后仍缺索引 {sorted(still)}，'
                       f'将在每日索引对账时补建')
    return True


def _orm_index_names(t):
    """ORM 侧该表应有的索引名。拿不到名字的（未命名表达式索引）不参与比对，避免误判。"""
    return {i.name for i in t.indexes if i.name}


def _dst_index_names(bind, name):
    """镜像侧该表实际有的索引名；表不存在或反射失败返回空集（由列对账那条路处理）。"""
    from sqlalchemy import inspect as sa_inspect
    try:
        return {i['name'] for i in sa_inspect(bind).get_indexes(name)}
    except Exception:
        return set()


def reconcile_indexes(src, dst, tables=None):
    """索引对账：返回 {表名: [镜像缺失的索引名]}。

    为什么列对账不够：索引不在列集里。models.py 后来给某列补 `index=True` 时列集不变，
    `reconcile_schema` 永远看不见——本机实测镜像有 9 张 community_* 表缺 PG 与 ORM
    都有的 ix_*_id 索引，行数列结构两道对账全绿，漂移照旧。
    更要紧的是 `_ensure_dst_table` 的并发窗口会把整张表的索引静默删光（见其注释），
    没有这一道，「镜像少索引」既不报错也永不自愈。

    额外表（EXTRA_TABLES）不比：它们结构靠反射 PG 得到，索引名两边同源，比了没意义。
    """
    tables = tables or _mirror_tables(src)
    bad = {}
    for name, t in tables.items():
        if name in _SKIP_TABLES or name in _reflected:
            continue
        want = _orm_index_names(t)
        if not want:
            continue
        miss = want - _dst_index_names(dst, name)
        if miss:
            bad[name] = sorted(miss)
    return bad


def repair_indexes(src, dst, tables=None, bad=None):
    """只补建缺失索引（CREATE INDEX，不动一行数据），返回 {表名: [已补索引名]}。

    不整表重刷：索引缺失与数据无关，重刷要 delete+insert 全表，既慢又把「拷走的库」
    在无关表上重写一遍，没必要。
    """
    tables = tables or _mirror_tables(src)
    bad = reconcile_indexes(src, dst, tables) if bad is None else bad
    done = {}
    for name, miss in bad.items():
        t = tables.get(name)
        if t is None:
            continue
        want = _orm_index_names(t)
        made = []
        with _lock, dst.begin() as conn:
            for ix in t.indexes:
                if ix.name is None or ix.name not in set(miss) or ix.name not in want:
                    continue
                try:
                    ix.create(bind=conn, checkfirst=True)   # 幂等：已在就跳过
                    made.append(ix.name)
                except Exception as e:
                    logger.error(f'[mirror] 表 {name} 索引 {ix.name} 补建失败: {e}')
        if made:
            done[name] = made
            logger.warning(f'[mirror] 表 {name} 补建缺失索引 {made}：'
                           f'列对账看不见索引，这一步是自愈路径')
    return done


def _copy_rows(t, s, d, batch=_BATCH):
    """在已有连接/事务上整表重灌：目标清空后按源库全量重灌（保留原主键值）。"""
    d.execute(delete(t))
    n = 0
    buf = []
    for row in s.execute(select(t)):
        buf.append({c.key: row._mapping[c.key] for c in t.columns})
        if len(buf) >= batch:
            d.execute(t.insert(), buf)
            n += len(buf)
            buf = []
    if buf:
        d.execute(t.insert(), buf)
        n += len(buf)
    return n


def resync_table(t, src, dst, batch=_BATCH):
    """整表重刷：先保证目标表结构追平代码，再清空重灌。返回行数。"""
    _ensure_dst_table(t, src, dst)
    with src.connect() as s, dst.begin() as d:
        return _copy_rows(t, s, d, batch)


def reconcile_counts(src, dst, tables=None):
    """逐表行数对账，返回 [(表名, 源, 目标)] 差异列表（目标缺表按 None 计）。"""
    tables = tables or _mirror_tables(src)
    have = _table_names(dst)
    diff = []
    with src.connect() as s, dst.connect() as d:
        for name, t in tables.items():
            if name in _SKIP_TABLES:
                continue
            cs = s.execute(select(func.count()).select_from(t)).scalar()
            if name not in have:
                cd = None
            else:
                cd = d.execute(select(func.count()).select_from(t)).scalar()
            if cd is None or cs != cd:
                diff.append((name, cs, cd))
    return diff


def reconcile_schema(src, dst, tables=None):
    """结构对账：返回镜像侧缺表、或列集与代码不一致的表名。

    为何不能只靠行数：加了新字段但旧行照旧时，两侧行数完全相等，行数对账看不见；
    不修的话镜像会永久停在旧结构上，老师侧一读新字段就报 no such column。
    每日一次，走 ORM 元数据比列名，107 张表也就是几十毫秒的量级。
    额外表（EXTRA_TABLES）结构以反射到的 PG 列为准，同样要追平。
    """
    tables = tables or _mirror_tables(src)
    bad = []
    for name, t in tables.items():
        if name in _SKIP_TABLES:
            continue
        if _cols_of(dst, name) != {c.name for c in t.columns}:
            bad.append(name)
    return bad


def reconcile_secondary(src, dst, names=None):
    """中间表全量主键集合对账，返回需重刷的表名列表。

    行数对账抓不到“换人不换数”的中间表漂移（考试换题、作业改交），故单独走这一道。
    """
    names = set(names) if names is not None else set(_all_secondary_names())
    tables = _tables_by_name()
    bad = []
    with src.connect() as s, dst.connect() as d:
        for name in names:
            t = tables.get(name)
            if t is None or name not in _table_names(dst):
                continue
            if _pk_tuples(s, t) != _pk_tuples(d, t):
                bad.append(name)
    return bad


def copy_alembic_version(src, dst):
    """把源库 alembic_version 原样带到镜像库。

    不搬的后果：他人机器 SQLite 里 alembic_version 缺失/落后，启动或 `flask db
    upgrade` 会去重放整条历史链（含大量 PRAGMA/SQLite 专属写法），在一份已是最新
    schema 的镜像库上直接撞「表已存在」。
    """
    from sqlalchemy import text
    with src.connect() as s:
        try:
            ver = s.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
        except Exception:
            return []
    if not ver:
        return []
    with dst.begin() as d:
        d.execute(text('CREATE TABLE IF NOT EXISTS alembic_version ('
                       'version_num VARCHAR(32) NOT NULL, '
                       'CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))'))
        d.execute(text('DELETE FROM alembic_version'))
        for v in ver:
            d.execute(text('INSERT INTO alembic_version (version_num) VALUES (:v)'), {'v': v})
    return list(ver)


def _backup_target(dst_path, keep=3):
    """整库重刷前把现有镜像文件转存 .bak_pre_mirror_<时间戳>，轮转保留最近 keep 份。

    时间戳走 fmt_local（= 运维看文件名的本地日历时刻）：直接 `utcnow().strftime(...)`
    会把快照文件名归到 UTC 日、与上海日界差 8h，且会撞 v5.36 时间契约静态门。
    """
    import glob
    import shutil
    if not os.path.isfile(dst_path):
        return None
    dst_dir = os.path.dirname(dst_path)
    tag = fmt_local(utcnow(), '%Y%m%d_%H%M%S')
    keep = max(int(keep), 1)
    name = os.path.basename(dst_path)
    stem, ext = os.path.splitext(name)
    snap = os.path.join(dst_dir, f'{stem}.bak_pre_mirror_{tag}{ext}')
    shutil.copy2(dst_path, snap)
    olds = sorted(glob.glob(os.path.join(dst_dir, f'{stem}.bak_pre_mirror_*')),
                  key=os.path.basename, reverse=True)
    for stale in olds[keep:]:
        try:
            os.remove(stale)
        except OSError:
            pass
    return snap


def resync_all(src=None, dst=None, backup=True):
    """整库重刷（bootstrap 与对账修复用）：create_all + 逐表全量 + 版本号搬运。

    逐表范围走 _mirror_tables（ORM + EXTRA_TABLES）：create_all 只能建出有模型的表，
    额外表靠 resync_table 里的 _ensure_dst_table 按反射结构建。
    单表异常不阻断整库重刷：额外表结构含 SQLite 不支持的类型（JSONB/数组）时，
    只为这一张表记一条告警，不能把正常的 106 张表也带不进去。
    """
    from database import db
    if src is None:
        from database import db as _db
        src = _db.engine
    if dst is None:
        dst = get_mirror_engine()
    if backup:
        _backup_target(str(make_url(dst.url).database),
                       _cfg().get('SQLITE_MIRROR_BACKUP_KEEP', 3))
    db.metadata.create_all(bind=dst, checkfirst=True)
    total = 0
    per = {}
    skipped = []
    for name, t in _mirror_tables(src).items():
        if name in _SKIP_TABLES:
            continue
        try:
            per[name] = resync_table(t, src, dst)
            total += per[name]
        except Exception as e:
            skipped.append(name)
            logger.error(f'[mirror] 表 {name} 重灌失败（该表本次不进镜像）: {e}',
                         exc_info=True)
    ver = copy_alembic_version(src, dst)
    flush_wal(dst)
    logger.info(f'[mirror] 整库重刷完成：{len(per)} 表 / {total} 行，'
                f'alembic_version={",".join(ver) or "无"}'
                f'{f"，跳过 {skipped}" if skipped else ""}')
    return per, ver


# ────────────────────────── 调度接线 ──────────────────────────

def ensure_bootstrap():
    """进程内一次：镜像文件缺表/缺内容则整库重刷，把存量 PG 数据一次性铺过去。"""
    if _bootstrap_done.is_set():
        return False
    with _lock:
        if _bootstrap_done.is_set():
            return False
        from database import db
        tables = _mirror_tables(db.engine)      # 额外表缺了也算缺，否则永不进镜像
        dst = get_mirror_engine()
        have = _table_names(dst)
        missing = [n for n in tables if n not in have and n not in _SKIP_TABLES]
        empty = False
        if not missing:
            probe = tables.get('user')
            if probe is not None:
                with dst.connect() as c:
                    empty = not c.execute(select(func.count()).select_from(probe)).scalar()
        if missing or empty:
            logger.info(f'[mirror] 镜像库需重建：缺表 {len(missing)} 张'
                        f'{"，且 user 表为空" if not missing and empty else ""} → 整库重刷')
            resync_all(db.engine, dst)
        _bootstrap_done.set()
        return True


def sqlite_mirror_tick():
    """调度任务入口（60s 轮询）：bootstrap 一次 + 每日对账修差异。"""
    if not mirror_enabled():
        return
    # 1. 首启：把 PG 存量铺进 SQLite 镜像
    if not _bootstrap_done.is_set():
        ensure_bootstrap()
        return                      # 本 tick 只做重建，避免与对账抢锁
    cfg = _cfg()
    if not cfg.get('SQLITE_MIRROR_RECONCILE', True):
        return
    # 2. 每日一次结构 + 行数对账；有差异（含实时写失败遗留、新表/新字段）就重刷修掉
    today = local_today()
    if _last_reconcile[0] == today and not _degraded.is_set():
        return
    from database import db
    tables = _mirror_tables(db.engine)
    with _lock:
        try:
            diff = reconcile_counts(db.engine, get_mirror_engine(), tables)
            sec_bad = reconcile_secondary(db.engine, get_mirror_engine())
            schema_bad = reconcile_schema(db.engine, get_mirror_engine(), tables)
            idx_bad = reconcile_indexes(db.engine, get_mirror_engine(), tables)
            unknown = unknown_extra_tables(db.engine)
        except Exception as e:
            logger.error(f'[mirror] 对账失败: {e}', exc_info=True)
            return
        # 镜像清单之外的表说在明处：不提醒的话，这种表“没进镜像”与“进了”从监控
        # 上看不出区别（不报错也不告警，只能等到老师侧读到 no such table 才发现）
        if unknown:
            logger.warning(f'[mirror] PG 里有 {len(unknown)} 张表既无 ORM 模型也未登记进 '
                           f'EXTRA_TABLES，不会被镜像：{unknown[:12]}。'
                           f'需要随项目目录交付的话：补模型或登记进 EXTRA_TABLES')
        _degraded.clear()
        _last_reconcile[0] = today
        if not diff and not sec_bad and not schema_bad and not idx_bad:
            logger.info('[mirror] 对账一致：PG 与 SQLite 镜像逐表行数、列结构、'
                        '索引与中间表主键集合均相同')
            return
        logger.warning(f'[mirror] 对账发现 {len(diff)} 张表行数不一致、'
                       f'{len(schema_bad)} 张表结构不一致（缺表/缺列）、'
                       f'{len(sec_bad)} 张中间表主键集合不一致、'
                       f'{len(idx_bad)} 张表缺索引，逐表重刷修复：'
                       f'{diff[:8]} / {schema_bad[:8]} / {sec_bad[:8]} / {list(idx_bad)[:8]}')
        counted = {n for n, _, _ in diff}
        fixed_schema = set()
        for name in schema_bad:
            # 缺表 / 旧结构靠重刷追平：resync_table 会先把镜像侧表按代码重建
            if name in counted:
                continue        # 已在下面行数差异里，不重刷第二遍
            try:
                resync_table(tables[name], db.engine, get_mirror_engine())
                fixed_schema.add(name)
            except Exception as e:
                logger.error(f'[mirror] 表 {name} 结构重建失败: {e}', exc_info=True)
        for name, _, _ in diff:
            t = tables.get(name)
            if t is None:
                continue
            try:
                resync_table(t, db.engine, get_mirror_engine())
            except Exception as e:
                logger.error(f'[mirror] 表 {name} 重刷失败: {e}', exc_info=True)
        for name in sec_bad:
            if name in counted or name in fixed_schema:
                continue        # 已整表重灌过，不重刷第二遍
            try:
                resync_table(tables[name], db.engine, get_mirror_engine())
            except Exception as e:
                logger.error(f'[mirror] 中间表 {name} 重刷失败: {e}', exc_info=True)
        # 索引单独补：上面重刷过的表已连带把索引建回来，这里只拾重刷没覆盖到的
        # （列集相同、仅索引缺失的那些表，重刷它们只会白白重写整表数据）
        if idx_bad:
            try:
                repair_indexes(db.engine, get_mirror_engine(), tables)
            except Exception as e:
                logger.error(f'[mirror] 索引补建失败: {e}', exc_info=True)
        copy_alembic_version(db.engine, get_mirror_engine())
        flush_wal()


def mirror_status():
    """healthz 用廉价状态（不跑对账，不开源库连接）。

    mtime 是关键信号：主库为 PG 时，镜像文件 mtime 持续追新 = 实时同步真的在写；
    停在旧时刻 = 同步没跑（能一眼区分「切了 PG但镜像挂了」与「镜像正常」）。
    """
    from datetime import datetime, timezone
    try:
        cfg = _cfg()
    except RuntimeError:
        return {'enabled': False, 'reason': '无应用上下文'}
    out = {'enabled': mirror_enabled(), 'backend': cfg.get('DB_ACTIVE_BACKEND')}
    if EXTRA_TABLES:
        # 只在登记了额外表时出现，不为此多开一条库连接（healthz 要廉价）
        out['extra_tables'] = list(EXTRA_TABLES)
    if not out['enabled']:
        # 说清为什么关：否则“没镜像”与“开关关了”在监控面上看不出区别
        out['reason'] = ('主库非 PG' if out['backend'] != 'postgresql'
                         else '开关关闭' if not cfg.get('SQLITE_MIRROR_ENABLED', True)
                         else '镜像目标与主库同文件')
        return out
    path = str(make_url(mirror_uri(cfg)).database)
    out['file'] = os.path.basename(path)
    out['bootstrapped'] = _bootstrap_done.is_set()
    out['degraded'] = _degraded.is_set()
    out['last_reconcile'] = str(_last_reconcile[0]) if _last_reconcile[0] else None
    out['journal'] = _journal_mode[0] or None
    # WAL 未关掉时，真实数据时刻在 -wal 上，只看主文件 mtime 会误判“镜像没在写”，
    # 故取主文件与侧车文件的最新 mtime，并给出带 -wal 的拷贝提醒。
    stat_times = {}
    for suffix in ('', '-wal', '-shm'):
        p = path + suffix
        if os.path.exists(p):
            stat_times[suffix] = os.path.getmtime(p)
    if os.path.isfile(path):
        out['size'] = os.path.getsize(path)
    if stat_times:
        newest = max(stat_times.values())
        # 文件 mtime 是机器秒数：先显式按 UTC 组装 aware 时刻，再走 fmt_local 按固定 +8 展示；
        # 直接 fromtimestamp(秒) 不推 tz 会按系统时区解释，换机器口径就变（v5.36 静态门拦的就是这个）
        out['mtime'] = fmt_local(datetime.fromtimestamp(newest, tz=timezone.utc),
                                  '%Y-%m-%d %H:%M:%S')
        if stat_times.get('-wal') and os.path.isfile(path + '-wal') \
                and os.path.getsize(path + '-wal') > 0:
            out['wal_pending'] = os.path.getsize(path + '-wal')
            out['copy_hint'] = '存在未检查点的 -wal，拷库请连 exam_system.db-wal 一起拷'
    else:
        out['mtime'] = None
    return out


def reset_state():
    """测试/脚本用：清进程内标记，使 ensure_bootstrap/tick 可重复验证。"""
    global _events_on, _last_reconcile, _sec_all
    _bootstrap_done.clear()
    _degraded.clear()
    _last_reconcile = [None]
    _sec_cache.clear()
    _sec_all = None
    _reflected.clear()
    _journal_mode[0] = ''
    dispose_mirror_engine()
    unregister_events()
