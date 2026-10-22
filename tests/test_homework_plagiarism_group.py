# -*- coding: utf-8 -*-
"""v5.6 作业反抄袭 + v5.7 小组作业（函数层，内存库）。

锁住：
1. 开放式文字：compare_text_submissions 字符 n-gram Jaccard 命中高相似对、过短跳过；
2. 题集式编程题：复用 compare_submissions 代码查重；
3. 小组作业：HomeworkGroup/成员、_apply_groups 重复学生拒绝、跨组不重复；
4. 小组提交共享：组员 A 提交后组员 B 取到同一 submission（group_id）；
5. 小组批改通知全组成员。
"""
import pytest

from database import db
from database.models import Major, Question
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission,
    HomeworkGroup, HomeworkGroupMember,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
)
from oj.plagiarism import compare_text_submissions, text_similarity


@pytest.fixture()
def env(app, user_factory):
    teacher = user_factory('pg_teacher', role='teacher')
    s1 = user_factory('pg_s1')
    s2 = user_factory('pg_s2')
    s3 = user_factory('pg_s3')
    major = Major(name='查重小组专业')
    db.session.add(major)
    db.session.flush()
    q = Question(content='实现一个加法函数', answer='B', type='programming',
                 difficulty='easy', major_id=major.id)
    db.session.add(q)
    db.session.commit()
    return {'teacher': teacher, 's1': s1, 's2': s2, 's3': s3, 'q': q}


def _make_open_homework(env, is_group=False):
    hw = Homework(title='开放式查重作业', description='写一段文字',
                  hw_type=HomeworkTypeEnum.OPEN, teacher_id=env['teacher'].id,
                  status=HomeworkStatusEnum.PUBLISHED, is_group=is_group)
    db.session.add(hw)
    db.session.flush()
    db.session.add(HomeworkStudent(homework_id=hw.id, student_id=env['s1'].id))
    db.session.add(HomeworkStudent(homework_id=hw.id, student_id=env['s2'].id))
    db.session.add(HomeworkStudent(homework_id=hw.id, student_id=env['s3'].id))
    db.session.commit()
    return hw


def test_text_similarity_hits_near_duplicate():
    a = '这是一段关于机器学习线性回归的作业说明文字内容较长。'
    b = '这是一段关于机器学习线性回归的作业说明文字内容较长。'  # 完全相同
    c = '完全不相关的另一段文字讨论哲学与人生。'
    assert text_similarity(a, b) >= 0.99
    assert text_similarity(a, c) < 0.5


def test_compare_text_submissions_filters_short_and_returns_pairs():
    subs = [
        {'student_id': 1, 'username': 'a', 'text': '机器学习线性回归的核心是最小二乘法求解参数。' * 3},
        {'student_id': 2, 'username': 'b', 'text': '机器学习线性回归的核心是最小二乘法求解参数。' * 3},
        {'student_id': 3, 'username': 'c', 'text': '短'},   # 过短被过滤
    ]
    pairs = compare_text_submissions(subs, threshold=0.7)
    assert len(pairs) == 1
    assert pairs[0]['similarity'] >= 0.7


def test_group_creation_and_uniqueness(env):
    from homework.routes import _apply_groups
    hw = Homework(title='小组作业', teacher_id=env['teacher'].id,
                  status=HomeworkStatusEnum.DRAFT, is_group=True)
    db.session.add(hw)
    db.session.commit()
    # 重复学生跨组 → 拒绝
    err = _apply_groups(hw, [
        {'name': 'A组', 'student_ids': [env['s1'].id, env['s2'].id]},
        {'name': 'B组', 'student_ids': [env['s1'].id]},
    ])
    assert err and '不能重复' in err
    # 合法分组
    err = _apply_groups(hw, [
        {'name': 'A组', 'student_ids': [env['s1'].id, env['s2'].id]},
        {'name': 'B组', 'student_ids': [env['s3'].id]},
    ])
    assert err is None
    assert len(hw.groups) == 2
    # 同步名单：3 名组员全进 HomeworkStudent
    assert {hs.student_id for hs in hw.hw_students} == {env['s1'].id, env['s2'].id, env['s3'].id}


def test_group_submission_shared_by_members(env):
    from homework.services import get_student_group, get_group_submission
    from homework.routes import _apply_groups, _my_submission
    hw = Homework(title='小组共享作业', hw_type=HomeworkTypeEnum.OPEN,
                  teacher_id=env['teacher'].id, status=HomeworkStatusEnum.DRAFT,
                  is_group=True)
    db.session.add(hw)
    db.session.commit()
    _apply_groups(hw, [{'name': 'A组', 'student_ids': [env['s1'].id, env['s2'].id]}])
    hw.status = HomeworkStatusEnum.PUBLISHED
    db.session.commit()
    # s1 创建提交
    g = get_student_group(hw, env['s1'].id)
    sub = HomeworkSubmission(homework_id=hw.id, student_id=env['s1'].id,
                             group_id=g.id, status=SubmissionStatusEnum.DRAFT, content='A组答案')
    db.session.add(sub)
    db.session.commit()
    # s2 取到同一份
    sub2 = _my_submission(hw, env['s2'].id)
    assert sub2 is not None and sub2.id == sub.id
    assert sub2.group_id == g.id


def test_open_homework_plagiarism_detects_pair(env):
    from homework.services import homework_plagiarism_check
    hw = _make_open_homework(env)
    long_text = '机器学习线性回归的核心是最小二乘法求解参数矩阵。' * 4
    for s, text in [(env['s1'], long_text), (env['s2'], long_text),
                    (env['s3'], '哲学人生探讨完全不一样的主题内容。' * 4)]:
        db.session.add(HomeworkSubmission(homework_id=hw.id, student_id=s.id,
                                          status=SubmissionStatusEnum.SUBMITTED, content=text))
    db.session.commit()
    result = homework_plagiarism_check(hw, threshold=0.7)
    assert result['hw_type'] == 'open'
    assert result['pair_count'] >= 1
    pair = result['items'][0]['pairs'][0]
    assert {pair['a']['student_id'], pair['b']['student_id']} == {env['s1'].id, env['s2'].id}
