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
from utils.permissions import require_teacher, require_login
from utils.security import limiter
from utils.timeutil import utcnow, iso_local, parse_dt
from competition.routes import _UPLOAD_DIR, _save_upload
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkAnswer,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from homework.services import (
    finalize_submission, recompute_total, notify_homework_students, ai_suggest_grading,
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
    return HomeworkStudent.query.filter_by(homework_id=hw.id, student_id=user_id).first()


def _my_submission(hw, user_id):
    return HomeworkSubmission.query.filter_by(homework_id=hw.id, student_id=user_id).first()


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
    for flag in ('allow_late', 'allow_resubmit'):
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
        return jsonify(d)
    if hw.status == HomeworkStatusEnum.DRAFT or not _in_roster(hw, user.id):
        return jsonify({'message': '作业不存在或未对你开放'}), 404
    d = hw.to_dict()
    if hw.hw_type == HomeworkTypeEnum.QUESTION_SET:
        d['questions'] = [_question_payload(hq, False) for hq in
                          sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))]
    sub = _my_submission(hw, user.id)
    d['my_submission'] = sub.to_dict() if sub else None
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
            msg = _apply_roster(hw, data['student_ids'])
            if msg:
                return jsonify({'message': msg}), 400
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

    hw.status = HomeworkStatusEnum.PUBLISHED
    hw.published_at = utcnow()
    hw.reminded_at = None
    title = '新作业发布'
    due_txt = f'截止 {iso_local(hw.deadline)}' if hw.deadline else '无截止时间（随到随做）'
    content = f'老师发布了作业《{hw.title}》，{due_txt}，请及时完成。'
    n = notify_homework_students(hw, title, content)
    db.session.commit()
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


@homework_bp.route('/homeworks/<int:hw_id>/urge', methods=['POST'])
@limiter.limit('30/min')
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
    label = {SubmissionStatusEnum.SUBMITTED: '待批改', SubmissionStatusEnum.GRADED: '已批改'}
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
                   pass_score=hw.pass_score)
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
    payload = {'homework': hw.to_dict(), 'editable': hw.accepts_submission and
               (sub is None or sub.status == SubmissionStatusEnum.DRAFT or
                (not hw.is_expired and hw.allow_resubmit and sub.status == SubmissionStatusEnum.SUBMITTED))}
    if hw.hw_type == HomeworkTypeEnum.QUESTION_SET:
        payload['questions'] = [_question_payload(hq, False) for hq in
                                sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))]
        payload['answers'] = ({str(a.question_id): a.answer for a in sub.answers} if sub else {})
    else:
        payload['content'] = (sub.content if sub else '')
        payload['attachment'] = sub.attachment_meta() if sub else None
    if sub:
        payload['submission'] = sub.to_dict()
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
    if not hw.accepts_submission:
        return jsonify({'message': '已过截止时间'}), 400
    sub = _my_submission(hw, user.id)
    if sub and sub.status == SubmissionStatusEnum.GRADED:
        return jsonify({'message': '已批改完成，不可再修改'}), 400
    if sub is None:
        sub = HomeworkSubmission(homework_id=hw.id, student_id=user.id,
                                 status=SubmissionStatusEnum.DRAFT)
        db.session.add(sub)
        db.session.flush()
    data = request.get_json(silent=True) or {}
    hq_map = {hq.question_id: hq for hq in hw.hw_questions}
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
        a.answer = str(text if text is not None else '')[:50000]
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


@homework_bp.route('/homeworks/<int:hw_id>/submit', methods=['POST'])
@limiter.limit('20/min')
def api_submit(hw_id):
    user, err = require_login()
    if err:
        return err
    hw = db.session.get(Homework, hw_id)
    if not hw or not _in_roster(hw, user.id):
        return jsonify({'message': '作业不存在或未对你发布'}), 404
    if hw.status != HomeworkStatusEnum.PUBLISHED:
        return jsonify({'message': '作业未发布或已关闭'}), 400
    if hw.is_expired and not hw.allow_late:
        return jsonify({'message': '已过截止时间且不允许迟交'}), 403

    sub = _my_submission(hw, user.id)
    if sub and sub.status == SubmissionStatusEnum.GRADED:
        return jsonify({'message': '已批改完成，不能再提交'}), 400
    resubmit = bool(sub and sub.status == SubmissionStatusEnum.SUBMITTED)
    if resubmit:
        if hw.is_expired:
            return jsonify({'message': '迟交仅一次，过期后不可重交'}), 403
        if not hw.allow_resubmit:
            return jsonify({'message': '本作业不允许重交'}), 403

    if sub is None:
        sub = HomeworkSubmission(homework_id=hw.id, student_id=user.id,
                                 status=SubmissionStatusEnum.DRAFT)
        db.session.add(sub)
        db.session.flush()

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
            a.answer = str(text if text is not None else '')[:50000]
        if hw.hw_type == HomeworkTypeEnum.OPEN and 'content' in data:
            sub.content = str(data.get('content') or '')[:50000]

    if hw.hw_type == HomeworkTypeEnum.OPEN and not (sub.content or '').strip() \
            and not (sub.attachment_json or {}).get('stored_name'):
        return jsonify({'message': '请至少填写内容或上传附件'}), 400

    finalize_submission(hw, sub)
    if resubmit:
        sub.version = (sub.version or 1) + 1
    db.session.commit()
    # 师生互动：学生提交/重交 → 实时通知教师去批改（经 ORM 事件自动推送）
    from api.notification_routes import create_notification
    create_notification(
        hw.teacher_id, '收到作业重交' if resubmit else '收到作业提交',
        f'《{hw.title}》学生 {user.username} 已提交（第 {sub.version or 1} 版），待批改。',
        type='info', related_type='homework', related_id=hw.id)
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
    return jsonify({'items': [s.to_dict(for_teacher=True) for s in subs],
                    'not_submitted': not_submitted,
                    'student_count': len(hw.hw_students)})


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
    return {'homework': hw.to_dict(for_teacher=True),
            'submission': sub.to_dict(for_teacher=True),
            'answers': [a.to_dict(for_teacher=True,
                                  max_score=hq_map[a.question_id].score if a.question_id in hq_map else None)
                        for a in sub.answers],
            'questions': [_question_payload(hq, True) for hq in
                          sorted(hw.hw_questions, key=lambda x: (x.order or 0, x.question_id))]}


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

    data = request.get_json(silent=True) or {}

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
        from api.notification_routes import create_notification
        create_notification(sub.student_id, '作业已批改',
                            f'《{hw.title}》成绩已公布：{sub.total_score} 分（满分 {sub.max_score}）。',
                            type='success', related_type='homework', related_id=hw.id)
        db.session.commit()
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
        sub.status = SubmissionStatusEnum.GRADED
        sub.graded_by = user.id
        sub.graded_at = utcnow()
        from api.notification_routes import create_notification
        create_notification(sub.student_id, '作业已批改',
                            f'《{hw.title}》成绩已公布：{earned} 分'
                            + (f'（满分 {max_total}）' if max_total else '') + '。',
                            type='success', related_type='homework', related_id=hw.id)
    db.session.commit()
    return jsonify({'message': '已批改完成' if pending == 0 else f'已保存给分（仍有 {pending} 题待批）',
                    'graded': pending == 0, 'pending_manual': pending,
                    'submission': sub.to_dict(for_teacher=True)})


@homework_bp.route('/homeworks/<int:hw_id>/grade/<int:sub_id>/ai_suggest', methods=['POST'])
@limiter.limit('10/min')
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
    if not (user.is_teacher() and hw.teacher_id == user.id) and sub.student_id != user.id:
        return jsonify({'message': '无权下载该附件'}), 403
    att = sub.attachment_json or {}
    if not att.get('stored_name'):
        return jsonify({'message': '无附件'}), 404
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
