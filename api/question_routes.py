from flask import Blueprint, request, jsonify, send_from_directory, Response
from database.models import Question, Major, Course, Department, QuestionTypeEnum, QUESTION_TYPE_LABELS, DifficultyEnum
from database import db
from config import Config
import os
import uuid
import io
import csv
import json

from utils.timeutil import iso_local

# 与 app.py 的 UPLOAD_FOLDER 保持同源：统一使用 Config.APP_DIR（frozen = exe 旁；dev = 项目根）
UPLOAD_FOLDER = os.path.join(Config.APP_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'avi', 'mov'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

HAS_OPENPYXL = False
try:
    from openpyxl import Workbook
    HAS_OPENPYXL = True
except ImportError:
    pass

HAS_DOCX = False
try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    pass

from utils.redis_cache import get_cache, set_cache, invalidate_question_cache, CacheKey
from utils.security import limiter, RateLimitConfig, verify_token
from utils.logger import logger

def _require_teacher():
    """写操作鉴权：委托 utils.permissions 统一实现（RBAC 收敛）。"""
    from utils.permissions import require_teacher
    return require_teacher(deny_msg='无权操作，仅教师可管理题库')

def _normalize_cases(value):
    """OJ 用例列表（v4.7）：仅保留含 input/expected 的 dict 元素，归一为字符串；空 → None。

    兼容前端传 JSON 字符串或数组；非法输入一律降级为无用例（回落 AI/人工评分）。"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    if not isinstance(value, list):
        return None
    out = [{'input': str(c.get('input') or ''), 'expected': str(c.get('expected') or '')}
           for c in value if isinstance(c, dict)]
    return out or None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _normalize_options(value):
    """统一 options 存储为 JSON 数组字符串（前端所有展示处均 JSON.parse）。

    列表 → json.dumps；JSON 数组字符串 → 原样保留；其余 → None。"""
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False) if value else None
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return value
        except (ValueError, TypeError):
            pass
        return json.dumps([value], ensure_ascii=False)
    return None

TAG_MAX_LEN = 20
TAG_MAX_COUNT = 10

def _clean_tag(raw, allow_empty=False):
    """单个标签清洗（v5.23）：strip 后非空（allow_empty 时空→''）、≤20字、不含斜杠（保证 URL path 安全）。非法抛 ValueError。"""
    s = str(raw if raw is not None else '').strip()
    if not s:
        if allow_empty:
            return ''
        raise ValueError('标签不能为空')
    if len(s) > TAG_MAX_LEN:
        raise ValueError(f'单个标签长度不能超过{TAG_MAX_LEN}字')
    if '/' in s or '\\' in s:
        raise ValueError('标签不能包含斜杠')
    return s

def _normalize_tags(value):
    """标签数组归一（v5.23）：兼容 JSON 字符串或数组；逐项清洗、去空、去重、数量上限；非法抛 ValueError。
    与 knowledge（知识点）正交，仅组织/检索用途，不参与掌握度/判分/推荐。空数组返回 []。"""
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else []
        except (ValueError, TypeError):
            raise ValueError('tags 必须为标签数组')
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('tags 必须为标签数组')
    seen = []
    for t in value:
        s = _clean_tag(t, allow_empty=True)
        if s and s not in seen:
            seen.append(s)
    if len(seen) > TAG_MAX_COUNT:
        raise ValueError(f'标签数量不能超过{TAG_MAX_COUNT}个')
    return seen

api_question_bp = Blueprint('api_question', __name__)

@api_question_bp.route('/questions', methods=['GET'])
@limiter.limit(RateLimitConfig.QUESTION_QUERY)
def api_list_questions():
    # 鉴权：题库仅登录用户可见；学生视角剔除答案/解析，防止考前拖库
    user = verify_token()
    if not user:
        return jsonify({'message': '请先登录'}), 401
    is_teacher = user.is_teacher()

    major_id = request.args.get('major_id')
    course_id = request.args.get('course_id')
    q_type = request.args.get('type')
    scope = request.args.get('scope')  # all / mine / public（仅教师有意义）
    tag = request.args.get('tag')  # v5.23 按标签筛选（对 JSON 数组按 "标签" 包含匹配）

    # scope 仅教师可用；学生始终看全部（传统行为）
    if not is_teacher:
        scope = None

    # 缓存按角色+scope隔离
    cache_key = CacheKey.questions_key(major_id, course_id, q_type) + (':t' if is_teacher else ':s')
    if scope:
        cache_key += f':{scope}'
    if tag:
        cache_key += f':tag={tag}'
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return jsonify(cached_data)

    query = Question.query
    if major_id:
        query = query.filter(Question.major_id == int(major_id))
    if course_id:
        query = query.filter(Question.course_id == int(course_id))
    if q_type:
        query = query.filter(Question.type == q_type)
    if tag:
        # tags 底层为 JSON TEXT（如 ["易错","高频"]），按带引号的 "标签" 精确包含匹配，避免子串误命中
        query = query.filter(Question.tags.like('%."{}"%.'.replace('.', '%').format(tag)))

    if scope == 'mine':
        query = query.filter(Question.creator_id == user.id)
    elif scope == 'public':
        query = query.filter(Question.is_public.is_(True), Question.creator_id != user.id)

    questions = query.all()

    result = [{
        'id': q.id,
        'content': q.content,
        'type': q.type,
        'difficulty': q.difficulty,
        'source': q.source,
        'major_id': q.major_id,
        'major_name': q.major.name if q.major else '',
        'course_id': q.course_id,
        'course_name': q.course.name if q.course else '',
        'options': q.options,
        # 答案与解析仅教师可见；学生端（如悬赏发布）只需要题干/选项
        'answer': q.answer if is_teacher else '',
        'analysis': q.analysis if is_teacher else '',
        'knowledge': q.knowledge,
        'tags': q.tags or [],                     # v5.23 自由标签数组（与知识点正交）
        'material': q.material,                  # v4.3 材料题共享材料
        'material_group': q.material_group,      # v4.3 同组题共享同一材料
        # v4.7 OJ 用例含预期输出，仅教师可见
        'test_cases': (q.test_cases if is_teacher else None),
        'creator_id': q.creator_id,
        'creator_name': q.creator.username if q.creator else '',
        'is_public': q.is_public,
        'is_owner': q.creator_id == user.id if is_teacher else False,
        'created_at': iso_local(q.created_at)
    } for q in questions]

    set_cache(cache_key, result, expires=300)
    return jsonify(result)

@api_question_bp.route('/questions', methods=['POST'])
def api_add_question():
    user, err = _require_teacher()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if not data.get('content') or not data.get('type') or not data.get('difficulty') or data.get('major_id') is None:
        return jsonify({'message': '缺少必要参数（content/type/difficulty/major_id）'}), 400
    try:
        tags_val = _normalize_tags(data.get('tags'))
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    q = Question(
        content=data['content'],
        options=_normalize_options(data.get('options')),
        answer=data.get('answer', ''),
        analysis=data.get('analysis', ''),
        major_id=data['major_id'],
        course_id=data.get('course_id'),
        type=data['type'],
        difficulty=data['difficulty'],
        source=data.get('source', 'manual'),
        creator_id=user.id,
        is_public=bool(data.get('is_public', False)),
        material=(data.get('material') or None),           # v4.3 材料题
        material_group=(data.get('material_group') or None),
        test_cases=_normalize_cases(data.get('test_cases')),  # v4.7 OJ 用例
        tags=tags_val or None,                                # v5.23 自由标签
    )
    db.session.add(q)
    db.session.commit()
    invalidate_question_cache(major_id=data['major_id'], course_id=data.get('course_id'))
    return jsonify({'message': '添加成功', 'id': q.id})

@api_question_bp.route('/questions/<int:id>', methods=['PUT'])
def api_update_question(id):
    user, err = _require_teacher()
    if err:
        return err
    q = Question.query.get_or_404(id)
    # 仅创建者可编辑自己的题目；公共题库中他人的题目只读
    if q.creator_id is not None and q.creator_id != user.id:
        return jsonify({'message': '只能编辑自己创建的题目'}), 403
    old_major_id = q.major_id
    old_course_id = q.course_id
    data = request.get_json(silent=True) or {}
    if not data.get('content') or not data.get('type') or not data.get('difficulty') or data.get('major_id') is None:
        return jsonify({'message': '缺少必要参数（content/type/difficulty/major_id）'}), 400
    try:
        tags_val = _normalize_tags(data.get('tags')) if 'tags' in data else None
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    q.content = data['content']
    q.options = _normalize_options(data.get('options'))
    q.answer = data.get('answer', '')
    q.analysis = data.get('analysis', '')
    q.major_id = data['major_id']
    q.course_id = data.get('course_id')
    q.type = data['type']
    q.difficulty = data['difficulty']
    q.source = data.get('source', q.source)
    if 'tags' in data:                            # v5.23 自由标签（创建者可整体替换）
        q.tags = tags_val or None
    if 'material' in data:                       # v4.3 材料题
        q.material = data.get('material') or None
        q.material_group = (data.get('material_group') or None) if q.material else None
    if 'test_cases' in data:                     # v4.7 OJ 用例
        q.test_cases = _normalize_cases(data.get('test_cases'))
    if 'is_public' in data:
        q.is_public = bool(data['is_public'])
    db.session.commit()
    invalidate_question_cache(major_id=data['major_id'], course_id=data.get('course_id'))
    if old_major_id != data['major_id']:
        invalidate_question_cache(major_id=old_major_id)
    if old_course_id != data.get('course_id'):
        invalidate_question_cache(course_id=old_course_id)
    return jsonify({'message': '更新成功'})

@api_question_bp.route('/questions/<int:id>/oj_run', methods=['POST'])
@limiter.limit('10 per minute')
def api_question_oj_run(id):
    """v4.7 编程题 OJ 试跑：教师提交代码按本题用例评测（验用例/自测答案）。"""
    user, err = _require_teacher()
    if err:
        return err
    q = Question.query.get_or_404(id)
    if q.type != QuestionTypeEnum.PROGRAMMING:
        return jsonify({'message': '仅编程题支持 OJ 试跑'}), 400
    if not q.test_cases:
        return jsonify({'message': '本题未配置评测用例，请先在题库编辑中添加'}), 400
    from oj.services import grade as oj_grade
    data = request.get_json(silent=True) or {}
    result = oj_grade(str(data.get('code') or ''), 'python', q.test_cases)
    return jsonify(result)

@api_question_bp.route('/questions/<int:id>', methods=['DELETE'])
def api_delete_question(id):
    user, err = _require_teacher()
    if err:
        return err
    q = Question.query.get_or_404(id)
    # 仅创建者可删除自己的题目
    if q.creator_id is not None and q.creator_id != user.id:
        return jsonify({'message': '只能删除自己创建的题目'}), 403

    # 删除守卫：ExamQuestion 直接引用 Question，删除会破坏关联考试的答题与判分
    from database.models import ExamQuestion
    if ExamQuestion.query.filter_by(question_id=q.id).count():
        return jsonify({'message': '该题目已被考试引用，禁止删除。请先在相应考试的组题中移除该题'}), 400

    major_id = q.major_id
    course_id = q.course_id
    db.session.delete(q)
    db.session.commit()
    invalidate_question_cache(major_id=major_id, course_id=course_id)
    return jsonify({'message': '删除成功'})

@api_question_bp.route('/questions/<int:id>/toggle_public', methods=['POST'])
def api_toggle_public(id):
    """切换题目的公开状态（加入/移出公共题库）"""
    user, err = _require_teacher()
    if err:
        return err
    q = Question.query.get_or_404(id)
    if q.creator_id is not None and q.creator_id != user.id:
        return jsonify({'message': '只能操作自己创建的题目'}), 403
    q.is_public = not q.is_public
    db.session.commit()
    invalidate_question_cache(major_id=q.major_id, course_id=q.course_id)
    return jsonify({'message': '已加入公共题库' if q.is_public else '已移出公共题库', 'is_public': q.is_public})

@api_question_bp.route('/questions/<int:id>/tags', methods=['POST'])
def api_add_question_tag(id):
    """v5.23 协同贴标签：创建者可为自己的题加标签；非创建教师仅可为公共题库(is_public)题加标签。幂等去重。"""
    user, err = _require_teacher()
    if err:
        return err
    q = Question.query.get_or_404(id)
    is_creator = q.creator_id is None or q.creator_id == user.id
    if not is_creator and not q.is_public:
        return jsonify({'message': '只能为自己创建或公共题库的题目贴标签'}), 403
    data = request.get_json(silent=True) or {}
    try:
        tag = _clean_tag(data.get('tag'))
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    cur = list(q.tags or [])
    if tag not in cur:
        if len(cur) >= TAG_MAX_COUNT:
            return jsonify({'message': f'标签数量已达上限（{TAG_MAX_COUNT} 个）'}), 400
        cur.append(tag)
        q.tags = cur
        db.session.commit()
        invalidate_question_cache(major_id=q.major_id, course_id=q.course_id)
    return jsonify({'message': '标签已添加', 'tags': q.tags or []})

@api_question_bp.route('/questions/<int:id>/tags/<string:tag>', methods=['DELETE'])
def api_remove_question_tag(id, tag):
    """v5.23 移除标签：仅创建者（或历史无主 NULL creator）可删。"""
    user, err = _require_teacher()
    if err:
        return err
    q = Question.query.get_or_404(id)
    if q.creator_id is not None and q.creator_id != user.id:
        return jsonify({'message': '只能移除自己创建的题目的标签'}), 403
    cur = list(q.tags or [])
    tag = (tag or '').strip()
    if tag in cur:
        cur.remove(tag)
        q.tags = cur or None
        db.session.commit()
        invalidate_question_cache(major_id=q.major_id, course_id=q.course_id)
    return jsonify({'message': '标签已移除', 'tags': q.tags or []})

@api_question_bp.route('/questions/tags', methods=['GET'])
def api_question_tag_cloud():
    """v5.23 标签云：聚合当前题库全部标签及题数，按题数降序。"""
    user, err = _require_teacher()
    if err:
        return err
    from collections import Counter
    counter = Counter()
    for (tags,) in db.session.query(Question.tags).all():
        for t in (tags or []):
            counter[t] += 1
    cloud = [{'tag': t, 'count': c} for t, c in counter.most_common()]
    return jsonify({'tags': cloud})

MAX_FILE_SIZE = 50 * 1024 * 1024

@api_question_bp.route('/upload', methods=['POST'])
def api_upload_file():
    user, err = _require_teacher()
    if err:
        return err
    if 'file' not in request.files:
        return jsonify({'error': '没有选择文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '文件名不能为空'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': '文件格式不支持'}), 400

    # multipart 下 file.content_length 常为 None，用 stream 实际探测大小
    try:
        file.stream.seek(0, os.SEEK_END)
        file_size = file.stream.tell()
        file.stream.seek(0)
    except Exception:
        file_size = file.content_length or 0
    if file_size and file_size > MAX_FILE_SIZE:
        return jsonify({'error': '文件大小超过限制（最大50MB）'}), 400

    try:
        ext = file.filename.rsplit('.', 1)[1].lower()
        new_filename = str(uuid.uuid4()) + '.' + ext
        file_path = os.path.join(UPLOAD_FOLDER, new_filename)
        file.save(file_path)

        return jsonify({
            'success': True,
            'url': '/uploads/' + new_filename,
            'filename': file.filename,
            'size': file_size
        })
    except Exception:
        logger.exception("文件上传失败 filename=%s", file.filename)
        return jsonify({'error': '文件保存失败，请稍后重试'}), 500

def _parse_word_questions(file_storage):
    """从Word文件中提取题目数据"""
    import re
    doc = Document(file_storage)
    questions = []
    current_major = ''
    current_question = {'content': '', 'options': [], 'answer': '', 'analysis': '', 'type': 'single_choice', 'difficulty': 'medium', 'major': ''}
    
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        
        major_match = re.match(r'【(.+?)】', text)
        if major_match:
            current_major = major_match.group(1)
            continue
        
        q_num_match = re.match(r'第(\d+)题', text)
        q_num_match2 = re.match(r'(\d+)\.', text)
        
        if q_num_match or q_num_match2:
            if current_question['content']:
                questions.append(current_question)
            
            current_question = {'content': '', 'options': [], 'answer': '', 'analysis': '', 'type': 'single_choice', 'difficulty': 'medium', 'major': current_major}
            
            type_match = re.search(r'【(.+?)】', text)
            if type_match:
                type_text = type_match.group(1)
                # 中文→枚举键：由事实源 LABELS 反转生成（v4.7 收敛，不再独立维护字典）
                type_map = {label: key for key, label in QUESTION_TYPE_LABELS.items()}
                current_question['type'] = type_map.get(type_text, 'single_choice')
            
            diff_match = re.search(r'难度[:：](.+)', text)
            if diff_match:
                diff_text = diff_match.group(1)
                diff_map = {label: key for key, label in DifficultyEnum.LABELS.items()}
                current_question['difficulty'] = diff_map.get(diff_text, 'medium')
            continue
        
        if text.startswith(('A.', 'B.', 'C.', 'D.', 'E.', 'F.', 'G.', 'H.', 'A、', 'B、', 'C、', 'D、')):
            option_text = re.sub(r'^[A-H][.、]', '', text).strip()
            current_question['options'].append(option_text)
            continue
        
        if text.startswith('答案：') or text.startswith('答案:'):
            current_question['answer'] = text.replace('答案：', '').replace('答案:', '').strip()
            continue
        
        if text.startswith('解析：') or text.startswith('解析:'):
            current_question['analysis'] = text.replace('解析：', '').replace('解析:', '').strip()
            continue
        
        if current_question['content']:
            current_question['content'] += '\n' + text
        else:
            current_question['content'] = text
    
    if current_question['content']:
        questions.append(current_question)
    
    return questions

def _get_or_create_major(major_name):
    """获取或创建专业"""
    major = Major.query.filter_by(name=major_name).first()
    if not major:
        major = Major(name=major_name, description=f'自动创建：{major_name}')
        db.session.add(major)
        db.session.commit()
    return major

def _get_or_create_course(course_name, major_id):
    """获取或创建课程"""
    if not course_name:
        return None
    course = Course.query.filter_by(name=course_name, major_id=major_id).first()
    if not course:
        course = Course(name=course_name, major_id=major_id, description=f'自动创建：{course_name}')
        db.session.add(course)
        db.session.commit()
    return course

@api_question_bp.route('/questions/import', methods=['POST'])
def api_import_questions():
    """导入题目API"""
    user, err = _require_teacher()
    if err:
        return err
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '请选择文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': '文件名不能为空'}), 400
    
    filename = file.filename
    is_word = filename.endswith(('.doc', '.docx'))
    is_excel = filename.endswith(('.xlsx', '.xls'))
    is_csv = filename.endswith('.csv')
    
    if not (is_word or is_excel or is_csv):
        return jsonify({'success': False, 'message': '不支持的文件格式，请上传CSV、Excel或Word文件'}), 400
    
    questions_data = []
    
    try:
        if is_word:
            if not HAS_DOCX:
                return jsonify({'success': False, 'message': '服务器未安装python-docx，请使用CSV或Excel格式'}), 500
            questions_data = _parse_word_questions(file)
        elif is_excel:
            if not HAS_OPENPYXL:
                return jsonify({'success': False, 'message': '服务器未安装openpyxl，请使用CSV格式'}), 500
            from openpyxl import load_workbook
            wb = load_workbook(file)
            ws = wb.active
            headers = [cell.value for cell in ws[1]]
            for row in ws.iter_rows(min_row=2):
                row_data = {}
                for i, cell in enumerate(row):
                    if i < len(headers):
                        row_data[headers[i]] = cell.value
                questions_data.append(row_data)
        else:
            file_content = file.read().decode('utf-8-sig')
            reader = csv.DictReader(file_content.splitlines())
            for row in reader:
                questions_data.append(row)
        
        success_count = 0
        failed_count = 0
        
        for q_data in questions_data:
            try:
                content = q_data.get('content') or q_data.get('题目内容') or q_data.get('题目')
                if not content:
                    failed_count += 1
                    continue
                
                major_name = q_data.get('major') or q_data.get('专业') or q_data.get('专业名称') or '未分类'
                major = _get_or_create_major(major_name)
                
                q_type = q_data.get('type') or q_data.get('题型') or 'single_choice'
                difficulty = q_data.get('difficulty') or q_data.get('难度') or 'medium'
                answer = q_data.get('answer') or q_data.get('答案') or ''
                analysis = q_data.get('analysis') or q_data.get('解析') or ''
                options = q_data.get('options', [])
                
                if isinstance(options, list):
                    options_json = json.dumps(options, ensure_ascii=False)
                else:
                    options_json = str(options or '')
                
                course_name = q_data.get('course') or q_data.get('课程')
                course = _get_or_create_course(course_name, major.id)
                
                question = Question(
                    content=content,
                    options=options_json,
                    answer=answer,
                    analysis=analysis,
                    type=q_type,
                    difficulty=difficulty,
                    major_id=major.id,
                    course_id=course.id if course else None,
                    source='manual'
                )
                db.session.add(question)
                success_count += 1
            except Exception as e:
                failed_count += 1
        
        db.session.commit()
        
        invalidate_question_cache()
        
        return jsonify({
            'success': True,
            'count': success_count,
            'failed': failed_count,
            'message': f'成功导入 {success_count} 道题目'
        })
    
    except Exception:
        db.session.rollback()
        logger.exception("题目导入失败 filename=%s", file.filename)
        return jsonify({'success': False, 'message': '导入失败：文件解析出错，请检查文件格式是否符合模板'}), 500

@api_question_bp.route('/questions/template/<format>')
def api_download_template(format):
    """下载题目导入模板"""
    user, err = _require_teacher()
    if err:
        return err
    fmt = format.lower()
    
    if fmt == 'word':
        if not HAS_DOCX:
            return jsonify({'success': False, 'message': '服务器未安装python-docx'}), 500
        
        doc = Document()
        
        doc.add_heading('题库导入模板', level=1)
        
        doc.add_paragraph('使用说明：')
        doc.add_paragraph('1. 每题格式：题号+题目内容（换行）选项A（换行）选项B（换行）选项C（换行）选项D（换行）答案：XXX（换行）解析：XXX')
        doc.add_paragraph('2. 题号格式：第1题、第2题、第3题... 或 1.、2.、3.')
        doc.add_paragraph('3. 选项格式：A.、B.、C.、D. 开头')
        doc.add_paragraph('4. 答案格式：答案：选项字母（如：答案：B 或 答案：AB）')
        doc.add_paragraph('5. 解析格式：解析：XXX')
        doc.add_paragraph('6. 题目类型默认：单选题（如需其他类型，请在题号后注明，如：第1题【多选题】）')
        doc.add_paragraph('7. 难度默认：中等（如需其他难度，请注明，如：难度：简单/中等/困难）')
        doc.add_paragraph('8. 专业名称：在题目前一行注明，如：【Python编程】')
        
        doc.add_heading('示例题目', level=2)
        
        doc.add_paragraph('【Python编程】')
        doc.add_paragraph('第1题')
        doc.add_paragraph('Python中哪个关键字用于定义函数？')
        doc.add_paragraph('A. class')
        doc.add_paragraph('B. def')
        doc.add_paragraph('C. function')
        doc.add_paragraph('D. define')
        doc.add_paragraph('答案：B')
        doc.add_paragraph('解析：def是Python中定义函数的关键字')
        
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        
        return Response(
            buf.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={'Content-Disposition': 'attachment; filename=question_template.docx'}
        )
    
    if fmt == 'excel':
        if not HAS_OPENPYXL:
            return jsonify({'success': False, 'message': '服务器未安装openpyxl'}), 500
        
        wb = Workbook()
        ws = wb.active
        ws.append(['题目内容', '专业', '题型', '难度', '选项(JSON格式)', '答案', '解析', '课程'])
        ws.append([
            'Python中哪个关键字用于定义函数？',
            'Python编程',
            'single_choice',
            'easy',
            '["A. class", "B. def", "C. function", "D. define"]',
            'B',
            'def是Python中定义函数的关键字',
            'Python基础'
        ])
        ws.append([
            '以下哪些是Python的内置数据类型？',
            'Python编程',
            'multiple_choice',
            'medium',
            '["A. list", "B. dict", "C. array", "D. tuple"]',
            'ABD',
            'list、dict、tuple都是Python内置数据类型',
            'Python基础'
        ])
        
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        
        return Response(
            buf.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': 'attachment; filename=question_template.xlsx'}
        )
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['题目内容', '专业', '题型', '难度', '选项(JSON格式)', '答案', '解析', '课程'])
    writer.writerow([
        'Python中哪个关键字用于定义函数？',
        'Python编程',
        'single_choice',
        'easy',
        '["A. class", "B. def", "C. function", "D. define"]',
        'B',
        'def是Python中定义函数的关键字',
        'Python基础'
    ])
    writer.writerow([
        '以下哪些是Python的内置数据类型？',
        'Python编程',
        'multiple_choice',
        'medium',
        '["A. list", "B. dict", "C. array", "D. tuple"]',
        'ABD',
        'list、dict、tuple都是Python内置数据类型',
        'Python基础'
    ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8-sig',
        headers={'Content-Disposition': 'attachment; filename=question_template.csv'}
    )