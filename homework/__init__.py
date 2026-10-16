# -*- coding: utf-8 -*-
"""作业练习模块（v5.0，第五大业务模块）：教师发布/编辑/批改，学生经通知作答提交。

- models：homework / homework_question / homework_student / homework_submission / homework_answer
- services：判分引擎（客观题 check_objective + 编程题 OJ 通过率 + 主观题待人工）、
  时效调度 tick（到期锁定 / 未交提醒，reminded_at CAS 幂等）
- routes：homework_bp（挂 /api，前缀 /homeworks）

设计边界：纯教务，不触碰 ledger/积分（防大量提交刷分向量）；
题集式复用 api/exam_engine 与 oj/ 判分基座，开放式附件复用 utils/uploads 白名单。
"""
