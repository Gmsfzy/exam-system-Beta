# -*- coding: utf-8 -*-
"""批量讲义生成队列（v7.9）。

学习计划生成后，教师/学生希望「每条任务都有一份详细文档」——一次 8 条任务就是 8 次
AI 调用，同步做必然超时（前端 axios 与网关都有秒级上限），故照 oj/queue.py 的同构
思路改成后台队列：

- 队列以 material_gen_job 表的 status 列为唯一事实源（不引外部 MQ）：
  pending→running→done/failed；
- 幂等：按 job_id 条件 UPDATE 抢占（仅 pending→running 成功者生成），重复投递/
  多 worker 不会双生成、不会双写资料；
- 失败可重放：异常回置 pending 并计 attempts，超限（MAX_ATTEMPTS）置 failed 终态；
  进程崩溃遗留的 running 行由每轮开头复位；
- 额度阻塞不同于失败：学生当日 AI 额度用完时任务**留在 pending 不计 attempts**，
  次日额度惰性重置后由轮询自动续跑（批量半途作废才是真浪费）；
- 整批完成后发一条站内通知（不是每份一条，8 条计划弹 8 次框属噪音），经
  notify_socket 的 ORM 事件自动实时推送；通知失败不影响已入库资料。

资料只在生成成功后才落 study_material：半成品/降级大纲不混进资料库与公开广场。
"""
import threading
import uuid

from utils.logger import logger

MAX_ATTEMPTS = 3          # 单份文档最多生成次数，超限置 failed 终态
BATCH_LIMIT = 20          # 单轮最多处理条数（一轮吃满一批 8 条还有余量）
DEFAULT_KIND = 'mindmap'  # 讲义+思维导图合一：一份文档同时给正文与导图

_wake = threading.Event()
_stop = threading.Event()
_thread = None
_thread_lock = threading.Lock()

PENDING = 'pending'
RUNNING = 'running'
DONE = 'done'
FAILED = 'failed'

# _run_one 的三态回执：done=已出成品，retry=可重试（回炉），blocked=额度不足留队
_R_DONE, _R_RETRY, _R_BLOCKED = 'done', 'retry', 'blocked'


def wake():
    """提醒后台线程立即排空（受理批量后调用；未被唤醒时也会按间隔轮询兜底）。"""
    _wake.set()


def new_batch_id():
    return uuid.uuid4().hex


def kind_name(kind):
    """形态中文名（提示词模板表同源）：通知/受理文案都要按形态说人话。

    未知形态回落到「学习文档」，不让文案层反过来把 bug 抛给用户。"""
    from ai_service.services import MATERIAL_KIND_NAMES
    return MATERIAL_KIND_NAMES.get(kind, '学习文档')


def _subject_of(plan):
    """资料学科：优先课程名，退到专业名（都空则交模板用「通用」）。

    StudyPlan 只有 course_id/major_id 外键列、没建 relationship，故显式取行。"""
    from database import db
    from database.models import Course, Major
    if plan.course_id:
        course = db.session.get(Course, plan.course_id)
        if course is not None and course.name:
            return course.name[:50]
    if plan.major_id:
        major = db.session.get(Major, plan.major_id)
        if major is not None and major.name:
            return major.name[:50]
    return None


def _prompt_of(task, plan):
    """喂 AI 的主题：任务标题 + 计划上下文。practice/custom 型任务没有知识点描述，
    只给标题会太薄，故带上计划名；KP 型再补一句知识点描述。"""
    parts = [task.title or '']
    if getattr(plan, 'title', None):
        parts.append(f'（学习计划：{plan.title}）')
    kp = getattr(task, 'knowledge_point', None)
    if kp is not None:
        desc = (kp.description or '').strip()
        parts.append(f'（知识点：{kp.name}' + (f'，{desc[:120]}' if desc else '') + '）')
    return ''.join(parts)[:500]


def enqueue(user, plan, kind=DEFAULT_KIND, force=False):
    """为计划的每条任务投一份生成作业（在 app_context 内调用，本函数只落队不等结果）。

    返回 (batch_id, queued, skipped)：
    - queued：本次实际投递的作业数；
    - skipped：该任务已有**同形态**成品资料、或同形态作业还在队列里没跑完的任务数
      （重复点按钮不该重复产出 8 份）。
    只给 pending 状态的任务补档？不——已完成的任务同样需要讲义可回看，故全量投。

    跳过判据必须带上 kind（v7.18 修的一类体验事故）：旧口径只按 task_id+active，
    于是「生成过讲义」会挡住「生成教案」——整批 5 条全被判为已有文档，前端弹「要全部
    重新生成吗」，用户一勾 force 就把讲义连教案一起从头重做。形态之间本就是不同的
    产物，各留一份互不干扰；与 _existing_material 的写入口径（user+kind+task）对齐后，
    「同形态重做=原地替换、异形态新增=另起一份」才是自洽的。
    """
    from database import db
    from database.models import MaterialGenJob, StudyMaterial
    from ai_service.services import MATERIAL_TEMPLATES

    # 形态白名单以模板表为单一事实源：有提示词模板才谈得上生成，
    # 新增形态（如 v7.14 lesson_plan 教案）只需改 services.py。
    kind = kind if kind in MATERIAL_TEMPLATES else DEFAULT_KIND
    batch_id = new_batch_id()
    # 在飞的同形态作业也要挡：成品资料是生成成功后才落库的，队列 10s 一轮，用户连点两次
    # 「生成教案」时第一次还没产出，只看 study_material 会照样再投一批（2026-11-13 真机冒烟
    # 实测第三次点击 queued=2/skipped=0）。落库口径上 _existing_material 会原地替换、数据不
    # 会翻倍，但白花一次 AI 额度并多扣一次配额，故按 pending/running 去重；
    # force（确认强制重做）与「重试失败项」（status=failed）不受此限。
    inflight = {row[0] for row in db.session.query(MaterialGenJob.task_id).filter(
        MaterialGenJob.plan_id == plan.id, MaterialGenJob.kind == kind,
        MaterialGenJob.status.in_([PENDING, RUNNING])).all() if row[0] is not None}
    queued = skipped = 0
    for task in (plan.tasks or []):
        if not force and (task.id in inflight or db.session.query(StudyMaterial.id).filter(
                StudyMaterial.task_id == task.id,
                StudyMaterial.kind == kind,
                StudyMaterial.status == 'active').first() is not None):
            skipped += 1
            continue
        kp = getattr(task, 'knowledge_point', None)
        db.session.add(MaterialGenJob(
            user_id=user.id, batch_id=batch_id, plan_id=plan.id, task_id=task.id,
            kind=kind, title=(task.title or '未命名任务')[:200],
            prompt=_prompt_of(task, plan)[:500], subject=_subject_of(plan),
            difficulty=(kp.difficulty if kp is not None else None),
            knowledge_point_id=task.knowledge_point_id, status=PENDING))
        queued += 1
    db.session.commit()
    return batch_id, queued, skipped


def _claim(job_id):
    """原子抢占：仅当仍处于 pending 时翻转为 running。返回是否抢到（幂等判重）。"""
    from database import db
    from database.models import MaterialGenJob
    n = db.session.query(MaterialGenJob).filter(
        MaterialGenJob.id == job_id,
        MaterialGenJob.status == PENDING).update(
        {MaterialGenJob.status: RUNNING}, synchronize_session=False)
    db.session.commit()
    return bool(n)


def _run_one(job_id):
    """生成一份资料并落库。返回 _R_DONE / _R_RETRY / _R_BLOCKED。"""
    from database import db
    from database.models import MaterialGenJob, StudyMaterial, User
    from ai_service.gate import check_ai_quota, charge_ai_quota, log_ai_usage
    from ai_service.services import ai_generate_material
    import time

    job = db.session.get(MaterialGenJob, job_id)
    if job is None or job.status != RUNNING:
        return _R_DONE                        # 已被清理/状态已变，视作处理完
    user = db.session.get(User, job.user_id)
    if user is None:
        job.status, job.error = FAILED, '用户不存在'
        db.session.commit()
        return _R_DONE

    allowed, _quota = check_ai_quota(user)
    if not allowed:
        # 额度不足留队：不计 attempts，次日 reset_date 惰性刷新后自动续跑
        db.session.query(MaterialGenJob).filter(MaterialGenJob.id == job_id).update(
            {MaterialGenJob.status: PENDING}, synchronize_session=False)
        db.session.commit()
        return _R_BLOCKED

    t0 = time.perf_counter()
    try:
        content, degraded = ai_generate_material(db.session, job.prompt, job.kind,
                                                 job.subject, job.difficulty)
    except Exception:
        db.session.rollback()
        _bump_retry(job_id, 'AI 调用异常')
        logger.exception('[material-queue] 生成异常 job_id=%s', job_id)
        return _R_RETRY

    job = db.session.get(MaterialGenJob, job_id)
    try:
        # 「同一任务的同一形态只留最新一份」：enqueue 的跳过判据按 task_id+kind+active，
        # 这里也必须按同一口径命中已有行原地替换。若一律新建，force 重做会让同一任务
        # 堆出两份（2026-11-12 真机实测：id 3-7 降级骨架与 id 8-12 真产出并存，旧骨架还
        # 留在资料库里挡视线），且已公开那份的收藏/浏览数会随重复行被割裂。
        m = _existing_material(job)
        if m is None:
            m = StudyMaterial(user_id=job.user_id, kind=job.kind, title=job.title[:200],
                              content=content[:30000], subject=job.subject,
                              difficulty=job.difficulty, knowledge_point_id=job.knowledge_point_id,
                              plan_id=job.plan_id, task_id=job.task_id, source='ai')
            db.session.add(m)
        else:
            m.kind = job.kind
            m.title = job.title[:200]
            m.content = content[:30000]
            m.subject = job.subject
            m.difficulty = job.difficulty
            m.knowledge_point_id = job.knowledge_point_id
            m.plan_id = job.plan_id
            m.task_id = job.task_id
            m.source = 'ai'                      # updated_at 由 onupdate 自动刷新
        charge_ai_quota(user)
        log_ai_usage(job.user_id, 'material_batch:' + job.kind,
                     'degraded' if degraded else 'success',
                     (time.perf_counter() - t0) * 1000)
        job.status = DONE
        job.material_id = None                # 下方 flush 后回填真实 id
        db.session.flush()
        job.material_id = m.id
        if degraded:
            job.error = 'AI 不可用，已落降级框架大纲'
        db.session.commit()
        return _R_DONE
    except Exception:
        db.session.rollback()
        _bump_retry(job_id, '资料入库异常')
        logger.exception('[material-queue] 入库异常 job_id=%s', job_id)
        return _R_RETRY


def _existing_material(job):
    """找该作业应当写入的那份已有资料（找不到则新建）。

    只认 active：被举报下架的 removed 行留作审核证据，重做时另出一份。
    task_id 优先（每条任务一份），退化到 plan_id（计划级文档），两者都空则不复用。"""
    from database import db
    from database.models import StudyMaterial
    q = db.session.query(StudyMaterial).filter(
        StudyMaterial.user_id == job.user_id,
        StudyMaterial.kind == job.kind,
        StudyMaterial.status == 'active')
    if job.task_id is not None:
        return q.filter(StudyMaterial.task_id == job.task_id).order_by(
            StudyMaterial.id.desc()).first()
    if job.plan_id is not None:
        return q.filter(StudyMaterial.plan_id == job.plan_id).order_by(
            StudyMaterial.id.desc()).first()
    return None


def _bump_retry(job_id, reason):
    """失败回炉：attempts+1，未超限回 pending，超限置 failed 终态。"""
    from database import db
    from database.models import MaterialGenJob
    job = db.session.get(MaterialGenJob, job_id)
    if job is None:
        return
    job.attempts = (job.attempts or 0) + 1
    job.error = (reason or '')[:200]
    job.status = FAILED if job.attempts >= MAX_ATTEMPTS else PENDING
    db.session.commit()


def _notify_batch(batch_id):
    """整批收尾通知（仅当批内不再有 pending/running）。通知是非关键路径，兜异常。"""
    from database import db
    from database.models import MaterialGenJob
    from utils.notify import create_notification

    jobs = MaterialGenJob.query.filter_by(batch_id=batch_id).all()
    if not jobs:
        return
    if any(j.status in (PENDING, RUNNING) for j in jobs):
        return                                # 还有活儿（多半卡在额度），不打扰
    user_id = jobs[0].user_id
    ok = sum(1 for j in jobs if j.status == DONE)
    bad = sum(1 for j in jobs if j.status == FAILED)
    plan = jobs[0].plan
    # 文案跟形态走：旧实现写死「批量讲义」，生成教案/摘要/练习题集回来也是这句，
    # 用户以为下错了指令（v7.18 需求 b）
    name = kind_name(jobs[0].kind)
    tail = f'，{bad} 份失败可在计划页重试。' if bad else '，可前往资料库查看。'
    title = f'批量{name}完成：{ok} 份'
    content = (f'「{plan.title if plan else "学习计划"}」的{name}已生成 {ok} 份' + tail)
    try:
        create_notification(user_id, title, content,
                            type='success' if ok else 'error', related_type='material')
    except Exception:
        db.session.rollback()
        logger.exception('[material-queue] 批量完成通知失败 batch_id=%s', batch_id)


def process_once(limit=BATCH_LIMIT):
    """排空一轮队列（在 app_context 内调用）。返回处理条数。

    轮次开头复位残留 running（上次崩溃/重启遗留），抢占保证不双生成；
    额度阻塞时提前收轮，避免无意义地逐条空转 AI 门禁查询。"""
    from database import db
    from database.models import MaterialGenJob
    db.session.query(MaterialGenJob).filter(MaterialGenJob.status == RUNNING).update(
        {MaterialGenJob.status: PENDING}, synchronize_session=False)
    db.session.commit()
    rows = db.session.query(MaterialGenJob.id, MaterialGenJob.batch_id).filter(
        MaterialGenJob.status == PENDING).order_by(MaterialGenJob.id).limit(limit).all()
    done = 0
    touched_batches = set()
    for job_id, batch_id in rows:
        touched_batches.add(batch_id)
        if not _claim(job_id):
            continue
        r = _run_one(job_id)
        if r == _R_DONE:
            done += 1
        elif r == _R_BLOCKED:
            break
    for batch_id in touched_batches:
        _notify_batch(batch_id)
    return done


def batch_info(batch_id, user_id):
    """批次进度摘要（前端轮询用）：{total, pending, running, done, failed, items:[...]}"""
    from database import db
    from database.models import MaterialGenJob
    jobs = MaterialGenJob.query.filter_by(batch_id=batch_id, user_id=user_id).order_by(
        MaterialGenJob.id).all()
    items = [{'id': j.id, 'task_id': j.task_id, 'title': j.title, 'status': j.status,
              'attempts': j.attempts or 0, 'material_id': j.material_id, 'error': j.error}
             for j in jobs]
    return {'batch_id': batch_id, 'total': len(items),
            'pending': sum(1 for i in items if i['status'] == PENDING),
            'running': sum(1 for i in items if i['status'] == RUNNING),
            'done': sum(1 for i in items if i['status'] == DONE),
            'failed': sum(1 for i in items if i['status'] == FAILED),
            'items': items}


def plan_documents(plan_id, user_id):
    """某计划已生成的文档清单（计划页直接列，省得用户去资料库大海捞针）。"""
    from database import db
    from database.models import StudyMaterial
    mats = StudyMaterial.query.filter(StudyMaterial.plan_id == plan_id,
                                      StudyMaterial.user_id == user_id,
                                      StudyMaterial.status == 'active').order_by(
        StudyMaterial.task_id, StudyMaterial.id.desc()).all()
    return mats


def purge_refs(plan_id=None, task_ids=()):
    """删计划/删任务前的反向引用清理（必须在建表时就想到的那一环）。

    v7.9 给 `study_material`/`material_gen_job` 加了 `plan_id/task_id` 外键后，
    「删一个曾生成过文档的学习计划」在 PG 上会被反向引用直接挡下（真机取证：
    `ForeignKeyViolation … material_gen_job_task_id_fkey`），而 SQLite 不强制外键、
    测试门全绿（与隐患 #23 同形状）。两条口径：
    - 作业行直接删：它是队列的过程数据，计划都没了留着只会指向空号；
    - 成品资料保留：文档是用户资产（可能已公开/被收藏），只摘掉 plan/task 反链。

    逐条改 ORM 对象而不用 `Query.update()/delete()`：bulk 写进不了实时镜像（#24）。"""
    from database import db
    from database.models import MaterialGenJob, StudyMaterial
    task_ids = list(task_ids or [])

    # 两个维度分开摘：删单条任务时只能动 task_id，把整个 plan 链一并洗掉会
    # 让同一计划剩下的文档从计划页上消失（那页是按 plan_id 列的）
    if plan_id is not None:
        for m in StudyMaterial.query.filter_by(plan_id=plan_id).all():
            m.plan_id = None
    if task_ids:
        for m in StudyMaterial.query.filter(StudyMaterial.task_id.in_(task_ids)).all():
            m.task_id = None

    jobs = []
    if plan_id is not None:
        jobs += MaterialGenJob.query.filter_by(plan_id=plan_id).all()
    if task_ids:
        jobs += [j for j in MaterialGenJob.query.filter(
            MaterialGenJob.task_id.in_(task_ids)).all() if j not in jobs]
    for job in jobs:
        db.session.delete(job)
    db.session.flush()                       # 先落这批改动，再让调用方删父行
    return len(jobs)


def retry_failed(batch_id, user_id):
    """把批内 failed 行重置为 pending 重放（人工点「重试失败项」；超限终态不自动复活）。"""
    from database import db
    from database.models import MaterialGenJob
    n = db.session.query(MaterialGenJob).filter(
        MaterialGenJob.batch_id == batch_id, MaterialGenJob.user_id == user_id,
        MaterialGenJob.status == FAILED).update({MaterialGenJob.status: PENDING,
                                                 MaterialGenJob.attempts: 0,
                                                 MaterialGenJob.error: None},
                                                synchronize_session=False)
    db.session.commit()
    if n:
        wake()
    return n


# ── 后台线程装配（与 oj/queue.py 同款 daemon 线程，不引外部 MQ）──
def _loop(app, interval):
    while not _stop.is_set():
        _wake.wait(timeout=interval)
        _wake.clear()
        if _stop.is_set():
            break
        with app.app_context():
            try:
                process_once()
            except Exception:
                logger.exception('[material-queue] 后台生成轮异常')
                try:
                    from database import db
                    db.session.rollback()
                except Exception:
                    pass


def start_queue(app, interval: float = 10.0):
    """启动后台生成线程（幂等：重复调用不重复启动）。"""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, args=(app, interval),
                                   daemon=True, name='material-queue')
        _thread.start()
        logger.info('[material-queue] 批量讲义线程已启动（间隔 %.1fs）', interval)


def stop_queue():
    """停止后台线程（测试收尾用；daemon 线程亦随进程退出）。"""
    global _thread
    _stop.set()
    _wake.set()
    _thread = None


def drain_once():
    """同步排空当前 pending（测试/「立即生成」按钮想当场看到结果时用）。"""
    return process_once(limit=200)
