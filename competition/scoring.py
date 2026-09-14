"""竞赛计分服务：客观题判定 + 速度加成"""
import json

from database.models import QuestionTypeEnum

# 竞赛只允许客观题（即时判分，无需人工/AI评分）
COMPETITION_QUESTION_TYPES = {'single_choice', 'multiple_choice', 'true_false', 'fill_blank'}

DEFAULT_SCORING_RULE = {'base_ratio': 0.7, 'speed_ratio': 0.3}


def parse_scoring_rule(scoring_rule_text):
    """解析计分规则 JSON，异常时回退默认值"""
    try:
        rule = json.loads(scoring_rule_text or '')
        base = float(rule.get('base_ratio', DEFAULT_SCORING_RULE['base_ratio']))
        speed = float(rule.get('speed_ratio', DEFAULT_SCORING_RULE['speed_ratio']))
        if base < 0 or speed < 0 or base + speed == 0:
            raise ValueError
        # 归一化，保证每题满分不超过题目分值
        total = base + speed
        return base / total, speed / total
    except (ValueError, TypeError):
        return DEFAULT_SCORING_RULE['base_ratio'], DEFAULT_SCORING_RULE['speed_ratio']


def grade_objective(q_type, student_ans, correct_ans):
    """客观题判定，与 ai_service/services.py 的比对规则保持一致"""
    student_ans = (student_ans or '').strip()
    correct_ans = (correct_ans or '').strip()
    if q_type == 'multiple_choice':
        return ''.join(sorted(student_ans.upper())) == ''.join(sorted(correct_ans.upper()))
    if q_type == 'fill_blank':
        return student_ans.lower() == correct_ans.lower()
    return student_ans.upper() == correct_ans.upper()


def calc_question_score(full_score, is_correct, time_spent, per_question_seconds,
                        base_ratio, speed_ratio):
    """得分 = 满分 × base_ratio + 满分 × speed_ratio × 剩余时间比；答错 0 分"""
    if not is_correct:
        return 0.0
    ratio = base_ratio
    if speed_ratio > 0 and per_question_seconds > 0:
        remain = max(0.0, 1.0 - (time_spent or 0) / per_question_seconds)
        ratio += speed_ratio * remain
    return round(full_score * ratio, 2)


def validate_question_for_competition(question):
    """竞赛只允许客观题入库"""
    return question.type in COMPETITION_QUESTION_TYPES
