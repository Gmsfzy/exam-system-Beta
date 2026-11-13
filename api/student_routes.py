from flask import Blueprint, request, jsonify
from database.models import User, Exam, ExamStudent, Result
from database import db
from utils.timeutil import iso_local
from utils.security import verify_token
from utils.permissions import require_teacher

api_student_bp = Blueprint('api_student', __name__)

@api_student_bp.route('/exams/<int:id>/students', methods=['GET'])
def api_exam_students(id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
    exam = Exam.query.get_or_404(id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权访问'}), 403
    
    students = []
    for es in exam.exam_students:
        s = es.student
        result = Result.query.filter_by(exam_id=id, student_id=s.id).first()
        students.append({
            'id': s.id,
            'username': s.username,
            'email': s.email,
            'invited_at': iso_local(es.invited_at),
            'has_submitted': result is not None,
            'score': result.score if result else None
        })
    return jsonify(students)

@api_student_bp.route('/exams/<int:id>/invite', methods=['POST'])
def api_invite_students(id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    
    exam = Exam.query.get_or_404(id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权邀请'}), 403
    
    data = request.get_json()
    student_ids = data.get('student_ids', [])
    for s_id in student_ids:
        existing = ExamStudent.query.filter_by(exam_id=id, student_id=s_id).first()
        if not existing:
            es = ExamStudent(exam_id=id, student_id=s_id)
            db.session.add(es)
    
    db.session.commit()
    return jsonify({'message': '邀请成功'})

@api_student_bp.route('/exams/<int:id>/remove_student/<int:student_id>', methods=['POST'])
def api_remove_student(id, student_id):
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err

    exam = Exam.query.get_or_404(id)
    if exam.creator_id != user.id:
        return jsonify({'message': '无权修改'}), 403

    es = ExamStudent.query.filter_by(exam_id=id, student_id=student_id).first()
    if not es:
        return jsonify({'message': '该学生未被邀请'}), 400
    db.session.delete(es)
    db.session.commit()
    return jsonify({'message': '已取消邀请'})

@api_student_bp.route('/students', methods=['GET'])
def api_list_students():
    """v7.7 学生列表：支持 ?course_id= 按课程历史考生过滤 + ?search= 关键词。

    - course_id 给出时，只返回曾在该课程下参加过考试的学生（隐式"班级"概念）。
      要加新人？清除筛选或用 search 关键词精确搜。
    - search 对 username/email 做 LIKE。
    - 两个参数可叠加。"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err

    course_id = request.args.get('course_id', type=int)
    search = (request.args.get('search') or '').strip()

    query = User.query.filter_by(role='student')

    if course_id:
        from database.models import Exam, ExamStudent
        exam_ids = [e.id for e in Exam.query.filter_by(course_id=course_id).all()]
        if not exam_ids:
            # 这门课还没人考过试 → 返回空，提示教师换筛选条件或用搜索
            return jsonify([])
        historical_ids = [es.student_id for es in ExamStudent.query.filter(ExamStudent.exam_id.in_(exam_ids)).all()]
        if not historical_ids:
            return jsonify([])
        query = query.filter(User.id.in_(historical_ids))

    if search:
        like = f"%{search}%"
        query = query.filter(db.or_(User.username.like(like), User.email.like(like)))

    students = query.order_by(User.username).all()
    return jsonify([{'id': s.id, 'username': s.username, 'email': s.email} for s in students])