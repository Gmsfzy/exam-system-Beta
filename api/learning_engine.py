# -*- coding: utf-8 -*-
"""学习闭环引擎：掌握度 EWMA/遗忘衰减、间隔复习排期、任务自动核销、打卡连击。

自我学习模块的共享计算层，被 api/learning_routes.py 与 utils/scheduler.py 复用。
以"知识点掌握度"为中心：答题数据驱动掌握度与任务核销，掌握度衰减驱动复习队列。
所有函数只操作传入 session 上下文内的数据，不自行 commit（由调用方控制事务边界）。
"""
import math
from datetime import timedelta

from sqlalchemy import func

from database import db
from database.models import (
    KnowledgeMastery, ReviewItem, StudyCheckin, StudyPlan, StudyPlanTask,
    question_knowledge_point,
)
from utils.logger import logger
from utils.timeutil import utcnow

# ── 算法常量 ──────────────────────────────────────────────────────
MASTERY_HALF_LIFE_DAYS = 30.0   # 掌握度展示衰减半衰期（天）
EWMA_ALPHA = 0.3                # 掌握度 EWMA 平滑系数
MASTERED_LEVEL = 80.0           # 视为"已掌握"的掌握度阈值
DECAY_RISK_RAW = 70.0           # 遗忘风险：原始掌握度下限
DECAY_RISK_SHOWN = 50.0         # 遗忘风险：展示掌握度上限
PASS_RATIO = 0.8                # 小测/终测通过线
REVIEW_INTERVALS = [1, 3, 7, 16, 35]  # 简化 SM-2 间隔序列（天）
REVIEW_RETIRE_REPS = 5          # 连续答对达此次数即退休


# ── 掌握度 ────────────────────────────────────────────────────────

def decayed_level(level, last_verified_at, now=None):
    """按遗忘曲线计算展示掌握度：level * exp(-ln2 * 距上次验证天数 / 半衰期)"""
    if not level:
        return 0.0
    if last_verified_at is None:
        return round(level, 2)
    now = now or utcnow()
    days = max((now - last_verified_at).total_seconds() / 86400.0, 0)
    return round(level * math.exp(-math.log(2) * days / MASTERY_HALF_LIFE_DAYS), 2)


def get_mastery(user_id, kp_id):
    return KnowledgeMastery.query.filter_by(user_id=user_id, knowledge_point_id=kp_id).first()


def update_mastery(user_id, kp_ids, correct_ratio):
    """EWMA 更新一批知识点的掌握度：new = old + alpha * (obs - old)，obs = correct_ratio*100。
    任何一次验证都会把衰减锚点 last_verified_at 重置为当前（近期答对 => 展示值不衰减）。
    """
    obs = max(0.0, min(100.0, (correct_ratio or 0) * 100))
    now = utcnow()
    for kp_id in set(kp_ids or []):
        m = get_mastery(user_id, kp_id)
        if not m:
            m = KnowledgeMastery(user_id=user_id, knowledge_point_id=kp_id, level=0.0)
            db.session.add(m)
        m.level = round(m.level + EWMA_ALPHA * (obs - m.level), 2)
        m.total_attempts = (m.total_attempts or 0) + 1
        if (correct_ratio or 0) >= 0.5:
            m.total_correct = (m.total_correct or 0) + 1
        m.last_verified_at = now
    db.session.flush()
    return m


def bump_mastery_floor(user_id, kp_id, floor):
    """节点标记掌握 / 小测通过：把该 KP 掌握度抬到不低于 floor，并重置衰减锚点"""
    if not kp_id:
        return
    m = get_mastery(user_id, kp_id)
    if not m:
        m = KnowledgeMastery(user_id=user_id, knowledge_point_id=kp_id, level=0.0)
        db.session.add(m)
    m.level = round(max(m.level or 0.0, floor), 2)
    m.last_verified_at = utcnow()
    db.session.flush()


def mastery_level_value(user_id, kp_id):
    """当前掌握度原始值（0-100），无记录返回 0"""
    m = get_mastery(user_id, kp_id)
    return (m.level if m else 0.0) or 0.0


# ── 题目-知识点映射 ───────────────────────────────────────────────

def kp_ids_of_question(question_id):
    rows = db.session.query(question_knowledge_point.c.knowledge_point_id) \
        .filter(question_knowledge_point.c.question_id == question_id).all()
    return [r[0] for r in rows]


# ── 薄弱点自适应推荐（复用掌握度地基，只推已有题、不动态生成）──────────────

def weak_knowledge_points(user_id, limit=15, now=None):
    """该生「已接触且展示掌握度最低」的知识点 [(kp_id, 展示掌握度)]，升序（越靠前越薄弱）。

    仅纳入已有掌握度记录的知识点：新学生冷启动无数据时返回空，不强行推荐。
    """
    now = now or utcnow()
    scored = [
        (m.knowledge_point_id, decayed_level(m.level, m.last_verified_at, now))
        for m in KnowledgeMastery.query.filter_by(user_id=user_id).all()
    ]
    weak = [(kp, lv) for kp, lv in scored if lv < MASTERED_LEVEL]
    weak.sort(key=lambda x: x[1])
    return weak[:limit]


def recommend_practice_questions(user_id, limit=5, now=None):
    """按最薄弱知识点推荐「尚未作答过」的已有题目，供今日学习页主动练习。

    选型：命中薄弱知识点的题目中，剔除该生考试/自由练习已作答过的（保证是「新题」），
    再按所属知识点的薄弱程度排序取前 limit 道。返回题目摘要 dict 列表。
    """
    from database.models import (
        Question, KnowledgePoint, Answer, ExamSession,
        PracticeAnswer, PracticeSession,
    )
    weak = weak_knowledge_points(user_id, limit=15, now=now)
    if not weak:
        return []
    rank = {kp: i for i, (kp, _) in enumerate(weak)}   # 值越小越薄弱
    shown = {kp: lv for kp, lv in weak}

    answered = set()
    for (qid,) in db.session.query(Answer.question_id).join(
            ExamSession, Answer.session_id == ExamSession.id) \
            .filter(ExamSession.student_id == user_id).all():
        answered.add(qid)
    for (qid,) in db.session.query(PracticeAnswer.question_id).join(
            PracticeSession, PracticeAnswer.session_id == PracticeSession.id) \
            .filter(PracticeSession.user_id == user_id).all():
        answered.add(qid)

    # 题目命中薄弱知识点：记录其最薄弱的那个 KP（rank 最小）
    q_best = {}
    rows = db.session.query(
        question_knowledge_point.c.question_id,
        question_knowledge_point.c.knowledge_point_id,
    ).filter(question_knowledge_point.c.knowledge_point_id.in_(list(rank))).all()
    for qid, kp in rows:
        cur = q_best.get(qid)
        if cur is None or rank[kp] < cur[0]:
            q_best[qid] = (rank[kp], kp)

    cand_ids = [qid for qid in q_best if qid not in answered]
    if not cand_ids:
        return []
    qs = {q.id: q for q in Question.query.filter(Question.id.in_(cand_ids)).all()}
    ordered = sorted(cand_ids, key=lambda qid: (q_best[qid][0], qid))

    out = []
    for qid in ordered:
        q = qs.get(qid)
        if not q:
            continue
        _, kp = q_best[qid]
        kpo = db.session.get(KnowledgePoint, kp)
        out.append({
            'question_id': q.id,
            'content': (q.content or '')[:80],
            'type': q.type,
            'difficulty': q.difficulty,
            'knowledge_point': kpo.name if kpo else None,
            'mastery': round(shown.get(kp, 0.0), 1),
        })
        if len(out) >= limit:
            break
    return out


# ── 间隔复习（简化 SM-2） ─────────────────────────────────────────

def ensure_review_item(user_id, question_id, source_type='wrong', due_at=None):
    """幂等创建/复活复习卡。已存在且退休则重置为 pending。"""
    ri = ReviewItem.query.filter_by(user_id=user_id, question_id=question_id).first()
    if ri:
        if ri.status == 'retired':
            ri.status = 'pending'
            ri.interval_days = 1
            ri.repetitions = 0
            ri.due_at = due_at or utcnow()
        return ri
    ri = ReviewItem(user_id=user_id, question_id=question_id, source_type=source_type,
                    interval_days=1, due_at=due_at or utcnow())
    db.session.add(ri)
    return ri


def schedule_next_review(ri, correct):
    """根据复习判分结果推进排期"""
    now = utcnow()
    if correct:
        ri.repetitions = (ri.repetitions or 0) + 1
        idx = min(ri.repetitions - 1, len(REVIEW_INTERVALS) - 1)
        ri.interval_days = REVIEW_INTERVALS[idx]
        ri.due_at = now + timedelta(days=ri.interval_days)
        if ri.repetitions >= REVIEW_RETIRE_REPS:
            ri.status = 'retired'
    else:
        ri.repetitions = 0
        ri.interval_days = 1
        ri.ease = max(1.3, (ri.ease or 2.5) - 0.2)
        ri.due_at = now + timedelta(days=1)
        ri.status = 'pending'


def due_review_count(user_id, now=None):
    now = now or utcnow()
    return ReviewItem.query.filter_by(user_id=user_id, status='pending') \
        .filter(ReviewItem.due_at <= now).count()


# ── 打卡连击 ──────────────────────────────────────────────────────

def touch_checkin(user_id, minutes=0, tasks_delta=0):
    """记录当日有效学习：累加分钟数与完成任务数（幂等 upsert）；顺带检查学习徽章"""
    today = utcnow().date()
    c = StudyCheckin.query.filter_by(user_id=user_id, day=today).first()
    if not c:
        c = StudyCheckin(user_id=user_id, day=today, minutes=0, tasks_done=0)
        db.session.add(c)
    if minutes:
        c.minutes = (c.minutes or 0) + int(minutes)
    if tasks_delta:
        c.tasks_done = (c.tasks_done or 0) + int(tasks_delta)
    db.session.flush()
    # 打卡时顺带检查连击/证书/路径完成徽章（内部已静默降级，不影响主流程）
    grant_learning_badges(user_id)
    return c


def compute_streak(user_id, today=None):
    """从今天（或昨天，若今天未打卡则从今天往前连续）回溯连续打卡天数"""
    today = today or utcnow().date()
    days = {r[0] for r in db.session.query(StudyCheckin.day)
            .filter(StudyCheckin.user_id == user_id).all()}
    if not days:
        return 0
    # 今天没打卡则从昨天起算
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def week_checkin_days(user_id, today=None):
    """近 7 天（含今天）的打卡日期集合，供前端日历条渲染"""
    today = today or utcnow().date()
    start = today - timedelta(days=6)
    rows = StudyCheckin.query.filter(
        StudyCheckin.user_id == user_id,
        StudyCheckin.day >= start, StudyCheckin.day <= today).all()
    return {c.day.isoformat(): {'minutes': c.minutes or 0,
                                'tasks_done': c.tasks_done or 0} for c in rows}


def last_active_date(user_id):
    """最近一次有效学习日期（打卡），无则 None"""
    c = StudyCheckin.query.filter_by(user_id=user_id) \
        .order_by(StudyCheckin.day.desc()).first()
    return c.day if c else None


# ── 计划任务自动核销 ──────────────────────────────────────────────

def _mark_task_done(task):
    if task.status != 'done':
        task.status = 'done'
        task.done_at = utcnow()
        task.auto_done = True
        return True
    return False


def auto_complete_tasks(user_id, kp_ids=None, practiced_delta=0):
    """自动核销 active 计划中的任务：
    - knowledge_point 型：所挂 KP 掌握度 >= MASTERED_LEVEL 时置 done；
    - practice 型：累加本次刷题数到 progress_count，达到 question_count 时置 done；
    - custom/resource 型：保持手动打卡，不自动核销。
    返回本次新核销的任务数（用于打卡 tasks_done 累加）。
    """
    kp_ids = set(kp_ids or [])
    newly_done = 0
    plans = StudyPlan.query.filter_by(user_id=user_id, status='active').all()
    for plan in plans:
        for task in plan.tasks:
            if task.status == 'done':
                continue
            if task.task_type == 'knowledge_point' and task.knowledge_point_id:
                if mastery_level_value(user_id, task.knowledge_point_id) >= MASTERED_LEVEL:
                    if _mark_task_done(task):
                        newly_done += 1
            elif task.task_type == 'practice':
                # practice 型若绑定 KP，仅当本次练习覆盖该 KP 才推进；无 KP 绑定则通用推进
                scope_ok = (not task.knowledge_point_id) or bool(kp_ids) or practiced_delta > 0
                if practiced_delta > 0 and scope_ok:
                    target = task.question_count or 0
                    if target > 0:
                        task.progress_count = (task.progress_count or 0) + int(practiced_delta)
                        if task.progress_count >= target and _mark_task_done(task):
                            newly_done += 1
    # 计划状态按任务实况流转（复用与 _plan_to_dict 一致的判定）
    for plan in plans:
        tasks = plan.tasks
        done = sum(1 for t in tasks if t.status == 'done')
        if tasks and done == len(tasks) and plan.status == 'active':
            plan.status = 'completed'
        elif tasks and done < len(tasks) and plan.status == 'completed':
            plan.status = 'active'
    db.session.flush()
    return newly_done


# ── 证书编号 ──────────────────────────────────────────────────────

def gen_serial_no():
    import secrets
    year = utcnow().year
    return f'ZHX-{year}-{secrets.token_hex(4).upper()}'


# ── 学习徽章发放（复用 competition 勋章体系，幂等） ──────────────

def grant_learning_badges(user_id):
    """按当前数据状态检查并发放学习类徽章（不 commit，由调用方事务提交）。
    失败静默降级：勋章是附加激励，不得影响主流程。
    """
    try:
        from competition.gamification import check_and_grant
        from database.models import PathCertificate, UserPathEnrollment
        triggers = []
        streak = compute_streak(user_id)
        if streak >= 21:
            triggers += ['study_streak_7', 'study_streak_21']
        elif streak >= 7:
            triggers.append('study_streak_7')
        if PathCertificate.query.filter_by(user_id=user_id).count() >= 1:
            triggers.append('first_certificate')
        if UserPathEnrollment.query.filter_by(user_id=user_id, status='completed').count() >= 1:
            triggers.append('first_path_complete')
        if triggers:
            return check_and_grant(user_id, triggers)
    except Exception:
        logger.exception('学习徽章发放失败 user=%s', user_id)
    return []


# ── 每日巡查（后台调度线程调用，自带 24h 幂等守卫） ──────────────

_last_tick_day = None


def _notified_recently(user_id, related_type, related_id, days, now=None):
    """通知查重：最近 N 天内是否发过同类型关联通知（防打扰）"""
    from database.models import Notification
    since = (now or utcnow()) - timedelta(days=days)
    q = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.related_type == related_type,
        Notification.created_at >= since)
    if related_id is not None:
        q = q.filter(Notification.related_id == related_id)
    return q.count() > 0


def learning_daily_tick():
    """学习闭环每日巡查（每天有且只跑一次）：
    1) 掌握度衰减审查 → 生成遗忘复习卡（每人每日上限 10 张）
    2) 复习到期数量 >=5 → 推送复习提醒
    3) 3 天未学习且有活跃计划/在读路径 → 学习坚持提醒（每人每 3 天至多 1 条）
    4) 计划进度落后超 30 个百分点 → 调整预警
    5) 路径全部节点已掌握但未考终测 → 终测引导
    """
    global _last_tick_day
    now = utcnow()
    today = now.date()
    if _last_tick_day == today:
        return
    _last_tick_day = today

    from database.models import (
        Notification, StudyLog, UserPathEnrollment, LearningPathNode,
        UserNodeProgress, QuizAttempt, PathCertificate,
    )
    from api.notification_routes import create_notification

    # 1) 衰减审查 → 复习卡
    try:
        user_ids = [r[0] for r in db.session.query(KnowledgeMastery.user_id).distinct().all()]
        total_cards = 0
        for uid in user_ids:
            rows = KnowledgeMastery.query.filter_by(user_id=uid).all()
            decayed = [m for m in rows
                       if (m.level or 0) >= DECAY_RISK_RAW
                       and decayed_level(m.level, m.last_verified_at, now) < DECAY_RISK_SHOWN]
            decayed.sort(key=lambda m: m.last_verified_at or now)
            created = 0
            for m in decayed:
                if created >= 10:
                    break
                qids = [r[0] for r in db.session.query(
                    question_knowledge_point.c.question_id)
                    .filter(question_knowledge_point.c.knowledge_point_id == m.knowledge_point_id)
                    .limit(2).all()]
                for qid in qids:
                    ri = ensure_review_item(uid, qid, source_type='mastery_decay', due_at=now)
                    if ri in db.session.new or ri.status == 'pending':
                        created += 1
            total_cards += created
        db.session.commit()
        if total_cards:
            logger.info('[learning_tick] 衰减复习卡生成 %d 张', total_cards)
    except Exception:
        db.session.rollback()
        logger.exception('[learning_tick] 衰减审查失败')

    # 2) 复习到期提醒
    try:
        rows = db.session.query(ReviewItem.user_id, func.count(ReviewItem.id)) \
            .filter(ReviewItem.status == 'pending', ReviewItem.due_at <= now) \
            .group_by(ReviewItem.user_id).having(func.count(ReviewItem.id) >= 5).all()
        for uid, cnt in rows:
            if _notified_recently(uid, 'review_remind', uid, 1, now):
                continue
            create_notification(uid, '复习任务到期', f'你有 {cnt} 道题到了复习窗口，\n去今日学习页清除积压吧。',
                                type='info', related_type='review_remind', related_id=uid)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('[learning_tick] 复习提醒失败')

    # 3) 3 天未学习提醒（仅针对近期活跃学习者，避免新功能打扰沉睡账号）
    try:
        from sqlalchemy import or_
        active_plan_users = {r[0] for r in db.session.query(StudyPlan.user_id)
                             .filter(StudyPlan.status == 'active').distinct().all()}
        active_enroll_users = {r[0] for r in db.session.query(UserPathEnrollment.user_id)
                               .filter(UserPathEnrollment.status == 'active').distinct().all()}
        candidates = active_plan_users | active_enroll_users
        for uid in candidates:
            last = db.session.query(func.max(StudyLog.studied_at)) \
                .filter(StudyLog.user_id == uid).scalar()
            if not last:
                continue
            gap = (now - last).days
            if 3 <= gap <= 14 and not _notified_recently(uid, 'study_remind', uid, 3, now):
                create_notification(uid, '学习别断档啦', f'你已经 {gap} 天没学习了，今天的任务和复习在等你。',
                                    type='warning', related_type='study_remind', related_id=uid)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('[learning_tick] 未学习提醒失败')

    # 4) 计划进度落后预警
    try:
        plans = StudyPlan.query.filter(StudyPlan.status == 'active') \
            .filter(StudyPlan.start_date.isnot(None), StudyPlan.end_date.isnot(None)).all()
        for p in plans:
            span = (p.end_date - p.start_date).days
            if span <= 0:
                continue
            expected = min(max((today - p.start_date).days / span, 0), 1)
            tasks = p.tasks
            if not tasks:
                continue
            done_rate = sum(1 for t in tasks if t.status == 'done') / len(tasks)
            if expected - done_rate > 0.3 and not _notified_recently(
                    p.user_id, 'plan_lag', p.id, 3, now):
                create_notification(
                    p.user_id, f'计划进度预警：{p.title}',
                    f'时间已过 {round(expected * 100)}%，任务仅完成 {round(done_rate * 100)}%，建议调整计划或加赶进度。',
                    type='warning', related_type='plan_lag', related_id=p.id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('[learning_tick] 计划预警失败')

    # 5) 结业测评引导
    try:
        enrs = UserPathEnrollment.query.filter_by(status='completed').all()
        for e in enrs:
            if not e.path_id or not e.user_id:
                continue
            has_attempt = db.session.query(QuizAttempt.id).filter_by(
                user_id=e.user_id, path_id=e.path_id, scope_type='path_final').first()
            has_cert = db.session.query(PathCertificate.id).filter_by(
                user_id=e.user_id, path_id=e.path_id).first()
            if has_attempt or has_cert:
                continue
            if _notified_recently(e.user_id, 'final_quiz', e.path_id, 7, now):
                continue
            title = e.path.title if e.path else '学习路径'
            create_notification(
                e.user_id, f'可以参加结业测评啦：{title}',
                f'你已完成「{title}」全部节点，通过结业测评即可获得结业证书。',
                type='info', related_type='final_quiz', related_id=e.path_id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('[learning_tick] 终测引导失败')

    logger.info('[learning_tick] 学习闭环每日巡查完成 %s', today)
