# -*- coding: utf-8 -*-
"""v7.6 便携 Redis 语义回归门。

覆盖三条不可让步的语义（详见 utils/redis_portable.py 模块文档）：
复用优先不启第二实例、端口避让要传到限流层、任何失败都只降级不拒起。
全部用假 cfg / 假 exe，绝不改动真实 Config，也不要求本机装有 Redis。
"""
import json
import os
import socket
import sys
import threading
from types import SimpleNamespace

import pytest

import utils.redis_portable as rp


# ────────────────────────── 测试脚手架 ──────────────────────────
def _cfg(tmp_path, **kw):
    """假 Config：只带本模块会读的字段，避免测试去动真实 Config。"""
    base = dict(
        APP_DIR=str(tmp_path),
        REDIS_HOST='127.0.0.1', REDIS_PORT=6379, REDIS_DB=0,
        REDIS_PASSWORD='', REDIS_BACKEND='auto',
        REDIS_SERVER_PATH='', REDIS_PORTABLE_DIR=str(tmp_path / 'tools' / 'redis'),
        REDIS_PORTABLE_DATA=str(tmp_path / 'instance' / 'redis'),
        REDIS_ALT_PORTS=[6380, 6381, 6382], REDIS_START_TIMEOUT=5,
        REDIS_AUTO_START=True,
        RATE_LIMIT_STORAGE_URI='redis://127.0.0.1:6379/0',
        RATE_LIMIT_URI_EXPLICIT=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    """占位用的 TCP 监听：既能造出「端口被人占了」，也能造出「会答 PING 的 Redis」。"""

    def __init__(self, reply=None):
        self.reply = reply
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.recv(64)
                    if self.reply is not None:
                        conn.sendall(self.reply)
                except OSError:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._stop.set()
        self.sock.close()


STUB = r'''
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
s.bind(('127.0.0.1', port))
s.listen(8)
while True:
    c, _ = s.accept()
    with c:
        c.recv(64)
        c.sendall(b'+PONG\r\n')
'''


@pytest.fixture()
def stub_exe(tmp_path):
    """替身 redis-server：一个会答 RESP PING 的 python 脚本（真正的进程语义照样跑得通）。

    真实 redis-server.exe 需自行下载 Redis-8.x-Windows-x64-msys2.zip 解压到 tools/redis/，
    测试不能依赖网络产物，故用替身覆盖 spawn/就绪等待/关停这条链。
    """
    p = tmp_path / 'fake_redis_server.py'
    p.write_text(STUB, encoding='utf-8')
    return str(p)


# ────────────────────────── 二进制发现 ──────────────────────────
def test_find_server_prefers_explicit_path(tmp_path):
    exe = tmp_path / 'mine.exe'
    exe.write_text('', encoding='utf-8')
    cfg = _cfg(tmp_path, REDIS_SERVER_PATH=str(exe))
    assert rp.find_server(cfg) == str(exe)


def test_find_server_picks_project_portable_dir(tmp_path):
    """zip 解压常多套一层目录，根目录/bin/子目录/单层同名目录都要能发现。"""
    cfg = _cfg(tmp_path)
    nested = tmp_path / 'tools' / 'redis' / 'Redis-8.0.1-Windows-x64-msys2'
    nested.mkdir(parents=True)
    target = nested / 'redis-server.exe'
    target.write_text('', encoding='utf-8')
    assert rp.find_server(cfg) == str(target)


def test_find_server_returns_none_without_binary_and_empty_path(tmp_path, monkeypatch):
    """没二进制必须返回 None 而不是抛异常——上层据此降级 fake 缓存。"""
    monkeypatch.setattr(rp.shutil, 'which', lambda name: None)
    cfg = _cfg(tmp_path)
    assert rp.find_server(cfg) is None


# ────────────────────────── 端口三态探活 ──────────────────────────
def test_probe_free_only_on_explicit_refuse(monkeypatch):
    """只有明确被拒才算空口。"""
    def _refused(addr, timeout=None):
        raise ConnectionRefusedError()
    monkeypatch.setattr(rp.socket, 'create_connection', _refused)
    assert rp.probe('127.0.0.1', 6399) == 'free'


def test_probe_connect_timeout_is_not_free(monkeypatch):
    """连过去超时（防火墙丢包/口被人占着）不能算 free。"""
    def _hang(addr, timeout=None):
        raise socket.timeout()
    monkeypatch.setattr(rp.socket, 'create_connection', _hang)
    assert rp.probe('127.0.0.1', 6399) == 'occupied'


def test_probe_never_claims_alive_without_redis():
    """刚释放的口：绝不能判成 alive。free/occupied 的分界在 Windows 上本就不可靠
    （实机：bind 过又关掉的口连过去是 TimeoutError 而不是拒绝），所以选口不依赖它，
    以 redis-server 自己 bind 的结果为准——详见 test_spawn_retries_next_candidate_port。"""
    assert rp.probe('127.0.0.1', _free_port(), timeout=0.3) in ('free', 'occupied')


def test_probe_occupied_when_non_redis_listener():
    with _Server(reply=b'HTTP/1.1 200 OK\r\n') as srv:
        assert rp.probe('127.0.0.1', srv.port, timeout=0.5) == 'occupied'


def test_probe_occupied_when_listener_never_answers():
    """accept 了但不回话：不能因为 recv 超时就当成空口。"""
    with _Server(reply=None) as srv:
        assert rp.probe('127.0.0.1', srv.port, timeout=0.4) == 'occupied'


def test_probe_occupied_when_socket_listens_silently():
    """只 listen 不 accept（内核会接受连接）：同样是 occupied，
    判成 free 会把 redis-server 启在它 bind 不上的口上（实机取证撞到的判据漏洞）。"""
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert rp.probe('127.0.0.1', port, timeout=0.4) == 'occupied'
    finally:
        s.close()


def test_probe_alive_on_plain_and_noauth_reply():
    """-NOAUTH 也是 Redis 在应答：误判成占用会去启第二个实例，互相 flush 同一份缓存。"""
    for reply in (b'+PONG\r\n', b'-NOAUTH Authentication required.\r\n'):
        with _Server(reply=reply) as srv:
            assert rp.probe('127.0.0.1', srv.port, timeout=0.5) == 'alive'


# ────────────────────────── 复用优先 / 不该拉起的场景 ──────────────────────────
def test_reuses_live_redis_and_never_spawns(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rp, 'probe', lambda *a, **k: 'alive')
    monkeypatch.setattr(rp, '_spawn', lambda *a, **k: calls.append(a) or (None, ''))
    info = rp.ensure_running(_cfg(tmp_path))
    assert info['action'] == 'reused'
    assert calls == [], '已有 Redis 在应答时绝不能启动第二个实例'


def test_remote_target_is_never_spawned(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rp, 'probe', lambda *a, **k: 'free')
    monkeypatch.setattr(rp, '_spawn', lambda *a, **k: calls.append(a) or (None, ''))
    info = rp.ensure_running(_cfg(tmp_path, REDIS_HOST='10.0.0.20'))
    assert info['action'] == 'none'
    assert '非本机' in info['reason']
    assert calls == []


@pytest.mark.parametrize('backend', ['disabled', 'fakeredis'])
def test_forced_backend_is_respected(tmp_path, monkeypatch, backend):
    calls = []
    monkeypatch.setattr(rp, 'probe', lambda *a, **k: 'free')
    monkeypatch.setattr(rp, '_spawn', lambda *a, **k: calls.append(a) or (None, ''))
    info = rp.ensure_running(_cfg(tmp_path, REDIS_BACKEND=backend))
    assert info['action'] == 'none' and calls == []


def test_no_binary_degrades_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, 'probe', lambda *a, **k: 'free')
    monkeypatch.setattr(rp, 'find_server', lambda cfg=None: None)
    info = rp.ensure_running(_cfg(tmp_path), allow_spawn=True)   # 越过 pytest 会话守卫
    assert info['action'] == 'none'
    assert 'redis-server' in info['reason'], '原因要能指到该把 zip 解压到哪'


def test_probe_blowup_never_propagates(tmp_path, monkeypatch):
    """探活本身出错（异常 DNS、防火墙怪行为）也不能把异常抛出到启动链路。"""
    def _boom(*a, **k):
        raise OSError('防火墙捣乱')
    monkeypatch.setattr(rp, 'probe', _boom)
    info = rp.ensure_running(_cfg(tmp_path))
    assert info['action'] == 'none'


def test_test_session_guard_blocks_spawn(tmp_path, monkeypatch):
    """pytest 里一律不拉子进程（conftest 在 import app 前只改了库 URI，本模块照样会执行）。"""
    assert rp._in_test_session() is True
    calls = []
    monkeypatch.setattr(rp, 'probe', lambda *a, **k: 'free')
    monkeypatch.setattr(rp, '_spawn', lambda *a, **k: calls.append(a) or (None, ''))
    info = rp.ensure_running(_cfg(tmp_path), allow_spawn=False)
    assert info['action'] == 'none' and calls == []


# ────────────────────────── 端口避让与遗留实例 ──────────────────────────
def test_leftover_portable_instance_is_reused_not_duplicated(tmp_path, monkeypatch):
    """上一轮崩了留下的便携实例还活着：沿用它的端口，不再启第二个。"""
    cfg = _cfg(tmp_path)
    cfg.REDIS_PORTABLE_DIR = str(tmp_path / 'tools' / 'redis')
    exe = tmp_path / 'redis-server.exe'
    exe.write_text('', encoding='utf-8')
    monkeypatch.setattr(rp, 'find_server', lambda c=None: str(exe))

    def fake_probe(host, port, timeout=0.6):
        return 'occupied' if int(port) == 6379 else 'alive'      # 6380 上是我们的遗留实例
    monkeypatch.setattr(rp, 'probe', fake_probe)
    monkeypatch.setattr(rp, '_read_marker', lambda c: {'pid': 4242, 'port': 6380})
    info = rp.ensure_running(cfg)
    assert info['action'] == 'reused' and info['port'] == 6380
    assert '遗留' in info['source']


def test_occupied_default_port_avoids_to_alt(tmp_path, monkeypatch):
    """6379 被别的程序（非 Redis）占着 → 避让到备用口，并且 host 落到 127.0.0.1。"""
    cfg = _cfg(tmp_path)
    exe = tmp_path / 'redis-server.exe'
    exe.write_text('', encoding='utf-8')
    monkeypatch.setattr(rp, 'find_server', lambda c=None: str(exe))
    monkeypatch.setattr(rp, '_read_marker', lambda c: None)

    picked = []

    def fake_probe(host, port, timeout=0.6):
        port = int(port)
        if port == 6379:
            return 'occupied'
        if port == 6380:
            picked.append(port)
            return 'alive'
        return 'free'
    monkeypatch.setattr(rp, 'probe', fake_probe)
    monkeypatch.setattr(rp, '_spawn', lambda e, p, c: (_ for _ in ()).throw(
        AssertionError('probe 已就绪则不该再 spawn')))
    # 6380 探到 alive：这是「避让过程中发现备用口已有 Redis」，直接复用
    info = rp.ensure_running(cfg)
    assert info['action'] == 'reused' and info['port'] == 6380 and picked == [6380]


def test_all_candidate_ports_fail_to_bind(tmp_path, monkeypatch):
    """候选口全拉不起（真的有人占着，redis-server 自己会退）：降级且不改配置。"""
    cfg = _cfg(tmp_path)
    exe = tmp_path / 'redis-server.exe'
    exe.write_text('', encoding='utf-8')
    monkeypatch.setattr(rp, 'find_server', lambda c=None: str(exe))
    monkeypatch.setattr(rp, '_read_marker', lambda c: None)
    monkeypatch.setattr(rp, 'probe', lambda h, p, timeout=0.6: 'occupied')
    monkeypatch.setattr(rp, '_spawn', lambda e, p, c: (None, 'bind 失败'))
    info = rp.apply_runtime(None, cfg, allow_spawn=True)
    assert info['action'] == 'none' and '未拉起成功' in info['reason']
    assert (cfg.REDIS_HOST, cfg.REDIS_PORT, cfg.RATE_LIMIT_STORAGE_URI) == \
        ('127.0.0.1', 6379, 'redis://127.0.0.1:6379/0')


def test_spawn_retries_next_candidate_port(tmp_path, monkeypatch):
    """首选口 bind 不上就换备用口重试：Windows 上客户端探测分不出空口与被占
    （实机：刚 bind 过又关掉的口 probe 直接 TimeoutError），只能以 bind 结果为准。"""
    cfg = _cfg(tmp_path)
    exe = tmp_path / 'redis-server.exe'
    exe.write_text('', encoding='utf-8')
    monkeypatch.setattr(rp, 'find_server', lambda c=None: str(exe))
    monkeypatch.setattr(rp, '_read_marker', lambda c: None)
    monkeypatch.setattr(rp, 'probe', lambda h, p, timeout=0.6: 'free')
    tried = []

    def fake_spawn(e, p, c):
        tried.append(p)
        if p == 6379:
            return None, 'Creating Server TCP listening socket: bind: Address already in use'
        return SimpleNamespace(pid=4321, poll=lambda: None, terminate=lambda: None,
                               wait=lambda **k: 0, kill=lambda: None), ''
    monkeypatch.setattr(rp, '_spawn', fake_spawn)
    info = rp.ensure_running(cfg, allow_spawn=True)
    assert info['action'] == 'spawned' and info['port'] == 6380
    assert tried == [6379, 6380], '首选口失败后必须逐个候选口重试'
    rp._shutdown_child()


# ────────────────────────── 真拉进程（替身 exe）──────────────────────────
@pytest.mark.skipif(os.name != 'nt', reason='跨盘符 relpath 仅 Windows 会报错')
def test_display_path_survives_cross_drive(tmp_path):
    """实机踩过的坑：APP_DIR 在 D:、redis 装在 C: 时裸 relpath 抛 ValueError，
    又处在 spawn 成功之后的收尾段，会把已拉起的实例误报成 none。"""
    cfg = _cfg(tmp_path, APP_DIR='D:\\projects\\exam')
    exe = 'C:\\Program Files\\redis\\redis-server.exe'
    assert rp._display_path(exe, cfg) == exe


def test_spawn_full_chain_then_cleanup(tmp_path, stub_exe, monkeypatch):
    """替身 exe 走通完整链路：发现 → 拉起 → 等就绪 → 回写配置 → 退出时关闭。"""
    cfg = _cfg(tmp_path, REDIS_SERVER_PATH=sys.executable)
    port = _free_port()
    monkeypatch.setattr(rp, '_build_command',
                        lambda exe, p, c: [sys.executable, stub_exe, str(p)])
    # 首选口空着，直接用它：把固定端口塞进备用表末尾，其余备用口保持真空
    cfg.REDIS_ALT_PORTS = [port]
    cfg.REDIS_PORT = port
    info = rp.apply_runtime(None, cfg, allow_spawn=True)
    proc = rp._child
    try:
        assert info['action'] == 'spawned', info['reason']
        assert (info['host'], info['port']) == ('127.0.0.1', port)
        assert (cfg.REDIS_HOST, cfg.REDIS_PORT) == ('127.0.0.1', port)
        assert proc is not None and proc.poll() is None
        marker = rp._read_marker(cfg)
        assert marker and marker['port'] == port and marker['pid'] == proc.pid
    finally:
        rp._shutdown_child()
    assert proc.poll() is not None, '自行拉起的实例必须随应用退出关掉'
    assert rp._child is None


def test_spawn_timeout_leaves_config_untouched(tmp_path, monkeypatch):
    """拉不起来（假 exe 立刻退出）→ action=none，且原有 host/port 与限流 URI 一字不改。"""
    cfg = _cfg(tmp_path, REDIS_HOST='127.0.0.1', REDIS_PORT=6399)
    before = (cfg.REDIS_HOST, cfg.REDIS_PORT, cfg.RATE_LIMIT_STORAGE_URI)
    exe = tmp_path / 'redis-server.exe'
    exe.write_text('', encoding='utf-8')
    monkeypatch.setattr(rp, 'find_server', lambda c=None: str(exe))
    monkeypatch.setattr(rp, '_read_marker', lambda c: None)
    monkeypatch.setattr(rp, 'probe', lambda h, p, timeout=0.6: 'free')
    monkeypatch.setattr(rp, '_spawn', lambda e, p, c: (None, '假 exe 秒退'))
    info = rp.apply_runtime(None, cfg, allow_spawn=True)
    assert info['action'] == 'none'
    assert (cfg.REDIS_HOST, cfg.REDIS_PORT, cfg.RATE_LIMIT_STORAGE_URI) == before


# ────────────────────────── 限流 URI 跟随最终端口 ──────────────────────────
def test_apply_runtime_rebases_rate_limit_uri(tmp_path, monkeypatch):
    """端口避让到 6381 后限流必须跟着换，否则 init_security 探空口 → 静默回落 memory://。"""
    monkeypatch.setattr(rp, 'ensure_running',
                        lambda cfg=None, allow_spawn=None: {'action': 'spawned', 'host': '127.0.0.1',
                                          'port': 6381, 'source': 'x', 'reason': ''})
    cfg = _cfg(tmp_path)
    rp.apply_runtime(None, cfg)
    assert cfg.RATE_LIMIT_STORAGE_URI == 'redis://127.0.0.1:6381/0'


def test_explicit_rate_limit_uri_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, 'ensure_running',
                        lambda cfg=None, allow_spawn=None: {'action': 'spawned', 'host': '127.0.0.1',
                                          'port': 6381, 'source': 'x', 'reason': ''})
    cfg = _cfg(tmp_path, RATE_LIMIT_STORAGE_URI='redis://sentinel:6379/9',
               RATE_LIMIT_URI_EXPLICIT=True)
    rp.apply_runtime(None, cfg)
    assert cfg.RATE_LIMIT_STORAGE_URI == 'redis://sentinel:6379/9'


def test_memory_rate_limit_default_is_not_upgraded(tmp_path, monkeypatch):
    """没配过 Redis 的机器默认 memory://（单进程 waitress 计数本就准确），不擅自改写。"""
    monkeypatch.setattr(rp, 'ensure_running',
                        lambda cfg=None, allow_spawn=None: {'action': 'spawned', 'host': '127.0.0.1',
                                          'port': 6381, 'source': 'x', 'reason': ''})
    cfg = _cfg(tmp_path, RATE_LIMIT_STORAGE_URI='memory://')
    rp.apply_runtime(None, cfg)
    assert cfg.RATE_LIMIT_STORAGE_URI == 'memory://'


def test_resolve_rate_limit_uri_rebuild_keeps_db_and_password(monkeypatch):
    monkeypatch.delenv('RATE_LIMIT_STORAGE_URI', raising=False)
    from config import resolve_rate_limit_uri
    assert resolve_rate_limit_uri(host='127.0.0.1', port='6381', db='3',
                                  password='p@ss') == 'redis://:p%40ss@127.0.0.1:6381/3'
    assert resolve_rate_limit_uri(explicit='redis://x:1/2', host='h', port='9') == \
        'redis://x:1/2'


def test_runtime_publishes_to_app_config(tmp_path, monkeypatch):
    """healthz 的 redis_runtime 来源：app.config 里必须能看到本轮做了什么。"""
    from flask import Flask
    monkeypatch.setattr(rp, 'ensure_running',
                        lambda cfg=None, allow_spawn=None: {'action': 'reused', 'host': '127.0.0.1',
                                          'port': 6379, 'source': '已运行实例', 'reason': 'r'})
    app = Flask(__name__)
    cfg = _cfg(tmp_path)
    rp.apply_runtime(app, cfg)
    assert app.config['REDIS_RUNTIME']['action'] == 'reused'
    assert app.config['REDIS_PORT'] == 6379


def test_healthz_exposes_redis_runtime():
    """接线回归门：便携层真的跑在 init_redis() 之前，且结果能从 /healthz 看到。

    同时钉住一条运维语义：跑测试绝不应拉起子进程（conftest 在 import app 前
    只改了库 URI，app.py 的 import 期代码在测试里照样执行）。"""
    import app as prod
    body = prod.app.test_client().get('/healthz').get_json()
    info = body['redis_runtime']
    assert info['action'] in ('reused', 'none'), '测试会话内不得拉起 Redis 子进程'
    assert info['reason'], '无论成败都要说清为什么，不然换设备无法排查'
    assert body['redis'] in (None, 'real', 'fake')
    assert 'password' not in json.dumps(info, ensure_ascii=False).lower()
