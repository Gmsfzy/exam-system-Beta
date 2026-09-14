from flask import Blueprint, request, jsonify
from database.models import User, Exam, ExamStudent, Result
from database import db
from utils.timeutil import iso_local
from utils.security import verify_token

api_student_bp = Blueprint('api_student', __name__)

@api_student_bp.route('/exams/<int:id>/students', methods=['GET'])
def api_exam_students(id):
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
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
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
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
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403

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
    user = verify_token()
    if not user or not user.is_teacher():
        return jsonify({'message': '无权访问'}), 403
    
    students = User.query.filter_by(role='student').all()
    return jsonify([{'id': s.id, 'username': s.username, 'email': s.email} for s in students])