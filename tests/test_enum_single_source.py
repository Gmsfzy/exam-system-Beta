# -*- coding: utf-8 -*-
"""v4.6.1 枚举收敛回归门：题型/难度后端单一来源不漂移。

任何一侧新增值而未同步 label 表，本测试立即失败。
"""
import pytest

from database.models import DifficultyEnum, QuestionTypeEnum, _QUESTION_TYPE_LABELS


def _str_members(cls):
    return {v for k, v in vars(cls).items()
            if not k.startswith('_') and isinstance(v, str)}


def test_question_type_labels_cover_all_members():
    values = _str_members(QuestionTypeEnum)
    # 枚举成员必须全部有 label；允许额外历史兜底键（如 essay，与前端 enums.js 对齐）
    assert values <= set(_QUESTION_TYPE_LABELS), '题型枚举新增值未补 label'
    assert all(_QUESTION_TYPE_LABELS[v] != v for v in _QUESTION_TYPE_LABELS), \
        'label 不允许与值同义（漏翻译）'


def test_no_local_qtype_mapping_residue():
    """v4.7 收敛锁：后端不得再出现本地题型→中文字典（单一事实源）"""
    import pathlib
    suspects = ['competition/gamification_routes.py', 'ai_service/client.py',
                'api/question_routes.py', 'api/result_routes.py', 'api/ai_routes.py']
    for rel in suspects:
        text = pathlib.Path(rel).read_text(encoding='utf-8')
        assert "'multiple_choice': '多选题'" not in text, \
            f'{rel} 存在本地题型映射字典残留'
        assert "'单选题': 'single_choice'" not in text, \
            f'{rel} 存在本地题型反查字典残留'


def test_difficulty_labels_cover_all_members():
    values = _str_members(DifficultyEnum)
    assert set(DifficultyEnum.LABELS) == values, '难度 label 与枚举值集合不一致'


@pytest.mark.parametrize('qtype', sorted(_str_members(QuestionTypeEnum)))
def test_label_roundtrip(qtype):
    assert QuestionTypeEnum.label(qtype) == _QUESTION_TYPE_LABELS[qtype]


def test_label_fallback_returns_raw():
    assert QuestionTypeEnum.label('unknown_type') == 'unknown_type'
    assert DifficultyEnum.label('unknown') == 'unknown'


def test_subjective_set():
    for t in QuestionTypeEnum.SUBJECTIVE_TYPES:
        assert t in _str_members(QuestionTypeEnum)
    assert QuestionTypeEnum.is_subjective(QuestionTypeEnum.SHORT_ANSWER)
    assert not QuestionTypeEnum.is_subjective(QuestionTypeEnum.SINGLE_CHOICE)
