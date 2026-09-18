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
    返回 (earned_score, total_score)，仅负责判分与写 Answer，不创建 Result。
    """
    from database.models import ExamSession, Answer, ExamQuestion, Question

    exam_session = session.get(ExamSession, session_id)
    if not exam_session:
        raise ValueError("考试会话不存在")
    exam_id = exam_session.exam_id

    answers = Answer.query.filter_by(session_id=exam_session.id).all()

    total_score = 0
    earned_score = 0
    OBJECTIVE_TYPES = {'single_choice', 'multiple_choice', 'true_false', 'fill_blank'}

    for answer in answers:
        exam_question = ExamQuestion.query.filter_by(exam_id=exam_id, question_id=answer.question_id).first()
        question = session.get(Question, answer.question_id)

        if not (exam_question and question):
            continue

        total_score += exam_question.score
        student_ans = (answer.student_answer or '').strip()
        correct_ans = (question.answer or '').strip()

        # 主观题标记需要人工评分，并调用AI语义批改
        if QuestionTypeEnum.is_subjective(question.type):
            answer.needs_manual_grade = True
            try:
                result = ai_client.grade_answer(question.content, question.answer, student_ans)
                data = json.loads(result)
                answer.is_correct = data.get('is_correct', False)
                # AI 返回 0-100 百分比，clamp 到 [0, 100] 防止异常值，再换算题目满分
                ratio = max(0.0, min(float(data.get('score', 0) or 0), 100.0))
                answer.score = (ratio / 100) * exam_question.score
                earned_score += answer.score
            except Exception:
                # AI 调用失败，主观题先给 0 分，等人工评分
                answer.is_correct = False
                answer.score = 0
            continue

        # ── 客观题：本地比对 ──────────────────────────────
        if question.type == 'multiple_choice':
            # 多选题：按字符排序后比较（允许答案顺序不同）
            s_sorted = ''.join(sorted(student_ans.upper()))
            c_sorted = ''.join(sorted(correct_ans.upper()))
            is_correct = s_sorted == c_sorted
        elif question.type == 'fill_blank':
            # 填空题：忽略大小写和多余空格
            is_correct = student_ans.lower() == correct_ans.lower()
        else:
            # 单选题 / 判断题：完全匹配（忽略大小写）
            is_correct = student_ans.upper() == correct_ans.upper()

        answer.is_correct = is_correct
        answer.score = exam_question.score if is_correct else 0
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