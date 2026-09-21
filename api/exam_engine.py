# -*- coding: utf-8 -*-
"""考试考务升级共享引擎（v4.3）：
客观题评分规则 / 逐人随机卷与选项乱序 / 多次作答成绩策略 / 掌握度联动 / Socket 通报

被 execution_routes、exam_routes、result_routes、app.py(自动收卷) 与 ai_service.services(判分) 共用，
判分规则只在 `check_objective` 一处实现，避免多端口径漂移。
"""
import json
import random
import re

from database import db
from database.models import (
    Exam, ExamQuestion, ExamSession, Answer, Question, Result, QuestionTypeEnum,
)
from utils.logger import logger

LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

# 判分：选项字母前缀（"A. xxx" / "A、xxx" / "A) xxx" 等）
_OPT_PREFIX = re.compile(r'^\s*[A-Za-z]\s*[\.、:：\)]\s*')


def _as_list(value):
    """options 兼容 JSON 字符串与原生 list 两种存量形态"""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else None
        except (ValueError, TypeError):
            return None
    return None


def check_objective(q_type, student_ans, correct_ans, rule='all_or_nothing'):
    """客观题比对。返回 (is_exact_correct, ratio 0..1)。
    多选题 rule=partial 时：所选为标准答案非空子集 → 按比例给分（漏选得分），含错选 → 0。
    """
    s = (student_ans or '').strip()
    c = (correct_ans or '').strip()
    if q_type == 'multiple_choice':
        s_letters = sorted(set(re.sub(r'[^A-Za-z]', '', s).upper()))
        c_letters = sorted(set(re.sub(r'[^A-Za-z]', '', c).upper()))
        if not c_letters:
            return False, 0.0
        if s_letters == c_letters and s_letters:
            return True, 1.0
        if rule == 'partial' and s_letters and set(s_letters) <= set(c_letters):
            return False, len(s_letters) / len(c_letters)
        return False, 0.0
    if q_type == 'fill_blank':
        ok = s.lower() == c.lower()
        return ok, 1.0 if ok else 0.0
    # single_choice / true_false / 其余客观题
    ok = s.upper() == c.upper()
    return ok, 1.0 if ok else 0.0


# ── 逐人随机卷 / 选项乱序 ──────────────────────────────────────────

def build_session_paper(exam):
    """开考时构建本次会话的试卷：返回 (question_ids, option_map)。
    paper_mode=random 从全卷抽 random_count 题；shuffle_options 时为选择题生成乱序映射。
    option_map: {str(qid): [perm]}，perm[i] = 显示第 i 项对应的原始索引。
    """
    eqs = sorted(exam.exam_questions, key=lambda x: x.order)
    ids = [eq.question_id for eq in eqs]
    if exam.paper_mode == 'random' and exam.random_count and 0 < exam.random_count < len(ids):
        ids = random.sample(ids, exam.random_count)
    option_map = {}
    if exam.shuffle_options:
        qmap = {q.id: q for q in Question.query.filter(Question.id.in_(ids)).all()} if ids else {}
        for qid in ids:
            q = qmap.get(qid)
            if not q or q.type not in ('single_choice', 'multiple_choice'):
                continue
            opts = _as_list(q.options)
            if not opts or len(opts) < 2:
                continue
            perm = list(range(len(opts)))
            random.shuffle(perm)
            if perm != list(range(len(opts))):
                option_map[str(qid)] = perm
    return ids, option_map


def display_options(question, perm):
    """按乱序映射生成展示选项：剥离原字母前缀、重新编号（A/B/C...），
    学生所见字母即"位置"，判分时经 map_letters 反映射回原始字母。
    """
    opts = _as_list(question.options)
    if not opts:
        return question.options
    out = []
    for i, src in enumerate(perm):
        if src >= len(opts):
            out.append(f'{LETTERS[i]}. ')
            continue
        text = str(opts[src])
        text = _OPT_PREFIX.sub('', text, count=1)
        out.append(f'{LETTERS[i]}. {text}')
    return out


def map_letters(letters, perm, reverse=False):
    """答案字母在「显示位置 ↔ 原始索引」间换算。letters 如 'AB'/'A,B'。perm 为空则原样返回。"""
    if not perm or not letters:
        return letters
    chosen = re.findall(r'[A-Za-z]', letters.upper())
    out = []
    for ch in chosen:
        idx = LETTERS.find(ch)
        if idx < 0:
            continue
        orig = perm[idx] if not reverse else (perm.index(idx) if idx in perm else idx)
        if orig < len(LETTERS):
            out.append(LETTERS[orig])
    return ''.join(out)


def session_question_ids(sess, exam):
    """本次会话的有效题单：random 模式取抽题结果（∩当前试卷，防组卷变更），否则全卷"""
    assigned = sess.assigned_question_ids
    if isinstance(assigned, str):
        try:
            assigned = json.loads(assigned)
        except (ValueError, TypeError):
            assigned = None
    eqs = sorted(exam.exam_questions, key=lambda x: x.order)
    all_ids = [eq.question_id for eq in eqs]
    if assigned:
        kept = [qid for qid in assigned if qid in all_ids]
        if kept:
            return kept
    return all_ids


def session_option_map(sess):
    om = sess.option_map
    if isinstance(om, str):
        try:
            om = json.loads(om)
        except (ValueError, TypeError):
            om = None
    return om if isinstance(om, dict) else {}


def canonical_answer(sess, question_id, display_letters):
    """把学生提交的（乱序显示）字母答案还原为原始题面字母；perm 中第 i 位=原始索引，
    显示字母索引 i → 原始 perm[i]，即 map_letters(letters, perm, reverse=False)"""
    perm = session_option_map(sess).get(str(question_id))
    if not perm:
        return display_letters
    return map_letters(display_letters or '', perm, reverse=False)


def display_answer(sess, question_id, orig_letters):
    """原始字母答案 → 显示字母（供 take 回显草稿）"""
    perm = session_option_map(sess).get(str(question_id))
    if not perm:
        return orig_letters
    return map_letters(orig_letters or '', perm, reverse=True)


# ── 多次作答成绩策略 ───────────────────────────────────────────────

def apply_exam_result(sess, earned, total):
    """按 exam.score_strategy 幂等落 Result（一学生一行，best/last）。
    调用方负责 commit。返回 (result, created, changed)。
    best：新分更高才覆盖；last：总是覆盖为最近一次。
    """
    exam = db.session.get(Exam, sess.exam_id)
    result = Result.query.filter_by(exam_id=sess.exam_id, student_id=sess.student_id).first()
    if not result:
        result = Result(exam_id=sess.exam_id, student_id=sess.student_id,
                        score=earned, total_score=total,
                        submitted_at=sess.end_time or _utcnow())
        result.session_id = sess.id
        db.session.add(result)
        return result, True, True
    strategy = (exam.score_strategy if exam else 'last') or 'last'
    better = (earned or 0) > (result.score or 0)
    changed = False
    if strategy == 'best':
        if better:
            changed = True
    else:  # last：以最近一次为准
        changed = True
    if changed:
        result.score = earned
        result.total_score = total
        result.session_id = sess.id
        result.submitted_at = sess.end_time
    return result, False, changed


def _utcnow():
    from utils.timeutil import utcnow
    return utcnow()


# ── 知识点掌握度联动（v4.3 P2）─────────────────────────────────────

def update_mastery_from_exam(student_id, session_id):
    """按本次作答逐知识点更新掌握度（EWMA）。非关键路径，调用方 try/except。
    客观题 ratio 取对错，主观题取 effective_score/满分。
    """
    from api.learning_engine import kp_ids_of_question, update_mastery
    answers = Answer.query.filter_by(session_id=session_id).all()
    if not answers:
        return 0
    bucket = {}
    sess = db.session.get(ExamSession, session_id)
    eq_cache = {}
    for a in answers:
        q = db.session.get(Question, a.question_id)
        if not q:
            continue
        kps = kp_ids_of_question(q.id)
        if not kps:
            continue
        if a.question_id not in eq_cache:
            eq = ExamQuestion.query.filter_by(exam_id=sess.exam_id, question_id=q.id).first() if sess else None
            eq_cache[a.question_id] = (eq.score if eq else 0) or 0
        full = eq_cache[a.question_id]
        if QuestionTypeEnum.is_subjective(q.type):
            ratio = min(1.0, (a.effective_score or 0) / full) if full else 0.0
        else:
            ratio = 1.0 if a.is_correct else 0.0
        for kp in kps:
            bucket.setdefault(kp, []).append(ratio)
    touched = 0
    for kp, ratios in bucket.items():
        update_mastery(student_id, [kp], sum(ratios) / len(ratios))
        touched += 1
    return touched


# ── Socket 通报（复用竞赛个人房间基建）─────────────────────────────

def notify_teacher(exam, event_payload):
    """考试事件实时通报教师创建者（交卷/强制交卷/开考监控刷新）"""
    try:
        from competition.realtime import notify_user
        if exam and exam.creator_id:
            notify_user(exam.creator_id, 'exam_alert', event_payload)
    except Exception:
        logger.debug('exam_alert 推送失败（非关键）', exc_info=True)


def notify_student_result_published(student_id, exam_id, result_id):
    try:
        from competition.realtime import notify_user
        notify_user(student_id, 'result_published',
                    {'exam_id': exam_id, 'result_id': result_id})
    except Exception:
        logger.debug('result_published 推送失败（非关键）', exc_info=True)
