"""v7.21 学习规划仓：plan_template / plan_template_item 两表 + 路径节点放宽

背景：学习规划仓要把「专业/课程 + 可复用模板」沉淀下来，模板条目既可能指向
结构化主数据（课程/章节/知识点），也可能是非结构化素材（外链/富文本/附件）。
一键使用模板时，条目要落成个人学习路径节点，因此 learning_path_node 必须能挂
课程/外链/富文本/附件——旧的 _node_ref_check（知识点或章节二选一）挡住了这条路。

三件事：
1. learning_path_node 补 6 列：course_id / title / url / content / file_name / file_size
2. 重建 _node_ref_check 为「六类学习对象至少挂一种」
3. 新建 plan_template（模板头）与 plan_template_item（有序条目）

⚠️ 方言可移植（v6.8 约束）：严禁 PRAGMA/sqlite_master；sa.inspect 判存在性、逐列判重。
SQLite 不支持 DROP CONSTRAINT，旧 CHECK 在 SQLite 下保留（仅本地开发库受影响，
生产 PostgreSQL 走 ALTER TABLE DROP/ADD CONSTRAINT）。

Revision ID: 0052_plan_repository
Revises: 0051_ai_ask_and_suggest
Create Date: 2026-11-15
"""
import sqlalchemy as sa
from alembic import op

revision = '0052_plan_repository'
down_revision = '0051_ai_ask_and_suggest'
branch_labels = None
depends_on = None

NODE_TABLE = 'learning_path_node'
TPL = 'plan_template'
ITEM = 'plan_template_item'

NODE_COLS = (
    ('course_id', sa.Column('course_id', sa.Integer(), nullable=True)),
    ('title', sa.Column('title', sa.String(200), nullable=True)),
    ('url', sa.Column('url', sa.String(500), nullable=True)),
    ('content', sa.Column('content', sa.Text(), nullable=True)),
    ('file_name', sa.Column('file_name', sa.String(255), nullable=True)),
    ('file_size', sa.Column('file_size', sa.Integer(), nullable=True)),
)

NODE_CHECK = (
    '(knowledge_point_id IS NOT NULL) OR (chapter_id IS NOT NULL) '
    'OR (course_id IS NOT NULL) OR (url IS NOT NULL) '
    'OR (content IS NOT NULL) OR (file_name IS NOT NULL)'
)

ITEM_CHECK = (
    '(course_id IS NOT NULL) OR (chapter_id IS NOT NULL) '
    'OR (knowledge_point_id IS NOT NULL) OR (url IS NOT NULL) '
    'OR (content IS NOT NULL) OR (file_name IS NOT NULL)'
)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # ── 1. learning_path_node 扩列 ──────────────────────────────
    if insp.has_table(NODE_TABLE):
        have = {c['name'] for c in insp.get_columns(NODE_TABLE)}
        added = []
        for name, col in NODE_COLS:
            if name in have:
                continue
            op.add_column(NODE_TABLE, col)
            added.append(name)
        print('[0052] %s 扩列：%s' % (NODE_TABLE, ', '.join(added) or '无（幂等跳过）'))

        # ── 2. 重建节点引用约束 ────────────────────────────────
        if bind.dialect.name == 'postgresql':
            op.create_foreign_key(
                'fk_learning_path_node_course_id', NODE_TABLE, 'course', ['course_id'], ['id'])
            bind.execute(sa.text(
                'ALTER TABLE %s DROP CONSTRAINT IF EXISTS _node_ref_check' % NODE_TABLE))
            bind.execute(sa.text(
                'ALTER TABLE %s ADD CONSTRAINT _node_ref_check CHECK (%s)'
                % (NODE_TABLE, NODE_CHECK)))
            print('[0052] %s 约束 _node_ref_check 已放宽为六类学习对象' % NODE_TABLE)
        else:
            print('[0052] %s 约束跳过（%s 不支持 DROP CONSTRAINT，旧约束仅拦非结构化节点）'
                  % (NODE_TABLE, bind.dialect.name))
    else:
        print('[0052] %s 不存在，跳过扩列' % NODE_TABLE)

    # ── 3. plan_template ──────────────────────────────────────
    if not insp.has_table(TPL):
        op.create_table(
            TPL,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('title', sa.String(100), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('major_id', sa.Integer(), sa.ForeignKey('major.id'), nullable=True),
            sa.Column('template_type', sa.String(20), nullable=False,
                      server_default='structured'),
            sa.Column('visibility', sa.String(10), nullable=False, server_default='private'),
            sa.Column('difficulty', sa.String(20), nullable=True, server_default='medium'),
            sa.Column('target_hours', sa.Integer(), nullable=True),
            sa.Column('use_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('owner_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=True,
                      server_default=sa.func.now()),
        )
        op.create_index('ix_plan_tpl_visibility', TPL, ['visibility'])
        op.create_index('ix_plan_tpl_major', TPL, ['major_id'])
        op.create_index('ix_plan_tpl_owner', TPL, ['owner_id'])
        print('[0052] %s 已建' % TPL)
    else:
        print('[0052] %s 已存在（幂等跳过）' % TPL)

    # ── 4. plan_template_item ─────────────────────────────────
    if not insp.has_table(ITEM):
        op.create_table(
            ITEM,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('template_id', sa.Integer(),
                      sa.ForeignKey('plan_template.id'), nullable=False),
            sa.Column('item_type', sa.String(20), nullable=False, server_default='course'),
            sa.Column('title', sa.String(200), nullable=True),
            sa.Column('course_id', sa.Integer(), sa.ForeignKey('course.id'), nullable=True),
            sa.Column('chapter_id', sa.Integer(), sa.ForeignKey('chapter.id'), nullable=True),
            sa.Column('knowledge_point_id', sa.Integer(),
                      sa.ForeignKey('knowledge_point.id'), nullable=True),
            sa.Column('url', sa.String(500), nullable=True),
            sa.Column('content', sa.Text(), nullable=True),
            sa.Column('file_name', sa.String(255), nullable=True),
            sa.Column('file_size', sa.Integer(), nullable=True),
            sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('estimated_minutes', sa.Integer(), nullable=True, server_default='60'),
            sa.Column('order_num', sa.Integer(), nullable=False, server_default='0'),
            sa.UniqueConstraint('template_id', 'order_num', name='_plan_tpl_item_order_uc'),
            sa.CheckConstraint(ITEM_CHECK, name='_plan_tpl_item_ref_check'),
        )
        op.create_index('ix_plan_tpl_item_tpl', ITEM, ['template_id'])
        print('[0052] %s 已建' % ITEM)
    else:
        print('[0052] %s 已存在（幂等跳过）' % ITEM)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table in (ITEM, TPL):
        if not insp.has_table(table):
            print('[0052 downgrade] %s 不存在（幂等跳过）' % table)
            continue
        n = bind.execute(sa.text('SELECT COUNT(*) FROM %s' % table)).scalar()
        if n:
            raise RuntimeError(
                '[0052 downgrade] %s 还有 %d 行数据，删表等于删模板；请先备份再降级'
                % (table, n))
        for idx in {i['name'] for i in insp.get_indexes(table)}:
            op.drop_index(idx, table_name=table)
        op.drop_table(table)
        print('[0052 downgrade] %s 已删除' % table)

    if not insp.has_table(NODE_TABLE):
        return
    if bind.dialect.name == 'postgresql':
        bind.execute(sa.text(
            'ALTER TABLE %s DROP CONSTRAINT IF EXISTS _node_ref_check' % NODE_TABLE))
        bind.execute(sa.text(
            'ALTER TABLE %s ADD CONSTRAINT _node_ref_check CHECK '
            '(knowledge_point_id IS NOT NULL OR chapter_id IS NOT NULL)' % NODE_TABLE))
        bind.execute(sa.text(
            'ALTER TABLE %s DROP CONSTRAINT IF EXISTS fk_learning_path_node_course_id'
            % NODE_TABLE))
    have = {c['name'] for c in insp.get_columns(NODE_TABLE)}
    for name, _ in reversed(NODE_COLS):
        if name in have:
            op.drop_column(NODE_TABLE, name)
    print('[0052 downgrade] %s 扩列已回退' % NODE_TABLE)
