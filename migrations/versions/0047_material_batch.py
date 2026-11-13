"""v7.9 批量讲义生成：study_material 加 plan_id/task_id + 新表 material_gen_job

- study_material.plan_id/task_id：把 AI 生成的文档显式挂回学习计划条目。
  不靠 knowledge_point_id 反查的原因：practice/custom 型任务没有 KP（AI 给的 kp_id
  不在白名单时会被强制降为 custom 并置 None），反查会静默漏挂；跨计划共用同一
  知识点时还会串档。两列均可空，存量手写资料不受影响。
- material_gen_job：批量队列行（一条任务一行），状态机 pending/running/done/failed
  以 DB 列为唯一事实源，对齐 oj/queue.py，不引外部 MQ。队列与成品分表，避免
  半成品污染资料库/公开广场/收藏/举报那几条都没过滤"生成中"的查询路径。

⚠️ 方言可移植（v6.8 约束）：严禁 PRAGMA/sqlite_master；用 sa.inspect 判存在性，
add_column/create_table 全部幂等跳过，存量行靠 server_default 回填。

Revision ID: 0047_material_batch
Revises: 6ee25575ae44
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = '0047_material_batch'
down_revision = '6ee25575ae44'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # 1) 成品表加关联列
    cols = _columns(bind, 'study_material')
    for name in ('plan_id', 'task_id'):
        if name not in cols:
            op.add_column('study_material', sa.Column(name, sa.Integer(), nullable=True))
            print('[0047] study_material.%s 已添加' % name)
        else:
            print('[0047] study_material.%s 已存在（幂等跳过）' % name)
    if 'ix_material_plan' not in {i['name'] for i in insp.get_indexes('study_material')}:
        op.create_index('ix_material_plan', 'study_material', ['plan_id'])
        print('[0047] ix_material_plan 已建')

    # 2) 队列表
    if not insp.has_table('material_gen_job'):
        op.create_table(
            'material_gen_job',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('batch_id', sa.String(32), nullable=False),
            sa.Column('plan_id', sa.Integer(), sa.ForeignKey('study_plan.id'), nullable=False),
            sa.Column('task_id', sa.Integer(), sa.ForeignKey('study_plan_task.id'), nullable=False),
            sa.Column('kind', sa.String(20), nullable=False, server_default='mindmap'),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('prompt', sa.String(500), nullable=False),
            sa.Column('subject', sa.String(50), nullable=True),
            sa.Column('difficulty', sa.String(20), nullable=True),
            sa.Column('knowledge_point_id', sa.Integer(),
                      sa.ForeignKey('knowledge_point.id'), nullable=True),
            sa.Column('status', sa.String(12), nullable=False, server_default='pending'),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('material_id', sa.Integer(),
                      sa.ForeignKey('study_material.id'), nullable=True),
            sa.Column('error', sa.String(200), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False,
                      server_default=sa.func.now()),
            sa.CheckConstraint("status IN ('pending', 'running', 'done', 'failed')",
                               name='_material_job_status_ck'),
        )
        op.create_index('ix_material_job_status', 'material_gen_job', ['status'])
        op.create_index('ix_material_job_batch', 'material_gen_job', ['batch_id'])
        op.create_index('ix_material_job_user_created', 'material_gen_job',
                        ['user_id', 'created_at'])
        print('[0047] material_gen_job 已建（含 3 索引）')
    else:
        print('[0047] material_gen_job 已存在（幂等跳过）')


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table('material_gen_job'):
        for idx in ('ix_material_job_user_created', 'ix_material_job_batch',
                    'ix_material_job_status'):
            if idx in {i['name'] for i in insp.get_indexes('material_gen_job')}:
                op.drop_index(idx, table_name='material_gen_job')
        op.drop_table('material_gen_job')
        print('[0047 downgrade] material_gen_job 已删除')
    cols = _columns(bind, 'study_material')
    if 'ix_material_plan' in {i['name'] for i in insp.get_indexes('study_material')}:
        op.drop_index('ix_material_plan', table_name='study_material')
    with op.batch_alter_table('study_material') as batch_op:
        for name in ('task_id', 'plan_id'):
            if name in cols:
                batch_op.drop_column(name)
    print('[0047 downgrade] study_material 关联列已删除')
