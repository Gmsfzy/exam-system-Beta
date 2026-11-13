"""v7.20 AI 输出留痕：新表 ai_ask_record + homework_answer 的 AI 建议三列

两处都是「把已经花出去的 AI 结果存下来」，语义同源，放一个迁移：
- ai_ask_record：AI 答疑的问答留痕。此前答疑只回不落，同一道错题反复点就反复烧额度与
  十几秒外呼；现在按「用户 + 题 + 疑问 + 作答」四元组指纹在窗口内复用上次的解析。
  刻意不复用 ai_usage_log：那张表是治理统计表（每次调用含 fail 都写一行、成本页整表扫），
  把 Text 正文塞进去会让统计查询拖着大字段跑；留痕与统计是两种读路径。
  question_id 外键取 ON DELETE SET NULL：删题路由只守了 ExamQuestion，被错题本引用过的
  题随时可能被删，NOT NULL 外键会把「删题」撞成 PG 外键错误；题面另存快照补可读性。
- homework_answer.ai_suggested_*：AI 批改建议留痕，供事后比对「AI 建议分 vs 教师终分」。
  三列全部可空（历史行没有建议、AI 失败时也不写），与 manual_score 互不覆盖。

⚠️ 方言可移植（v6.8 约束）：严禁 PRAGMA/sqlite_master；sa.inspect 判存在性，逐列判重，幂等跳过。

Revision ID: 0051_ai_ask_and_suggest
Revises: 0050_insight_cert_display
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = '0051_ai_ask_and_suggest'
down_revision = '0050_insight_cert_display'
branch_labels = None
depends_on = None

ASK = 'ai_ask_record'
ANSWER = 'homework_answer'
SUGGEST_COLS = ('ai_suggested_score', 'ai_suggested_comment', 'ai_suggested_at')


def upgrade():
    insp = sa.inspect(op.get_bind())

    if not insp.has_table(ASK):
        op.create_table(
            ASK,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=False),
            sa.Column('question_id', sa.Integer(),
                      sa.ForeignKey('question.id', ondelete='SET NULL'), nullable=True),
            sa.Column('question_content', sa.Text(), nullable=True),
            sa.Column('doubt', sa.Text(), nullable=True),
            sa.Column('student_answer', sa.Text(), nullable=True),
            sa.Column('analysis', sa.Text(), nullable=False),
            sa.Column('source', sa.String(10), nullable=False, server_default='ai'),
            sa.Column('fingerprint', sa.String(40), nullable=False),
            sa.Column('hit_count', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('last_hit_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("source IN ('ai', 'rule')", name='_ai_ask_source_ck'),
        )
        op.create_index('ix_ai_ask_user_fp', ASK, ['user_id', 'fingerprint'])
        op.create_index('ix_ai_ask_created', ASK, ['created_at'])
        print('[0051] %s 已建（答疑问答留痕 + 指纹复用）' % ASK)
    else:
        print('[0051] %s 已存在（幂等跳过）' % ASK)

    if insp.has_table(ANSWER):
        have = {c['name'] for c in insp.get_columns(ANSWER)}
        added = []
        for name, col in (
            ('ai_suggested_score', sa.Column('ai_suggested_score', sa.Float(), nullable=True)),
            ('ai_suggested_comment', sa.Column('ai_suggested_comment', sa.Text(), nullable=True)),
            ('ai_suggested_at', sa.Column('ai_suggested_at', sa.DateTime(), nullable=True)),
        ):
            if name in have:
                continue
            op.add_column(ANSWER, col)
            added.append(name)
        print('[0051] %s AI 建议列已补：%s' % (ANSWER, ', '.join(added) or '无（幂等跳过）'))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table(ANSWER):
        have = {c['name'] for c in insp.get_columns(ANSWER)}
        for name in SUGGEST_COLS:
            if name in have:
                op.drop_column(ANSWER, name)
        print('[0051 downgrade] %s AI 建议列已移除' % ANSWER)

    if not insp.has_table(ASK):
        print('[0051 downgrade] %s 不存在（幂等跳过）' % ASK)
        return
    n = bind.execute(sa.text('SELECT COUNT(*) FROM %s' % ASK)).scalar()
    if n:
        raise RuntimeError(
            '[0051 downgrade] %s 还有 %d 行答疑留痕，删表等于删数据；请先备份再降级' % (ASK, n))
    for idx in ('ix_ai_ask_user_fp', 'ix_ai_ask_created'):
        if idx in {i['name'] for i in insp.get_indexes(ASK)}:
            op.drop_index(idx, table_name=ASK)
    op.drop_table(ASK)
    print('[0051 downgrade] %s 已删除' % ASK)
