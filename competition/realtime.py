"""实时推送服务：Socket.IO 安全封装，未安装/未初始化时静默降级"""
from competition.leaderboard import get_leaderboard


_socketio = None


def init_realtime(sio):
    """app 启动时注入 SocketIO 实例"""
    global _socketio
    _socketio = sio


def is_live():
    return _socketio is not None


def notify_leaderboard_update(competition_id, top=10):
    """榜单变动：向竞赛房间广播最新 Top10"""
    if not _socketio:
        return
    _socketio.emit('leaderboard_update', {
        'competition_id': competition_id,
        'leaderboard': get_leaderboard(competition_id, limit=top),
    }, room=f'competition_{competition_id}')


def notify_battle_update(battle):
    """PK 进度/得分变动：向对战房间广播"""
    if not _socketio:
        return
    _socketio.emit('battle_update', battle.to_dict(), room=f'battle_{battle.id}')


def notify_battle_end(battle):
    """PK 结束：向对战房间广播结果"""
    if not _socketio:
        return
    _socketio.emit('battle_end', battle.to_dict(), room=f'battle_{battle.id}')


def notify_battle_accepted(battle):
    """挑战被接受：通知发起者立即进入对战"""
    if not _socketio:
        return
    _socketio.emit('battle_accepted', battle.to_dict(), room=f'battle_{battle.id}')


def notify_user(user_id, event, payload):
    """个人房间推送（段位/积分/勋章变化等）；需 join_user 鉴权后加入 user_{id}"""
    if not _socketio:
        return
    _socketio.emit(event, payload, room=f'user_{int(user_id)}')
