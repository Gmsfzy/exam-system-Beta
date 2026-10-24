# -*- coding: utf-8 -*-
"""v5.21 课程成绩册/权重聚合 API（跨模块只读视图）。

按课程维度把某位教师的作业（HomeworkSubmission.total_score/max_score）与考试
（Result.score/total_score）得分率，依其自定义权重方案（course_grade_scheme）加权汇总，
产出成绩册。核心红线：纯读聚合，绝不改写 total_score/status、不写 ledger、不改任何判分口径；
与 v5.18 build_class_analytics 同属只读看板家族。

权限：Course 无归属教师，故成绩册绑定「建方案的教师」（created_by）——
教师只可配置/查看本人建的方案；学生只读回放本人总评（脱敏，仅本人行）。
挂载：app.py 统一 url_prefix='/api'，本蓝图路径以 /courses、/gradebook 起。
"""
from collections import OrderedDict

from flask import Blueprint, request, jsonify

from database import db
from database.models import (
    User, Course, Exam, ExamStudent, Result, ExamStatusEnum,
    CourseGradeScheme, GradeComponentTypeEnum, GradeAggregateEnum,
)
from homework.models import (
    Homework, HomeworkStudent, HomeworkSubmission,
    HomeworkStatusEnum, SubmissionStatusEnum,
)
from utils.permissions import require_teacher, require_login
from utils.security import limiter

api_gradebook_bp = Blueprint('api_gradebook', __name__)

# 得分率聚合口径说明：mean 仅计已完成项 / all 未做按 0 计入分母 / best 取最高得分率
_COMPONENT_ALL = GradeComponentTypeEnum.ALL
_AGG_ALL = GradeAggregateEnum.VALUES


# ═══════════════════════ 只读聚合服务 ═══════════════════════

def _rate_from_pools(item_rates, student_id, aggregate):
    """由 {item_id: {student_id: rate}} 计算某生在某一组件上的得分率（0~1）。

    item_rates 为该组件类型下全部可计入项的每生得分率映射；返回 None 表示无可计数据。
    """
    pool = [m[student_id] for m in item_rates.values() if student_id in m]
    denominator = len(item_rates)
    if aggregate == GradeAggregateEnum.BEST:
        return max(pool) if pool else None
    if aggregate == GradeAggregateEnum.ALL:
        if denominator <= 0:
            return None
        return sum(pool) / denominator   # 未做项按 0 计入分母
    # mean：仅按该生已完成项求平均
    return (sum(pool) / len(pool)) if pool else None


def _collect_homework_rates(course_id, teacher_id):
    """返回该教师该课程下（非草稿）作业的 {hw_id: {student_id: 得分率}} 与参与/名单学生集合。"""
    hw_items = Homework.query.filter(
        Homework.course_id == course_id,
        Homework.teacher_id == teacher_id,
        Homework.status != HomeworkStatusEnum.DRAFT,
    ).all()
    rates = {}
    members = set()
    for hw in hw_items:
        m = {}
        for sub in HomeworkSubmission.query.filter_by(
                homework_id=hw.id, status=SubmissionStatusEnum.GRADED).all():
            if sub.max_score and sub.max_score > 0 and sub.total_score is not None:
                m[sub.student_id] = sub.total_score / sub.max_score
        rates[hw.id] = m
        # 名单成员也纳入学生集合，使未交者在 all 口径下呈现 0
        for hs in HomeworkStudent.query.filter_by(homework_id=hw.id).all():
            members.add(hs.student_id)
    members |= {sid for mm in rates.values() for sid in mm}
    return rates, len(hw_items), members


def _collect_exam_rates(course_id, teacher_id, only_published=False):
    """返回该教师该课程下（非草稿）考试的 {exam_id: {student_id: 得分率}} 与参与/受邀学生集合。"""
    exam_items = Exam.query.filter(
        Exam.course_id == course_id,
        Exam.creator_id == teacher_id,
        Exam.status != ExamStatusEnum.DRAFT,
    ).all()
    if only_published:
        exam_items = [e for e in exam_items if e.results_published]
    rates = {}
    members = set()
    for exam in exam_items:
        m = {}
        for r in Result.query.filter_by(exam_id=exam.id).all():
            if r.total_score and r.total_score > 0 and r.score is not None:
                m[r.student_id] = r.score / r.total_score
        rates[exam.id] = m
        for es in ExamStudent.query.filter_by(exam_id=exam.id).all():
            members.add(es.student_id)
    members |= {sid for mm in rates.values() for sid in mm}
    return rates, len(exam_items), members


def _build_group_rows(schemes, hw_rates, exam_rates, students):
    """逐生加权总评（0~100），返回 rows 列表。students 为学生 id 集合。"""
    names = {}
    if students:
        for u in User.query.filter(User.id.in_(students)).all():
            names[u.id] = u.username
    rows = []
    for sid in sorted(students):
        num = 0.0
        den = 0.0
        comps = []
        for s in schemes:
            if s.component_type == GradeComponentTypeEnum.EXAM:
                rate = _rate_from_pools(exam_rates, sid, s.aggregate)
            else:
                rate = _rate_from_pools(hw_rates, sid, s.aggregate)
            w = float(s.weight or 0.0)
            comps.append({
                'scheme_id': s.id, 'name': s.name, 'component_type': s.component_type,
                'aggregate': s.aggregate, 'weight': round(w, 2),
                'rate': round(rate * 100, 2) if rate is not None else None,
            })
            if rate is not None and w > 0:
                num += rate * w
                den += w
        total = round(num / den * 100, 2) if den > 0 else None
        rows.append({'student_id': sid, 'student_name': names.get(sid, str(sid)),
                     'total': total, 'components': comps})
    return rows


def build_course_gradebook(course_id, only_published=False):
    """按课程聚合各教师方案的成绩册分组列表（只读，不写库）。"""
    schemes = CourseGradeScheme.query.filter_by(course_id=course_id).order_by(
        CourseGradeScheme.created_by.asc(), CourseGradeScheme.id.asc()).all()
    grouped = OrderedDict()
    for s in schemes:
        grouped.setdefault(s.created_by, []).append(s)

    # 缓存每位教师的作业/考试得分率映射，避免逐方案重复查询
    cache = {}
    result = []
    for teacher_id, ss in grouped.items():
        if teacher_id not in cache:
            hw_rates, hw_count, hw_members = _collect_homework_rates(course_id, teacher_id)
            exam_rates, exam_count, exam_members = _collect_exam_rates(course_id, teacher_id, only_published)
            cache[teacher_id] = (hw_rates, hw_count, exam_rates, exam_count, hw_members | exam_members)
        hw_rates, hw_count, exam_rates, exam_count, students = cache[teacher_id]
        teacher = db.session.get(User, teacher_id)
        rows = _build_group_rows(ss, hw_rates, exam_rates, students)
        result.append({
            'teacher_id': teacher_id,
            'teacher_name': teacher.username if teacher else '',
            'homework_count': hw_count,
            'exam_count': exam_count,
            'schemes': [{
                'id': s.id, 'component_type': s.component_type, 'name': s.name,
                'weight': round(float(s.weight or 0.0), 2), 'aggregate': s.aggregate,
            } for s in ss],
            'rows': rows,
        })
    return result


def _scheme_payload(data):
    """校验/归一方案字段，返回 (dict, err_msg)。"""
    component_type = str(data.get('component_type') or '').strip()
    if component_type not in _COMPONENT_ALL:
        return None, 'component_type 须为 homework/exam'
    aggregate = str(data.get('aggregate') or GradeAggregateEnum.MEAN).strip()
    if aggregate not in _AGG_ALL:
        return None, 'aggregate 须为 mean/all/best'
    try:
        weight = float(data.get('weight'))
    except (TypeError, ValueError):
        return None, 'weight 须为 0~100 的数字'
    if not (0.0 <= weight <= 100.0):
        return None, 'weight 须在 0~100 之间'
    name = str(data.get('name') or '').strip()[:100]
    return {'component_type': component_type, 'aggregate': aggregate,
            'weight': round(weight, 2), 'name': name}, None


# ═══════════════════════ 端点：权重方案 CRUD ═══════════════════════

@api_gradebook_bp.route('/courses/<int:course_id>/gradebook/schemes', methods=['GET'])
def api_scheme_list(course_id):
    user, err = require_teacher()
    if err:
        return err
    if not db.session.get(Course, course_id):
        return jsonify({'message': '课程不存在'}), 404
    rows = CourseGradeScheme.query.filter_by(
        course_id=course_id, created_by=user.id).order_by(CourseGradeScheme.id.asc()).all()
    return jsonify({'schemes': [{
        'id': s.id, 'component_type': s.component_type, 'name': s.name,
        'weight': round(float(s.weight or 0.0), 2), 'aggregate': s.aggregate,
    } for s in rows]})


@api_gradebook_bp.route('/courses/<int:course_id>/gradebook/schemes', methods=['POST'])
@limiter.limit('60/minute')
def api_scheme_create(course_id):
    user, err = require_teacher()
    if err:
        return err
    course = db.session.get(Course, course_id)
    if not course:
        return jsonify({'message': '课程不存在'}), 404
    p, msg = _scheme_payload(request.get_json(silent=True) or {})
    if msg:
        return jsonify({'message': msg}), 400
    if CourseGradeScheme.query.filter_by(course_id=course_id, created_by=user.id).count() >= 20:
        return jsonify({'message': '单课程计分组件上限 20 条'}), 400
    s = CourseGradeScheme(course_id=course_id, created_by=user.id, **p)
    db.session.add(s)
    db.session.commit()
    return jsonify({'message': '已添加', 'scheme': {
        'id': s.id, 'component_type': s.component_type, 'name': s.name,
        'weight': round(float(s.weight or 0.0), 2), 'aggregate': s.aggregate}}), 201


@api_gradebook_bp.route('/gradebook/schemes/<int:scheme_id>', methods=['PUT'])
@limiter.limit('60/minute')
def api_scheme_update(scheme_id):
    user, err = require_teacher()
    if err:
        return err
    s = db.session.get(CourseGradeScheme, scheme_id)
    if not s:
        return jsonify({'message': '方案不存在'}), 404
    if s.created_by != user.id:
        return jsonify({'message': '仅可修改本人创建的计分组件'}), 403
    p, msg = _scheme_payload(request.get_json(silent=True) or {})
    if msg:
        return jsonify({'message': msg}), 400
    for k, v in p.items():
        setattr(s, k, v)
    db.session.commit()
    return jsonify({'message': '已更新', 'scheme': {
        'id': s.id, 'component_type': s.component_type, 'name': s.name,
        'weight': round(float(s.weight or 0.0), 2), 'aggregate': s.aggregate}})


@api_gradebook_bp.route('/gradebook/schemes/<int:scheme_id>', methods=['DELETE'])
@limiter.limit('60/minute')
def api_scheme_delete(scheme_id):
    user, err = require_teacher()
    if err:
        return err
    s = db.session.get(CourseGradeScheme, scheme_id)
    if not s:
        return jsonify({'message': '方案不存在'}), 404
    if s.created_by != user.id:
        return jsonify({'message': '仅可删除本人创建的计分组件'}), 403
    db.session.delete(s)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ═══════════════════════ 端点：成绩册视图 ═══════════════════════

@api_gradebook_bp.route('/courses/<int:course_id>/gradebook', methods=['GET'])
@limiter.limit('60/minute')
def api_gradebook(course_id):
    """教师成绩册：仅返回本人建方案的分组（含逐生加权总评与组件明细）。只读聚合，不改判分/账本。"""
    user, err = require_teacher()
    if err:
        return err
    course = db.session.get(Course, course_id)
    if not course:
        return jsonify({'message': '课程不存在'}), 404
    groups = [g for g in build_course_gradebook(course_id) if g['teacher_id'] == user.id]
    return jsonify({'course': {'id': course.id, 'name': course.name}, 'groups': groups})


@api_gradebook_bp.route('/courses/<int:course_id>/gradebook/me', methods=['GET'])
@limiter.limit('60/minute')
def api_gradebook_me(course_id):
    """学生本人成绩册：跨该课程所有教师方案，仅返回请求者本人行；考试仅计已发布成绩。"""
    user, err = require_login()
    if err:
        return err
    course = db.session.get(Course, course_id)
    if not course:
        return jsonify({'message': '课程不存在'}), 404
    me = []
    for g in build_course_gradebook(course_id, only_published=True):
        row = next((r for r in g['rows'] if r['student_id'] == user.id), None)
        if row:
            me.append({'teacher_name': g['teacher_name'], 'schemes': g['schemes'],
                       'total': row['total'], 'components': row['components']})
    return jsonify({'course': {'id': course.id, 'name': course.name}, 'gradebooks': me})
