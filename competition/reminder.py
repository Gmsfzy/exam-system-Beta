# -*- coding: utf-8 -*-
"""开赛提醒：临近开赛的竞赛向已报名选手推送通知（由 scheduler 每 60s 调用）。

幂等：以 competition.remind_sent_at 作为"已提醒"标记，单场只发一次。
机器人账号（role='bot'）永不收件。
"""
from datetime import timedelta

from database import db
from database.models import User
from utils.timeutil import utcnow, fmt_local
from utils.notify import create_notification
from competition.models import (
    Competition, CompetitionParticipant, CompetitionStatusEnum,
)


def send_competition_reminders():
    """扫描处于开赛提醒窗口内的竞赛，向报名者批量发通知并置提醒标记。"""
    now = utcnow()
    comps = (Competition.query
             .filter(Competition.remind_before > 0,
                     Competition.remind_sent_at.is_(None),
                     Competition.status.in_([CompetitionStatusEnum.PUBLISHED,
                                             CompetitionStatusEnum.ONGOING]))
             .all())
    for comp in comps:
        try:
            lead = timedelta(minutes=comp.remind_before or 0)
            # 仅在 [now, now + remind_before] 开窗且尚未开赛时提醒
            if not (comp.start_time > now and comp.start_time <= now + lead):
                continue
            _remind_one(comp, now)
        except Exception:
            db.session.rollback()
            continue


def _remind_one(comp, now):
    rows = (db.session.query(CompetitionParticipant.user_id)
            .join(User, User.id == CompetitionParticipant.user_id)
            .filter(CompetitionParticipant.competition_id == comp.id,
                    User.role != 'bot').all())
    when = fmt_local(comp.start_time)
    for (uid,) in rows:
        create_notification(
            user_id=uid, title='竞赛即将开始',
            content=f'「{comp.title}」将于 {when} 开赛，快去应战吧。',
            type='info', related_type='competition', related_id=comp.id,
            commit=False)
    comp.remind_sent_at = now
    db.session.commit()
