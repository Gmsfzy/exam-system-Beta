# -*- coding: utf-8 -*-
"""v5.8 作业模板与系列化：函数层回归门。

锁住：
1. 模板抽题：按 filters（专业/题型/难度）抽题，count 或 distribution；
2. 模板生成作业：抽题+名单+deadline_hours，标题带系列序号；
3. 系列 tick：到达计划时间自动生成并发布、建 DailyTask、通知，generated_count 累加，全完成置 COMPLETED；
4. 提交时完成对应 DailyTask（幂等）；
5. 周清单聚合本周已发布作业。
"""
from datetime import timedelta

import pytest

from database import db
from database.models import Question, User, DailyTask, Major
from utils.timeutil import utcnow, local_today
from homework.models import (
    Homework, HomeworkStatusEnum, HomeworkTypeEnum,
    HomeworkTemplate, HomeworkSeries, HomeworkSeriesStatusEnum,
)
from homework.services import (
    _pick_questions_by_template, generate_homework_from_template,
    homework_series_tick, complete_homework_daily_task,
)


@pytest.fixture()
def env(app, user_factory):
    major = Major(name='TS专业')
    db.session.add(major)
    db.session.flush()
    teacher = user_factory('ts_teacher', role='teacher')
    s1 = user_factory('ts_student_1')
    s2 = user_factory('ts_student_2')

    def q(content, qtype, difficulty='easy', major_id=None):
        row = Question(content=content, answer='A', type=qtype, difficulty=difficulty,
                       major_id=major_id or major.id,
                       options=['A. 对', 'B. 错'] if qtype in ('single_choice', 'true_false') else None)
        db.session.add(row)
        return row

    # 10 道题：6 单选 + 4 判断；难度各半
    questions = []
    for i in range(6):
        questions.append(q(f'单选{i}', 'single_choice', 'easy' if i < 3 else 'hard'))
    for i in range(4):
        questions.append(q(f'判断{i}', 'true_false', 'easy' if i < 2 else 'hard'))
    db.session.flush()
    return {'teacher': teacher, 's1': s1, 's2': s2, 'major': major, 'questions': questions}


def test_pick_by_count_and_type(env):
    picked = _pick_questions_by_template({'filters': {'types': ['single_choice']}, 'count': 3})
    assert len(picked) == 3
    assert all(p.type == 'single_choice' for p in picked)

    picked = _pick_questions_by_template({'filters': {'difficulty': 'hard'}, 'count': 2})
    assert len(picked) == 2
    assert all(p.difficulty == 'hard' for p in picked)


def test_pick_distribution(env):
    config = {'filters': {}, 'distribution': [
        {'difficulty': 'easy', 'count': 2},
        {'difficulty': 'hard', 'count': 2}]}
    picked = _pick_questions_by_template(config)
    assert len(picked) == 4
    assert sum(1 for p in picked if p.difficulty == 'easy') == 2
    assert sum(1 for p in picked if p.difficulty == 'hard') == 2


def test_pick_count_clamped_to_pool(env):
    # 池子只有 4 道判断，要 10 道会自动 clamp
    picked = _pick_questions_by_template({'filters': {'types': ['true_false']}, 'count': 10})
    assert len(picked) == 4


def test_generate_from_template(env):
    template = HomeworkTemplate(
        teacher_id=env['teacher'].id, title='每日一练',
        config_json={'filters': {'types': ['single_choice']}, 'count': 2, 'default_score': 5},
        settings_json={'deadline_hours': 24},
        roster_json=[env['s1'].id, env['s2'].id])
    db.session.add(template)
    db.session.flush()

    hw, err = generate_homework_from_template(template, env['teacher'].id)
    assert err is None
    assert hw.hw_type == HomeworkTypeEnum.QUESTION_SET
    assert len(hw.hw_questions) == 2
    assert len(hw.hw_students) == 2
    assert hw.deadline is not None
    assert hw.status == HomeworkStatusEnum.DRAFT


def test_generate_series_title_with_index(env):
    template = HomeworkTemplate(
        teacher_id=env['teacher'].id, title='每日一练',
        config_json={'filters': {}, 'count': 1, 'default_score': 5},
        settings_json={}, roster_json=[env['s1'].id])
    db.session.add(template)
    db.session.flush()

    hw, err = generate_homework_from_template(template, env['teacher'].id, index=3, series_id=99)
    assert err is None
    assert hw.series_id == 99
    assert '4' in hw.title   # 系列时标题带序号 (index+1)


def test_series_tick_generates_due_homeworks(env):
    template = HomeworkTemplate(
        teacher_id=env['teacher'].id, title='每日一练',
        config_json={'filters': {}, 'count': 1, 'default_score': 5},
        settings_json={'deadline_hours': 24},
        roster_json=[env['s1'].id, env['s2'].id])
    db.session.add(template)
    db.session.flush()

    # start_at 在过去，count=2，interval=24h → 两份都到期
    series = HomeworkSeries(
        teacher_id=env['teacher'].id, template_id=template.id, title='周系列',
        start_at=utcnow() - timedelta(hours=48), interval_hours=24, count=2,
        status=HomeworkSeriesStatusEnum.ACTIVE)
    db.session.add(series)
    db.session.commit()

    homework_series_tick()
    db.session.refresh(series)
    assert series.generated_count == 2
    assert series.status == HomeworkSeriesStatusEnum.COMPLETED

    hws = Homework.query.filter_by(series_id=series.id).order_by(Homework.id).all()
    assert len(hws) == 2
    assert all(hw.status == HomeworkStatusEnum.PUBLISHED for hw in hws)

    # 两份作业 × 2 名学生 = 4 个 DailyTask
    tasks = DailyTask.query.filter(
        DailyTask.user_id.in_([env['s1'].id, env['s2'].id]),
        DailyTask.day == local_today()).all()
    assert len(tasks) == 4
    assert tasks[0].title.startswith('作业：')


def test_series_tick_not_premature(env):
    template = HomeworkTemplate(
        teacher_id=env['teacher'].id, title='未来',
        config_json={'filters': {}, 'count': 1},
        settings_json={}, roster_json=[env['s1'].id])
    db.session.add(template)
    db.session.flush()

    series = HomeworkSeries(
        teacher_id=env['teacher'].id, template_id=template.id, title='未来系列',
        start_at=utcnow() + timedelta(days=7), interval_hours=24, count=3,
        status=HomeworkSeriesStatusEnum.ACTIVE)
    db.session.add(series)
    db.session.commit()

    homework_series_tick()
    db.session.refresh(series)
    assert series.generated_count == 0
    assert series.status == HomeworkSeriesStatusEnum.ACTIVE
    assert Homework.query.filter_by(series_id=series.id).count() == 0


def test_complete_daily_task_on_submit(env):
    template = HomeworkTemplate(
        teacher_id=env['teacher'].id, title='每日一练',
        config_json={'filters': {}, 'count': 1, 'default_score': 5},
        settings_json={}, roster_json=[env['s1'].id])
    db.session.add(template)
    db.session.flush()

    hw, _ = generate_homework_from_template(template, env['teacher'].id)
    hw.status = HomeworkStatusEnum.PUBLISHED
    hw.published_at = utcnow()
    db.session.commit()

    from homework.services import _create_daily_tasks_for_homework
    _create_daily_tasks_for_homework(hw)
    db.session.commit()

    task = DailyTask.query.filter_by(user_id=env['s1'].id, day=local_today()).first()
    assert task is not None
    assert task.status == 'pending'

    complete_homework_daily_task(hw, env['s1'].id)
    db.session.refresh(task)
    assert task.status == 'done'

    # 幂等：重复调用不报错
    complete_homework_daily_task(hw, env['s1'].id)


def test_weekly_list_query(env):
    template = HomeworkTemplate(
        teacher_id=env['teacher'].id, title='本周作业',
        config_json={'filters': {}, 'count': 1},
        settings_json={}, roster_json=[env['s1'].id])
    db.session.add(template)
    db.session.flush()

    hw, _ = generate_homework_from_template(template, env['teacher'].id)
    hw.status = HomeworkStatusEnum.PUBLISHED
    hw.published_at = utcnow()
    db.session.commit()

    from datetime import timedelta
    now = utcnow()
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    from homework.models import HomeworkStudent
    hws = Homework.query.join(HomeworkStudent, HomeworkStudent.homework_id == Homework.id) \
        .filter(HomeworkStudent.student_id == env['s1'].id,
                Homework.status == HomeworkStatusEnum.PUBLISHED,
                Homework.published_at >= week_start,
                Homework.published_at < week_end).all()
    assert len(hws) == 1
    assert hws[0].id == hw.id
