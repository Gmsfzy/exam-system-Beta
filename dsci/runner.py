# -*- coding: utf-8 -*-
"""数据科学赛沙箱执行器（v4.11）：可读写工作目录内文件的 jail 子进程。

与 oj.runner 的区别与边界（重要，登记《存在隐患.md》#9）：
- DS 代码需读数据集、写 submission.csv，故放开 open()/文件读写，但进程 cwd 锁定在
  一次性临时目录，公开数据集以相对路径落盘其中；gold（隐藏答案）永不进本目录。
- 仍沿用静态危险模式拒绝（网络/进程/子进程/破坏性 os.*/exec/eval）与隔离解释器
  -I、超时强杀、输出截断；env 仅透传定位 DLL 所需的最小白名单，不外泄业务环境变量。
- 定位是"校内防呆级"，非竞技级防逃逸；恶意用户仍可能借放开的文件写入做危险操作，
  边界与缓解（限流/超时/并发）已写入风险台账。
"""
import json
import os
import re
import subprocess
import sys
import tempfile

from oj.runner import _kill_tree

# 单次运行上限
MAX_CODE_SIZE = 100000          # 数据科学脚本可能较长
MAX_OUTPUT = 200 * 1024         # stdout/stderr 截断
MAX_SUBMISSION_BYTES = 2 * 1024 * 1024   # 回读 submission.csv 上限
RUN_TIMEOUT = 30.0              # 默认超时（秒），数据预处理需要更长
_TIMEOUT_CLAMP = (1.0, 60.0)

# DS 危险模式：沿用 oj 的网络/进程/破坏面，但刻意不含 open()（DS 需文件读写）
_DS_DANGER_PATTERNS = [
    r'\bimport\s+(ctypes|socket|subprocess|multiprocessing|shutil|asyncio|threading|webbrowser)\b',
    r'\bfrom\s+(ctypes|socket|subprocess|multiprocessing|shutil|asyncio|threading|webbrowser)\b',
    r'\bos\s*\.\s*(system|popen|exec\w*|spawn\w*|remove|unlink|kill|startfile|fork|walk|listdir|fwalk)\b',
    r'\b__import__\s*\(',
    r'\bexec\s*\(', r'\beval\s*\(\s*compile',
    r'\bos\s*\.\s*environ\b',           # 禁读进程环境变量（防泄 .env 注入的密钥）
]
_DS_DANGER_RE = [re.compile(p) for p in _DS_DANGER_PATTERNS]

# 子进程最小可用环境（仅够 numpy/pandas 定位系统 DLL，不含业务密钥）
_ENV_ALLOW = ('PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
              'LANG', 'LC_ALL', 'HOME', 'USERPROFILE')


def check_ds_code(code):
    """DS 静态防呆：命中危险模式返回原因，干净返回 None。"""
    if not code or not code.strip():
        return '代码为空'
    if len(code) > MAX_CODE_SIZE:
        return f'代码超过 {MAX_CODE_SIZE} 字符上限'
    for pat in _DS_DANGER_RE:
        if pat.search(code):
            return f'代码包含受限操作（{pat.pattern[:40]}…）'
    return None


def _minimal_env():
    return {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}


def _run_script(script_name, files, timeout):
    """在临时 workdir 落盘 files（{相对名: 文本}）并执行 script_name，回读产物。

    返回 {stdout, stderr, exit_code, timed_out, error, artifacts:{名: 内容}}。
    artifacts 仅回收本次运行新增/改动的普通文本文件（限体积），供上层取 submission.csv。
    """
    timeout = max(_TIMEOUT_CLAMP[0], min(float(timeout), _TIMEOUT_CLAMP[1]))
    with tempfile.TemporaryDirectory(prefix='dsci-') as workdir:
        preexisting = set()
        for name, content in (files or {}).items():
            safe = os.path.join(workdir, name)
            if os.path.dirname(safe) != workdir:      # 拒绝越界相对路径
                return {'stdout': '', 'stderr': '', 'exit_code': None,
                        'timed_out': False, 'error': f'非法文件名：{name}',
                        'artifacts': {}}
            with open(safe, 'w', encoding='utf-8') as f:
                f.write(content if content is not None else '')
            preexisting.add(name)

        kwargs = {}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        try:
            proc = subprocess.Popen(
                [sys.executable, '-I', script_name],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=workdir, env=_minimal_env(), **kwargs)
        except OSError as exc:
            return {'stdout': '', 'stderr': str(exc), 'exit_code': None,
                    'timed_out': False, 'error': f'执行环境异常：{exc}',
                    'artifacts': {}}
        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            try:
                out, err = proc.communicate(timeout=5)
            except Exception:
                out, err = b'', b''

        # 回收新增/改动的文本产物
        artifacts = {}
        for root, _dirs, fnames in os.walk(workdir):
            for fn in fnames:
                if fn == script_name:
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, workdir).replace('\\', '/')
                try:
                    if os.path.getsize(full) > MAX_SUBMISSION_BYTES:
                        continue
                    with open(full, 'r', encoding='utf-8') as f:
                        artifacts[rel] = f.read()
                except (OSError, UnicodeDecodeError):
                    continue
        return {
            'stdout': (out or b'')[:MAX_OUTPUT].decode('utf-8', errors='replace'),
            'stderr': (err or b'')[:MAX_OUTPUT].decode('utf-8', errors='replace'),
            'exit_code': proc.returncode,
            'timed_out': timed_out,
            'error': None,
            'artifacts': artifacts,
        }


def run_notebook(code, public_files, timeout=RUN_TIMEOUT, output_name='submission.csv'):
    """在线运行：物化公开数据集，跑用户 code，回读其写出的 output_name 作为预测。

    public_files: {相对文件名: csv 文本}（train/test/sample，不含 gold）
    返回 {status, stdout, stderr, exit_code, timed_out, error, produced_submission}
      status: 'ok' | 'rejected' | 'error'
    """
    reason = check_ds_code(code)
    if reason:
        return {'status': 'rejected', 'stdout': '', 'stderr': '', 'exit_code': None,
                'timed_out': False, 'error': reason, 'produced_submission': None}
    files = dict(public_files or {})
    files['main.py'] = code
    r = _run_script('main.py', files, timeout)
    if r['error']:
        return {'status': 'error', 'stdout': r['stdout'], 'stderr': r['stderr'],
                'exit_code': None, 'timed_out': False, 'error': r['error'],
                'produced_submission': None}
    produced = r['artifacts'].get(output_name)
    return {'status': 'ok', 'stdout': r['stdout'], 'stderr': r['stderr'],
            'exit_code': r['exit_code'], 'timed_out': r['timed_out'],
            'error': ('运行超时' if r['timed_out'] else
                      (None if r['exit_code'] in (0, None) else f'退出码 {r["exit_code"]}')),
            'produced_submission': produced}


_SCORER_PREFIX = "import json\nimport pandas as pd\n\n"
_SCORER_SUFFIX = (
    "\n\ndef _score_main():\n"
    "    gold = pd.read_csv('gold.csv')\n"
    "    pred = pd.read_csv('pred.csv')\n"
    "    print(json.dumps({'score': float(score(gold, pred))}))\n\n"
    "_score_main()\n"
)


def run_custom_scorer(scorer_code, gold_csv, pred_csv, timeout=RUN_TIMEOUT):
    """教师自定义 scorer 沙箱评分：约定 scorer_code 定义 score(gold, pred)->float。

    gold/pred 以 csv 文本喂入，脚本末尾打印 {'score': x}。返回 {ok, score, error,
    stdout, stderr}。scorer_code 同样过 DS 静态防呆。
    """
    reason = check_ds_code(scorer_code)
    if reason:
        return {'ok': False, 'score': None, 'error': f'评分脚本被拒绝：{reason}',
                'stdout': '', 'stderr': ''}
    script = _SCORER_PREFIX + scorer_code + _SCORER_SUFFIX
    r = _run_script('scorer_main.py',
                    {'scorer_main.py': script, 'gold.csv': gold_csv, 'pred.csv': pred_csv},
                    timeout)
    if r['error']:
        return {'ok': False, 'score': None, 'error': r['error'],
                'stdout': r['stdout'], 'stderr': r['stderr']}
    if r['timed_out']:
        return {'ok': False, 'score': None, 'error': '评分脚本运行超时',
                'stdout': r['stdout'], 'stderr': r['stderr']}
    if r['exit_code'] not in (0, None):
        tail = '\n'.join(r['stderr'].strip().splitlines()[-3:]) or f'评分脚本退出码 {r["exit_code"]}'
        return {'ok': False, 'score': None, 'error': tail[:300],
                'stdout': r['stdout'], 'stderr': r['stderr']}
    # 取 stdout 最后一行合法 JSON
    for line in reversed([ln for ln in r['stdout'].splitlines() if ln.strip()]):
        try:
            obj = json.loads(line)
            if 'score' in obj:
                return {'ok': True, 'score': round(float(obj['score']), 6),
                        'error': None, 'stdout': r['stdout'], 'stderr': r['stderr']}
        except (ValueError, TypeError):
            continue
    return {'ok': False, 'score': None, 'error': '评分脚本未输出 {\'score\': ...}',
            'stdout': r['stdout'], 'stderr': r['stderr']}
