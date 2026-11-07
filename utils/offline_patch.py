# -*- coding: utf-8 -*-
"""离线机器的变更补丁：把「没有 PG 的那台电脑上写的数据」带回主库（v7.5）。

为什么需要它：v7.4 的镜像是单向的（PG → SQLite），老师在离线机上改的东西回不来，
只能人工重录。视情降级让离线机可以正常写本地 SQLite，写出来的差异就得有个体面的
归并办法，否则「允许离线写」这个决定本身就会变成新的分叉源（隐患 #25）。

为什么必须有基线（三方合并）：只有离线库和 PG 两个状态时，无法区分
「老师在离线机上改的」和「本机这段时间改的」。所以离线机第一次启动时抓一份基线快照
（= 本次离线周期的起点），导出时算「基线 → 离线库」的差异，才算得出老师侧做了什么。
补丁里对被改/被删的行连同基线值一起存，导入时才能判断 PG 侧有没有另动过。

口径与边界（重要）：
- **行级、按主键**：不重放 SQL（方言不同），也不要求业务代码配合改任何东西。
- **值比较全靠归一**：同一份数据在 SQLite 与 PG 里返回的 Python 类型不同（Boolean 是
  0/1 还是 True、Numeric 是 '1.5' 还是 Decimal('1.50')、时间戳一边字符串一边 datetime），
  不归一会把没改过的行判成「两边都动过」，制造一堆假冲突。JSON 列反过来：必须**保留
  结构**不能转成文本，否则写回主库的是 Python repr，非法 JSON，读路径全线拿不到对象。
- **主键撞车不自动重编号**：离线插入自增 id=8，而本机也插了 id=8 时，按「保留原主键」
  的口径会报冲突。自动重编号要级联改所有外键引用，风险远大于收益，交给人工定夺。
- **无主键的表跳过并明报**：没有可比对的标识，不做「猜一行对一行」。
- **导入走 Core，不经过 ORM**：所以 PG 侧不会触发镜像实时写，导入后必须刷新镜像
  （CLI 默认顺带做掉），否则镜像会落后到下一次每日对账。
- **归并后必须把 PG 序列推到 max(id)**：insert 带显式主键、不走 PG 默认值，不归位的话
  归并进来的行会提前占掉序列下一个要发的号，本机之后任何普通新增直接撞主键（见
  `_sync_sequences`）。
- **整体一个事务**：dry_run 与 abort 都靠回滚实现，不会留下「半张补丁已生效」的现场。
"""
import json
import os
import shutil
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import create_engine, delete, select, text, types as sqltypes
from sqlalchemy.event import listens_for

from utils.logger import logger
from utils.timeutil import fmt_local, utcnow
from utils.sqlite_mirror import _pk_predicate

FORMAT = 'exam_offline_patch_v1'
CONFLICT_STRATEGIES = ('pg', 'offline', 'abort')
_OP_KEYS = {'insert': 'inserted', 'update': 'updated', 'delete': 'deleted'}


# ────────────────────────── 值归一与还原 ──────────────────────────

def _num(value):
    """数值归一到最短十进制串：1.50 / 1.5 / '1.5' 必须算同一个值。"""
    try:
        d = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    return format(d, 'f')


def _dt(value):
    """时间归一：去时区后缀、对齐微秒尾零，两侧收成同一个 naive 串。

    本仓时间口径是 naive UTC（见 utils/timeutil），而 PG 读回来是 datetime、
    SQLite 读回来是字符串，不归一就没法判断「这行到底改过没有」。
    """
    if isinstance(value, datetime):
        v = value.replace(tzinfo=None) if value.tzinfo else value
        return v.isoformat(sep=' ')
    if isinstance(value, (date, time)):          # date/time 必须在 datetime 之后判
        return value.isoformat()
    s = str(value).strip().replace('T', ' ')
    for suffix in ('+00:00', '-00:00', 'Z', 'z'):
        if s.endswith(suffix):
            s = s[:-len(suffix)].rstrip()
            break
    if '.' in s:                                 # '.5' 与 '.500000' 是同一时刻（都是 50 万微秒）
        head, micro = s.rsplit('.', 1)
        if micro.isdigit():
            # 必须按「秒的小数」而不是「微秒定宽串」解析：PG 给 '.5'，SQLAlchemy 给 '.500000'，
            # 拿 zfill(6) 补 '.5' 会把它读成 5 微秒，两者永不相等，于是每个带微秒的
            # 时间戳都会被误判成「两边都动过」——假冲突能堆满整份报告。
            us = int(micro.ljust(6, '0')[:6])
            s = head if us == 0 else f'{head}.{us:06d}'
    return s


def _resolve_type(col):
    """取列的实际类型形态：TypeDecorator 的真实类型在 impl 上（本仓 Enum 就是这么包的）。"""
    t = getattr(col, 'type', None)
    if t is None:
        return None
    if isinstance(t, sqltypes.TypeDecorator) and isinstance(getattr(t, 'impl', None),
                                                           sqltypes.TypeEngine):
        return t.impl
    return t


def _norm(col, value):
    """把列值转成可比较、可 JSON 化的形态（比较与冲突判定只用它）。

    优先按列类型归一；认不出类型的（自定义类型没暴露 impl）按值本身的 Python 类型兜底。
    任何一步抛错都不丢弃数据：退回 str，宁可判定保守也不要凭空造出差异。
    """
    if value is None:
        return None
    t = _resolve_type(col)
    try:
        if isinstance(value, (dict, list)):
            # JSON 列必须保留结构：走到下面的 str() 会把它写成 Python repr 文本
            # （"{'text': '…'}" 单引号），那不是合法 JSON，入主库后所有 json.loads
            # 的读路径只能拿到原串（E2E 实测踩过）。归一到按 key 排序的普通结构，
            # 两侧都从 dict/list 出发，比较与补丁 JSON 序列化都不丢东西。
            return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         default=str))
        if isinstance(t, sqltypes.Boolean) or isinstance(value, bool):
            return bool(value)
        if isinstance(value, (bytes, bytearray, memoryview)) or \
                isinstance(t, sqltypes.LargeBinary):
            return bytes(value).hex()
        if isinstance(value, datetime) or (isinstance(t, sqltypes.DateTime)
                                           and not isinstance(t, sqltypes.Date)):
            return _dt(value)
        if isinstance(value, (date, time)) or isinstance(t, (sqltypes.Date, sqltypes.Time)):
            return _dt(value)
        if isinstance(t, (sqltypes.Integer, sqltypes.BigInteger, sqltypes.SmallInteger)):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(t, (sqltypes.Numeric, sqltypes.Float)) or \
                isinstance(value, (float, Decimal)):
            return _num(value)
        return str(value)
    except Exception:
        return str(value)


def _cast(col, value):
    """补丁里的 JSON 值 → 能安全绑进目标列的 Python 值。

    不转的后果：psycopg2 把 '8' 当 text 发给 integer 列会报类型不匹配，timestamp 列
    收到字符串同理。认不出类型的列原样交给 SQLAlchemy（自定义类型自己会 process_bind_param）。
    """
    if value is None:
        return None
    t = _resolve_type(col)
    try:
        if isinstance(t, sqltypes.Boolean):
            return bool(value)
        if isinstance(t, sqltypes.LargeBinary):
            return bytes.fromhex(value) if isinstance(value, str) else value
        if isinstance(t, (sqltypes.Integer, sqltypes.BigInteger, sqltypes.SmallInteger)):
            return int(value)
        if isinstance(t, sqltypes.Float):
            return float(value)
        if isinstance(t, sqltypes.Numeric):
            return Decimal(str(value))
        if isinstance(t, sqltypes.DateTime):
            return datetime.fromisoformat(value) if isinstance(value, str) else value
        if isinstance(t, sqltypes.Date):
            return date.fromisoformat(value) if isinstance(value, str) else value
        if isinstance(t, sqltypes.Time):
            return time.fromisoformat(value) if isinstance(value, str) else value
    except Exception as e:
        logger.warning(f'[patch] 列 {getattr(col, "name", "?")} 值还原失败（原样传入）: {e}')
    return value


def _values(t, row, cols):
    return {c.key: _cast(c, row.get(c.key)) for c in cols}


def _auto_maintained(col):
    """这列是不是数据库自己维护的（onupdate 时间戳一类），不代表人有意的修改。

    必须从冲突判定里剔出去：本仓几乎每张表都有 updated_at=onupdate(utcnow)，老师改一次、
    本机也改一次，两边时间戳必然不同。算进去的话每行都会撞出一个谁也没碰过的
    updated_at 列冲突，报告被假案填满，真正的同列冲突反而看不见。
    """
    return getattr(col, 'onupdate', None) is not None or \
        getattr(col, 'server_onupdate', None) is not None


# ────────────────────────── 表清单与连接 ──────────────────────────

def sqlite_engine(path):
    """离线库/基线文件引擎。用完必须 dispose：导出绝不能改动现场。

    开 foreign_keys：SQLite 默认不强制外键，不开的话合并顺序写错了也不会报错，
    而正式目标 PG 是无条件强制的——只有这里也强，本地测试才能真把顺序问题测出来。
    """
    path = os.path.abspath(str(path))
    if not os.path.isfile(path):
        raise FileNotFoundError(f'SQLite 文件不存在：{path}')
    engine = create_engine('sqlite:///' + path.replace(os.sep, '/'),
                           connect_args={'timeout': 30}, future=True)

    @listens_for(engine, 'connect')
    def _fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        try:
            cur.execute('PRAGMA foreign_keys=ON')
        except Exception:          # 不支持也不能让导出失败
            pass
        finally:
            cur.close()

    return engine


def _tables(engine):
    """与镜像同口径的清单（ORM 模型表 + EXTRA_TABLES），保证比的、写的都是同一套表。"""
    from utils import sqlite_mirror as sm
    return sm._mirror_tables(engine)


def _rows(conn, t):
    """读全表为 {主键元组: {列名: 归一值}}；无主键返回 None（表示这张表不比）。"""
    cols = list(t.primary_key.columns)
    if not cols:
        return None
    out = {}
    for row in conn.execute(select(t)):
        m = row._mapping
        out[tuple(m[c.key] for c in cols)] = {c.key: _norm(c, m[c.key]) for c in t.columns}
    return out


def _read_row(conn, t, pk):
    """在调用方事务里读一行（归一形态）；不存在返回 None。主键列数不符也返回 None。"""
    cols = list(t.primary_key.columns)
    if len(cols) != len(pk):
        return None
    row = conn.execute(select(t).where(_pk_predicate(t, [pk]))).first()
    if row is None:
        return None
    return {c.key: _norm(c, row._mapping[c.key]) for c in t.columns}


# ────────────────────────── 导出：基线 → 离线库 ──────────────────────────

def build_patch(baseline_path, offline_path, tables=None):
    """算出离线侧相对基线的变更集，返回补丁 dict（全程不碰 PG）。

    被改和被删的行都带上基线值 base：导入时靠它判断 PG 这段时间有没有也被本机改过，
    没有 base 就只能「无条件覆盖」或「全部当冲突」，两者都不可用。
    """
    base_eng = sqlite_engine(baseline_path)
    off_eng = sqlite_engine(offline_path)
    tables = tables or _tables(off_eng)
    changes, skipped, alembic = [], [], []
    try:
        with base_eng.connect() as b, off_eng.connect() as o:
            try:
                alembic = [r[0] for r in b.execute(
                    text('SELECT version_num FROM alembic_version'))]
            except Exception:
                alembic = []
            for name, t in tables.items():
                b_rows, o_rows = _rows(b, t), _rows(o, t)
                if b_rows is None or o_rows is None:
                    skipped.append(name)
                    continue
                inserted = [{'pk': list(pk), 'row': o_rows[pk]}
                            for pk in o_rows.keys() - b_rows.keys()]
                deleted = [{'pk': list(pk), 'base': b_rows[pk]}
                           for pk in b_rows.keys() - o_rows.keys()]
                updated = [{'pk': list(pk), 'row': o_rows[pk], 'base': b_rows[pk]}
                           for pk in o_rows.keys() & b_rows.keys()
                           if o_rows[pk] != b_rows[pk]]
                if not (inserted or updated or deleted):
                    continue
                changes.append((name, {
                    'inserted': sorted(inserted, key=lambda x: str(x['pk'])),
                    'updated': sorted(updated, key=lambda x: str(x['pk'])),
                    'deleted': sorted(deleted, key=lambda x: str(x['pk'])),
                    'unchanged': len(o_rows) - len(inserted) - len(updated)}))
    finally:
        base_eng.dispose()
        off_eng.dispose()
    stats = {k: sum(len(v[k]) for _, v in changes)
             for k in ('inserted', 'updated', 'deleted')}
    return {
        'format': FORMAT,
        'created_at': fmt_local(utcnow(), '%Y-%m-%d %H:%M:%S'),
        'baseline': dict(_file_info(baseline_path), alembic=alembic),
        'offline': _file_info(offline_path),
        'tables': dict(changes),
        'skipped_tables': skipped,
        'stats': stats,
    }


def _file_info(path):
    path = os.path.abspath(str(path))
    if not os.path.isfile(path):
        return {'file': os.path.basename(path), 'size': None, 'mtime': None}
    st = os.stat(path)
    return {'file': os.path.basename(path), 'size': st.st_size,
            'mtime': fmt_local(datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                               '%Y-%m-%d %H:%M:%S')}


def write_patch(patch, path):
    """补丁落 JSON（缩进 + 中文原样）：先给人看过一遍再导入。"""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(patch, f, ensure_ascii=False, indent=1, default=str)
    return path


def read_patch(path):
    with open(path, encoding='utf-8') as f:
        patch = json.load(f)
    if patch.get('format') != FORMAT:
        raise ValueError(f'补丁格式不是 {FORMAT}（收到 {patch.get("format")}），版本不匹配不要用')
    for key in ('tables', 'baseline', 'stats'):
        if key not in patch:
            raise ValueError(f'补丁缺少 {key} 字段，文件可能不完整')
    return patch


def summarize(patch):
    """人类可读摘要（导入前先看这个）：每表各类操作行数 + 跳过的表 + 基线版本。"""
    lines = [f"补丁生成于 {patch.get('created_at')}，"
             f"基线 {patch['baseline'].get('file')} "
             f"(alembic={','.join(patch['baseline'].get('alembic') or []) or '无'})",
             f"合计：新增 {patch['stats']['inserted']} 行 / "
             f"修改 {patch['stats']['updated']} 行 / 删除 {patch['stats']['deleted']} 行"]
    for name, delta in patch['tables'].items():
        lines.append(f"  {name:<44} +{len(delta['inserted']):<5} "
                     f"~{len(delta['updated']):<5} -{len(delta['deleted'])}")
    if patch.get('skipped_tables'):
        lines.append(f"  无主键、未参与比对：{patch['skipped_tables']}")
    return '\n'.join(lines)


# ────────────────────────── 基线快照 ──────────────────────────

def baseline_path(patch_dir):
    return os.path.join(patch_dir, 'baseline.db')


def capture_baseline(db_path, patch_dir):
    """离线机第一次启动时抓基线，返回 (路径, 是否新建)。已存在则绝不动。

    为什么不能每次启动都重抓：那样上一次离线期间写的东西会被当成「基线本来就有」，
    导出时永远看不见，等于静默丢掉老师的劳动。基线只能由导入成功后显式重置。
    """
    os.makedirs(patch_dir, exist_ok=True)
    dst = baseline_path(patch_dir)
    if os.path.isfile(dst):
        return dst, False
    src = os.path.abspath(str(db_path))
    if not os.path.isfile(src):
        raise FileNotFoundError(f'离线库不存在，无法抓基线：{src}')
    # 用 sqlite 在线备份 API：直接 copy 正在使用的文件可能拷到半截（撕裂页/未检查点 WAL）
    import sqlite3
    # 注意 sqlite3 的 `with conn` 只管事务提交，不关连接！拿它当 close 用会把
    # baseline.db 的句柄一直留在进程里，下一步归档/重置基线在 Windows 上直接撞
    # PermissionError（实测踩过），而且每次启动都漏一条连接。
    src_con, dst_con = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        with dst_con:
            src_con.backup(dst_con)
    finally:
        dst_con.close()
        src_con.close()
    return dst, True


def baseline_is_stale(patch, baseline_file):
    """补丁里记的基线，是不是已经比磁盘上那份基线旧（返回 (是否旧, 说明)）。

    为什么单管这一条：合并完不重置基线时，下一份补丁仍拿旧基线算差异，上一轮已经
    归并进主库的行会被当成「新增」再发一遍；碰上 --on-conflict offline 就是
    整行覆盖，把主库这一轮的修改一起抹掉（本机 E2E 实测踩到）。基线只能由导入
    成功后显式重置，所以这口锅只能靠提醒而不是代劳。

    参数给的是基线文件本身（而不是目录）：--baseline 可以指到拷回来的目录里，
    拿本机的默认目录判断会错。
    """
    path = str(baseline_file)
    if not os.path.isfile(path):
        return False, f'基线文件不存在，无从比较：{path}'
    recorded = (patch.get('baseline') or {}).get('mtime')
    if not recorded:
        return False, '补丁没记基线时间（旧版补丁），不做判定'
    current = _file_info(path).get('mtime')
    if current and recorded < current:
        return True, f'补丁基线 {recorded} 早于当前基线 {current}，本补丁可能已合并过'
    return False, f'补丁基线 {recorded} 不早于当前基线 {current}'


def remove_baseline(patch_dir_or_file):
    """导入成功后重置基线：下次离线启动会以「已合并」的状态重抓。

    不直接删，先归档 baseline.used_<时间戳>.db：合并结果有疑问时还能回溯上一个离线周期。

    参数可以是一个目录（重置默认 baseline.db）也可以直接是基线文件路径：拷回来的
    离线目录里基线不在本机默认目录下，--reset-baseline 得能重置到那份。
    """
    target = str(patch_dir_or_file)
    path = target if target.lower().endswith('.db') else baseline_path(target)
    if not os.path.isfile(path):
        return None
    patch_dir = os.path.dirname(os.path.abspath(path))
    archived = os.path.join(
        patch_dir, 'baseline.used_%s.db' % fmt_local(utcnow(), '%Y%m%d_%H%M%S'))
    try:
        shutil.move(path, archived)
    except PermissionError as e:
        # Windows 上文件被任何连接打开时 rename 会直接失败，说清该关谁而不是抛个 32
        raise PermissionError(
            f'基线文件正被另一个进程打开，无法重置：{path}；'
            f'请先关掉正在跑的离线服务（或另一个 --export 进程）再重试') from e
    olds = sorted((os.path.join(patch_dir, n) for n in os.listdir(patch_dir)
                   if n.startswith('baseline.used_')), key=os.path.basename, reverse=True)
    for stale in olds[3:]:
        try:
            os.remove(stale)
        except OSError:
            pass
    return archived


# ────────────────────────── 导入：补丁 → PG ──────────────────────────

def _int_pk(table):
    """单列整数主键 → 返回该列；复合主键/非整数主键返回 None（没有序列可补）。"""
    cols = list(table.primary_key.columns)
    if len(cols) != 1:
        return None
    impl = _resolve_type(cols[0])
    if isinstance(impl, sqltypes.Boolean) or not isinstance(impl, sqltypes.Integer):
        return None
    return cols[0]


def _seq_sync_targets(tables, patch):
    """本补丁里有新增行、且主键是单列整数的表：[(表名, 主键列名), …]。

    tables 是归并用的表清单字典（与写入同一套），不在清单里的表名不会被处理。
    只看 inserted：update/delete 不引入新主键，不需要动序列。
    """
    out = []
    for name in tables:
        if not (patch['tables'].get(name) or {}).get('inserted'):
            continue
        col = _int_pk(tables[name])
        if col is not None:
            out.append((name, col.key))
    return out


def _sync_sequences(conn, targets):
    """把 PG 序列推到已落库的 max(id)，只在 PostgreSQL 方言下调用。

    为什么不能省（真机取证）：`_apply_one` 的 insert 带显式主键、不经 PG 默认值，
    于是归并进来的行会占掉序列「下一个要发」的那个号却不推进序列；实测
    notebook 归并 id=9 后，本机再建笔记本就 `UniqueViolation: notebook_pkey`——
    等于归并完把主库的写入功能弄坏，而且是隔一段时间才爆、现场已离开归并日志。
    SQLite 无此问题（按 rowid max+1 自己发号），所以不在那个方言上跑。

    GREATEST 保证**只前进不后退**：若 PG 序列已跑到比补丁 max(id) 更远（本机这段时间
    自己新增过），无条件 setval 到 max 会把序列拉回去，反而会撞已有行。
    """
    for name, col in targets:
        seq = conn.execute(text('SELECT pg_get_serial_sequence(:t, :c)'),
                           {'t': name, 'c': col}).scalar()
        if not seq:
            continue      # 复合/非序列主键，或本就没绑定序列
        conn.execute(text(
            f'SELECT setval(:s, GREATEST((SELECT coalesce(max("{col}"), 0) FROM "{name}"), '
            f'(SELECT last_value FROM {seq})), true)'), {'s': seq})


def apply_patch(patch, target_engine, on_conflict='pg', dry_run=False, tables=None):
    """把补丁合并进目标库（PG），返回报告 dict。全程一个事务。

    三方判定（B=基线，O=离线最终值，P=目标当前值）：
    - 新增：P 无 → 插入；P 有且等于 O → 已同步跳过；P 有但不等 → 冲突。
    - 修改：P 无（本机把行删了）→ 冲突；P == O → 跳过；否则按列拆：只写「离线改过而
      本机没改过」的列，两边改到同一列才叫冲突（详见 _apply_one）。
    - 删除：P 无 → 跳过；P 内容与 B 一致 → 删；本机改过实际列 → 冲突。

    两边都只动了 onupdate 时间戳（updated_at）不算碰过：那是数据库自己刷的。

    顺序：插入/更新按元数据依赖序（父表在前），删除按反序（子表先删），避开外键指向
    还不存在的父行。dry_run 与 abort 都以回滚收场，库里不会留下半张补丁。
    """
    if on_conflict not in CONFLICT_STRATEGIES:
        raise ValueError(f'on_conflict 只支持 {CONFLICT_STRATEGIES}，收到 {on_conflict}')
    tables = tables or _tables(target_engine)
    report = {'applied': {'inserted': 0, 'updated': 0, 'deleted': 0},
              'skipped': {'inserted': 0, 'updated': 0, 'deleted': 0},
              'conflicts': [], 'aborted': False, 'dry_run': bool(dry_run),
              'on_conflict': on_conflict}
    ordered = [n for n in tables if n in patch['tables']]
    conn = target_engine.connect()
    trans = conn.begin()
    try:
        for op_kind, reverse in (('insert', False), ('update', False), ('delete', True)):
            if report['aborted']:
                break
            for name in (reversed(ordered) if reverse else ordered):
                t = tables[name]
                if not list(t.primary_key.columns):
                    continue
                cols = list(t.columns)
                for item in patch['tables'][name][_OP_KEYS[op_kind]]:
                    outcome = _apply_one(op_kind, item, t, cols, conn, report, on_conflict)
                    if outcome == 'abort':
                        break
                if report['aborted']:
                    break
        # 新增行是带显式主键写进来的，PG 序列不知道号已被占用：不在此归位，
        # 本机之后对同一张表的普通新增会撞主键（详见 _sync_sequences）。
        if not report['aborted'] and not dry_run and \
                target_engine.dialect.name == 'postgresql':
            _sync_sequences(conn, _seq_sync_targets(tables, patch))
        if report['aborted'] or dry_run:
            trans.rollback()
        else:
            trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()
    return report


def _apply_one(op_kind, item, t, cols, conn, report, on_conflict):
    """处理一行，返回 'applied' / 'skipped' / 'abort'（冲突已按策略处置时也归前两者）。

    update 走列级三方合并：逐列分别看「离线侧有没有改」与「目标侧有没有改」。
    一开始本函数是整行覆盖，那会把「老师改了 title、本机改了 description」
    当成整行冲突：选 target 丢老师的修改，选 offline 抹本机修改，两边都不对。
    """
    key = _OP_KEYS[op_kind]
    pk = tuple(item['pk'])
    cur = _read_row(conn, t, pk)
    name = t.name
    if op_kind == 'insert':
        want = item['row']
        if cur is None:
            # dry_run 也真实执行语句：靠外层统一回滚来「预演」，判定路径与正式导入一致
            conn.execute(t.insert().values(**_values(t, want, cols)))
            report['applied'][key] += 1
            return 'applied'
        if cur == want:
            report['skipped'][key] += 1
            return 'skipped'
        return _conflict(report, name, op_kind, pk, cur, want, None, on_conflict, conn, t, cols)
    if op_kind == 'update':
        want, base = item['row'], item.get('base')
        if cur is None:
            return _conflict(report, name, op_kind, pk, None, want, base,
                             on_conflict, conn, t, cols)
        if cur == want:
            report['skipped'][key] += 1
            return 'skipped'
        if base is None:      # 旧补丁没有基线列，无法拆列，保守按整行处理
            return _conflict(report, name, op_kind, pk, cur, want, base,
                             on_conflict, conn, t, cols)
        content = [c for c in cols if not _auto_maintained(c)]
        theirs = [c for c in content if want.get(c.key) != base.get(c.key)]
        clash = [c.key for c in theirs if cur.get(c.key) != base.get(c.key)]
        if clash:
            # 同一列两边都动过：该行不动（不半套落库），把列名列清楚交给人定夺
            return _conflict(report, name, op_kind, pk, cur, want, base,
                             on_conflict, conn, t, cols, columns=clash)
        if not theirs:
            # 只有 updated_at 之类的时间戳变过：内容没动，不写也不报冲突
            report['skipped'][key] += 1
            return 'skipped'
        conn.execute(t.update().where(_pk_predicate(t, [pk])).values(
            **{c.key: _cast(c, want.get(c.key)) for c in theirs}))
        report['applied'][key] += 1
        return 'applied'
    # delete
    base = item.get('base')
    if cur is None:
        report['skipped'][key] += 1
        return 'skipped'
    if base is not None and cur != base:
        clash = [c.key for c in cols if not _auto_maintained(c)
                 and cur.get(c.key) != base.get(c.key)]
        if clash:
            return _conflict(report, name, op_kind, pk, cur, None, base,
                             on_conflict, conn, t, cols, columns=clash)
    conn.execute(delete(t).where(_pk_predicate(t, [pk])))
    report['applied'][key] += 1
    return 'applied'


def _conflict(report, name, op_kind, pk, cur, want, base, strategy, conn, t, cols,
              columns=None):
    """冲突：pg=保留目标（计入 skipped）、offline=以离线为准（计入 applied）、abort=中止。

    columns 为冲突列清单（update/delete 才有）：insert 冲突只能整行取舍，
    而 update 冲突在策略为 offline 时只写真正撞车的列，不搭着改无争的列。
    """
    item = {'table': name, 'op': op_kind, 'pk': [str(v) for v in pk],
            'target': cur, 'offline': want, 'baseline': base}
    if columns:
        item['columns'] = columns
    if op_kind == 'insert' and strategy == 'offline' and cur is not None:
        # insert 没有基线可拆列，「以离线为准」只能整行顶掉：把这一点写进报告，
        # 别让人以为只改了离线新写的那几列（主库独有的列也会被换掉）
        item['note'] = ('新增行主键已存在且内容不同，按 offline 整行覆盖：'
                        '主库该行的其它列一并被替换')
        logger.warning('[patch] %s pk=%s 整行覆盖主库（insert 无基线可拆列）',
                       name, item['pk'])
    if strategy == 'abort':
        report['conflicts'].append(item)
        report['aborted'] = True
        return 'abort'
    key = _OP_KEYS[op_kind]
    if strategy == 'offline':
        if want is not None:
            if cur is None:
                conn.execute(t.insert().values(**_values(t, want, cols)))
            else:
                picked = [c for c in cols if not columns or c.key in columns]
                conn.execute(t.update().where(_pk_predicate(t, [pk])).values(
                    **{c.key: _cast(c, want.get(c.key)) for c in picked}))
        elif op_kind == 'delete':
            conn.execute(delete(t).where(_pk_predicate(t, [pk])))
        report['applied'][key] += 1
        report['conflicts'].append(dict(item, resolved='offline'))
        return 'applied'
    report['skipped'][key] += 1
    report['conflicts'].append(dict(item, resolved='target'))
    return 'skipped'


def write_conflicts(report, patch_dir):
    """冲突单独落文件：合并只能告诉你「哪几行两边都动过」，取舍得人做。"""
    if not report['conflicts']:
        return None
    path = os.path.join(
        patch_dir, 'conflicts_%s.json' % fmt_local(utcnow(), '%Y%m%d_%H%M%S'))
    os.makedirs(patch_dir, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'created_at': fmt_local(utcnow(), '%Y-%m-%d %H:%M:%S'),
                   'aborted': report['aborted'], 'on_conflict': report['on_conflict'],
                   'conflicts': report['conflicts']}, f, ensure_ascii=False, indent=1,
                  default=str)
    return path
