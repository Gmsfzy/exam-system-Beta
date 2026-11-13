# -*- coding: utf-8 -*-
"""v7.14 教案形态：把 'lesson_plan' 加进 study_material.kind 的 CHECK 白名单。

新增一份提示词模板（services.MATERIAL_TEMPLATES）就够了？不够——kind 上有 DB 级
CHECK 白名单（models._material_kind_ck），PG 会直接拒绝写入，SQLite 同样强制 CHECK。

⚠️ SQLite 侧为什么不用 op.batch_alter_table：alembic 的 batch 把**带名字的**反射
CHECK 放进 unnamed_constraints 桶（batch.py:307），而 drop_constraint 靠对象身份
比对（batch.py:732），迁移里新构造的 CheckConstraint 永远匹配不上，于是旧白名单被
原样带进重建后的表——迁移不报错、日志正常、新值照样被拒。这类"跑绿了但没生效"比
报错难查得多，故 SQLite 走显式重建：反射现有列/PK/FK/UNIQUE/其余 CHECK/索引，按原
结构建新表搬数据，只替换那一条 kind CHECK。

反射而非手写 DDL：本机 SQLite 库的 study_material 列集并不一致（有的还停在 0046
没有 plan_id/task_id），手写建表语句会把结构钉死在某个版本上。

方言可移植（v6.8 约束）：本文件唯一的 SQLite 专属语句是重建期间临时关
legacy_alter_table —— 否则 RENAME 会把子表（material_favorite/material_report/
material_gen_job）的 REFERENCES study_material 一起改写到临时表名上，DROP 掉临时表
后那些外键就指向不存在的表。PG 分支只发原生 DROP/ADD CONSTRAINT。

Revision ID: 0048_material_lesson_plan
Revises: 0047_material_batch
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = '0048_material_lesson_plan'
down_revision = '0047_material_batch'
branch_labels = None
depends_on = None

TABLE = 'study_material'
CK_NAME = '_material_kind_ck'
# 与 database/models.py 的 _material_kind_ck 逐项一致（tests/test_material_lesson_plan.py 有护栏用例）
KINDS_WITH_LESSON = ('video_script', 'mindmap', 'lecture', 'summary', 'quiz',
                     'lesson_plan', 'manual')
KINDS_LEGACY = ('video_script', 'mindmap', 'lecture', 'summary', 'quiz', 'manual')


def _sqltext(kinds):
    return "kind IN (%s)" % ', '.join("'%s'" % k for k in kinds)


def _kind_check(bind):
    """现存 kind CHECK 的表达式文本；该约束不存在返回 None。"""
    for c in sa.inspect(bind).get_check_constraints(TABLE):
        if c.get('name') == CK_NAME:
            return c.get('sqltext') or ''
    return None


def _count(bind):
    return bind.execute(sa.text('SELECT COUNT(*) FROM %s' % TABLE)).scalar()


def upgrade():
    bind = op.get_bind()
    _apply(bind, KINDS_WITH_LESSON, 'lesson_plan')


def downgrade():
    bind = op.get_bind()
    n = bind.execute(sa.text("SELECT COUNT(*) FROM %s WHERE kind='lesson_plan'"
                             % TABLE)).scalar()
    if n:
        raise RuntimeError(
            '[0048 downgrade] 还有 %d 份教案（kind=lesson_plan）在库，收紧白名单会连带'
            '毁掉这些行；请先删除这些资料再降级' % n)
    _apply(bind, KINDS_LEGACY, None)


def _apply(bind, kinds, marker):
    cur = _kind_check(bind)
    if cur and marker and marker in cur:
        print('[0048] %s 已放开（幂等跳过）' % CK_NAME)
        return
    if cur is None:
        # 老库或 create_all 之外的路径没带名字：直接补一条，不纠结删除
        op.create_check_constraint(CK_NAME, TABLE, _sqltext(kinds))
        print('[0048] %s 原先不存在，已按新白名单创建' % CK_NAME)
        return
    if bind.dialect.name == 'sqlite':
        _rebuild_sqlite(bind, kinds)
    else:
        op.drop_constraint(CK_NAME, table_name=TABLE, type_='check')
        op.create_check_constraint(CK_NAME, TABLE, _sqltext(kinds))
        print('[0048] %s 已按新白名单替换（%s）' % (CK_NAME, bind.dialect.name))


def _rebuild_sqlite(bind, kinds):
    """按反射结构重建 study_material，只替换 kind 那一条 CHECK，行数必须不变。"""
    insp = sa.inspect(bind)
    cols = insp.get_columns(TABLE)
    names = [c['name'] for c in cols]
    pk_cols = (insp.get_pk_constraint(TABLE).get('constrained_columns')
               or ['id'])
    # 必须在改名/DROP 之前取走：旧表一没，get_indexes 就只剩空集，索引会静默丢失
    checks = list(insp.get_check_constraints(TABLE))
    uniques = list(insp.get_unique_constraints(TABLE))
    fks = list(insp.get_foreign_keys(TABLE))
    indexes = list(insp.get_indexes(TABLE))
    md = sa.MetaData()
    args = []
    for c in cols:
        args.append(sa.Column(
            c['name'], c['type'],
            nullable=c.get('nullable', True),
            # 反射回来的 default 是 DDL 原文（含引号），原样贴回才不改写默认值语义
            server_default=sa.text(c['default']) if c.get('default') else None,
            primary_key=c['name'] in pk_cols))
    for c in checks:
        if c['name'] == CK_NAME:
            continue
        args.append(sa.CheckConstraint(c['sqltext'], name=c['name']))
    for u in uniques:
        args.append(sa.UniqueConstraint(*u['column_names'], name=u['name']))
    for f in fks:
        # 建表时只需知道被引用表的列名能解析外键，不能让它们进 DDL：
        # 按 alembic batch 的做法在临时 MetaData 里摆一组空壳引用表
        rt = f['referred_table']
        if rt != TABLE and rt not in md:
            sa.Table(rt, md, *[sa.Column(cn, sa.Integer, primary_key=True)
                               for cn in (f['referred_columns'] or ['id'])])
        args.append(sa.ForeignKeyConstraint(
            f['constrained_columns'],
            ['%s.%s' % (f['referred_table'], col)
             for col in (f['referred_columns'] or ['id'])],
            name=f.get('name') or None))
    args.append(sa.CheckConstraint(_sqltext(kinds), name=CK_NAME))
    new_t = sa.Table(TABLE, md, *args)

    tmp = '_sm_old_0048'
    before = _count(bind)
    # 该库默认不强制外键（全仓未设 PRAGMA foreign_keys），此处只为保险
    bind.exec_driver_sql('PRAGMA foreign_keys=OFF')
    # ON＝RENAME 不连带改写子表引用；子表仍按名字指向即将重建的 study_material
    bind.exec_driver_sql('PRAGMA legacy_alter_table=ON')
    try:
        bind.exec_driver_sql('ALTER TABLE %s RENAME TO %s' % (TABLE, tmp))
        new_t.create(bind=bind, checkfirst=False)
        collist = ', '.join('"%s"' % n for n in names)
        bind.exec_driver_sql(
            'INSERT INTO %s (%s) SELECT %s FROM %s' % (TABLE, collist, collist, tmp))
        after = _count(bind)
        bind.exec_driver_sql('DROP TABLE %s' % tmp)
    finally:
        bind.exec_driver_sql('PRAGMA legacy_alter_table=OFF')
    # 索引随旧表一起被 DROP，按之前反射到的清单原样补回（唯一约束在建表时已带）
    for ix in indexes:
        sa.Index(ix['name'], *[new_t.c[n] for n in ix['column_names']],
                 unique=bool(ix.get('unique'))).create(bind=bind)
    if after != before:
        raise RuntimeError('[0048] 重建后行数不一致：%d → %d，已中止' % (before, after))
    print('[0048] SQLite 侧 study_material 已重建，%d 行原样保留，%s 已换成新白名单'
          % (after, CK_NAME))
