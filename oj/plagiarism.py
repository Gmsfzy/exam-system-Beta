# -*- coding: utf-8 -*-
"""编程题代码抄袭查重：词级 shingle 指纹 + Jaccard 相似度（纯 Python，无外部服务）。

定位：OJ（v4.7）的天然配套缺口——系统已能评测编程题，却看不见学生之间抄代码。
本模块对同一道编程题的多份提交做两两指纹相似度比对，输出高相似对，供教师
阅卷/监考页人工复核线索。不依赖 MOSS/JPlag。

重要边界：相似度高 ≠ 必然抄袭（如都调用同一标准库、教师给的模板骨架、极短
代码），故仅作为**复核线索**而非自动判罚；比对前剔除空行/整行注释，过短提交
（<min_tokens）不参与以避免误报。
"""
import re
from collections import defaultdict

# 词法切分：标识符/数字/运算符/分隔符各成 token（跨语言的粗粒度近似）
_TOKEN_RE = re.compile(r"[A-Za-z_]\w*|\d+|[^\s\w]")
# 整行注释前缀：命中则丢弃该行（保守只处理整行，避免误删字符串内的 #/进行符）
_COMMENT_PREFIX = ('#', '//', '/*', '*', '--')


def _tokenize(code):
    """代码 → 归一化 token 列表：去整行注释/空行，词元小写。"""
    if not code:
        return []
    kept = []
    for line in code.splitlines():
        s = line.strip()
        if not s or s.startswith(_COMMENT_PREFIX):
            continue
        kept.append(s)
    tokens = _TOKEN_RE.findall('\n'.join(kept))
    return [t.lower() for t in tokens]


def _shingles(tokens, k):
    """token 序列 → k 元词组（shingle）指纹集合；序列过短退化为整体。"""
    if len(tokens) < k:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}


def similarity(code_a, code_b, k=4):
    """两段代码的 Jaccard 相似度 ∈ [0,1]（基于 k 元词组指纹集合）。"""
    sa = _shingles(_tokenize(code_a), k)
    sb = _shingles(_tokenize(code_b), k)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def compare_submissions(submissions, threshold=0.7, min_tokens=15, k=4):
    """对一份题目下的多份提交两两比对，返回相似度 ≥ threshold 的高相似对。

    submissions: [{'student_id', 'username', 'code'}, ...]
    返回: [{'a': {...}, 'b': {...}, 'similarity': float, 'tokens': int}, ...]，按相似度降序。
    """
    enriched = []
    for s in submissions:
        toks = _tokenize(s.get('code'))
        if len(toks) < min_tokens:  # 过短不参与（易误报）
            continue
        enriched.append({
            'student_id': s['student_id'],
            'username': s['username'],
            'shingles': _shingles(toks, k),
            'tokens': len(toks),
        })

    pairs = []
    n = len(enriched)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = enriched[i], enriched[j]
            union = len(a['shingles'] | b['shingles'])
            if not union:
                continue
            sim = len(a['shingles'] & b['shingles']) / union
            if sim >= threshold:
                pairs.append({
                    'a': {'student_id': a['student_id'], 'username': a['username']},
                    'b': {'student_id': b['student_id'], 'username': b['username']},
                    'similarity': round(sim, 4),
                    'tokens': min(a['tokens'], b['tokens']),
                })
    pairs.sort(key=lambda p: p['similarity'], reverse=True)
    return pairs


def _gather_submissions(exam_id, question_id=None):
    """取该考试编程题的作答，按 (题目, 学生) 归并（同学生多次作答取最长一份）。

    返回 {question_id: [ {student_id, username, code}, ... ]}。
    """
    from database.models import QuestionTypeEnum
    rows = db_answer_join(exam_id, question_id, QuestionTypeEnum.PROGRAMMING)
    grouped = defaultdict(dict)  # question_id -> student_id -> row(最长 code)
    for question_id_, student_id, username, code in rows:
        code = code or ''
        cur = grouped[question_id_].get(student_id)
        if cur is None or len(code) > len(cur['code']):
            grouped[question_id_][student_id] = {
                'student_id': student_id, 'username': username, 'code': code}
    return {qid: list(students.values()) for qid, students in grouped.items()}


def db_answer_join(exam_id, question_id, prog_type):
    """构造 (question_id, student_id, username, code) 四元组查询。"""
    from database.models import Answer, ExamSession, Question, User
    query = (
        Answer.query
        .join(ExamSession, Answer.session_id == ExamSession.id)
        .join(Question, Answer.question_id == Question.id)
        .join(User, ExamSession.student_id == User.id)
        .filter(ExamSession.exam_id == exam_id, Question.type == prog_type)
    )
    if question_id is not None:
        query = query.filter(Question.id == question_id)
    return query.with_entities(
        Answer.question_id, ExamSession.student_id, User.username,
        Answer.student_answer)


def find_similar_pairs(exam_id, question_id=None, threshold=0.7,
                       min_tokens=15, k=4):
    """按题目分组返回高相似对；仅含编程题，跳过无任何高相似的题目。

    返回: [{'question_id', 'pairs': [...]}, ...]，题目按最高相似度降序。
    """
    by_question = _gather_submissions(exam_id, question_id)
    results = []
    for qid, subs in by_question.items():
        pairs = compare_submissions(subs, threshold=threshold,
                                    min_tokens=min_tokens, k=k)
        if pairs:
            results.append({'question_id': qid, 'pairs': pairs})
    results.sort(key=lambda r: max(p['similarity'] for p in r['pairs']),
                 reverse=True)
    return results


# ═══════════════════════ 文本相似度（开放式作业 / 中文文本） ═══════════════════════
# 中文无空格分词，采用字符 n-gram shingle + Jaccard，与代码路径同口径，
# 但 token=单字符（含中英文/数字），去空白。
_TEXT_NORMALIZE_RE = re.compile(r'\s+')


def _char_shingles(text, k):
    """文本 → 字符 k-gram 指纹集合；过短退化为整体。"""
    if not text:
        return set()
    s = _TEXT_NORMALIZE_RE.sub('', text)
    if len(s) < k:
        return {s} if s else set()
    return {s[i:i + k] for i in range(len(s) - k + 1)}


def text_similarity(text_a, text_b, k=4):
    """两段文本的 Jaccard 相似度 ∈ [0,1]（字符 k-gram）。"""
    sa = _char_shingles(text_a, k)
    sb = _char_shingles(text_b, k)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def compare_text_submissions(submissions, threshold=0.7, min_chars=20, k=4):
    """开放式文本作答两两比对，返回相似度 ≥ threshold 的高相似对。

    submissions: [{'student_id', 'username', 'text'}, ...]
    与 compare_submissions 同形，便于复用 UI。
    """
    enriched = []
    for s in submissions:
        text = s.get('text') or ''
        if len(_TEXT_NORMALIZE_RE.sub('', text)) < min_chars:
            continue
        enriched.append({
            'student_id': s['student_id'],
            'username': s['username'],
            'shingles': _char_shingles(text, k),
            'chars': len(_TEXT_NORMALIZE_RE.sub('', text)),
        })

    pairs = []
    n = len(enriched)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = enriched[i], enriched[j]
            union = len(a['shingles'] | b['shingles'])
            if not union:
                continue
            sim = len(a['shingles'] & b['shingles']) / union
            if sim >= threshold:
                pairs.append({
                    'a': {'student_id': a['student_id'], 'username': a['username']},
                    'b': {'student_id': b['student_id'], 'username': b['username']},
                    'similarity': round(sim, 4),
                    'tokens': min(a['chars'], b['chars']),
                })
    pairs.sort(key=lambda p: p['similarity'], reverse=True)
    return pairs
