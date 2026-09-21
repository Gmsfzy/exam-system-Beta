# -*- coding: utf-8 -*-
"""数据科学竞赛（v4.11）：数据集 + 在线运行 + 自动指标评分 + 公/私榜。

复用 competition.Competition 作为宿主（沿用 ledger 托管/结算、交叉审核、
邀请码门禁、公告、通知），本包只承载 DS 赛道专有的数据与逻辑：
- models：数据集/文件、提交、在线运行留痕
- metrics：sklearn-free 指标（accuracy/f1_macro/rmse/mae/auc）+ 自定义 scorer 约定
- runner：放开 open() 的 jail 子进程执行器（复用 oj.runner 基座）
- routes：dsci_bp（挂 /api）
"""
