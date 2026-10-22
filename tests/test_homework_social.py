# -*- coding: utf-8 -*-
"""v5.4 讨论区 + v5.5 生生互评回归门（函数层，内存库）。

锁住：
1. 讨论楼层结构、身份快照、软删除内容替换、mine 标记；
2. 互评分配：排除自评、每人 N 份、唯一约束不重复；
3. 重新分配保留已提交互评、清空待办并避开已有评审组合；
4. 互评汇总完成率/每份均分/评审人进度；
5. 被评学生匿名结果（均分 + 评语，无 reviewer 身份）。

HTTP 往返（鉴权/通知/详情匿名字段）由 test_http_e2e 的社交链负责。
"""
import pytest

from database import db
from database.models import Question, Major, WrongAnswerRecord
from utils.timeutil import utcnow
from homework.models import (
    Homework, HomeworkQuestion, HomeworkStudent, HomeworkSubmission, HomeworkComment,
    HomeworkPeerReview, HomeworkAnswer, HomeworkGroup, HomeworkGroupMember,
    HomeworkStatusEnum, HomeworkTypeEnum, SubmissionStatusEnum,
    PeerReviewStatusEnum, PeerReviewAuditEnum,
)
from homework.services import (
    distribute_peer_reviews, peer_review_summary, peer_review_received,
    compute_peer_final_score, audit_peer_review,
    complete_peer_review_daily_task, sync_learning_effects,
    award_homework_submit_points, award_homework_grade_bonus,
    HOMEWORK_SUBMIT_POINTS,
)
from ledger.models import LedgerTxn
from competition.gamification import current_season
from competition.models import UserPointsProfile


@pytest.fixture()
def social_env(app, user_factory):
    teacher = user_factory('social_teacher', role='teacher')
    s1 = user_factory('social_s1')
    s2 = user_factory('social_s2')
    s3 = user_factory('social_s3')
    major = Major(name='社交作业专业')
    db.session.add(major)
    db.session.flush()
    q = Question(content='1+1=?', answer='B', type='single_choice',
                 difficulty='easy', major_id=major.id, options=['A. 1', 'B. 2'])
    db.session.add(q)
    db.session.commit()

    hw = Homework(title='社交作业', hw_type=HomeworkTypeEnum.QUESTION_SET,
                  teacher_id=teacher.id, status=HomeworkStatusEnum.PUBLISHED)
    db.session.add(hw)
    db.session.flush()
    db.session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id, score=10.0, order=0))
    for st in (s1, s2, s3):
        db.session.add(HomeworkStudent(homework_id=hw.id, student_id=st.id))
    db.session.commit()

    def submit(student, text='B'):
        sub = HomeworkSubmission(homework_id=hw.id, student_id=student.id,
                                 status=SubmissionStatusEnum.SUBMITTED,
                                 submitted_at=utcnow())
        db.session.add(sub)
        db.session.commit()
        return sub

    return {'teacher': teacher, 'students': (s1, s2, s3), 'hw': hw, 'q': q,
            'submit': submit}


def test_comment_thread_snapshot_and_soft_delete(social_env):
    hw, teacher, (s1, s2, _s3) = social_env['hw'], social_env['teacher'], social_env['students']
    top = HomeworkComment(homework_id=hw.id, user_id=s1.id, content='这道题怎么做？')
    db.session.add(top)
    db.session.flush()
    reply = HomeworkComment(homework_id=hw.id, user_id=teacher.id, parent_id=top.id,
                            content='先通分再相加', is_teacher=True)
    db.session.add(reply)
    db.session.commit()

    d = top.to_dict(current_user_id=s1.id)
    assert d['content'] == '这道题怎么做？' and d['mine'] is True
    assert d['is_teacher'] is False and d['parent_id'] is None
    rd = reply.to_dict(current_user_id=s2.id)
    assert rd['is_teacher'] is True and rd['mine'] is False

    top.deleted_at = utcnow()
    db.session.commit()
    deleted = top.to_dict(current_user_id=s1.id)
    assert deleted['deleted'] is True and deleted['content'] == '该评论已删除'


def test_distribute_excludes_self_and_respects_quota(social_env):
    hw = social_env['hw']
    subs = [social_env['submit'](st) for st in social_env['students']]
    result = distribute_peer_reviews(hw, per_submission=2)

    assert result['created'] == 6
    rows = HomeworkPeerReview.query.filter_by(homework_id=hw.id).all()
    assert len(rows) == 6
    for sub in subs:
        assigned = [r for r in rows if r.submission_id == sub.id]
        assert len(assigned) == 2
        assert all(r.reviewer_id != sub.student_id for r in assigned)
        assert len({r.reviewer_id for r in assigned}) == 2
    assert all(r.status == PeerReviewStatusEnum.PENDING for r in rows)


def test_redistribute_keeps_submitted_and_avoids_repeat(social_env):
    hw = social_env['hw']
    subs = [social_env['submit'](st) for st in social_env['students']]
    distribute_peer_reviews(hw, per_submission=2)
    kept = HomeworkPeerReview.query.filter_by(homework_id=hw.id).first()
    kept.status = PeerReviewStatusEnum.SUBMITTED
    kept.score = 88.0
    kept.submitted_at = utcnow()
    db.session.commit()
    kept_pair = (kept.submission_id, kept.reviewer_id)

    result = distribute_peer_reviews(hw, per_submission=2)
    rows = HomeworkPeerReview.query.filter_by(homework_id=hw.id).all()

    assert result['submitted_kept'] == 1
    assert all(r.status == PeerReviewStatusEnum.SUBMITTED
               for r in rows if (r.submission_id, r.reviewer_id) == kept_pair)
    assert sum(1 for r in rows if r.status == PeerReviewStatusEnum.SUBMITTED) == 1
    # 同一评审人不会在同一份提交上出现两次
    pairs = [(r.submission_id, r.reviewer_id) for r in rows]
    assert len(pairs) == len(set(pairs))
    assert all(tuple(p) != kept_pair or r.status == PeerReviewStatusEnum.SUBMITTED
               for p, r in zip(pairs, rows))


def test_distribute_requires_two_submissions(social_env):
    hw = social_env['hw']
    social_env['submit'](social_env['students'][0])
    result = distribute_peer_reviews(hw, per_submission=2)
    assert result['created'] == 0 and '至少需要 2 份' in result['error']
    assert HomeworkPeerReview.query.filter_by(homework_id=hw.id).count() == 0


def test_summary_and_anonymous_received(social_env):
    hw = social_env['hw']
    s1, s2, s3 = social_env['students']
    sub1 = social_env['submit'](s1)
    social_env['submit'](s2)
    social_env['submit'](s3)
    db.session.add_all([
        HomeworkPeerReview(homework_id=hw.id, submission_id=sub1.id,
                           reviewer_id=s2.id, status=PeerReviewStatusEnum.SUBMITTED,
                           score=80.0, comment='思路清晰', submitted_at=utcnow()),
        HomeworkPeerReview(homework_id=hw.id, submission_id=sub1.id,
                           reviewer_id=s3.id, status=PeerReviewStatusEnum.SUBMITTED,
                           score=90.0, comment='步骤可再精简', submitted_at=utcnow()),
        HomeworkPeerReview(homework_id=hw.id, submission_id=sub1.id,
                           reviewer_id=s1.id, status=PeerReviewStatusEnum.PENDING),
    ])
    db.session.commit()

    summary = peer_review_summary(hw)
    assert summary['total'] == 3 and summary['submitted'] == 2
    assert summary['completion_rate'] == 66.7
    row = next(x for x in summary['per_submission'] if x['submission_id'] == sub1.id)
    assert row['review_count'] == 3 and row['submitted_count'] == 2
    assert row['avg_score'] == 85.0 and row['username'] == 'social_s1'
    reviewer = next(x for x in summary['reviewers'] if x['reviewer_id'] == s2.id)
    assert reviewer['assigned'] == 1 and reviewer['submitted'] == 1
    assert reviewer['pending'] == 0

    received = peer_review_received(sub1)
    assert received['count'] == 2 and received['avg_score'] == 85.0
    assert received['comments'][0]['comment'] == '思路清晰'
    assert 'reviewer_id' not in received and all(
        'reviewer_id' not in c for c in received['comments'])


# ═══════════════════════ v5.9 深度互评 ═══════════════════════

def test_dimension_weighted_score():
    scores = {'accuracy': 100, 'completeness': 80, 'standard': 90, 'innovation': 60}
    # 0.4*100 + 0.3*80 + 0.2*90 + 0.1*60 = 88
    assert compute_peer_final_score(scores) == 88.0
    # 仅部分维度：按已填维度权重归一
    assert compute_peer_final_score({'accuracy': 100, 'completeness': 50}) == 78.57
    assert compute_peer_final_score({}) is None
    assert compute_peer_final_score({'accuracy': 120}) is None


def test_audit_accept_and_weighted_view_keeps_official_score(social_env):
    hw, (s1, s2, s3) = social_env['hw'], social_env['students']
    sub1 = social_env['submit'](s1)
    social_env['submit'](s2)
    social_env['submit'](s3)
    sub1.total_score = 70.0
    sub1.max_score = 100.0
    hw.peer_review_weight = 0.3
    dims = {'accuracy': 100, 'completeness': 80, 'standard': 90, 'innovation': 60}
    r1 = HomeworkPeerReview(homework_id=hw.id, submission_id=sub1.id, reviewer_id=s2.id,
                            status=PeerReviewStatusEnum.SUBMITTED, score=88.0,
                            scores_json=dims, submitted_at=utcnow())
    r2 = HomeworkPeerReview(homework_id=hw.id, submission_id=sub1.id, reviewer_id=s3.id,
                            status=PeerReviewStatusEnum.SUBMITTED, score=60.0,
                            scores_json={'accuracy': 60}, submitted_at=utcnow())
    db.session.add_all([r1, r2])
    db.session.commit()

    assert audit_peer_review(r1, 'accept', '客观准确', teacher_id=social_env['teacher'].id)['review']
    assert audit_peer_review(r2, 'reject', '打分偏低')['review']
    db.session.commit()
    assert r1.audit_status == PeerReviewAuditEnum.ACCEPTED
    assert r2.audit_status == PeerReviewAuditEnum.REJECTED

    received = peer_review_received(sub1)
    assert received['count'] == 2
    assert received['accepted_count'] == 1 and received['rejected_count'] == 1
    assert received['accepted_avg_score'] == 88.0
    assert received['weight'] == 0.3
    assert received['weighted_contribution'] == 26.4
    assert received['final_view_score'] == 96.4
    # 官方总分不被改写
    assert sub1.total_score == 70.0

    summary = peer_review_summary(hw)
    assert summary['accepted'] == 1 and summary['rejected'] == 1
    row = next(x for x in summary['per_submission'] if x['submission_id'] == sub1.id)
    assert row['peer_weighted_score'] == 26.4
    assert row['dimension_avg']['accuracy'] == 80.0
    assert summary['reviews'][0]['reviewer_name'] in ('social_s2', 'social_s3')
    assert summary['reviews'][0]['teacher_comment'] in ('客观准确', '打分偏低')


def test_distribute_creates_peer_daily_task_and_completes(social_env):
    from database.models import DailyTask

    hw = social_env['hw']
    for st in social_env['students']:
        social_env['submit'](st)
    result = distribute_peer_reviews(hw, per_submission=2)
    assert result['daily_tasks'] == 3
    tasks = DailyTask.query.filter_by(source='peer_review').all()
    assert len(tasks) == 3
    assert {t.user_id for t in tasks} == {s.id for s in social_env['students']}

    complete_peer_review_daily_task(hw, social_env['students'][0].id)
    db.session.commit()
    done = DailyTask.query.filter_by(user_id=social_env['students'][0].id,
                                     source='peer_review').first()
    assert done.status == 'done' and done.done_at is not None


# ═══════════ v5.9 作业 ↔ 错题本联动 + 积分入账 ═══════════

def test_group_homework_syncs_wrong_and_points_to_all_members(social_env):
    """小组作业：错题/掌握度/积分按全组成员落地，而不是只给最后提交人。"""
    hw, (s1, s2, s3), q = social_env['hw'], social_env['students'], social_env['q']
    hw.is_group = True
    grp = HomeworkGroup(homework_id=hw.id, name='A组')
    db.session.add(grp)
    db.session.flush()
    db.session.add_all([HomeworkGroupMember(group_id=grp.id, student_id=s1.id),
                        HomeworkGroupMember(group_id=grp.id, student_id=s2.id)])
    sub = HomeworkSubmission(homework_id=hw.id, student_id=s1.id, group_id=grp.id,
                             status=SubmissionStatusEnum.SUBMITTED, submitted_at=utcnow(),
                             max_score=10.0)
    db.session.add(sub)
    db.session.flush()
    db.session.add(HomeworkAnswer(submission_id=sub.id, question_id=q.id, answer='A',
                                  is_correct=False, auto_score=0.0,
                                  needs_manual_grade=False))
    db.session.commit()

    sync_learning_effects(hw, sub, scope='auto')
    assert WrongAnswerRecord.query.filter_by(user_id=s1.id, question_id=q.id).count() == 1
    assert WrongAnswerRecord.query.filter_by(user_id=s2.id, question_id=q.id).count() == 1
    assert WrongAnswerRecord.query.filter_by(user_id=s3.id, question_id=q.id).count() == 0

    assert award_homework_submit_points(hw, sub) == HOMEWORK_SUBMIT_POINTS * 2
    assert award_homework_submit_points(hw, sub) == 0   # 重交幂等


def test_submit_points_once_and_profile_mirror(social_env):
    hw, s1 = social_env['hw'], social_env['students'][0]
    sub = social_env['submit'](s1)

    assert award_homework_submit_points(hw, sub) == HOMEWORK_SUBMIT_POINTS
    assert award_homework_submit_points(hw, sub) == 0

    rows = LedgerTxn.query.filter_by(user_id=s1.id, ref_type='homework', ref_id=hw.id).all()
    assert len(rows) == 1 and rows[0].currency == 'points' and rows[0].delta == 10
    profile = UserPointsProfile.query.filter_by(
        user_id=s1.id, season=current_season()).first()
    assert profile is not None and profile.points == HOMEWORK_SUBMIT_POINTS


def test_grade_bonus_by_score_ratio_and_idempotent(social_env):
    hw, s1 = social_env['hw'], social_env['students'][0]
    sub = social_env['submit'](s1)
    sub.status = SubmissionStatusEnum.GRADED
    sub.total_score = 8.0
    sub.max_score = 10.0
    db.session.commit()

    assert award_homework_grade_bonus(hw, sub) == 16   # 20 × 80%
    assert award_homework_grade_bonus(hw, sub) == 0    # 重批不重复
    profile = UserPointsProfile.query.filter_by(
        user_id=s1.id, season=current_season()).first()
    assert profile.points == 16
