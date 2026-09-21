# -*- coding: utf-8 -*-
"""DS 指标服务单测（v4.11）：各预置指标数值正确 + 格式/覆盖边界结构化报错。

纯 numpy/pandas，不触库不启子进程；custom 由 runner 负责，本文件只验证其被
score_from_frames 明确拒绝（防误当预置指标静默返回错分）。
"""
import numpy as np
import pandas as pd

from dsci.metrics import (METRICS, higher_is_better, is_preset, score_from_frames)


def _df(id_col, tgt_col, ids, tgts):
    return pd.DataFrame({id_col: ids, tgt_col: tgts})


CFG_CLS = {'metric': 'accuracy', 'id_column': 'id', 'target_column': 'label'}


def test_accuracy_basic():
    gold = _df('id', 'label', [1, 2, 3, 4], ['a', 'b', 'a', 'b'])
    pred = _df('id', 'label', [1, 2, 3, 4], ['a', 'b', 'b', 'b'])
    r = score_from_frames(pred, gold, CFG_CLS)
    assert r['status'] == 'ok' and abs(r['score'] - 0.75) < 1e-9


def test_accuracy_type_noise_tolerant():
    """预测 1 与 gold '1' 视为同类，避免 str/int 类型噪声误判错。"""
    gold = _df('id', 'label', [1, 2], [1, 0])
    pred = _df('id', 'label', [1, 2], ['1', '0'])
    assert score_from_frames(pred, gold, CFG_CLS)['score'] == 1.0


def test_f1_macro_binary_handcheck():
    gold = _df('id', 'y', [1, 2, 3, 4], [1, 1, 0, 0])
    pred = _df('id', 'y', [1, 2, 3, 4], [1, 0, 0, 0])
    # 类1: tp1 fp0 fn1 -> F1=2/(2+0+1)=0.6667; 类0: tp2 fp1 fn0 -> F1=4/(4+1+0)=0.8
    r = score_from_frames(pred, gold, {'metric': 'f1_macro', 'id_column': 'id', 'target_column': 'y'})
    assert r['status'] == 'ok' and abs(r['score'] - (0.6666667 + 0.8) / 2) < 1e-4


def test_rmse_mae():
    gold = _df('id', 'y', [1, 2, 3], [1.0, 2.0, 3.0])
    pred = _df('id', 'y', [1, 2, 3], [2.0, 2.0, 5.0])
    assert score_from_frames(pred, gold, {'metric': 'rmse', 'id_column': 'id', 'target_column': 'y'})['score'] == \
        round(float(np.sqrt((1 + 0 + 4) / 3)), 6)
    assert score_from_frames(pred, gold, {'metric': 'mae', 'id_column': 'id', 'target_column': 'y'})['score'] == \
        round(float((1 + 0 + 2) / 3), 6)


def test_auc_perfect_and_ties():
    gold = _df('id', 'y', [1, 2, 3, 4], [0, 0, 1, 1])
    pred = _df('id', 'y', [1, 2, 3, 4], [0.1, 0.2, 0.8, 0.9])
    assert score_from_frames(pred, gold, {'metric': 'auc', 'id_column': 'id', 'target_column': 'y'})['score'] == 1.0
    # 完全并列 -> AUC 0.5（秩并列取平均）
    pred_tie = _df('id', 'y', [1, 2, 3, 4], [0.5, 0.5, 0.5, 0.5])
    assert abs(score_from_frames(pred_tie, gold, {'metric': 'auc', 'id_column': 'id', 'target_column': 'y'})['score'] - 0.5) < 1e-9


def test_auc_requires_two_classes():
    gold = _df('id', 'y', [1, 2], [1, 1])
    pred = _df('id', 'y', [1, 2], [0.6, 0.7])
    r = score_from_frames(pred, gold, {'metric': 'auc', 'id_column': 'id', 'target_column': 'y'})
    assert r['status'] == 'error' and '二分类' in r['error']


def test_missing_id_coverage_error():
    gold = _df('id', 'y', [1, 2, 3], [1, 0, 1])
    pred = _df('id', 'y', [1, 2], [1, 0])   # 缺 id=3
    r = score_from_frames(pred, gold, CFG_CLS)
    assert r['status'] == 'error' and '缺少' in r['error']


def test_missing_column_error():
    gold = _df('id', 'y', [1, 2], [1, 0])
    pred = _df('id', 'wrong', [1, 2], [1, 0])
    r = score_from_frames(pred, gold, {'metric': 'accuracy', 'id_column': 'id', 'target_column': 'y'})
    assert r['status'] == 'error' and '缺少列' in r['error']


def test_non_numeric_regression_error():
    gold = _df('id', 'y', [1, 2], [1.0, 2.0])
    pred = _df('id', 'y', [1, 2], ['a', 'b'])
    r = score_from_frames(pred, gold, {'metric': 'rmse', 'id_column': 'id', 'target_column': 'y'})
    assert r['status'] == 'error'


def test_custom_not_scored_here():
    gold = _df('id', 'y', [1, 2], [1, 0])
    pred = _df('id', 'y', [1, 2], [1, 0])
    r = score_from_frames(pred, gold, {'metric': 'custom', 'id_column': 'id', 'target_column': 'y'})
    assert r['status'] == 'error' and '沙箱' in r['error']


def test_unknown_metric_and_direction():
    gold = _df('id', 'y', [1], [1])
    assert score_from_frames(gold, gold, {'metric': 'nope', 'id_column': 'id', 'target_column': 'y'})['status'] == 'error'
    assert is_preset('accuracy') and not is_preset('custom')
    assert higher_is_better('rmse') is False
    assert higher_is_better('accuracy') is True
    assert higher_is_better('custom', custom_override=False) is False
    assert set(METRICS) >= {'accuracy', 'f1_macro', 'rmse', 'mae', 'auc', 'custom'}
