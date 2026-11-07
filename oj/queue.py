# -*- coding: utf-8 -*-
"""OJ 异步评测队列（v7.0 阶段 3）。

交卷命中编程题（有用例且工具链就绪、OJ_ASYNC_GRADING 开启）时，ai_grade_exam 只把
answer.oj_status 置 pending（本次结算按暂定 0 分），真正评测投本模块后台线程：
- 队列以 DB 状态列为唯一事实源（不引外部 MQ）：pending→grading→done/failed；
- 幂等：按 answer_id 原子 UPDATE 抢占（仅 pending→grading 成功者评），多 worker/重复入队不双评；
- 失败可重放：评测异常回置 pending 并计 attempts，超限（MAX_ATTEMPTS）置 failed 终态；
  进程崩溃遗留的 pending/grading 行由每轮开头复位 + 轮询兜底重放；
- 回填后重算本场会话得分与 Result（复用 apply_exam_result 幂等 upsert，与 ledger 正交），
  并经 create_notification → ORM 事件自动走 Socket.IO 实时推送。
"""
import threading

from utils.logger import logger

MAX_ATTEMPTS = 3          # 单条作答最多评测次数，超限置 failed 终态
BATCH_LIMIT = 20          # 单轮最多处理条数（防长尾批量挤占）

_wake = threading.Event()
_stop = threading.Event()
_thread = None
_thread_lock = threading.Lock()

PENDING = 'pending'
GRADING = 'grading'
DONE = 'done'
FAILED = 'failed'


def async_enabled():
    from config import Config
    return bool(getattr(Config, 'OJ_ASYNC_GRADING', False))


def wake():
    """提醒后台线程立即排空（交卷后调用；未被唤醒时也会按间隔轮询兜底）。"""
    _wake.set()


def _claim(answer_id):
    """原子抢占：仅当仍处于 pending 时翻转为 grading。返回是否抢占成功（幂等判重）。"""
    from database import db
    from database.models import Answer
    n = db.session.query(Answer).filter(Answer.id == answer_id,
                                        Answer.oj_status == PENDING).update(
        {Answer.oj_status: GRADING}, synchronize_session=False)
    db.session.commit()
    return bool(n)


def _grade_one(answer_id):
    """评测一条已抢占（grading）的作答并回填。

    返回 True=已出结果（done），False=回落人工/跳过，
    异常向上抛出由 _process 统一按重放/终态处理。
    """
    from database import db
    from database.models import Answer, Question, ExamQuestion, ExamSession
    from oj.services import grade

    ans = db.session.get(Answer, answer_id)
    if ans is None or ans.oj_status != GRADING:
        return False                          # 已被清理/回滚，跳过
    question = db.session.get(Question, ans.question_id)
    if question is None:
        ans.oj_status = FAILED
        return False
    sess = db.session.get(ExamSession, ans.session_id)
    eq = db.session.query(ExamQuestion).filter_by(
        exam_id=sess.exam_id, question_id=ans.question_id).first() if sess else None
    eq_score = (eq.score if eq is not None else 0.0) or 0.0

    r = grade(ans.student_answer or '', getattr(question, 'language', None) or 'python',
              question.test_cases)
    if not r['supported']:
        # 语言未注册/工具链缺失：回落既有 AI/人工链路（与同步口径一致）
        ans.oj_status = None
        ans.oj_verdict = None
        ans.needs_manual_grade = True
        db.session.commit()
        return False

    ratio = (r['passed'] / r['total']) if r['total'] else 0.0
    ans.oj_verdict = r['verdict']
    ans.is_correct = r['verdict'] == 'AC'
    ans.score = round(eq_score * ratio, 2)
    ans.needs_manual_grade = False
    ans.oj_status = DONE
    db.session.commit()
    return True


def _resettle(session_id, graded=False):
    """回填后重算该会话得分与 Result（best/last 幂等），并联动错题/掌握度 + 通知学生。

    口径与交卷链路一致：earned=Σ(manual_score 优先，否则 score)，total=Σ会话题单满分。
    graded=True 且本会话已无未完成项时才发「评测完成」通知（回落人工的不发）。
    """
    from database import db
    from database.models import Answer, Exam, ExamQuestion, ExamSession
    from api.exam_engine import apply_exam_result, session_question_ids, update_mastery_from_exam
    from api.learning_routes import sync_wrong_from_exam
    from utils.notify import create_notification

    sess = db.session.get(ExamSession, session_id)
    if sess is None:
        return
    exam = db.session.get(Exam, sess.exam_id)
    eqs = db.session.query(ExamQuestion).filter_by(exam_id=sess.exam_id).all()
    score_map = {eq.question_id: eq.score for eq in eqs}
    paper_ids = [qid for qid in session_question_ids(sess, exam) if qid in score_map]
    answers = Answer.query.filter_by(session_id=sess.id).all()
    earned = sum((a.manual_score if a.manual_score is not None else (a.score or 0))
                 for a in answers if a.question_id in paper_ids)
    total = sum(score_map[qid] for qid in paper_ids)
    sess.score = round(earned, 2)
    apply_exam_result(sess, round(earned, 2), round(total, 2))
    db.session.commit()

    # 错题/掌握度联动：交卷时对 pending 行按暂定值跳过，此处以终值补做（非关键路径）
    if not any(a.oj_status in (PENDING, GRADING) for a in answers):
        try:
            sync_wrong_from_exam(sess.student_id, sess.exam_id, session_id=sess.id)
        except Exception:
            logger.exception('[oj-queue] 错题联动失败（非关键）session_id=%s', sess.id)
        try:
            update_mastery_from_exam(sess.student_id, sess.id)
        except Exception:
            logger.exception('[oj-queue] 掌握度联动失败（非关键）session_id=%s', sess.id)
        # 评测完成通知（经 notify_socket ORM 事件实时推送）；未发布成绩不提分数
        if graded:
            try:
                published = bool(exam is not None and exam.results_published)
                content = (f'「{exam.title if exam else "考试"}」编程题评测已完成，'
                           + (f'当前得分 {round(earned, 1)}/{round(total, 1)}。' if published
                              else '成绩公布后可在成绩单查看。'))
                create_notification(sess.student_id, '编程题评测完成', content,
                                    type='success', related_type='exam', related_id=sess.exam_id)
            except Exception:
                logger.exception('[oj-queue] 评测完成通知失败（非关键）session_id=%s', sess.id)


def _process(answer_id):
    """评测一条作答的完整事务（抢占→判分→回填→重算→失败重放）。返回是否真出了 verdict。"""
    from database import db
    from database.models import Answer
    if not _claim(answer_id):
        return False                          # 已被他人抢占或状态已变，幂等跳过
    graded = False
    try:
        graded = _grade_one(answer_id)
        ans = db.session.get(Answer, answer_id)
        _resettle(ans.session_id if ans else None, graded=graded)
        return graded
    except Exception:
        db.session.rollback()
        ans = db.session.get(Answer, answer_id)
        if ans is not None:
            ans.oj_attempts = (ans.oj_attempts or 0) + 1
            ans.oj_status = FAILED if ans.oj_attempts >= MAX_ATTEMPTS else PENDING
            db.session.commit()
        logger.exception('[oj-queue] 评测异常 answer_id=%s（回炉重放/超限终态）', answer_id)
        return False


def has_pending(session_id):
    """本会话是否存在未完成异步评测（pending/grading）。交卷链路据此暂缓错题/掌握度联动。"""
    from database import db
    from database.models import Answer
    return db.session.query(Answer.id).filter(
        Answer.session_id == session_id,
        Answer.oj_status.in_([PENDING, GRADING])).first() is not None


def process_once(limit=BATCH_LIMIT):
    """排空一轮 pending 队列（在 app_context 内调用）。返回处理条数。

    单线程消费模型：轮次开始时残留的 grading 行必为上次崩溃/异常遗留，先复位 pending；
    超限 failed 行不自动重试（留待人工处置），幂等抢占防双评。"""
    from database import db
    from database.models import Answer
    db.session.query(Answer).filter(Answer.oj_status == GRADING).update(
        {Answer.oj_status: PENDING}, synchronize_session=False)
    db.session.commit()
    ids = [row[0] for row in db.session.query(Answer.id).filter(
        Answer.oj_status == PENDING).order_by(Answer.id).limit(limit).all()]
    done = 0
    for aid in ids:
        if _process(aid):
            done += 1
    return done


def drain_session(session_id):
    """立即同步排空某会话的 pending（测试/教师端「催评测」用；正常路径靠后台线程）。"""
    from database import db
    from database.models import Answer
    ids = [row[0] for row in db.session.query(Answer.id).filter(
        Answer.session_id == session_id, Answer.oj_status == PENDING).order_by(Answer.id).all()]
    n = 0
    for aid in ids:
        if _process(aid):
            n += 1
    return n


def pending_info(session_id):
    """会话异步评测状态摘要（轮询端点用）：{pending, items:[{answer_id,question_id,status,verdict,score}]}"""
    from database import db
    from database.models import Answer
    rows = Answer.query.filter_by(session_id=session_id).filter(
        Answer.oj_status.isnot(None)).all()
    items = [{'answer_id': a.id, 'question_id': a.question_id, 'status': a.oj_status,
              'verdict': a.oj_verdict, 'score': a.score, 'attempts': a.oj_attempts or 0}
             for a in rows]
    return {'pending': any(a['status'] in (PENDING, GRADING) for a in items), 'items': items}


# ── 后台线程装配（复用 utils/scheduler 的 daemon 线程模式，不引外部 MQ）──
def _loop(app, interval):
    while not _stop.is_set():
        _wake.wait(timeout=interval)
        _wake.clear()
        if _stop.is_set():
            break
        # 开关关闭时零 DB 查询（避免无用轮询）；开启后交卷 wake 最迟 interval 内接手
        if not async_enabled():
            continue
        with app.app_context():
            try:
                process_once()
            except Exception:
                logger.exception('[oj-queue] 后台评测轮异常')
                try:
                    from database import db
                    db.session.rollback()
                except Exception:
                    pass


def start_queue(app, interval: float = 5.0):
    """启动后台评测线程（幂等：重复调用不重复启动）。"""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, args=(app, interval),
                                   daemon=True, name='oj-queue')
        _thread.start()
        logger.info('[oj-queue] 异步评测线程已启动（间隔 %.1fs）', interval)


def stop_queue():
    """停止后台线程（测试收尾用；daemon 线程亦随进程退出）。"""
    global _thread
    _stop.set()
    _wake.set()
    _thread = None
