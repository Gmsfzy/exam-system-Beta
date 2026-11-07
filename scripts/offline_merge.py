# -*- coding: utf-8 -*-
"""离线机器变更归并的运维入口（v7.5）。

场景：老师/教授在没有 PG 的电脑上跑本项目（视情降级到项目内 SQLite），写的东西落在
本地库里。回本机（或在装有 PG 的机器上处理拷回来的目录）时，用本脚本把那段变更
算成补丁并合并进 PostgreSQL。

两条常用路径：
    # A. 在离线机上只打补丁（不连 PG 也能跑），把 patch_*.json 拷回来即可
    python scripts/offline_merge.py --export
    python scripts/offline_merge.py --summary instance/offline/patch_xxx.json

    # B. 在本机对拷回来的整个目录直接算 + 看 + 合并（默认路径就是本机 instance/）
    python scripts/offline_merge.py --export --offline-db D:/incoming/exam_system.db \
                                    --baseline D:/incoming/instance/offline/baseline.db
    python scripts/offline_merge.py --apply  D:/incoming/patch_xxx.json --dry-run
    python scripts/offline_merge.py --apply  D:/incoming/patch_xxx.json

--apply 默认保留 PG 侧（冲突只报告不覆盖），合并完会自动重刷 SQLite 镜像：
导入走的是 Core 语句、不经过 ORM，不刷镜像的话 PG 已经变了而镜像要等下一次每日对账
才追平（与隐患 #24 同源，别在这里再踩一次）。

退出码：0 干净 / 1 有冲突需人工定夺 / 2 前置条件不满足 / 3 遇冲突中止（已整体回滚）
"""
import os
import sys
import argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import app as _app                                  # noqa: E402  导入即注册全部 models
from database import db                             # noqa: E402
from utils import offline_patch as op               # noqa: E402
from utils.timeutil import fmt_local, utcnow        # noqa: E402


def _echo(msg):
    print(msg, flush=True)


def _build_parser():
    ap = argparse.ArgumentParser(description='离线 SQLite 变更 → PostgreSQL 归并入口')
    ap.add_argument('--export', action='store_true',
                    help='按「基线 → 离线库」算差异，写出补丁 JSON（不连 PG 也能跑）')
    ap.add_argument('--summary', metavar='PATCH.json', help='打印补丁摘要（只读）')
    ap.add_argument('--apply', metavar='PATCH.json',
                    help='把补丁合并进当前主库（必须是 PostgreSQL）')
    ap.add_argument('--capture-baseline', action='store_true',
                    help='手工为当前库抓基线（已存在则不动，除非 --rotate-baseline）')
    ap.add_argument('--rotate-baseline', action='store_true',
                    help='归档现有基线后重抓（确认上一周期已合并完再用）')
    ap.add_argument('--offline-db', metavar='PATH',
                    help='离线库文件路径（默认当前生效的 SQLite 主库）')
    ap.add_argument('--baseline', metavar='PATH', help='基线快照路径（默认 OFFLINE_PATCH_DIR/baseline.db）')
    ap.add_argument('--out', metavar='PATH', help='补丁输出路径（默认 OFFLINE_PATCH_DIR/patch_<时间戳>.json）')
    ap.add_argument('--on-conflict', choices=op.CONFLICT_STRATEGIES, default='pg',
                    help='冲突取舍：pg=保留主库（默认）/ offline=以离线为准 / abort=整体中止回滚')
    ap.add_argument('--dry-run', action='store_true',
                    help='--apply 的预演：真跑一遍判定再整体回滚，库里不留痕迹')
    ap.add_argument('--reset-baseline', action='store_true',
                    help='--apply 成功后重置基线（下次离线启动以已合并状态重抓）')
    ap.add_argument('--no-refresh-mirror', action='store_true',
                    help='--apply 成功后不重刷 SQLite 镜像（不建议）')
    return ap


def _paths(cfg, args):
    """路径归一：默认都落在项目内，拷来拷去不用带参数。"""
    patch_dir = cfg['OFFLINE_PATCH_DIR']
    offline_db = args.offline_db or str(db.engine.url.database)
    baseline = args.baseline or op.baseline_path(patch_dir)
    return patch_dir, offline_db, baseline


def _do_export(cfg, args):
    patch_dir, offline_db, baseline = _paths(cfg, args)
    for label, path in (('基线', baseline), ('离线库', offline_db)):
        if not os.path.isfile(path):
            _echo(f'[stop] {label}不存在：{path}')
            if label == '基线':
                _echo('       离线机第一次启动会自动抓基线；也可先跑 --capture-baseline。')
            return 2
    patch = op.build_patch(baseline, offline_db)
    out = args.out or os.path.join(
        patch_dir, 'patch_%s.json' % fmt_local(utcnow(), '%Y%m%d_%H%M%S'))
    op.write_patch(patch, out)
    _echo(op.summarize(patch))
    _echo(f'[export] 补丁已写出：{out}')
    if not patch['tables']:
        _echo('[export] 离线期间没有任何数据变化（基线与离线库一致）。')
    if patch['skipped_tables']:
        _echo(f'[export] {len(patch["skipped_tables"])} 张无主键表未参与比对，'
              f'如确有需要请手工处理：{patch["skipped_tables"]}')
    return 0


def _do_summary(args):
    patch = op.read_patch(args.summary)
    _echo(op.summarize(patch))
    return 0


def _do_apply(cfg, args):
    if cfg.get('DB_ACTIVE_BACKEND') != 'postgresql':
        _echo(f'[stop] 当前主库后端={cfg.get("DB_ACTIVE_BACKEND")}，'
              f'归并必须在装有 PostgreSQL 的机器上跑（DB_BACKEND=postgres/auto）。')
        return 2
    patch = op.read_patch(args.apply)
    _echo(op.summarize(patch))
    base_target = args.baseline or op.baseline_path(cfg['OFFLINE_PATCH_DIR'])
    stale, why = op.baseline_is_stale(patch, base_target)
    if stale:
        # 上一轮合并完没重置基线的话，已归并进主库的行会被重新算成「新增」；
        # 默认策略只会跳过（安全），但 --on-conflict offline 是整行覆盖，会抹掉主库修改
        _echo(f'[warn] {why}。若本轮已经合并过，请先 --reset-baseline 再导下一份；'
              + ('尤其当前策略是 offline，它会把主库独有的列一起顶掉。'
                 if args.on_conflict == 'offline' else '当前策略 pg 不会改动已存在的行。'))
    _echo(f'[apply] 目标={cfg.get("DB_URL_SAFE")} 冲突策略={args.on_conflict} '
          f'预演={"是" if args.dry_run else "否"}')
    report = op.apply_patch(patch, db.engine, on_conflict=args.on_conflict,
                            dry_run=args.dry_run)
    if report['aborted']:
        _echo('[abort] 遇冲突已整体回滚，主库未改动。逐条冲突见下：')
        for item in report['conflicts'][:10]:
            _echo(f'        {item["table"]} {item["op"]} pk={item["pk"]}')
        return 3
    a, s = report['applied'], report['skipped']
    _echo(f"[apply] 生效：新增 {a['inserted']} / 修改 {a['updated']} / 删除 {a['deleted']}"
          f'；跳过（已一致或保留主库）：{s["inserted"] + s["updated"] + s["deleted"]}')
    patch_dir = cfg['OFFLINE_PATCH_DIR']
    if report['conflicts']:
        path = op.write_conflicts(report, patch_dir)
        _echo(f'[conflict] {len(report["conflicts"])} 行两边都动过，'
              f'已按策略「{args.on_conflict}」处置，明细：{path}')
        for item in report['conflicts'][:5]:
            if item.get('columns'):
                _echo(f'          {item["table"]} {item["op"]} pk={item["pk"]} '
                      f'撞车列：{item["columns"]}')
            if item.get('note'):
                _echo(f'          {item["table"]} {item["op"]} pk={item["pk"]} '
                      f'{item["note"]}')
    if args.dry_run:
        _echo('[apply] 预演结束，已整体回滚，主库未改动。')
        return 1 if report['conflicts'] else 0
    if not args.no_refresh_mirror:
        # 导入走 Core，不触发 ORM 事件 → 镜像不会自动追平，这里主动重刷一次
        from utils import sqlite_mirror as sm
        per, ver = sm.resync_all(db.engine, sm.get_mirror_engine())
        _echo(f'[mirror] 已重刷 SQLite 镜像：{len(per)} 表 / {sum(per.values())} 行，'
              f'version={",".join(ver) or "无"}')
    if args.reset_baseline:
        # 重置的是本补丁所用的那份基线（--baseline 可以指到拷回来的目录里）
        archived = op.remove_baseline(base_target)
        _echo(f'[baseline] 已重置基线（上一周期归档为 {os.path.basename(archived)}）'
              if archived else f'[baseline] 无基线文件可重置：{base_target}')
    elif os.path.isfile(base_target) and not stale:
        _echo('[hint] 确认本补丁已完全合并后，建议加 --reset-baseline 重置基线，'
              '否则下一轮导出会把已归并的行重当成「新增」发回来。')
    return 1 if report['conflicts'] else 0


def _do_capture(cfg, args):
    patch_dir, offline_db, baseline = _paths(cfg, args)
    if args.rotate_baseline and os.path.isfile(baseline):
        archived = op.remove_baseline(patch_dir)
        _echo(f'[baseline] 旧基线归档为 {os.path.basename(archived)}')
    dst, created = op.capture_baseline(offline_db, patch_dir)
    _echo(f'[baseline] {"已新建" if created else "已存在，未改动"}：{dst}')
    if not created:
        _echo('          基线只在离线周期开始时抓一次；要重抓请加 --rotate-baseline。')
    return 0


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if not (args.export or args.summary or args.apply or args.capture_baseline):
        _build_parser().print_help()
        _echo('\n[stop] 未指定动作。')
        return 2
    with _app.app.app_context():
        cfg = _app.app.config
        _echo(f'[env] DB_BACKEND={cfg.get("DB_BACKEND")} '
              f'生效={cfg.get("DB_ACTIVE_BACKEND")} 主库={cfg.get("DB_URL_SAFE")}')
        if cfg.get('DB_OFFLINE_MODE'):
            _echo(f'[env] 离线交付模式：{cfg.get("DB_OFFLINE_REASON")}')
        if args.export:
            return _do_export(cfg, args)
        if args.summary:
            return _do_summary(args)
        if args.apply:
            return _do_apply(cfg, args)
        return _do_capture(cfg, args)


if __name__ == '__main__':
    sys.exit(main())
