from database.models import Department, Major, Course, User, RoleEnum
from database import db

def init_data():
    if Department.query.first():
        print('[DB] 数据库已初始化，跳过数据填充')
        return

    departments = [
        {'name': '计算机学院', 'description': '负责计算机科学与技术、软件工程等专业的教学与研究'},
        {'name': '信息学院', 'description': '负责信息管理、通信工程等专业的教学与研究'},
        {'name': '数学学院', 'description': '负责数学、统计学等专业的教学与研究'},
        {'name': '物理学院', 'description': '负责物理学、应用物理等专业的教学与研究'},
        {'name': '经济管理学院', 'description': '负责经济、管理等专业的教学与研究'},
    ]
    dept_map = {}
    for d in departments:
        dept = Department(name=d['name'], description=d['description'])
        db.session.add(dept)
        db.session.flush()
        dept_map[d['name']] = dept

    majors = [
        {'name': '计算机科学与技术', 'description': '培养计算机科学与技术领域的高级人才', 'dept': '计算机学院'},
        {'name': '软件工程', 'description': '培养软件工程领域的高级人才', 'dept': '计算机学院'},
        {'name': '人工智能', 'description': '培养人工智能领域的高级人才', 'dept': '计算机学院'},
        {'name': '网络工程', 'description': '培养网络工程领域的高级人才', 'dept': '计算机学院'},
        {'name': '信息管理与信息系统', 'description': '培养信息管理领域的高级人才', 'dept': '信息学院'},
        {'name': '通信工程', 'description': '培养通信工程领域的高级人才', 'dept': '信息学院'},
        {'name': '数学与应用数学', 'description': '培养数学领域的高级人才', 'dept': '数学学院'},
        {'name': '统计学', 'description': '培养统计学领域的高级人才', 'dept': '数学学院'},
        {'name': '物理学', 'description': '培养物理学领域的高级人才', 'dept': '物理学院'},
        {'name': '应用物理学', 'description': '培养应用物理领域的高级人才', 'dept': '物理学院'},
        {'name': '工商管理', 'description': '培养工商管理领域的高级人才', 'dept': '经济管理学院'},
        {'name': '会计学', 'description': '培养会计学领域的高级人才', 'dept': '经济管理学院'},
    ]
    major_map = {}
    for m in majors:
        major = Major(name=m['name'], description=m['description'], department_id=dept_map[m['dept']].id)
        db.session.add(major)
        db.session.flush()
        major_map[m['name']] = major

    courses = [
        {'name': '高等数学', 'description': '大学数学基础课程', 'major': '计算机科学与技术', 'credit': 6.0, 'semester': '第一学期'},
        {'name': '高等数学', 'description': '大学数学基础课程', 'major': '软件工程', 'credit': 6.0, 'semester': '第一学期'},
        {'name': '高等数学', 'description': '大学数学基础课程', 'major': '人工智能', 'credit': 6.0, 'semester': '第一学期'},
        {'name': '高等数学', 'description': '大学数学基础课程', 'major': '网络工程', 'credit': 6.0, 'semester': '第一学期'},
        {'name': '高等数学', 'description': '大学数学基础课程', 'major': '信息管理与信息系统', 'credit': 6.0, 'semester': '第一学期'},
        {'name': '高等数学', 'description': '大学数学基础课程', 'major': '通信工程', 'credit': 6.0, 'semester': '第一学期'},
        {'name': '线性代数', 'description': '线性代数基础课程', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第一学期'},
        {'name': '线性代数', 'description': '线性代数基础课程', 'major': '软件工程', 'credit': 4.0, 'semester': '第一学期'},
        {'name': '线性代数', 'description': '线性代数基础课程', 'major': '人工智能', 'credit': 4.0, 'semester': '第一学期'},
        {'name': '线性代数', 'description': '线性代数基础课程', 'major': '数学与应用数学', 'credit': 4.0, 'semester': '第一学期'},
        {'name': 'Python编程', 'description': 'Python编程语言入门', 'major': '计算机科学与技术', 'credit': 3.0, 'semester': '第二学期'},
        {'name': 'Python编程', 'description': 'Python编程语言入门', 'major': '软件工程', 'credit': 3.0, 'semester': '第二学期'},
        {'name': 'Python编程', 'description': 'Python编程语言入门', 'major': '人工智能', 'credit': 3.0, 'semester': '第二学期'},
        {'name': 'Python编程', 'description': 'Python编程语言入门', 'major': '信息管理与信息系统', 'credit': 3.0, 'semester': '第二学期'},
        {'name': '数据结构', 'description': '数据结构与算法', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '数据结构', 'description': '数据结构与算法', 'major': '软件工程', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '数据结构', 'description': '数据结构与算法', 'major': '人工智能', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '数据结构', 'description': '数据结构与算法', 'major': '网络工程', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '计算机网络', 'description': '计算机网络原理与应用', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '计算机网络', 'description': '计算机网络原理与应用', 'major': '软件工程', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '计算机网络', 'description': '计算机网络原理与应用', 'major': '网络工程', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '操作系统', 'description': '操作系统原理与实现', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '操作系统', 'description': '操作系统原理与实现', 'major': '软件工程', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '数据库原理', 'description': '数据库系统原理与应用', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '数据库原理', 'description': '数据库系统原理与应用', 'major': '软件工程', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '数据库原理', 'description': '数据库系统原理与应用', 'major': '信息管理与信息系统', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '人工智能基础', 'description': '人工智能基本概念与方法', 'major': '人工智能', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '人工智能基础', 'description': '人工智能基本概念与方法', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第四学期'},
        {'name': '机器学习', 'description': '机器学习算法与实践', 'major': '人工智能', 'credit': 4.0, 'semester': '第四学期'},
        {'name': '深度学习', 'description': '深度学习原理与应用', 'major': '人工智能', 'credit': 4.0, 'semester': '第四学期'},
        {'name': '软件工程导论', 'description': '软件工程基本概念与方法', 'major': '软件工程', 'credit': 3.0, 'semester': '第二学期'},
        {'name': '软件测试', 'description': '软件测试方法与技术', 'major': '软件工程', 'credit': 3.0, 'semester': '第四学期'},
        {'name': '软件项目管理', 'description': '软件项目管理方法', 'major': '软件工程', 'credit': 3.0, 'semester': '第五学期'},
        {'name': '计算机组成原理', 'description': '计算机硬件组成原理', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '离散数学', 'description': '离散数学基础', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第一学期'},
        {'name': '离散数学', 'description': '离散数学基础', 'major': '软件工程', 'credit': 4.0, 'semester': '第一学期'},
        {'name': '概率论与数理统计', 'description': '概率论与数理统计基础', 'major': '计算机科学与技术', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '概率论与数理统计', 'description': '概率论与数理统计基础', 'major': '人工智能', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '概率论与数理统计', 'description': '概率论与数理统计基础', 'major': '统计学', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '信号与系统', 'description': '信号与系统分析', 'major': '通信工程', 'credit': 4.0, 'semester': '第二学期'},
        {'name': '通信原理', 'description': '通信原理与技术', 'major': '通信工程', 'credit': 4.0, 'semester': '第三学期'},
        {'name': '运筹学', 'description': '运筹学方法与应用', 'major': '工商管理', 'credit': 3.0, 'semester': '第三学期'},
        {'name': '管理学原理', 'description': '管理学基本原理', 'major': '工商管理', 'credit': 3.0, 'semester': '第一学期'},
        {'name': '会计基础', 'description': '会计学基础', 'major': '会计学', 'credit': 3.0, 'semester': '第一学期'},
        {'name': '中级财务会计', 'description': '中级财务会计', 'major': '会计学', 'credit': 4.0, 'semester': '第三学期'},
    ]
    for c in courses:
        course = Course(name=c['name'], description=c['description'], major_id=major_map[c['major']].id,
                        credit=c['credit'], semester=c['semester'])
        db.session.add(course)

    admin = User(username='admin', email='admin@exam.com', role=RoleEnum.TEACHER)
    admin.set_password('admin123')
    db.session.add(admin)

    teacher = User(username='teacher', email='teacher@exam.com', role=RoleEnum.TEACHER)
    teacher.set_password('teacher123')
    db.session.add(teacher)

    student = User(username='student', email='student@exam.com', role=RoleEnum.STUDENT)
    student.set_password('student123')
    db.session.add(student)

    db.session.commit()
    print('[DB] 初始化数据完成')