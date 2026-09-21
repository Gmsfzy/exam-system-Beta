# -*- coding: utf-8 -*-
"""v4.6.1 低危修复回归门：JWT 吊销水位（token_valid_at）与签发 iat。"""
import datetime as dt

import jwt
import pytest

from api.auth_routes import generate_token
from config import Config
from database import db
from utils.security import verify_token
from utils.timeutil import utcnow


def _verify_with(token):
    from flask import current_app
    with current_app.test_request_context(
            '/api/ping', headers={'Authorization': f'Bearer {token}'}):
        return verify_token()


def test_token_carries_iat(app, user_factory):
    u = user_factory('tok1')
    payload = jwt.decode(generate_token(u), Config.SECRET_KEY, algorithms=['HS256'])
    assert 'iat' in payload and isinstance(payload['iat'], int)


def test_valid_token_without_watermark(app, user_factory):
    u = user_factory('tok2')
    assert _verify_with(generate_token(u)) is not None


def test_revocation_watermark_blocks_older_token(app, user_factory):
    u = user_factory('tok3')
    token = generate_token(u)
    u.token_valid_at = utcnow().replace(microsecond=0) + dt.timedelta(seconds=1)
    db.session.commit()
    assert _verify_with(token) is None        # 登出前签发的旧票即时失效


def test_watermark_allows_newer_token(app, user_factory):
    u = user_factory('tok4')
    u.token_valid_at = utcnow().replace(microsecond=0) - dt.timedelta(seconds=10)
    db.session.commit()
    assert _verify_with(generate_token(u)) is not None  # 水位之后签发可用


def test_same_second_boundary_not_killed(app, user_factory):
    """水位对齐整秒语义：iat == 水位 的 token 必须可用（登出后同秒重登不误杀）。"""
    u = user_factory('tok5')
    token = generate_token(u)
    iat = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])['iat']
    u.token_valid_at = dt.datetime.fromtimestamp(iat, tz=dt.timezone.utc)
    db.session.commit()
    assert _verify_with(token) is not None    # issued < valid_at 才吊销，相等放行


def test_legacy_token_without_iat_revoked_after_logout(app, user_factory):
    u = user_factory('tok6')
    legacy = jwt.encode({'user_id': u.id, 'exp': utcnow() + dt.timedelta(days=1)},
                        Config.SECRET_KEY, algorithm='HS256')
    assert _verify_with(legacy) is not None   # 未登出：无 iat 历史票仍可用
    u.token_valid_at = utcnow().replace(microsecond=0)
    db.session.commit()
    assert _verify_with(legacy) is None       # 登出后：无 iat 一律视为失效


def test_bogus_token_returns_none(app):
    assert _verify_with('not-a-jwt') is None
