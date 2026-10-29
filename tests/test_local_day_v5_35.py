# -*- coding: utf-8 -*-
"""「今天」口径统一回归门（v5.35）

背景：生产代码里业务「今天」曾混用 `utcnow().date()`（UTC 日）与 `date.today()`
（跑测试/部署机的本地日）。上海用户日历与 UTC 日在 00:00–07:59（= UTC 16:00–23:59）
这 8 小时窗口里差一天，表现为：打卡/连击日界落在上海 08:00、逾期任务晚 8 小时标红、
今日专注时长窗口错位、AI 日配额在 08:00 重置。

锁定口径：
1. `local_date()` 把存储值（naive/aware UTC）折到上海日历日，跨本地午夜归对当天；
2. `local_today()` 恒等于 `local_date(utcnow())`，且永不早于 UTC 日；
3. `local_day_start()` 与 `local_date()` 互逆： instant ∈ [start, start+1d)；
4. 打卡写入的 day、连击回溯、近 7 天热力、逾期判定、AI 日配额重置都按上海日；
5. 日窗口（今日专注时长）下界为上海 00:00 对应的 UTC 时刻，与打卡同一口径。

时钟冻结：monkeypatch `utils.timeutil.utcnow`（local_today/local_date 都在 timeutil
内部取「现在」，业务模块只引用 helper，因此一处替换即可全局钉住），把「现在」定在
上海 01:30（UTC 前一天 17:30）——正是新旧口径必然不同的那一档。
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from database import db
from utils.timeutil import (LOCAL_TZ, local_date, local_day_start, local_today,
                            localtime, utcnow)

UTC = timezone.utc
# 冻结点：上海 2026-10-29 01:30 = UTC 2026-10-28 17:30（UTC 日与本地日不同的窗口）
FROZEN_UTC = datetime(2026, 10, 28, 17, 30, tzinfo=UTC)


@pytest.fixture()
def frozen_clock(monkeypatch):
    """把 timeutil 的「现在」钉在 FROZEN_UTC，返回 (UTC 日, 上海日)。"""
    import utils.timeutil as tu
    monkeypatch.setattr(tu, 'utcnow', lambda: FROZEN_UTC)
    return FROZEN_UTC.date(), tu.local_today()


# ─────────────────── 一、helper 语义（纯函数，固定时刻） ───────────────────

def test_local_date_crosses_local_midnight():
    """UTC 16:00 之后本地已跨天：必须归到次日，而不是 dt.date() 的 UTC 日。"""
    assert local_date(datetime(2026, 10, 28, 15, 59, 59, tzinfo=UTC)) == date(2026, 10, 28)
    assert local_date(datetime(2026, 10, 28, 16, 0, 0, tzinfo=UTC)) == date(2026, 10, 29)
    assert local_date(datetime(2026, 10, 28, 23, 59, tzinfo=UTC)) == date(2026, 10, 29)
    assert local_date(datetime(2026, 10, 29, 7, 59, tzinfo=UTC)) == date(2026, 10, 29)
    # 数据库里 UTCDateTime 读出来是 naive UTC，同样按 UTC 解释
    assert local_date(datetime(2026, 10, 28, 16, 30)) == date(2026, 10, 29)
    assert local_date(None) is None


def test_local_date_never_earlier_than_utc_day():
    """一天 24 个采样点：上海日 ≥ UTC 日，且 UTC 16 点起恰好 +1 天。"""
    for hour in range(24):
        inst = datetime(2026, 10, 28, hour, 30, tzinfo=UTC)
        expect = date(2026, 10, 29) if hour >= 16 else date(2026, 10, 28)
        assert local_date(inst) == expect
        assert local_date(inst) >= inst.date()


def test_local_day_start_anchor_and_invertibility():
    """上海日历日 -> 该日 00:00 的 UTC 时刻（前一天 16:00），且与 local_date 互逆。"""
    assert local_day_start(date(2026, 10, 29)) == datetime(2026, 10, 28, 16, 0, tzinfo=UTC)
    assert local_day_start(date(2026, 10, 29)).tzinfo == UTC
    for hour in range(0, 48, 3):
        inst = datetime(2026, 10, 28, 5, 0, tzinfo=UTC) + timedelta(hours=hour)
        start = local_day_start(local_date(inst))
        assert start <= inst < start + timedelta(days=1)
        assert local_date(start) == local_date(inst)
        assert start.astimezone(LOCAL_TZ).time().hour == 0


def test_local_today_contract():
    """local_today() == local_date(utcnow())，且日窗口的上下界把「现在」夹在中间。"""
    now = utcnow()
    today = local_date(now)
    assert local_today() == today or abs((local_today() - today).days) <= 1  # 跨日瞬间容差
    start = local_day_start(today)
    assert start <= now < start + timedelta(days=1)
    assert localtime(now).utcoffset() == timedelta(hours=8)


# ─────────────── 二、打卡 / 连击 / 近 7 天（冻结在跨日窗口） ───────────────

def test_checkin_writes_local_day(app, user_factory, frozen_clock):
    """上海 01:30 打卡必须记在当天：老口径 utcnow().date() 会写成昨天。"""
    from api.learning_engine import touch_checkin
    from database.models import StudyCheckin
    utc_day, local_day = frozen_clock
    assert utc_day != local_day            # 冻结点确实落在两日相差的窗口内
    u = user_factory('ld_checkin')
    c = touch_checkin(u.id, minutes=20, tasks_delta=1)
    assert c.day == local_day and c.minutes == 20 and c.tasks_done == 1
    # 同日幂等 upsert：再打一次不新增行，分钟累加
    c2 = touch_checkin(u.id, minutes=10)
    assert c2.id == c.id and c2.minutes == 30
    assert StudyCheckin.query.filter_by(user_id=u.id).count() == 1


def test_streak_counts_backwards_from_local_day(app, user_factory, frozen_clock):
    """连击按上海日回溯：今+昨（本地日）=2，断一天即断连。"""
    from api.learning_engine import compute_streak, week_checkin_days
    from database.models import StudyCheckin
    _, local_day = frozen_clock
    u = user_factory('ld_streak')
    for offset, minutes in ((0, 15), (1, 20), (3, 5)):
        db.session.add(StudyCheckin(user_id=u.id, day=local_day - timedelta(days=offset),
                                    minutes=minutes, tasks_done=0))
    db.session.commit()
    assert compute_streak(u.id, local_day) == 2
    week = week_checkin_days(u.id, local_day)
    assert set(week) == {(local_day - timedelta(days=n)).isoformat() for n in (0, 1, 3)}
    assert week[local_day.isoformat()]['minutes'] == 15


# ─────────────── 三、计划的逾期与热力（冻结在跨日窗口） ───────────────

def _mk_plan(user, due_offset, done_at=None):
    from database.models import StudyPlan, StudyPlanTask
    plan = StudyPlan(user_id=user.id, title='口径计划', start_date=local_today(),
                     end_date=local_today() + timedelta(days=10), status='active')
    db.session.add(plan)
    db.session.flush()
    task = StudyPlanTask(plan_id=plan.id, title='任务A', task_type='custom', order_num=1,
                         due_date=local_today() + timedelta(days=due_offset),
                         status='pending')
    if done_at is not None:
        task.status = 'done'
        task.done_at = done_at
    db.session.add(task)
    db.session.commit()
    return plan, task


def test_overdue_flag_uses_local_day(app, user_factory, frozen_clock):
    """到期日=本地日的前一天：上海 01:30 就该标红（老口径要等到 08:00 才标）。"""
    from api.learning_routes import _task_to_dict
    _, local_day = frozen_clock
    u = user_factory('ld_overdue')
    plan, task = _mk_plan(u, -1)
    assert task.due_date == local_day - timedelta(days=1)
    assert _task_to_dict(task)['overdue'] is True


def test_due_today_not_overdue(app, user_factory, frozen_clock):
    """到期日=本地当天：仍是今天到期，不得提前标红。"""
    from api.learning_routes import _task_to_dict
    _, local_day = frozen_clock
    u = user_factory('ld_today')
    plan, task = _mk_plan(u, 0)
    assert task.due_date == local_day
    assert _task_to_dict(task)['overdue'] is False


def test_heat_and_window_bucket_by_local_day(app, user_factory, frozen_clock):
    """本地今天 01:30 完成的任务归今天的格子；日窗口下界同为上海 00:00。"""
    from api.learning_routes import _plan_to_dict
    utc_day, local_day = frozen_clock
    u = user_factory('ld_heat')
    done_at = local_day_start(local_day) + timedelta(hours=1, minutes=30)
    assert done_at.date() == utc_day                 # UTC 侧还算昨天
    plan, task = _mk_plan(u, 3, done_at=done_at)
    body = _plan_to_dict(plan)
    assert body['heat'] == {local_day.isoformat(): 1}
    assert body['tasks_done'] == 1 and body['overdue_count'] == 0
    # 今日专注窗口（learning_routes 的 day_start）：该时刻必须落在窗口内
    start = local_day_start(local_today())
    assert start <= done_at < start + timedelta(days=1)


# ─────────────── 四、AI 日配额按上海日惰性重置 ───────────────

def test_ai_quota_resets_on_local_day(app, user_factory, frozen_clock):
    """reset_date 存的是昨天（UTC 日口径的旧值）：本地跨天后当天即重置额度。"""
    from ai_service.gate import check_ai_quota, get_quota_info
    from database.models import AiQuota
    utc_day, local_day = frozen_clock
    u = user_factory('ld_quota')
    db.session.add(AiQuota(user_id=u.id, daily_limit=5, used_today=5, reset_date=utc_day))
    db.session.commit()
    assert get_quota_info(u)['used_today'] == 0      # 已是新的一天，不该继续算满
    allowed, quota = check_ai_quota(u)
    assert allowed is True and quota.reset_date == local_day and quota.used_today == 0
