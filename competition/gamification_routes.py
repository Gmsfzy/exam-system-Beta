# -*- coding: utf-8 -*-
"""竞技化路由：段位 / 赛季 / 勋章 / 学情画像"""
from datetime import timedelta

from flask import Blueprint, request, jsonify

from database import db
from database.models import User, Exam, ExamQuestion, ExamSession, Answer, Question, Result
from utils.timeutil import utcnow, iso_local
from utils.security import verify_token
from competition.models import (
    UserPointsProfile, SeasonMeta, SeasonArchive, UserBadge,
    Competition, CompetitionParticipant, CompetitionQuestion, CompetitionAnswer,
    PkBattle, PkAnswer, PkBattleStatusEnum, ParticipantStatusEnum,
)
from competition.gamification import (
    TIERS, TIER_COLORS, tier_of, tier_progress, current_season,
    ensure_profile, season_rank_of, check_and_grant, BADGE_DEFS,
)

gamification_bp = Blueprint('gamification', __name__)

QTYPE_LABELS = {
    'single_choice': '单选题', 'multiple_choice': '多选题', 'true_false': '判断题',
    'fill_blank': '填空题', 'short_answer': '简答题', 'essay': '论述题',
    'calculation': '计算题', 'programming': '编程题',
}


# ═══════════════ 段位 / 赛季 ═══════════════
# 注：过期竞赛结算 / 赛季归档已迁移到 utils.scheduler 后台线程，
# 请求路径不再执行 _gate()，避免每请求查 DB 与并发竞态。

@gamification_bp.route('/rank/me', methods=['GET'])
def rank_me():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    season = current_season()
    p = ensure_profile(user.id, season)
    rank = season_rank_of(user.id, season)
    total_players = UserPointsProfile.query.filter_by(season=season).count()
    return jsonify({
        'season': season,
        'tier_progress': tier_progress(p.points),
        'stats': p.to_dict(),
        'rank': rank,
        'total_players': total_players,
    })


@gamification_bp.route('/rank/seasons', methods=['GET'])
def rank_seasons():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    metas = SeasonMeta.query.order_by(SeasonMeta.season.desc()).all()
    return jsonify([{'season': m.season, 'archived': m.archived} for m in metas])


@gamification_bp.route('/rank/season/<season>', methods=['GET'])
def rank_season(season):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401

    meta = SeasonMeta.query.filter_by(season=season).first()
    board, my = [], None
    if meta and meta.archived:
        rows = (SeasonArchive.query.filter_by(season=season)
                .order_by(SeasonArchive.rank.asc())
                .limit(100).all())
        board = [{
            'rank': a.rank, 'user_id': a.user_id, 'username': a.user.username,
            'points': a.points, 'tier': a.tier,
            'pk_win': a.pk_win, 'pk_total': a.pk_total,
            'timed_finished': a.timed_finished,
        } for a in rows]
        mine = next((b for b in board if b['user_id'] == user.id), None)
        if mine is None:
            own = SeasonArchive.query.filter_by(season=season, user_id=user.id).first()
            mine = ({'rank': own.rank, 'user_id': own.user_id,
                     'username': own.user.username, 'points': own.points,
                     'tier': own.tier, 'pk_win': own.pk_win,
                     'pk_total': own.pk_total, 'timed_finished': own.timed_finished}
                    if own else None)
        my = mine
    else:
        profiles = (UserPointsProfile.query.filter_by(season=season)
                    .order_by(UserPointsProfile.points.desc(),
                              UserPointsProfile.last_played_at.asc())
                    .limit(100).all())
        prev_key, rank = None, 0
        for i, p in enumerate(profiles, start=1):
            key = (p.points, p.last_played_at)
            if key != prev_key:
                rank, prev_key = i, key
            board.append({
                'rank': rank, 'user_id': p.user_id, 'username': p.user.username,
                'points': p.points, 'tier': tier_of(p.points),
                'pk_win': p.pk_win, 'pk_total': p.pk_win + p.pk_lose + p.pk_draw,
                'timed_finished': p.timed_finished,
            })
        my = next((b for b in board if b['user_id'] == user.id), None)
    return jsonify({'season': season, 'leaderboard': board, 'me': my})


@gamification_bp.route('/rank/archives', methods=['GET'])
def rank_archives():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    rows = (SeasonArchive.query.filter_by(user_id=user.id)
            .order_by(SeasonArchive.season.desc()).all())
    return jsonify([{
        'season': a.season, 'rank': a.rank, 'points': a.points, 'tier': a.tier,
        'pk_win': a.pk_win, 'pk_total': a.pk_total, 'timed_finished': a.timed_finished,
    } for a in rows])


# ═══════════════ 勋章 ═══════════════

@gamification_bp.route('/badges/me', methods=['GET'])
def badges_me():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    mine = UserBadge.query.filter_by(user_id=user.id).all()
    mine_map = {b.badge_code: b for b in mine}
    # 合并悬赏模块勋章定义（独立模块，防御性导入）
    all_badge_defs = dict(BADGE_DEFS)
    try:
        from bounty.rewards import BOUNTY_BADGES
        all_badge_defs.update(BOUNTY_BADGES)
    except ImportError:
        pass
    all_defs = []
    for code, d in all_badge_defs.items():
        b = mine_map.get(code)
        all_defs.append({
            'code': code, 'name': d['name'], 'description': d['description'],
            'icon': d['icon'], 'granted': b is not None,
            'granted_at': iso_local(b.granted_at) if b else None,
            'season': b.season if b else None,
        })
    all_defs.sort(key=lambda x: (not x['granted'], x['code']))
    return jsonify({'all': all_defs})


# ═══════════════ 学情画像 ═══════════════

def _exam_profile(student_id):
    """考试侧：趋势 + 题型统计"""
    rows = (db.session.query(Result, Exam.title.label('title'))
            .join(Exam, Exam.id == Result.exam_id)
            .filter(Result.student_id == student_id)
            .order_by(Result.submitted_at.asc()).all())
    trend = []
    for r, title in rows:
        rate = round(r.score / r.total_score, 4) if r.total_score > 0 else 0
        trend.append({
            'exam_id': r.exam_id,
            'title': title or '',
            'score': r.score, 'total_score': r.total_score,
            'score_rate': rate,
            'submitted_at': iso_local(r.submitted_at) if r.submitted_at else None,
        })
    avg_rate = (round(sum(t['score_rate'] for t in trend) / len(trend), 4)
                if trend else None)

    # 题型统计：Answer → session(学生) → Question.type；得分率按 ExamQuestion 分值加权
    rows = (db.session.query(
                Question.type.label('q_type'),
                db.func.count(Answer.id).label('total'),
                db.func.sum(db.case((Answer.is_correct.is_(True), 1), else_=0)).label('correct'),
                db.func.sum(db.func.coalesce(Answer.manual_score, Answer.score, 0)
                            * db.func.coalesce(ExamQuestion.score, 1)).label('got'),
                db.func.sum(ExamQuestion.score).label('full'),
            )
            .join(ExamSession, ExamSession.id == Answer.session_id)
            .join(Question, Question.id == Answer.question_id)
            .outerjoin(ExamQuestion, db.and_(
                ExamQuestion.exam_id == ExamSession.exam_id,
                ExamQuestion.question_id == Answer.question_id))
            .filter(ExamSession.student_id == student_id)
            .group_by(Question.type).all())
    type_stats = []
    for r in rows:
        type_stats.append({
            'q_type': r.q_type,
            'label': QTYPE_LABELS.get(r.q_type, r.q_type),
            'total': int(r.total or 0),
            'correct': int(r.correct or 0),
            'accuracy': round(int(r.correct or 0) / r.total, 4) if r.total else 0,
            'score_rate': round(float(r.got or 0) / float(r.full), 4) if r.full else None,
        })
    return {'exam_count': len(trend), 'avg_score_rate': avg_rate,
            'trend': trend, 'type_stats': type_stats}


def _competition_profile(student_id, season):
    """竞赛侧：段位积分 + PK + 题型 + 速度 + 近期战绩"""
    p = UserPointsProfile.query.filter_by(user_id=student_id, season=season).first()
    pk_total = PkBattle.query.filter(
        PkBattle.status == PkBattleStatusEnum.FINISHED,
        (PkBattle.challenger_id == student_id) | (PkBattle.opponent_id == student_id),
    ).count()
    pk_win = PkBattle.query.filter(
        PkBattle.status == PkBattleStatusEnum.FINISHED,
        PkBattle.winner_id == student_id).count()

    # 竞赛题型正确率：CompetitionAnswer（限时赛）+ PkAnswer
    comp_rows = (db.session.query(
                     CompetitionQuestion.q_type.label('q_type'),
                     db.func.count(CompetitionAnswer.id).label('total'),
                     db.func.sum(db.case((CompetitionAnswer.is_correct.is_(True), 1), else_=0))
                     .label('correct'))
                 .join(CompetitionAnswer, CompetitionAnswer.cq_id == CompetitionQuestion.id)
                 .join(CompetitionParticipant,
                       CompetitionParticipant.id == CompetitionAnswer.participant_id)
                 .filter(CompetitionParticipant.user_id == student_id)
                 .group_by(CompetitionQuestion.q_type).all())
    pk_rows = (db.session.query(
                   CompetitionQuestion.q_type.label('q_type'),
                   db.func.count(PkAnswer.id).label('total'),
                   db.func.sum(db.case((PkAnswer.is_correct.is_(True), 1), else_=0))
                   .label('correct'))
               .join(PkAnswer, PkAnswer.cq_id == CompetitionQuestion.id)
               .filter(PkAnswer.player_id == student_id)
               .group_by(CompetitionQuestion.q_type).all())
    merged = {}
    for r in list(comp_rows) + list(pk_rows):
        m = merged.setdefault(r.q_type, {'total': 0, 'correct': 0})
        m['total'] += int(r.total or 0)
        m['correct'] += int(r.correct or 0)
    type_stats = [{
        'q_type': k, 'label': QTYPE_LABELS.get(k, k),
        'total': v['total'], 'correct': v['correct'],
        'accuracy': round(v['correct'] / v['total'], 4) if v['total'] else 0,
    } for k, v in merged.items()]

    speed_row = db.session.query(
        db.func.avg(CompetitionAnswer.time_spent)
    ).join(CompetitionParticipant,
           CompetitionParticipant.id == CompetitionAnswer.participant_id
           ).filter(CompetitionParticipant.user_id == student_id).scalar()
    pk_speed = db.session.query(db.func.avg(PkAnswer.time_spent)).filter(
        PkAnswer.player_id == student_id).scalar()
    speeds = [float(s) for s in (speed_row, pk_speed) if s is not None]
    avg_speed = round(sum(speeds) / len(speeds), 1) if speeds else None

    # 近 5 场战绩（限时赛完赛 + PK 结算）
    recent = []
    finishes = (CompetitionParticipant.query
                .filter_by(user_id=student_id,
                           status=ParticipantStatusEnum.FINISHED)
                .order_by(CompetitionParticipant.finished_at.desc())
                .limit(5).all())
    for f in finishes:
        recent.append({
            'kind': 'timed', 'at': iso_local(f.finished_at) if f.finished_at else None,
            'title': f.competition.title if f.competition else '',
            'score': f.score, 'rank': None,
        })
    battles = (PkBattle.query
               .filter(PkBattle.status == PkBattleStatusEnum.FINISHED,
                       (PkBattle.challenger_id == student_id) |
                       (PkBattle.opponent_id == student_id))
               .order_by(PkBattle.finished_at.desc()).limit(5).all())
    for b in battles:
        recent.append({
            'kind': 'pk', 'at': iso_local(b.finished_at) if b.finished_at else None,
            'title': b.competition.title if b.competition else '',
            'score': b.challenger_score if b.challenger_id == student_id else b.opponent_score,
            'result': ('win' if b.winner_id == student_id
                       else 'draw' if b.winner_id is None else 'lose'),
        })
    recent.sort(key=lambda x: x['at'] or '', reverse=True)
    recent = recent[:5]

    return {
        'season': season,
        'points': p.points if p else 0,
        'tier': tier_of(p.points) if p else tier_of(0),
        'rank': season_rank_of(student_id, season),
        'pk': {'total': pk_total, 'win': pk_win,
               'lose': pk_total - pk_win if pk_total else 0,
               'win_rate': round(pk_win / pk_total, 4) if pk_total else None},
        'timed_finished': p.timed_finished if p else 0,
        'type_stats': type_stats,
        'avg_speed_seconds': avg_speed,
        'recent': recent,
    }


def _radar(student_id, exam, comp):
    """综合五维：准确率 / 速度 / 竞技力 / 稳定度 / 活跃度"""
    all_total = sum(t['total'] for t in exam['type_stats']) + \
        sum(t['total'] for t in comp['type_stats'])
    all_correct = sum(t['correct'] for t in exam['type_stats']) + \
        sum(t['correct'] for t in comp['type_stats'])
    accuracy = round(all_correct / all_total * 100) if all_total else None

    speed = None
    if comp['avg_speed_seconds'] is not None:
        speed = max(0, round(100 - comp['avg_speed_seconds'] / 60 * 100))

    competitive = min(100, round(comp['points'] / 10))

    stability = None
    if len(exam['trend']) >= 3:
        rates = [t['score_rate'] for t in exam['trend']]
        mean = sum(rates) / len(rates)
        std = (sum((r - mean) ** 2 for r in rates) / len(rates)) ** 0.5
        stability = max(0, round(100 - std * 200))

    since = utcnow() - timedelta(days=30)
    timed_n = CompetitionParticipant.query.filter(
        CompetitionParticipant.user_id == student_id,
        CompetitionParticipant.status == ParticipantStatusEnum.FINISHED,
        CompetitionParticipant.finished_at >= since).count()
    pk_n = PkBattle.query.filter(
        PkBattle.status == PkBattleStatusEnum.FINISHED,
        (PkBattle.challenger_id == student_id) |
        (PkBattle.opponent_id == student_id),
        PkBattle.finished_at >= since).count()
    exam_n = ExamSession.query.filter(
        ExamSession.student_id == student_id,
        ExamSession.status == 'submitted',
        ExamSession.end_time >= since).count()
    activity = min(100, (timed_n + pk_n + exam_n) * 12)

    return {'accuracy': accuracy, 'speed': speed, 'competitive': competitive,
            'stability': stability, 'activity': activity}


@gamification_bp.route('/profile/study', methods=['GET'])
def study_profile_me():
    user = verify_token()
    if not user or not user.is_student():
        return jsonify({'message': '无权访问'}), 403
    return jsonify(_build_study_profile(user.id))


@gamification_bp.route('/profile/study/<int:student_id>', methods=['GET'])
def study_profile_of(student_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    if not user.is_teacher():
        return jsonify({'message': '仅教师可查询他人画像'}), 403
    target = db.session.get(User, student_id)
    if not target or not target.is_student():
        return jsonify({'message': '学生不存在'}), 404
    return jsonify(_build_study_profile(student_id))


def _build_study_profile(student_id):
    season = current_season()
    exam = _exam_profile(student_id)
    comp = _competition_profile(student_id, season)
    radar = _radar(student_id, exam, comp)
    student = db.session.get(User, student_id)
    return {
        'student': {'id': student_id, 'username': student.username if student else ''},
        'exam': exam,
        'competition': comp,
        'radar': radar,
    }
