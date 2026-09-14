# -*- coding: utf-8 -*-
"""战队路由：创建 / 加入 / 退出 / 转让 / 解散 / 排行榜"""
from flask import Blueprint, request, jsonify

from database import db
from database.models import User
from utils.timeutil import iso_local
from utils.security import verify_token
from competition.models import Team, TeamMember, UserPointsProfile
from competition.gamification import (
    current_season, ensure_profile, tier_of, check_and_grant,
)

team_bp = Blueprint('teams', __name__)


def _require_student():
    user = verify_token()
    if not user or not user.is_student():
        return None, (jsonify({'message': '仅学生可操作战队'}), 403)
    return user, None


def _team_season_points(team, season):
    """战队积分 = 队员当前赛季竞技积分之和（实时计算）"""
    total = 0
    for m in team.members:
        p = UserPointsProfile.query.filter_by(user_id=m.user_id, season=season).first()
        if p:
            total += p.points
    return total


def _team_dict(team, season):
    members = []
    for m in team.members:
        p = UserPointsProfile.query.filter_by(user_id=m.user_id, season=season).first()
        members.append({
            'user_id': m.user_id,
            'username': m.user.username,
            'role': m.role,
            'points': p.points if p else 0,
            'tier': tier_of(p.points) if p else tier_of(0),
            'joined_at': iso_local(m.joined_at),
        })
    members.sort(key=lambda x: (-x['points'], x['user_id']))
    return {
        'id': team.id,
        'name': team.name,
        'description': team.description or '',
        'captain_id': team.captain_id,
        'captain': team.captain.username if team.captain else '',
        'member_count': len(members),
        'points': sum(m['points'] for m in members),
        'members': members,
        'created_at': iso_local(team.created_at),
    }


def _my_membership(user_id):
    return TeamMember.query.filter_by(user_id=user_id).first()


# ═══════════════ 查询 ═══════════════

@team_bp.route('/teams', methods=['GET'])
def team_board():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    season = current_season()
    teams = Team.query.all()
    board = [_team_dict(t, season) for t in teams]
    board.sort(key=lambda x: (-x['points'], x['id']))
    for i, t in enumerate(board, start=1):
        t['rank'] = i
    return jsonify(board)


@team_bp.route('/teams/mine', methods=['GET'])
def team_mine():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    m = _my_membership(user.id)
    if not m:
        return jsonify(None)
    return jsonify(_team_dict(m.team, current_season()))


# ═══════════════ 操作 ═══════════════

@team_bp.route('/teams', methods=['POST'])
def create_team():
    user, err = _require_student()
    if err:
        return err
    if _my_membership(user.id):
        return jsonify({'message': '你已在战队中，不能重复创建'}), 400
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name or len(name) > 20:
        return jsonify({'message': '战队名必填且不超过20字'}), 400
    if Team.query.filter_by(name=name).first():
        return jsonify({'message': '战队名已存在'}), 400

    team = Team(name=name, description=(data.get('description') or '').strip(),
                captain_id=user.id)
    db.session.add(team)
    db.session.flush()
    db.session.add(TeamMember(team_id=team.id, user_id=user.id, role='captain'))
    db.session.commit()
    check_and_grant(user.id, {'team_found'})
    db.session.commit()
    return jsonify(_team_dict(team, current_season())), 201


@team_bp.route('/teams/<int:team_id>/join', methods=['POST'])
def join_team(team_id):
    user, err = _require_student()
    if err:
        return err
    team = db.session.get(Team, team_id)
    if not team:
        return jsonify({'message': '战队不存在'}), 404
    if _my_membership(user.id):
        return jsonify({'message': '你已加入其他战队'}), 400
    db.session.add(TeamMember(team_id=team.id, user_id=user.id, role='member'))
    db.session.commit()
    return jsonify(_team_dict(team, current_season()))


@team_bp.route('/teams/<int:team_id>/leave', methods=['POST'])
def leave_team(team_id):
    user, err = _require_student()
    if err:
        return err
    m = _my_membership(user.id)
    if not m or m.team_id != team_id:
        return jsonify({'message': '你不在这个战队'}), 400
    if m.role == 'captain' and m.team.captain_id == user.id:
        return jsonify({'message': '队长需先转让队长或解散战队'}), 400
    db.session.delete(m)
    db.session.commit()
    return jsonify({'message': '已退出战队'})


@team_bp.route('/teams/<int:team_id>/transfer', methods=['POST'])
def transfer_captain(team_id):
    user, err = _require_student()
    if err:
        return err
    team = db.session.get(Team, team_id)
    if not team:
        return jsonify({'message': '战队不存在'}), 404
    if team.captain_id != user.id:
        return jsonify({'message': '仅队长可转让'}), 403
    data = request.get_json(silent=True) or {}
    target_id = data.get('user_id')
    target = next((m for m in team.members if m.user_id == target_id), None)
    if not target or target.user_id == user.id:
        return jsonify({'message': '转让目标必须是战队其他成员'}), 400
    team.captain_id = target.user_id
    for m in team.members:
        m.role = 'captain' if m.user_id == target.user_id else 'member'
    db.session.commit()
    return jsonify(_team_dict(team, current_season()))


@team_bp.route('/teams/<int:team_id>', methods=['DELETE'])
def dissolve_team(team_id):
    user, err = _require_student()
    if err:
        return err
    team = db.session.get(Team, team_id)
    if not team:
        return jsonify({'message': '战队不存在'}), 404
    if team.captain_id != user.id:
        return jsonify({'message': '仅队长可解散战队'}), 403
    db.session.delete(team)  # TeamMember 级联删除
    db.session.commit()
    return jsonify({'message': '战队已解散'})
