from ai_service.client import AIClient
from database.models import (
    Question, Major, QuestionTypeEnum, DifficultyEnum,
    Chapter, KnowledgePoint, KnowledgeEdge,
    LearningPath, LearningPathNode,
)
from config import Config
from utils.logger import logger
import json
import re

ai_client = AIClient()

def clean_json_text(text: str) -> str:
    """清洗AI返回文本，提取纯JSON字符串"""
    # 移除markdown代码块标记、换行、空格干扰
    text = re.sub(r'```(json)?', '', text)
    text = text.strip()
    return text

def ai_generate_questions(session, major_id: int, question_type: str, difficulty: str, count: int = 5, description: str = None, course_id: int = None, source: str = 'ai'):
    """使用AI生成题目并保存到数据库。

    session: SQLAlchemy Session（调用方传 db.session），统一用
    session.get/add/commit，避免形参名 db 与实际语义不符。
    """
    major = session.get(Major, major_id)
    if not major:
        logger.error(f"Failed to generate questions: major {major_id} not found")
        raise ValueError("专业不存在")

    logger.info(f"AI generating {count} questions for major {major.name} (type: {question_type}, difficulty: {difficulty})")
    
    try:
        result = ai_client.generate_question(major.name, question_type, difficulty, count, description, source)
        clean_text = clean_json_text(result)
        questions = []

        data_list = json.loads(clean_text)
        if isinstance(data_list, list):
            for data in data_list:
                if data.get("content") and data.get("answer"):
                    question = Question(
                        content=data["content"],
                        options=json.dumps(data.get("options", [])) if data.get("options") else None,
                        answer=data["answer"],
                        analysis=data.get("analysis", ""),
                        knowledge=data.get("knowledge", ""),
                        major_id=major_id,
                        course_id=course_id,
                        type=question_type,
                        difficulty=difficulty,
                        source=source
                    )
                    session.add(question)
                    questions.append(question)
        session.commit()
        logger.info(f"Successfully generated {len(questions)} questions")
        return questions
    except json.JSONDecodeError as e:
        logger.error(f"AI returned invalid JSON: {str(e)}", exc_info=True)
        raise Exception(f"AI返回内容不是有效JSON: {str(e)}")
    except Exception as e:
        logger.error(f"Error generating questions: {str(e)}", exc_info=True)
        raise

def ai_grade_exam(session, session_id: int):
    """AI批改考试：客观题本地比对，主观题调AI并标记人工评分。

    session: SQLAlchemy Session（调用方传 db.session）。
    统一以 session_id 为唯一入参（v4.0 修复）：调用方均持有会话 ID，
    exam_id/student_id 从会话内部获取，避免传参错配。
    v4.3 升级：按本次会话题单判分（含逐人随机卷）；未答题目补记 0 分作答行，
    total_score 覆盖全卷（修复旧版"未作答不计入总分"）；多选题遵循 exam.multi_score_rule。
    返回 (earned_score, total_score)，仅负责判分与写 Answer，不创建 Result。
    """
    from database.models import ExamSession, Exam, Answer, ExamQuestion, Question
    from api.exam_engine import check_objective, session_question_ids

    exam_session = session.get(ExamSession, session_id)
    if not exam_session:
        raise ValueError("考试会话不存在")
    exam_id = exam_session.exam_id
    exam = session.get(Exam, exam_id)
    rule = (getattr(exam, 'multi_score_rule', None) or 'all_or_nothing')

    # 批量预载题单配置与题目实体，消除逐答案 N+1
    eqs = ExamQuestion.query.filter_by(exam_id=exam_id).all()
    eq_map = {eq.question_id: eq for eq in eqs}
    q_ids = [qid for qid in session_question_ids(exam_session, exam) if qid in eq_map]
    questions = {q.id: q for q in Question.query.filter(Question.id.in_(q_ids)).all()} if q_ids else {}
    answers = {a.question_id: a for a in Answer.query.filter_by(session_id=exam_session.id).all()}

    total_score = 0
    earned_score = 0

    for qid in q_ids:
        exam_question = eq_map.get(qid)
        question = questions.get(qid)
        if not (exam_question and question):
            continue

        total_score += exam_question.score
        answer = answers.get(qid)
        if answer is None:
            # 未答题补记空作答行（判 0 分，主观题空答不再送人工）
            answer = Answer(session_id=exam_session.id, question_id=qid, student_answer='')
            session.add(answer)
            answers[qid] = answer
        student_ans = (answer.student_answer or '').strip()
        correct_ans = (question.answer or '').strip()

        # ── v4.7 编程题 OJ 自动评测：有用例时按 AC 通过率判分，不再送 AI/人工；
        #    无用例或非 Python 语言回落既有主观题链路 ──
        if question.type == QuestionTypeEnum.PROGRAMMING and getattr(question, 'test_cases', None):
            from oj.services import grade as oj_grade
            if not student_ans:
                answer.needs_manual_grade = False
                answer.is_correct = False
                answer.score = 0
                answer.oj_verdict = 'CE'
                continue
            oj_result = oj_grade(student_ans, 'python', question.test_cases)
            if oj_result['supported']:
                ratio = (oj_result['passed'] / oj_result['total']) if oj_result['total'] else 0.0
                answer.needs_manual_grade = False
                answer.is_correct = oj_result['verdict'] == 'AC'
                answer.score = round(exam_question.score * ratio, 2)
                answer.oj_verdict = oj_result['verdict']
                earned_score += answer.score
                continue

        # 主观题标记需要人工评分，并调用AI语义批改
        if QuestionTypeEnum.is_subjective(question.type):
            if not student_ans:
                answer.needs_manual_grade = False
                answer.is_correct = False
                answer.score = 0
                continue
            answer.needs_manual_grade = True
            try:
                result = ai_client.grade_answer(question.content, question.answer, student_ans)
                data = json.loads(result)
                answer.is_correct = data.get('is_correct', False)
                # AI 返回 0-100 百分比，clamp 到 [0, 100] 防止异常值，再换算题目满分
                ratio = max(0.0, min(float(data.get('score', 0) or 0), 100.0)) / 100.0
                answer.score = round(ratio * exam_question.score, 2)
                earned_score += answer.score
            except Exception:
                # AI 调用失败，主观题先给 0 分，等人工评分
                answer.is_correct = False
                answer.score = 0
            continue

        # ── 客观题：本地比对（多选 partial 规则由 exam_engine.check_objective 统一实现）──
        is_correct, score_ratio = check_objective(question.type, student_ans, correct_ans, rule)
        answer.is_correct = is_correct
        answer.score = round(exam_question.score * score_ratio, 2)
        earned_score += answer.score

    session.commit()
    return earned_score, total_score

def ai_generate_analysis(session, question_id: int, student_answer: str):
    """生成单题解析。

    session: SQLAlchemy Session（调用方传 db.session）。
    """
    question = session.get(Question, question_id)
    if not question:
        raise ValueError("题目不存在")

    result = ai_client.generate_analysis(question.content, question.answer, student_answer)

    return result


# ── 三期：AI 生成路径骨架 / AI 学习助手对话 ──────────────────────────

_EDGE_RELATIONS = ('prerequisite', 'related', 'derived')


def ai_generate_path_skeleton(session, major_id: int, title: str, chapter_ids: list,
                              description: str = None, estimated_minutes: int = 30,
                              creator_id: int = None, learning_goal: str = None,
                              start_date=None, target_end_date=None):
    """AI 生成学习路径骨架：按章节拆解知识点 + 依赖边 + 推荐顺序，落库为草稿路径。

    session: SQLAlchemy Session（调用方传 db.session）。
    返回 (path, stats)：stats 含 kp_created/kp_existing/edges_created/nodes_created。
    知识点按 (chapter_id, name) 幂等 upsert：已存在直接复用，不重复创建。
    """
    major = session.get(Major, major_id)
    if not major:
        raise ValueError("专业不存在")
    chapters = [c for c in (session.get(Chapter, cid) for cid in chapter_ids) if c]
    if not chapters:
        raise ValueError("请至少选择一个有效章节")

    chapter_brief = "\n".join(
        f"{i}. 章节「{ch.name}」（所属课程：{ch.course.name if ch.course else '未知'}）"
        for i, ch in enumerate(chapters, 1)
    )
    prompt = f"""请为{major.name}专业设计一条学习路径的知识骨架，覆盖以下章节：
{chapter_brief}

要求：
1. 每个章节拆解 3~6 个核心知识点，知识点名称在整条路径内必须唯一、简洁（不超过20字）
2. 标注知识点难度（easy/medium/hard）、章内顺序 order_num（从1开始）、所属章节下标 chapter_index（从0开始，对应上面章节编号-1）
3. 给出知识点之间的依赖关系边，relation_type 只能是 prerequisite（先学）/ related（关联）/ derived（衍生）
4. 给出推荐学习顺序 node_order：按学习先后排列的知识点名称列表
5. description 用一句话说明该知识点学什么

仅输出标准 JSON 对象，禁止任何多余文字、markdown、注释：
{{
    "knowledge_points": [
        {{"name": "知识点名", "description": "一句话说明", "difficulty": "easy", "chapter_index": 0, "order_num": 1}}
    ],
    "edges": [
        {{"source_name": "前置知识点名", "target_name": "后继知识点名", "relation_type": "prerequisite"}}
    ],
    "node_order": ["知识点名1", "知识点名2"]
}}"""

    system = "你是课程设计专家，只输出标准JSON，不要多余文字、标题、注释、换行说明"
    logger.info(f"AI generating path skeleton for major {major.name}, chapters={chapter_ids}")
    try:
        raw = ai_client.generate_json(system, prompt, temp=0.5, max_tok=4000)
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"AI path skeleton returned invalid JSON: {str(e)}", exc_info=True)
        raise Exception("AI返回内容不是有效JSON，请重试")
    except Exception:
        logger.exception("AI 生成路径骨架失败")
        raise

    if not isinstance(data, dict):
        raise Exception("AI返回结构不符合预期，请重试")

    # 1) 知识点幂等 upsert：按 (chapter_id, name) 查重，存在复用、不存在新建
    name_to_kp = {}
    stats = {'kp_created': 0, 'kp_existing': 0, 'edges_created': 0, 'nodes_created': 0}
    for item in data.get('knowledge_points') or []:
        name = str(item.get('name') or '').strip()[:80]
        if not name:
            continue
        idx = item.get('chapter_index')
        chapter = chapters[idx] if isinstance(idx, int) and 0 <= idx < len(chapters) else chapters[0]
        difficulty = item.get('difficulty') if item.get('difficulty') in ('easy', 'medium', 'hard') else 'easy'
        try:
            order_num = max(0, int(item.get('order_num') or 0))
        except (TypeError, ValueError):
            order_num = 0
        kp = KnowledgePoint.query.filter_by(chapter_id=chapter.id, name=name).first()
        if kp:
            stats['kp_existing'] += 1
        else:
            kp = KnowledgePoint(
                chapter_id=chapter.id, name=name,
                description=(str(item.get('description') or '').strip() or None),
                order_num=order_num, difficulty=difficulty,
            )
            session.add(kp)
            session.flush()  # 立即拿 id，供建边与建节点使用
            stats['kp_created'] += 1
        name_to_kp[name] = kp

    # 2) 依赖边：名称映射回 id，跳过缺失/自环/重复
    for e in data.get('edges') or []:
        src = name_to_kp.get(str(e.get('source_name') or '').strip())
        dst = name_to_kp.get(str(e.get('target_name') or '').strip())
        if not src or not dst or src.id == dst.id:
            continue
        relation = e.get('relation_type') if e.get('relation_type') in _EDGE_RELATIONS else 'related'
        exists = KnowledgeEdge.query.filter_by(
            source_id=src.id, target_id=dst.id, relation_type=relation).first()
        if exists:
            continue
        session.add(KnowledgeEdge(source_id=src.id, target_id=dst.id, relation_type=relation, weight=1.0))
        stats['edges_created'] += 1

    # 3) 创建草稿路径：同 major+title 撞唯一约束时自动升版本
    version = 'v1'
    while session.query(LearningPath.id).filter_by(
            major_id=major_id, title=title, version=version).first():
        num = int(version[1:]) + 1
        version = f'v{num}'
    path = LearningPath(
        major_id=major_id, title=title, description=description,
        learning_goal=learning_goal,
        start_date=start_date, target_end_date=target_end_date,
        difficulty='medium', version=version, creator_id=creator_id,
    )

    # 4) 按 node_order 生成节点序列；node_order 缺失时按创建顺序兜底
    ordered_names = [str(n).strip() for n in (data.get('node_order') or [])]
    ordered_kps = [name_to_kp[n] for n in ordered_names if n in name_to_kp]
    for name, kp in name_to_kp.items():
        if kp not in ordered_kps:
            ordered_kps.append(kp)

    session.add(path)
    session.flush()
    for i, kp in enumerate(ordered_kps, 1):
        session.add(LearningPathNode(
            path_id=path.id, node_type='knowledge_point',
            knowledge_point_id=kp.id, chapter_id=kp.chapter_id,
            order_num=i, role='core', estimated_minutes=estimated_minutes,
        ))
        stats['nodes_created'] += 1

    session.commit()
    logger.info(f"Path skeleton created: path={path.id}, stats={stats}")
    return path, stats


def ai_chat_reply(session, messages: list, context: str = None):
    """AI 学习助手多轮对话（服务端无状态，历史由前端持有）。

    session: SQLAlchemy Session（调用方传 db.session，本函数不直接读写库）。
    messages: [{'role': 'user'|'assistant', 'content': str}]，服务端截取最近12条防超长。
    context: 页面背景摘要（前端按所在页面拼接），注入 system 提升建议针对性。
    返回纯文本回复。
    """
    system = (
        "你是「智汇学场」学习平台的 AI 学习助手，擅长讲解知识点、分析错题错因、"
        "规划学习路径和给出复习建议。要求：用简体中文回答；友好耐心、结构清晰（可分点）；"
        "控制在300字以内；只讨论与学习相关的话题，拒绝提供任何考试作弊帮助。"
    )
    if context:
        system += f"\n学生当前所在的页面背景：{context}"

    cleaned = [
        {'role': m['role'], 'content': str(m.get('content') or '').strip()}
        for m in messages
        if isinstance(m, dict) and m.get('role') in ('user', 'assistant')
        and str(m.get('content') or '').strip()
    ][-12:]
    if not cleaned:
        raise ValueError("对话内容为空")

    return ai_client.chat([{'role': 'system', 'content': system}] + cleaned)


_CHAT_SYSTEM = (
    "你是「智汇学场」学习平台的 AI 学习助手，擅长讲解知识点、分析错题错因、"
    "规划学习路径和给出复习建议。要求：用简体中文回答；友好耐心、结构清晰（可分点）；"
    "控制在300字以内；只讨论与学习相关的话题，拒绝提供任何考试作弊帮助。"
)


def build_chat_system(context: str = None) -> str:
    """拼装学习助手 system 提示（流式/非流式共用）"""
    return _CHAT_SYSTEM + (f"\n学生当前所在的页面背景：{context}" if context else "")


def chat_stream_iter(messages: list, system: str):
    """流式对话生成器：逐块 yield 增量文本；AI 失败时 yield 降级提示后正常结束。

    messages: [{'role': 'user'|'assistant', 'content': str}] 历史（不含 system）。
    调用方负责持久化聚合后的完整回复（是否降级看首块前缀标记）。
    """
    try:
        yielded = False
        for delta in ai_client.chat_stream([{'role': 'system', 'content': system}] + messages):
            yielded = True
            yield delta
        if not yielded:
            yield from _degraded_chat_iter(system, messages)
    except Exception:
        logger.exception('AI 流式对话失败，降级规则回复')
        yield from _degraded_chat_iter(system, messages)


def _degraded_chat_iter(system: str, messages: list):
    """AI 不可用时的规则化降级回复：明确告知降级，不误导学生"""
    last_q = next((m['content'] for m in reversed(messages) if m.get('role') == 'user'), '')
    text = (
        "【AI 服务暂不可用，以下为系统自动建议】\n"
        f"关于「{last_q[:40]}」的建议：\n"
        "1. 先到错题本回顾相关错题，用解析理解正确思路；\n"
        "2. 在自由刷题中针对同名知识点练习 5~10 题验证掌握；\n"
        "3. 若仍困惑，可预约向老师请教并整理到学习笔记。\n"
        "稍后 AI 恢复后可重新提问获得针对性讲解。"
    )
    yield text


def ai_analyze_wrong_answer(session, question, wrong_answer: str, wrong_count: int) -> str:
    """错题逐题 AI 归因分析：诊断错因并给改进建议，返回纯文本。

    session: SQLAlchemy Session（调用方传 db.session，本函数不读写库）。
    异常抛 Exception，由调用方降级规则建议。
    """
    options = ''
    try:
        if question.options:
            opts = json.loads(question.options) if isinstance(question.options, str) else question.options
            options = '\n'.join(f"{chr(65 + i)}. {o}" for i, o in enumerate(opts[:8]))
    except Exception:
        options = str(question.options or '')[:500]
    system = (
        "你是错题诊断专家。用简体中文分析学生错因并给出改进建议。要求："
        "1) 先判断学生答案反映的具体错因（概念混淆/审题疏漏/计算失误/方法不会等），"
        "结合干扰项特征推测思路偏差；2) 用一两句话点破本题考点与正确思路；"
        "3) 给出 1~2 条可执行的后续行动建议。总字数 150 字以内，"
        "直接输出正文，不要标题、不要前缀、不要 markdown。"
    )
    prompt = (
        f"题目：{question.content}\n"
        f"{('选项：\n' + options) if options else ''}\n"
        f"正确答案：{question.answer}\n"
        f"学生答案：{wrong_answer or '（未作答）'}\n"
        f"该题累计答错：{wrong_count} 次"
    )
    return ai_client.chat([{'role': 'system', 'content': system},
                           {'role': 'user', 'content': prompt}], temp=0.4, max_tok=600)


def ai_explain_topic(session, topic: str, kp_hint: str = None) -> str:
    """知识点即问即讲：生成结构化讲解卡内容，返回纯文本 markdown。

    session: SQLAlchemy Session（本函数不读写库）。
    kp_hint: 可选的库内知识点描述，帮 AI 对齐术语体系。
    """
    system = (
        "你是精讲老师。为学生制作一张知识点讲解卡，用简体中文 markdown，结构："
        "## 一句话说清楚（本质定义）；## 为什么重要（在专业体系中的位置）；"
        "## 核心要点（3~5 条，关键公式/术语用 **加粗**）；## 典型例子（1 个，贴近学生专业）；"
        "## 易错提醒（1~2 条）。总字数 400 字以内，只输出卡片正文。"
    )
    prompt = f"讲解主题：{topic}"
    if kp_hint:
        prompt += f"\n（课程体系中该知识点的定位：{kp_hint}）"
    return ai_client.chat([{'role': 'system', 'content': system},
                           {'role': 'user', 'content': prompt}], temp=0.5, max_tok=1200)


def ai_polish_note(session, kp_name: str, note_text: str):
    """AI 润色/提炼个人知识点笔记：保留木意、结构化、纠正表述，返回纯文本。

    session: SQLAlchemy Session（调用方传 db.session，本函数不直接读写库）。
    """
    if not (note_text or '').strip():
        raise ValueError("笔记内容为空")
    system = (
        "你是学习笔记整理助手。把学生写的知识点笔记润色得更清晰、准确、结构化，"
        "保留原意与关键术语，修正错别字与概念表述，适当分点。用简体中文，"
        f"围绕知识点「{kp_name}」。只输出润色后的笔记正文，不要额外解释、标题或前缀。"
    )
    user_msg = (note_text or '').strip()[:4000]
    return ai_client.chat([{'role': 'system', 'content': system},
                           {'role': 'user', 'content': user_msg}], temp=0.5, max_tok=1200)


def ai_suggest_daily_tasks(session, context_text: str):
    """AI 生成每日学习任务建议：根据今日学习状态快照输出 3~5 条可执行任务。

    session: SQLAlchemy Session（调用方传 db.session，本函数不直接读写库）。
    context_text: 调用方聚合的用户现状描述（到期复习/待办计划/路径节点/薄弱项等）。
    返回任务标题字符串列表；输出异常抛 ValueError，由调用方降级为规则建议。
    """
    if not (context_text or '').strip():
        raise ValueError("学习状态快照为空")
    system = (
        "你是学习规划助手。根据学生今日学习状态，给出 3~5 条具体可执行的每日学习任务建议。"
        "要求：每条不超过 30 字、动词开头、可量化（题数/时长/知识点名）；"
        "优先覆盖：到期复习、薄弱知识点巩固、学习路径推进、计划待办。"
        "只讨论学习相关内容。仅输出标准 JSON 字符串数组，禁止多余文字："
        '["完成 10 道到期复习题", "学习路径节点「XXX」"]'
    )
    raw = ai_client.generate_json(system, context_text.strip()[:2000], temp=0.6, max_tok=600)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"AI daily task suggestions returned invalid JSON: {raw[:200]}")
        raise ValueError("AI 建议输出格式异常")
    if not isinstance(data, list):
        raise ValueError("AI 建议输出结构异常")
    out = [str(x).strip()[:200] for x in data if str(x or '').strip()]
    if not out:
        raise ValueError("AI 未返回有效建议")
    return out[:5]


def ai_suggest_plan_tasks(session, goal_text: str, kp_lines: str, days: int, allowed_kp_ids=None):
    """AI 拆解学习目标为学习计划任务清单（4~8 条）。

    session: SQLAlchemy Session（本函数不直接读写库）。
    goal_text: 计划标题+目标描述；kp_lines: 可用知识点 "id|名称" 多行文本（可为空）；
    days: 计划周期天数；allowed_kp_ids: 允许引用的知识点 id 集合（防幻觉）。
    返回任务 dict 列表（含 due_day 第几天）；输出异常抛 ValueError，由调用方降级规则拆解。
    """
    if not (goal_text or '').strip():
        raise ValueError("计划目标为空")
    days = max(1, min(int(days or 14), 365))
    allowed_kp_ids = set(allowed_kp_ids or [])
    system = (
        "你是学习规划助手。把学生的学习目标拆解成 4~8 个按时间递进、可执行的任务。要求："
        "task_type 只能取 knowledge_point（学某个知识点）/ practice（刷题）/ custom（其他，如看书/整理笔记）；"
        "knowledge_point_id 只能来自给定知识点列表，没有合适项则置 null；"
        "任务按周期均匀分布，due_day 为第几天完成（1~"
        f"{days}的整数，递增）；estimated_minutes 为单次投入时长(10~180)。"
        "只讨论学习相关内容。仅输出标准 JSON 数组，禁止多余文字："
        '[{"title":"掌握「栈与队列」并配套练习","task_type":"knowledge_point",'
        '"knowledge_point_id":12,"question_count":5,"estimated_minutes":45,"due_day":3}]'
    )
    prompt = (f"学习目标：{goal_text.strip()[:1000]}\n计划周期：{days} 天内完成\n"
              f"可用知识点（格式 id|名称）：\n{(kp_lines or '（无）')[:1500]}\n请输出任务拆解 JSON 数组。")
    raw = ai_client.generate_json(system, prompt, temp=0.5, max_tok=1500)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"AI plan tasks returned invalid JSON: {raw[:200]}")
        raise ValueError("AI 拆解输出格式异常")
    if not isinstance(data, list) or not data:
        raise ValueError("AI 拆解输出结构异常")
    out = []
    for item in data[:8]:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()[:200]
        if not title:
            continue
        ttype = item.get('task_type') if item.get('task_type') in ('knowledge_point', 'practice', 'custom') else 'custom'
        try:
            kp_id = int(item.get('knowledge_point_id')) if item.get('knowledge_point_id') else None
        except (TypeError, ValueError):
            kp_id = None
        if kp_id not in allowed_kp_ids:
            kp_id = None
        if ttype == 'knowledge_point' and kp_id is None:
            ttype = 'custom'   # 无有效知识点Id时降为自定义，避免前端展示断层
        def _clip(v, lo, hi, default=None):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return default
            return max(lo, min(v, hi))
        try:
            due_day = max(1, min(int(item.get('due_day') or 0), days)) or None
        except (TypeError, ValueError):
            due_day = None
        out.append({'title': title, 'task_type': ttype, 'knowledge_point_id': kp_id,
                    'question_count': _clip(item.get('question_count'), 1, 50) if ttype == 'practice' else (_clip(item.get('question_count'), 1, 50, 5) if ttype == 'knowledge_point' else None),
                    'estimated_minutes': _clip(item.get('estimated_minutes'), 5, 240, 45),
                    'due_day': due_day})
    if not out:
        raise ValueError("AI 未返回有效任务")
    return out


# ── v4.5 多形态 AI 学习资料生成 ────────────────────────────────────

MATERIAL_TEMPLATES = {
    'video_script': (
        "你是学习视频文案策划。基于以下知识点制作一段 3-6 分钟短教学视频的完整素材包，用 markdown 输出：\n"
        "1) 口播文案（口语化、[画面]/[口播]分段）；2) 字幕文本（按句拆行）；\n"
        "3) 分镜脚本表（镜号/画面描述/口播词/时长）；4) 知识点总结（≤5 条要点）；\n"
        "5) 随堂小题（3 道选择题附答案解析）。\n学科：{subject}；难度：{difficulty}。\n知识点：{prompt}"
    ),
    'mindmap': (
        "你是知识体系梳理专家。基于以下知识点输出：\n"
        "第一部分：结构化学习文档（概念定义/原理剖析/案例讲解/易错点/总结/课后习题 5 道带答案）；\n"
        "第二部分：一个 ```mermaid 代码块的 mindmap 思维导图，层级不少于 3 层。\n"
        "学科：{subject}；难度：{difficulty}。\n知识点：{prompt}"
    ),
    'lecture': (
        "你是学习讲义撰写专家。基于以下知识点撰写结构化学习讲义，包含：\n"
        "概念定义、原理剖析、案例讲解、易错点、小结、课后习题 5 道带答案。\n"
        "学科：{subject}；难度：{difficulty}。\n知识点：{prompt}"
    ),
    'summary': (
        "把以下知识点提炼为不超过 300 字的高浓度总结，结构化分点，关键术语加粗。\n"
        "学科：{subject}；难度：{difficulty}。\n知识点：{prompt}"
    ),
    'quiz': (
        "基于以下知识点出 5 道练习题（4 选择 + 1 简答），每题附标准答案与解析，"
        "选择题用 markdown 列表给出选项。\n学科：{subject}；难度：{difficulty}。\n知识点：{prompt}"
    ),
}

MATERIAL_KIND_NAMES = {
    'video_script': '视频脚本包', 'mindmap': '讲义+思维导图', 'lecture': '结构化讲义',
    'summary': '高浓度摘要', 'quiz': '练习题集',
}


def _degraded_material(kind, prompt, subject, difficulty):
    """AI 不可用时的降级框架大纲（对齐项目降级哲学，首行标注来源）"""
    name = MATERIAL_KIND_NAMES.get(kind, '学习资料')
    return (
        "【AI 服务暂不可用】以下为系统生成的资料框架大纲，可稍后重新生成完整内容。\n\n"
        f"# {prompt} · {name}\n\n"
        "## 概念定义\n（是什么：用一句话给出本质定义，再展开术语解释）\n\n"
        "## 原理剖析\n（为什么成立：推导/机制/适用条件）\n\n"
        "## 典型案例\n（怎么用：结合{subject}场景的 1-2 个例子）\n\n"
        "## 易错提醒\n（常见误区与辨析）\n\n"
        "## 本讲小结\n（3-5 条要点回顾）\n\n"
        "## 自测题\n（3-5 道，附答案）\n"
    ).replace('{subject}', subject or '本专业')


def ai_generate_material(session, prompt: str, kind: str = 'lecture',
                         subject: str = None, difficulty: str = None):
    """生成一份学习资料 markdown。返回 (content, degraded)；AI 失败降级为框架大纲。

    session: SQLAlchemy Session（本函数不读写库，与同类函数签名保持一致）。
    """
    tpl = MATERIAL_TEMPLATES.get(kind)
    if not tpl:
        raise ValueError("未知资料类型：" + str(kind))
    text = tpl.format(prompt=prompt.strip()[:500], subject=subject or '通用',
                      difficulty=difficulty or '常规')
    try:
        content = ai_client.chat(
            [{'role': 'system', 'content': '你是面向高校师生的自学习平台内容生成助手，用简体中文 markdown 输出，结构清晰。'},
             {'role': 'user', 'content': text}],
            temp=0.6, max_tok=4000)
        if content and content.strip():
            return content.strip(), False
    except Exception as e:
        logger.warning(f"ai_generate_material degraded: {e}")
    return _degraded_material(kind, prompt, subject, difficulty), True


def ai_decide_material_kind(session, prompt: str) -> str:
    """AI 判断知识点体量：零散单一概念→video_script，体系性专题→mindmap。失败默认 mindmap。"""
    rule = (
        "判断以下知识点描述属于哪种体量，只输出一个 JSON："
        '{"kind":"small"或"system"}。规则：零散、简短、单一概念、3-6 分钟能讲完→small；'
        "章节、模块、多关联知识点的体系性主题→system。只输出 JSON。\n"
        f"知识点：{(prompt or '')[:300]}"
    )
    try:
        content = ai_client.chat([{'role': 'user', 'content': rule}], temp=0.1, max_tok=64)
        obj = json.loads(clean_json_text(content))
        return 'video_script' if obj.get('kind') == 'small' else 'mindmap'
    except Exception as e:
        logger.warning(f"ai_decide_material_kind fallback to mindmap: {e}")
        return 'mindmap'