# -*- coding: utf-8 -*-
"""RBAC 统一门禁行为矩阵（v4.7 收敛回归门）

utils.permissions.require_teacher 是 38 处散点收敛后的唯一实现，
覆盖迁移中用到的全部形态变体：
- 标准两段式：未登录 401 / 非教师 403
- bounty/competition 合并式：未登录也 403 同文案
- chapter_routes 历史 'error' 键变体
"""
import pytest

from utils import permissions


@pytest.fixture()
def patched(app, monkeypatch):
    """返回 setter：permissions.verify_token -> 指定 user（None=未登录）"""
    def setter(user):
        monkeypatch.setattr(permissions, 'verify_token', lambda: user)
        return user
    return setter


class TestRequireTeacher:
    def test_unauthorized_default_401(self, app, patched):
        patched(None)
        user, err = permissions.require_teacher()
        assert user is None
        resp, code = err
        assert code == 401
        assert resp.get_json() == {'message': '请先登录'}

    def test_unauthorized_403_variant(self, app, patched):
        """bounty/competition 合并式：未登录按原语义回落 403 同文案"""
        patched(None)
        user, err = permissions.require_teacher(
            deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
        assert user is None
        resp, code = err
        assert code == 403
        assert resp.get_json() == {'message': '无权访问'}

    def test_student_denied_with_custom_msg(self, app, patched, user_factory):
        stu = user_factory('rbac_stu', role='student')
        patched(stu)
        user, err = permissions.require_teacher(deny_msg='无权操作，仅教师可管理题库')
        assert user is None
        resp, code = err
        assert code == 403
        assert resp.get_json() == {'message': '无权操作，仅教师可管理题库'}

    def test_teacher_passes(self, app, patched, user_factory):
        tea = user_factory('rbac_tea', role='teacher')
        patched(tea)
        user, err = permissions.require_teacher(deny_msg='无权访问')
        assert err is None
        assert user.id == tea.id

    def test_error_key_variant(self, app, patched, user_factory):
        """chapter_routes 历史响应键 'error' 兼容"""
        patched(None)
        user, err = permissions.require_teacher(
            deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403, key='error')
        resp, code = err
        assert code == 403
        assert resp.get_json() == {'error': '无权访问'}


class TestLocalHelperDelegation:
    """4 份本地 _require_teacher 委托后返回形态与文案不回退"""

    def test_question_routes_delegate(self, app, patched, user_factory):
        from api.question_routes import _require_teacher
        patched(None)
        user, err = _require_teacher()
        assert user is None and err[1] == 401
        tea = user_factory('q_tea', role='teacher')
        patched(tea)
        user, err = _require_teacher()
        assert err is None and user.id == tea.id

    def test_competition_routes_delegate(self, app, patched, user_factory):
        from competition.routes import _require_teacher
        patched(None)
        user, err = _require_teacher()
        # competition 原语义：未登录也是 403 无权访问
        assert user is None and err[1] == 403
        assert err[0].get_json() == {'message': '无权访问'}
