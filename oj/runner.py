# -*- coding: utf-8 -*-
"""OJ 子进程执行器

安全定位（重要）：Windows 下无 seccomp/rlimit，本执行器为"校内测验级防呆"——
静态危险模式拒绝 + 隔离解释器（-I：忽略环境变量/用户 site-packages）+
独立临时工作目录 + 超时强杀 + 输出截断。它不是竞技级防逃逸沙箱，
恶意用户可绕过静态检查做危险操作，边界已写入《存在隐患.md》风险台账。
"""
import os
import re
import subprocess
import sys
import tempfile

# 单用例输出上限（防无限 print 撑爆内存，超出截断判 WA）
MAX_OUTPUT = 1024 * 1024
# 提交代码长度上限
MAX_CODE_SIZE = 20000

# 静态危险模式：进程/网络/文件系统破坏/底层逃逸（大小写敏感，按源码文本匹配）
_DANGER_PATTERNS = [
    r'\bimport\s+(ctypes|socket|subprocess|multiprocessing|shutil|asyncio|threading|webbrowser)\b',
    r'\bfrom\s+(ctypes|socket|subprocess|multiprocessing|shutil|asyncio|threading|webbrowser)\b',
    r'\bos\s*\.\s*(system|popen|exec\w*|spawn\w*|remove|unlink|kill|startfile|fork|walk|listdir)\b',
    r'\b__import__\s*\(',
    r'\bopen\s*\(',                       # 正常题解走 stdin，无需文件读写
    r'\bexec\s*\(', r'\beval\s*\(\s*compile',
]
_DANGER_RE = [re.compile(p) for p in _DANGER_PATTERNS]

# 子进程最小可用环境：Windows 下空环境（env={}）会让 Python 子进程初始化
# 随机数源失败（Fatal Python error: _Py_HashRandomization_Init），SYSTEMROOT
# 为必需项；白名单不含任何业务环境变量（密钥等），与 dsci/runner.py 同一做法
_ENV_ALLOW = ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
              'LANG', 'LC_ALL', 'HOME', 'USERPROFILE')


def _minimal_env():
    return {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}


def check_code(code):
    """静态防呆检查：命中危险模式返回原因字符串，干净返回 None。"""
    if not code or not code.strip():
        return '代码为空'
    if len(code) > MAX_CODE_SIZE:
        return f'代码超过 {MAX_CODE_SIZE} 字符上限'
    for pat in _DANGER_RE:
        if pat.search(code):
            return f'代码包含受限操作（{pat.pattern[:40]}…）'
    return None


def _kill_tree(proc):
    """强杀子进程；Windows 下尽力杀掉进程树（taskkill /T），失败回落 kill()。"""
    try:
        if os.name == 'nt':
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                capture_output=True, timeout=10,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def run_python(code, stdin='', timeout=5.0):
    """在隔离临时环境执行 code，喂 stdin，返回结果字典。

    返回：{stdout, stderr, exit_code, timed_out, error}
    error 非 None 表示未执行（静态拒绝/环境异常）。
    """
    reason = check_code(code)
    if reason:
        return {'stdout': '', 'stderr': '', 'exit_code': None,
                'timed_out': False, 'error': reason}

    timeout = max(0.5, min(float(timeout), 15.0))  # 钳制 [0.5, 15] 秒
    with tempfile.TemporaryDirectory(prefix='oj-') as workdir:
        script = os.path.join(workdir, 'main.py')
        with open(script, 'w', encoding='utf-8') as f:
            f.write(code)
        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            proc = subprocess.Popen(
                [sys.executable, '-I', script],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=workdir,
                env=_minimal_env(),  # -I + 最小白名单环境：不带任何业务环境变量
                **kwargs)
        except OSError as exc:
            return {'stdout': '', 'stderr': str(exc), 'exit_code': None,
                    'timed_out': False, 'error': f'执行环境异常：{exc}'}
        timed_out = False
        try:
            out, err = proc.communicate(
                (stdin or '').encode('utf-8', errors='replace'), timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                out, err = proc.communicate(timeout=5)
            except Exception:
                out, err = b'', b''
        return {
            'stdout': (out or b'')[:MAX_OUTPUT].decode('utf-8', errors='replace'),
            'stderr': (err or b'')[:8192].decode('utf-8', errors='replace'),
            'exit_code': proc.returncode,
            'timed_out': timed_out,
            'error': None,
        }
