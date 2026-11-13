"""AI 出题超时与重试策略回归

真机取证：当前方舟 endpoint 是推理模型（回复带 reasoning_content），5 道编程题
首次实测 74.2s、复测 93.2s，沿用 AI_TIMEOUT=60 必然每次掐断；而旧策略把读超时
也重试一次，用户要白等两倍时间才看到失败。本文件锁住四条容易回退的口径。
"""
import json

import pytest
import requests

from ai_service import client as client_mod
from ai_service.client import AIClient, AITimeoutError, AINetworkError
from ai_service.services import exam_timeout


class OkResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": '[{"content":"x","answer":"y"}]'}}]}


class Http401Resp:
    """密钥失效/被限流这类接口错误：不能被归进「答得慢」，也不该重试。"""
    status_code = 401

    def raise_for_status(self):
        raise requests.exceptions.HTTPError('401 Client Error: Unauthorized')

    def json(self):
        return {}


@pytest.fixture
def spy(monkeypatch):
    """拦下真实出站请求，记录每次生效的读超时；跑完由 monkeypatch 自动还原。"""
    calls = []

    def install(exc=None, resp=None):
        def fake_post(*a, **kw):
            calls.append(kw.get('timeout'))
            if exc:
                raise exc
            return resp if resp is not None else OkResp()
        monkeypatch.setattr(client_mod.requests, 'post', fake_post)
        calls.clear()
        return calls
    return install


def test_read_timeout_not_retried(spy):
    calls = spy(exc=requests.exceptions.ReadTimeout('read timed out'))
    with pytest.raises(AITimeoutError) as ei:
        AIClient()._post_ark({'max_tokens': 4000}, timeout=7)
    # 模型还在写，重发只会再等一个整超时并双倍消耗额度
    assert len(calls) == 1
    assert ei.value.seconds == 7   # 上层文案要能报出实际生效的超时值


def test_connect_timeout_goes_through_retry(spy):
    # ConnectTimeout 同时继承 Timeout 与 ConnectionError，分支顺序写错就会被读超时吃掉
    calls = spy(exc=requests.exceptions.ConnectTimeout('connect timed out'))
    with pytest.raises(AINetworkError):
        AIClient()._post_ark({'max_tokens': 4000}, timeout=7)
    assert len(calls) == AIClient().max_retries


def test_connection_error_retried(spy):
    calls = spy(exc=requests.exceptions.ConnectionError('refused'))
    with pytest.raises(AINetworkError):
        AIClient()._post_ark({'max_tokens': 4000}, timeout=7)
    assert len(calls) == AIClient().max_retries


def test_http_error_not_retried_and_keeps_reason(spy):
    calls = spy(resp=Http401Resp())
    with pytest.raises(AINetworkError) as ei:
        AIClient()._post_ark({'max_tokens': 4000}, timeout=7)
    assert len(calls) == 1
    assert '401' in str(ei.value)   # 密钥/限流线索不能丢


def test_success_passthrough(spy):
    calls = spy()
    raw = AIClient()._post_ark({'max_tokens': 4000}, timeout=7)
    assert len(calls) == 1
    assert json.loads(raw)[0]['answer'] == 'y'


@pytest.mark.parametrize('count,expected', [
    (1, 180), (5, 180), (6, 192), (10, 240), (20, 360),
])
def test_exam_timeout_formula(count, expected):
    """基准按 5 道计，超出部分每道 +12s；接口上限 20 道时约 360s。"""
    assert exam_timeout(count) == expected


def test_generate_question_passes_timeout(spy):
    """出题必须把算好的超时带到出站请求上——漏传就退回 60s，正是这次的故障形状。"""
    limit = exam_timeout(8)
    calls = spy()
    AIClient().generate_question('计算机科学与技术', 'programming', 'medium',
                                 count=8, timeout=limit)
    assert calls == [limit]


def test_waitress_channel_timeout_wired():
    """服务器层天花板已配置化（v7.16）：只加配置不接线 = 仍写死 120s，
    本机走 Werkzeug 测不出来，直到生产上大批量出题才断。"""
    import os
    from config import Config
    assert isinstance(Config.WAITRESS_CHANNEL_TIMEOUT, int)
    assert Config.WAITRESS_CHANNEL_TIMEOUT == int(os.getenv('WAITRESS_CHANNEL_TIMEOUT', '120'))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'app.py'), encoding='utf-8') as f:
        src = f.read()
    assert 'WAITRESS_CHANNEL_TIMEOUT' in src
    assert 'channel_timeout=chan_timeout' in src      # 严禁回退成硬编码字面量


def test_startup_warning_uses_same_formula():
    """启动告警里的出题上限必须与 exam_timeout 同公式：两处各写一份数字，
    改一处就静默失真（接口上限 20 道 → 360s）。"""
    import os
    from config import Config
    inline = (int(Config.AI_EXAM_TIMEOUT) + 15 * int(Config.AI_EXAM_EXTRA_PER_Q))
    assert exam_timeout(20) == inline
    assert exam_timeout(20) > exam_timeout(5)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'app.py'), encoding='utf-8') as f:
        src = f.read()
    assert 'AI_EXAM_EXTRA_PER_Q' in src               # 告警阈值走的是同一组配置项
