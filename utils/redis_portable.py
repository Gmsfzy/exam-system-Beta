# -*- coding: utf-8 -*-
"""便携 Redis（v7.6）：让 Redis 像 tools/mingw64 那样随项目走。

要解决的问题：换到一台没装 Redis/Memurai 的电脑，缓存层原先只能落 fakeredis
（进程内存，重启即空、多进程不共享）。这里补上「项目内自带 redis-server 就自己拉起来」。

三条不可让步的语义（与《环境兼容说明.md》对应小节一致）：

1. 复用优先。目标端口上只要有活着的 Redis（本机 Memurai、Docker 映射的、别人手动起的），
   一律直接连，绝不启动第二个实例——两个实例抢同一 db 会互相 flush，且「我起的」这件事
   会变成「我谁都不知道」。
2. 拉不起来绝不拒起服务。找不到二进制、端口全被占、进程秒退……一律返回 action='none'，
   由 utils.redis_cache.init_redis() 按原有 auto 链降级到 fakeredis / DB 穿透。
   这与 v7.5 PG 的「装了但连不上就拒起服务」**刻意相反**：PG 存的是数据真值，
   Redis 只是可丢的加速层，把它升级成新的故障源是赔本买卖。
3. 只管自己起的。atexit 只 terminate 本进程 Popen 出来的那个 handle，
    marker 文件里记录的上一轮遗留实例不杀（可能是别的进程正在用）。

发现顺序与 oj/adapters/_toolchain.py 完全一致：
显式配置 Config.REDIS_SERVER_PATH → 环境变量 → 项目内 tools/redis/ → 系统 PATH。
"""
import os
import sys
import json
import atexit
import socket
import subprocess
import shutil
import time
import logging

logger = logging.getLogger(__name__)

# 只有这些目标才允许「本机没装 Redis」的推断与自动拉起；远程 Redis 不碰（同 PG 口径）
_LOOPBACK = {'127.0.0.1', 'localhost', '::1', '0.0.0.0', ''}

_EXE = 'redis-server.exe' if os.name == 'nt' else 'redis-server'

# ensure_running 的结果，模块级留存供 /healthz 汇报（进程内只跑一次）
_RUNTIME = {'action': 'none', 'host': None, 'port': None,
            'source': None, 'reason': '未执行'}

# 本进程 Popen 出来的实例（唯一有权在退出时关闭的）
_child = None
_atexit_registered = False


def _cfg():
    from config import Config
    return Config


def is_loopback(host):
    """本机回环判定：只有本地目标才可能自动拉起便携实例。"""
    h = (host or '').strip()
    return h in _LOOPBACK or h.startswith('127.')


def find_server(cfg=None):
    """按四级优先定位 redis-server 可执行文件，返回绝对路径或 None（不抛）。"""
    cfg = cfg or _cfg()

    def _resolve(spec):
        if not spec:
            return None
        if os.path.isabs(spec):
            return spec if os.path.exists(spec) else None
        return shutil.which(spec)

    # 1. Config 显式属性（.env 的 REDIS_SERVER_PATH 已在 config 里读入）
    try:
        p = _resolve(getattr(cfg, 'REDIS_SERVER_PATH', None))
        if p:
            return p
    except Exception:
        pass
    # 2. 环境变量（绕过 config 直接给进程注入的场景）
    p = _resolve(os.environ.get('REDIS_SERVER_PATH'))
    if p:
        return p
    # 3. 项目内便携目录：根目录、bin/、以及 zip 解出来常带的单层同名目录
    base = getattr(cfg, 'REDIS_PORTABLE_DIR', None)
    for cand in _portable_candidates(base):
        if os.path.exists(cand):
            return cand
    # 4. 系统 PATH（Linux 部署时 apt 装的 redis-server 走这一级）
    try:
        return shutil.which('redis-server')
    except Exception:
        return None


def _portable_candidates(base):
    """项目内便携目录下的候选路径（含 zip 解压常见的多套一层目录，最深 2 层）。"""
    if not base or not os.path.isdir(base):
        return []
    out = [os.path.join(base, _EXE), os.path.join(base, 'bin', _EXE)]
    try:
        for name in sorted(os.listdir(base)):
            sub = os.path.join(base, name)
            if not os.path.isdir(sub):
                continue
            out.append(os.path.join(sub, _EXE))
            out.append(os.path.join(sub, 'bin', _EXE))
    except OSError:
        pass
    return out


def probe(host, port, timeout=0.6):
    """目标端口三态探活：'alive'（Redis 在应答）/'occupied'（别的程序在听）/'free'（没人听）。

    走 RESP inline command 而不是 import redis：一是免依赖（脚本环境也能用），
    二是能区分「端口被别的程序占了」和「根本是空的」——前者要避让，后者可以直接用。
    收到任何 RESP 单级回复（+ 或 -）都算 Redis 活着：带 requirepass 的实例会回
    -NOAUTH，那同样是 Redis，不能误判成占用后去启第二个实例。

    「连上了但不应答」必须算 occupied 而不是 free：实机拿一个只 listen/accept
    不回话的端口试过，原先在 recv 超时时落到 except 分支被判成空口，
    结果会把 redis-server 启在一个它 bind 不上、也没人能连的口上。
    只有明确被拒（ConnectionRefusedError）才认定是空的。
    """
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
    except ConnectionRefusedError:
        return 'free'
    except (socket.timeout, TimeoutError, OSError):
        return 'occupied'
    try:
        s.settimeout(timeout)
        s.sendall(b'PING\r\n')
        reply = s.recv(64)
    except (socket.timeout, TimeoutError, OSError):
        return 'occupied'
    finally:
        s.close()
    if not reply:
        return 'occupied'
    return 'alive' if reply[:1] in (b'+', b'-', b':', b'$') else 'occupied'


def _marker_path(cfg):
    return os.path.join(cfg.REDIS_PORTABLE_DATA, 'portable-instance.json')


def _read_marker(cfg):
    try:
        with open(_marker_path(cfg), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _write_marker(cfg, info):
    try:
        os.makedirs(cfg.REDIS_PORTABLE_DATA, exist_ok=True)
        with open(_marker_path(cfg), 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False)
    except OSError as e:
        logger.debug(f'[便携 Redis] 记录实例信息失败（不影响运行）: {e}')


def _clear_marker(cfg):
    try:
        os.remove(_marker_path(cfg))
    except OSError:
        pass


def _build_command(exe, port, cfg):
    """便携实例启动参数。

    关掉持久化（save '' + appendonly no）：缓存是数据库的派生数据，重启后重新预热即可，
    留下 rdb/aof 只会带来「旧缓存比新数据旧」和「拷项目时多一堆二进制垃圾」两个麻烦。
    只绑 127.0.0.1 + protected-mode yes：不照抄现成发行版 conf 里的 protected-mode no，
    免得换台机器一开机就把缓存端口敞开在局域网上。
    """
    data_dir = cfg.REDIS_PORTABLE_DATA
    return [
        exe,
        '--port', str(port),
        '--bind', '127.0.0.1',
        '--protected-mode', 'yes',
        '--save', '',
        '--appendonly', 'no',
        '--maxmemory', '256mb',
        '--maxmemory-policy', 'allkeys-lru',
        '--dir', data_dir,
        '--logfile', os.path.join(data_dir, 'redis.log'),
    ]


def _spawn(exe, port, cfg):
    """拉起便携实例，返回 (Popen|None, reason)。"""
    os.makedirs(cfg.REDIS_PORTABLE_DATA, exist_ok=True)
    cmd = _build_command(exe, port, cfg)
    kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, **kwargs)
    deadline = time.time() + max(1, int(cfg.REDIS_START_TIMEOUT))
    while time.time() < deadline:
        if probe('127.0.0.1', port) == 'alive':
            return proc, ''
        if proc.poll() is not None:
            log = os.path.join(cfg.REDIS_PORTABLE_DATA, 'redis.log')
            tail = ''
            try:
                with open(log, 'r', encoding='utf-8', errors='replace') as f:
                    tail = (f.read().strip().splitlines() or [''])[-1]
            except OSError:
                pass
            return None, f'redis-server 启动即退出（code={proc.returncode}）' + \
                (f'：{tail}' if tail else '')
        time.sleep(0.2)
    _terminate(proc)
    return None, f'{cfg.REDIS_START_TIMEOUT}s 内未就绪'


def _terminate(proc):
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _shutdown_child():
    """atexit：只关本进程自己拉起的那个实例。"""
    global _child
    if _child is None:
        return
    proc, _child = _child, None
    logger.info('[便携 Redis] 应用退出，关闭自行拉起的 redis-server')
    _terminate(proc)


def _in_test_session():
    """pytest 里绝不拉子进程。

    tests/conftest.py 在 import app 之前只替换了数据库 URI，app.py 的 import 期代码
    （含本模块）在测试中照样执行；全量 557 个用例每跑一次都启一个 Redis 服务进程
    是不能接受的，而且 CI/无二进制环境下还会引入不确定性。
    """
    if os.environ.get('PYTEST_CURRENT_TEST'):
        return True
    argv0 = os.path.basename(sys.argv[0] or '').lower()
    if argv0.startswith('pytest') or argv0 == 'py.test':
        return True
    return any('pytest' in str(a).lower() for a in sys.argv[:2])


def _display_path(exe, cfg):
    """日志/healthz 里的 exe 展示路径：项目内给相对路径，其余给绝对路径。

    不能用裸 os.path.relpath：Windows 上跨盘符（APP_DIR 在 D:、Redis 装在 C:）会直接
    抛 ValueError，而它处于 spawn 成功之后的收尾段——不包住就会把已拉起的实例误报成
    action=none（实机踩到，见 tests/test_redis_portable.py）。
    """
    try:
        return os.path.relpath(exe, cfg.APP_DIR).replace('\\', '/')
    except Exception:
        return str(exe)


def _dedup(ports):
    """保留顺序去重（配置端口与 marker/备用口可能重合）。"""
    out, seen = [], set()
    for p in ports:
        if p and int(p) not in seen:
            seen.add(int(p))
            out.append(int(p))
    return out


def ensure_running(cfg=None, allow_spawn=None):
    """确保有一个可用的 Redis 实例，并把生效 host/port 落到配置上。

    返回 {'action': reused|spawned|none, 'host', 'port', 'source', 'reason'}；
    任何异常都在内部吞掉并转成 action='none'——这个函数永远不能成为启动失败的原因。
    """
    global _child, _atexit_registered
    cfg = cfg or _cfg()
    host = getattr(cfg, 'REDIS_HOST', 'localhost')
    port = int(getattr(cfg, 'REDIS_PORT', 6379))
    info = {'action': 'none', 'host': host, 'port': port,
            'source': None, 'reason': ''}
    try:
        backend = getattr(cfg, 'REDIS_BACKEND', 'auto')
        if backend in ('disabled', 'fakeredis'):
            info['reason'] = f'REDIS_BACKEND={backend}，按配置不连接真实 Redis'
            return _record(info)

        status = probe(host, port)
        if status == 'alive':
            info.update(action='reused', source='已运行实例',
                        reason=f'{host}:{port} 上已有 Redis，直接复用（不启动第二实例）')
            return _record(info)

        if not is_loopback(host):
            info['reason'] = f'目标 {host}:{port} 不可达且非本机，不代为拉起'
            return _record(info)

        # 先找「是不是已经有一个在跑」：配置端口、上一轮遗留的便携实例（marker）、备用口。
        # 这一步放在任何 spawn 判据之前，连 REDIS_AUTO_START=false 也要能命中复用——
        # 关掉自动拉起不应该让我们错过已在运行的实例而误报成「没有 Redis」。
        marker = _read_marker(cfg)
        marker_port = int(marker['port']) if marker and marker.get('port') else None
        alts = [int(p) for p in getattr(cfg, 'REDIS_ALT_PORTS', []) or []]
        candidates = _dedup([port, marker_port] + alts)

        for p in candidates:
            if probe('127.0.0.1', p) == 'alive':
                info.update(action='reused', host='127.0.0.1', port=p,
                            source='项目便携实例（上一轮遗留）' if p == marker_port
                            else '已在运行的 Redis 实例',
                            reason='复用在跑的实例，不重复启动')
                return _record(info)

        # 走到这里才真的要拉进程：配置开关 → 测试会话 → 二进制发现，三道闸门
        if allow_spawn is False or not getattr(cfg, 'REDIS_AUTO_START', True):
            info['reason'] = ('REDIS_AUTO_START=false，只做发现与复用；'
                              f'候选端口 {candidates} 上没在跑的 Redis，降级 fake 缓存')
            return _record(info)
        if allow_spawn is not True and _in_test_session():
            # allow_spawn=True 是测试专用绕道（tests/test_redis_portable.py 靠它验进程链路）
            info['reason'] = '测试会话内不拉起子进程'
            return _record(info)

        exe = find_server(cfg)
        if not exe:
            info['reason'] = (f'本机无 Redis 且项目内未提供 redis-server'
                              f'（解压到 {cfg.REDIS_PORTABLE_DIR} 即可随项目走），降级 fake 缓存')
            return _record(info)

        # 端口能不能用，最终以 redis-server 自己 bind 的结果为准：
        # Windows 上连一个真空口都可能超时（实机取证：刚 bind 过又关掉的口
        # probe 直接 TimeoutError），单靠客户端探测区分不出「空口」与「被人占着」；
        # 而 bind 失败是确定性的——口被人占着 redis-server 会立即退出，换下一个候选口重试。
        proc, target, last = None, None, ''
        for p in candidates:
            proc, last = _spawn(exe, p, cfg)
            if proc is not None:
                target = p
                break
        if proc is None:
            info['reason'] = (f'候选端口 {candidates} 均未拉起成功：{last}，降级 fake 缓存')
            logger.warning(f'[便携 Redis] {info["reason"]}')
            return _record(info)

        _child = proc
        if not _atexit_registered:
            atexit.register(_shutdown_child)
            _atexit_registered = True
        _write_marker(cfg, {'pid': proc.pid, 'port': target, 'exe': exe})
        info.update(action='spawned', host='127.0.0.1', port=target,
                    source=_display_path(exe, cfg),
                    reason=f'已启动项目内便携 Redis（pid={proc.pid}）')
        return _record(info)
    except Exception as e:      # 兜死：便携层任何故障都不许阻断应用启动
        logger.warning(f'[便携 Redis] 探测/拉起异常（忽略，按原配置降级）: {e}')
        info['reason'] = f'便携 Redis 处理异常：{e}'
        return _record(info)


def apply_runtime(app, cfg=None, allow_spawn=None):
    """接入点：拉起/复用后把生效值同时写回 Config 类与 app.config。

    必须两边都写：utils.redis_cache._try_real_redis 与 utils.security.init_security
    读的是 Config 类属性（不是 app.config），只写 app.config 的话缓存会连旧端口。
    allow_spawn 仅供测试显式越过 pytest 会话守卫，生产调用一律留空。
    """
    cfg = cfg or _cfg()
    info = ensure_running(cfg, allow_spawn=allow_spawn)
    if info['action'] == 'none':
        # 没成也不要紧：原有 auto 链会自己落到 fakeredis / DB 穿透
        logger.info(f"[便携 Redis] 未启用真实实例：{info['reason']}")
        _publish(app, cfg, info)
        return info

    cfg.REDIS_HOST, cfg.REDIS_PORT = info['host'], info['port']
    # 端口避让后限流必须跟着换：RATE_LIMIT_STORAGE_URI 是 import 期算死的字符串，
    # 不回写就会去探一个没人听的端口然后静默回落 memory://（多进程计数被稀释且无感）。
    # 用户显式写过 RATE_LIMIT_STORAGE_URI 的以他写的为准，不动。
    if not getattr(cfg, 'RATE_LIMIT_URI_EXPLICIT', False) and \
            str(cfg.RATE_LIMIT_STORAGE_URI).startswith('redis://'):
        from config import resolve_rate_limit_uri
        cfg.RATE_LIMIT_STORAGE_URI = resolve_rate_limit_uri(
            host=info['host'], port=info['port'],
            db=getattr(cfg, 'REDIS_DB', None),
            password=getattr(cfg, 'REDIS_PASSWORD', None))
    _publish(app, cfg, info)
    logger.info(f"[便携 Redis] {info['action']} -> {info['host']}:{info['port']} "
                f"（{info['source']}）；{info['reason']}")
    return info


def _publish(app, cfg, info):
    if app is None:
        return
    try:
        app.config['REDIS_HOST'] = cfg.REDIS_HOST
        app.config['REDIS_PORT'] = cfg.REDIS_PORT
        app.config['RATE_LIMIT_STORAGE_URI'] = cfg.RATE_LIMIT_STORAGE_URI
        app.config['REDIS_RUNTIME'] = info
    except Exception:
        pass


def _record(info):
    """结果留存供 /healthz；配置回写统一在 apply_runtime 里做，此处不产生副作用。"""
    global _RUNTIME
    _RUNTIME = info
    return info


def runtime_info():
    """/healthz 用：本轮便携 Redis 做了什么（不含密码）。"""
    return dict(_RUNTIME)
