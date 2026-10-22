# -*- coding: utf-8 -*-
"""作业判分与时效服务（v5.0）。

判分口径与考试链路一致但独立实现（避免耦合 ExamSession 结构）：
- 客观题：api/exam_engine.check_objective 单一判分事实源（单选/多选/填空/判断）
- 编程题（有 test_cases）：oj.services.grade 按通过率折算，记 oj_verdict；空码 CE
- 其余主观题/开放式：needs_manual_grade=True，待教师逐题/整体给分
作业不进 ledger：此处只落 HomeworkSubmission/HomeworkAnswer，无任何积分/钱包写入。
"""
import json

from database import db
from database.models import Question, QuestionTypeEnum, User
from utils.logger import logger
from utils.timeutil import utcnow, iso_local
from utils.notify import create_notification
from homework.models import (
    Homework, HomeworkStatusEnum, HomeworkTypeEnum, HomeworkSubmission,
    HomeworkAnswer, SubmissionStatusEnum,
)


def grade_submission(hw, sub):
    """对题集式提交逐题判分（重交覆盖时全量重算并清人工分）。

    返回 (auto_earned, max_total)；调用方负责 commit。
    未作答的题目补记空作答行（自动 0 分 / 主观空答不送人工），与考试收卷语义一致。
    """
    from api.exam_engine import check_objective

    hqs = sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))
    q_ids = [hq.question_id for hq in hqs]
    qmap = {q.id: q for q in Question.query.filter(Question.id.in_(q_ids)).all()} if q_ids else {}
    amap = {a.question_id: a for a in sub.answers}
    earned = 0.0
    total = 0.0
    for hq in hqs:
        total += hq.score or 0
        q = qmap.get(hq.question_id)
        a = amap.get(hq.question_id)
        if a is None:
            a = HomeworkAnswer(submission_id=sub.id, question_id=hq.question_id, answer='')
            db.session.add(a)
            sub.answers.append(a)
        # 重交覆盖：清空上一轮人工批改痕迹
        a.manual_score = None
        a.comment = None
        if not q:
            a.needs_manual_grade = False
            a.is_correct = False
            a.auto_score = 0.0
            continue
        text = (a.answer or '').strip()

        # 编程题 OJ：有用例即机器判（与考试/练习链路同一口径）
        if q.type == QuestionTypeEnum.PROGRAMMING and getattr(q, 'test_cases', None):
            a.needs_manual_grade = False
            if not text:
                a.oj_verdict, a.is_correct, a.auto_score = 'CE', False, 0.0
            else:
                from oj.services import grade as oj_grade
                r = oj_grade(text, 'python', q.test_cases)
                if r['supported']:
                    ratio = (r['passed'] / r['total']) if r['total'] else 0.0
                    a.oj_verdict = r['verdict']
                    a.is_correct = r['verdict'] == 'AC'
                    a.auto_score = round((hq.score or 0) * ratio, 2)
                else:
                    a.needs_manual_grade = True   # 语言不支持评测 → 回落人工
                    a.auto_score = None
            if not a.needs_manual_grade:
                earned += a.auto_score or 0.0
            continue

        if QuestionTypeEnum.is_subjective(q.type):
            if not text:
                a.needs_manual_grade = False
                a.is_correct = False
                a.auto_score = 0.0
            else:
                a.needs_manual_grade = True
                a.is_correct = None
                a.auto_score = None
            continue

        ok, ratio = check_objective(q.type, text, (q.answer or '').strip())
        a.needs_manual_grade = False
        a.is_correct = ok
        a.auto_score = round((hq.score or 0) * ratio, 2)
        earned += a.auto_score
    sub.max_score = round(total, 2)
    sub.total_score = None   # 含人工待批则总分以批改完成为准
    return round(earned, 2), round(total, 2)


def recompute_total(sub):
    """按当前作答有效分汇总总分（批改调用后复用）。返回 (earned, max_total, pending_manual)。"""
    earned = round(sum(a.effective_score for a in sub.answers), 2)
    max_total = sub.max_score or round(sum(
        (hq.score or 0) for hq in sub.homework.hw_questions), 2)
    pending = [a for a in sub.answers if a.needs_manual_grade and a.manual_score is None]
    sub.total_score = earned
    sub.max_score = max_total
    return earned, max_total, len(pending)


def finalize_submission(hw, sub):
    """提交/重交落状态：题集式走自动判分，开放式整体待批。"""
    if hw.hw_type == HomeworkTypeEnum.QUESTION_SET:
        grade_submission(hw, sub)
    else:
        sub.max_score = None
        sub.total_score = None
    sub.status = SubmissionStatusEnum.SUBMITTED
    sub.submitted_at = utcnow()
    sub.is_late = bool(hw.is_expired)
    return sub


def notify_homework_students(hw, title, content, only_unsubmitted=False):
    """批量通知名单学生：commit=False 由调用方统一提交（遵守循环内不逐行 commit 规范）。

    实时推送由 ORM 事件（utils/notify_socket）在调用方 commit 后自动发出，此处无需手动推。"""
    submitted_ids = set()
    if only_unsubmitted:
        submitted_ids = {s.student_id for s in hw.submissions
                         if s.status in (SubmissionStatusEnum.SUBMITTED,
                                         SubmissionStatusEnum.GRADED)}
    n = 0
    for hs in hw.hw_students:
        if hs.student_id in submitted_ids:
            continue
        create_notification(hs.student_id, title, content, type='info',
                            related_type='homework', related_id=hw.id, commit=False)
        n += 1
    return n


def homework_expiry_tick():
    """后台调度任务：到期锁定 + 截止前未交提醒（各自独立事务，单点失败不阻塞其余）。

    1) published 且已过 deadline 且 allow_late=False → 自动 closed（迟交通道关闭）
    2) published 且 remind_before>0 且未提醒过 且 now >= deadline-提醒窗口 →
       给未提交学生发提醒；reminded_at 条件 UPDATE CAS 抢占，多进程/多轮幂等
    """
    now = utcnow()
    # 1) 到期锁定
    due = Homework.query.filter(Homework.status == HomeworkStatusEnum.PUBLISHED,
                                 Homework.deadline < now,
                                 Homework.allow_late == False).all()  # noqa: E712
    for hw in due:
        try:
            hw.status = HomeworkStatusEnum.CLOSED
            db.session.commit()
            logger.info(f'[homework] 作业 {hw.id} 截止且不允许迟交，已自动关闭')
        except Exception:
            db.session.rollback()
            logger.error(f'[homework] 到期关闭失败 hw={hw.id}', exc_info=True)
    # 2) 截止前提醒
    to_remind = Homework.query.filter(Homework.status == HomeworkStatusEnum.PUBLISHED,
                                      Homework.remind_before > 0,
                                      Homework.reminded_at.is_(None)).all()
    for hw in to_remind:
        try:
            if hw.deadline is None:
                continue
            from datetime import timedelta
            remind_at = hw.deadline - timedelta(minutes=hw.remind_before)
            if now < remind_at or now > hw.deadline:
                continue
            # CAS 抢占提醒权（并发/多进程幂等）
            res = db.session.execute(
                db.text('UPDATE homework SET reminded_at = :now '
                        'WHERE id = :id AND reminded_at IS NULL'),
                {'now': now, 'id': hw.id})
            if res.rowcount != 1:
                db.session.rollback()
                continue
            db.session.refresh(hw)
            title = '作业即将截止'
            content = f'《{hw.title}》将于 {iso_local(hw.deadline)} 截止，请尽快提交。'
            notify_homework_students(hw, title, content, only_unsubmitted=True)
            db.session.commit()
            logger.info(f'[homework] 作业 {hw.id} 截止提醒已发送给未提交学生')
        except Exception:
            db.session.rollback()
            logger.error(f'[homework] 截止提醒失败 hw={hw.id}', exc_info=True)


# v5.2 错题收录判错阈值：得分率（effective_score/满分）低于该值才入错题本；
# 未满分但 ≥60% 视为基本掌握不打扰，与「错题本聚焦薄弱环节」定位一致。
WRONG_SYNC_RATIO = 0.6


def sync_learning_effects(hw, sub, scope):
    """作业→学习闭环联动（v5.2）：错题收录 + 知识点掌握度 EWMA。

    作业判分是两段式，对应两个 scope，按 needs_manual_grade 划分集合、互不重叠，
    避免 wrong_count 双计：
    - scope='auto'：提交/重交后调用，处理客观题+OJ（提交时已自动判分）
    - scope='final'：批改完成（首次转 GRADED）后调用，处理人工判分题
    判错标准：得分率 < WRONG_SYNC_RATIO；掌握度口径与考试一致（客观 1/0、主观得分率）。
    非关键路径：调用方 try/except；内部统一 commit（sync_wrong_from_answers 亦自提交）。
    """
    from api.learning_routes import sync_wrong_from_answers
    from api.learning_engine import kp_ids_of_question, update_mastery

    want_manual = (scope == 'final')
    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
    q_ids = [a.question_id for a in sub.answers]
    qmap = {q.id: q for q in Question.query.filter(Question.id.in_(q_ids)).all()} if q_ids else {}
    wrong = []
    bucket = {}
    for a in sub.answers:
        if bool(a.needs_manual_grade) != want_manual:
            continue
        hq = hq_map.get(a.question_id)
        q = qmap.get(a.question_id)
        if not hq or not q:
            continue
        full = hq.score or 0
        if full <= 0:
            continue
        ratio = max(0.0, min(1.0, (a.effective_score or 0.0) / full))
        if ratio < WRONG_SYNC_RATIO:
            wrong.append((a.question_id, a.answer or '', q.answer or ''))
        kps = kp_ids_of_question(q.id)
        if kps:
            obs = ratio if QuestionTypeEnum.is_subjective(q.type) \
                else (1.0 if a.is_correct else 0.0)
            for kp_id in kps:
                bucket.setdefault(kp_id, []).append(obs)
    recipients = learning_recipients(hw, sub)
    synced = 0
    for uid in recipients:
        if wrong:
            synced += sync_wrong_from_answers(uid, 'homework', hw.id, wrong)
        for kp_id, ratios in bucket.items():
            update_mastery(uid, [kp_id], sum(ratios) / len(ratios))
    db.session.commit()
    return synced


def learning_recipients(hw, sub):
    """学习闭环受益学生：小组作业取全组成员（v5.9 修复仅同步最后提交人），个人作业取提交人。"""
    if getattr(hw, 'is_group', False) and getattr(sub, 'group_id', None):
        from homework.models import HomeworkGroup
        grp = db.session.get(HomeworkGroup, sub.group_id)
        if grp and grp.members:
            return [m.student_id for m in grp.members]
    return [sub.student_id] if sub.student_id else []


# ═══════════════ 作业积分入账（v5.10） ═══════════════
# 口径：最终提交发基础分（每生每份作业一次，重交不重复）；批改完成后按得分率补发质量分。
# 走统一 ledger（points/award，scope=当前赛季）并镜像用户赛季档案，与竞技积分同口径。

HOMEWORK_SUBMIT_POINTS = 10
HOMEWORK_GRADE_BONUS_MAX = 20


def _award_homework_points(user_id, delta, hw, idempotency_key, memo):
    """单笔作业积分入账（幂等）：重复键返回 0，调用方负责 commit。"""
    delta = int(delta or 0)
    if delta <= 0 or not user_id:
        return 0
    from competition.gamification import current_season, ensure_profile, upsert_points_history
    from ledger.core import post
    from ledger.models import LedgerTxn

    if LedgerTxn.query.filter_by(idempotency_key=idempotency_key).first():
        return 0
    season = current_season()
    post(user_id, 'points', delta, 'award', scope=season, ref_type='homework',
         ref_id=hw.id, memo=memo, idempotency_key=idempotency_key)
    profile = ensure_profile(user_id, season)
    profile.points = (profile.points or 0) + delta
    profile.last_played_at = utcnow()
    upsert_points_history(user_id, season, profile.points)
    return delta


def award_homework_submit_points(hw, sub):
    """最终提交入账：基础分 10（小组作业全组成员各一份），重交不重复。返回实发总额。"""
    awarded = 0
    for uid in learning_recipients(hw, sub):
        awarded += _award_homework_points(
            uid, HOMEWORK_SUBMIT_POINTS, hw,
            f'homework-submit:{hw.id}:{uid}', f'作业提交：《{hw.title[:40]}》')
    db.session.commit()
    return awarded


def award_homework_grade_bonus(hw, sub):
    """批改完成后按得分率补发 0–20 分（独立幂等键，重批不重复）。返回实发总额。"""
    if not sub.max_score or sub.max_score <= 0 or sub.total_score is None:
        return 0
    ratio = max(0.0, min(1.0, float(sub.total_score) / float(sub.max_score)))
    bonus = int(round(HOMEWORK_GRADE_BONUS_MAX * ratio))
    awarded = 0
    for uid in learning_recipients(hw, sub):
        awarded += _award_homework_points(
            uid, bonus, hw,
            f'homework-grade:{hw.id}:{uid}',
            f'作业质量：《{hw.title[:40]}》得分率 {ratio:.0%}')
    db.session.commit()
    return awarded


def ai_suggest_grading(sub):
    """AI 辅助批改建议（不落库）：对每个待人工作答调用 ai_client.grade_answer。

    返回 {suggestions: [{answer_id, suggestion_id?, score, comment}], failed: n}；
    score 已按题目满分换算（AI 原始返回 0-100 百分比，同考试 clamp 口径）。
    """
    from ai_service.services import ai_client
    hw = sub.homework
    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
    suggestions = []
    failed = 0
    for a in sub.answers:
        if not a.needs_manual_grade or a.manual_score is not None:
            continue
        q = db.session.get(Question, a.question_id)
        hq = hq_map.get(a.question_id)
        if not q or not hq:
            continue
        try:
            result = ai_client.grade_answer(q.content, q.answer or '', a.answer or '')
            data = json.loads(result)
            ratio = max(0.0, min(float(data.get('score', 0) or 0), 100.0)) / 100.0
            suggestions.append({
                'answer_id': a.id, 'question_id': a.question_id,
                'score': round(ratio * (hq.score or 0), 2), 'max_score': hq.score,
                'is_correct': bool(data.get('is_correct', False)),
                'comment': str(data.get('comment') or data.get('analysis') or '')[:500],
            })
        except Exception:
            failed += 1
            logger.debug(f'[homework] AI 建议失败 answer={a.id}（非关键路径）', exc_info=True)
    return {'suggestions': suggestions, 'failed': failed}


# ═══════════════ v5.3 AI 讲评：班级共性分析 + 单份讲评 ═══════════════

AI_REVIEW_MODEL = 'ark-chat'
WEAK_RATIO = 0.6          # 得分率低于该值视为薄弱题/知识点
MAX_WEAK_QUESTIONS = 8    # 讲评聚焦的薄弱题上限


def _clamp_ratio(value):
    try:
        return round(max(0.0, min(float(value), 1.0)), 4)
    except (TypeError, ValueError):
        return 0.0


def _clip(text, limit=120):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit] + '…'


def _submitted_list(hw):
    return [s for s in hw.submissions
            if s.status != SubmissionStatusEnum.DRAFT]


def _class_stats(hw):
    """班级统计快照（纯本地聚合，不依赖 AI）：提交率、平均分、题目得分率、知识点薄弱项。

    只统计已提交的答卷；题目级指标以「平均得分率」为主，客观题附选项分布与正确率。
    数据结构即前端展示与 AI prompt 的公共输入，AI 失败时仍完整可用。
    """
    from api.learning_engine import kp_ids_of_question
    from database.models import KnowledgePoint

    subs = _submitted_list(hw)
    graded = [s for s in subs if s.status == SubmissionStatusEnum.GRADED]
    roster = len(hw.hw_students)
    scored = [s for s in graded if s.total_score is not None]
    full = hw.max_score() or 0.0
    avg_score = round(sum(s.total_score for s in scored) / len(scored), 2) if scored else None
    avg_ratio = _clamp_ratio(avg_score / full) if (scored and full > 0) else None
    pass_score = getattr(hw, 'pass_score', None)
    pass_rate = None
    if scored and pass_score is not None:
        pass_rate = round(sum(1 for s in scored if s.total_score >= pass_score) / len(scored) * 100, 1)

    stats = {
        'homework_id': hw.id, 'title': hw.title, 'hw_type': hw.hw_type,
        'max_score': full, 'total_students': roster, 'submitted': len(subs),
        'submitted_rate': round(len(subs) / roster * 100, 1) if roster else 0.0,
        'graded': len(graded), 'late': sum(1 for s in subs if s.is_late),
        'avg_score': avg_score, 'avg_ratio': avg_ratio, 'pass_rate': pass_rate,
        'questions': [], 'weak_questions': [], 'knowledge_points': [],
        'weak_knowledge_points': [],
    }
    if hw.hw_type == HomeworkTypeEnum.OPEN:
        return stats

    hqs = sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))
    answers_by_q = {}
    for sub in subs:
        for a in sub.answers:
            answers_by_q.setdefault(a.question_id, []).append(a)

    kp_bucket = {}
    for hq in hqs:
        q = db.session.get(Question, hq.question_id)
        if not q:
            continue
        rows = answers_by_q.get(hq.question_id, [])
        question_full = hq.score or 0.0
        ratios = [_clamp_ratio((a.effective_score or 0.0) / question_full)
                  for a in rows] if question_full > 0 else []
        avg_ratio_q = round(sum(ratios) / len(ratios), 4) if ratios else None
        attempts = len(rows)
        item = {
            'question_id': q.id, 'content': _clip(q.content, 90), 'type': q.type,
            'score': question_full, 'attempts': attempts, 'avg_ratio': avg_ratio_q,
            'avg_score': round(sum((a.effective_score or 0.0) for a in rows) / attempts, 2)
            if attempts else None,
            'correct_rate': round(sum(1 for a in rows if a.is_correct) / attempts * 100, 1)
            if attempts else None,
            'is_weak': bool(avg_ratio_q is not None and avg_ratio_q < WEAK_RATIO),
        }
        if not QuestionTypeEnum.is_subjective(q.type):
            dist = {}
            for a in rows:
                key = str(a.answer or '').strip().upper()
                if key:
                    dist[key] = dist.get(key, 0) + 1
            item['answer_distribution'] = dict(sorted(dist.items(),
                                                       key=lambda kv: -kv[1])[:6])
        stats['questions'].append(item)

        if avg_ratio_q is not None:
            for kp_id in kp_ids_of_question(q.id):
                kp_bucket.setdefault(kp_id, []).append(avg_ratio_q)

    stats['weak_questions'] = sorted(
        [q for q in stats['questions'] if q['is_weak']],
        key=lambda x: (x['avg_ratio'], -(x['attempts'] or 0)))[:MAX_WEAK_QUESTIONS]

    if kp_bucket:
        kps = {k.id: k for k in KnowledgePoint.query.filter(
            KnowledgePoint.id.in_(list(kp_bucket))).all()}
        rows = []
        for kp_id, ratios in kp_bucket.items():
            kp = kps.get(kp_id)
            if not kp:
                continue
            rows.append({'id': kp_id, 'name': kp.name,
                         'avg_ratio': round(sum(ratios) / len(ratios), 4),
                         'question_count': len(ratios)})
        rows.sort(key=lambda x: x['avg_ratio'])
        stats['knowledge_points'] = rows
        stats['weak_knowledge_points'] = [r for r in rows if r['avg_ratio'] < WEAK_RATIO]
    return stats


def _class_prompt(stats):
    lines = [
        f"作业《{stats['title']}》（{'开放式' if stats['hw_type'] == HomeworkTypeEnum.OPEN else '题集式'}）",
        f"应交 {stats['total_students']} 人，实交 {stats['submitted']} 人"
        f"（提交率 {stats['submitted_rate']}%），已批改 {stats['graded']} 份，迟交 {stats['late']} 份。",
    ]
    if stats['avg_score'] is not None:
        lines.append(f"平均分 {stats['avg_score']}/{stats['max_score']}"
                     f"（平均得分率 {round((stats['avg_ratio'] or 0) * 100, 1)}%）"
                     + (f"，及格率 {stats['pass_rate']}%" if stats['pass_rate'] is not None else '。'))
    if stats['weak_questions']:
        lines.append('薄弱题目（平均得分率 <60%）：')
        for i, q in enumerate(stats['weak_questions'], 1):
            seg = (f"{i}. [{q['type']}] {q['content']}｜满分 {q['score']}｜"
                   f"平均得分率 {round((q['avg_ratio'] or 0) * 100)}%｜作答 {q['attempts']} 人")
            if q.get('answer_distribution'):
                seg += f"｜答案分布 {q['answer_distribution']}"
            lines.append(seg)
    if stats['weak_knowledge_points']:
        lines.append('薄弱知识点：' + '；'.join(
            f"{k['name']}（{round(k['avg_ratio'] * 100)}%）"
            for k in stats['weak_knowledge_points'][:8]))
    if not stats['weak_questions'] and stats['submitted'] == 0:
        lines.append('注意：目前还没有学生提交，请仅基于提交情况给出教学提醒。')
    return '\n'.join(lines)


def _degraded_class_content(stats):
    """AI 不可用时的规则讲评：统计完整保留，文字由规则拼装（不阻断教师使用）。"""
    weak = stats['weak_questions']
    summary = (f"本次作业应交 {stats['total_students']} 人、实交 {stats['submitted']} 人"
               f"（提交率 {stats['submitted_rate']}%），已批改 {stats['graded']} 份。")
    if stats['avg_score'] is not None:
        summary += (f"平均分 {stats['avg_score']}/{stats['max_score']}"
                    f"，平均得分率 {round((stats['avg_ratio'] or 0) * 100, 1)}%。")
    summary += f"共有 {len(weak)} 道薄弱题目需要讲评。" if weak else "整体掌握情况良好。"
    mistakes = []
    for q in weak[:5]:
        mistake = f"平均得分率 {round((q['avg_ratio'] or 0) * 100)}%"
        if q.get('answer_distribution'):
            top = list(q['answer_distribution'].items())[0]
            mistake += f"，高频作答 {top[0]}（{top[1]} 人）"
        mistakes.append({'question': q['content'], 'mistake': mistake,
                         'advice': '建议课堂上还原解题思路，并补充同类变式练习。'})
    suggestions = []
    if weak:
        suggestions.append('优先讲评得分率低于 60% 的题目，按错误类型归类讲解。')
    if stats['weak_knowledge_points']:
        suggestions.append('针对薄弱知识点安排 10 分钟小测或变式训练。')
    if stats['submitted'] < stats['total_students']:
        suggestions.append('联系未提交学生，了解卡点并安排补交。')
    if stats['late']:
        suggestions.append('关注迟交学生的完成质量，必要时个别辅导。')
    return {'summary': summary, 'common_mistakes': mistakes,
            'weak_points': [k['name'] for k in stats['weak_knowledge_points']],
            'teaching_suggestions': suggestions or ['可安排一次整卷讲评，先梳理共性错因。']}


def _normalize_class_content(data, stats):
    if not isinstance(data, dict):
        return _degraded_class_content(stats)
    out = {'summary': str(data.get('summary') or '').strip()[:800],
           'common_mistakes': [], 'weak_points': [], 'teaching_suggestions': []}
    for row in (data.get('common_mistakes') or [])[:8]:
        if isinstance(row, dict):
            out['common_mistakes'].append({
                'question': str(row.get('question') or '')[:200],
                'mistake': str(row.get('mistake') or '')[:300],
                'advice': str(row.get('advice') or '')[:400],
            })
        elif row:
            out['common_mistakes'].append({'question': '', 'mistake': str(row)[:300],
                                           'advice': ''})
    out['weak_points'] = [str(x)[:60] for x in (data.get('weak_points') or [])[:10] if x]
    out['teaching_suggestions'] = [str(x)[:300] for x in
                                    (data.get('teaching_suggestions') or [])[:8] if x]
    if not out['summary']:
        out['summary'] = _degraded_class_content(stats)['summary']
    if not out['teaching_suggestions']:
        out['teaching_suggestions'] = _degraded_class_content(stats)['teaching_suggestions']
    return out


def build_class_review(hw):
    """生成班级共性分析：本地统计 + AI 文字解读；AI 失败降级规则讲评。

    返回 {'stats': dict, 'content': dict, 'degraded': bool}；不落库（路由层负责 upsert）。
    """
    stats = _class_stats(hw)
    if not stats['submitted']:
        return {'stats': stats, 'content': _degraded_class_content(stats),
                'degraded': True}
    try:
        from ai_service.services import ai_client
        raw = ai_client.generate_json(
            '你是经验丰富的学科教师与教研员，擅长根据作业数据撰写班级讲评。'
            '只输出 JSON：{"summary": "整体讲评 120 字内", '
            '"common_mistakes": [{"question": "题目简述", "mistake": "共性错因", '
            '"advice": "讲评建议"}], "weak_points": ["薄弱知识点"], '
            '"teaching_suggestions": ["讲评课建议 3-5 条"]}。'
            '要求：面向教师，结论必须来自给定数据，不臆造学生姓名。',
            _class_prompt(stats), temp=0.4, max_tok=2200)
        data = json.loads(raw)
        return {'stats': stats, 'content': _normalize_class_content(data, stats),
                'degraded': False}
    except Exception:
        logger.warning(f'[homework] 班级 AI 讲评失败，降级规则讲评 hw={hw.id}', exc_info=True)
        return {'stats': stats, 'content': _degraded_class_content(stats),
                'degraded': True}


def _submission_stats(hw, sub):
    """单份答卷的逐题明细（仅教师批改场景调用，含答案比对）。"""
    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
    details = []
    for a in sorted(sub.answers, key=lambda x: (hq_map.get(x.question_id).order or 0)
                    if hq_map.get(x.question_id) else 0):
        hq = hq_map.get(a.question_id)
        q = db.session.get(Question, a.question_id)
        if not hq or not q:
            continue
        full = hq.score or 0.0
        details.append({
            'question_id': q.id, 'content': _clip(q.content, 100), 'type': q.type,
            'answer': _clip(a.answer or '', 200), 'correct_answer': _clip(q.answer or '', 120),
            'score': round(a.effective_score or 0.0, 2), 'max_score': full,
            'is_correct': bool(a.is_correct),
            'ratio': _clamp_ratio((a.effective_score or 0.0) / full) if full else 0.0,
        })
    full_total = sum(hq_map[qid].score or 0 for qid in hq_map) if hq_map else 0.0
    return {'total_score': sub.total_score, 'max_score': sub.max_score or full_total,
            'ratio': _clamp_ratio((sub.total_score or 0.0) / (sub.max_score or full_total or 1)),
            'questions': details}


def _degraded_submission_content(stats):
    ratio = round((stats['ratio'] or 0) * 100, 1)
    wrong = [d for d in stats['questions'] if not d['is_correct'] and d['score'] < d['max_score']]
    summary = (f"本次作业得分 {stats['total_score']}/{stats['max_score']}"
               f"（得分率 {ratio}%）。")
    summary += f"有 {len(wrong)} 道题未完全掌握，建议逐题复盘。" if wrong else "全部答对，掌握扎实。"
    strengths = []
    right = [d for d in stats['questions'] if d['is_correct']]
    if right:
        strengths.append(f"答对 {len(right)} 道题，基础掌握较好。")
    improvements = [{'point': d['content'],
                     'advice': f"该题得分 {d['score']}/{d['max_score']}，建议对照正确答案复盘思路。"}
                    for d in wrong[:6]]
    next_steps = ['把本次错题加入错题本并按计划重做。']
    if wrong:
        next_steps.append('针对失分知识点补充 2-3 道同类变式题。')
    if ratio < 60:
        next_steps.append('主动向老师或同学请教未理解的部分。')
    return {'summary': summary, 'strengths': strengths,
            'improvements': improvements, 'next_steps': next_steps}


def _normalize_submission_content(data, stats):
    if not isinstance(data, dict):
        return _degraded_submission_content(stats)
    out = {'summary': str(data.get('summary') or '').strip()[:800],
           'strengths': [str(x)[:200] for x in (data.get('strengths') or [])[:6] if x],
           'improvements': [], 'next_steps': [str(x)[:200] for x in
                                              (data.get('next_steps') or [])[:6] if x]}
    for row in (data.get('improvements') or [])[:8]:
        if isinstance(row, dict):
            out['improvements'].append({'point': str(row.get('point') or '')[:200],
                                        'advice': str(row.get('advice') or '')[:400]})
        elif row:
            out['improvements'].append({'point': str(row)[:200], 'advice': ''})
    if not out['summary']:
        out['summary'] = _degraded_submission_content(stats)['summary']
    return out


def build_submission_review(hw, sub):
    """生成单份 AI 讲评（教师触发，基于该生答题明细）。AI 失败降级规则讲评。"""
    stats = _submission_stats(hw, sub)
    if sub.status != SubmissionStatusEnum.GRADED:
        # 未批改时得分不完整，讲评易误导；由路由层拦截，这里兜底降级
        return {'stats': stats, 'content': _degraded_submission_content(stats),
                'degraded': True}
    if hw.hw_type == HomeworkTypeEnum.OPEN:
        body = f"开放式作业正文（节选）：{_clip(sub.content or '', 1500)}"
    else:
        body = '\n'.join(
            f"{i}. [{d['type']}] {d['content']}\n   学生答案：{d['answer'] or '（空）'}\n"
            f"   正确答案：{d['correct_answer']}\n   得分：{d['score']}/{d['max_score']}"
            for i, d in enumerate(stats['questions'][:25], 1))
    prompt = (f"作业《{hw.title}》单份答卷：总分 {stats['total_score']}/{stats['max_score']}。\n{body}")
    try:
        from ai_service.services import ai_client
        raw = ai_client.generate_json(
            '你是耐心的学科教师，为学生撰写本次作业的个性化讲评。只输出 JSON：'
            '{"summary": "总评 120 字内", "strengths": ["做得好的地方"], '
            '"improvements": [{"point": "失分知识点或题型", "advice": "改进建议"}], '
            '"next_steps": ["下一步行动 2-3 条"]}。'
            '语气鼓励、具体，不臆造未提供的信息。',
            prompt, temp=0.5, max_tok=1800)
        data = json.loads(raw)
        return {'stats': stats, 'content': _normalize_submission_content(data, stats),
                'degraded': False}
    except Exception:
        logger.warning(f'[homework] 单份 AI 讲评失败，降级规则讲评 sub={sub.id}', exc_info=True)
        return {'stats': stats, 'content': _degraded_submission_content(stats), 'degraded': True}


def upsert_ai_review(hw, scope, result, created_by, submission_id=None):
    """讲评结果落库（同作业同 scope 覆盖旧结果），返回 HomeworkAiReview 记录。"""
    from homework.models import HomeworkAiReview

    scope_key = 'class' if scope == 'class' else f'sub:{submission_id}'
    rec = HomeworkAiReview.query.filter_by(homework_id=hw.id, scope_key=scope_key).first()
    if rec is None:
        rec = HomeworkAiReview(homework_id=hw.id, scope=scope, scope_key=scope_key,
                               submission_id=submission_id, created_by=created_by)
        db.session.add(rec)
    rec.content_json = result['content']
    rec.stats_json = result['stats']
    rec.degraded = bool(result.get('degraded'))
    rec.model = 'rule-fallback' if result.get('degraded') else AI_REVIEW_MODEL
    rec.created_by = created_by
    rec.updated_at = utcnow()
    db.session.commit()
    return rec


# ═══════════════ v5.5 生生互评 / v5.9 深度互评：分配 / 汇总 / 审核 / 匿名结果 ═══════════════

PEER_REVIEW_PER_SUBMISSION = 2   # 默认每份作业分配 2 位同学互评
PEER_REVIEW_MAX_PER_SUBMISSION = 5
# v5.9 互评维度（权重合计 1.0；前端按此渲染评分项并展示加权预览）
PEER_REVIEW_DIMENSIONS = (
    {'key': 'accuracy', 'label': '准确性', 'weight': 0.4,
     'hint': '答案/结论是否正确，论据是否可靠'},
    {'key': 'completeness', 'label': '完整性', 'weight': 0.3,
     'hint': '是否覆盖题目全部要求，步骤是否有缺失'},
    {'key': 'standard', 'label': '规范性', 'weight': 0.2,
     'hint': '格式、书写、代码风格与提交规范'},
    {'key': 'innovation', 'label': '创造性', 'weight': 0.1,
     'hint': '是否有独立思路或更优解法'},
)
# 互评截止前多久开始催办（分钟）
PEER_REVIEW_REMIND_MINUTES = 24 * 60


def peer_review_dimensions():
    """返回维度定义的副本，供接口/前端渲染。"""
    return [dict(d) for d in PEER_REVIEW_DIMENSIONS]


def _clean_dimension_scores(scores):
    """过滤合法维度分（0~100），返回 {key: float}。"""
    clean = {}
    if not isinstance(scores, dict):
        return clean
    for d in PEER_REVIEW_DIMENSIONS:
        v = scores.get(d['key'])
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if 0 <= v <= 100:
            clean[d['key']] = round(v, 2)
    return clean


def compute_peer_final_score(scores):
    """维度分 → 0~100 加权总分；未提供任何有效维度时返回 None。"""
    clean = _clean_dimension_scores(scores)
    if not clean:
        return None
    total_weight = sum(d['weight'] for d in PEER_REVIEW_DIMENSIONS if d['key'] in clean)
    if total_weight <= 0:
        return None
    weighted = sum(clean[d['key']] * d['weight']
                   for d in PEER_REVIEW_DIMENSIONS if d['key'] in clean)
    return round(weighted / total_weight, 2)


def _ensure_peer_daily_task(hw, reviewer_id):
    """互评分配后为评审人建当日 DailyTask（source='peer_review'，幂等）。"""
    try:
        from database.models import DailyTask
        today = utcnow().date()
        title = f'互评：{hw.title[:80]}'
        exists = DailyTask.query.filter_by(user_id=reviewer_id, day=today,
                                           title=title).first()
        if not exists:
            db.session.add(DailyTask(user_id=reviewer_id, day=today, title=title,
                                     source='peer_review', status='pending'))
    except Exception:
        logger.debug(f'[peer] 互评每日任务创建失败 hw={hw.id} user={reviewer_id}（非关键）')


def complete_peer_review_daily_task(hw, student_id):
    """学生提交互评后，把对应的互评 DailyTask 标记为完成。"""
    try:
        from database.models import DailyTask
        today = utcnow().date()
        task = DailyTask.query.filter_by(user_id=student_id, day=today,
                                         title=f'互评：{hw.title[:80]}').first()
        if task and task.status == 'pending':
            task.status = 'done'
            task.done_at = utcnow()
    except Exception:
        logger.debug(f'[peer] 互评每日任务完成标记失败 hw={hw.id}（非关键）')


def distribute_peer_reviews(hw, per_submission=PEER_REVIEW_PER_SUBMISSION):
    """教师触发：为每份已提交作业随机分配 N 位同学互评（排除本人）。

    重新分配时清空所有 pending 任务，已提交（submitted）的互评保留，
    并避免给已评过同一份作业的同学重复派单（唯一约束兜底）。
    返回 {'created', 'reviewers': {reviewer_id: count}, 'submitted_kept'}；
    不 commit，由路由层统一提交并通知。
    """
    import random
    from homework.models import HomeworkPeerReview, PeerReviewStatusEnum

    subs = [s for s in hw.submissions if s.status != SubmissionStatusEnum.DRAFT]
    if len(subs) < 2:
        return {'error': '至少需要 2 份已提交作业才能开展互评', 'created': 0,
                'reviewers': {}, 'submitted_kept': 0}
    try:
        per_submission = min(max(int(per_submission), 1), PEER_REVIEW_MAX_PER_SUBMISSION)
    except (TypeError, ValueError):
        per_submission = PEER_REVIEW_PER_SUBMISSION

    # 清空待互评任务（保留已提交的成果），避免重复派单堆积
    HomeworkPeerReview.query.filter_by(
        homework_id=hw.id, status=PeerReviewStatusEnum.PENDING).delete(
        synchronize_session=False)
    db.session.expire(hw, ['peer_reviews'])
    submitted_pairs = {(r.submission_id, r.reviewer_id) for r in
                       HomeworkPeerReview.query.filter_by(
                           homework_id=hw.id,
                           status=PeerReviewStatusEnum.SUBMITTED).all()}
    pool = [s.student_id for s in subs]
    counts = {}
    created = 0
    for sub in subs:
        candidates = [sid for sid in pool
                      if sid != sub.student_id and (sub.id, sid) not in submitted_pairs]
        random.shuffle(candidates)
        for reviewer_id in candidates[:per_submission]:
            db.session.add(HomeworkPeerReview(
                homework_id=hw.id, submission_id=sub.id, reviewer_id=reviewer_id,
                status=PeerReviewStatusEnum.PENDING))
            counts[reviewer_id] = counts.get(reviewer_id, 0) + 1
            created += 1
    db.session.flush()
    # v5.9 互评任务接入 DailyTask/打卡
    for reviewer_id in counts:
        _ensure_peer_daily_task(hw, reviewer_id)
    return {'created': created, 'reviewers': counts,
            'submitted_kept': len(submitted_pairs),
            'daily_tasks': len(counts)}


def _dimension_average(rows):
    """一批已提交互评的维度均分。"""
    avg = {}
    for d in PEER_REVIEW_DIMENSIONS:
        vals = []
        for r in rows:
            v = (r.scores_json or {}).get(d['key'])
            if isinstance(v, (int, float)):
                vals.append(float(v))
        avg[d['key']] = round(sum(vals) / len(vals), 2) if vals else None
    return avg


def peer_review_summary(hw):
    """教师端互评汇总：完成率、每份均分/维度均分/审核与加权分、评审人进度。"""
    from homework.models import (
        HomeworkPeerReview, PeerReviewStatusEnum, PeerReviewAuditEnum,
    )

    rows = HomeworkPeerReview.query.filter_by(homework_id=hw.id).all()
    submitted = [r for r in rows if r.status == PeerReviewStatusEnum.SUBMITTED]
    weight = float(hw.peer_review_weight or 0.0)
    per_sub = {}
    for r in rows:
        item = per_sub.setdefault(r.submission_id, {
            'submission_id': r.submission_id, 'review_count': 0,
            'submitted_count': 0, 'scores': [], 'accepted_scores': [],
            '_rows': []})
        item['review_count'] += 1
        if r.status == PeerReviewStatusEnum.SUBMITTED:
            item['submitted_count'] += 1
            item['_rows'].append(r)
            if r.score is not None:
                item['scores'].append(r.score)
                if r.audit_status == PeerReviewAuditEnum.ACCEPTED:
                    item['accepted_scores'].append(r.score)
    sub_by_id = {s.id: s for s in hw.submissions}
    per_submission = []
    for sid, item in per_sub.items():
        sub = sub_by_id.get(sid)
        scores = item.pop('scores')
        accepted_scores = item.pop('accepted_scores')
        review_rows = item.pop('_rows')
        item['avg_score'] = round(sum(scores) / len(scores), 2) if scores else None
        item['accepted_avg_score'] = round(
            sum(accepted_scores) / len(accepted_scores), 2) if accepted_scores else None
        item['peer_weighted_score'] = round(item['accepted_avg_score'] * weight, 2) \
            if item['accepted_avg_score'] is not None and weight > 0 else None
        item['dimension_avg'] = _dimension_average(review_rows)
        item['student_id'] = sub.student_id if sub else None
        item['username'] = (sub.student.username if sub and sub.student else '')
        item['submission_status'] = sub.status if sub else None
        per_submission.append(item)
    per_submission.sort(key=lambda x: (x['username'] or ''))

    reviewers = {}
    audit_counts = {'accepted': 0, 'rejected': 0, 'pending_audit': 0}
    for r in rows:
        item = reviewers.setdefault(r.reviewer_id, {
            'reviewer_id': r.reviewer_id, 'assigned': 0, 'submitted': 0,
            'accepted': 0, 'rejected': 0})
        item['assigned'] += 1
        if r.status == PeerReviewStatusEnum.SUBMITTED:
            item['submitted'] += 1
            if r.audit_status == PeerReviewAuditEnum.ACCEPTED:
                audit_counts['accepted'] += 1
                item['accepted'] += 1
            elif r.audit_status == PeerReviewAuditEnum.REJECTED:
                audit_counts['rejected'] += 1
                item['rejected'] += 1
            else:
                audit_counts['pending_audit'] += 1
    reviewer_rows = []
    for rid, item in reviewers.items():
        reviewer = db.session.get(User, rid)
        item['username'] = reviewer.username if reviewer else ''
        item['pending'] = item['assigned'] - item['submitted']
        reviewer_rows.append(item)
    reviewer_rows.sort(key=lambda x: (x['username'] or ''))

    # 教师审核明细（完整可见评审人身份）
    review_rows = []
    for r in sorted(submitted, key=lambda x: (x.submission_id, x.id)):
        d = r.to_dict(for_teacher=True)
        sub = sub_by_id.get(r.submission_id)
        d['reviewer_name'] = r.reviewer.username if r.reviewer else ''
        d['student_id'] = sub.student_id if sub else None
        d['student_name'] = (sub.student.username if sub and sub.student else '')
        review_rows.append(d)

    total = len(rows)
    return {'total': total, 'submitted': len(submitted),
            'pending': total - len(submitted),
            'completion_rate': round(len(submitted) / total * 100, 1) if total else 0.0,
            'accepted': audit_counts['accepted'],
            'rejected': audit_counts['rejected'],
            'pending_audit': audit_counts['pending_audit'],
            'weight': weight,
            'deadline': iso_local(hw.peer_review_deadline) if hw.peer_review_deadline else None,
            'dimensions': peer_review_dimensions(),
            'per_submission': per_submission, 'reviewers': reviewer_rows,
            'reviews': review_rows}


def peer_review_received(sub):
    """被评学生可见的匿名互评结果：均分/维度均分/审核状态/互评加权分。

    匿名：不披露评审人身份；仅教师审核采纳（accepted）的互评参与加权分。
    加权分是独立字段，不写 HomeworkSubmission.total_score。
    """
    from homework.models import (
        HomeworkPeerReview, PeerReviewStatusEnum, PeerReviewAuditEnum,
    )

    rows = HomeworkPeerReview.query.filter_by(
        submission_id=sub.id, status=PeerReviewStatusEnum.SUBMITTED).all()
    if not rows:
        return None
    scores = [r.score for r in rows if r.score is not None]
    accepted = [r for r in rows if r.audit_status == PeerReviewAuditEnum.ACCEPTED]
    accepted_scores = [r.score for r in accepted if r.score is not None]
    accepted_avg = round(sum(accepted_scores) / len(accepted_scores), 2) \
        if accepted_scores else None
    hw = sub.homework
    weight = float(getattr(hw, 'peer_review_weight', 0.0) or 0.0)
    contribution = round(accepted_avg * weight, 2) \
        if accepted_avg is not None and weight > 0 else None
    final_view = round(sub.total_score + contribution, 2) \
        if contribution is not None and sub.total_score is not None else None
    return {'count': len(rows),
            'avg_score': round(sum(scores) / len(scores), 2) if scores else None,
            'dimension_avg': _dimension_average(rows),
            'accepted_count': len(accepted),
            'rejected_count': len([r for r in rows
                                   if r.audit_status == PeerReviewAuditEnum.REJECTED]),
            'accepted_avg_score': accepted_avg,
            'weight': weight,
            'weighted_contribution': contribution,
            'final_view_score': final_view,
            'deadline': iso_local(hw.peer_review_deadline)
            if getattr(hw, 'peer_review_deadline', None) else None,
            'comments': [{'score': r.score, 'scores': r.scores_json or {},
                          'comment': r.comment or '',
                          'audit_status': r.audit_status,
                          'submitted_at': iso_local(r.submitted_at)} for r in rows]}


def audit_peer_review(review, action, comment='', teacher_id=None):
    """教师审核单条互评：accept=采纳（计入互评加权分）/ reject=驳回。

    返回 {'error'} 或 {'review'}；不 commit，由路由统一提交并通知。
    """
    from homework.models import PeerReviewStatusEnum, PeerReviewAuditEnum

    if review.status != PeerReviewStatusEnum.SUBMITTED:
        return {'error': '该互评尚未提交，不能审核'}
    if action not in ('accept', 'reject'):
        return {'error': '审核动作须为 accept 或 reject'}
    review.audit_status = PeerReviewAuditEnum.ACCEPTED if action == 'accept' \
        else PeerReviewAuditEnum.REJECTED
    review.teacher_comment = (comment or '')[:1000]
    review.audited_by = teacher_id
    review.audited_at = utcnow()
    return {'review': review.to_dict(for_teacher=True)}


def peer_review_deadline_tick():
    """调度器任务：互评截止前催办未完成互评的评审人（CAS 幂等）。"""
    from datetime import timedelta
    from homework.models import (
        HomeworkPeerReview, HomeworkStatusEnum, PeerReviewStatusEnum,
    )

    now = utcnow()
    items = Homework.query.filter(
        Homework.status == HomeworkStatusEnum.PUBLISHED,
        Homework.peer_review_deadline.isnot(None),
        Homework.peer_review_reminded_at.is_(None)).all()
    for hw in items:
        try:
            remind_at = hw.peer_review_deadline - timedelta(minutes=PEER_REVIEW_REMIND_MINUTES)
            if now < remind_at or now > hw.peer_review_deadline:
                continue
            res = db.session.execute(
                db.text('UPDATE homework SET peer_review_reminded_at = :now '
                        'WHERE id = :id AND peer_review_reminded_at IS NULL'),
                {'now': now, 'id': hw.id})
            if res.rowcount != 1:
                db.session.rollback()
                continue
            db.session.refresh(hw)
            pending = HomeworkPeerReview.query.filter_by(
                homework_id=hw.id, status=PeerReviewStatusEnum.PENDING).all()
            reviewer_ids = {r.reviewer_id for r in pending}
            for rid in reviewer_ids:
                create_notification(
                    rid, '互评即将截止',
                    f'《{hw.title}》互评将于 {iso_local(hw.peer_review_deadline)} 截止，'
                    f'你还有未完成的互评任务，请尽快提交。',
                    type='warning', related_type='homework', related_id=hw.id,
                    commit=False)
            db.session.commit()
            logger.info(f'[peer] 作业 {hw.id} 互评截止提醒已发送 {len(reviewer_ids)} 人')
        except Exception:
            db.session.rollback()
            logger.error(f'[peer] 互评截止提醒失败 hw={hw.id}', exc_info=True)


# ═══════════════════════ v5.8 作业模板与系列化 ═══════════════════════

def _template_question_query(config):
    """按模板 config.filters 构造题目查询（抽题与预览共用）。"""
    filters = (config or {}).get('filters') or {}
    q = Question.query
    if filters.get('major_id'):
        q = q.filter(Question.major_id == int(filters['major_id']))
    if filters.get('course_id'):
        q = q.filter(Question.course_id == int(filters['course_id']))
    if filters.get('chapter_id'):
        q = q.filter(Question.chapter_id == int(filters['chapter_id']))
    if filters.get('difficulty'):
        q = q.filter(Question.difficulty == filters['difficulty'])
    types = filters.get('types')
    if types:
        q = q.filter(Question.type.in_(types))
    return q


def preview_template_questions(config):
    """抽题预览：返回命中题目、难度分布与题库可用量（不落库）。"""
    config = config or {}
    pool = _template_question_query(config).all()
    available = {}
    for q in pool:
        available[q.difficulty or 'unknown'] = available.get(q.difficulty or 'unknown', 0) + 1
    questions = _pick_questions_by_template(config)
    default_score = float(config.get('default_score', 5) or 5)
    picked = [{'id': q.id, 'content': (q.content or '')[:200], 'type': q.type,
               'difficulty': q.difficulty, 'course_id': q.course_id,
               'chapter_id': q.chapter_id, 'score': default_score}
              for q in questions]
    picked_counts = {}
    for item in picked:
        key = item['difficulty'] or 'unknown'
        picked_counts[key] = picked_counts.get(key, 0) + 1
    return {'available': available, 'picked_counts': picked_counts,
            'questions': picked, 'pool_total': len(pool),
            'picked_total': len(picked)}


def _pick_questions_by_template(config):
    """按模板 config 的筛选规则抽取题目列表（Question 实例）。"""
    pool = _template_question_query(config).all()
    distribution = config.get('distribution')
    if distribution:
        # 按难度分布抽取
        picked = []
        by_diff = {}
        for item in pool:
            by_diff.setdefault(item.difficulty, []).append(item)
        for slot in distribution:
            diff = slot.get('difficulty')
            cnt = int(slot.get('count', 0))
            import random
            choices = by_diff.get(diff, [])[:]
            random.shuffle(choices)
            picked.extend(choices[:cnt])
        return picked
    # 按总数随机
    import random
    count = int(config.get('count', 5))
    random.shuffle(pool)
    return pool[:count]


def generate_homework_from_template(template, teacher_id, index=0, publish=False, series_id=None):
    """从模板生成一份作业草稿（可选直接发布）。

    index 用于标题序号（如「周练 3/5」），series_id 关联系列。
    返回 (homework, error)。
    """
    from homework.models import (Homework, HomeworkQuestion, HomeworkStudent,
                                 HomeworkStatusEnum, HomeworkTypeEnum)
    import random as _random

    config = template.config_json or {}
    settings = template.settings_json or {}
    roster = template.roster_json or []

    title = f'{template.title} {index + 1}/{config.get("count", "?")}' \
        if series_id else template.title
    hw = Homework(title=title[:200], description=template.description or '',
                  hw_type=HomeworkTypeEnum.QUESTION_SET, teacher_id=teacher_id,
                  status=HomeworkStatusEnum.DRAFT,
                  allow_late=settings.get('allow_late', True),
                  allow_resubmit=settings.get('allow_resubmit', True),
                  remind_before=settings.get('remind_before', 0) or 0,
                  pass_score=settings.get('pass_score'),
                  series_id=series_id)
    deadline_hours = settings.get('deadline_hours')
    if deadline_hours:
        from datetime import timedelta
        hw.deadline = utcnow() + timedelta(hours=int(deadline_hours))
    db.session.add(hw)
    db.session.flush()
    # 抽题
    questions = _pick_questions_by_template(config)
    default_score = float(config.get('default_score', 5))
    for i, q in enumerate(questions):
        db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id,
                                        score=default_score, order=i))
    # 名单
    for sid in roster:
        try:
            sid = int(sid)
            db.session.add(HomeworkStudent(homework_id=hw.id, student_id=sid))
        except (TypeError, ValueError):
            continue
    if publish:
        hw.status = HomeworkStatusEnum.PUBLISHED
        hw.published_at = utcnow()
    db.session.commit()
    return hw, None


def homework_series_tick():
    """调度器任务：扫描进行中的系列，生成已到期未生成的作业。"""
    from homework.models import (HomeworkSeries, HomeworkSeriesStatusEnum)

    series_list = HomeworkSeries.query.filter(
        HomeworkSeries.status == HomeworkSeriesStatusEnum.ACTIVE).all()
    for s in series_list:
        try:
            now = utcnow()
            # 生成所有到期且未生成的份
            while s.generated_count < s.count and s.planned_at(s.generated_count) <= now:
                idx = s.generated_count
                hw, err = generate_homework_from_template(
                    s.template, s.teacher_id, index=idx, publish=True, series_id=s.id)
                if err:
                    logger.error(f'[series] 系列 {s.id} 第 {idx} 份生成失败: {err}')
                    break
                # 给名单学生建每日任务 + 通知
                _create_daily_tasks_for_homework(hw)
                _notify_series_homework(hw)
                s.generated_count += 1
                db.session.commit()
                logger.info(f'[series] 系列 {s.id} 第 {idx + 1}/{s.count} 份作业已生成发布')
            if s.generated_count >= s.count:
                s.status = HomeworkSeriesStatusEnum.COMPLETED
                db.session.commit()
        except Exception:
            db.session.rollback()
            logger.error(f'[series] 系列 {s.id} tick 异常', exc_info=True)


def _create_daily_tasks_for_homework(hw):
    """作业发布时，为名单内每个学生在发布当日创建一条 DailyTask（source='manual' 对应 CHECK 枚举）。"""
    try:
        from database.models import DailyTask
        today = utcnow().date()
        for hs in hw.hw_students:
            # 幂等：同作业同日不重复建
            exists = DailyTask.query.filter_by(
                user_id=hs.student_id, day=today,
                title=f'作业：{hw.title}').first()
            if not exists:
                db.session.add(DailyTask(user_id=hs.student_id, day=today,
                                         title=f'作业：{hw.title[:80]}',
                                         source='manual', status='pending'))
    except Exception:
        logger.debug(f'[series] 为作业 {hw.id} 创建每日任务失败（非关键）', exc_info=True)


def _notify_series_homework(hw):
    """系列生成作业后通知名单学生。"""
    try:
        notify_homework_students(
            hw, '新作业发布', f'《{hw.title}》已发布，请按时完成。')
    except Exception:
        logger.debug(f'[series] 作业 {hw.id} 通知失败（非关键）', exc_info=True)


def complete_homework_daily_task(hw, student_id):
    """学生提交作业时，把对应的 DailyTask 标记为完成（同标题）。"""
    try:
        from database.models import DailyTask
        from utils.timeutil import utcnow as _now
        today = _now().date()
        task = DailyTask.query.filter_by(
            user_id=student_id, day=today,
            title=f'作业：{hw.title}').first()
        if task and task.status == 'pending':
            task.status = 'done'
            task.done_at = _now()
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.debug(f'[series] 作业 {hw.id} 完成任务标记失败（非关键）', exc_info=True)



# ═══════════════════════ v5.6 作业反抄袭 ═══════════════════════

def homework_plagiarism_check(hw, threshold=0.7):
    """作业级查重：题集式编程题复用 oj.plagiarism.compare_submissions，
    开放式文字用 compare_text_submissions（字符 n-gram）。

    返回: {'hw_type', 'items': [{'question_id', 'question_content', 'pairs': [...]}
             或开放式单条 {'kind':'open','pairs':[...]}],
           'scanned': 参与比对的提交数, 'pair_count': 高相似对总数}
    仅作复核线索，相似高 ≠ 必然抄袭。
    """
    from oj.plagiarism import compare_submissions, compare_text_submissions

    submitted = [s for s in hw.submissions
                 if s.status in (SubmissionStatusEnum.SUBMITTED,
                                 SubmissionStatusEnum.GRADED)]
    items = []
    pair_count = 0
    scanned = 0

    if hw.hw_type == HomeworkTypeEnum.OPEN:
        subs = []
        for s in submitted:
            text = s.content or ''
            if not text.strip():
                continue
            subs.append({'student_id': s.student_id,
                         'username': s.student.username if s.student else '',
                         'text': text})
        scanned = len(subs)
        pairs = compare_text_submissions(subs, threshold=threshold)
        if pairs:
            items.append({'kind': 'open', 'pairs': pairs})
            pair_count += len(pairs)
        return {'hw_type': hw.hw_type, 'items': items,
                'scanned': scanned, 'pair_count': pair_count}

    # 题集式：逐题比对，仅编程题走代码查重
    from database.models import Question
    q_ids = [hq.question_id for hq in hw.hw_questions]
    qmap = {q.id: q for q in Question.query.filter(Question.id.in_(q_ids)).all()} if q_ids else {}
    for hq in hw.hw_questions:
        q = qmap.get(hq.question_id)
        if not q or q.type != QuestionTypeEnum.PROGRAMMING:
            continue
        subs = []
        for s in submitted:
            a = next((x for x in s.answers if x.question_id == hq.question_id), None)
            code = (a.answer or '') if a else ''
            if not code.strip():
                continue
            subs.append({'student_id': s.student_id,
                         'username': s.student.username if s.student else '',
                         'code': code})
        scanned += len(subs)
        pairs = compare_submissions(subs, threshold=threshold)
        if pairs:
            items.append({'question_id': hq.question_id,
                          'question_content': q.content,
                          'pairs': pairs})
            pair_count += len(pairs)
    return {'hw_type': hw.hw_type, 'items': items,
            'scanned': scanned, 'pair_count': pair_count}


# ═══════════════════════ v5.7 小组作业 ═══════════════════════

def get_student_group(hw, student_id):
    """返回学生在该作业所属的小组，无则 None。"""
    from homework.models import HomeworkGroup, HomeworkGroupMember
    return (HomeworkGroup.query
            .join(HomeworkGroupMember, HomeworkGroupMember.group_id == HomeworkGroup.id)
            .filter(HomeworkGroup.homework_id == hw.id,
                    HomeworkGroupMember.student_id == student_id).first())


def get_group_submission(hw, group_id):
    """小组作业：每组一份提交，取该组提交（无则 None）。"""
    return HomeworkSubmission.query.filter_by(
        homework_id=hw.id, group_id=group_id).first()


def sync_roster_from_groups(hw):
    """小组作业：把所有小组成员同步进发布名单（确保学生能在列表里看到作业）。"""
    from homework.models import HomeworkStudent
    member_ids = {m.student_id for g in hw.groups for m in g.members}
    existing = {hs.student_id for hs in hw.hw_students}
    for sid in member_ids:
        if sid not in existing:
            hw.hw_students.append(HomeworkStudent(student_id=sid))
    removed = existing - member_ids
    if removed:
        hw.hw_students[:] = [hs for hs in hw.hw_students
                             if hs.student_id not in removed]

