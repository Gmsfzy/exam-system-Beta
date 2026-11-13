# -*- coding: utf-8 -*-
"""测试账号清理：把若干账号名下的数据并到目标账号，然后删掉空号（v7.17）。

场景：本机跑真模型冒烟时会注册一次性账号（如 smoke_lp_1112），历次手动试号
（tt/ss）与自动化残留号（testuser_a8f2）也留在库里。这类号没有 HTTP 删除入口
（`api/auth_routes.py` 只有注册/登录/登出），而旁路 `DELETE FROM "user"` 会绕过
ORM 事件驱动的 PG→SQLite 实时镜像（隐患 #24），拷走的库里会留着一批幽灵账号。
本脚本因此在 app 上下文里走逐对象 ORM 写，删完镜像自然追平。

用法：
    python scripts/purge_users.py --users 4,5,6,21 --to 1            # 只报告，不动数据
    python scripts/purge_users.py --users 4,5,6,21 --to 1 --apply    # 真迁真删

机制（四步，每步都可能中止）：
1. 从 pg_constraint 现查「所有单列外键 → "user".id」，不写死表清单——全库这类外键
   99 条，人工维护必然漏掉新加的表，漏一条轻则删号时 FK 报错、重则被
   ON DELETE CASCADE 把数据整体带走；
2. 逐列把取值命中待删账号的行改成目标账号；所在列参与唯一/PK 约束（含复合，如
   `ledger_account(user_id,currency,scope)`、`_enroll_uc(user_id,path_id)`）的先做
   重名预检，撞了就中止报明细，绝不静默丢行或覆盖余额；
3. 迁移单独提交后再复查「不该再有行指向待删号」，通过才删账号本体。分两次提交是
   有意的：删号若被 FK 拒绝，已提交的只是归属迁移（数据仍在、只是换了主人），
   而同事务里失败会把两边一起回滚、看不出错在哪一步；
4. 全程 `setattr(obj, col, target)` 逐对象赋值，不用 `Query.update()/delete()`——
   bulk 语句不进 after_flush，PG 改了而 SQLite 镜像一行不动，正是 #24 的实机形状。

前提：主库为 PostgreSQL。SQLite 档下那份文件本身就是主库，不存在镜像关系，
本脚本直接退出码 2 拒跑（防有人在离线机上把它当「删账号」工具用）。
"""
import os
import sys
import argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import select, text   # noqa: E402

import app as _app                    # noqa: E402  导入即把全部业务模型注册进 db.metadata
from database import db               # noqa: E402
from database.models import User      # noqa: E402
from utils import sqlite_mirror as m  # noqa: E402


def _echo(msg):
    print(msg, flush=True)


def _in_list(ids):
    """把 id 列表拼成 SQL 字面量。都是 int() 过的数字，不存在注入面；
    之所以不用 `= ANY(:param)` 绑列表——SQLAlchemy 的 text() 参数不带类型，
    传 list 到 psycopg2 前就会被当成「参数个数不对」处理掉。"""
    return ', '.join(str(int(i)) for i in ids)


def _user_fk_columns():
    """现查所有「单列外键 → "user".id」，返回 [(表名, 列名, ON DELETE 规则)]。"""
    sql = text("""
        SELECT cls.relname, att.attname,
               CASE con.confdeltype WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT' WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL' ELSE con.confdeltype END
        FROM pg_constraint con
        JOIN pg_class cls ON cls.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = cls.relnamespace
        JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
        WHERE con.contype = 'f' AND con.confrelid = '"user"'::regclass
          AND ns.nspname = 'public'
        ORDER BY cls.relname, att.attname
    """)
    return [(tbl, col, rule) for tbl, col, rule in db.session.execute(sql)]


def _composite_user_fks():
    """复合外键指向 user 的情形（两列以上）本脚本不猜语义，出现就必须人工确认。"""
    sql = text("""
        SELECT cls.relname, array_length(con.conkey, 1)
        FROM pg_constraint con
        JOIN pg_class cls ON cls.oid = con.conrelid
        JOIN pg_namespace ns ON ns.oid = cls.relnamespace
        WHERE con.contype = 'f' AND con.confrelid = '"user"'::regclass
          AND ns.nspname = 'public' AND array_length(con.conkey, 1) > 1
    """)
    return [(r[0], r[1]) for r in db.session.execute(sql)]


def _model_by_table():
    """表名 → ORM 模型类（走 declarative registry，新增模型自动纳入）。"""
    mapping = {}
    for mapper in db.Model.registry.mappers:
        tbl = mapper.local_table
        if tbl is not None and tbl.name:
            mapping.setdefault(tbl.name, mapper.class_)
    return mapping


def _unique_keys_for(tbl, col):
    """归属列参与的唯一/PK 约束列集合（含复合）——迁移可能撞车的来源。"""
    sql = text("""
        SELECT array_agg(att.attname ORDER BY u.ord)
        FROM pg_constraint con
        CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord)
        JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = u.attnum
        WHERE con.conrelid = CAST(:tbl AS regclass) AND con.contype IN ('u', 'p')
        GROUP BY con.conname
        HAVING CAST(:col AS text) = ANY(array_agg(att.attname))
    """)
    return [list(r[0]) for r in db.session.execute(sql, {'tbl': tbl, 'col': col})]


def _find_conflicts(model, col, keys, doom, target):
    """逐行预检：col 从待删号改成 target 后，是否与已有行在唯一键上重名。"""
    bad = []
    for obj in db.session.scalars(select(model).where(
            model.__table__.c[col].in_(doom))).all():
        stmt = select(model)
        for key in keys:
            value = target if key == col else getattr(obj, key)
            stmt = stmt.where(getattr(model, key) == value)
        stmt = stmt.where(model.__table__.c[col].notin_(doom))
        if db.session.scalars(stmt).first() is not None:
            bad.append({'table': model.__tablename__, 'id': getattr(obj, 'id', None),
                        'keys': {k: getattr(obj, k) for k in keys if k != col}})
    return bad


def _table_counts(doom, label):
    """按外键列统计指向待删账号的行数，兼带 user 表总行数。"""
    out = {}
    for tbl, col, _rule in _user_fk_columns():
        n = db.session.execute(
            text(f'SELECT COUNT(*) FROM "{tbl}" WHERE "{col}" IN ({_in_list(doom)})')
        ).scalar()
        if n:
            out[f'{tbl}.{col}'] = n
    out['user(总行数)'] = db.session.execute(text('SELECT COUNT(*) FROM "user"')).scalar()
    _echo(f'\n[PG] {label}：')
    for key, n in sorted(out.items()):
        _echo(f'  {key:<40} {n}')
    return out


def migrate_ownership(doom, target, apply_changes):
    """把待删账号名下的行改到 target 名下，返回 [(表, 列, 行数)]。"""
    comp = _composite_user_fks()
    if comp:
        raise RuntimeError(f'存在指向 user 的复合外键 {comp}，本脚本不猜语义，请先人工确认')

    models = _model_by_table()
    touched, no_model = [], []
    for tbl, col, rule in _user_fk_columns():
        model = models.get(tbl)
        if model is None:
            # 有 FK 无模型：Core 写不进 after_flush，镜像会漏，宁可拒跑也不半成品
            n = db.session.execute(
                text(f'SELECT COUNT(*) FROM "{tbl}" WHERE "{col}" IN ({_in_list(doom)})')
            ).scalar()
            if n:
                no_model.append((tbl, col, n))
            continue
        rows = db.session.scalars(
            select(model).where(model.__table__.c[col].in_(doom))).all()
        if not rows:
            continue
        if rule == 'CASCADE':
            _echo(f'  [note] {tbl}.{col} 是 ON DELETE CASCADE，不迁就会随账号一起消失，'
                  f'一律先迁住')
        for keys in _unique_keys_for(tbl, col):
            bad = _find_conflicts(model, col, keys, doom, target)
            if bad:
                raise RuntimeError(f'{tbl} 唯一键 {keys}：迁到 user {target} 会与已有行撞车，'
                                   f'已中止（这类表多余额/报名，合并要按业务规则算，'
                                   f'不能机械改归属）：{bad}')
        for obj in rows:
            setattr(obj, col, target)
        touched.append((tbl, col, len(rows)))
        _echo(f'  {"已迁移" if apply_changes else "[dry] 将迁移"} '
              f'{tbl}.{col} {len(rows)} 行 → user {target}')

    if no_model:
        raise RuntimeError(f'这些表有指向 user 的外键但取不到 ORM 模型，走 Core 写会漏实时镜像，'
                           f'已中止：{no_model}（处理法：在 database/models.py 补模型，'
                           f'或改完手动跑 scripts/mirror_pg_to_sqlite.py --fix）')
    return touched


def assert_no_dependents(doom):
    """删账号前的最后一道闸：不该再有行指向待删号。"""
    left = []
    for tbl, col, _rule in _user_fk_columns():
        n = db.session.execute(
            text(f'SELECT COUNT(*) FROM "{tbl}" WHERE "{col}" IN ({_in_list(doom)})')
        ).scalar()
        if n:
            left.append((tbl, col, n))
    if left:
        raise RuntimeError(f'仍有行指向待删账号，删号会被 FK 拒绝：{left}。'
                           f'归属迁移已提交（数据都在、只是换了主人），可按 --dry-run 复查后重跑')


def mirror_side_check(touched_tables):
    """镜像侧同口径行数：PG 改了而这里没变，就说明写没走 ORM。"""
    dst = os.path.join(_ROOT, 'instance', 'exam_system.db')
    if not os.path.exists(dst):
        _echo('\n[mirror] 未见 instance/exam_system.db，跳过镜像核对')
        return
    import sqlite3
    tables = ['user'] + sorted({t for t in touched_tables})
    s = sqlite3.connect(dst)
    try:
        _echo('\n[mirror] SQLite 镜像侧行数（应与 PG 同口径）：')
        for tbl in tables:
            try:
                cnt = s.execute('SELECT COUNT(*) FROM "' + tbl + '"').fetchone()[0]
                _echo(f'  {tbl:<32} {cnt}')
            except sqlite3.Error as e:
                _echo(f'  {tbl:<32} 取数失败：{e}')
        side = [f for f in ('-wal', '-shm') if os.path.exists(dst + f)]
        _echo(f'[mirror] 侧车文件：{side or "无（journal=delete，整目录可直接拷走）"}')
    finally:
        s.close()


def _build_parser():
    ap = argparse.ArgumentParser(description='测试账号数据并转 + 空号删除（默认只预演）')
    ap.add_argument('--users', required=True, help='待删账号 id，逗号分隔，如 4,5,6,21')
    ap.add_argument('--to', type=int, required=True, help='数据并入的目标账号 id')
    ap.add_argument('--apply', action='store_true', help='真正执行（默认 dry-run，事务回滚）')
    return ap


def main(argv=None):
    args = _build_parser().parse_args(argv)
    doom = [int(x) for x in args.users.split(',') if x.strip()]
    target = args.to
    if not doom:
        _echo('[err] --users 为空')
        return 1
    if target in doom:
        _echo('[err] 目标账号不能同时在待删列表里')
        return 1

    with _app.app.app_context():
        from sqlalchemy.engine import make_url
        from config import Config
        if make_url(Config.SQLALCHEMY_DATABASE_URI).get_backend_name() != 'postgresql':
            _echo('[err] 主库不是 PostgreSQL：SQLite 档下这份文件就是主库，'
                  '不存在镜像同步问题，本脚本拒跑')
            return 2

        # 镜像事件必须挂上：不挂则这里写完 PG，SQLite 侧一行都不变
        m.register_events()

        users = sorted(db.session.scalars(
            select(User).where(User.id.in_(doom))).all(), key=lambda u: u.id)
        found = {u.id for u in users}
        if found != set(doom):
            _echo(f'[err] 待删账号里有不存在的 id：{sorted(set(doom) - found)}')
            return 1
        tgt = db.session.get(User, target)
        if tgt is None:
            _echo(f'[err] 目标账号 id={target} 不存在')
            return 1

        _echo(f'[账号] 待删：{[(u.id, u.username, u.role) for u in users]}')
        _echo(f'[账号] 并入：({tgt.id}, {tgt.username}, {tgt.role})')

        _table_counts(doom, '迁移前指向待删账号的行数')
        _echo('\n[归属迁移]')
        try:
            touched = migrate_ownership(doom, target, args.apply)
        except RuntimeError as e:
            db.session.rollback()
            _echo(f'\n[abort] {e}')
            return 1

        if not args.apply:
            db.session.rollback()
            _echo(f'\n[dry-run] 以上均为预演，事务已回滚，库里一行未动；'
                  f'确认无误后加 --apply（{len(touched)} 张表待改归属）')
            mirror_side_check({t for t, _c, _n in touched})
            return 0

        db.session.commit()
        _echo('')
        _table_counts(doom, '迁移后指向待删账号的行数（除 user 行本身外应全为空）')
        try:
            assert_no_dependents(doom)
        except RuntimeError as e:
            _echo(f'\n[abort] {e}')
            return 1

        for u in users:
            _echo(f'  删除账号 id={u.id} username={u.username} role={u.role}')
            db.session.delete(u)
        db.session.commit()

        _echo('\n[PG] 删除后各表总行数：')
        for tbl, col, n in touched:
            total = db.session.execute(text(f'SELECT COUNT(*) FROM "{tbl}"')).scalar()
            _echo(f'  {tbl:<32} {total}  （本轮并入 {col} {n} 行）')
        user_total = db.session.execute(text('SELECT COUNT(*) FROM "user"')).scalar()
        _echo(f'  {"user":<32} {user_total}')
        mirror_side_check({t for t, _c, _n in touched})
        _echo('\n[done] 完成。若镜像与 PG 行数不一致，跑：'
              'python scripts/mirror_pg_to_sqlite.py --fix')
        return 0


if __name__ == '__main__':
    sys.exit(main())
