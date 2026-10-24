# -*- coding: utf-8 -*-
"""作业练习 API（v5.0）。

角色分流：教师=创建者资源校验（require_teacher + teacher_id 比对，与考试口径一致）；
学生=须在该作业发布名单。序列化红线：学生视角不下发题面答案/解析/OJ 用例，
未批改不总分（HomeworkSubmission.to_dict 内建）。
挂载：app.py 统一 url_prefix='/api'，本蓝图路径以 /homeworks 起。
"""
import os
import csv
import io
import random
import shutil
import uuid

from flask import Blueprint, Response, jsonify, request, send_from_directory

from database import db
from database.models import Question, User
from utils.logger import logger
from utils.permissions import require_teacher, require_login
from utils.security import limiter
from utils.timeutil import utcnow, iso_local, parse_dt
from utils.notify import create_notification
from utils.uploads import UPLOAD_DIR as _UPLOAD_DIR, save_upload as _save_upload
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkAiReview, HomeworkComment, HomeworkPeerReview,
    HomeworkGroup, HomeworkGroupMember,
    HomeworkTemplate, HomeworkSeries, HomeworkSeriesStatusEnum,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
    PeerReviewStatusEnum, PeerReviewAuditEnum, HomeworkRubric,
    HomeworkProctorEvent, ProctorEventTypeEnum,
    ShowcaseStatusEnum,
    HomeworkAnnotation, AnnotationTypeEnum,
)
from homework.services import (
    finalize_submission, recompute_total, notify_homework_students, ai_suggest_grading,
    apply_late_penalty, blind_active, blind_label, ensure_submission_paper,
    build_class_review, build_submission_review, upsert_ai_review,
    build_class_analytics,
    distribute_peer_reviews, peer_review_summary, peer_review_received,
    compute_peer_final_score, _clean_dimension_scores, peer_review_dimensions,
    audit_peer_review, complete_peer_review_daily_task,
    homework_plagiarism_check, get_student_group, get_group_submission,
    sync_roster_from_groups,
    generate_homework_from_template, complete_homework_daily_task,
    preview_template_questions,
)

homework_bp = Blueprint('homework', __name__)

_TYPE_LABELS = {HomeworkTypeEnum.QUESTION_SET: '题集式', HomeworkTypeEnum.OPEN: '开放式'}


# ═══════════════════════ 通用助手 ═══════════════════════

def _get_own_homework(user, hw_id):
    hw = db.session.get(Homework, hw_id)
    if not hw:
        return None, (jsonify({'message': '作业不存在'}), 404)
    if hw.teacher_id != user.id:
        return None, (jsonify({'message': '无权操作他人作业'}), 403)
    return hw, None


def _in_roster(hw, user_id):
    """是否在发布名单：小组作业自动把小组成员同步进名单，故统一查 HomeworkStudent。"""
    return HomeworkStudent.query.filter_by(homework_id=hw.id, student_id=user_id).first()


def _my_submission(hw, user_id):
    """取本人（或本人小组）的提交。小组作业每组一份，组员共享。"""
    if hw.is_group:
        group = get_student_group(hw, user_id)
        if group:
            return get_group_submission(hw, group.id)
        return None
    return HomeworkSubmission.query.filter_by(homework_id=hw.id, student_id=user_id).first()


def _notify_graded(hw, sub, msg):
    """批改完成通知：个人作业通知本人；小组作业通知全组成员。"""
    if sub.group_id and sub.group:
        for m in sub.group.members:
            create_notification(m.student_id, '作业已批改', msg,
                                type='success', related_type='homework',
                                related_id=hw.id, commit=False)
    else:
        create_notification(sub.student_id, '作业已批改', msg,
                            type='success', related_type='homework', related_id=hw.id)


def _notify_returned(hw, sub, msg):
    """v5.17 退回订正通知：个人作业通知本人；小组作业通知全组成员（与批改口径一致）。"""
    if sub.group_id and sub.group:
        for m in sub.group.members:
            create_notification(m.student_id, '作业被退回订正', msg,
                                type='warning', related_type='homework',
                                related_id=hw.id, commit=False)
    else:
        create_notification(sub.student_id, '作业被退回订正', msg,
                            type='warning', related_type='homework', related_id=hw.id)


def _question_payload(hq, for_teacher):
    """题集式单题序列化：学生剥离 answer/analysis/test_cases（防答案泄露）。"""
    q = hq.question
    d = {'question_id': q.id, 'content': q.content, 'type': q.type,
         'options': q.options, 'score': hq.score, 'order': hq.order,
         'material': q.material}
    if for_teacher:
        d.update({'answer': q.answer, 'analysis': q.analysis,
                  'test_cases': q.test_cases, 'difficulty': q.difficulty})
    return d


def _take_question_payload(hq, perm):
    """v5.11 乱序作答专用：学生视角题目，若有选项乱序映射则重排选项（仅显示，不泄露答案）。"""
    d = _question_payload(hq, False)
    if perm:
        from api.exam_engine import display_options
        d['options'] = display_options(hq.question, perm)
    return d


def _canonical_choice_answer(hq_map, option_map, qid, text):
    """v5.11 选项乱序：把学生提交的显示位字母反归为原始位字母后存答（仅选择题且有映射时）。"""
    perm = option_map.get(str(qid)) if option_map else None
    if not perm:
        return text
    hq = hq_map.get(qid)
    if not hq or not hq.question or hq.question.type not in ('single_choice', 'multiple_choice'):
        return text
    from api.exam_engine import map_letters
    return map_letters(str(text or ''), perm, reverse=False)


def _parse_deadline(value):
    if not value:
        return None
    try:
        return parse_dt(value)
    except Exception:
        return False


def _apply_common_fields(hw, data):
    """草稿/已发布共用可改字段；返回错误消息串或 None。"""
    if 'title' in data:
        title = str(data.get('title') or '').strip()
        if not title:
            return '标题不能为空'
        hw.title = title[:200]
    if 'description' in data:
        hw.description = str(data.get('description') or '')[:20000]
    for flag in ('allow_late', 'allow_resubmit', 'allow_revision'):
        if flag in data:
            setattr(hw, flag, bool(data[flag]))
    if 'remind_before' in data:
        try:
            hw.remind_before = min(max(int(data['remind_before']), 0), 7 * 24 * 60)
        except (TypeError, ValueError):
            return 'remind_before 须为 0~10080 的分钟数'
    if 'pass_score' in data:
        ps = data.get('pass_score')
        if ps is None or ps == '':
            hw.pass_score = None
        else:
            try:
                ps = float(ps)
            except (TypeError, ValueError):
                return 'pass_score 须为数字或留空'
            if ps < 0:
                return 'pass_score 不能为负'
            hw.pass_score = round(ps, 2)
    if 'is_group' in data:
        hw.is_group = bool(data['is_group'])
    # v5.11 迟交扣分 / 匿名批改 / 乱序开关 / 分级提醒
    if 'late_penalty_pct' in data:
        try:
            hw.late_penalty_pct = min(max(float(data['late_penalty_pct']), 0.0), 100.0)
        except (TypeError, ValueError):
            return 'late_penalty_pct 须为 0~100 的数字'
    for flag in ('blind_grading', 'shuffle_questions', 'shuffle_options'):
        if flag in data:
            setattr(hw, flag, bool(data[flag]))
    if 'remind_levels' in data:
        levels = data.get('remind_levels')
        if levels in (None, ''):
            hw.remind_levels_json = None
        elif not isinstance(levels, list):
            return 'remind_levels 须为列表或留空'
        else:
            cleaned = []
            for lv in levels:
                if not isinstance(lv, dict):
                    return 'remind_levels 元素须为 {minutes, label}'
                try:
                    m = min(max(int(lv.get('minutes')), 0), 7 * 24 * 60)
                except (TypeError, ValueError):
                    return 'remind_levels.minutes 须为 0~10080 分钟'
                cleaned.append({'minutes': m, 'label': str(lv.get('label') or '')[:20]})
            hw.remind_levels_json = cleaned
    # v5.14 多种评分制：仅显示层，不改分数/账本口径
    if 'grade_mode' in data:
        gm = str(data.get('grade_mode') or 'numeric').strip().lower()
        if gm not in ('numeric', 'level', 'comment'):
            return 'grade_mode 须为 numeric/level/comment'
        hw.grade_mode = gm
    if 'grade_scale' in data:
        sc = data.get('grade_scale')
        if sc in (None, ''):
            hw.grade_scale_json = None
        elif not isinstance(sc, list):
            return 'grade_scale 须为列表或留空'
        else:
            cleaned = []
            for it in sc:
                if not isinstance(it, dict):
                    return 'grade_scale 元素须为 {label, min}'
                try:
                    mv = float(it.get('min'))
                except (TypeError, ValueError):
                    return 'grade_scale.min 须为数字（得分率 0~1）'
                cleaned.append({'label': str(it.get('label') or '')[:12],
                                'min': round(mv, 4)})
            hw.grade_scale_json = cleaned
    # v5.15 评分量规：关联本教师的量规（可置空解除）；不改判分口径
    if 'rubric_id' in data:
        rid = data.get('rubric_id')
        if rid in (None, ''):
            hw.rubric_id = None
        else:
            try:
                rid = int(rid)
            except (TypeError, ValueError):
                return 'rubric_id 须为整数或留空'
            rb = db.session.get(HomeworkRubric, rid)
            if not rb or rb.teacher_id != hw.teacher_id:
                return '量规不存在或不属于你'
            hw.rubric_id = rid
    # v5.16 作答防作弊监测开关（仅记录事件、不强制交卷）
    if 'enable_monitor' in data:
        hw.enable_monitor = bool(data['enable_monitor'])
    return None


def _clean_rubric_dimensions(raw):
    """校验/清洗量规维度；返回 (cleaned_list, err_str)。

    元素：{label:str, max_score:float>=0, levels:[{score:float, desc:str}]}；levels 可选。
    """
    if not isinstance(raw, list) or not raw:
        return None, 'dimensions 须为非空列表'
    cleaned = []
    for d in raw:
        if not isinstance(d, dict):
            return None, '维度元素须为对象 {label, max_score, levels?}'
        label = str(d.get('label') or '').strip()[:60]
        if not label:
            return None, '维度 label 不能为空'
        try:
            mx = float(d.get('max_score'))
        except (TypeError, ValueError):
            return None, f'维度「{label}」max_score 须为数字'
        if mx < 0:
            return None, f'维度「{label}」max_score 不能为负'
        levels = []
        lv = d.get('levels')
        if isinstance(lv, list):
            for x in lv:
                if not isinstance(x, dict):
                    continue
                try:
                    sv = float(x.get('score'))
                except (TypeError, ValueError):
                    return None, f'维度「{label}」描述语 score 须为数字'
                levels.append({'score': round(sv, 2), 'desc': str(x.get('desc') or '')[:200]})
        cleaned.append({'label': label, 'max_score': round(mx, 2), 'levels': levels})
    return cleaned, None


def _normalize_rubric_scores(rubric, raw):
    """按量规维度将提交的逐维度分归一为 [{index,label,score}]；返回 (list, err_str)。

    raw 可为 {index:score} 字典或 [{index,label,score}] 列表；score 限 [0, dim.max_score]。
    仅用于快照与“合计建议分”，不参与 total_score 推导。
    """
    dims = rubric.dimensions()
    by_index = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                by_index[int(k)] = v
            except (TypeError, ValueError):
                return None, 'rubric_scores 键须为维度索引'
    elif isinstance(raw, list):
        for i, it in enumerate(raw):
            if isinstance(it, dict):
                idx = it.get('index', i)
                try:
                    by_index[int(idx)] = it.get('score')
                except (TypeError, ValueError):
                    return None, 'rubric_scores.index 须为整数'
    else:
        return None, 'rubric_scores 须为对象或列表'
    out = []
    for i, d in enumerate(dims):
        if i not in by_index:
            continue
        sv = by_index[i]
        if sv is None or sv == '':
            continue
        try:
            sv = float(sv)
        except (TypeError, ValueError):
            return None, f'维度「{d.get("label")}」得分须为数字'
        mx = float(d.get('max_score') or 0)
        if sv < 0 or sv > mx:
            return None, f'维度「{d.get("label")}」得分须在 0~{mx} 之间'
        out.append({'index': i, 'label': d.get('label'), 'score': round(sv, 2)})
    return out, None


def _apply_groups(hw, groups):
    """整体替换小组名单（仅小组作业）；返回错误串或 None。

    groups: [{'name': str, 'student_ids': [int]}]
    同一名学生只能在一个小组内；自动同步到 HomeworkStudent。
    """
    if hw.status != HomeworkStatusEnum.DRAFT:
        return '已发布作业不可再调整小组'
    if not isinstance(groups, list) or not groups:
        return '小组作业至少需要 1 个小组'
    # 收集所有学生 id
    all_ids = []
    for g in groups:
        name = str(g.get('name') or '').strip()[:100] or '未命名小组'
        sids = g.get('student_ids') or []
        for sid in sids:
            try:
                all_ids.append(int(sid))
            except (TypeError, ValueError):
                return 'student_ids 须为整数列表'
    if not all_ids:
        return '每个小组至少需要 1 名学生'
    if len(all_ids) != len(set(all_ids)):
        return '同一名学生不能重复加入多个小组'
    valid = {u.id for u in User.query.filter(
        User.id.in_(all_ids), User.role == 'student').all()}
    missing = [i for i in all_ids if i not in valid]
    if missing:
        return f'学生不存在：{missing}'

    # 重建小组
    hw.groups.clear()
    db.session.flush()
    for g in groups:
        name = str(g.get('name') or '').strip()[:100] or '未命名小组'
        grp = HomeworkGroup(name=name)
        for sid in g.get('student_ids') or []:
            grp.members.append(HomeworkGroupMember(student_id=int(sid)))
        hw.groups.append(grp)
    db.session.flush()
    sync_roster_from_groups(hw)
    return None


def _apply_roster(hw, student_ids):
    """整体替换发布名单；返回错误串或 None。"""
    ids = []
    for x in student_ids or []:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            return 'student_ids 须为整数列表'
    if not ids:
        return '发布名单不能为空'
    valid = {u.id for u in User.query.filter(
        User.id.in_(ids), User.role == 'student').all()}
    missing = [i for i in ids if i not in valid]
    if missing:
        return f'学生不存在：{missing}'
    keep = set(ids)
    for hs in list(hw.hw_students):
        if hs.student_id not in keep:
            db.session.delete(hs)
            keep_existing = True
    existing = {hs.student_id for hs in hw.hw_students}
    for sid in ids:
        if sid not in existing:
            db.session.add(HomeworkStudent(homework_id=hw.id, student_id=sid))
    return None


# ═══════════════════════ 列表 / 详情 ═══════════════════════

@homework_bp.route('/homeworks', methods=['GET'])
def api_list():
    user, err = require_login()
    if err:
        return err
    if user.is_teacher():
        q = Homework.query.filter_by(teacher_id=user.id)
        status = request.args.get('status')
        if status in HomeworkStatusEnum.ALL:
            q = q.filter(Homework.status == status)
        rows = q.order_by(Homework.id.desc()).all()
        counts = {}
        if rows:
            from sqlalchemy import func
            subq = (db.session.query(HomeworkSubmission.homework_id,
                                     func.count(HomeworkSubmission.id))
                    .filter(HomeworkSubmission.homework_id.in_([h.id for h in rows]),
                            HomeworkSubmission.status != SubmissionStatusEnum.DRAFT)
                    .group_by(HomeworkSubmission.homework_id).all())
            counts = {hid: n for hid, n in subq}
        items = [h.to_dict(for_teacher=True,
                           stats={'submitted_count': counts.get(h.id, 0),
                                  'student_count': len(h.hw_students)}) for h in rows]
        return jsonify({'items': items, 'is_teacher': True})
    # 学生：名单内 + 非草稿
    hw_ids = [hs.homework_id for hs in HomeworkStudent.query.filter_by(student_id=user.id).all()]
    rows = (Homework.query.filter(Homework.id.in_(hw_ids),
                                  Homework.status != HomeworkStatusEnum.DRAFT)
            .order_by(Homework.deadline.asc()).all()) if hw_ids else []
    mine = {s.homework_id: s for s in HomeworkSubmission.query.filter(
        HomeworkSubmission.homework_id.in_([h.id for h in rows]),
        HomeworkSubmission.student_id == user.id).all()} if rows else {}
    items = []
    for h in rows:
        d = h.to_dict()
        sub = mine.get(h.id)
        d['my_submission'] = sub.to_dict() if sub else None
        items.append(d)
    return jsonify({'items': items, 'is_teacher': False})


@homework_bp.route('/homeworks/<int:hw_id>', methods=['GET'])
def api_detail(hw_id):
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw:
        return jsonify({'message': '作业不存在'}), 404
    if hw.teacher_id == user.id and user.is_teacher():
        d = hw.to_dict(for_teacher=True,
                       stats={'submitted_count': sum(1 for s in hw.submissions
                                                     if s.status != SubmissionStatusEnum.DRAFT),
                              'student_count': len(hw.hw_students)})
        d['questions'] = [_question_payload(hq, True) for hq in
                          sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))]
        d['student_ids'] = [hs.student_id for hs in hw.hw_students]
        d['groups'] = [g.to_dict() for g in hw.groups]
        return jsonify(d)
    if hw.status == HomeworkStatusEnum.DRAFT or not _in_roster(hw, user.id):
        return jsonify({'message': '作业不存在或未对你开放'}), 404
    d = hw.to_dict()
    if hw.hw_type == HomeworkTypeEnum.QUESTION_SET:
        d['questions'] = [_question_payload(hq, False) for hq in
                          sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))]
    sub = _my_submission(hw, user.id)
    d['my_submission'] = sub.to_dict() if sub else None
    if hw.is_group:
        grp = get_student_group(hw, user.id)
        d['my_group'] = grp.to_dict() if grp else None
    return jsonify(d)


# ═══════════════════════ 教师：创建 / 编辑 / 删除 ═══════════════════════

@homework_bp.route('/homeworks', methods=['POST'])
def api_create():
    user, err = require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '标题不能为空'}), 400
    hw_type = data.get('hw_type') or HomeworkTypeEnum.QUESTION_SET
    if hw_type not in HomeworkTypeEnum.ALL:
        return jsonify({'message': 'hw_type 须为 question_set/open'}), 400
    deadline = _parse_deadline(data.get('deadline'))
    if deadline is False:
        return jsonify({'message': '时间格式错误'}), 400
    # deadline 为 None 表示不设截止时间（可选，永不过期）

    hw = Homework(title=title[:200], description=str(data.get('description') or ''),
                  hw_type=hw_type, teacher_id=user.id, deadline=deadline, status=HomeworkStatusEnum.DRAFT)
    msg = _apply_common_fields(hw, data)
    if msg:
        return jsonify({'message': msg}), 400
    db.session.add(hw)
    db.session.flush()

    if hw_type == HomeworkTypeEnum.QUESTION_SET:
        msg = _apply_questions(hw, data.get('questions'))
        if msg:
            db.session.rollback()
            return jsonify({'message': msg}), 400
    if data.get('student_ids') is not None:
        msg = _apply_roster(hw, data.get('student_ids'))
        if msg:
            db.session.rollback()
            return jsonify({'message': msg}), 400
    if hw.is_group and data.get('groups') is not None:
        msg = _apply_groups(hw, data.get('groups'))
        if msg:
            db.session.rollback()
            return jsonify({'message': msg}), 400
    db.session.commit()
    return jsonify({'message': '作业草稿已创建', 'homework': hw.to_dict(for_teacher=True)}), 201


def _apply_questions(hw, questions):
    """整体替换题目清单（仅草稿可用）；返回错误串或 None。"""
    if not isinstance(questions, list) or not questions:
        return '题集式作业至少选择 1 道题'
    if len(questions) > 100:
        return '题目数量上限 100'
    qids = []
    for item in questions:
        try:
            qid = int(item.get('question_id'))
        except (TypeError, ValueError, AttributeError):
            return 'question_id 无效'
        qids.append(qid)
    qmap = {q.id: q for q in Question.query.filter(Question.id.in_(qids)).all()}
    missing = [x for x in qids if x not in qmap]
    if missing:
        return f'题目不存在：{missing}'
    hw.hw_questions.clear()
    db.session.flush()   # 先落删除，避免同复合主键先插后删冲突
    for i, item in enumerate(questions):
        try:
            score = float(item.get('score', 1.0))
        except (TypeError, ValueError):
            return 'score 须为数字'
        if not (0 < score <= 100):
            return '每题分值须在 (0, 100] 区间'
        db.session.add(HomeworkQuestion(
            homework_id=hw.id, question_id=int(item.get('question_id')),
            score=score, order=i))
    return None


@homework_bp.route('/homeworks/<int:hw_id>', methods=['PUT'])
def api_update(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    msg = _apply_common_fields(hw, data)
    if msg:
        return jsonify({'message': msg}), 400

    if 'deadline' in data:
        deadline = _parse_deadline(data.get('deadline'))
        if deadline is False:
            return jsonify({'message': '时间格式错误'}), 400
        # deadline 为 None：取消截止时间（改为不限期）
        if hw.deadline != deadline:
            hw.deadline = deadline
            if deadline and not hw.is_expired:
                hw.reminded_at = None   # 改期至未来：允许重新提醒
    if hw.status == HomeworkStatusEnum.DRAFT:
        # 草稿：全量可改（题目清单仅限题集式）
        if 'hw_type' in data and data['hw_type'] != hw.hw_type:
            if data['hw_type'] not in HomeworkTypeEnum.ALL:
                return jsonify({'message': 'hw_type 须为 question_set/open'}), 400
            hw.hw_type = data['hw_type']
        if hw.hw_type == HomeworkTypeEnum.QUESTION_SET and data.get('questions') is not None:
            msg = _apply_questions(hw, data['questions'])
            if msg:
                return jsonify({'message': msg}), 400
        if data.get('student_ids') is not None:
            msg = _apply_roster(hw, data.get('student_ids'))
            if msg:
                return jsonify({'message': msg}), 400
        if hw.is_group and data.get('groups') is not None:
            msg = _apply_groups(hw, data.get('groups'))
            if msg:
                return jsonify({'message': msg}), 400
        if not hw.is_group:
            # 切回非小组：清空小组与提交的 group_id 关联
            for g in list(hw.groups):
                db.session.delete(g)
    else:
        # 已发布/已关闭：题目清单锁定，仅名单可调
        if data.get('student_ids') is not None:
            msg = _apply_roster(hw, data['student_ids'])
            if msg:
                return jsonify({'message': msg}), 400
            # 名单收缩：已退出学生的草稿提交一并清理（已提交的保留供留档）
            in_roster = {hs.student_id for hs in hw.hw_students}
            for sub in list(hw.submissions):
                if sub.student_id not in in_roster and sub.status == SubmissionStatusEnum.DRAFT:
                    db.session.delete(sub)
    db.session.commit()
    return jsonify({'message': '已保存', 'homework': hw.to_dict(for_teacher=True)})


@homework_bp.route('/homeworks/<int:hw_id>', methods=['DELETE'])
def api_delete(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    if hw.status != HomeworkStatusEnum.DRAFT:
        return jsonify({'message': '仅草稿可删除；已发布作业请用关闭/撤回'}), 400
    db.session.delete(hw)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ═══════════════════════ 发布 / 关闭 ═══════════════════════

@homework_bp.route('/homeworks/<int:hw_id>/publish', methods=['POST'])
def api_publish(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    if hw.status != HomeworkStatusEnum.DRAFT:
        return jsonify({'message': '仅草稿可发布'}), 400
    if hw.hw_type == HomeworkTypeEnum.QUESTION_SET and not hw.hw_questions:
        return jsonify({'message': '题集式作业须先选题'}), 400
    if hw.hw_type == HomeworkTypeEnum.OPEN and not (hw.description or '').strip():
        return jsonify({'message': '开放式作业须填写作业说明'}), 400
    if hw.is_expired:
        return jsonify({'message': '截止时间已过，请先修改截止时间'}), 400
    if not hw.hw_students:
        return jsonify({'message': '发布名单为空'}), 400
    if hw.is_group and not hw.groups:
        return jsonify({'message': '小组作业须先创建小组'}), 400

    hw.status = HomeworkStatusEnum.PUBLISHED
    hw.published_at = utcnow()
    hw.reminded_at = None
    title = '新作业发布'
    due_txt = f'截止 {iso_local(hw.deadline)}' if hw.deadline else '无截止时间（随到随做）'
    content = f'老师发布了作业《{hw.title}》，{due_txt}，请及时完成。'
    n = notify_homework_students(hw, title, content)
    db.session.commit()
    # v5.8：发布时为名单学生创建当日 DailyTask（非关键路径）
    try:
        from homework.services import _create_daily_tasks_for_homework
        _create_daily_tasks_for_homework(hw)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.debug('[homework] 发布时创建每日任务失败（非关键）', exc_info=True)
    return jsonify({'message': f'已发布并通知 {n} 名学生',
                    'homework': hw.to_dict(for_teacher=True)})


@homework_bp.route('/homeworks/<int:hw_id>/close', methods=['POST'])
def api_close(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    if hw.status != HomeworkStatusEnum.PUBLISHED:
        return jsonify({'message': '仅已发布作业可关闭'}), 400
    hw.status = HomeworkStatusEnum.CLOSED
    notify_homework_students(hw, '作业已关闭', f'作业《{hw.title}》已被老师关闭，不再接收提交。')
    db.session.commit()
    return jsonify({'message': '已关闭', 'homework': hw.to_dict(for_teacher=True)})


# ═══════════════════════ 教师：催交 / 统计 / 导出 / 复制 / 随机抽题 ═══════════════════════

def _compute_stats(hw):
    """作业成绩聚合：提交率/批改进度/分数分布/及格率/优秀率（仅计已批改）。"""
    subs = [s for s in hw.submissions if s.status != SubmissionStatusEnum.DRAFT]
    graded = [s for s in subs if s.status == SubmissionStatusEnum.GRADED]
    scores = [s.total_score for s in graded if s.total_score is not None]
    full = hw.max_score()
    if full is None:
        fulls = [s.max_score for s in graded if s.max_score]
        full = round(sum(fulls) / len(fulls), 2) if fulls else None
    student_count = len(hw.hw_students)
    submitted = len(subs)
    st = {'student_count': student_count,
          'submitted_count': submitted,
          'submitted_rate': round(submitted / student_count * 100, 1) if student_count else 0.0,
          'graded_count': len(graded),
          'pending_count': submitted - len(graded),
          'full_score': full,
          'avg_score': round(sum(scores) / len(scores), 2) if scores else None,
          'max_score_value': round(max(scores), 2) if scores else None,
          'min_score_value': round(min(scores), 2) if scores else None}
    st['pass_rate'] = (round(sum(1 for s in scores if s >= hw.pass_score) / len(scores) * 100, 1)
                       if hw.pass_score is not None and scores else None)
    st['excellent_rate'] = (round(sum(1 for s in scores if s >= full * 0.9) / len(scores) * 100, 1)
                            if full and scores else None)
    return st


@homework_bp.route('/homeworks/<int:hw_id>/stats', methods=['GET'])
def api_stats(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    return jsonify({'homework': hw.to_dict(for_teacher=True), 'stats': _compute_stats(hw)})


@homework_bp.route('/homeworks/analytics', methods=['GET'])
@limiter.limit('60/minute')
def api_class_analytics():
    """v5.18 跨作业学情分析看板（教师）：完成率/得分趋势/知识点薄弱热力/每题得分率+区分度。

    只读聚合，不改判分与账本口径；可选 ?homework_id= 限定单份作业。"""
    user, err = require_teacher()
    if err:
        return err
    q = Homework.query.filter(Homework.teacher_id == user.id,
                              Homework.status != HomeworkStatusEnum.DRAFT)
    hw_filter = request.args.get('homework_id', type=int)
    if hw_filter:
        q = q.filter(Homework.id == hw_filter)
    hws = q.order_by(Homework.id.asc()).all()
    return jsonify(build_class_analytics(hws))


# ═══════════════════════ v5.3 AI 讲评：班级共性分析 ═══════════════════════

def _get_class_review(hw):
    return HomeworkAiReview.query.filter_by(homework_id=hw.id, scope_key='class').first()


@homework_bp.route('/homeworks/<int:hw_id>/ai_review', methods=['GET'])
def api_class_review_get(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    rec = _get_class_review(hw)
    return jsonify({'exists': bool(rec), 'review': rec.to_dict() if rec else None})


@homework_bp.route('/homeworks/<int:hw_id>/ai_review', methods=['POST'])
@limiter.limit('6/minute')
def api_class_review_generate(hw_id):
    """生成/刷新班级共性分析（统计始终可用，AI 失败降级规则讲评）。"""
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    result = build_class_review(hw)
    rec = upsert_ai_review(hw, 'class', result, user.id)
    message = ('AI 服务暂不可用，已生成规则版讲评（统计数据完整）'
               if rec.degraded else '班级 AI 讲评已生成')
    if not result['stats']['submitted']:
        message = '暂无学生提交，已生成提交情况提醒'
    return jsonify({'message': message, 'degraded': bool(rec.degraded),
                    'review': rec.to_dict()})


@homework_bp.route('/homeworks/<int:hw_id>/ai_review/publish', methods=['POST'])
def api_class_review_publish(hw_id):
    """班级讲评发布/撤回：发布后学生端 result 才可见。"""
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    rec = _get_class_review(hw)
    if not rec:
        return jsonify({'message': '请先生成班级 AI 讲评'}), 404
    data = request.get_json(silent=True) or {}
    published = bool(data.get('published', True))
    rec.published_at = utcnow() if published else None
    db.session.commit()
    return jsonify({'message': '已发布给学生' if published else '已撤回，学生不可见',
                    'review': rec.to_dict()})


@homework_bp.route('/homeworks/<int:hw_id>/urge', methods=['POST'])
@limiter.limit('30/minute')
def api_urge(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    if hw.status != HomeworkStatusEnum.PUBLISHED:
        return jsonify({'message': '仅已发布作业可催交'}), 400
    n = notify_homework_students(hw, '作业催交提醒',
                                 f'老师提醒：作业《{hw.title}》你尚未提交，请尽快完成。',
                                 only_unsubmitted=True)
    db.session.commit()
    if n == 0:
        return jsonify({'message': '全部学生已提交，无需催交', 'urged': 0})
    return jsonify({'message': f'已提醒 {n} 名未交学生', 'urged': n})


@homework_bp.route('/homeworks/<int:hw_id>/export', methods=['GET'])
def api_export(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    subs = [s for s in hw.submissions if s.status != SubmissionStatusEnum.DRAFT]
    subs.sort(key=lambda s: (s.student.username or '') if s.student else '')
    label = {SubmissionStatusEnum.SUBMITTED: '待批改', SubmissionStatusEnum.GRADED: '已批改',
             SubmissionStatusEnum.RETURNED: '待订正'}
    buf = io.StringIO()
    buf.write('\ufeff')   # BOM 让 Excel 正确识别 UTF-8
    w = csv.writer(buf)
    w.writerow(['学生', '状态', '版本', '是否迟交', '提交时间', '得分', '满分', '评语'])
    for s in subs:
        w.writerow([s.student.username if s.student else s.student_id,
                    label.get(s.status, s.status), s.version or 1,
                    '是' if s.is_late else '否',
                    iso_local(s.submitted_at) if s.submitted_at else '',
                    '' if s.total_score is None else s.total_score,
                    '' if s.max_score is None else s.max_score,
                    (s.comment or '').replace('\n', ' ')])
    submitted_ids = {s.student_id for s in subs}
    for hs in hw.hw_students:
        if hs.student_id not in submitted_ids:
            w.writerow([hs.student.username if hs.student else hs.student_id,
                        '未提交', '', '', '', '', '', ''])
    fname = f'homework_{hw.id}_scores.csv'
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{fname}"'})


@homework_bp.route('/homeworks/<int:hw_id>/copy', methods=['POST'])
def api_copy(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    new = Homework(title=(hw.title[:190] + '（副本）'), description=hw.description or '',
                   hw_type=hw.hw_type, teacher_id=user.id, status=HomeworkStatusEnum.DRAFT,
                   deadline=hw.deadline, allow_late=hw.allow_late,
                   allow_resubmit=hw.allow_resubmit, remind_before=hw.remind_before or 0,
                   pass_score=hw.pass_score,
                   late_penalty_pct=hw.late_penalty_pct or 0.0, blind_grading=hw.blind_grading,
                   shuffle_questions=hw.shuffle_questions, shuffle_options=hw.shuffle_options,
                   remind_levels_json=hw.remind_levels_json)
    # 参考资料：复制一份物理文件并换 stored_name，避免两个作业共享同一文件互相删毁
    if hw.reference_json and hw.reference_json.get('stored_name'):
        src = hw.reference_json['stored_name']
        src_path = os.path.join(_UPLOAD_DIR, src)
        if os.path.exists(src_path):
            new_stored = f'hwref_{uuid.uuid4().hex}{os.path.splitext(src)[1]}'
            shutil.copyfile(src_path, os.path.join(_UPLOAD_DIR, new_stored))
            new.reference_json = {**hw.reference_json, 'stored_name': new_stored}
    db.session.add(new)
    db.session.flush()
    for hq in sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id)):
        db.session.add(HomeworkQuestion(homework_id=new.id, question_id=hq.question_id,
                                        score=hq.score, order=hq.order))
    for hs in hw.hw_students:
        db.session.add(HomeworkStudent(homework_id=new.id, student_id=hs.student_id))
    db.session.commit()
    return jsonify({'message': '已复制为草稿', 'homework': new.to_dict(for_teacher=True)}), 201


@homework_bp.route('/homeworks/random_questions', methods=['GET'])
def api_random_questions():
    """按专业/课程/章节/难度/类型从题库随机抽题，供题集式作业自动组卷预填。"""
    user, err = require_teacher()
    if err:
        return err
    try:
        count = min(max(int(request.args.get('count', 5)), 1), 50)
    except (TypeError, ValueError):
        count = 5
    exclude = {int(x) for x in request.args.getlist('exclude') if str(x).isdigit()}
    q = Question.query
    for arg, field in (('major_id', 'major_id'), ('course_id', 'course_id'),
                       ('chapter_id', 'chapter_id')):
        val = request.args.get(arg)
        if val not in (None, '') and str(val).isdigit():
            q = q.filter(getattr(Question, field) == int(val))
    for arg, field in (('difficulty', 'difficulty'), ('qtype', 'type')):
        val = request.args.get(arg)
        if val not in (None, ''):
            q = q.filter(getattr(Question, field) == val)
    rows = [x for x in q.all() if x.id not in exclude]
    random.shuffle(rows)
    items = [{'question_id': x.id, 'content': x.content, 'type': x.type,
              'difficulty': x.difficulty, 'options': x.options, 'score': 5}
             for x in rows[:count]]
    return jsonify({'items': items, 'available': len(rows)})


# ═══════════════════════ 学生：作答 / 提交 / 成绩 ═══════════════════════

@homework_bp.route('/homeworks/<int:hw_id>/take', methods=['GET'])
def api_take(hw_id):
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw or hw.status == HomeworkStatusEnum.DRAFT:
        return jsonify({'message': '作业不存在'}), 404
    if not _in_roster(hw, user.id):
        return jsonify({'message': '该作业未对你发布'}), 403
    if hw.status != HomeworkStatusEnum.PUBLISHED:
        return jsonify({'message': '作业已关闭，无法进入作答'}), 400
    sub = _my_submission(hw, user.id)
    assigned = option_map = None
    shuffle = hw.hw_type == HomeworkTypeEnum.QUESTION_SET and (hw.shuffle_questions or hw.shuffle_options)
    if shuffle and sub is None:
        # v5.11 乱序需持久化个人映射：首次进入建 DRAFT 提交承载题序/选项映射（不进批改列表）
        sub = HomeworkSubmission(homework_id=hw.id, student_id=user.id,
                                 status=SubmissionStatusEnum.DRAFT)
        if hw.is_group:
            grp = get_student_group(hw, user.id)
            if grp:
                sub.group_id = grp.id
        db.session.add(sub)
        db.session.flush()
    if shuffle:
        assigned, option_map = ensure_submission_paper(hw, sub)
        db.session.commit()
    editable = hw.accepts_submission and (
        sub is None or sub.status == SubmissionStatusEnum.DRAFT or
        (not hw.is_expired and hw.allow_resubmit and sub.status == SubmissionStatusEnum.SUBMITTED))
    # v5.17 退回订正：教师退回后始终可重交（不受截止/allow_resubmit 限制），仅需作业仍为已发布
    if sub and sub.status == SubmissionStatusEnum.RETURNED and hw.status == HomeworkStatusEnum.PUBLISHED:
        editable = True
    payload = {'homework': hw.to_dict(), 'editable': editable}
    if hw.hw_type == HomeworkTypeEnum.QUESTION_SET:
        hqs = sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))
        if assigned:   # v5.11 题目乱序：按该生持久题序展示
            rank = {qid: i for i, qid in enumerate(assigned)}
            hqs = sorted(hqs, key=lambda x: rank.get(x.question_id, 1 << 30))
        payload['questions'] = [_take_question_payload(hq, (option_map or {}).get(str(hq.question_id)))
                                for hq in hqs]
        raw = {str(a.question_id): a.answer for a in sub.answers} if sub else {}
        if option_map:   # v5.11 存的是规范化字母，回显映射回该生显示位
            from api.exam_engine import map_letters
            for k, v in raw.items():
                perm = option_map.get(k)
                if perm:
                    raw[k] = map_letters(v or '', perm, reverse=True)
        payload['answers'] = raw
    else:
        payload['content'] = (sub.content if sub else '')
        payload['attachment'] = sub.attachment_meta() if sub else None
    if sub:
        payload['submission'] = sub.to_dict()
    if hw.is_group:
        grp = get_student_group(hw, user.id)
        payload['my_group'] = grp.to_dict() if grp else None
    return jsonify(payload)


@homework_bp.route('/homeworks/<int:hw_id>/answers', methods=['POST'])
def api_save_answers(hw_id):
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw or not _in_roster(hw, user.id):
        return jsonify({'message': '作业不存在或未对你发布'}), 404
    if hw.status != HomeworkStatusEnum.PUBLISHED:
        return jsonify({'message': '作业已关闭'}), 400
    sub = _my_submission(hw, user.id)
    # v5.17 退回订正：已退回的提交不受截止时间限制可存草稿（教师已显式授权重交）
    if not hw.accepts_submission and not (sub and sub.status == SubmissionStatusEnum.RETURNED):
        return jsonify({'message': '已过截止时间'}), 400
    if sub and sub.status == SubmissionStatusEnum.GRADED:
        return jsonify({'message': '已批改完成，不可再修改'}), 400
    if sub is None:
        sub = HomeworkSubmission(homework_id=hw.id, student_id=user.id,
                                 status=SubmissionStatusEnum.DRAFT)
        if hw.is_group:
            grp = get_student_group(hw, user.id)
            if grp:
                sub.group_id = grp.id
        db.session.add(sub)
        db.session.flush()
    elif hw.is_group:
        sub.student_id = user.id
    data = request.get_json(silent=True) or {}
    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
    _, option_map = ensure_submission_paper(hw, sub)   # v5.11 乱序：复用/生成个人映射
    saved = 0
    for qid, text in (data.get('answers') or {}).items():
        try:
            qid = int(qid)
        except (TypeError, ValueError):
            continue
        if qid not in hq_map:
            continue   # 不在本作业题单：静默忽略
        a = next((x for x in sub.answers if x.question_id == qid), None)
        if a is None:
            a = HomeworkAnswer(submission_id=sub.id, question_id=qid)
            db.session.add(a)
            sub.answers.append(a)
        val = _canonical_choice_answer(hq_map, option_map, qid, text) if option_map else text
        a.answer = str(val if val is not None else '')[:50000]
        saved += 1
    if hw.hw_type == HomeworkTypeEnum.OPEN and 'content' in data:
        sub.content = str(data.get('content') or '')[:50000]
        db.session.flush()
        saved += 1
    db.session.commit()
    return jsonify({'message': '已保存', 'saved': saved, 'version': sub.version})


def _save_attachment_to(sub, file):
    try:
        stored, size = _save_upload(file, 'hw')
    except ValueError as e:
        return str(e)
    old = (sub.attachment_json or {}).get('stored_name')
    if old and old != stored:   # 重交覆盖附件：清理旧盘文件，避免孤儿堆积
        try:
            os.remove(os.path.join(_UPLOAD_DIR, old))
        except OSError:
            pass
    sub.attachment_json = {
        'filename': file.filename[:200], 'stored_name': stored, 'size': size,
        'ext': os.path.splitext(file.filename)[1].lower()}
    return None


def _award_grade_bonus_safe(hw, sub):
    """批改完成按得分率补发质量积分（非关键路径，失败不阻断批改响应）。"""
    try:
        from homework.services import award_homework_grade_bonus
        award_homework_grade_bonus(hw, sub)
    except Exception:
        logger.exception('[homework] 批改积分入账失败（非关键）hw=%s sub=%s', hw.id, sub.id)


@homework_bp.route('/homeworks/<int:hw_id>/submit', methods=['POST'])
@limiter.limit('20/minute')
def api_submit(hw_id):
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw or not _in_roster(hw, user.id):
        return jsonify({'message': '作业不存在或未对你发布'}), 404
    if hw.status != HomeworkStatusEnum.PUBLISHED:
        return jsonify({'message': '作业未发布或已关闭'}), 400

    sub = _my_submission(hw, user.id)
    if sub and sub.status == SubmissionStatusEnum.GRADED:
        return jsonify({'message': '已批改完成，不能再提交'}), 400
    # v5.17 退回订正重交：教师已显式授权，不受截止/allow_resubmit 限制（区别普通重交覆盖）
    revision = bool(sub and sub.status == SubmissionStatusEnum.RETURNED)
    resubmit = (not revision) and bool(sub and sub.status == SubmissionStatusEnum.SUBMITTED)
    if not revision:
        if hw.is_expired and not hw.allow_late:
            return jsonify({'message': '已过截止时间且不允许迟交'}), 403
        if resubmit:
            if hw.is_expired:
                return jsonify({'message': '迟交仅一次，过期后不可重交'}), 403
            if not hw.allow_resubmit:
                return jsonify({'message': '本作业不允许重交'}), 403

    if sub is None:
        sub = HomeworkSubmission(homework_id=hw.id, student_id=user.id,
                                 status=SubmissionStatusEnum.DRAFT)
        if hw.is_group:
            grp = get_student_group(hw, user.id)
            if grp:
                sub.group_id = grp.id
        db.session.add(sub)
        db.session.flush()
    elif hw.is_group:
        # 小组作业：任一成员提交均更新同一组提交的「提交人」为当前操作人
        sub.student_id = user.id

    # 开放式：multipart（file=附件）或 JSON content；题集式：取已存草稿作答
    if request.content_type and 'multipart/form-data' in request.content_type:
        if hw.hw_type != HomeworkTypeEnum.OPEN:
            return jsonify({'message': '题集式请用 JSON 提交'}), 400
        content = str(request.form.get('content') or '')[:50000]
        sub.content = content
        file = request.files.get('file')
        if file and file.filename:
            emsg = _save_attachment_to(sub, file)
            if emsg:
                return jsonify({'message': emsg}), 400
    else:
        data = request.get_json(silent=True) or {}
        _, option_map = ensure_submission_paper(hw, sub)   # v5.11 乱序：存答前反归
        hq_map = {hq.question_id: hq for hq in hw.hw_questions}
        for qid, text in (data.get('answers') or {}).items():
            try:
                qid = int(qid)
            except (TypeError, ValueError):
                continue
            if not any(hq.question_id == qid for hq in hw.hw_questions):
                continue
            a = next((x for x in sub.answers if x.question_id == qid), None)
            if a is None:
                a = HomeworkAnswer(submission_id=sub.id, question_id=qid)
                db.session.add(a)
                sub.answers.append(a)
            val = _canonical_choice_answer(hq_map, option_map, qid, text) if option_map else text
            a.answer = str(val if val is not None else '')[:50000]
        if hw.hw_type == HomeworkTypeEnum.OPEN and 'content' in data:
            sub.content = str(data.get('content') or '')[:50000]

    if hw.hw_type == HomeworkTypeEnum.OPEN and not (sub.content or '').strip() \
            and not (sub.attachment_json or {}).get('stored_name'):
        return jsonify({'message': '请至少填写内容或上传附件'}), 400

    finalize_submission(hw, sub)
    if resubmit or revision:
        sub.version = (sub.version or 1) + 1
    if revision:
        sub.revision_round = (sub.revision_round or 0) + 1
        sub.is_late = False   # 订正重做视为教师授权的返工，不按迟交处理
    db.session.commit()
    # 师生互动：学生提交/重交 → 实时通知教师去批改（经 ORM 事件自动推送）
    create_notification(
        hw.teacher_id, '收到作业订正重交' if revision else ('收到作业重交' if resubmit else '收到作业提交'),
        f'《{hw.title}》学生 {user.username} 已提交（第 {sub.version or 1} 版），待批改。',
        type='info', related_type='homework', related_id=hw.id)
    # v5.2 学习闭环：自动判分部分的错题收录 + 知识点掌握度（非关键路径，不阻塞提交）
    try:
        from homework.services import sync_learning_effects
        sync_learning_effects(hw, sub, scope='auto')
    except Exception:
        logger.exception('[homework] 学习闭环联动失败（非关键）hw=%s sub=%s', hw.id, sub.id)
    # v5.8 系列作业：提交即完成当日对应的 DailyTask
    try:
        complete_homework_daily_task(hw, user.id)
    except Exception:
        logger.debug('[homework] 每日任务标记失败（非关键）', exc_info=True)
    # v5.10 作业入账：最终提交发放基础积分（重交幂等，不重复计分）
    try:
        from homework.services import award_homework_submit_points
        award_homework_submit_points(hw, sub)
    except Exception:
        logger.exception('[homework] 提交积分入账失败（非关键）hw=%s sub=%s', hw.id, sub.id)
    return jsonify({'message': '提交成功' + ('（迟交已标记）' if sub.is_late else ''),
                    'submission': sub.to_dict()}), 201


@homework_bp.route('/homeworks/<int:hw_id>/result', methods=['GET'])
def api_result(hw_id):
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw or not _in_roster(hw, user.id):
        return jsonify({'message': '作业不存在或未对你发布'}), 404
    sub = _my_submission(hw, user.id)
    if not sub or sub.status == SubmissionStatusEnum.DRAFT:
        return jsonify({'submitted': False, 'homework': hw.to_dict()})
    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
    payload = {'submitted': True, 'homework': hw.to_dict(),
               'submission': sub.to_dict(),
               'answers': [a.to_dict(for_teacher=False,
                                     max_score=hq_map[a.question_id].score if a.question_id in hq_map else None)
                           for a in sub.answers]}
    # v5.3 AI 讲评：班级讲评仅发布后可见；单份讲评批改完成后可见
    class_rec = _get_class_review(hw)
    payload['class_review'] = (class_rec.to_dict(for_student=True)
                               if class_rec and class_rec.published_at else None)
    if sub.status == SubmissionStatusEnum.GRADED:
        own_rec = HomeworkAiReview.query.filter_by(
            homework_id=hw.id, scope_key=f'sub:{sub.id}').first()
        payload['ai_review'] = own_rec.to_dict(for_student=True) if own_rec else None
        # v5.5 互评结果：批改完成后才对本人披露（匿名）
        payload['peer_review'] = peer_review_received(sub)
    else:
        payload['ai_review'] = None
        payload['peer_review'] = None
    return jsonify(payload)


# ═══════════════════════ 教师：提交列表 / 批改 ═══════════════════════

@homework_bp.route('/homeworks/<int:hw_id>/submissions', methods=['GET'])
def api_submissions(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    subs = [s for s in hw.submissions if s.status != SubmissionStatusEnum.DRAFT]
    subs.sort(key=lambda s: (s.status != SubmissionStatusEnum.SUBMITTED, s.id), reverse=False)
    submitted_ids = {s.student_id for s in subs}
    not_submitted = [{'student_id': hs.student_id,
                      'username': hs.student.username if hs.student else ''}
                     for hs in hw.hw_students if hs.student_id not in submitted_ids]
    blind = blind_active(hw)
    items = [s.to_dict(for_teacher=True) for s in subs]
    if blind:   # v5.11 匿名批改：批完前隐藏身份（不泄露真名/student_id）
        for s, d in zip(subs, items):
            d['username'] = blind_label(hw, s)
            d['student_id'] = None
            d['blind'] = True
        not_submitted = [{'student_id': None, 'username': '未提交'}] * len(not_submitted)
    return jsonify({'items': items,
                    'not_submitted': not_submitted,
                    'blind': blind,
                    'student_count': len(hw.hw_students),
                    'groups': [g.to_dict() for g in hw.groups]})


@homework_bp.route('/homeworks/grading-queue', methods=['GET'])
@limiter.limit('60/minute')
def api_grading_queue():
    """v5.12 批改工作台：跨该教师所有已发布作业聚合待批（SUBMITTED）提交。

    只读不改判分口径；`pending` 为题集式待人工题数（开放式为 0 但 hw_type=open 仍需整体给分）。
    尊重匿名批改（blind_grading）：批完前隐去真名/student_id。可选按作业过滤 + 分页。
    """
    user, err = require_teacher()
    if err:
        return err
    hws = (Homework.query.filter(Homework.teacher_id == user.id,
                                 Homework.status != HomeworkStatusEnum.DRAFT)
           .order_by(Homework.id.desc()).all())
    hw_filter = request.args.get('homework_id', type=int)
    try:
        page = max(1, request.args.get('page', 1, type=int))
        size = min(200, max(1, request.args.get('size', 100, type=int)))
    except (TypeError, ValueError):
        page, size = 1, 100

    rows = []            # (submitted_at_key, item_dict)
    per_hw = []          # 每作业进度
    graded_total = 0
    pending_total = 0
    for hw in hws:
        submitted = [s for s in hw.submissions if s.status != SubmissionStatusEnum.DRAFT]
        graded = [s for s in submitted if s.status == SubmissionStatusEnum.GRADED]
        to_grade = [s for s in submitted if s.status == SubmissionStatusEnum.SUBMITTED]
        graded_total += len(graded)
        pending_total += len(to_grade)
        per_hw.append({'id': hw.id, 'title': hw.title, 'hw_type': str(hw.hw_type),
                       'submitted': len(submitted), 'graded': len(graded), 'pending': len(to_grade)})
        if hw_filter and hw.id != hw_filter:
            continue
        blind = blind_active(hw)
        for s in to_grade:
            pend = sum(1 for a in s.answers if a.needs_manual_grade and a.manual_score is None)
            item = {'sub_id': s.id, 'homework_id': hw.id, 'homework_title': hw.title,
                    'hw_type': str(hw.hw_type), 'student_id': (None if blind else s.student_id),
                    'username': (blind_label(hw, s) if blind else
                                 (s.student.username if s.student else '')),
                    'blind': blind,
                    'submitted_at': iso_local(s.submitted_at) if s.submitted_at else None,
                    'pending': pend, 'max_score': s.max_score, 'is_late': bool(s.is_late)}
            rows.append(((s.submitted_at.timestamp() if s.submitted_at else 0), item))
    rows.sort(key=lambda x: x[0])            # 按提交时间升序（先交先批）
    items = [it for _, it in rows]
    total = len(items)
    start = (page - 1) * size
    paged = items[start:start + size]
    return jsonify({'items': paged, 'total': total, 'page': page, 'size': size,
                    'stats': {'pending_total': pending_total, 'graded_total': graded_total},
                    'homeworks': per_hw})


@homework_bp.route('/homeworks/<int:hw_id>/grade/<int:sub_id>', methods=['GET'])
def api_grade_view(hw_id, sub_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    return jsonify(_grade_payload(hw, sub))


def _grade_payload(hw, sub):
    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
    rec = HomeworkAiReview.query.filter_by(
        homework_id=hw.id, scope_key=f'sub:{sub.id}').first()
    sub_d = sub.to_dict(for_teacher=True)
    blind = blind_active(hw)
    if blind:   # v5.11 匿名批改：批改视图同样隐去真名，批改仍走 sub_id
        sub_d['username'] = blind_label(hw, sub)
        sub_d['student_id'] = None
        sub_d['blind'] = True
    return {'homework': hw.to_dict(for_teacher=True),
            'submission': sub_d,
            'blind': blind,
            'rubric': hw.rubric.to_dict() if hw.rubric else None,
            'answers': [a.to_dict(for_teacher=True,
                                  max_score=hq_map[a.question_id].score if a.question_id in hq_map else None)
                        for a in sub.answers],
            'questions': [_question_payload(hq, True) for hq in
                          sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))],
            'ai_review': rec.to_dict() if rec else None,
            'peer_review': peer_review_received(sub)}


@homework_bp.route('/homeworks/<int:hw_id>/grade/<int:sub_id>', methods=['POST'])
def api_grade_submit(hw_id, sub_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    if sub.status == SubmissionStatusEnum.DRAFT:
        return jsonify({'message': '学生尚未提交'}), 400
    was_graded = sub.status == SubmissionStatusEnum.GRADED  # v5.2：仅首次转 GRADED 触发学习闭环

    data = request.get_json(silent=True) or {}

    # v5.15 评分量规：逐维度得分快照（可选，仅记录/建议，不改 total_score/manual_score）
    if 'rubric_scores' in data:
        if hw.rubric is None:
            return jsonify({'message': '本作业未关联量规'}), 400
        rs, rerr = _normalize_rubric_scores(hw.rubric, data.get('rubric_scores'))
        if rerr:
            return jsonify({'message': rerr}), 400
        sub.rubric_scores_json = rs

    # 开放式：无逐题作答行，整体给一个总分（score 缺省则只存评语、保持待批）
    if hw.hw_type == HomeworkTypeEnum.OPEN:
        if 'comment' in data:
            sub.comment = str(data.get('comment') or '')[:5000]
        score = data.get('score')
        if score is None or score == '':
            db.session.commit()
            return jsonify({'message': '已保存评语', 'graded': False, 'pending_manual': 1,
                            'submission': sub.to_dict(for_teacher=True)})
        try:
            score = float(score)
        except (TypeError, ValueError):
            return jsonify({'message': '分数须为数字'}), 400
        full = data.get('max_score')
        try:
            full = float(full) if full not in (None, '') else 100.0
        except (TypeError, ValueError):
            full = 100.0
        if full <= 0:
            full = 100.0
        if not (0 <= score <= full):
            return jsonify({'message': f'分数须在 0~{full} 之间'}), 400
        sub.total_score = round(score, 2)
        sub.max_score = round(full, 2)
        sub.status = SubmissionStatusEnum.GRADED
        sub.graded_by = user.id
        sub.graded_at = utcnow()
        apply_late_penalty(hw, sub)   # v5.11 迟交扣分（转 GRADED 收口）
        msg = f'《{hw.title}》成绩已公布：{sub.total_score} 分（满分 {sub.max_score}）。'
        _notify_graded(hw, sub, msg)
        db.session.commit()
        if not was_graded:
            _award_grade_bonus_safe(hw, sub)
        return jsonify({'message': '已批改完成', 'graded': True, 'pending_manual': 0,
                        'submission': sub.to_dict(for_teacher=True)})

    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
    amap = {a.id: a for a in sub.answers}
    applied = 0
    for item in data.get('answers') or []:
        a = amap.get(item.get('answer_id'))
        if not a:
            continue
        score = item.get('score')
        if score is not None and score != '':
            try:
                score = float(score)
            except (TypeError, ValueError):
                return jsonify({'message': f'题目 {a.question_id} 分数须为数字'}), 400
            full = (hq_map[a.question_id].score if a.question_id in hq_map else None) or 100.0
            if not (0 <= score <= full):
                return jsonify({'message': f'题目 {a.question_id} 分数须在 0~{full} 之间'}), 400
            a.manual_score = round(score, 2)
        comment = item.get('comment')
        if comment is not None:
            a.comment = str(comment)[:2000]
        applied += 1
    if 'comment' in data:
        sub.comment = str(data.get('comment') or '')[:5000]

    earned, max_total, pending = recompute_total(sub)
    if pending == 0:
        apply_late_penalty(hw, sub)   # v5.11 迟交扣分（转 GRADED 收口，先扣后播报）
        earned = sub.total_score
        sub.status = SubmissionStatusEnum.GRADED
        sub.graded_by = user.id
        sub.graded_at = utcnow()
        msg = (f'《{hw.title}》成绩已公布：{earned} 分'
               + (f'（满分 {max_total}）' if max_total else '') + '。')
        _notify_graded(hw, sub, msg)
    db.session.commit()
    if pending == 0 and not was_graded:
        # v5.2 学习闭环：人工判分部分错题收录 + 掌握度（首次转 GRADED 才触发，防重复收录）
        try:
            from homework.services import sync_learning_effects
            sync_learning_effects(hw, sub, scope='final')
        except Exception:
            logger.exception('[homework] 学习闭环联动失败（非关键）hw=%s sub=%s', hw.id, sub.id)
        # v5.10 批改完成：按得分率补发作业质量积分（独立幂等键）
        _award_grade_bonus_safe(hw, sub)
    return jsonify({'message': '已批改完成' if pending == 0 else f'已保存给分（仍有 {pending} 题待批）',
                    'graded': pending == 0, 'pending_manual': pending,
                    'submission': sub.to_dict(for_teacher=True)})


@homework_bp.route('/homeworks/<int:hw_id>/grade/<int:sub_id>/return', methods=['POST'])
def api_grade_return(hw_id, sub_id):
    """v5.17 教师将已批改提交退回订正（需作业开启 allow_revision）。

    区别 allow_resubmit（截止前自由覆盖）：本动作发生在批改之后，置 status=returned
    并落退回意见，通知学生重交。账务护栏：重交重批沿用既有幂等键
    （homework-submit/homework-grade 不含轮次）天然不二次发分，质量分不补差。"""
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    if not hw.allow_revision:
        return jsonify({'message': '本作业未开启订正重做'}), 400
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    if sub.status != SubmissionStatusEnum.GRADED:
        return jsonify({'message': '仅已批改的提交可退回订正'}), 400
    data = request.get_json(silent=True) or {}
    reason = str(data.get('reason') or '').strip()[:2000]
    if reason:
        sub.comment = reason
    sub.status = SubmissionStatusEnum.RETURNED
    db.session.commit()
    msg = f'《{hw.title}》已被老师退回订正' + (f'：{reason}' if reason else '，请查看反馈后重新提交。')
    _notify_returned(hw, sub, msg)
    db.session.commit()
    return jsonify({'message': '已退回订正', 'submission': sub.to_dict(for_teacher=True)})


@homework_bp.route('/homeworks/redo', methods=['GET'])
def api_homework_redo():
    """v5.17 学生待订正列表：跨本人相关已发布作业筛 status=returned 的提交，
    附上次分数/退回意见/订正轮次（小组作业取本组共享提交）。"""
    user, err = require_login()
    if err:
        return err
    if user.is_teacher():
        return jsonify({'message': '待订正列表仅对学生开放'}), 403
    hws = (Homework.query.join(HomeworkStudent, HomeworkStudent.homework_id == Homework.id)
           .filter(HomeworkStudent.student_id == user.id,
                   Homework.status == HomeworkStatusEnum.PUBLISHED).all())
    items = []
    for hw in hws:
        sub = _my_submission(hw, user.id)
        if not sub or sub.status != SubmissionStatusEnum.RETURNED:
            continue
        gmode = (getattr(hw, 'grade_mode', 'numeric') or 'numeric')
        items.append({'homework_id': hw.id, 'title': hw.title, 'hw_type': str(hw.hw_type),
                      'sub_id': sub.id, 'is_group': bool(hw.is_group),
                      'deadline': iso_local(hw.deadline) if hw.deadline else None,
                      'has_deadline': hw.deadline is not None,
                      'grade_mode': gmode,
                      'total_score': None if gmode == 'comment' else sub.total_score,
                      'max_score': sub.max_score, 'comment': sub.comment or '',
                      'revision_round': sub.revision_round or 0, 'version': sub.version or 1,
                      'graded_at': iso_local(sub.graded_at) if sub.graded_at else None})
    items.sort(key=lambda it: it['graded_at'] or '', reverse=True)
    return jsonify({'items': items, 'count': len(items)})


# ═══════════════════ v5.19 优秀作业展示墙 / 精选归档 ═══════════════════

def _showcase_visible(hw, user):
    """展示墙可见性：该作业发布名单内成员，或作业创建教师本人。"""
    return hw.teacher_id == user.id or bool(_in_roster(hw, user.id))


def _showcase_author(sub, viewer):
    """作者展示名：学生选择匿名且查看者非本人/非该作业教师 → 匿名同学。"""
    name = sub.student.username if sub.student else ''
    if sub.showcase_anon and viewer.id != sub.student_id:
        hw = sub.homework
        if hw and hw.teacher_id != viewer.id:
            return '匿名同学'
    return name


def _showcase_summary(sub, viewer):
    hw = sub.homework
    return {
        'sub_id': sub.id, 'homework_id': hw.id, 'homework_title': hw.title,
        'hw_type': str(hw.hw_type), 'author': _showcase_author(sub, viewer),
        'is_mine': sub.student_id == viewer.id,
        'total_score': sub.total_score, 'max_score': sub.max_score,
        'comment': sub.comment or '', 'excerpt': (sub.content or '')[:160],
        'has_attachment': bool((sub.attachment_json or {}).get('stored_name')),
        'showcase_anon': bool(sub.showcase_anon),
        'showcase_status': sub.showcase_status,
        'graded_at': iso_local(sub.graded_at) if sub.graded_at else None,
    }


@homework_bp.route('/homeworks/<int:hw_id>/grade/<int:sub_id>/feature', methods=['POST'])
def api_showcase_feature(hw_id, sub_id):
    """v5.19 教师提名/撤下优秀作业展示（仅已批改可提名；提名后待学生同意）。"""
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or 'nominate').strip()
    if action == 'withdraw':
        sub.showcase_status = ShowcaseStatusEnum.NONE
        sub.showcase_at = utcnow()
        db.session.commit()
        return jsonify({'message': '已从展示墙撤下', 'submission': sub.to_dict(for_teacher=True)})
    if sub.status != SubmissionStatusEnum.GRADED:
        return jsonify({'message': '仅已批改的提交可提名展示'}), 400
    sub.showcase_status = ShowcaseStatusEnum.NOMINATED
    sub.showcase_at = utcnow()
    create_notification(sub.student_id, '作品入选优秀作业展示',
                        f'《{hw.title}》你的作业被老师推荐展示，同意后可在展示墙与同学分享（可选择匿名）。',
                        type='success', related_type='homework', related_id=hw.id)
    db.session.commit()
    return jsonify({'message': '已提名，待学生确认授权后上墙',
                    'submission': sub.to_dict(for_teacher=True)})


@homework_bp.route('/homeworks/showcase/<int:sub_id>/consent', methods=['POST'])
def api_showcase_consent(sub_id):
    """v5.19 学生对提名作品授权/拒绝（accept=true 上 featured，可带 anonymous 匿名展示；
    accept=false 撤回至 none）。仅提交本人（或小组成员）可操作。"""
    user, err = require_login()
    if err:
        return err
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub:
        return jsonify({'message': '提交不存在'}), 404
    owner = sub.student_id == user.id
    if not owner and sub.group_id and sub.group:
        owner = any(m.student_id == user.id for m in sub.group.members)
    if not owner:
        return jsonify({'message': '只能处理自己的作品'}), 403
    if sub.showcase_status not in (ShowcaseStatusEnum.NOMINATED, ShowcaseStatusEnum.FEATURED):
        return jsonify({'message': '当前状态无需确认'}), 400
    data = request.get_json(silent=True) or {}
    accept = bool(data.get('accept'))
    if sub.showcase_status == ShowcaseStatusEnum.FEATURED and accept:
        return jsonify({'message': '作品已在展示墙'}), 400
    if accept:
        sub.showcase_anon = bool(data.get('anonymous'))
        sub.showcase_status = ShowcaseStatusEnum.FEATURED
        create_notification(sub.homework.teacher_id, '学生已同意展示作品',
                            f'《{sub.homework.title}》有作品已确认授权上展示墙。',
                            type='success', related_type='homework', related_id=sub.homework_id)
    else:
        sub.showcase_status = ShowcaseStatusEnum.NONE
    sub.showcase_at = utcnow()
    db.session.commit()
    return jsonify({'message': '已同意展示' if accept else '已拒绝/撤回展示',
                    'showcase_status': sub.showcase_status})


@homework_bp.route('/homeworks/showcase', methods=['GET'])
@limiter.limit('60/minute')
def api_showcase_wall():
    """v5.19 展示墙：列出查看者所在名单作业里的 featured 作品（摘要+教师点评）。"""
    user, err = require_login()
    if err:
        return err
    subs = (HomeworkSubmission.query.filter(
        HomeworkSubmission.showcase_status == ShowcaseStatusEnum.FEATURED).all())
    items = []
    for sub in subs:
        hw = sub.homework
        if not hw or not _showcase_visible(hw, user):
            continue
        items.append(_showcase_summary(sub, user))
    items.sort(key=lambda x: x['graded_at'] or '', reverse=True)
    return jsonify({'items': items, 'count': len(items)})


@homework_bp.route('/homeworks/showcase/invitations', methods=['GET'])
def api_showcase_invitations():
    """v5.19 学生待确认的展示邀请（本人被提名 nominated 的作品）。教师 403。"""
    user, err = require_login()
    if err:
        return err
    if user.is_teacher():
        return jsonify({'message': '展示邀请仅对学生开放'}), 403
    subs = (HomeworkSubmission.query.filter_by(
        student_id=user.id, showcase_status=ShowcaseStatusEnum.NOMINATED).all())
    items = []
    for sub in subs:
        if not sub.homework:
            continue
        items.append({
            'sub_id': sub.id, 'homework_id': sub.homework_id,
            'homework_title': sub.homework.title, 'hw_type': str(sub.homework.hw_type),
            'total_score': sub.total_score, 'max_score': sub.max_score,
            'comment': sub.comment or '', 'excerpt': (sub.content or '')[:200],
            'nominated_at': iso_local(sub.showcase_at) if sub.showcase_at else None,
        })
    items.sort(key=lambda x: x['nominated_at'] or '', reverse=True)
    return jsonify({'items': items, 'count': len(items)})


@homework_bp.route('/homeworks/showcase/<int:sub_id>', methods=['GET'])
def api_showcase_detail(sub_id):
    """v5.19 展示详情：名单内可查看完整正文/附件元信息（按可见性再校验）。"""
    user, err = require_login()
    if err:
        return err
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub or not sub.homework:
        return jsonify({'message': '作品不存在'}), 404
    if sub.showcase_status != ShowcaseStatusEnum.FEATURED and sub.student_id != user.id:
        return jsonify({'message': '该作品未公开'}), 403
    if not _showcase_visible(sub.homework, user):
        return jsonify({'message': '无权查看该作品'}), 403
    d = _showcase_summary(sub, user)
    d['content'] = sub.content or ''
    d['attachment'] = sub.attachment_meta()
    return jsonify(d)


# ═══════════════════ v5.20 批改批注（图片/PDF 画线，仅教师可写）═══════════════════

def _clean_shape(s):
    """校验并归一化单个批注图形；非法类型/非 dict 返回 None（不落库脏数据）。

    坐标以归一化比例（0~1）存储，适配不同显示尺寸；page 支持 PDF 多页（图片恒 0）。"""
    if not isinstance(s, dict):
        return None
    t = s.get('type')
    if t not in AnnotationTypeEnum.ALL:
        return None
    try:
        page = int(s.get('page', 0) or 0)
    except (TypeError, ValueError):
        page = 0
    if page < 0:
        page = 0
    try:
        width = max(0.0, min(float(s.get('width') or 2), 60.0))
    except (TypeError, ValueError):
        width = 2.0
    out = {'id': str(s.get('id') or '')[:40], 'type': t, 'page': page,
           'color': str(s.get('color') or '#ef4444')[:20], 'width': width}
    pts = s.get('points')
    if isinstance(pts, list):
        norm = []
        for p in pts[:400]:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                try:
                    norm.append([round(float(p[0]), 4), round(float(p[1]), 4)])
                except (TypeError, ValueError):
                    continue
        out['points'] = norm
    if s.get('x') is not None and s.get('y') is not None:
        try:
            out['x'] = round(float(s['x']), 4)
            out['y'] = round(float(s['y']), 4)
        except (TypeError, ValueError):
            pass
    if t == AnnotationTypeEnum.TEXT:
        out['text'] = str(s.get('text') or '')[:200]
    return out


@homework_bp.route('/homeworks/<int:hw_id>/annotation', methods=['GET'])
def api_annotation_get(hw_id):
    """读某份提交的批注图层：创建教师 / 提交本人（含组员）可看，其余 403。"""
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw:
        return jsonify({'message': '作业不存在'}), 404
    sub_id = request.args.get('submission_id', type=int)
    mine = _my_submission(hw, user.id)
    sub = db.session.get(HomeworkSubmission, sub_id) if sub_id else mine
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    is_owner_teacher = user.is_teacher() and hw.teacher_id == user.id
    if not is_owner_teacher and not (mine and mine.id == sub.id):
        return jsonify({'message': '无权查看该批注'}), 403
    ann = HomeworkAnnotation.query.filter_by(submission_id=sub.id).first()
    return jsonify({'submission_id': sub.id,
                    'shapes': (ann.shapes_json if ann else []) or [],
                    'can_edit': bool(is_owner_teacher)})


@homework_bp.route('/homeworks/<int:hw_id>/annotation', methods=['POST'])
@limiter.limit('60/minute')
def api_annotation_save(hw_id):
    """教师 upsert 某份提交的批注图层（纯叠加，不改判分/总分/账本）。"""
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    sub_id = data.get('submission_id')
    sub = db.session.get(HomeworkSubmission, sub_id) if sub_id else None
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    shapes = data.get('shapes')
    if not isinstance(shapes, list):
        return jsonify({'message': 'shapes 必须为列表'}), 400
    if len(shapes) > 500:
        return jsonify({'message': '批注图形过多（上限 500）'}), 400
    clean = [c for c in (_clean_shape(s) for s in shapes) if c]
    ann = HomeworkAnnotation.query.filter_by(submission_id=sub.id).first()
    if ann is None:
        ann = HomeworkAnnotation(submission_id=sub.id, homework_id=hw.id,
                                 author_id=user.id, shapes_json=clean)
        db.session.add(ann)
    else:
        ann.shapes_json = clean
        ann.author_id = user.id
    db.session.commit()
    return jsonify({'message': '批注已保存', 'count': len(clean), 'shapes': clean})


@homework_bp.route('/homeworks/<int:hw_id>/grade/<int:sub_id>/ai_suggest', methods=['POST'])
@limiter.limit('10/minute')
def api_grade_ai(hw_id, sub_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    try:
        result = ai_suggest_grading(sub)
    except Exception:
        return jsonify({'message': 'AI 服务暂不可用，请稍后重试或人工批改'}), 503
    return jsonify(result)


@homework_bp.route('/homeworks/<int:hw_id>/grade/batch', methods=['POST'])
@limiter.limit('30/minute')
def api_grade_batch(hw_id):
    """v5.11 同题批量给分：把某题统一分数/评语应用到多份提交（缺省=所有非草稿提交）。

    逐份重算总分，pending 归零则转 GRADED（首次转态才触发学习闭环与质量积分，批量内逐份幂等）。
    """
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    if hw.hw_type != HomeworkTypeEnum.QUESTION_SET:
        return jsonify({'message': '仅题集式作业支持逐题批量给分'}), 400
    data = request.get_json(silent=True) or {}
    try:
        qid = int(data.get('question_id'))
    except (TypeError, ValueError):
        return jsonify({'message': 'question_id 须为数字'}), 400
    hq = next((x for x in hw.hw_questions if x.question_id == qid), None)
    if not hq:
        return jsonify({'message': '题目不在本作业'}), 404
    score = data.get('score')
    if score is None or score == '':
        return jsonify({'message': 'score 必填'}), 400
    try:
        score = float(score)
    except (TypeError, ValueError):
        return jsonify({'message': '分数须为数字'}), 400
    full = hq.score or 100.0
    if not (0 <= score <= full):
        return jsonify({'message': f'分数须在 0~{full} 之间'}), 400
    comment = str(data.get('comment') or '')[:2000] if data.get('comment') is not None else None

    subs = [s for s in hw.submissions if s.status != SubmissionStatusEnum.DRAFT]
    sids = data.get('submission_ids')
    if sids:
        want = {int(x) for x in sids if str(x).isdigit()}
        subs = [s for s in subs if s.id in want]
    applied = still_pending = 0
    newly = []
    for sub in subs:
        a = next((x for x in sub.answers if x.question_id == qid), None)
        if a is None:
            continue
        was_graded = sub.status == SubmissionStatusEnum.GRADED
        a.manual_score = round(score, 2)
        if comment is not None:
            a.comment = comment
        _earned, _max, pending = recompute_total(sub)
        applied += 1
        if pending == 0:
            apply_late_penalty(hw, sub)   # 重算后重新扣（recompute 已回写原始分，幂等）
            if not was_graded:
                sub.status = SubmissionStatusEnum.GRADED
                sub.graded_by = user.id
                sub.graded_at = utcnow()
                newly.append(sub)
        else:
            still_pending += 1
    db.session.commit()
    # 首次转 GRADED：逐份补做学习闭环 + 通知 + 质量积分（失败不阻断，与单份一致）
    from homework.services import sync_learning_effects, award_homework_grade_bonus
    for sub in newly:
        msg = (f'《{hw.title}》成绩已公布：{sub.total_score} 分'
               + (f'（满分 {sub.max_score}）' if sub.max_score else '') + '。')
        _notify_graded(hw, sub, msg)
        try:
            sync_learning_effects(hw, sub, scope='final')
        except Exception:
            logger.exception('[homework] 批量批改学习闭环失败 hw=%s sub=%s', hw.id, sub.id)
        try:
            award_homework_grade_bonus(hw, sub)
        except Exception:
            logger.exception('[homework] 批量批改积分入账失败 hw=%s sub=%s', hw.id, sub.id)
    db.session.commit()
    return jsonify({'message': f'已批量给分 {applied} 份（新批完 {len(newly)}，待批 {still_pending}）',
                    'applied': applied, 'graded': len(newly), 'still_pending': still_pending})


# ═══════════════════════ v5.3 AI 讲评：单份讲评 ═══════════════════════

@homework_bp.route('/homeworks/<int:hw_id>/grade/<int:sub_id>/ai_review', methods=['GET'])
def api_submission_review_get(hw_id, sub_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    rec = HomeworkAiReview.query.filter_by(
        homework_id=hw.id, scope_key=f'sub:{sub.id}').first()
    return jsonify({'exists': bool(rec), 'review': rec.to_dict() if rec else None})


@homework_bp.route('/homeworks/<int:hw_id>/grade/<int:sub_id>/ai_review', methods=['POST'])
@limiter.limit('10/minute')
def api_submission_review_generate(hw_id, sub_id):
    """生成单份 AI 讲评（须已批改；未批改分数不完整，拒绝生成）。"""
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    sub = db.session.get(HomeworkSubmission, sub_id)
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    if sub.status != SubmissionStatusEnum.GRADED:
        return jsonify({'message': '批改完成后才能生成单份 AI 讲评'}), 400
    result = build_submission_review(hw, sub)
    rec = upsert_ai_review(hw, 'submission', result, user.id, submission_id=sub.id)
    return jsonify({'message': 'AI 服务暂不可用，已生成规则版讲评'
                    if rec.degraded else '单份 AI 讲评已生成',
                    'degraded': bool(rec.degraded), 'review': rec.to_dict()})


# ═══════════════════════ 附件下载（鉴权：本人 / 创建教师）═══════════════════════

@homework_bp.route('/homeworks/<int:hw_id>/attachment', methods=['GET'])
def api_attachment(hw_id):
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw:
        return jsonify({'message': '作业不存在'}), 404
    sub_id = request.args.get('submission_id', type=int)
    sub = db.session.get(HomeworkSubmission, sub_id) if sub_id else _my_submission(hw, user.id)
    if not sub or sub.homework_id != hw.id:
        return jsonify({'message': '提交不存在'}), 404
    # v5.5：互评人可下载被评提交的附件（匿名评审所需）
    is_reviewer = HomeworkPeerReview.query.filter_by(
        submission_id=sub.id, reviewer_id=user.id).first() is not None
    if not (user.is_teacher() and hw.teacher_id == user.id) \
            and sub.student_id != user.id and not is_reviewer:
        return jsonify({'message': '无权下载该附件'}), 403
    att = sub.attachment_json or {}
    if not att.get('stored_name'):
        return jsonify({'message': '无附件'}), 404
    # v5.20 批注画布需内联显示图片/PDF：?inline=1 时不强制下载（mimetype 由扩展名推断）
    inline = request.args.get('inline', type=int) == 1
    if inline:
        return send_from_directory(_UPLOAD_DIR, att['stored_name'])
    return send_from_directory(_UPLOAD_DIR, att['stored_name'],
                               as_attachment=True, download_name=att.get('filename'))


# ═══════════════════════ 教师参考资料（上传/删除/下载）═══════════════════════

@homework_bp.route('/homeworks/<int:hw_id>/reference', methods=['POST'])
def api_reference_upload(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'message': '请选择文件'}), 400
    try:
        stored, size = _save_upload(f, 'hwref')
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    old = (hw.reference_json or {}).get('stored_name')
    if old and old != stored:   # 覆盖旧资料：清理磁盘文件，避免孤儿堆积
        try:
            os.remove(os.path.join(_UPLOAD_DIR, old))
        except OSError:
            pass
    hw.reference_json = {'filename': f.filename[:200], 'stored_name': stored, 'size': size,
                         'ext': os.path.splitext(f.filename)[1].lower()}
    db.session.commit()
    return jsonify({'message': '参考资料已上传', 'reference': hw.reference_meta(),
                    'homework': hw.to_dict(for_teacher=True)})


@homework_bp.route('/homeworks/<int:hw_id>/reference', methods=['DELETE'])
def api_reference_delete(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    old = (hw.reference_json or {}).get('stored_name')
    if old:
        try:
            os.remove(os.path.join(_UPLOAD_DIR, old))
        except OSError:
            pass
    hw.reference_json = None
    db.session.commit()
    return jsonify({'message': '参考资料已删除', 'homework': hw.to_dict(for_teacher=True)})


@homework_bp.route('/homeworks/<int:hw_id>/reference', methods=['GET'])
def api_reference_download(hw_id):
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw or hw.status == HomeworkStatusEnum.DRAFT:
        return jsonify({'message': '作业不存在'}), 404
    if not ((user.is_teacher() and hw.teacher_id == user.id) or _in_roster(hw, user.id)):
        return jsonify({'message': '无权下载该资料'}), 403
    ref = hw.reference_json or {}
    if not ref.get('stored_name'):
        return jsonify({'message': '无参考资料'}), 404
    return send_from_directory(_UPLOAD_DIR, ref['stored_name'], as_attachment=True,
                               download_name=ref.get('filename'))


# ═══════════════════════ v5.4 作业讨论区 ═══════════════════════

def _can_access_discussion(hw, user):
    """讨论区参与者：创建教师 + 发布名单学生。"""
    return (user.is_teacher() and hw.teacher_id == user.id) or bool(_in_roster(hw, user.id))


def _discuss_homework(user, hw_id):
    """取作业并校验讨论区访问权；返回 (hw, is_owner_teacher, error_response)。"""
    hw = db.session.get(Homework, hw_id)
    if not hw:
        return None, False, (jsonify({'message': '作业不存在'}), 404)
    owner_teacher = bool(user.is_teacher() and hw.teacher_id == user.id)
    if not owner_teacher:
        if hw.status == HomeworkStatusEnum.DRAFT or not _in_roster(hw, user.id):
            return None, False, (jsonify({'message': '作业不存在或未对你开放'}), 404)
    if not _can_access_discussion(hw, user):
        return None, False, (jsonify({'message': '无权参与该作业讨论'}), 403)
    return hw, owner_teacher, None


@homework_bp.route('/homeworks/<int:hw_id>/comments', methods=['GET'])
def api_comments(hw_id):
    user, err = require_login()
    if err:
        return err
    hw, owner_teacher, err = _discuss_homework(user, hw_id)
    if err:
        return err
    question_id = request.args.get('question_id', type=int)
    page = max(request.args.get('page', 1, type=int) or 1, 1)
    page_size = min(max(request.args.get('page_size', 20, type=int) or 20, 1), 50)
    q = HomeworkComment.query.filter_by(homework_id=hw.id, parent_id=None)
    if question_id:
        q = q.filter_by(question_id=question_id)
    total = q.count()
    tops = (q.order_by(HomeworkComment.created_at.desc(), HomeworkComment.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    ids = [c.id for c in tops]
    replies = (HomeworkComment.query
               .filter(HomeworkComment.parent_id.in_(ids))
               .order_by(HomeworkComment.created_at.asc(), HomeworkComment.id.asc()).all()
               ) if ids else []
    reply_map = {}
    for r in replies:
        reply_map.setdefault(r.parent_id, []).append(r)
    items = []
    for c in tops:
        d = c.to_dict(current_user_id=user.id, for_teacher=owner_teacher)
        d['replies'] = [r.to_dict(current_user_id=user.id, for_teacher=owner_teacher)
                        for r in reply_map.get(c.id, [])]
        items.append(d)
    return jsonify({'items': items, 'total': total, 'page': page, 'page_size': page_size,
                    'can_moderate': owner_teacher, 'is_teacher': owner_teacher})


@homework_bp.route('/homeworks/<int:hw_id>/comments', methods=['POST'])
def api_comment_create(hw_id):

    user, err = require_login()
    if err:
        return err
    hw, owner_teacher, err = _discuss_homework(user, hw_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    content = str(data.get('content') or '').strip()
    if not content:
        return jsonify({'message': '评论内容不能为空'}), 400
    if len(content) > 2000:
        return jsonify({'message': '评论内容不能超过 2000 字'}), 400

    question_id = data.get('question_id')
    if question_id not in (None, ''):
        try:
            question_id = int(question_id)
        except (TypeError, ValueError):
            return jsonify({'message': 'question_id 须为整数'}), 400
        if question_id not in {hq.question_id for hq in hw.hw_questions}:
            return jsonify({'message': '该题目不属于本次作业'}), 400
    else:
        question_id = None

    parent = None
    parent_id = data.get('parent_id')
    if parent_id not in (None, ''):
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return jsonify({'message': 'parent_id 须为整数'}), 400
        parent = db.session.get(HomeworkComment, parent_id)
        if not parent or parent.homework_id != hw.id:
            return jsonify({'message': '回复的评论不存在'}), 404
        if parent.deleted_at:
            return jsonify({'message': '该评论已删除，无法回复'}), 400
        if parent.parent_id:   # 二层以上扁平化到主楼
            parent = db.session.get(HomeworkComment, parent.parent_id)
        parent_id = parent.id
        question_id = parent.question_id

    c = HomeworkComment(homework_id=hw.id, question_id=question_id,
                        parent_id=parent_id, user_id=user.id, content=content,
                        is_teacher=owner_teacher)
    db.session.add(c)
    db.session.flush()

    if parent and parent.user_id != user.id:
        create_notification(parent.user_id, '作业讨论有新回复',
                            f'《{hw.title}》{user.username} 回复了你：{content[:60]}',
                            related_type='homework', related_id=hw.id, commit=False)
    elif parent is None and not owner_teacher:
        create_notification(hw.teacher_id, '作业讨论有新提问',
                            f'《{hw.title}》{user.username}：{content[:60]}',
                            related_type='homework', related_id=hw.id, commit=False)
    db.session.commit()
    return jsonify(c.to_dict(current_user_id=user.id, for_teacher=owner_teacher)), 201


@homework_bp.route('/homeworks/<int:hw_id>/comments/<int:cid>', methods=['DELETE'])
def api_comment_delete(hw_id, cid):
    user, err = require_login()
    if err:
        return err
    hw, owner_teacher, err = _discuss_homework(user, hw_id)
    if err:
        return err
    c = db.session.get(HomeworkComment, cid)
    if not c or c.homework_id != hw.id:
        return jsonify({'message': '评论不存在'}), 404
    if c.user_id != user.id and not owner_teacher:
        return jsonify({'message': '只能删除自己的评论'}), 403
    if not c.deleted_at:
        c.deleted_at = utcnow()
        db.session.commit()
    return jsonify({'message': '已删除'})


# ═══════════════════════ v5.5 生生互评 ═══════════════════════

@homework_bp.route('/homeworks/<int:hw_id>/peer_reviews/distribute', methods=['POST'])
def api_peer_distribute(hw_id):

    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    if hw.status == HomeworkStatusEnum.DRAFT:
        return jsonify({'message': '请先发布作业再发起互评'}), 400
    data = request.get_json(silent=True) or {}
    result = distribute_peer_reviews(hw, data.get('per_submission', 2))
    if result.get('error'):
        db.session.rollback()
        return jsonify({'message': result['error']}), 400
    for reviewer_id, count in result['reviewers'].items():
        create_notification(reviewer_id, '作业互评任务',
                            f'《{hw.title}》你收到 {count} 份同学作业待互评，请客观打分并给出建议。',
                            related_type='homework', related_id=hw.id, commit=False)
    db.session.commit()
    return jsonify({'message': f'已分配 {result["created"]} 份互评任务',
                    'created': result['created'],
                    'submitted_kept': result['submitted_kept'],
                    'summary': peer_review_summary(hw)})


@homework_bp.route('/homeworks/<int:hw_id>/peer_reviews', methods=['GET'])
def api_peer_summary(hw_id):
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    return jsonify(peer_review_summary(hw))


@homework_bp.route('/homeworks/peer_reviews/mine', methods=['GET'])
def api_peer_mine():
    user, err = require_login()
    if err:
        return err
    rows = (HomeworkPeerReview.query.filter_by(reviewer_id=user.id)
            .order_by(HomeworkPeerReview.id.desc()).all())
    items = []
    for r in rows:
        hw = r.homework
        if not hw or hw.status == HomeworkStatusEnum.DRAFT:
            continue
        items.append({'review': r.to_dict(),
                      'homework': {'id': hw.id, 'title': hw.title, 'hw_type': hw.hw_type,
                                   'teacher_name': hw.teacher.username if hw.teacher else '',
                                   'peer_review_deadline': iso_local(hw.peer_review_deadline)
                                   if hw.peer_review_deadline else None,
                                   'peer_review_weight': float(hw.peer_review_weight or 0.0)}})
    pending = sum(1 for i in items if i['review']['status'] == PeerReviewStatusEnum.PENDING)
    submitted = sum(1 for i in items if i['review']['status'] == PeerReviewStatusEnum.SUBMITTED)
    return jsonify({'items': items, 'pending_count': pending, 'submitted_count': submitted,
                    'dimensions': peer_review_dimensions()})


def _get_my_review(user, hw_id, review_id):
    review = db.session.get(HomeworkPeerReview, review_id)
    if not review or review.homework_id != hw_id:
        return None, (jsonify({'message': '互评任务不存在'}), 404)
    if review.reviewer_id != user.id:
        return None, (jsonify({'message': '无权查看该互评任务'}), 403)
    return review, None


@homework_bp.route('/homeworks/<int:hw_id>/peer_reviews/<int:review_id>', methods=['GET'])
def api_peer_detail(hw_id, review_id):
    user, err = require_login()
    if err:
        return err
    review, err = _get_my_review(user, hw_id, review_id)
    if err:
        return err
    hw = review.homework
    sub = review.submission
    if not hw or not sub:
        return jsonify({'message': '互评任务数据不完整'}), 404
    sub_payload = {'id': sub.id, 'version': sub.version, 'is_late': bool(sub.is_late),
                   'submitted_at': iso_local(sub.submitted_at) if sub.submitted_at else None,
                   'content': sub.content or '', 'attachment': sub.attachment_meta()}
    questions = []
    if hw.hw_type == HomeworkTypeEnum.QUESTION_SET:
        amap = {a.question_id: a for a in sub.answers}
        for hq in sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id)):
            qd = _question_payload(hq, False)
            a = amap.get(hq.question_id)
            qd['peer_answer'] = (a.answer or '') if a else ''
            questions.append(qd)
    return jsonify({'review': review.to_dict(), 'homework': hw.to_dict(),
                    'submission': sub_payload, 'questions': questions,
                    'dimensions': peer_review_dimensions()})


@homework_bp.route('/homeworks/<int:hw_id>/peer_reviews/<int:review_id>', methods=['POST'])
def api_peer_submit(hw_id, review_id):

    user, err = require_login()
    if err:
        return err
    review, err = _get_my_review(user, hw_id, review_id)
    if err:
        return err
    hw = review.homework
    if not hw or hw.status == HomeworkStatusEnum.DRAFT:
        return jsonify({'message': '作业未开放'}), 404
    if review.status != PeerReviewStatusEnum.PENDING:
        return jsonify({'message': '该互评已提交，不可重复提交'}), 400
    if hw.peer_review_deadline and utcnow() > hw.peer_review_deadline:
        return jsonify({'message': '互评已截止，无法提交'}), 400
    data = request.get_json(silent=True) or {}
    # v5.9 多维度评分：传 scores 则按维度权重折算；兼容旧的单一 score
    dim_scores = _clean_dimension_scores(data.get('scores'))
    final_score = compute_peer_final_score(dim_scores)
    if final_score is None:
        try:
            final_score = float(data.get('score'))
        except (TypeError, ValueError):
            return jsonify({'message': '请至少为 1 个维度打分（0~100）'}), 400
        if final_score < 0 or final_score > 100:
            return jsonify({'message': '评分须在 0~100 之间'}), 400
        final_score = round(final_score, 2)
        dim_scores = {}
    comment = str(data.get('comment') or '').strip()
    if len(comment) > 2000:
        return jsonify({'message': '评语不能超过 2000 字'}), 400
    review.score = final_score
    review.scores_json = dim_scores or None
    review.comment = comment
    review.status = PeerReviewStatusEnum.SUBMITTED
    review.submitted_at = utcnow()
    complete_peer_review_daily_task(hw, user.id)
    create_notification(hw.teacher_id, '作业互评已提交',
                        f'《{hw.title}》{user.username} 完成 1 份同学互评。',
                        related_type='homework', related_id=hw.id, commit=False)
    db.session.commit()
    return jsonify(review.to_dict())


@homework_bp.route('/homeworks/<int:hw_id>/peer_reviews/settings', methods=['PUT'])
def api_peer_settings(hw_id):
    """教师设置互评截止时间与互评分权重（0~1，0=不计入总分视图）。"""
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if 'deadline' in data:
        deadline = parse_dt(data.get('deadline'))
        hw.peer_review_deadline = deadline
        hw.peer_review_reminded_at = None  # 修改截止时间后允许重新催办
    if 'weight' in data:
        try:
            weight = float(data.get('weight') or 0)
        except (TypeError, ValueError):
            return jsonify({'message': '权重须为 0~1 的数字'}), 400
        if not 0.0 <= weight <= 1.0:
            return jsonify({'message': '权重须在 0~1 之间'}), 400
        hw.peer_review_weight = round(weight, 4)
    db.session.commit()
    return jsonify({'message': '互评设置已保存',
                    'homework': hw.to_dict(for_teacher=True),
                    'summary': peer_review_summary(hw)})


@homework_bp.route('/homeworks/<int:hw_id>/peer_reviews/<int:review_id>/audit',
                   methods=['POST'])
def api_peer_audit(hw_id, review_id):
    """教师审核互评：采纳（计入加权分）/ 驳回。"""

    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    review = db.session.get(HomeworkPeerReview, review_id)
    if not review or review.homework_id != hw.id:
        return jsonify({'message': '互评记录不存在'}), 404
    data = request.get_json(silent=True) or {}
    result = audit_peer_review(review, str(data.get('action') or ''),
                               comment=data.get('comment') or '', teacher_id=user.id)
    if result.get('error'):
        db.session.rollback()
        return jsonify({'message': result['error']}), 400
    accepted = review.audit_status == PeerReviewAuditEnum.ACCEPTED
    create_notification(review.reviewer_id,
                        '互评审核结果',
                        f'《{hw.title}》你的互评已被教师{"采纳" if accepted else "驳回"}。'
                        + (f'教师意见：{review.teacher_comment}' if review.teacher_comment else ''),
                        type='info', related_type='homework', related_id=hw.id,
                        commit=False)
    db.session.commit()
    return jsonify({'message': '已采纳' if accepted else '已驳回',
                    'review': review.to_dict(for_teacher=True),
                    'summary': peer_review_summary(hw)})


# ═══════════════════════ v5.6 作业反抄袭 ═══════════════════════

@homework_bp.route('/homeworks/<int:hw_id>/plagiarism', methods=['GET'])
@limiter.limit('20/minute')
def api_homework_plagiarism(hw_id):
    """作业级查重：题集式编程题复用 oj.plagiarism，开放式文字走字符 n-gram。

    query: threshold 相似度阈值（默认 0.7）。仅作复核线索。
    """
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    try:
        threshold = float(request.args.get('threshold', 0.7))
    except (TypeError, ValueError):
        return jsonify({'message': 'threshold 须为 0~1 的数值'}), 400
    if not 0.0 <= threshold <= 1.0:
        return jsonify({'message': 'threshold 须为 0~1 的数值'}), 400
    result = homework_plagiarism_check(hw, threshold=threshold)
    return jsonify({'homework_id': hw.id, 'threshold': threshold, **result})


# ═══════════════════════ v5.8 作业模板与系列化 ═══════════════════════

def _get_own_template(user, tid):
    t = db.session.get(HomeworkTemplate, tid)
    if not t or t.teacher_id != user.id:
        return None, (jsonify({'message': '模板不存在'}), 404)
    return t, None


@homework_bp.route('/homeworks/templates', methods=['GET'])
def api_template_list():
    user, err = require_teacher()
    if err:
        return err
    items = HomeworkTemplate.query.filter_by(teacher_id=user.id) \
        .order_by(HomeworkTemplate.updated_at.desc()).all()
    return jsonify({'items': [t.to_dict() for t in items]})


@homework_bp.route('/homeworks/templates/preview', methods=['POST'])
@limiter.limit('20/minute')
def api_template_preview():
    """抽题预览：按当前配置试抽一次，返回题目、难度分布与题库可用量。"""
    user, err = require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    config = data.get('config') or {}
    filters = config.get('filters') or {}
    if not filters.get('major_id'):
        return jsonify({'message': '请先选择专业'}), 400
    try:
        config['count'] = max(1, min(int(config.get('count') or 5), 50))
    except (TypeError, ValueError):
        return jsonify({'message': '抽题数量须为 1~50 的整数'}), 400
    distribution = config.get('distribution')
    if distribution:
        if not isinstance(distribution, list):
            return jsonify({'message': '难度分布格式不正确'}), 400
        for slot in distribution:
            try:
                if int(slot.get('count', 0)) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({'message': '难度分布数量须为非负整数'}), 400
    result = preview_template_questions(config)
    if not result['pool_total']:
        return jsonify({'message': '当前条件下题库没有匹配题目', **result}), 200
    return jsonify(result)


@homework_bp.route('/homeworks/templates', methods=['POST'])
@limiter.limit('6/minute')
def api_template_create():
    user, err = require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '模板标题不能为空'}), 400
    t = HomeworkTemplate(teacher_id=user.id, title=title[:200],
                         description=(data.get('description') or '')[:2000],
                         config_json=data.get('config') or {},
                         settings_json=data.get('settings') or {},
                         roster_json=data.get('roster') or [])
    db.session.add(t)
    db.session.commit()
    return jsonify({'message': '模板已创建', 'template': t.to_dict()}), 201


@homework_bp.route('/homeworks/templates/<int:tid>', methods=['GET'])
def api_template_detail(tid):
    user, err = require_teacher()
    if err:
        return err
    t, err = _get_own_template(user, tid)
    if err:
        return err
    return jsonify({'template': t.to_dict()})


@homework_bp.route('/homeworks/templates/<int:tid>', methods=['PUT'])
def api_template_update(tid):
    user, err = require_teacher()
    if err:
        return err
    t, err = _get_own_template(user, tid)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        t.title = (data.get('title') or t.title).strip()[:200]
    if 'description' in data:
        t.description = (data.get('description') or '')[:2000]
    if 'config' in data:
        t.config_json = data.get('config') or {}
    if 'settings' in data:
        t.settings_json = data.get('settings') or {}
    if 'roster' in data:
        t.roster_json = data.get('roster') or []
    db.session.commit()
    return jsonify({'message': '已更新', 'template': t.to_dict()})


@homework_bp.route('/homeworks/templates/<int:tid>', methods=['DELETE'])
def api_template_delete(tid):
    user, err = require_teacher()
    if err:
        return err
    t, err = _get_own_template(user, tid)
    if err:
        return err
    # 若有系列在用，拒绝删除
    if HomeworkSeries.query.filter_by(template_id=t.id).first():
        return jsonify({'message': '该模板被作业系列引用，无法删除'}), 400
    db.session.delete(t)
    db.session.commit()
    return jsonify({'message': '已删除'})


@homework_bp.route('/homeworks/templates/<int:tid>/generate', methods=['POST'])
def api_template_generate(tid):
    """从模板立即生成一份作业草稿（手动，不关联系列）。"""
    user, err = require_teacher()
    if err:
        return err
    t, err = _get_own_template(user, tid)
    if err:
        return err
    hw, err = generate_homework_from_template(t, user.id, publish=False)
    if err:
        return jsonify({'message': err}), 400
    return jsonify({'message': '已生成作业草稿', 'homework': hw.to_dict(for_teacher=True)}), 201


# ── 作业系列 ──

def _get_own_series(user, sid):
    s = db.session.get(HomeworkSeries, sid)
    if not s or s.teacher_id != user.id:
        return None, (jsonify({'message': '系列不存在'}), 404)
    return s, None


@homework_bp.route('/homeworks/series', methods=['GET'])
def api_series_list():
    user, err = require_teacher()
    if err:
        return err
    items = HomeworkSeries.query.filter_by(teacher_id=user.id) \
        .order_by(HomeworkSeries.created_at.desc()).all()
    return jsonify({'items': [s.to_dict() for s in items]})


@homework_bp.route('/homeworks/series', methods=['POST'])
@limiter.limit('3/minute')
def api_series_create():
    user, err = require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    template_id = data.get('template_id')
    t = db.session.get(HomeworkTemplate, template_id)
    if not t or t.teacher_id != user.id:
        return jsonify({'message': '模板不存在'}), 404
    title = (data.get('title') or t.title).strip()[:200]
    start_at = parse_dt(data.get('start_at'))
    if not start_at:
        return jsonify({'message': '请指定首次发布时间'}), 400
    try:
        count = max(1, min(int(data.get('count', 5)), 30))
    except (TypeError, ValueError):
        count = 5
    try:
        interval_hours = max(1, int(data.get('interval_hours', 24)))
    except (TypeError, ValueError):
        interval_hours = 24
    s = HomeworkSeries(teacher_id=user.id, template_id=t.id, title=title,
                       description=(data.get('description') or '')[:2000],
                       start_at=start_at, interval_hours=interval_hours, count=count)
    db.session.add(s)
    db.session.commit()
    return jsonify({'message': '系列已创建（达到首次发布时间后自动生成作业）',
                    'series': s.to_dict()}), 201


@homework_bp.route('/homeworks/series/<int:sid>', methods=['GET'])
def api_series_detail(sid):
    user, err = require_teacher()
    if err:
        return err
    s, err = _get_own_series(user, sid)
    if err:
        return err
    return jsonify({'series': s.to_dict(include_homeworks=True)})


@homework_bp.route('/homeworks/series/<int:sid>', methods=['DELETE'])
def api_series_delete(sid):
    user, err = require_teacher()
    if err:
        return err
    s, err = _get_own_series(user, sid)
    if err:
        return err
    # 停止生成，已生成的作业保留
    s.status = HomeworkSeriesStatusEnum.PAUSED
    db.session.commit()
    return jsonify({'message': '系列已停止（已生成的作业保留）'})


@homework_bp.route('/homeworks/series/<int:sid>/start', methods=['POST'])
def api_series_start(sid):
    """手动启动系列（草稿→进行中），到达计划时间后由调度器生成。"""
    user, err = require_teacher()
    if err:
        return err
    s, err = _get_own_series(user, sid)
    if err:
        return err
    if s.status not in (HomeworkSeriesStatusEnum.DRAFT, HomeworkSeriesStatusEnum.PAUSED):
        return jsonify({'message': f'当前状态 {s.status} 不可启动'}), 400
    s.status = HomeworkSeriesStatusEnum.ACTIVE
    db.session.commit()
    return jsonify({'message': '系列已启动', 'series': s.to_dict()})


@homework_bp.route('/homeworks/series/<int:sid>/generate_now', methods=['POST'])
def api_series_generate_now(sid):
    """手动立即生成下一份作业（不等待计划时间）。"""
    user, err = require_teacher()
    if err:
        return err
    s, err = _get_own_series(user, sid)
    if err:
        return err
    if s.generated_count >= s.count:
        return jsonify({'message': '该系列已全部生成完毕'}), 400
    idx = s.generated_count
    hw, err = generate_homework_from_template(
        s.template, s.teacher_id, index=idx, publish=True, series_id=s.id)
    if err:
        return jsonify({'message': err}), 400
    s.generated_count += 1
    if s.generated_count >= s.count:
        s.status = HomeworkSeriesStatusEnum.COMPLETED
    db.session.commit()
    return jsonify({'message': f'第 {idx + 1}/{s.count} 份已生成',
                    'homework': hw.to_dict(for_teacher=True)}), 201


# ── 学生：本周作业清单 ──

@homework_bp.route('/homeworks/weekly', methods=['GET'])
def api_weekly_homeworks():
    """学生本周作业清单：按发布时间聚合，供「我的本周作业」视图。"""
    user, err = require_login()
    if err:
        return err
    from datetime import datetime, timedelta
    # week_start：本周一 00:00（本地）
    now = utcnow()
    weekday = now.weekday()  # 周一=0
    week_start = (now - timedelta(days=weekday)).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    # 取本周内发布的、在名单中的作业
    hws = Homework.query.join(HomeworkStudent, HomeworkStudent.homework_id == Homework.id) \
        .filter(HomeworkStudent.student_id == user.id,
                Homework.status == HomeworkStatusEnum.PUBLISHED,
                Homework.published_at >= week_start,
                Homework.published_at < week_end).all()
    items = []
    for hw in hws:
        sub = _my_submission(hw, user.id)
        items.append({
            'id': hw.id, 'title': hw.title, 'hw_type': hw.hw_type,
            'teacher_name': hw.teacher.username if hw.teacher else '',
            'has_deadline': hw.deadline is not None,
            'published_at': iso_local(hw.published_at),
            'deadline': iso_local(hw.deadline) if hw.deadline else None,
            'is_expired': hw.is_expired,
            'submitted': sub is not None and sub.status in (
                SubmissionStatusEnum.SUBMITTED, SubmissionStatusEnum.GRADED),
            'graded': sub is not None and sub.status == SubmissionStatusEnum.GRADED,
            'total_score': sub.total_score if sub and sub.status == SubmissionStatusEnum.GRADED else None,
            'series_id': hw.series_id,
        })
    return jsonify({'week_start': iso_local(week_start),
                    'week_end': iso_local(week_end),
                    'items': items})


@homework_bp.route('/homeworks/center', methods=['GET'])
@limiter.limit('60/minute')
def api_homework_center():
    """v5.13 作业中心/待办看板（学生）：跨本人相关全部作业（发布名单含小组）的只读聚合。

    每项返回 `{id,title,hw_type,deadline,has_deadline,status_of_me,days_left,total_score,max_score,
    is_late,can_submit}`，按「待交且临近截止」优先排序（待交→待批→已批，组内按剩余天数升序）。
    另附 `score_trend`（历次已批作业得分率序列）与 `stats`（待交/临近截止/待批/已批 计数）。
    不改判分与成绩口径（分数口径与 `to_dict` 一致：仅已批改可见总分）。"""
    user, err = require_login()
    if err:
        return err
    if user.is_teacher():
        return jsonify({'message': '作业中心仅对学生开放'}), 403
    now = utcnow()
    hws = (Homework.query.join(HomeworkStudent, HomeworkStudent.homework_id == Homework.id)
           .filter(HomeworkStudent.student_id == user.id,
                   Homework.status != HomeworkStatusEnum.DRAFT).all())
    items = []
    trend_src = []
    for hw in hws:
        sub = _my_submission(hw, user.id)
        if sub is None or sub.status == SubmissionStatusEnum.DRAFT:
            status_me = 'unsubmitted'
        elif sub.status == SubmissionStatusEnum.SUBMITTED:
            status_me = 'submitted'
        elif sub.status == SubmissionStatusEnum.RETURNED:
            status_me = 'returned'
        else:
            status_me = 'graded'
        days_left = (round((hw.deadline - now).total_seconds() / 86400.0, 2)
                     if hw.deadline else None)
        max_sc = (sub.max_score if (sub and sub.max_score is not None) else hw.max_score())
        can_submit = (status_me == 'unsubmitted'
                      and (hw.deadline is None or hw.deadline >= now or bool(hw.allow_late))
                      and hw.status == HomeworkStatusEnum.PUBLISHED)
        # v5.17 退回订正：教师已授权重交，不受截止限制
        if status_me == 'returned' and hw.status == HomeworkStatusEnum.PUBLISHED:
            can_submit = True
        # v5.14 多种评分制：显示层派生（不改 total_score 数值口径，仅影响呈现）
        gmode = (getattr(hw, 'grade_mode', 'numeric') or 'numeric')
        gdisp = None
        if status_me in ('graded', 'returned') and sub:
            if gmode == 'level':
                ratio = (sub.total_score / max_sc) if (max_sc and sub.total_score is not None) else None
                gdisp = hw.level_for_ratio(ratio) if ratio is not None else None
            elif gmode == 'comment':
                gdisp = sub.comment or ''
            else:
                gdisp = sub.total_score
        vis_total = (None if (gmode == 'comment' and status_me in ('graded', 'returned'))
                     else (sub.total_score if status_me in ('graded', 'returned') else None))
        items.append({'id': hw.id, 'title': hw.title, 'hw_type': str(hw.hw_type),
                      'teacher_name': hw.teacher.username if hw.teacher else '',
                      'deadline': iso_local(hw.deadline) if hw.deadline else None,
                      'has_deadline': hw.deadline is not None,
                      'is_expired': bool(hw.is_expired), 'allow_late': bool(hw.allow_late),
                      'status_of_me': status_me, 'days_left': days_left,
                      'total_score': vis_total,
                      'grade_mode': gmode, 'grade_display': gdisp,
                      'max_score': max_sc,
                      'is_late': bool(sub.is_late) if sub else False,
                      'can_submit': can_submit, 'sub_id': sub.id if sub else None})
        if status_me == 'graded' and sub and sub.total_score is not None:
            trend_src.append({'homework_id': hw.id, 'title': hw.title,
                              'total_score': sub.total_score, 'max_score': max_sc,
                              'graded_at': sub.graded_at})
    items.sort(key=lambda it: ({'unsubmitted': 0, 'returned': 1, 'submitted': 2, 'graded': 3}[it['status_of_me']],
                                it['days_left'] if it['days_left'] is not None else float('inf')))
    stats = {'unsubmitted': sum(1 for it in items if it['status_of_me'] == 'unsubmitted'),
             'returned': sum(1 for it in items if it['status_of_me'] == 'returned'),
             'submitted': sum(1 for it in items if it['status_of_me'] == 'submitted'),
             'graded': sum(1 for it in items if it['status_of_me'] == 'graded'),
             'due_soon': sum(1 for it in items if it['status_of_me'] == 'unsubmitted'
                             and it['days_left'] is not None and 0 <= it['days_left'] <= 3)}
    trend_src.sort(key=lambda x: x['graded_at'] or now)
    score_trend = [{'homework_id': t['homework_id'], 'title': t['title'],
                    'total_score': t['total_score'], 'max_score': t['max_score'],
                    'ratio': (round(t['total_score'] / t['max_score'], 4) if t['max_score'] else None),
                    'graded_at': iso_local(t['graded_at']) if t['graded_at'] else None}
                   for t in trend_src]
    return jsonify({'items': items, 'total': len(items), 'stats': stats,
                    'score_trend': score_trend})


# ════════════════════ v5.15 评分量规 Rubric 库（教师可复用） ════════════════════

@homework_bp.route('/homeworks/rubrics', methods=['GET'])
def api_rubric_list():
    user, err = require_teacher()
    if err:
        return err
    rows = (HomeworkRubric.query.filter_by(teacher_id=user.id)
            .order_by(HomeworkRubric.id.desc()).all())
    items = []
    for rb in rows:
        d = rb.to_dict()
        d['homework_count'] = Homework.query.filter_by(rubric_id=rb.id).count()
        items.append(d)
    return jsonify({'items': items, 'total': len(items)})


@homework_bp.route('/homeworks/rubrics', methods=['POST'])
def api_rubric_create():
    user, err = require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    title = str(data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '量规标题不能为空'}), 400
    dims, derr = _clean_rubric_dimensions(data.get('dimensions'))
    if derr:
        return jsonify({'message': derr}), 400
    rb = HomeworkRubric(teacher_id=user.id, title=title[:200],
                        description=str(data.get('description') or '')[:2000],
                        dimensions_json=dims)
    db.session.add(rb)
    db.session.commit()
    return jsonify({'message': '已创建', 'rubric': rb.to_dict()}), 201


@homework_bp.route('/homeworks/rubrics/<int:rid>', methods=['GET'])
def api_rubric_detail(rid):
    user, err = require_teacher()
    if err:
        return err
    rb = db.session.get(HomeworkRubric, rid)
    if not rb or rb.teacher_id != user.id:
        return jsonify({'message': '量规不存在'}), 404
    return jsonify(rb.to_dict())


@homework_bp.route('/homeworks/rubrics/<int:rid>', methods=['PUT'])
def api_rubric_update(rid):
    user, err = require_teacher()
    if err:
        return err
    rb = db.session.get(HomeworkRubric, rid)
    if not rb or rb.teacher_id != user.id:
        return jsonify({'message': '量规不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        title = str(data.get('title') or '').strip()
        if not title:
            return jsonify({'message': '量规标题不能为空'}), 400
        rb.title = title[:200]
    if 'description' in data:
        rb.description = str(data.get('description') or '')[:2000]
    if 'dimensions' in data:
        dims, derr = _clean_rubric_dimensions(data.get('dimensions'))
        if derr:
            return jsonify({'message': derr}), 400
        rb.dimensions_json = dims
    db.session.commit()
    return jsonify({'message': '已保存', 'rubric': rb.to_dict()})


@homework_bp.route('/homeworks/rubrics/<int:rid>', methods=['DELETE'])
def api_rubric_delete(rid):
    user, err = require_teacher()
    if err:
        return err
    rb = db.session.get(HomeworkRubric, rid)
    if not rb or rb.teacher_id != user.id:
        return jsonify({'message': '量规不存在'}), 404
    # 解除引用：引用该量规的作业 rubric_id 置空（已存子提交 rubric_scores 保留供留档）
    for hw in Homework.query.filter_by(rubric_id=rb.id).all():
        hw.rubric_id = None
    db.session.delete(rb)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ═══════════════ v5.16 作答防作弊监测（只记不拦，不强制交卷）═══════════════

@homework_bp.route('/homeworks/<int:hw_id>/proctor', methods=['POST'])
@limiter.limit('60/minute')
def api_proctor_report(hw_id):
    """学生作答监测上报：记录一条异常行为事件（tab_switch|blur|paste|copy）。

    仅当作业开启 enable_monitor 时落库；未开启则空操作（不影响作答）。
    与考试不同：只记录、不强制交卷、不影响判分。无提交时先建 DRAFT 承载事件。
    """
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw or not _in_roster(hw, user.id):
        return jsonify({'message': '作业不存在或未对你发布'}), 404
    if hw.status != HomeworkStatusEnum.PUBLISHED:
        return jsonify({'message': '作业未发布'}), 400
    if not hw.enable_monitor:
        return jsonify({'message': '本作业未开启监测', 'recorded': 0}), 200
    data = request.get_json(silent=True) or {}
    etype = str(data.get('type') or '').strip().lower()
    if etype not in ProctorEventTypeEnum.ALL:
        return jsonify({'message': '非法事件类型'}), 400
    sub = _my_submission(hw, user.id)
    if sub is None:
        sub = HomeworkSubmission(homework_id=hw.id, student_id=user.id,
                                 status=SubmissionStatusEnum.DRAFT)
        if hw.is_group:
            grp = get_student_group(hw, user.id)
            if grp:
                sub.group_id = grp.id
        db.session.add(sub)
        db.session.flush()
    db.session.add(HomeworkProctorEvent(homework_id=hw.id, submission_id=sub.id,
                                        student_id=user.id, type=etype, at=utcnow()))
    db.session.commit()
    return jsonify({'message': '已记录', 'recorded': 1}), 201


@homework_bp.route('/homeworks/<int:hw_id>/monitor', methods=['GET'])
def api_monitor(hw_id):
    """教师监测看板：逐生聚合异常事件计数/时间线（按总数降序）。"""
    user, err = require_teacher()
    if err:
        return err
    hw, err = _get_own_homework(user, hw_id)
    if err:
        return err
    events = (HomeworkProctorEvent.query.filter_by(homework_id=hw.id)
              .order_by(HomeworkProctorEvent.at.asc()).all())
    by_student = {}
    for ev in events:
        rec = by_student.setdefault(ev.student_id, {
            'student_id': ev.student_id,
            'username': ev.student.username if ev.student else None,
            'counts': {t: 0 for t in ProctorEventTypeEnum.ALL},
            'total': 0, 'timeline': []})
        rec['counts'][ev.type] = rec['counts'].get(ev.type, 0) + 1
        rec['total'] += 1
        rec['timeline'].append({'type': ev.type, 'at': iso_local(ev.at)})
    students = sorted(by_student.values(), key=lambda x: x['total'], reverse=True)
    return jsonify({
        'homework': {'id': hw.id, 'title': hw.title, 'status': hw.status,
                     'enable_monitor': bool(hw.enable_monitor)},
        'summary': {'students_with_events': len(students), 'total_events': len(events)},
        'event_types': list(ProctorEventTypeEnum.ALL),
        'students': students,
    })


