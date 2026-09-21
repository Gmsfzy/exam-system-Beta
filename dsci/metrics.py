# -*- coding: utf-8 -*-
"""数据科学赛指标服务（v4.11）：纯 numpy/pandas，不依赖 sklearn/scipy。

评分契约：
- score_from_frames(pred_df, gold_df, cfg) 收到的是已按同一 id 子集对齐前的两片帧，
  内部做 id 内连接与列校验，任何格式/覆盖问题返回结构化 {status:'error', error:...}
  而不抛异常（评分器永不被脏数据打崩）。
- 公榜 = 用 public 子集 gold 评分，私榜 = 用全量 gold 评分；两者用同一套指标实现。
- 预置指标方向内置于 METRICS；custom 由教师设定 higher_is_better，走 runner 执行。
"""
import numpy as np

# 指标登记表：higher=True 越大越好，False 越小越好；kind 决定预处理方式
METRICS = {
    'accuracy':  {'label': '准确率',   'higher': True,  'kind': 'class'},
    'f1_macro':  {'label': '宏平均F1', 'higher': True,  'kind': 'class'},
    'rmse':      {'label': 'RMSE',     'higher': False, 'kind': 'reg'},
    'mae':       {'label': 'MAE',      'higher': False, 'kind': 'reg'},
    'auc':       {'label': 'AUC',      'higher': True,  'kind': 'auc'},
    'custom':    {'label': '自定义',   'higher': True,  'kind': 'custom'},
}


def is_preset(metric):
    return metric in METRICS and metric != 'custom'


def higher_is_better(metric, custom_override=None):
    """预置指标方向内置；custom 取教师显式设定（缺省按越大越好）。"""
    if metric == 'custom':
        return bool(custom_override) if custom_override is not None else True
    return METRICS.get(metric, {}).get('higher', True)


def _as_class(series):
    """分类标签统一成可比较字符串（消除 1 与 '1'、True 与 1 的类型噪声）。"""
    return np.array([str(x).strip() for x in series.tolist()], dtype=object)


def _as_float(series):
    return np.array([float(x) for x in series.tolist()], dtype=float)


def _accuracy(y_true, y_pred):
    return float(np.mean(y_pred == y_true))


def _f1_macro(y_true, y_pred):
    labels = np.unique(np.concatenate([np.unique(y_true), np.unique(y_pred)]))
    f1s = []
    for lb in labels:
        tp = np.sum((y_pred == lb) & (y_true == lb))
        fp = np.sum((y_pred == lb) & (y_true != lb))
        fn = np.sum((y_pred != lb) & (y_true == lb))
        denom = (2 * tp + fp + fn)
        f1s.append(0.0 if denom == 0 else (2 * tp) / denom)
    return float(np.mean(f1s)) if f1s else 0.0


def _rmse(y_true, y_pred):
    return float(np.sqrt(np.mean((y_pred - y_true) ** 2)))


def _mae(y_true, y_pred):
    return float(np.mean(np.abs(y_pred - y_true)))


def _auc(y_true, y_score):
    """二分类 AUC，Mann-Whitney U 秩公式（并列取平均秩），sklearn-free。"""
    labels = np.unique(y_true)
    if set(labels.tolist()) != {0, 1}:
        raise ValueError('AUC 仅支持二分类（gold 标签需为 0/1）')
    pos = y_score[y_true == 1]
    neg = y_score[y_true == 0]
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        raise ValueError('AUC 需正负两类样本')
    all_scores = np.concatenate([pos, neg])
    order = np.argsort(all_scores, kind='mergesort')
    ranks = np.empty(len(all_scores), dtype=float)
    ranks[order] = np.arange(1, len(all_scores) + 1)
    # 并列取平均秩
    sorted_scores = all_scores[order]
    i = 0
    while i < len(sorted_scores):
        j = i
        while j + 1 < len(sorted_scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        if j > i:
            avg = (i + 1 + j + 1) / 2.0
            ranks[order[i:j + 1]] = avg
        i = j + 1
    sum_pos_ranks = ranks[:n_pos].sum()
    return float((sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def score_from_frames(pred_df, gold_df, cfg):
    """按 cfg 对齐预测与答案并评分。

    cfg: {metric, id_column, target_column}
    返回：{status:'ok', score: float} 或 {status:'error', error: str}
    """
    metric = cfg.get('metric')
    id_col = cfg.get('id_column')
    tgt_col = cfg.get('target_column')
    if metric not in METRICS:
        return {'status': 'error', 'error': f'未知指标：{metric}'}
    if not id_col or not tgt_col:
        return {'status': 'error', 'error': '未配置主键列/目标列'}
    for name, df in (('预测', pred_df), ('答案', gold_df)):
        if id_col not in df.columns or tgt_col not in df.columns:
            return {'status': 'error',
                    'error': f'{name}文件缺少列「{id_col}」或「{tgt_col}」'}

    merged = gold_df[[id_col, tgt_col]].merge(
        pred_df[[id_col, tgt_col]], on=id_col, how='left', suffixes=('', '_pred'))
    if merged[tgt_col + '_pred'].isna().any():
        miss = int(merged[tgt_col + '_pred'].isna().sum())
        return {'status': 'error',
                'error': f'预测缺少 {miss} 个样本的 {tgt_col}（须覆盖全部 {id_col}）'}

    kind = METRICS[metric]['kind']
    try:
        if kind == 'class':
            y_true = _as_class(merged[tgt_col])
            y_pred = _as_class(merged[tgt_col + '_pred'])
            score = _accuracy(y_true, y_pred) if metric == 'accuracy' else _f1_macro(y_true, y_pred)
        elif kind == 'reg':
            y_true = _as_float(merged[tgt_col])
            y_pred = _as_float(merged[tgt_col + '_pred'])
            if not (np.isfinite(y_pred).all()):
                return {'status': 'error', 'error': '预测含非数值或 NaN'}
            score = _rmse(y_true, y_pred) if metric == 'rmse' else _mae(y_true, y_pred)
        elif kind == 'auc':
            y_true = _as_float(merged[tgt_col])
            y_pred = _as_float(merged[tgt_col + '_pred'])
            if not (np.isfinite(y_pred).all()):
                return {'status': 'error', 'error': '预测含非数值或 NaN'}
            score = _auc(y_true, y_pred)
        else:  # custom：本函数不处理，由 runner 沙箱执行教师 scorer
            return {'status': 'error', 'error': 'custom 指标须经沙箱评分器处理'}
    except (ValueError, TypeError) as exc:
        return {'status': 'error', 'error': f'数据无法按 {metric} 评分：{exc}'}
    except Exception as exc:  # 数值异常不外泄为 500
        return {'status': 'error', 'error': f'评分异常：{exc}'}

    if score is None or not np.isfinite(score):
        return {'status': 'error', 'error': '评分结果非有限数'}
    return {'status': 'ok', 'score': round(float(score), 6)}
