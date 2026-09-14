# -*- coding: utf-8 -*-
"""自定义列类型"""
import json
from datetime import timezone

from sqlalchemy import DateTime, Text, TypeDecorator


class UTCDateTime(TypeDecorator):
    """全系统 DateTime 列的统一自定义类型
    - 写入：aware -> 转 naive UTC 落库（SQLite 本就不存时区，存储格式不变）
    - 读取：naive -> 补成 aware UTC（此后代码层不再出现 naive 时间）
    - 兼容：naive 写入视为已是 UTC（历史数据归一化由 Alembic 0002 完成）
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value


class JSONType(TypeDecorator):
    """JSON 字段类型（底层 TEXT 存储，兼容 SQLite）。
    - 写入 dict/list → 自动 json.dumps；写入 JSON 字符串 → 原样落库
    - 读取 → 自动 json.loads 为 Python 对象；解析失败则返回原字符串
    - 兼容历史数据：原 TEXT 列中存的 JSON 字符串可直接被反序列化
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return value  # 已序列化的 JSON 字符串，直接落库
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return value
        return value
