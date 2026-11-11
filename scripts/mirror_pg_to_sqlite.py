# -*- coding: utf-8 -*-
"""PG 主库 → SQLite 只读镜像的运维入口（v7.4）。

场景：
- 拷项目给老师/教授前，先跑一次 --resync，保证对方拿到的 SQLite 是最新全量；
- 怀疑两库漂移（如镜像期间进程被强杀）时跑 --reconcile 看逐表行数与中间表差异；
- 日常无需手动：app.py 启动会挂实时事件并 bootstrap，调度线程每日对账自愈。

用法：
    python scripts/mirror_pg_to_sqlite.py --status          # 看当前镜像状态
    python scripts/mirror_pg_to_sqlite.py --resync          # 整库重刷（重刷前自动快照旧镜像）
    python scripts/mirror_pg_to_sqlite.py --reconcile       # 逐表行数 + 列结构对账（只报不改）
    python scripts/mirror_pg_to_sqlite.py --fix             # 对账并把差异表重刷成 PG 的样子

前提：.env 的 DB_BACKEND=postgres（或 auto 且 PG 探活成功）。主库为 SQLite 时本脚本
直接退出——那份文件本身就是主库，不存在镜像关系，硬跑只会自我覆盖。

无 ORM 模型的表：镜像清单 = models.py 里的模型 + utils/sqlite_mirror.py 的 EXTRA_TABLES。
只在迁移里 create_table 而不登记、又不写模型的表不会进镜像，--reconcile 会把它们列出来提醒。
"""
import os
import sys
import json
import argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy.engine import make_url   # noqa: E402

import app as _app                       # noqa: E402  导入即注册全部 models 到 db.metadata
from database import db                  # noqa: E402
from utils import sqlite_mirror as m     # noqa: E402


def _echo(msg):
    print(msg, flush=True)


def _echo_unknown(src):
    """把「PG 有但镜像清单里没有」的表说在明处（不提醒就会被当成“已同步”）。"""
    unknown = m.unknown_extra_tables(src)
    if unknown:
        _echo(f'[warn] PG 里有 {len(unknown)} 张表既无 ORM 模型也未登记进 EXTRA_TABLES，'
              f'不会被镜像：{unknown}')
        _echo('       需要交付的话：在 database/models.py 补模型，'
              '或在 utils/sqlite_mirror.py 的 EXTRA_TABLES 里登记表名。')
    return unknown


def _build_parser():
    ap = argparse.ArgumentParser(description='PG → SQLite 镜像同步运维入口')
    ap.add_argument('--status', action='store_true', help='打印镜像状态（默认动作）')
    ap.add_argument('--resync', action='store_true', help='整库重刷：PG 全量覆盖 SQLite 镜像')
    ap.add_argument('--reconcile', action='store_true', help='逐表行数对账')
    ap.add_argument('--fix', action='store_true',
                    help='对账后把差异表整表重刷（等价于 --reconcile --fix）')
    ap.add_argument('--no-backup', action='store_true',
                    help='整库重刷前不快照旧镜像文件（默认会快照 .bak_pre_mirror_*）')
    return ap


def _normalize(args):
    """标记归一：--fix 语义上必然要先知道差异在哪，直接隐含对账。

    否则单敲 --fix 会静默落到下面的“打印状态”分支，操作员以为已经修完
    （实测踩过一次：报 RC=0、镜像文件 mtime 却一动没动）。
    """
    if args.fix:
        args.reconcile = True
    return args


def main(argv=None):
    args = _normalize(_build_parser().parse_args(argv))

    with _app.app.app_context():
        cfg = _app.app.config
        _echo(f'[env] 主库后端={cfg.get("DB_ACTIVE_BACKEND")} '
              f'主库={cfg.get("DB_URL_SAFE")}')
        _echo(f'[env] 镜像目标={m.mirror_uri(cfg)}')
        if not m.mirror_enabled():
            st = m.mirror_status()
            _echo(f'[stop] 镜像未启用（{st.get("reason", "原因未知")}），'
                  f'无需同步；如需启用请把 .env 的 DB_BACKEND 设为 postgres。')
            return 2

        if args.resync:
            per, ver = m.resync_all(db.engine, m.get_mirror_engine(),
                                    backup=not args.no_backup)
            diff = m.reconcile_counts(db.engine, m.get_mirror_engine())
            sec_bad = m.reconcile_secondary(db.engine, m.get_mirror_engine())
            schema_bad = m.reconcile_schema(db.engine, m.get_mirror_engine())
            idx_bad = m.reconcile_indexes(db.engine, m.get_mirror_engine())
            _echo(f'[resync] 已重刷 {len(per)} 张表 / {sum(per.values())} 行，'
                  f'alembic_version={",".join(ver) or "无"}')
            _echo(f'[resync] 对账差异表 {len(diff)} 张 / 中间表主键不一致 {len(sec_bad)} 张'
                  f' / 结构不一致 {len(schema_bad)} 张 / 缺索引 {len(idx_bad)} 张'
                  + (f'：{diff[:10]}' if diff else ''))
            _echo_unknown(db.engine)
            return 0 if not diff and not sec_bad and not schema_bad and not idx_bad else 1

        if args.reconcile:
            diff = m.reconcile_counts(db.engine, m.get_mirror_engine())
            sec_bad = m.reconcile_secondary(db.engine, m.get_mirror_engine())
            schema_bad = m.reconcile_schema(db.engine, m.get_mirror_engine())
            idx_bad = m.reconcile_indexes(db.engine, m.get_mirror_engine())
            unknown = _echo_unknown(db.engine)
            if not diff and not sec_bad and not schema_bad and not idx_bad:
                _echo('[reconcile] 逐表行数、列结构、索引与中间表主键集合均一致，'
                      '镜像与主库同步'
                      + (f'（另有 {len(unknown)} 张清单外表未镜像，见上）' if unknown else ''))
                return 0
            if schema_bad:
                # 单独报这一道：新表/新字段在行数上看不出问题，不报就会误判“已同步”
                _echo(f'[reconcile] {len(schema_bad)} 张表镜像侧缺表或列结构落后于代码：'
                      f'{schema_bad[:20]}')
            if diff:
                _echo(f'[reconcile] {len(diff)} 张表行数不一致（表名 / PG / SQLite）：')
                for name, a, b in diff[:40]:
                    _echo(f'           {name:<44} {str(a):>8} {str(b):>8}')
            if sec_bad:
                _echo(f'[reconcile] {len(sec_bad)} 张中间表主键集合不一致（行数可能相同）：'
                      f'{sec_bad[:20]}')
            if idx_bad:
                # 单独报这一道：索引不在列集里，列对账全绿也可能整张表没索引
                _echo(f'[reconcile] {len(idx_bad)} 张表镜像侧缺索引（不动数据，--fix 只补建）：')
                for name, miss in list(idx_bad.items())[:20]:
                    _echo(f'           {name:<44} {miss}')
            if not args.fix:
                _echo('[reconcile] 未加 --fix，仅报告不修改。')
                return 1
            tables = m._mirror_tables(db.engine)     # ORM 表 + EXTRA_TABLES 登记的额外表
            counted = {name for name, _, _ in diff}
            with m._lock:
                for name in schema_bad:
                    # 缺表/旧结构：resync_table 会先按代码重建镜像侧表再灌数据
                    if name in counted:
                        continue
                    n = m.resync_table(tables[name], db.engine, m.get_mirror_engine())
                    _echo(f'[fix] {name} 结构追平并重刷 {n} 行')
                for name, _, _ in diff:
                    t = tables.get(name)
                    if t is None:
                        _echo(f'[fix] 元数据中无表 {name}，跳过')
                        continue
                    n = m.resync_table(t, db.engine, m.get_mirror_engine())
                    _echo(f'[fix] {name} 重刷 {n} 行')
                for name in sec_bad:
                    t = tables.get(name)
                    if t is None:
                        _echo(f'[fix] 元数据中无中间表 {name}，跳过')
                        continue
                    n = m.resync_table(t, db.engine, m.get_mirror_engine())
                    _echo(f'[fix] 中间表 {name} 重刷 {n} 行')
                m.copy_alembic_version(db.engine, m.get_mirror_engine())
                fixed_idx = m.repair_indexes(db.engine, m.get_mirror_engine(),
                                             tables, bad=idx_bad)
                for name, made in list(fixed_idx.items())[:20]:
                    _echo(f'[fix] {name} 补建索引 {made}')
            left = m.reconcile_counts(db.engine, m.get_mirror_engine())
            left_sec = m.reconcile_secondary(db.engine, m.get_mirror_engine())
            left_sch = m.reconcile_schema(db.engine, m.get_mirror_engine())
            left_idx = m.reconcile_indexes(db.engine, m.get_mirror_engine())
            _echo(f'[fix] 修复后仍不一致 行数{len(left)} 张 / 中间表{len(left_sec)} 张'
                  f' / 结构{len(left_sch)} 张 / 索引{len(left_idx)} 张'
                  + (f'：{left[:10]}' if left else '')
                  + (f'；结构：{left_sch[:10]}' if left_sch else '')
                  + (f'；索引：{list(left_idx.items())[:10]}' if left_idx else ''))
            return 0 if not left and not left_sec and not left_sch and not left_idx else 1

        # 默认：状态
        st = m.mirror_status()
        _echo(json.dumps(st, ensure_ascii=False, indent=1))
        db_path = str(make_url(m.mirror_uri(cfg)).database)
        _echo(f'[hint] 镜像文件绝对路径：{db_path}')
        return 0


if __name__ == '__main__':
    sys.exit(main())
