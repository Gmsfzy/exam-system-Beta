# -*- coding: utf-8 -*-
"""通知外部渠道旁路投递：站内通知落库后，按配置把「重要事件」镜像投递到
邮件（收件人本人）与/或企业微信/钉钉群机器人 webhook。

设计约束（对齐 utils.security/调度器的健壮性风格）：
- 默认关闭：NOTIFY_EXTERNAL_ENABLED=false 时零副作用，不查库、不起线程。
- 事件白名单：仅 NOTIFY_EXTERNAL_RELATED_TYPES 内的 related_type 才外发，
  默认只放 result（成绩公布），避免「考试发布群发全体学生」造成刷屏/限流。
- 尽力而为 + 后台线程：SMTP/HTTP 均在守护线程执行，失败仅记日志，绝不冒泡
  影响 create_notification 主流程与请求响应。
- 无数据库依赖：进入投递线程前已取好收件邮箱与配置快照，线程内不碰 session。
"""
import threading
import smtplib
from email.message import EmailMessage

from utils.logger import logger

# 群机器人载荷构建：按 kind 选择 JSON 结构；均取纯文本正文
_WEBHOOK_BUILDERS = {
    'generic': lambda text: {'content': text},
    'wechat': lambda text: {'msgtype': 'text', 'text': {'content': text}},
    'dingtalk': lambda text: {'msgtype': 'text', 'text': {'content': text}},
}


def _allowed_related_types():
    from flask import current_app
    raw = current_app.config.get('NOTIFY_EXTERNAL_RELATED_TYPES', 'result')
    return {t.strip() for t in (raw or '').split(',') if t.strip()}


def should_dispatch(related_type):
    """是否值得外发：总开关开启 且 事件类型在白名单内。"""
    from flask import current_app
    if not current_app.config.get('NOTIFY_EXTERNAL_ENABLED', False):
        return False
    return (related_type or '') in _allowed_related_types()


def _build_text(title, content):
    return f'{title}\n{content}' if content else title


def _deliver(email_to, subject, text, cfg):
    """真正执行投递（在守护线程内调用）：邮件 + webhook，各自独立尽力而为。"""
    if email_to and cfg.get('smtp_host'):
        _send_email(email_to, subject, text, cfg)
    if cfg.get('webhook_url'):
        _send_webhook(text, cfg)


def _send_email(email_to, subject, text, cfg):
    try:
        msg = EmailMessage()
        msg['From'] = cfg.get('smtp_from') or cfg.get('smtp_user') or ''
        msg['To'] = email_to
        msg['Subject'] = subject
        msg.set_content(text)

        host, port = cfg['smtp_host'], cfg['smtp_port']
        if cfg.get('smtp_ssl'):
            server_cls = smtplib.SMTP_SSL
        else:
            server_cls = smtplib.SMTP
        with server_cls(host, port, timeout=10) as server:
            if not cfg.get('smtp_ssl') and cfg.get('smtp_starttls'):
                server.starttls()
            if cfg.get('smtp_user'):
                server.login(cfg['smtp_user'], cfg.get('smtp_password', ''))
            server.send_message(msg)
        logger.info(f'[notify_channel] 邮件已发送 -> {email_to}: {subject}')
    except Exception as e:  # noqa: BLE001 尽力而为，不外抛
        logger.warning(f'[notify_channel] 邮件发送失败 -> {email_to}: {e}')


def _send_webhook(text, cfg):
    try:
        import requests
        kind = cfg.get('webhook_kind', 'generic')
        builder = _WEBHOOK_BUILDERS.get(kind, _WEBHOOK_BUILDERS['generic'])
        resp = requests.post(cfg['webhook_url'], json=builder(text), timeout=10)
        resp.raise_for_status()
        logger.info(f'[notify_channel] webhook({kind}) 已投递')
    except Exception as e:  # noqa: BLE001 尽力而为，不外抛
        logger.warning(f'[notify_channel] webhook 投递失败: {e}')


def _snapshot_config():
    from flask import current_app
    c = current_app.config
    return {
        'smtp_host': c.get('NOTIFY_SMTP_HOST'),
        'smtp_port': int(c.get('NOTIFY_SMTP_PORT', 465)),
        'smtp_user': c.get('NOTIFY_SMTP_USER'),
        'smtp_password': c.get('NOTIFY_SMTP_PASSWORD'),
        'smtp_from': c.get('NOTIFY_SMTP_FROM'),
        'smtp_ssl': c.get('NOTIFY_SMTP_SSL', True),
        'smtp_starttls': c.get('NOTIFY_SMTP_STARTTLS', False),
        'webhook_url': c.get('NOTIFY_WEBHOOK_URL'),
        'webhook_kind': c.get('NOTIFY_WEBHOOK_KIND', 'generic'),
    }


def dispatch(user_id, title, content, related_type):
    """站内通知落库后调用：满足条件则在守护线程后台外发，主流程零阻塞、零异常。

    必须在可访问 current_app 与 db.session 的上下文中调用（请求/调度均可）。
    """
    try:
        if not should_dispatch(related_type):
            return
        cfg = _snapshot_config()
        email_to = _user_email(user_id)
        subject = title
        text = _build_text(title, content)
        if not email_to and not cfg.get('webhook_url'):
            return
        t = threading.Thread(
            target=_deliver, args=(email_to, subject, text, cfg),
            daemon=True, name='notify-channel')
        t.start()
    except Exception as e:  # noqa: BLE001 旁路投递绝不影响主流程
        logger.warning(f'[notify_channel] 投递调度异常（已忽略）: {e}')


def _user_email(user_id):
    from database import db
    from database.models import User
    u = db.session.get(User, user_id)
    return (u.email or None) if u else None
