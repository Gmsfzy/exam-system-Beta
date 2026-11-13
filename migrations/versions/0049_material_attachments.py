"""v7.18 资料附件：study_material 加 attachment_json 一列

用户在资料库里不只能读 AI 生成的 markdown，还要能自己挂东西进来：Word/Excel/PPT/PDF
文档、站外链接、视频、图片、思维导图文件（XMind/百度脑图导出的 html、markdown 版导图）。

为什么是一列 JSON 而不是一张 material_attachment 表：附件是资料的附属展示物，没有
独立查询、独立权限、独立统计的需求；建表要多背一套实时镜像对账 + 删资料级联清理
（v7.9 那次 plan_id/task_id 外键的反向引用坑就是现成的教训）。结构对齐 v4.6 的
study_note.attachment_json，同一套 uploads/ 白名单与落盘逻辑。

列类型用 TEXT：ORM 侧是 JSONType(impl=Text)，PG 与 SQLite 两边都是 TEXT，与 0015
的 attachment_json 同口径，避免 PG 上多出一种 JSON 类型让镜像重建对不上列结构。

方言可移植（v6.8 约束）：不写 PRAGMA，用 sa.inspect 判存在性，add_column 幂等跳过。

Revision ID: 0049_material_attachments
Revises: 0048_material_lesson_plan
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = '0049_material_attachments'
down_revision = '0048_material_lesson_plan'
branch_labels = None
depends_on = None

TABLE = 'study_material'
COLUMN = 'attachment_json'


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(TABLE)}


def upgrade():
    bind = op.get_bind()
    if COLUMN in _columns(bind):
        print('[0049] %s.%s 已存在（幂等跳过）' % (TABLE, COLUMN))
        return
    op.add_column(TABLE, sa.Column(COLUMN, sa.Text(), nullable=True))
    print('[0049] %s.%s 已添加' % (TABLE, COLUMN))


def downgrade():
    bind = op.get_bind()
    if COLUMN not in _columns(bind):
        print('[0049 downgrade] %s.%s 不存在（幂等跳过）' % (TABLE, COLUMN))
        return
    n = bind.execute(sa.text("SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL"
                             % (TABLE, COLUMN))).scalar()
    if n:
        raise RuntimeError(
            '[0049 downgrade] 还有 %d 份资料带附件，删列会连带丢掉这些引用（文件本体仍在 '
            'uploads/，但无人索引）；请先清空附件再降级' % n)
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_column(COLUMN)
    print('[0049 downgrade] %s.%s 已删除' % (TABLE, COLUMN))
