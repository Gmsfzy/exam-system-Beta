# -*- coding: utf-8 -*-
"""站内通知统一创建助手（v5.1 从 api/notification_routes 上移到 utils 层）

背景：create_notification 此前定义在 API 蓝图模块 api/notification_routes.py 内，
导致其余业务模块（竞赛/悬赏/作业/学习/考试）为规避循环 import，不得不在每个调用点
写一句函数内延迟 import。本模块把它收敛到 utils 稳定层：仅依赖 Notification 模型与
db，外部渠道投递仍延迟 import，任何业务模块都可在文件顶层直接
`from utils.notify import create_notification`，无循环依赖。

api/notification_routes.py 保留同名再导出，历史引用路径完全兼容。
"""
from database import db
from database.models import Notification


def create_notification(user_id, title, content='', type='info', related_type=None, related_id=None, commit=True):
    """创建通知助手函数。

    commit=True（默认）：立即提交，适合请求路径单次调用；
    commit=False：仅 add 不提交，由调用方在外层循环结束后统一 commit
    （如 scheduler 批量收卷，避免循环内逐行提交争抢写锁、提前半提交）。

    外部渠道旁路投递仅在 commit=True 且站内落库成功后触发（默认关闭、
    按 related_type 白名单、后台线程尽力而为）；commit=False 批量路径不投递，
    以免半提交误发与循环刷屏。
    """
    notification = Notification(
        user_id=user_id,
        title=title,
        content=content,
        type=type,
        related_type=related_type,
        related_id=related_id
    )
    db.session.add(notification)
    if commit:
        db.session.commit()
        # 站内落库成功后旁路投递邮件/webhook（默认关闭，异常不冒泡）
        from utils.notify_channels import dispatch
        dispatch(user_id, title, content, related_type)
    # 实时推送不在此处手动发：由 utils/notify_socket 的 ORM 事件在事务 commit 后统一
    # 自动发出（覆盖全模块与 commit=False 批量路径，且回滚不发、无幽灵推送）。
    return notification
