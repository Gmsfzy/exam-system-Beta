# -*- coding: utf-8 -*-
"""v4.6.1 中危修复回归门：限流存储 URI 派生（显式优先 → 跟随 Redis → 回落 memory）。

Config 在 import 时求值，用 importlib.reload + monkeypatch env 验证三种组合。
v5.29 起 config 会 load_dotenv(override=True) 强读项目 .env：本机存在 .env（如
REDIS_HOST=127.0.0.1）时会覆盖测试意图，故 reload 前空转 dotenv，只测派生逻辑。
"""
import importlib


def _reload_with(monkeypatch, env):
    import dotenv
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *a, **k: False)
    for k in ('RATE_LIMIT_STORAGE_URI', 'REDIS_HOST', 'REDIS_PORT',
              'REDIS_PASSWORD', 'REDIS_DB'):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config as config_mod
    importlib.reload(config_mod)
    return config_mod.Config.RATE_LIMIT_STORAGE_URI


def test_default_memory(monkeypatch):
    assert _reload_with(monkeypatch, {}) == 'memory://'


def test_explicit_uri_wins(monkeypatch):
    uri = _reload_with(monkeypatch, {
        'RATE_LIMIT_STORAGE_URI': 'redis://explicit:6380/9',
        'REDIS_HOST': 'should-be-ignored',
    })
    assert uri == 'redis://explicit:6380/9'


def test_follows_redis_host(monkeypatch):
    uri = _reload_with(monkeypatch, {
        'REDIS_HOST': '10.0.0.2', 'REDIS_PORT': '6380', 'REDIS_DB': '2',
    })
    assert uri == 'redis://10.0.0.2:6380/2'


def test_redis_password_escaped_with_colon_prefix(monkeypatch):
    """密码段必须 ":" + quote_plus(pw) + "@" ——缺冒号会被解析成用户名（曾经的 bug）。"""
    uri = _reload_with(monkeypatch, {
        'REDIS_HOST': 'h', 'REDIS_PASSWORD': 'p@ss',
    })
    assert uri == 'redis://:p%40ss@h:6379/0'
