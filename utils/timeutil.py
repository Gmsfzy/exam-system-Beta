# -*- coding: utf-8 -*-
"""时区统一工具：全系统时间约定
- 数据库：一律存 naive UTC（由 UTCDateTime TypeDecorator 保证读写转换）
- Python 层：一律 aware UTC（datetime.now(timezone.utc)）
- 展示/输入层：一律 Asia/Shanghai 墙上时间（中国自 1991 年无夏令时，固定 UTC+8，
  避免引入 pytz/tzdata 依赖）
"""
from datetime import datetime, timedelta, timezone

# 本地展示时区：中国标准时间（无夏令时）
LOCAL_TZ = timezone(timedelta(hours=8), 'Asia/Shanghai')


def utcnow():
    """当前时间：aware UTC（全系统唯一的「现在」来源）"""
    return datetime.now(timezone.utc)


def aware_min():
    """排序兜底用的 aware datetime.min（与 aware 时间比较/排序安全）"""
    return datetime.min.replace(tzinfo=timezone.utc)


def localtime(dt):
    """aware/naive(按 UTC 解释) -> Asia/Shanghai 墙上时间（aware）"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def iso_local(dt):
    """存储值 -> 本地时间 ISO 字符串（不带时区后缀，前端 new Date() 按本地解析）"""
    if dt is None:
        return None
    return localtime(dt).replace(tzinfo=None).isoformat()


def fmt_local(dt, fmt='%Y-%m-%d %H:%M'):
    """存储值 -> 本地时间字符串（API 序列化 / 前端展示用）"""
    local = localtime(dt)
    return local.strftime(fmt) if local else ''


def parse_dt(value, fmt=None):
    """用户输入 -> aware UTC（入库前统一口径）
    - 带时区（如前端 toISOString 的 ...Z）：按其时区转 UTC
    - 不带时区：按 Asia/Shanghai 墙上时间解释
    """
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        dt = value
    elif fmt:
        dt = datetime.strptime(value, fmt)
    else:
        dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc)


def current_season():
    """当前赛季键（按本地日历月 'YYYY-MM'）"""
    return localtime(utcnow()).strftime('%Y-%m')


def season_of(dt):
    """存储值 -> 所属赛季键（按本地日历月，赛季归属不能按 UTC 月切）"""
    local = localtime(dt)
    return local.strftime('%Y-%m') if local else current_season()
