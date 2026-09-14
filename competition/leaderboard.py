"""排行榜服务：SQL 聚合排名，同分按用时排序"""
from database import db
from utils.timeutil import iso_local

from competition.models import CompetitionParticipant, ParticipantStatusEnum


def get_leaderboard(competition_id, limit=100):
    """返回排行列表；排名规则：得分降序 → 用时升序。
    包含答题中的参与者（实时榜单）：其 used_time 尚未固化，仍为 0。"""
    rows = (CompetitionParticipant.query
            .filter(CompetitionParticipant.competition_id == competition_id,
                    CompetitionParticipant.status != ParticipantStatusEnum.JOINED)
            .options(db.joinedload(CompetitionParticipant.user))
            .order_by(CompetitionParticipant.score.desc(),
                      CompetitionParticipant.used_time.asc(),
                      CompetitionParticipant.started_at.asc())
            .limit(limit)
            .all())

    leaderboard = []
    prev_key = None
    rank = 0
    for i, p in enumerate(rows, start=1):
        key = (p.score, p.used_time)
        if key != prev_key:
            rank = i
            prev_key = key
        leaderboard.append({
            'rank': rank,
            'user_id': p.user_id,
            'username': p.user.username,
            'score': p.score,
            'used_time': p.used_time,
            'status': p.status,
            'finished_at': iso_local(p.finished_at),
        })
    return leaderboard


def get_my_rank(competition_id, user_id, participant=None):
    """查询指定用户名次（答题中按实时得分排名）。

    participant：可传入已查询的 CompetitionParticipant 行，避免重复查询。"""
    me = participant
    if me is None:
        me = CompetitionParticipant.query.filter_by(
            competition_id=competition_id, user_id=user_id).first()
    if not me:
        return None
    result = {'status': me.status, 'score': me.score,
              'used_time': me.used_time, 'rank': None}
    if me.status != ParticipantStatusEnum.JOINED:
        better = CompetitionParticipant.query.filter(
            CompetitionParticipant.competition_id == competition_id,
            CompetitionParticipant.status != ParticipantStatusEnum.JOINED,
            (CompetitionParticipant.score > me.score) |
            ((CompetitionParticipant.score == me.score) &
             (CompetitionParticipant.used_time < me.used_time) &
             (CompetitionParticipant.user_id != user_id))
        ).count()
        result['rank'] = better + 1
    return result
