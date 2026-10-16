# -*- coding: utf-8 -*-
"""数据库定时备份回归门：快照正确性、轮转只删自动备份、每日判重、开关关闭。

全程用 tmp_path 临时库隔离，绝不触碰 instance/exam_system.db。
"""
import os
import sqlite3

from utils import backup as bk


def _make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE t(v INTEGER)')
    con.executemany('INSERT INTO t VALUES (?)', [(i,) for i in range(rows)])
    con.commit()
    con.close()


def test_do_backup_produces_valid_snapshot(tmp_path):
    """在线备份 API 产出的副本应可读且数据一致。"""
    src = str(tmp_path / 'exam_system.db')
    _make_db(src, 5)
    dst = str(tmp_path / 'copy.db')
    bk._do_backup(src, dst)
    con = sqlite3.connect(dst)
    assert con.execute('SELECT COUNT(*) FROM t').fetchone()[0] == 5
    con.close()


def test_prune_keeps_newest_and_spares_manual_backups(tmp_path):
    """轮转保留最新 N 份自动备份，且绝不删除手工 .bak_* 文件。"""
    for i in range(1, 6):  # 5 份自动备份，字典序即时间序
        (tmp_path / f'{bk._AUTO_PREFIX}2026-01-01_00000{i}.db').write_text('x')
    (tmp_path / 'exam_system.db.bak_pre_ledger').write_text('keep')  # 手工备份

    bk._prune(str(tmp_path), keep=2)

    remaining = sorted(os.path.basename(p)
                       for p in (tmp_path).glob(bk._AUTO_GLOB))
    assert remaining == [f'{bk._AUTO_PREFIX}2026-01-01_000004.db',
                         f'{bk._AUTO_PREFIX}2026-01-01_000005.db']
    assert (tmp_path / 'exam_system.db.bak_pre_ledger').exists()


def test_backup_tick_daily_gate(app, tmp_path, monkeypatch):
    """当日已备份则跳过，不重复；首次产出内容正确。"""
    src = str(tmp_path / 'exam_system.db')
    _make_db(src, 3)
    monkeypatch.setattr(bk, '_sqlite_source_path', lambda: src)

    backup_dir = tmp_path / 'backups'
    bk.database_backup_tick()  # app fixture 已处于 app_context 内
    first = list(backup_dir.glob(bk._AUTO_GLOB))
    assert len(first) == 1
    con = sqlite3.connect(str(first[0]))
    assert con.execute('SELECT COUNT(*) FROM t').fetchone()[0] == 3
    con.close()

    bk.database_backup_tick()  # 同日再跑不新增
    assert len(list(backup_dir.glob(bk._AUTO_GLOB))) == 1


def test_backup_tick_skips_when_source_missing(app, tmp_path, monkeypatch):
    """库文件尚不存在（首次启动前）时静默跳过，不建目录。"""
    monkeypatch.setattr(bk, '_sqlite_source_path',
                        lambda: str(tmp_path / 'nonexistent.db'))
    bk.database_backup_tick()
    assert not (tmp_path / 'backups').exists()


def test_backup_tick_disabled(app, tmp_path, monkeypatch):
    """DB_BACKUP_ENABLED=False 时不执行备份。"""
    src = str(tmp_path / 'exam_system.db')
    _make_db(src, 1)
    monkeypatch.setattr(bk, '_sqlite_source_path', lambda: src)
    app.config['DB_BACKUP_ENABLED'] = False

    bk.database_backup_tick()

    assert not list((tmp_path / 'backups').glob(bk._AUTO_GLOB))
