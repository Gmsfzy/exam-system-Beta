"""Socket.IO 事件注册：房间管理（加入房间一律需要 JWT 鉴权）"""
from flask_socketio import join_room, leave_room

from database import db


def _socket_user_id(data):
    """从事件数据中解析 JWT，返回 user_id（int）或 None"""
    import jwt
    from config import Config
    token = (data or {}).get('token') or ''
    if not token:
        return None
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=['HS256'])
        return int(payload.get('user_id', -1))
    except Exception:
        return None


def register_socket_events(sio):
    @sio.on('join_competition')
    def on_join_competition(data):
        """客户端加入竞赛榜单房间；任何已登录用户可加入（与榜单接口可见性一致）"""
        uid = _socket_user_id(data)
        comp_id = (data or {}).get('competition_id')
        if uid and comp_id:
            join_room(f'competition_{comp_id}')

    @sio.on('leave_competition')
    def on_leave_competition(data):
        comp_id = (data or {}).get('competition_id')
        if comp_id:
            leave_room(f'competition_{comp_id}')

    @sio.on('join_battle')
    def on_join_battle(data):
        """加入 PK 对战房间；仅限对战双方（与 /pk/state 接口权限一致）"""
        uid = _socket_user_id(data)
        battle_id = (data or {}).get('battle_id')
        if not (uid and battle_id):
            return
        from database.models import PkBattle
        battle = db.session.get(PkBattle, int(battle_id))
        if battle and uid in (battle.challenger_id, battle.opponent_id):
            join_room(f'battle_{battle_id}')

    @sio.on('leave_battle')
    def on_leave_battle(data):
        battle_id = (data or {}).get('battle_id')
        if battle_id:
            leave_room(f'battle_{battle_id}')

    @sio.on('join_user')
    def on_join_user(data):
        """客户端加入个人房间（积分/段位/勋章推送）；必须带 JWT 且只能加入自己的房间"""
        uid = _socket_user_id(data)
        target = (data or {}).get('user_id')
        if not (uid and target):
            return
        try:
            if uid != int(target):
                return
        except (TypeError, ValueError):
            return
        join_room(f'user_{uid}')

    @sio.on('leave_user')
    def on_leave_user(data):
        uid = (data or {}).get('user_id')
        if uid:
            leave_room(f'user_{uid}')
