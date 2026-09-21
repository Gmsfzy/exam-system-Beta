# -*- coding: utf-8 -*-
"""DS 沙箱执行器单测（v4.11）：真实起子进程，验证读数据集→写预测→回读、
静态拒绝、超时、以及自定义 scorer 沙箱评分。全部用短超时保持轻量。
"""
from dsci.runner import check_ds_code, run_custom_scorer, run_notebook

_TRAIN = 'id,x\n1,2\n2,3\n3,4\n'


def test_notebook_reads_dataset_and_writes_submission():
    code = (
        'import pandas as pd\n'
        "df = pd.read_csv('train.csv')\n"
        "print('rows', len(df))\n"
        "out = pd.DataFrame({'id': df['id'], 'y': df['x'] * 2})\n"
        "out.to_csv('submission.csv', index=False)\n"
    )
    r = run_notebook(code, {'train.csv': _TRAIN}, timeout=15)
    assert r['status'] == 'ok', r
    assert 'rows 3' in r['stdout']
    assert r['produced_submission'] and 'id,y' in r['produced_submission']
    assert r['error'] is None


def test_notebook_no_submission_returns_none():
    r = run_notebook('print(123)', {}, timeout=10)
    assert r['status'] == 'ok' and r['produced_submission'] is None
    assert '123' in r['stdout']


def test_static_reject_network_import():
    reason = check_ds_code('import socket\nsocket.socket()')
    assert reason and '受限' in reason
    r = run_notebook('import os\nos.system("dir")', {}, timeout=5)
    assert r['status'] == 'rejected'


def test_open_is_allowed_in_ds():
    """与 oj 关键差异：DS 放开 open()，普通文件读写不被静态拒绝。"""
    assert check_ds_code("f = open('a.txt', 'w')") is None


def test_env_read_blocked():
    assert check_ds_code('import os\nprint(os.environ)') is not None


def test_notebook_timeout():
    r = run_notebook('x = 0\nwhile True:\n    x += 1', {}, timeout=1.0)
    assert r['timed_out'] is True and r['error'] == '运行超时'


def test_custom_scorer_ok():
    scorer = (
        'def score(gold, pred):\n'
        "    m = gold.merge(pred, on='id', suffixes=('_g', '_p'))\n"
        "    return float((m['y_g'] == m['y_p']).mean())\n"
    )
    gold = 'id,y\n1,1\n2,0\n3,1\n'
    pred = 'id,y\n1,1\n2,1\n3,1\n'
    r = run_custom_scorer(scorer, gold, pred, timeout=15)
    assert r['ok'] is True and abs(r['score'] - (2 / 3)) < 1e-6, r


def test_custom_scorer_rejected_and_error():
    assert run_custom_scorer('import socket\ndef score(g,p): return 1.0',
                             'id\n1', 'id\n1', timeout=5)['ok'] is False
    bad = 'def score(gold, pred):\n    raise ValueError("boom")\n'
    r = run_custom_scorer(bad, 'id,y\n1,1\n', 'id,y\n1,1\n', timeout=15)
    assert r['ok'] is False and 'boom' in r['error']
