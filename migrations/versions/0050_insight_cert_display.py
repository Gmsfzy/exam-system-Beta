"""v7.19 学习心得 + 证书公开分享：新表 study_insight / certificate_display

两张新表都是「只加不动既有表」：
- study_insight：自我学习模块新增的学习心得。固定三段（学习感悟与收获 / 我的心得与总结 /
  反思创造）分开存列，加一套周期归档字段（day/week/month/stage/custom + 起止 + 阶段名）。
  之所以不复用 study_note：笔记是无结构的随时记录，心得是回望一段周期的复盘产出，
  两者字段集不同（周期、三段、公开/分享），混在一张表里两头都要加 NULL 列并各写一套校验。
- certificate_display：三源证书（system/module/social）的展示态旁表——公开开关、浏览数、
  已分享的社区帖 id。刻意不给三张证书表各加两列：系统结业与赛季证书是平台颁发的只读
  资产，社会证书已有自己的核验字段，把「我怎么展示它」写进证书本体会让三类表结构继续
  分叉；旁表按 (cert_kind, cert_id) 唯一，没设置过就不存在行，读侧按缺省私有处理。

⚠️ 方言可移植（v6.8 约束）：严禁 PRAGMA/sqlite_master；用 sa.inspect 判存在性，
create_table/drop_table 全部幂等跳过。tags 用 TEXT（ORM 侧 JSONType(impl=Text)），
与 0015/0049 的 JSON 列同口径，避免 PG 上多出 JSON 类型让镜像重建对不上列结构。

Revision ID: 0050_insight_cert_display
Revises: 0049_material_attachments
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = '0050_insight_cert_display'
down_revision = '0049_material_attachments'
branch_labels = None
depends_on = None

INSIGHT = 'study_insight'
DISPLAY = 'certificate_display'


def upgrade():
    insp = sa.inspect(op.get_bind())

    if not insp.has_table(INSIGHT):
        op.create_table(
            INSIGHT,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('gains', sa.Text(), nullable=False, server_default=''),
            sa.Column('summary', sa.Text(), nullable=False, server_default=''),
            sa.Column('reflection', sa.Text(), nullable=False, server_default=''),
            sa.Column('period_type', sa.String(10), nullable=False, server_default='week'),
            sa.Column('period_start', sa.DateTime(), nullable=True),
            sa.Column('period_end', sa.DateTime(), nullable=True),
            sa.Column('period_note', sa.String(80), nullable=True),
            sa.Column('tags', sa.Text(), nullable=True),
            sa.Column('plan_id', sa.Integer(), sa.ForeignKey('study_plan.id'), nullable=True),
            sa.Column('knowledge_point_id', sa.Integer(),
                      sa.ForeignKey('knowledge_point.id'), nullable=True),
            sa.Column('source', sa.String(10), nullable=False, server_default='manual'),
            sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('views', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('share_post_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("period_type IN ('day', 'week', 'month', 'stage', 'custom')",
                               name='_insight_period_ck'),
            sa.CheckConstraint("source IN ('manual', 'ai_draft')", name='_insight_source_ck'),
        )
        op.create_index('ix_insight_user_updated', INSIGHT, ['user_id', 'updated_at'])
        op.create_index('ix_insight_public', INSIGHT, ['is_public'])
        print('[0050] %s 已建（三段 + 周期归档 + 公开/分享）' % INSIGHT)
    else:
        print('[0050] %s 已存在（幂等跳过）' % INSIGHT)

    if not insp.has_table(DISPLAY):
        op.create_table(
            DISPLAY,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('cert_kind', sa.String(10), nullable=False),
            sa.Column('cert_id', sa.Integer(), nullable=False),
            sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('views', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('share_post_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("cert_kind IN ('system', 'module', 'social')",
                               name='_cert_display_kind_ck'),
            sa.UniqueConstraint('cert_kind', 'cert_id', name='uq_cert_display_kind_cert'),
        )
        op.create_index('ix_cert_display_user', DISPLAY, ['user_id'])
        op.create_index('ix_cert_display_public', DISPLAY, ['is_public'])
        print('[0050] %s 已建（证书展示态旁表）' % DISPLAY)
    else:
        print('[0050] %s 已存在（幂等跳过）' % DISPLAY)


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in (DISPLAY, INSIGHT):
        if not insp.has_table(table):
            print('[0050 downgrade] %s 不存在（幂等跳过）' % table)
            continue
        n = bind.execute(sa.text('SELECT COUNT(*) FROM %s' % table)).scalar()
        if n:
            raise RuntimeError(
                '[0050 downgrade] %s 还有 %d 行用户内容，删表等于删数据；请先备份再降级'
                % (table, n))
        for idx in ('ix_insight_user_updated', 'ix_insight_public',
                    'ix_cert_display_user', 'ix_cert_display_public'):
            if idx in {i['name'] for i in insp.get_indexes(table)}:
                op.drop_index(idx, table_name=table)
        op.drop_table(table)
        print('[0050 downgrade] %s 已删除' % table)
