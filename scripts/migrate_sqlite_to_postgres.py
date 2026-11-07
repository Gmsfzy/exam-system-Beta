# -*- coding: utf-8 -*-
"""一次性数据搬移：SQLite(instance/exam_system.db) -> PostgreSQL(DATABASE_URL)。

设计（对齐 PostgreSQL 落地计划 §五）：
- 只在"存量 SQLite 库首次切 PG"时本机跑一次，可重跑（重跑前默认 TRUNCATE 目标）。
- 目标 schema 由 db.metadata.create_all() 从 ORM 元数据建表（可移植，绕过含 SQLite 专属
  PRAGMA 的历史迁移链；alembic_version 由外部 `alembic stamp head` 处理，本脚本不碰）。
- 按 db.metadata.sorted_tables 外键拓扑序逐表复制，显式带原主键 id bulk insert（保留原 id）。
- 循环外键/自引用（如 notebook.forked_from_id）：加载期 SET session_replication_role='replica'
  临时关闭 FK 校验（需目标角色为超级用户），全部插完再恢复 'origin'。探不到权限时降级为
  依赖拓扑序（多数表仍可成功）并给出明确提示；权限探测前置在独立事务中完成，
  不会因报错把后续复制事务一并毒化。
- JSONType/UTCDateTime 借 ORM 列的 TypeDecorator 原样往返（读 SQLite 反序列化、写 PG 再序列化），
  naive UTC datetime 不做时区转换。
- SQLite 自增无序列；PG 显式插入 id 后序列落后，必须对每张 serial/identity 主键列
  setval(pg_get_serial_sequence(...), MAX(id))，否则后续插入主键冲突。
- 结束打印每表 src/dst 行数对账（口径包含主动剔除的孤儿行）；任一不一致以非零码退出。
- 外键完整性预检（只读）：SQLite 默认不强制 FK，存量库常残留指向已删父行的子行；
  默认检测到就中止并列出明细，确认后可加 --drop-orphans 在复制时跳过（不改源库）。

用法：
    # 先停后端，冷备份 SQLite；.env 或环境变量设 DATABASE_URL 指向 PG
    python scripts/migrate_sqlite_to_postgres.py                 # 建表+搬数+重置序列+对账
    python scripts/migrate_sqlite_to_postgres.py --no-truncate   # 目标非空且不想清空（一般不用）
"""
import os
import sys
import argparse

# 元数据注册阶段强制走 SQLite 解析，避免 config 探活 PG 干扰本脚本（本脚本自带目标引擎）
os.environ['DB_BACKEND'] = 'sqlite'

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sqlalchemy import create_engine, select, func, text  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy import Integer, BigInteger, SmallInteger  # noqa: E402

import app  # noqa: E402,F401  导入即注册全部 models 到 db.metadata（blueprints -> models）
from database import db  # noqa: E402

_BATCH = 1000


def _source_uri(cli_source):
    if cli_source:
        return 'sqlite:///' + os.path.abspath(cli_source).replace('\\', '/')
    return 'sqlite:///' + os.path.join(
        os.path.abspath(os.path.join(_PROJECT_ROOT, 'instance')),
        'exam_system.db').replace('\\', '/')


def _resolve_tables():
    """返回外键拓扑序表列表；存在循环依赖时回退字母序（依赖 session_replication_role 关校验）。"""
    try:
        return list(db.metadata.sorted_tables)
    except Exception as e:  # CircularDependencyError 等
        print(f'[warn] sorted_tables 检测到循环依赖（{type(e).__name__}），'
              f'回退字母序 + 依赖关闭 FK 校验')
        return sorted(db.metadata.tables.values(), key=lambda t: t.name)


def _reset_sequences(dst, tables):
    """对每张 serial/identity 单列整数主键表，把序列重置到 MAX(id)。"""
    reset = 0
    for t in tables:
        pk = list(t.primary_key.columns)
        if len(pk) != 1:
            continue
        col = pk[0]
        if not isinstance(col.type, (Integer, BigInteger, SmallInteger)):
            continue
        if col.autoincrement is False:
            continue
        seq = dst.execute(
            text('SELECT pg_get_serial_sequence(:t, :c)'),
            {'t': t.name, 'c': col.name},
        ).scalar()
        if not seq:
            continue  # 非序列驱动主键（如手工赋值 user_id），跳过
        mx = dst.execute(select(func.max(col))).scalar()
        if mx is None:
            continue  # 空表：保持序列初始值
        dst.execute(text('SELECT setval(:s, :v, true)'), {'s': seq, 'v': mx})
        reset += 1
    print(f'[seq] 已重置 {reset} 张自增主键表的序列')


def _reconcile(src, dst, tables, src_existing, skips=None):
    """逐表对账 src/dst 行数，返回不一致表列表。

    skips 为本次主动剔除的孤儿行主键集合，对账口径为 src_cnt - 剔除数 == dst_cnt。
    """
    skips = skips or {}
    rows = []
    mismatch = []
    for t in tables:
        dst_cnt = dst.execute(
            select(func.count()).select_from(t)).scalar()
        if t.name in src_existing:
            src_cnt = src.execute(
                select(func.count()).select_from(t)).scalar()
            expect = src_cnt - len(skips.get(t.name, ()))
        else:
            src_cnt = 'N/A(源无此表)'
            expect = src_cnt
        rows.append((t.name, src_cnt, dst_cnt, len(skips.get(t.name, ())) or ''))
        if isinstance(src_cnt, int) and expect != dst_cnt:
            mismatch.append((t.name, expect, dst_cnt))

    name_w = max([len(n) for n, _, _, _ in rows] + [6])
    head_w = name_w + 38
    print('\n' + '=' * head_w)
    print(f'{"TABLE".ljust(name_w)} {"SRC".rjust(10)} {"DST".rjust(12)} {"剔除".rjust(8)}')
    print('-' * head_w)
    for n, s, d, k in rows:
        print(f'{n.ljust(name_w)} {str(s).rjust(10)} {str(d).rjust(12)} {str(k).rjust(8)}')
    print('=' * head_w)
    return mismatch


def _can_disable_fk(dst):
    """探测目标角色能否关闭 FK 校验（需超级用户），在独立事务中试探并回滚。

    不能时返回 False，由调用方降级为仅依赖外键拓扑序复制（元数据无环则等价安全）。
    """
    try:
        with dst.begin():
            pass                      # 先开一条干净事务确认连通
        with dst.begin() as c:
            c.execute(text("SET session_replication_role = 'replica'"))
            c.execute(text("SET session_replication_role = 'origin'"))
        return True
    except Exception as e:
        print(f'[warn] 关闭 FK 校验不可用（目标角色需超级用户）：{type(e).__name__}，'
              f'本次仅依赖拓扑序复制。')
        return False


def _pk_cols(t):
    """主键列列表（单列/复合均可）；无主键返回 None。"""
    return list(t.primary_key.columns) or None


def _collect_orphans(src, tables, existing):
    """只扫描不修改：找出源库中违反 ORM 外键定义的子表行（逐轮迭代至不动点）。

    背景：SQLite 默认不开 PRAGMA foreign_keys，父行（如题目）被删后子行
    （作答/试卷构题/错题本）静默残留；PG 强制校验，原样复制会抱 ForeignKeyViolation。
    级联：剔除某父行后，引用它的子行成为新一批孤儿，故需多轮迭代收敛。

    返回：(skips {表名: set(主键元组)}, report [(子表.列 -> 父表.列, 行数)], no_pk [表名])
    """
    by_name = {t.name: t for t in tables if t.name in existing}
    parent_keys = {}
    for name, t in by_name.items():
        pk = _pk_cols(t)
        if not pk:
            continue
        with src.connect() as c:
            parent_keys[name] = {tuple(r) for r in c.execute(select(*pk))}

    no_pk = [t.name for t in tables
             if t.name in existing and not _pk_cols(t) and list(t.foreign_keys)]

    skips = {}
    hits = {}
    for _round in range(20):
        changed = False
        for t in tables:
            if t.name not in existing:
                continue
            cpk = _pk_cols(t)
            if not cpk:
                continue
            for fk in t.foreign_keys:
                ref = fk.column
                pname = ref.table.name
                if pname not in parent_keys or len(_pk_cols(by_name[pname]) or []) != 1:
                    continue          # 父表无主键/复合主键引用不在本工具处理范围
                col = fk.parent
                valid = parent_keys[pname]
                label = f'{t.name}.{col.name} -> {pname}.{ref.name}'
                with src.connect() as c:
                    rows = c.execute(select(*cpk, col)).fetchall()
                for row in rows:
                    val = row[len(cpk)]
                    if val is None:
                        continue      # 可空外键未填不算违反
                    pkv = tuple(row[:len(cpk)])
                    if (val,) in valid:
                        continue
                    s = skips.setdefault(t.name, set())
                    if pkv in s:
                        continue      # 本轮前已判定为孤儿
                    s.add(pkv)
                    hits[label] = hits.get(label, 0) + 1
                    changed = True
        if not changed:
            break
        # 把已剔除的父行从索引里去掉，使下一轮能发现“因父行被剔而新产生的孤儿”
        for name, s in skips.items():
            if name in parent_keys:
                parent_keys[name] -= s
    else:
        print('[warn] 孤儿扫描未在 20 轮内收敛，结果可能不完整')

    report = sorted(hits.items(), key=lambda kv: -kv[1])
    return skips, report, no_pk


def main():
    ap = argparse.ArgumentParser(description='SQLite -> PostgreSQL 数据搬移')
    ap.add_argument('--source', default='',
                    help='源 SQLite 文件路径（默认 instance/exam_system.db）')
    ap.add_argument('--no-truncate', action='store_true',
                    help='不清空目标表（默认搬前 TRUNCATE ... RESTART IDENTITY CASCADE）')
    ap.add_argument('--drop-orphans', action='store_true',
                    help='复制时剔除违反外键的孤儿行（仅不插进目标库，不改动源库）；'
                         '不加此选项时检测到孤儿行会直接中止，避免 PG 端 ForeignKeyViolation')
    args = ap.parse_args()

    target_url = os.getenv('DATABASE_URL', '').strip()
    if not target_url:
        print('[error] 未设置 DATABASE_URL（目标 PostgreSQL 连接串），无法迁移')
        return 2
    if make_url(target_url).get_backend_name() != 'postgresql':
        print(f'[error] DATABASE_URL 不是 PostgreSQL：{target_url}')
        return 2

    src_uri = _source_uri(args.source)
    if not os.path.isfile(src_uri.replace('sqlite:///', '')):
        print(f'[error] 源 SQLite 文件不存在：{src_uri}')
        return 2

    src = create_engine(src_uri)
    dst = create_engine(target_url, pool_pre_ping=True)

    tables = _resolve_tables()
    src_existing = set(sa_inspect(src).get_table_names())

    # 0. 外键完整性预检（只读）：PG 强制校验，孤儿行先告知、后由选项决定处理方式
    skips, orphan_report, no_pk = _collect_orphans(src, tables, src_existing)
    if no_pk:
        print(f'[error] 以下带外键的表无主键，无法定位/剔除孤儿行：{no_pk}')
        return 2
    dropped_total = sum(len(v) for v in skips.values())
    if orphan_report:
        print('\n[preflight] 源库存在违反外键的孤儿行（SQLite 默认不强制 FK所致）：')
        for label, n in orphan_report:
            print(f'          {label:<56} {n} 行')
        print(f'          合计待剔除 {dropped_total} 行')
        if not args.drop_orphans:
            print('\n[FAIL] 未指定 --drop-orphans，中止。可选：')
            print('       a) 先人工修正源库引用（补建缺失父行或删干净子行）再重跑；')
            print('       b) 确认这些历史残留可丢弃，则加 --drop-orphans（不插进 PG，源库不动）。')
            return 2
        print('[preflight] --drop-orphans 已开启：复制时跳过这些行，源库保持不变。')

    # 1. 目标建空 schema（幂等，checkfirst）
    print('[schema] create_all（幂等，跳过已存在表）...')
    db.metadata.create_all(bind=dst, checkfirst=True)

    # 2. TRUNCATE 目标（默认，保证可重跑；RESTART IDENTITY 复位序列）
    if not args.no_truncate:
        print('[truncate] 清空目标表...')
        with dst.begin() as c:
            names = ', '.join(f'"{t.name}"' for t in tables)
            c.execute(text(f'TRUNCATE TABLE {names} RESTART IDENTITY CASCADE'))

    # 3. 搬数据（单事务：关 FK 校验 -> 逐表插 -> 开 FK 校验 -> 重置序列）
    #    权限探测前置在独立事务里做：非超级用户时该 SET 会报错，若放在复制
    #    事务内，PG 会把整条事务标为 aborted（InFailedSqlTransaction），后续插入
    #    全部堆错——降级分叉因此形同虚设（探测失败则回滚干净，不污染复制事务）。
    fk_off = _can_disable_fk(dst)
    total = 0
    with dst.begin() as dc:
        if fk_off:
            dc.execute(text("SET session_replication_role = 'replica'"))

        src_conn = src.connect()
        try:
            for t in tables:
                if t.name not in src_existing:
                    print(f'[skip] 源库无表 {t.name}')
                    continue
                result = src_conn.execute(select(t))
                cols = list(t.columns)
                drop_set = skips.get(t.name)
                pk_keys = [c.key for c in (t.primary_key.columns or [])]
                batch = []
                for row in result:
                    d = {c.key: row._mapping[c.key] for c in cols}
                    if drop_set and tuple(d[k] for k in pk_keys) in drop_set:
                        continue          # 预检判定的孤儿行：不入库（源库保持不动）
                    batch.append(d)
                    if len(batch) >= _BATCH:
                        dc.execute(t.insert(), batch)
                        total += len(batch)
                        batch = []
                if batch:
                    dc.execute(t.insert(), batch)
                    total += len(batch)
                if drop_set:
                    print(f'[copy] {t.name}（剔除孤儿 {len(drop_set)} 行）')
                else:
                    print(f'[copy] {t.name}')
        finally:
            src_conn.close()

        if fk_off:
            dc.execute(text("SET session_replication_role = 'origin'"))

        # 4. 重置序列（同一事务内，TRUNCATE RESTART 已复位，这里再对齐 MAX(id)）
        _reset_sequences(dc, tables)

    print(f'\n[done] 共插入 {total} 行' +
          (f'，另剔除孤儿行 {dropped_total} 行' if dropped_total else ''))

    # 5. 对账
    with src.connect() as s, dst.connect() as d:
        mismatch = _reconcile(s, d, tables, src_existing, skips)

    if mismatch:
        print(f'\n[FAIL] {len(mismatch)} 张表行数不一致：'
              f'{[m[0] for m in mismatch]}')
        print('       请修复后 TRUNCATE 目标重跑（默认即清库）。')
        return 1
    print('\n[OK] 所有表行数对账一致（含已剔除的孤儿行口径）。下一步：alembic stamp head 标记 PG 库版本。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
