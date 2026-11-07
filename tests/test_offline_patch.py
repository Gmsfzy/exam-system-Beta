# -*- coding: utf-8 -*-
"""v7.5 离线变更补丁（基线 → 离线库 → 主库三方归并）单测。

target 也用 SQLite 文件，且引擎开着 foreign_keys，这样合并顺序、约束冲突这些
在 PG 上才会暴露的问题，在本地测试里同样能暴露出来。真正与方言相关的只有
值的返回形态，那部分交给 _norm 的归一用例单独覆盖。
"""
import json
import os
import shutil
import time
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import (Boolean, Column, DateTime, Float, Integer, LargeBinary,
                        MetaData, Numeric, Table, create_engine, select, text)

import database.models            # noqa: F401  先把模型全量注册进 metadata
from database import db
from utils import offline_patch as op

# 直接取引用：上一行已保证 metadata 写满，不依赖任何 fixture 执行顺序
T = db.metadata.tables


def _new_engine(path):
    return create_engine('sqlite:///' + str(path).replace(os.sep, '/'), future=True)


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    """一份「有结构、有 3 行存量数据」的种子库，作为三个角色的共同起点。"""
    d = tmp_path_factory.mktemp('offl_seed')
    path = os.path.join(str(d), 'seed.db')
    eng = _new_engine(path)
    db.metadata.create_all(bind=eng)
    with eng.begin() as c:
        c.execute(text('CREATE TABLE IF NOT EXISTS alembic_version '
                       '(version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
        c.execute(text("INSERT INTO alembic_version VALUES ('0046_answer_oj_status')"))
        c.execute(T['user'].insert().values(username='own_teacher',
                                            password_hash='x', role='teacher'))
        c.execute(T['notebook'].insert().values(id=1, user_id=1, title='期中复习'))
        c.execute(T['notebook_cell'].insert().values(id=1, notebook_id=1,
                                                     source='print(1)'))
    eng.dispose()
    return path


@pytest.fixture()
def trio_(seed, tmp_path):
    """baseline / offline / target 三份同构库：起点完全一致，之后各自动谁的。"""
    paths, engs = {}, {}
    for key in ('baseline', 'offline', 'target'):
        paths[key] = str(tmp_path / f'{key}.db')
        shutil.copy(seed, paths[key])
        engs[key] = op.sqlite_engine(paths[key])
    trio_ = {'path': paths, 'eng': engs}
    yield trio_
    for e in engs.values():
        e.dispose()


def _write(trio_, which, stmt):
    with trio_['eng'][which].begin() as c:
        c.execute(stmt)


def _cell(trio_, which, name, pk, col):
    """按主键读某列的当前值；None 表示这行已经不在了。"""
    t = T[name]
    pkcol = list(t.primary_key.columns)[0]
    with trio_['eng'][which].connect() as c:
        row = c.execute(select(t.columns[col]).where(pkcol == pk)).first()
        return None if row is None else row[0]


def _patch(trio_):
    return op.build_patch(trio_['path']['baseline'], trio_['path']['offline'])


# ────────────────────────── 差异识别 ──────────────────────────

def test_clean_copy_produces_empty_patch(trio_):
    patch = _patch(trio_)
    assert patch['format'] == op.FORMAT
    assert patch['tables'] == {}
    assert patch['stats'] == {'inserted': 0, 'updated': 0, 'deleted': 0}
    assert patch['baseline']['alembic'] == ['0046_answer_oj_status']


def test_offline_insert_update_delete_are_classified(trio_):
    _write(trio_, 'offline', T['notebook'].insert().values(
        id=2, user_id=1, title='新增的笔记本'))
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='改过的标题'))
    _write(trio_, 'offline', T['notebook_cell'].delete().where(
        T['notebook_cell'].c.id == 1))
    patch = _patch(trio_)
    assert [r['pk'] for r in patch['tables']['notebook']['inserted']] == [[2]]
    assert patch['tables']['notebook']['updated'][0]['row']['title'] == '改过的标题'
    # 基线值必须带在补丁里：导入时靠它判断主库这段时间有没有也被动过
    assert patch['tables']['notebook']['updated'][0]['base']['title'] == '期中复习'
    assert patch['tables']['notebook_cell']['deleted'][0]['pk'] == [1]
    assert patch['stats'] == {'inserted': 1, 'updated': 1, 'deleted': 1}


def test_unchanged_rows_do_not_appear(trio_):
    """只改一行时，其余列必须被认成「没动」——假变更会让冲突判定与补丁体积一起失控。"""
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='x'))
    patch = _patch(trio_)
    assert patch['stats'] == {'inserted': 0, 'updated': 1, 'deleted': 0}
    entry = patch['tables']['notebook']['updated'][0]
    diff_cols = [k for k in entry['row'] if entry['row'][k] != entry['base'][k]]
    assert 'title' in diff_cols
    # updated_at 是 onupdate 刷的：它本就该随补丁带走（主库也得拿到这个新时间戳），
    # 但除此之外不该有任何列被算成差异
    assert set(diff_cols) <= {'title', 'updated_at'}, f'多出了假差异列：{diff_cols}'


# ────────────────────────── 导入：干净场景 ──────────────────────────

def test_apply_to_untouched_target_applies_all(trio_):
    _write(trio_, 'offline', T['notebook'].insert().values(
        id=2, user_id=1, title='离线新增'))
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='离线修改'))
    _write(trio_, 'offline', T['notebook_cell'].delete().where(
        T['notebook_cell'].c.id == 1))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['aborted'] is False and report['conflicts'] == []
    assert report['applied'] == {'inserted': 1, 'updated': 1, 'deleted': 1}
    assert _cell(trio_, 'target', 'notebook', 2, 'title') == '离线新增'
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == '离线修改'
    assert _cell(trio_, 'target', 'notebook_cell', 1, 'source') is None


def test_apply_is_idempotent(trio_):
    """同一份补丁重复导入只会得到 skipped：不能重复插、更不能误覆盖。"""
    _write(trio_, 'offline', T['notebook'].insert().values(
        id=2, user_id=1, title='离线新增'))
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='离线修改'))
    patch = _patch(trio_)
    first = op.apply_patch(patch, trio_['eng']['target'])
    before = _cell(trio_, 'target', 'notebook', 1, 'title')
    again = op.apply_patch(patch, trio_['eng']['target'])
    assert first['applied'] == {'inserted': 1, 'updated': 1, 'deleted': 0}
    assert again['applied'] == {'inserted': 0, 'updated': 0, 'deleted': 0}
    assert again['skipped']['inserted'] == 1 and again['skipped']['updated'] == 1
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == before


def test_parent_is_inserted_before_child(trio_):
    """离线同时新增笔记本与它的单元格：主键序不能反过来，反了外键直接失败。"""
    _write(trio_, 'offline', T['notebook'].insert().values(
        id=5, user_id=1, title='父行'))
    _write(trio_, 'offline', T['notebook_cell'].insert().values(
        id=5, notebook_id=5, source='x=1'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['applied']['inserted'] == 2
    assert _cell(trio_, 'target', 'notebook_cell', 5, 'notebook_id') == 5


# ────────────────────────── 冲突判定 ──────────────────────────

def _make_conflict(trio_):
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='离线改的'))
    _write(trio_, 'target', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='本机改的'))


def test_conflict_keeps_target_by_default(trio_):
    """两边都改过同一行：默认保留主库，只把冲突报出来，绝不静默选一边。"""
    _make_conflict(trio_)
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert len(report['conflicts']) == 1
    item = report['conflicts'][0]
    assert item['table'] == 'notebook' and item['op'] == 'update'
    assert item['target']['title'] == '本机改的'
    assert item['offline']['title'] == '离线改的'
    assert item['baseline']['title'] == '期中复习'
    assert item['resolved'] == 'target'
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == '本机改的'


def test_conflict_offline_strategy_overwrites_target(trio_):
    _make_conflict(trio_)
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'], on_conflict='offline')
    assert report['conflicts'][0]['resolved'] == 'offline'
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == '离线改的'


def test_conflict_lists_only_the_real_clash_columns(trio_):
    """冲突项的 columns 只能有人碰过的那一列。

    updated_at 是 onupdate 刷的，两边都必然不同；混进 columns 里等于用假列污染报告，
    选 offline 策略时还会连带把主库的时间戳也抹掉。
    """
    _make_conflict(trio_)
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['conflicts'][0]['columns'] == ['title']


# ────────────────────── 列级合并（各改各的列） ──────────────────────

def test_different_columns_merge_without_conflict(trio_):
    """老师改标题、本机改描述：两处修改必须都在，不该当成冲突二选一。"""
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='离线改的'))
    _write(trio_, 'target', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(description='本机改的描述'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['conflicts'] == [] and report['aborted'] is False
    assert report['applied']['updated'] == 1
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == '离线改的'
    assert _cell(trio_, 'target', 'notebook', 1, 'description') == '本机改的描述'


def test_bumped_timestamp_is_not_a_false_clash(trio_):
    """本机只是“碰”了一下这行（只刷 updated_at）：内容没改，不算冲突，离线的修改照旧生效。

    这一条不守住的话，实际效果是：主库只要重存过一行，所有离线修改都得退回人工定夺。
    """
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='离线改的'))
    _write(trio_, 'target', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='期中复习'))     # 写回相同值，只让 onupdate 跑
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['conflicts'] == []
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == '离线改的'


def test_delete_survives_a_local_timestamp_bump(trio_):
    """同理：本机只刷了时间戳的话，离线的删除就该照原样执行，不拦。"""
    _write(trio_, 'offline', T['notebook_cell'].delete().where(
        T['notebook_cell'].c.id == 1))
    _write(trio_, 'offline', T['notebook'].delete().where(T['notebook'].c.id == 1))
    _write(trio_, 'target', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='期中复习'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['conflicts'] == [] and report['applied']['deleted'] == 2
    assert _cell(trio_, 'target', 'notebook', 1, 'title') is None


def test_only_bookkeeping_change_counts_as_skipped(trio_):
    """离线侧只刷了时间戳（内容无差异）：不报冲突，也不发一条空 UPDATE。"""
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='期中复习'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['conflicts'] == []
    assert report['applied']['updated'] == 0
    assert report['skipped']['updated'] == 1


def test_abort_rolls_back_the_whole_merge(trio_):
    """abort 遇冲突整体回滚：同批里已经做过的无冲突变更也不能留下。"""
    _make_conflict(trio_)
    _write(trio_, 'offline', T['notebook'].insert().values(id=9, user_id=1, title='顺带新增'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'], on_conflict='abort')
    assert report['aborted'] is True
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == '本机改的'
    assert _cell(trio_, 'target', 'notebook', 9, 'title') is None, '已回滚，不该有半张补丁生效'


def test_dry_run_reports_without_changing_target(trio_):
    _write(trio_, 'offline', T['notebook'].insert().values(id=8, user_id=1, title='预演新增'))
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='离线改的'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'], dry_run=True)
    assert report['dry_run'] is True
    assert report['applied']['inserted'] == 1 and report['applied']['updated'] == 1
    assert _cell(trio_, 'target', 'notebook', 8, 'title') is None
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == '期中复习'


def test_delete_of_locally_modified_row_is_conflict(trio_):
    """离线把某行删了，而本机这段时间改过它：谁对需要人定夺，不能自动删。"""
    _write(trio_, 'offline', T['notebook_cell'].delete().where(
        T['notebook_cell'].c.id == 1))          # 先拆子行，否则离线侧自己先撞外键
    _write(trio_, 'offline', T['notebook'].delete().where(T['notebook'].c.id == 1))
    _write(trio_, 'target', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='本机改的'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['conflicts'][0]['op'] == 'delete'
    assert _cell(trio_, 'target', 'notebook', 1, 'title') == '本机改的'


def test_plain_delete_without_local_touch_is_applied(trio_):
    """同一场景但本机没动过：基线值等于当前值，删除就是删除，不算冲突。"""
    _write(trio_, 'offline', T['notebook_cell'].delete().where(
        T['notebook_cell'].c.id == 1))
    _write(trio_, 'offline', T['notebook'].delete().where(T['notebook'].c.id == 1))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['applied']['deleted'] == 2 and not report['conflicts']
    assert _cell(trio_, 'target', 'notebook', 1, 'title') is None
    assert _cell(trio_, 'target', 'notebook_cell', 1, 'source') is None


def test_primary_key_collision_on_insert_is_conflict(trio_):
    """两边各自新增同一个自增 id：不自动重编号（级联外键风险太大），报冲突。"""
    _write(trio_, 'offline', T['notebook'].insert().values(id=3, user_id=1, title='离线的 3 号'))
    _write(trio_, 'target', T['notebook'].insert().values(id=3, user_id=1, title='本机的 3 号'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['conflicts'][0]['op'] == 'insert'
    assert _cell(trio_, 'target', 'notebook', 3, 'title') == '本机的 3 号'


def test_insert_conflict_offline_strategy_replaces_the_whole_row(trio_):
    """insert 冲突没有基线可拆列：offline 就是整行顶掉，必须把这个代价说在明处。

    本机 E2E 实测：合并完不重置基线时，已归并的行会被重新算成「新增」，再选
    offline 就会把主库这一轮只改在其它列上的修改一起抹掉。行为不改（主键撞车
    本就只能二选一），但报告里必须带 note 与提醒。
    """
    _write(trio_, 'offline', T['notebook'].insert().values(
        id=3, user_id=1, title='离线的 3 号'))
    _write(trio_, 'target', T['notebook'].insert().values(
        id=3, user_id=1, title='本机的 3 号', description='本机独有的备注'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'], on_conflict='offline')
    item = report['conflicts'][0]
    assert item['op'] == 'insert' and 'note' in item
    assert _cell(trio_, 'target', 'notebook', 3, 'title') == '离线的 3 号'
    assert _cell(trio_, 'target', 'notebook', 3, 'description') is None, \
        '整行覆盖的代价：主库独有的列也会没——这正是要在 CLI 里警告的原因'


def test_row_missing_on_target_after_local_delete_is_conflict(trio_):
    """离线改了某行，而本机已把这行删掉：恢复还是承认删除，得人来看。"""
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='离线改的'))
    _write(trio_, 'target', T['notebook_cell'].delete().where(
        T['notebook_cell'].c.id == 1))          # 先拆子行，否则本机侧删不掉父行
    _write(trio_, 'target', T['notebook'].delete().where(T['notebook'].c.id == 1))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'])
    assert report['conflicts'][0]['op'] == 'update'
    assert report['conflicts'][0]['target'] is None


# ────────────────────────── 值归一 ──────────────────────────

def test_norm_tolerates_cross_backend_types():
    """同一份数据在两个后端返回的 Python 形态不同，必须归一到同一个比较口径。

    不归一的后果不是报错，而是把没改过的行判成「两边都动过」，冲突报告里全是假案。
    """
    md = MetaData()
    t = Table('probe', md, Column('b', Boolean), Column('n', Numeric(10, 2)),
              Column('f', Float), Column('i', Integer),
              Column('d', DateTime), Column('x', LargeBinary))
    assert op._norm(t.c.b, 1) == op._norm(t.c.b, True) == True            # noqa: E712
    assert op._norm(t.c.b, 0) == op._norm(t.c.b, False)
    assert op._norm(t.c.n, Decimal('1.50')) == op._norm(t.c.n, 1.5)
    assert op._norm(t.c.n, '2.25') == op._norm(t.c.n, Decimal('2.2500'))
    assert op._norm(t.c.i, '8') == op._norm(t.c.i, 8) == 8
    assert op._norm(t.c.d, datetime(2026, 11, 7, 10, 0, 0)) \
        == op._norm(t.c.d, '2026-11-07 10:00:00.000000')
    assert op._norm(t.c.d, datetime(2026, 11, 7, 10, 0, 0, 500000)) \
        == op._norm(t.c.d, '2026-11-07 10:00:00.5')
    assert op._norm(t.c.x, b'\x01\x02') == '0102'


def test_json_column_keeps_structure_not_repr(trio_):
    """JSON 列不能被归一成 Python repr 文本（本机 E2E 实测踩过的坑）。

    当时 _norm 对 dict 走的是最后那条兼作安全网的 str()，补丁里存下 "{'text': '…'}"（单引号），
    JSONType 对字符串是「原样落库」，于是主库里躺的是一段非法 JSON，
    读回来 json.loads 失败只能拿到原串——表面成功，数据已坏，必须钉住。
    """
    from database.types import JSONType
    jcol = Table('j', MetaData(), Column('cfg', JSONType)).c.cfg
    assert op._norm(jcol, {'b': 1, 'a': [1, 2]}) == {'a': [1, 2], 'b': 1}

    _write(trio_, 'offline', T['notebook_cell'].insert().values(
        id=7, notebook_id=1, order_num=1, cell_type='code', source='x=1',
        outputs={'text': '来自离线机', 'n': 3}))
    patch = _patch(trio_)
    got = patch['tables']['notebook_cell']['inserted'][0]['row']['outputs']
    assert isinstance(got, dict) and got['text'] == '来自离线机'
    report = op.apply_patch(patch, trio_['eng']['target'])
    assert report['applied']['inserted'] == 1
    back = _cell(trio_, 'target', 'notebook_cell', 7, 'outputs')
    assert back == {'n': 3, 'text': '来自离线机'}, f'回读不是对象：{back!r}'


def test_cast_restores_python_types_for_binding():
    t = Table('probe', MetaData(), Column('i', Integer), Column('n', Numeric),
              Column('b', Boolean), Column('d', DateTime), Column('x', LargeBinary))
    assert op._cast(t.c.i, '8') == 8
    assert op._cast(t.c.n, '1.50') == Decimal('1.50')
    assert op._cast(t.c.b, 1) is True
    assert op._cast(t.c.d, '2026-11-07 10:00:00') == datetime(2026, 11, 7, 10, 0, 0)
    assert op._cast(t.c.x, '0102') == b'\x01\x02'
    assert op._cast(t.c.i, None) is None


# ────────────────────────── 基线与补丁文件 ──────────────────────────

def test_capture_baseline_is_idempotent(tmp_path, trio_):
    d = str(tmp_path / 'patchdir')
    dst, created = op.capture_baseline(trio_['path']['offline'], d)
    assert created is True and os.path.isfile(dst)
    _write(trio_, 'offline', T['notebook'].insert().values(
        id=20, user_id=1, title='离线期间写的'))
    dst2, created2 = op.capture_baseline(trio_['path']['offline'], d)
    assert created2 is False, '重复启动不能重抓基线，否则上一次的劳动会被当成基线本身'
    patch = op.build_patch(dst, trio_['path']['offline'])
    assert patch['stats']['inserted'] == 1


def test_stale_baseline_is_detected(tmp_path, trio_):
    """补丁里的基线早于磁盘上的基线 → 判为「可能已合并过」。

    这一条能挡住刚才 E2E 踩到的坑：旧基线重导会把已归并的行当成新增，
    再选 offline 就是整行覆盖。不拦死（重放旧补丁验幂等是合法用法），但必须报出来。
    """
    d = str(tmp_path / 'patchdir')
    os.makedirs(d, exist_ok=True)
    dst, _ = op.capture_baseline(trio_['path']['offline'], d)
    patch = op.build_patch(dst, trio_['path']['offline'])
    stale, why = op.baseline_is_stale(patch, dst)
    assert stale is False, '同一份基线不该算旧'
    os.utime(dst, (time.time() + 120, time.time() + 120))   # 基线被重抓过（归档后新的）
    stale, why = op.baseline_is_stale(patch, dst)
    assert stale is True and '可能已合并过' in why
    stale, why = op.baseline_is_stale({'baseline': {}}, dst)
    assert stale is False and '没记基线时间' in why
    stale, why = op.baseline_is_stale(patch, str(tmp_path / 'nowhere.db'))
    assert stale is False and '不存在' in why


def test_reset_baseline_archives_previous_cycle(seed, tmp_path):
    """重置基线要归档上一周期，且没基线时是空操作。

    这里故意不借 trio_ fixture：它开着 baseline 引擎，Windows 上被占用的文件
    不能 rename，会把一条正常的归档路径测成 PermissionError。
    """
    d = str(tmp_path / 'patchdir')
    src = str(tmp_path / 'offline.db')
    shutil.copy(seed, src)
    assert op.remove_baseline(d) is None, '没有基线时重置应为空操作'
    op.capture_baseline(src, d)
    archived = op.remove_baseline(d)
    assert archived and os.path.isfile(archived)
    assert not os.path.isfile(op.baseline_path(d))


def test_patch_roundtrip_and_format_guard(tmp_path, trio_):
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='中文标题 → 保留'))
    path = op.write_patch(_patch(trio_), str(tmp_path / 'p.json'))
    patch = op.read_patch(path)
    assert patch['tables']['notebook']['updated'][0]['row']['title'] == '中文标题 → 保留'
    with open(path, encoding='utf-8') as f:
        assert '中文标题' in f.read(), '补丁给人看过，中文不能被转义成 \\uXXXX'
    bad = str(tmp_path / 'bad.json')
    with open(bad, 'w', encoding='utf-8') as f:
        json.dump({'format': 'other_v1'}, f)
    with pytest.raises(ValueError):
        op.read_patch(bad)
    half = str(tmp_path / 'half.json')
    with open(half, 'w', encoding='utf-8') as f:
        json.dump({'format': op.FORMAT}, f)
    with pytest.raises(ValueError):
        op.read_patch(half)


def test_summarize_lists_each_table(trio_):
    _write(trio_, 'offline', T['notebook'].insert().values(id=2, user_id=1, title='a'))
    _write(trio_, 'offline', T['notebook'].insert().values(id=3, user_id=1, title='b'))
    text_out = op.summarize(_patch(trio_))
    assert '新增 2 行' in text_out and 'notebook' in text_out


def test_bad_conflict_strategy_is_rejected(trio_):
    with pytest.raises(ValueError):
        op.apply_patch(_patch(trio_), trio_['eng']['target'], on_conflict='last_write_wins')


# ────────────────────────── 归并后的 PG 序列归位 ──────────────────────────
# insert 带显式主键写进 PG，不走列默认值 → 序列不知道号已被占用。
# 不归位的话，本机之后对同一张表的普通新增直接撞主键（真机踩过，见 _sync_sequences）。

def _offline_new_notebook(trio_, pk=2):
    _write(trio_, 'offline', T['notebook'].insert().values(
        id=pk, user_id=1, title='离线机上新增'))


def test_seq_targets_only_pick_tables_with_new_rows(trio_):
    _offline_new_notebook(trio_)
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='只改不改增'))
    targets = dict(op._seq_sync_targets(T, _patch(trio_)))
    assert targets == {'notebook': 'id'}, '只有新增行的表需要归位，纯修改/删除不需要'
    assert op._seq_sync_targets(T, {'tables': {}}) == []


def test_seq_targets_skip_composite_pk_tables(trio_):
    """复合主键没有「一把 setval 就能对齐」的序列，不能硬套单列逻辑。"""
    patch = {'tables': {'exam_question': {'inserted': [{'pk': [1, 1], 'row': {}}]}}}
    assert op._seq_sync_targets(T, patch) == []
    assert op._int_pk(T['exam_question']) is None
    assert op._int_pk(T['notebook']).key == 'id'


def test_sqlite_target_never_runs_pg_sequence_sql(trio_, monkeypatch):
    """SQLite 没有 pg_get_serial_sequence，方言守卫必须拦住。"""
    seen = []
    monkeypatch.setattr(op, '_sync_sequences', lambda conn, tg: seen.append(tg))
    _offline_new_notebook(trio_)
    patch = _patch(trio_)
    op.apply_patch(patch, trio_['eng']['target'], tables=T)
    assert seen == [], '在 SQLite 上发 PG 语句只会把已成功的归并拖成报错'


def test_pg_target_syncs_sequences_only_on_real_commit(trio_, monkeypatch):
    seen = []
    monkeypatch.setattr(op, '_sync_sequences', lambda conn, tg: seen.append(tg))
    monkeypatch.setattr(trio_['eng']['target'].dialect, 'name', 'postgresql')
    _offline_new_notebook(trio_)
    patch = _patch(trio_)
    op.apply_patch(patch, trio_['eng']['target'], tables=T, dry_run=True)
    assert seen == [], '预演整体回滚，不该动序列'
    op.apply_patch(patch, trio_['eng']['target'], tables=T)
    assert seen == [[('notebook', 'id')]]


def test_aborted_apply_does_not_sync_sequences(trio_, monkeypatch):
    """遇冲突中止时事务回滚，行没落库，也就没有号被占用。"""
    seen = []
    monkeypatch.setattr(op, '_sync_sequences', lambda conn, tg: seen.append(tg))
    monkeypatch.setattr(trio_['eng']['target'].dialect, 'name', 'postgresql')
    _offline_new_notebook(trio_)
    _write(trio_, 'offline', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='离线侧改的'))
    _write(trio_, 'target', T['notebook'].update().where(
        T['notebook'].c.id == 1).values(title='本机也改了同一列'))
    report = op.apply_patch(_patch(trio_), trio_['eng']['target'], tables=T,
                            on_conflict='abort')
    assert report['aborted'] is True
    assert seen == []


def test_sync_sequences_statement_shape():
    """跳过无序列表 + 用 GREATEST 保证只前进不后退。"""
    seen = []

    class _R:
        def __init__(self, value):
            self._v = value

        def scalar(self):
            return self._v

    class _Conn:
        def execute(self, stmt, params=None):
            sql = str(stmt)
            seen.append((sql, params))
            if 'pg_get_serial_sequence' in sql:
                return _R('public.notebook_id_seq' if params['t'] == 'notebook' else None)
            return _R(None)

    op._sync_sequences(_Conn(), [('notebook', 'id'), ('no_seq_table', 'id')])
    seq_sqls = [s for s, _ in seen if 'pg_get_serial_sequence' in s]
    setvals = [(s, p) for s, p in seen if 'setval' in s]
    assert len(seq_sqls) == 2, '每张候选表都要先问一次它的主键绑了哪个序列'
    assert len(setvals) == 1, '序列为空（无主键/不绑序列）的表必须跳过'
    body, params = setvals[0]
    assert params == {'s': 'public.notebook_id_seq'}
    assert 'GREATEST' in body and 'coalesce(max("id"), 0)' in body and 'last_value' in body, \
        '不带 GREATEST 会把已跑更远的序列拉回去，反而撞本机已有的行'
