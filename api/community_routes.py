# -*- coding: utf-8 -*-
"""v5.29 社区中心 · Phase 1 论坛 MVP — 后端 API 蓝图。

挂载：app.py 统一 url_prefix='/api'
端点清单（13 个）：
  GET    /posts                 public    帖子列表
  GET    /posts/<id>            public    帖子详情
  POST   /posts                 login     发帖
  PUT    /posts/<id>            author    编辑自己的帖
  DELETE /posts/<id>            author+   软删除帖子
  POST   /posts/<id>/like       login     点赞帖子
  DELETE /posts/<id>/like       login     取消点赞
  GET    /posts/<id>/comments   public    帖子评论列表
  POST   /posts/<id>/comments   login     发表评论
  DELETE /comments/<id>         author+   软删除评论
  POST   /comments/<id>/like    login     评论点赞
  DELETE /comments/<id>/like    login     取消评论点赞
  GET    /posts/linked/<type>/<id>  public  按关联类型查帖子（轻联动）
"""
import re
from collections import Counter

from flask import Blueprint, request, jsonify
from sqlalchemy import desc, or_, func
from sqlalchemy.exc import IntegrityError

from database import db
from database.models import (
    User, Course, WrongAnswerRecord, CommunityPost, CommunityComment, CommunityLike,
    CommunityFavorite, CommunityNotification, CommunityReport,
    CommunityPollOption, CommunityPollVote, CommunityUserStat, CommunityPointLog,
    CommunityCategoryEnum, CommunityLinkTypeEnum,
)
from utils.security import verify_token, limiter
from utils.permissions import require_login, require_teacher
from utils.redis_cache import cache_key, get_cache, set_cache, delete_cache, delete_pattern
from utils.uploads import save_upload
from utils.timeutil import utcnow, local_day_start

api_community_bp = Blueprint('api_community', __name__)

# Flask 3.x 蓝图的 url_prefix 与 register_blueprint 的 url_prefix 会互相覆盖而非叠加，
# 所以内部路由统一带 /community 前缀（app.register_blueprint 统一挂 /api）
# 最终所有端点地址: /api/community/*

# ───────────────────────────────────────────────────────────
# 工具函数
# ───────────────────────────────────────────────────────────

def _ok(data=None):
    """统一成功响应（与项目其他模块一致：直接返回业务数据本身）"""
    return jsonify(data if data is not None else {})


def _err(msg, code=400):
    """统一错误响应（message 键对齐 request.js 拦截器读取逻辑）"""
    return jsonify({'message': msg}), code


def _validate_category(cat):
    return cat in CommunityCategoryEnum.ALL


def _validate_linked_type(t):
    return t is None or t in CommunityLinkTypeEnum.ALL


def _hot_like_count(target_type, target_id, db_value):
    """点赞热计数：Redis 命中优先，未命中回写 DB 真值（降级时直接用 DB）。"""
    key = cache_key('community:like', target_type, target_id)
    cached = get_cache(key)
    if cached is not None:
        try:
            return int(cached)
        except (TypeError, ValueError):
            pass
    set_cache(key, int(db_value or 0), 120)
    return int(db_value or 0)


def _refresh_like_cache(target_type, target_id, value):
    set_cache(cache_key('community:like', target_type, target_id), int(value or 0), 120)


def _post_serialize(post, viewer):
    """帖子序列化（viewer 用于匿名权限判断）"""
    data = post.to_dict(viewer=viewer)
    data['liked'] = _is_liked('post', post.id, viewer) if viewer else False
    data['favorited'] = _is_favorited(post.id, viewer) if viewer else False
    data['like_count'] = _hot_like_count('post', post.id, post.like_count)
    data['poll'] = _poll_serialize(post, viewer)
    return data


def _poll_serialize(post, viewer):
    """投票序列化：无选项返回 None；计数从投票表聚合。"""
    options = CommunityPollOption.query.filter_by(post_id=post.id).order_by(
        CommunityPollOption.order_index.asc(), CommunityPollOption.id.asc()
    ).all()
    if not options:
        return None

    counts = dict(db.session.query(
        CommunityPollVote.option_id, func.count(CommunityPollVote.id)
    ).filter(CommunityPollVote.post_id == post.id).group_by(
        CommunityPollVote.option_id
    ).all())
    total = sum(counts.values())

    voted_option_id = None
    if viewer:
        vote = CommunityPollVote.query.filter_by(
            post_id=post.id, user_id=viewer.id
        ).first()
        voted_option_id = vote.option_id if vote else None

    return {
        'options': [{
            'id': o.id,
            'text': o.text,
            'vote_count': counts.get(o.id, 0),
            'percent': round(counts.get(o.id, 0) * 100 / total) if total else 0,
        } for o in options],
        'total_votes': total,
        'voted_option_id': voted_option_id,
        'can_vote': viewer is not None,
    }


def _normalize_tags(raw):
    """标签归一化：支持数组或逗号字符串，去空去重、最多 5 个、每个 ≤ 20 字。

    返回 (tags_string, error_message)。"""
    if raw in (None, ''):
        return None, None
    if isinstance(raw, str):
        items = raw.replace('，', ',').split(',')
    elif isinstance(raw, list):
        items = raw
    else:
        return None, '标签格式无效'

    cleaned = []
    for item in items:
        t = str(item).strip().lstrip('#')
        if not t:
            continue
        if len(t) > 20:
            return None, '单个标签 ≤ 20 字'
        if t not in cleaned:
            cleaned.append(t)
    if len(cleaned) > 5:
        return None, '最多 5 个标签'
    return (','.join(cleaned) or None), None


def _save_poll_options(post, raw_options):
    """校验并写入投票选项（2–6 个、每个 ≤ 100 字）。返回错误消息或 None。"""
    if not isinstance(raw_options, list):
        return '投票选项格式无效'
    texts = []
    for item in raw_options:
        t = str(item or '').strip()
        if not t:
            continue
        if len(t) > 100:
            return '单个投票选项 ≤ 100 字'
        texts.append(t)
    if len(texts) < 2 or len(texts) > 6:
        return '投票选项需 2–6 个'

    for index, text in enumerate(texts):
        db.session.add(CommunityPollOption(
            post_id=post.id, text=text, order_index=index
        ))
    return None


# ── 积分等级（第三批）─────────────────────────────────────
# 等级不落库，按积分阈值实时推导，避免账户与等级双写漂移
LEVEL_THRESHOLDS = (
    (0,    '新手上路'),
    (50,   '初出茅庐'),
    (150,  '社区活跃'),
    (300,  '热心达人'),
    (600,  '资深前辈'),
    (1000, '社区之星'),
)


def _level_info(points):
    points = max(0, int(points or 0))
    idx = 0
    for i, (threshold, _name) in enumerate(LEVEL_THRESHOLDS):
        if points >= threshold:
            idx = i
    threshold, name = LEVEL_THRESHOLDS[idx]
    next_points = (LEVEL_THRESHOLDS[idx + 1][0]
                   if idx + 1 < len(LEVEL_THRESHOLDS) else None)
    return {
        'points': points,
        'level': idx + 1,
        'level_name': name,
        'level_threshold': threshold,
        'next_level_points': next_points,
    }


def _get_stat(user_id, create=False):
    stat = CommunityUserStat.query.filter_by(user_id=user_id).first()
    if not stat and create:
        stat = CommunityUserStat(user_id=user_id, points=0)
        db.session.add(stat)
        db.session.flush()
    return stat


def _award_points(user_id, delta, reason, related_type=None, related_id=None):
    """积分入账（delta 可为负）：账户不存在时自动创建，并记一条流水。"""
    delta = int(delta or 0)
    if not user_id or delta == 0:
        return None
    stat = _get_stat(user_id, create=True)
    stat.points = max(0, (stat.points or 0) + delta)
    db.session.add(CommunityPointLog(
        user_id=user_id, delta=delta, reason=reason,
        related_type=related_type, related_id=related_id,
    ))
    return stat


def _comment_serialize(comment, viewer):
    data = comment.to_dict(viewer=viewer)
    data['liked'] = _is_liked('comment', comment.id, viewer) if viewer else False
    data['like_count'] = _hot_like_count('comment', comment.id, comment.like_count)
    return data


def _is_liked(target_type, target_id, user):
    if not user:
        return False
    return CommunityLike.query.filter_by(
        target_type=target_type, target_id=target_id, user_id=user.id
    ).first() is not None


def _is_favorited(post_id, user):
    if not user:
        return False
    return CommunityFavorite.query.filter_by(
        post_id=post_id, user_id=user.id
    ).first() is not None


# ── @提及 / 通知 ──────────────────────────────────────────

_MENTION_RE = re.compile(r'@([A-Za-z0-9_\u4e00-\u9fa5-]{1,20})')


def _extract_mentions(text):
    """从正文提取 @username（去重，忽略不存在的用户）。"""
    if not text:
        return []
    names = {m for m in _MENTION_RE.findall(text)}
    if not names:
        return []
    return User.query.filter(User.username.in_(names)).all()


def _notify(user_id, actor_id, ntype, post_id=None, comment_id=None, content=None):
    """写一条社区通知；自己触发的动作不再通知自己。"""
    if not user_id or user_id == actor_id:
        return None
    n = CommunityNotification(
        user_id=user_id,
        actor_id=actor_id,
        type=ntype,
        post_id=post_id,
        comment_id=comment_id,
        content=(content or '')[:200] or None,
    )
    db.session.add(n)
    return n


def _notify_mentions(text, actor_id, post_id, comment_id=None):
    for u in _extract_mentions(text):
        _notify(u.id, actor_id, 'mention', post_id=post_id,
                comment_id=comment_id, content=f'@{u.username} 你被提及了')


# ── 举报折叠 ─────────────────────────────────────────────

REPORT_FOLD_THRESHOLD = 3   # 待处理举报达到 3 条自动折叠


def _auto_fold_if_needed(target_type, obj):
    pending = CommunityReport.query.filter_by(
        target_type=target_type, target_id=obj.id, status='pending'
    ).count()
    obj.report_count = pending
    if pending >= REPORT_FOLD_THRESHOLD and not obj.hidden:
        obj.hidden = True
        if target_type == 'post':
            _notify(obj.author_id, None, 'hidden', post_id=obj.id,
                    content='你的帖子因多次举报已被折叠，管理员会尽快处理')
        else:
            _notify(obj.author_id, None, 'hidden', comment_id=obj.id,
                    post_id=obj.post_id, content='你的评论因多次举报已被折叠')
    elif pending < REPORT_FOLD_THRESHOLD and obj.hidden:
        # 举报被驳回后待处理数下降，自动解除折叠
        obj.hidden = False
    return pending


def _check_link_exists(linked_type, linked_id):
    """API 层校验关联有效性（DB 层无外键）"""
    if not linked_type or not linked_id:
        return True
    model_map = {
        'question': 'question',
        'homework': 'homework',
        'exam': 'exam',
    }
    if linked_type not in model_map:
        return False
    # 动态查：不同表名不同，用 text 直接查
    from sqlalchemy import text
    try:
        tbl = model_map[linked_type]
        row = db.session.execute(
            text(f'SELECT 1 FROM {tbl} WHERE id = :id LIMIT 1'),
            {'id': int(linked_id)}
        ).fetchone()
        return row is not None
    except Exception:
        return False


# ───────────────────────────────────────────────────────────
# 帖子 CRUD
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/posts', methods=['GET'])
@limiter.limit('120/minute')
def list_posts():
    """帖子列表。支持：
      - ?category=xxx 分类筛选
      - ?sort=new|hot  排序（默认 new）
      - ?q=关键字      标题搜索（LIKE %q%）
      - ?page=1&per_page=20 分页
      - ?linked_type=question&linked_id=123 轻联动过滤
      - ?tag=链表           标签精确过滤
      - ?course_id=9        班级圈子（课程）过滤
    """
    viewer = verify_token()
    category = request.args.get('category', '').strip() or None
    sort = request.args.get('sort', 'new').strip()
    q = request.args.get('q', '').strip()
    linked_type = request.args.get('linked_type', '').strip() or None
    linked_id = request.args.get('linked_id', type=int)
    resolved = request.args.get('resolved', '').strip()
    tag = request.args.get('tag', '').strip() or None
    course_id = request.args.get('course_id', type=int)
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, request.args.get('per_page', 20, type=int))

    if category and not _validate_category(category):
        return _err('无效分类', 400)
    if sort not in ('new', 'hot'):
        sort = 'new'
    if linked_type and not _validate_linked_type(linked_type):
        return _err('无效关联类型', 400)

    query = CommunityPost.query.filter_by(deleted=False)
    if category:
        query = query.filter_by(category=category)
    if q:
        query = query.filter(or_(
            CommunityPost.title.ilike(f'%{q}%'),
            CommunityPost.content.ilike(f'%{q}%'),
        ))
    if linked_type and linked_id:
        query = query.filter_by(linked_type=linked_type, linked_id=linked_id)
    if tag:
        # tags 以逗号分隔存储；先精确匹配首尾，再兼容中段
        query = query.filter(or_(
            CommunityPost.tags == tag,
            CommunityPost.tags.ilike(f'{tag},%'),
            CommunityPost.tags.ilike(f'%,{tag}'),
            CommunityPost.tags.ilike(f'%,{tag},%'),
        ))
    if course_id:
        query = query.filter_by(course_id=course_id)
    if resolved in ('1', 'true', 'yes'):
        query = query.filter_by(is_resolved=True)
    elif resolved in ('0', 'false', 'no'):
        query = query.filter_by(is_resolved=False)

    if sort == 'hot':
        # 热帖 = like_count + comment_count*2，未加 Redis 热计数时用 DB 字段
        query = query.order_by(desc(CommunityPost.like_count + CommunityPost.comment_count * 2))
    else:
        query = query.order_by(desc(CommunityPost.created_at))

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    posts = [_post_serialize(p, viewer) for p in paginated.items]
    return _ok({
        'items': posts,
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
        'has_next': paginated.has_next,
        'has_prev': paginated.has_prev,
        'categories': [{'value': v, 'label': CommunityCategoryEnum.label(v)}
                       for v in CommunityCategoryEnum.ALL],
    })


@api_community_bp.route('/community/posts/<int:post_id>', methods=['GET'])
@limiter.limit('120/minute')
def get_post(post_id):
    viewer = verify_token()
    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)

    comments = CommunityComment.query.filter_by(
        post_id=post_id, deleted=False
    ).order_by(CommunityComment.created_at.asc()).all()

    post_data = _post_serialize(post, viewer)
    post_data['comments'] = [_comment_serialize(c, viewer) for c in comments]
    return _ok(post_data)


@api_community_bp.route('/community/posts', methods=['POST'])
@limiter.limit('10/minute')
def create_post():
    user, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    category = data.get('category') or 'other'
    linked_type = data.get('linked_type')
    linked_id = data.get('linked_id')
    is_anonymous = bool(data.get('is_anonymous', False))
    tags, tag_err = _normalize_tags(data.get('tags'))
    poll_options = data.get('poll_options')
    course_id = data.get('course_id')
    try:
        bounty_points = int(data.get('bounty_points') or 0)
    except (TypeError, ValueError):
        return _err('悬赏积分格式无效')

    if not title or len(title) > 100:
        return _err('标题必填且 ≤ 100 字')
    if not content or len(content) > 5000:
        return _err('正文必填且 ≤ 5000 字')
    if not _validate_category(category):
        return _err('无效分类')
    if tag_err:
        return _err(tag_err)
    if poll_options is not None and not isinstance(poll_options, list):
        return _err('投票选项格式无效')
    if linked_type or linked_id:
        if not _validate_linked_type(linked_type) or not linked_id:
            return _err('关联类型和 ID 必须同时有效')
        if not _check_link_exists(linked_type, linked_id):
            return _err('关联的题目/作业/考试不存在')
    if course_id:
        try:
            course_id = int(course_id)
        except (TypeError, ValueError):
            return _err('圈子（课程）ID 无效')
        if not Course.query.get(course_id):
            return _err('圈子（课程）不存在')
    if bounty_points < 0 or bounty_points > 100:
        return _err('悬赏积分须在 0–100 之间')
    if bounty_points and linked_type != 'question':
        return _err('悬赏仅支持关联题目的求助帖')
    if bounty_points:
        stat = _get_stat(user.id)
        if (stat.points if stat else 0) < bounty_points:
            return _err('社区积分不足，无法设置该悬赏')

    # 匿名序号：同一用户匿名帖序号递增
    anon_index = None
    if is_anonymous:
        max_idx = db.session.query(func.max(CommunityPost.anon_index)).filter(
            CommunityPost.author_id == user.id,
            CommunityPost.is_anonymous == True,
        ).scalar()
        anon_index = (max_idx or 0) + 1

    post = CommunityPost(
        title=title,
        content=content,
        category=category,
        author_id=user.id,
        linked_type=linked_type,
        linked_id=linked_id,
        is_anonymous=is_anonymous,
        anon_index=anon_index,
        tags=tags,
        course_id=course_id or None,
        bounty_points=bounty_points,
    )
    db.session.add(post)
    db.session.flush()

    if poll_options is not None:
        poll_err = _save_poll_options(post, poll_options)
        if poll_err:
            db.session.rollback()
            return _err(poll_err)

    # 第三批：发帖积分 + 悬赏冻结（采纳后转给最佳答案作者）
    _award_points(user.id, 5, 'post', 'post', post.id)
    if bounty_points:
        _award_points(user.id, -bounty_points, 'bounty_hold', 'post', post.id)

    _notify_mentions(content, user.id, post.id)
    db.session.commit()

    return _ok(_post_serialize(post, user)), 201


@api_community_bp.route('/community/posts/<int:post_id>', methods=['PUT'])
@limiter.limit('60/minute')
def update_post(post_id):
    user, err = require_login()
    if err:
        return err

    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)
    if post.author_id != user.id:
        return _err('无权编辑他人帖子', 403)

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        t = data['title'].strip()
        if not t or len(t) > 100:
            return _err('标题必填且 ≤ 100 字')
        post.title = t
    if 'content' in data:
        c = data['content'].strip()
        if not c or len(c) > 5000:
            return _err('正文必填且 ≤ 5000 字')
        post.content = c
        _notify_mentions(c, user.id, post.id)
    if 'category' in data:
        if not _validate_category(data['category']):
            return _err('无效分类')
        post.category = data['category']
    if 'tags' in data:
        tags, tag_err = _normalize_tags(data.get('tags'))
        if tag_err:
            return _err(tag_err)
        post.tags = tags
    if 'course_id' in data:
        cid = data.get('course_id')
        if cid in (None, ''):
            post.course_id = None
        else:
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                return _err('圈子（课程）ID 无效')
            if not Course.query.get(cid):
                return _err('圈子（课程）不存在')
            post.course_id = cid

    db.session.commit()
    return _ok(_post_serialize(post, user))


@api_community_bp.route('/community/posts/<int:post_id>', methods=['DELETE'])
@limiter.limit('60/minute')
def delete_post(post_id):
    user, err = require_login()
    if err:
        return err

    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)

    # 权限：作者本人 / 老师 / 管理员
    if post.author_id != user.id and user.role not in ('teacher', 'admin'):
        return _err('无权删除', 403)

    # 第三批：未发放的悬赏在删除时退回作者
    if post.bounty_points and not post.bounty_rewarded:
        _award_points(post.author_id, post.bounty_points, 'bounty_refund', 'post', post.id)
        post.bounty_rewarded = True

    post.deleted = True
    db.session.commit()
    return _ok({'deleted': True})


# ───────────────────────────────────────────────────────────
# 点赞（帖子 + 评论共用一套逻辑）
# ───────────────────────────────────────────────────────────

def _toggle_like(target_type, target_id, user, value):
    """点赞/取消点赞；value=True 点赞，value=False 取消。

    返回 (ok, error, status_code)"""
    if target_type not in ('post', 'comment'):
        return False, '无效点赞目标类型', 400

    # 校验目标存在
    if target_type == 'post':
        obj = CommunityPost.query.get(target_id)
        if not obj or obj.deleted:
            return False, '帖子不存在或已删除', 404
    else:
        obj = CommunityComment.query.get(target_id)
        if not obj or obj.deleted:
            return False, '评论不存在或已删除', 404

    existing = CommunityLike.query.filter_by(
        target_type=target_type, target_id=target_id, user_id=user.id
    ).first()

    delta = 0
    if value and not existing:
        db.session.add(CommunityLike(
            target_type=target_type, target_id=target_id, user_id=user.id
        ))
        delta = 1
    elif not value and existing:
        db.session.delete(existing)
        delta = -1
    # else: 已点赞重复点赞 / 已取消重复取消 —— 幂等，直接返回

    if delta != 0:
        obj.like_count = max(0, obj.like_count + delta)
        # 第三批：被点赞方 +1 积分（自赞不计）
        if delta == 1 and obj.author_id != user.id:
            _award_points(obj.author_id, 1, 'like', target_type, target_id)
        db.session.commit()
        _refresh_like_cache(target_type, target_id, obj.like_count)
    else:
        _refresh_like_cache(target_type, target_id, obj.like_count)

    return True, None, 200


@api_community_bp.route('/community/posts/<int:post_id>/like', methods=['POST', 'DELETE'])
@limiter.limit('60/minute')
def like_post(post_id):
    user, err = require_login()
    if err:
        return err

    value = request.method == 'POST'
    ok, error, code = _toggle_like('post', post_id, user, value)
    if not ok:
        return _err(error, code)

    post = CommunityPost.query.get(post_id)
    return _ok({'liked': value, 'like_count': post.like_count})


@api_community_bp.route('/community/comments/<int:comment_id>/like', methods=['POST', 'DELETE'])
@limiter.limit('60/minute')
def like_comment(comment_id):
    user, err = require_login()
    if err:
        return err

    value = request.method == 'POST'
    ok, error, code = _toggle_like('comment', comment_id, user, value)
    if not ok:
        return _err(error, code)

    comment = CommunityComment.query.get(comment_id)
    return _ok({'liked': value, 'like_count': comment.like_count})


# ───────────────────────────────────────────────────────────
# 评论
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/posts/<int:post_id>/comments', methods=['GET'])
@limiter.limit('120/minute')
def list_comments(post_id):
    viewer = verify_token()

    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)

    comments = CommunityComment.query.filter_by(
        post_id=post_id, deleted=False
    ).order_by(CommunityComment.created_at.asc()).all()

    return _ok([_comment_serialize(c, viewer) for c in comments])


@api_community_bp.route('/community/posts/<int:post_id>/comments', methods=['POST'])
@limiter.limit('30/minute')
def create_comment(post_id):
    user, err = require_login()
    if err:
        return err

    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)

    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    is_anonymous = bool(data.get('is_anonymous', False))
    parent_id = data.get('parent_id')

    if not content or len(content) > 2000:
        return _err('评论内容必填且 ≤ 2000 字')

    parent = None
    if parent_id:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return _err('无效的回复目标')
        parent = CommunityComment.query.get(parent_id)
        if not parent or parent.deleted or parent.post_id != post_id:
            return _err('回复的评论不存在或不属于该帖子')

    anon_index = None
    if is_anonymous:
        max_idx = db.session.query(func.max(CommunityComment.anon_index)).filter(
            CommunityComment.author_id == user.id,
            CommunityComment.is_anonymous == True,
        ).scalar()
        anon_index = (max_idx or 0) + 1

    comment = CommunityComment(
        post_id=post_id,
        author_id=user.id,
        content=content,
        parent_id=parent_id or None,
        is_anonymous=is_anonymous,
        anon_index=anon_index,
    )
    db.session.add(comment)
    post.comment_count = (post.comment_count or 0) + 1
    db.session.flush()

    # 第三批：评论 +2 积分
    _award_points(user.id, 2, 'comment', 'comment', comment.id)

    # 楼中楼：回复通知父评论作者；一级评论通知帖子作者
    if parent:
        _notify(parent.author_id, user.id, 'reply', post_id=post_id,
                comment_id=comment.id, content=content)
    else:
        _notify(post.author_id, user.id, 'comment', post_id=post_id,
                comment_id=comment.id, content=content)
    _notify_mentions(content, user.id, post_id, comment.id)

    db.session.commit()

    return _ok(_comment_serialize(comment, user)), 201


@api_community_bp.route('/community/comments/<int:comment_id>', methods=['DELETE'])
@limiter.limit('60/minute')
def delete_comment(comment_id):
    user, err = require_login()
    if err:
        return err

    comment = CommunityComment.query.get(comment_id)
    if not comment or comment.deleted:
        return _err('评论不存在或已删除', 404)

    # 权限：评论作者 / 帖子作者 / 老师 / 管理员
    post = CommunityPost.query.get(comment.post_id)
    is_post_author = post and post.author_id == user.id
    if (comment.author_id != user.id
            and not is_post_author
            and user.role not in ('teacher', 'admin')):
        return _err('无权删除', 403)

    # 楼中楼：删除父评论时级联软删其所有子孙回复
    to_delete = [comment]
    queue = [comment.id]
    while queue:
        children = CommunityComment.query.filter(
            CommunityComment.parent_id == queue.pop(0),
            CommunityComment.deleted == False,
        ).all()
        for child in children:
            to_delete.append(child)
            queue.append(child.id)
    for c in to_delete:
        c.deleted = True
    if post:
        post.comment_count = max(0, (post.comment_count or 0) - len(to_delete))
    db.session.commit()
    return _ok({'deleted': True, 'affected': len(to_delete)})


# ───────────────────────────────────────────────────────────
# 轻联动：按关联类型查帖子
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/posts/linked/<linked_type>/<int:linked_id>', methods=['GET'])
@limiter.limit('120/minute')
def list_linked_posts(linked_type, linked_id):
    """轻联动端点：前端从题目/作业/考试详情页的「讨论」tab 调用。

    返回该题目/作业/考试关联的所有未删除帖子，格式与 list_posts 一致但不分页。
    """
    viewer = verify_token()

    if not _validate_linked_type(linked_type):
        return _err('无效关联类型', 400)

    posts = CommunityPost.query.filter_by(
        linked_type=linked_type,
        linked_id=linked_id,
        deleted=False,
    ).order_by(desc(CommunityPost.created_at)).all()

    return _ok([_post_serialize(p, viewer) for p in posts])


# ───────────────────────────────────────────────────────────
# 分类枚举（前端下拉框需要）
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/categories', methods=['GET'])
@limiter.limit('60/minute')
def list_categories():
    """返回所有分类的 value + label。公开端点，前端发帖页 select 用。"""
    return _ok([
        {'value': v, 'label': CommunityCategoryEnum.label(v)}
        for v in CommunityCategoryEnum.ALL
    ])


# ───────────────────────────────────────────────────────────
# 第一批扩充：收藏
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/posts/<int:post_id>/favorite', methods=['POST', 'DELETE'])
@limiter.limit('60/minute')
def favorite_post(post_id):
    user, err = require_login()
    if err:
        return err

    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)

    existing = CommunityFavorite.query.filter_by(
        post_id=post_id, user_id=user.id
    ).first()

    if request.method == 'POST':
        if not existing:
            db.session.add(CommunityFavorite(post_id=post_id, user_id=user.id))
            post.favorite_count = (post.favorite_count or 0) + 1
            db.session.commit()
        favorited = True
    else:
        if existing:
            db.session.delete(existing)
            post.favorite_count = max(0, (post.favorite_count or 0) - 1)
            db.session.commit()
        favorited = False

    return _ok({'favorited': favorited, 'favorite_count': post.favorite_count})


@api_community_bp.route('/community/favorites', methods=['GET'])
@limiter.limit('120/minute')
def list_favorites():
    user, err = require_login()
    if err:
        return err

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, request.args.get('per_page', 20, type=int))

    query = CommunityPost.query.join(
        CommunityFavorite, CommunityFavorite.post_id == CommunityPost.id
    ).filter(
        CommunityFavorite.user_id == user.id,
        CommunityPost.deleted == False,
    ).order_by(desc(CommunityFavorite.created_at))

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    return _ok({
        'items': [_post_serialize(p, user) for p in paginated.items],
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
    })


# ───────────────────────────────────────────────────────────
# 第一批扩充：已解决标记
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/posts/<int:post_id>/resolve', methods=['PUT'])
@limiter.limit('60/minute')
def resolve_post(post_id):
    user, err = require_login()
    if err:
        return err

    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)

    is_post_author = post.author_id == user.id
    is_teacher_or_admin = user.role in ('teacher', 'admin')
    if not is_post_author and not is_teacher_or_admin:
        return _err('只有作者、老师或管理员可以标记', 403)

    data = request.get_json(silent=True) or {}
    resolved = bool(data.get('resolved', True))
    post.is_resolved = resolved
    post.resolved_at = utcnow() if resolved else None
    post.resolved_by = user.id if resolved else None

    if resolved and not is_post_author:
        _notify(post.author_id, user.id, 'resolve', post_id=post.id,
                content='你的帖子已被标记为已解决')
    db.session.commit()

    return _ok(_post_serialize(post, user))


# ───────────────────────────────────────────────────────────
# 第一批扩充：@通知 / 消息中心
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/notifications', methods=['GET'])
@limiter.limit('120/minute')
def list_notifications():
    user, err = require_login()
    if err:
        return err

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, request.args.get('per_page', 20, type=int))
    unread_only = request.args.get('unread_only', '').lower() in ('1', 'true', 'yes')

    query = CommunityNotification.query.filter_by(user_id=user.id)
    if unread_only:
        query = query.filter_by(is_read=False)
    query = query.order_by(desc(CommunityNotification.created_at))

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    unread = CommunityNotification.query.filter_by(
        user_id=user.id, is_read=False
    ).count()

    return _ok({
        'items': [n.to_dict() for n in paginated.items],
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
        'unread': unread,
    })


@api_community_bp.route('/community/notifications/unread-count', methods=['GET'])
@limiter.limit('120/minute')
def unread_notification_count():
    user, err = require_login()
    if err:
        return err
    count = CommunityNotification.query.filter_by(
        user_id=user.id, is_read=False
    ).count()
    return _ok({'unread': count})


@api_community_bp.route('/community/notifications/<int:notification_id>/read', methods=['PUT'])
@limiter.limit('120/minute')
def read_notification(notification_id):
    user, err = require_login()
    if err:
        return err

    n = CommunityNotification.query.get(notification_id)
    if not n or n.user_id != user.id:
        return _err('通知不存在', 404)
    n.is_read = True
    db.session.commit()
    return _ok({'read': True})


@api_community_bp.route('/community/notifications/read-all', methods=['PUT'])
@limiter.limit('60/minute')
def read_all_notifications():
    user, err = require_login()
    if err:
        return err
    updated = CommunityNotification.query.filter_by(
        user_id=user.id, is_read=False
    ).update({CommunityNotification.is_read: True})
    db.session.commit()
    return _ok({'updated': updated})


# ───────────────────────────────────────────────────────────
# 第一批扩充：举报 + 折叠
# ───────────────────────────────────────────────────────────

def _require_teacher_or_admin():
    user = verify_token()
    if not user:
        return None, _err('请先登录', 401)
    if user.role not in ('teacher', 'admin'):
        return None, _err('无权访问', 403)
    return user, None


def _report_target(rep):
    """举报队列展示用：带出被举报内容的摘要。"""
    data = rep.to_dict()
    target = None
    if rep.target_type == 'post':
        target = CommunityPost.query.get(rep.target_id)
    else:
        target = CommunityComment.query.get(rep.target_id)
    if target:
        data['target_title'] = getattr(target, 'title', None)
        data['target_content'] = (target.content or '')[:200]
        data['target_author_id'] = target.author_id
        data['target_deleted'] = target.deleted
        data['target_hidden'] = target.hidden
        if rep.target_type == 'comment':
            data['target_post_id'] = target.post_id
    return data


@api_community_bp.route('/community/reports', methods=['POST'])
@limiter.limit('20/minute')
def create_report():
    user, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    target_type = (data.get('target_type') or '').strip()
    target_id = data.get('target_id')
    reason = (data.get('reason') or '').strip()

    if target_type not in ('post', 'comment'):
        return _err('无效举报对象类型')
    if not target_id or not reason or len(reason) > 200:
        return _err('举报理由必填且 ≤ 200 字')

    if target_type == 'post':
        target = CommunityPost.query.get(target_id)
    else:
        target = CommunityComment.query.get(target_id)
    if not target or target.deleted:
        return _err('举报的内容不存在或已删除', 404)
    if target.author_id == user.id:
        return _err('不能举报自己的内容')

    existing = CommunityReport.query.filter_by(
        target_type=target_type, target_id=target.id, reporter_id=user.id
    ).first()
    if existing:
        return _err('你已经举报过该内容')

    rep = CommunityReport(
        target_type=target_type,
        target_id=target.id,
        reporter_id=user.id,
        reason=reason,
    )
    db.session.add(rep)
    db.session.flush()
    pending = _auto_fold_if_needed(target_type, target)
    db.session.commit()

    return _ok({
        'report': rep.to_dict(),
        'report_count': pending,
        'hidden': target.hidden,
    }), 201


@api_community_bp.route('/community/reports', methods=['GET'])
@limiter.limit('120/minute')
def list_reports():
    user, err = _require_teacher_or_admin()
    if err:
        return err

    status = request.args.get('status', 'pending').strip() or None
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, request.args.get('per_page', 20, type=int))

    query = CommunityReport.query
    if status:
        query = query.filter_by(status=status)
    query = query.order_by(desc(CommunityReport.created_at))
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    return _ok({
        'items': [_report_target(r) for r in paginated.items],
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
    })


@api_community_bp.route('/community/reports/<int:report_id>', methods=['PUT'])
@limiter.limit('60/minute')
def handle_report(report_id):
    user, err = _require_teacher_or_admin()
    if err:
        return err

    rep = CommunityReport.query.get(report_id)
    if not rep:
        return _err('举报记录不存在', 404)
    if rep.status != 'pending':
        return _err('该举报已处理', 400)

    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()
    if action not in ('dismiss', 'remove'):
        return _err('action 只能是 dismiss 或 remove')

    target = None
    if rep.target_type == 'post':
        target = CommunityPost.query.get(rep.target_id)
    else:
        target = CommunityComment.query.get(rep.target_id)

    if action == 'remove' and target and not target.deleted:
        target.deleted = True
        if rep.target_type == 'post':
            _notify(target.author_id, user.id, 'report', post_id=target.id,
                    content='你的帖子因违规已被管理员删除')
        else:
            _notify(target.author_id, user.id, 'report', post_id=target.post_id,
                    comment_id=target.id, content='你的评论因违规已被管理员删除')

    rep.status = 'handled' if action == 'remove' else 'dismissed'
    rep.handled_by = user.id
    rep.handled_at = utcnow()

    if target:
        _auto_fold_if_needed(rep.target_type, target)
    db.session.commit()

    return _ok({'report': rep.to_dict()})


# ───────────────────────────────────────────────────────────
# 第一批扩充：图片 / 附件上传
# ───────────────────────────────────────────────────────────

_COMMUNITY_ALLOWED_EXTS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp',
    '.pdf', '.doc', '.docx', '.txt', '.md', '.zip', '.rar', '.7z',
}


@api_community_bp.route('/community/upload', methods=['POST'])
@limiter.limit('30/minute')
def upload_attachment():
    user, err = require_login()
    if err:
        return err

    file = request.files.get('file')
    if not file or not file.filename:
        return _err('请选择文件')

    import os
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _COMMUNITY_ALLOWED_EXTS:
        return _err('仅支持图片(png/jpg/jpeg/gif/webp)或文档(pdf/doc/docx/txt/md/zip)')

    try:
        stored, size = save_upload(file, 'community')
    except ValueError as e:
        return _err(str(e))

    return _ok({
        'url': f'/uploads/{stored}',
        'name': file.filename,
        'size': size,
        'is_image': ext in {'.png', '.jpg', '.jpeg', '.gif', '.webp'},
    }), 201


# ───────────────────────────────────────────────────────────
# 第二批扩充：投票帖
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/posts/<int:post_id>/vote', methods=['POST'])
@limiter.limit('60/minute')
def vote_post(post_id):
    """投票：一个用户对同一帖只保留一票，可改投。"""
    user, err = require_login()
    if err:
        return err

    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)

    data = request.get_json(silent=True) or {}
    try:
        option_id = int(data.get('option_id'))
    except (TypeError, ValueError):
        return _err('请选择一个投票选项')

    option = CommunityPollOption.query.filter_by(
        id=option_id, post_id=post_id
    ).first()
    if not option:
        return _err('投票选项不存在', 404)

    vote = CommunityPollVote.query.filter_by(
        post_id=post_id, user_id=user.id
    ).first()
    if vote:
        vote.option_id = option.id
    else:
        db.session.add(CommunityPollVote(
            post_id=post_id, option_id=option.id, user_id=user.id
        ))
    db.session.commit()

    return _ok(_poll_serialize(post, user))


# ───────────────────────────────────────────────────────────
# 第二批扩充：采纳答案
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/posts/<int:post_id>/accept', methods=['PUT'])
@limiter.limit('60/minute')
def accept_answer(post_id):
    """采纳回答：仅帖子作者可操作；采纳后帖子自动标记已解决。"""
    user, err = require_login()
    if err:
        return err

    post = CommunityPost.query.get(post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)
    if post.author_id != user.id:
        return _err('只有帖子作者可以采纳答案', 403)

    data = request.get_json(silent=True) or {}
    comment_id = data.get('comment_id')

    if not comment_id:
        post.accepted_comment_id = None
        post.is_resolved = False
        post.resolved_at = None
        post.resolved_by = None
        db.session.commit()
        return _ok(_post_serialize(post, user))

    try:
        comment_id = int(comment_id)
    except (TypeError, ValueError):
        return _err('无效的回答 ID')

    comment = CommunityComment.query.get(comment_id)
    if not comment or comment.deleted or comment.post_id != post_id:
        return _err('回答不存在或不属于该帖子', 404)

    changed = post.accepted_comment_id != comment.id
    post.accepted_comment_id = comment.id
    post.is_resolved = True
    post.resolved_at = utcnow()
    post.resolved_by = user.id
    if changed:
        # 第三批：采纳 +15 积分，悬赏转给最佳答案作者（仅首次采纳发放）
        _award_points(comment.author_id, 15, 'accept', 'comment', comment.id)
        if post.bounty_points and not post.bounty_rewarded:
            _award_points(comment.author_id, post.bounty_points,
                          'bounty_reward', 'post', post.id)
            post.bounty_rewarded = True
        _notify(comment.author_id, user.id, 'accept', post_id=post.id,
                comment_id=comment.id, content='你的回答被采纳为最佳答案')
        # v6.1 跨模块掌握度信号：被采纳回答视为对帖子标签对应知识点的掌握验证
        # 权重 0.3（弱于考试/作业的 1.0），避免刷社区回答刷高掌握度
        try:
            from api.learning_engine import update_mastery, resolve_kp_ids_by_names
            tag_names = (post.tags or '').split(',') if post.tags else []
            kp_ids = resolve_kp_ids_by_names(tag_names)
            if kp_ids:
                update_mastery(comment.author_id, kp_ids, 0.3)
        except Exception as e:
            # 掌握度更新为非关键路径，失败不影响采纳主流程
            from utils.logger import logger
            logger.warning('community accept mastery update failed: %s', e)
    db.session.commit()

    return _ok(_post_serialize(post, user))


# ───────────────────────────────────────────────────────────
# 第二批扩充：热门标签
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/tags', methods=['GET'])
@limiter.limit('120/minute')
def list_tags():
    """热门标签：聚合未删除帖子的 tags，按出现次数倒序取前 20。"""
    rows = db.session.query(CommunityPost.tags).filter(
        CommunityPost.deleted == False,
        CommunityPost.tags.isnot(None),
        CommunityPost.tags != '',
    ).all()

    counter = Counter()
    for (tags_text,) in rows:
        for t in (tags_text or '').split(','):
            t = t.strip()
            if t:
                counter[t] += 1

    return _ok([
        {'tag': tag, 'count': count}
        for tag, count in counter.most_common(20)
    ])


# ───────────────────────────────────────────────────────────
# 第二批扩充：个人主页
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/users/<int:user_id>', methods=['GET'])
@limiter.limit('120/minute')
def get_user_profile(user_id):
    """公开个人主页：基本信息 + 发帖/评论累计 + 帖子/评论分页列表。

    匿名内容只对本人和老师/管理员可见，避免通过主页反查匿名作者。"""
    viewer = verify_token()

    user = User.query.get(user_id)
    if not user:
        return _err('用户不存在', 404)

    is_self = viewer is not None and viewer.id == user.id
    is_teacher_or_admin = viewer is not None and viewer.role in ('teacher', 'admin')
    can_see_anon = is_self or is_teacher_or_admin

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, request.args.get('per_page', 20, type=int))

    post_query = CommunityPost.query.filter_by(author_id=user_id, deleted=False)
    comment_query = CommunityComment.query.filter_by(author_id=user_id, deleted=False)
    if not can_see_anon:
        post_query = post_query.filter_by(is_anonymous=False)
        comment_query = comment_query.filter_by(is_anonymous=False)

    post_total = post_query.count()
    comment_total = comment_query.count()
    resolved_total = post_query.filter_by(is_resolved=True).count()
    accepted_total = db.session.query(func.count(CommunityComment.id)).join(
        CommunityPost, CommunityComment.post_id == CommunityPost.id
    ).filter(
        CommunityComment.author_id == user_id,
        CommunityComment.deleted == False,
        CommunityPost.accepted_comment_id == CommunityComment.id,
    ).scalar() or 0
    like_received = db.session.query(
        func.coalesce(func.sum(CommunityPost.like_count), 0)
    ).filter(
        CommunityPost.author_id == user_id,
        CommunityPost.deleted == False,
    ).scalar() or 0

    posts_page = post_query.order_by(desc(CommunityPost.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    comments_page = comment_query.order_by(desc(CommunityComment.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    comment_items = []
    for c in comments_page.items:
        d = _comment_serialize(c, viewer)
        d['post_title'] = c.post.title if c.post else None
        comment_items.append(d)

    return _ok({
        'user': {
            'id': user.id,
            'username': user.username,
            'role': user.role,
            'created_at': user.created_at.isoformat() if user.created_at else None,
        },
        'stats': {
            'post_count': post_total,
            'comment_count': comment_total,
            'resolved_count': resolved_total,
            'accepted_count': int(accepted_total),
            'like_received': int(like_received),
            **{k: v for k, v in _level_info(
                (CommunityUserStat.query.filter_by(user_id=user_id).first() or
                 CommunityUserStat(points=0)).points
            ).items()},
            'rank': 1 + CommunityUserStat.query.filter(
                CommunityUserStat.points > (
                    CommunityUserStat.query.filter_by(user_id=user_id).first() or
                    CommunityUserStat(points=0)
                ).points
            ).count(),
        },
        'posts': {
            'items': [_post_serialize(p, viewer) for p in posts_page.items],
            'total': posts_page.total,
            'page': page,
            'pages': posts_page.pages,
        },
        'comments': {
            'items': comment_items,
            'total': comments_page.total,
            'page': page,
            'pages': comments_page.pages,
        },
    })


# ───────────────────────────────────────────────────────────
# 第二批扩充：社区管理后台
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/admin/stats', methods=['GET'])
@limiter.limit('120/minute')
def admin_stats():
    user, err = _require_teacher_or_admin()
    if err:
        return err

    today_start = local_day_start()
    return _ok({
        'total_posts': CommunityPost.query.filter_by(deleted=False).count(),
        'total_comments': CommunityComment.query.filter_by(deleted=False).count(),
        'hidden_posts': CommunityPost.query.filter_by(deleted=False, hidden=True).count(),
        'hidden_comments': CommunityComment.query.filter_by(deleted=False, hidden=True).count(),
        'resolved_posts': CommunityPost.query.filter_by(deleted=False, is_resolved=True).count(),
        'pending_reports': CommunityReport.query.filter_by(status='pending').count(),
        'today_posts': CommunityPost.query.filter(
            CommunityPost.deleted == False,
            CommunityPost.created_at >= today_start,
        ).count(),
        'active_authors': db.session.query(
            func.count(func.distinct(CommunityPost.author_id))
        ).filter(CommunityPost.deleted == False).scalar() or 0,
    })


@api_community_bp.route('/community/admin/posts', methods=['GET'])
@limiter.limit('120/minute')
def admin_list_posts():
    """管理列表：包含 hidden / deleted；支持状态、分类、关键字、作者过滤。"""
    user, err = _require_teacher_or_admin()
    if err:
        return err

    status = request.args.get('status', 'all').strip()
    category = request.args.get('category', '').strip() or None
    q = request.args.get('q', '').strip()
    author_id = request.args.get('author_id', type=int)
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, request.args.get('per_page', 20, type=int))

    query = CommunityPost.query
    if status == 'normal':
        query = query.filter_by(deleted=False, hidden=False)
    elif status == 'hidden':
        query = query.filter_by(deleted=False, hidden=True)
    elif status == 'deleted':
        query = query.filter_by(deleted=True)
    elif status == 'resolved':
        query = query.filter_by(deleted=False, is_resolved=True)
    if category:
        query = query.filter_by(category=category)
    if author_id:
        query = query.filter_by(author_id=author_id)
    if q:
        query = query.filter(or_(
            CommunityPost.title.ilike(f'%{q}%'),
            CommunityPost.content.ilike(f'%{q}%'),
        ))

    paginated = query.order_by(desc(CommunityPost.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for p in paginated.items:
        d = _post_serialize(p, user)
        d['author_username'] = p.author.username if p.author else None
        items.append(d)

    return _ok({
        'items': items,
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
    })


@api_community_bp.route('/community/admin/comments', methods=['GET'])
@limiter.limit('120/minute')
def admin_list_comments():
    """评论管理列表：包含 hidden / deleted，按帖子过滤可选。"""
    user, err = _require_teacher_or_admin()
    if err:
        return err

    post_id = request.args.get('post_id', type=int)
    status = request.args.get('status', 'all').strip()
    q = request.args.get('q', '').strip()
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(100, request.args.get('per_page', 20, type=int))

    query = CommunityComment.query
    if post_id:
        query = query.filter_by(post_id=post_id)
    if status == 'normal':
        query = query.filter_by(deleted=False, hidden=False)
    elif status == 'hidden':
        query = query.filter_by(deleted=False, hidden=True)
    elif status == 'deleted':
        query = query.filter_by(deleted=True)
    if q:
        query = query.filter(CommunityComment.content.ilike(f'%{q}%'))

    paginated = query.order_by(desc(CommunityComment.created_at)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for c in paginated.items:
        d = _comment_serialize(c, user)
        d['author_username'] = c.author.username if c.author else None
        d['post_title'] = c.post.title if c.post else None
        items.append(d)

    return _ok({
        'items': items,
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
    })


@api_community_bp.route('/community/admin/posts/<int:post_id>/visibility', methods=['PUT'])
@limiter.limit('60/minute')
def admin_set_post_visibility(post_id):
    user, err = _require_teacher_or_admin()
    if err:
        return err

    post = CommunityPost.query.get(post_id)
    if not post:
        return _err('帖子不存在', 404)

    data = request.get_json(silent=True) or {}
    hidden = bool(data.get('hidden', True))
    post.hidden = hidden
    if hidden:
        _notify(post.author_id, user.id, 'hidden', post_id=post.id,
                content='你的帖子已被管理员折叠')
    db.session.commit()

    return _ok(_post_serialize(post, user))


@api_community_bp.route('/community/admin/comments/<int:comment_id>/visibility', methods=['PUT'])
@limiter.limit('60/minute')
def admin_set_comment_visibility(comment_id):
    user, err = _require_teacher_or_admin()
    if err:
        return err

    comment = CommunityComment.query.get(comment_id)
    if not comment:
        return _err('评论不存在', 404)

    data = request.get_json(silent=True) or {}
    hidden = bool(data.get('hidden', True))
    comment.hidden = hidden
    if hidden:
        _notify(comment.author_id, user.id, 'hidden', post_id=comment.post_id,
                comment_id=comment.id, content='你的评论已被管理员折叠')
    db.session.commit()

    return _ok(_comment_serialize(comment, user))


# ───────────────────────────────────────────────────────────
# 第三批扩充：错题一键求助 / 班级圈子 / 我的积分
# ───────────────────────────────────────────────────────────

POINT_REASON_LABELS = {
    'post': '发布帖子',
    'comment': '发表评论',
    'accept': '答案被采纳',
    'like': '获得点赞',
    'bounty_hold': '设置悬赏',
    'bounty_reward': '获得悬赏',
    'bounty_refund': '悬赏退回',
}


def _format_question_options(options):
    """把题目选项格式化成可读文本（兼容字符串/字典两种历史形态）。"""
    if not isinstance(options, list):
        return ''
    lines = []
    for index, item in enumerate(options):
        letter = chr(ord('A') + index)
        if isinstance(item, dict):
            text = item.get('text') or item.get('value') or item.get('label') or ''
        else:
            text = item
        text = str(text).strip()
        if text:
            lines.append(f'{letter}. {text}')
    return '\n'.join(lines)


@api_community_bp.route('/community/ask-from-wrong-record', methods=['POST'])
@limiter.limit('10/minute')
def ask_from_wrong_record():
    """错题一键求助：由错题记录生成关联题目的求助帖（category=help）。"""
    user, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    try:
        record_id = int(data.get('wrong_record_id'))
    except (TypeError, ValueError):
        return _err('错题记录 ID 无效')

    record = WrongAnswerRecord.query.get(record_id)
    if not record or record.user_id != user.id:
        return _err('错题记录不存在', 404)
    question = record.question
    if not question:
        return _err('关联题目不存在', 404)

    try:
        bounty_points = int(data.get('bounty_points') or 0)
    except (TypeError, ValueError):
        return _err('悬赏积分格式无效')
    if bounty_points < 0 or bounty_points > 100:
        return _err('悬赏积分须在 0–100 之间')
    if bounty_points:
        stat = _get_stat(user.id)
        if (stat.points if stat else 0) < bounty_points:
            return _err('社区积分不足，无法设置该悬赏')

    is_anonymous = bool(data.get('is_anonymous', False))
    stem = (question.content or '').strip()
    one_line = re.sub(r'\s+', ' ', stem)
    title = (data.get('title') or '').strip() or f'【错题求助】{one_line[:80]}'
    if len(title) > 100:
        return _err('标题必填且 ≤ 100 字')

    custom_content = (data.get('content') or '').strip()
    if custom_content:
        content = custom_content[:5000]
    else:
        parts = ['我在错题本里遇到这道题，想请同学帮忙讲解正确思路。', '']
        if stem:
            parts.append(f'题目：{stem}')
        option_text = _format_question_options(question.options)
        if option_text:
            parts.append(option_text)
        if record.wrong_answer:
            parts.append(f'我的答案：{record.wrong_answer}')
        content = '\n'.join(parts)[:5000]

    tags, tag_err = _normalize_tags(data.get('tags'))
    if tag_err:
        return _err(tag_err)
    if tags is None and question.knowledge:
        # 知识点可能是逗号分隔的长串，自动取前 5 个作为标签，不阻断求助
        tags, _ = _normalize_tags(','.join((question.knowledge or '').split(',')[:5]))

    anon_index = None
    if is_anonymous:
        max_idx = db.session.query(func.max(CommunityPost.anon_index)).filter(
            CommunityPost.author_id == user.id,
            CommunityPost.is_anonymous == True,
        ).scalar()
        anon_index = (max_idx or 0) + 1

    post = CommunityPost(
        title=title,
        content=content,
        category='help',
        author_id=user.id,
        linked_type='question',
        linked_id=question.id,
        is_anonymous=is_anonymous,
        anon_index=anon_index,
        tags=tags,
        course_id=question.course_id,
        bounty_points=bounty_points,
    )
    db.session.add(post)
    db.session.flush()

    _award_points(user.id, 5, 'post', 'post', post.id)
    if bounty_points:
        _award_points(user.id, -bounty_points, 'bounty_hold', 'post', post.id)

    _notify_mentions(content, user.id, post.id)
    db.session.commit()

    return _ok(_post_serialize(post, user)), 201


@api_community_bp.route('/community/circles', methods=['GET'])
@limiter.limit('120/minute')
def list_circles():
    """班级圈子：按课程聚合，返回帖子数，按帖子数倒序。"""
    q = request.args.get('q', '').strip()

    courses_query = Course.query
    if q:
        courses_query = courses_query.filter(Course.name.ilike(f'%{q}%'))
    courses = courses_query.order_by(Course.name.asc()).all()

    counts = dict(db.session.query(
        CommunityPost.course_id, func.count(CommunityPost.id)
    ).filter(
        CommunityPost.deleted == False,
        CommunityPost.course_id.isnot(None),
    ).group_by(CommunityPost.course_id).all())

    items = [{
        'course_id': c.id,
        'name': c.name,
        'post_count': counts.get(c.id, 0),
        'major_id': c.major_id,
        'major_name': c.major.name if c.major else None,
    } for c in courses]
    items.sort(key=lambda x: (-x['post_count'], x['name']))

    return _ok({'items': items, 'total': len(items)})


@api_community_bp.route('/community/me/points', methods=['GET'])
@limiter.limit('120/minute')
def my_points():
    """我的社区积分：余额、等级、排名与最近流水。"""
    user, err = require_login()
    if err:
        return err

    stat = _get_stat(user.id)
    points = stat.points if stat else 0
    rank = 1 + CommunityUserStat.query.filter(
        CommunityUserStat.points > points
    ).count()

    limit = min(50, max(1, request.args.get('limit', 20, type=int)))
    logs = CommunityPointLog.query.filter_by(user_id=user.id).order_by(
        desc(CommunityPointLog.created_at), desc(CommunityPointLog.id)
    ).limit(limit).all()

    return _ok({
        **_level_info(points),
        'rank': rank,
        'logs': [{
            'id': l.id,
            'delta': l.delta,
            'reason': l.reason,
            'reason_label': POINT_REASON_LABELS.get(l.reason, l.reason),
            'related_type': l.related_type,
            'related_id': l.related_id,
            'created_at': l.created_at.isoformat() if l.created_at else None,
        } for l in logs],
    })
