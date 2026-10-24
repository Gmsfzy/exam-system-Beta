# -*- coding: utf-8 -*-
"""v5.23 题目标签系统：纯校验函数 + 模型列/查询级回归门（内存库）。

锁定语义：
1. _clean_tag/_normalize_tags：strip、去空、去重保序、单项≤20、总≤10、拒斜杠、
   兼容 JSON 字符串；非法一律抛 ValueError；
2. Question.tags 与 knowledge 正交：写 tags 不改 knowledge，未设 tags 存 NULL；
3. 查询级筛选 LIKE '%%"tag"%%' 精确命中数组元素，不误命中子串；
4. 标签云 Counter 聚合计数正确。
端点/权限侧（协同加/删除/角色门禁/?tag= 往返/非法 400）由 test_http_e2e 覆盖。
"""
import pytest

from database import db
from database.models import Question, Major
from api.question_routes import _clean_tag, _normalize_tags


def test_clean_tag_rules():
    assert _clean_tag('  易错  ') == '易错'                 # strip
    assert _clean_tag('   ', allow_empty=True) == ''        # 空 + allow_empty
    with pytest.raises(ValueError):
        _clean_tag('')          # 空且非 allow_empty
    with pytest.raises(ValueError):
        _clean_tag('超' * 21)    # 单项 > 20 字
    with pytest.raises(ValueError):
        _clean_tag('a/b')        # 含斜杠（保证 URL path 安全）


def test_normalize_tags_semantics():
    assert _normalize_tags(None) == []
    assert _normalize_tags([]) == []
    assert _normalize_tags(['a', ' a ', 'b', '']) == ['a', 'b']   # 去空去重保序
    assert _normalize_tags('["x", "y"]') == ['x', 'y']             # 兼容 JSON 字符串
    assert _normalize_tags([str(i) for i in range(1, 11)]) == [str(i) for i in range(1, 11)]  # 恰好 10 个
    with pytest.raises(ValueError):
        _normalize_tags([str(i) for i in range(1, 12)])             # 11 个超限
    with pytest.raises(ValueError):
        _normalize_tags({'a': 1})                                   # dict 非法
    with pytest.raises(ValueError):
        _normalize_tags('not-json')                                  # 非数组字符串


def test_tags_orthogonal_to_knowledge(app, user_factory):
    """tags 列独立于 knowledge：写 tags 不动知识点，未设 tags 存 NULL（序列化层按 [] 回显）。"""
    major = Major(name='t523专业')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('t523_teacher', role='teacher')
    q = Question(content='q?', answer='B', type='single_choice', difficulty='easy',
                 major_id=major.id, creator_id=teacher.id,
                 knowledge='极限,导数', tags=['易错', '高频'])
    db.session.add(q)
    db.session.commit()
    got = db.session.get(Question, q.id)
    assert got.tags == ['易错', '高频']
    assert got.knowledge == '极限,导数'          # 正交：tags 未污染 knowledge

    q2 = Question(content='q2', answer='A', type='single_choice', difficulty='easy',
                  major_id=major.id, creator_id=teacher.id)
    db.session.add(q2)
    db.session.commit()
    assert db.session.get(Question, q2.id).tags is None


def test_tag_like_filter(app, user_factory):
    """复现端点里的 LIKE '%%"标签"%%' 表达式：精确命中数组元素，不误命中子串。"""
    major = Major(name='t523f')
    db.session.add(major)
    db.session.flush()
    t = user_factory('t523_ft', role='teacher')
    for tags in (['易错', '高频'], ['计算'], None):
        db.session.add(Question(content='c', answer='A', type='single_choice',
                                difficulty='easy', major_id=major.id, creator_id=t.id, tags=tags))
    db.session.commit()

    hit = Question.query.filter(Question.tags.like('%"高频"%')).all()
    assert len(hit) == 1 and hit[0].tags == ['易错', '高频']
    # 子串不误命中："高"（非 "高频"）不应命中
    assert Question.query.filter(Question.tags.like('%"高"%')).count() == 0
    assert Question.query.filter(Question.tags.like('%"计算"%')).count() == 1


def test_tag_cloud_counter(app, user_factory):
    """标签云 Counter 聚合（复现端点口径）。"""
    from collections import Counter
    major = Major(name='t523c')
    db.session.add(major)
    db.session.flush()
    t = user_factory('t523_ct', role='teacher')
    for tags in (['hot', '错题'], ['hot'], ['new'], None):
        db.session.add(Question(content='c', answer='A', type='single_choice',
                                difficulty='easy', major_id=major.id, creator_id=t.id, tags=tags))
    db.session.commit()
    counter = Counter()
    for (row_tags,) in db.session.query(Question.tags).all():
        for tag in (row_tags or []):
            counter[tag] += 1
    assert counter['hot'] == 2
    assert counter['错题'] == 1
    assert counter['new'] == 1
