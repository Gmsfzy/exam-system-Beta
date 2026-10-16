# -*- coding: utf-8 -*-
"""全局通知实时推送（ORM 事件层，v5.0）。

设计目标：五大模块（在线考试 / 答题竞赛 / 征集悬赏 / 自主学习 / 作业练习）任何
产生站内通知的师生操作，对方都能通过 Socket.IO 即时收到 new_notification 推送，
无需在每个 create_notification 调用点逐一埋点。

实现方式：监听 Notification 的 ORM 事件——
- after_insert：通知行 INSERT 后（id / 默认值已就绪）序列化负载并暂存到当前 Session；
- after_commit：所属事务真正提交成功后，逐条推送到用户个人房间 user_{id}；
- after_rollback：事务回滚则丢弃暂存，杜绝「幽灵推送」。

因挂钩在 ORM 层，故无论走 create_notification（含 commit=True 单发与 commit=False
批量）还是任何直接 db.session.add(Notification(...))，只要最终 commit 落库即自动推送。
Socket.IO 未初始化 / 无客户端 / 推送异常均静默降级（前端仍有 30s 轮询兜底）。
"""
import logging

from sqlalchemy import event
from sqlalchemy.orm import Session, object_session

from database.models import Notification
from utils.timeutil import iso_local

logger = logging.getLogger(__name__)

# Session 实例上暂存待推送负载的属性名
_BUCKET = '_pending_notify_push'


def _serialize(n):
    """把通知行序列化为与 /api/notifications 一致的前端负载形状。"""
    from api.notification_routes import get_time_ago
    return {
        'id': n.id,
        'title': n.title,
        'content': n.content,
        'type': n.type,
        'read': bool(n.read),
        'related_type': n.related_type,
        'related_id': n.related_id,
        'created_at': iso_local(n.created_at),
        'time_ago': get_time_ago(n.created_at),
    }


def register_notification_push():
    """注册全局通知推送事件监听（幂等：重复注册前会先移除旧监听）。"""
    # 幂等：允许在测试/重载场景重复调用而不叠加
    for target, name, fn in (
        (Notification, 'after_insert', _after_insert),
        (Session, 'after_commit', _after_commit),
        (Session, 'after_rollback', _after_rollback),
    ):
        if not event.contains(target, name, fn):
            event.listen(target, name, fn)


@event.listens_for(Notification, 'after_insert')
def _after_insert(mapper, connection, target):
    """通知落库（INSERT 完成，id/默认值已就绪）：暂存负载，等待事务提交后推送。"""
    try:
        session = object_session(target)
        if session is None:
            return
        payload = (target.user_id, _serialize(target))
        bucket = getattr(session, _BUCKET, None)
        if bucket is None:
            bucket = []
            setattr(session, _BUCKET, bucket)
        bucket.append(payload)
    except Exception:
        logger.debug('[notify_socket] 暂存通知负载失败（非关键路径）', exc_info=True)


@event.listens_for(Session, 'after_commit')
def _after_commit(session):
    """事务真正提交成功：把本次提交产生的通知逐条实时推送到个人房间。"""
    bucket = getattr(session, _BUCKET, None)
    if not bucket:
        return
    setattr(session, _BUCKET, [])   # 先清空再推送，避免推送过程重入导致重复
    from competition.realtime import notify_user
    for user_id, payload in bucket:
        try:
            notify_user(user_id, 'new_notification', payload)
        except Exception:
            logger.debug('[notify_socket] 推送 new_notification 失败（降级轮询）', exc_info=True)


@event.listens_for(Session, 'after_rollback')
def _after_rollback(session):
    """事务回滚：丢弃未落库通知的待推送负载，杜绝幽灵推送。"""
    if getattr(session, _BUCKET, None):
        setattr(session, _BUCKET, [])
