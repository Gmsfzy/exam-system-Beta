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
from datetime import timedelta

from flask import Blueprint, request, jsonify
from sqlalchemy import desc, or_, and_, func
from sqlalchemy.exc import IntegrityError

from database import db
from database.models import (
    User, Course, Question, Exam, WrongAnswerRecord, UserFollow,
    CommunityPost, CommunityComment, CommunityLike,
    CommunityFavorite, CommunityNotification, CommunityReport,
    CommunityPollOption, CommunityPollVote, CommunityUserStat, CommunityPointLog,
    CommunityCategoryEnum, CommunityLinkTypeEnum,
    CommunityMoment, CommunityMomentComment, CommunityTopic,
    CommunityMomentTopic, CommunityMomentFavorite,
    CommunityMomentVisibilityEnum, CommunityRepostTypeEnum,
    CommunityDmConversation, CommunityDmMessage, CommunityUserBlock,
    CommunityDmAccessLog,
)
from utils.notify import create_notification
from homework.models import Homework
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


def _post_serialize(post, viewer, viewer_liked_ids=None, viewer_fav_ids=None):
    """帖子序列化（viewer 用于匿名权限判断；viewer_liked_ids/viewer_fav_ids 可预查集合避免 N+1）"""
    data = post.to_dict(viewer=viewer)
    if viewer:
        data['liked'] = (post.id in viewer_liked_ids) if viewer_liked_ids is not None else _is_liked('post', post.id, viewer)
        data['favorited'] = (post.id in viewer_fav_ids) if viewer_fav_ids is not None else _is_favorited(post.id, viewer)
    else:
        data['liked'] = False
        data['favorited'] = False
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


def _comment_serialize(comment, viewer, viewer_liked_ids=None):
    data = comment.to_dict(viewer=viewer)
    if viewer:
        data['liked'] = (comment.id in viewer_liked_ids) if viewer_liked_ids is not None else _is_liked('comment', comment.id, viewer)
    else:
        data['liked'] = False
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


def _notify(user_id, actor_id, ntype, post_id=None, comment_id=None, content=None,
            moment_id=None, moment_comment_id=None):
    """写一条社区通知；自己触发的动作不再通知自己。"""
    if not user_id or user_id == actor_id:
        return None
    n = CommunityNotification(
        user_id=user_id,
        actor_id=actor_id,
        type=ntype,
        post_id=post_id,
        comment_id=comment_id,
        moment_id=moment_id,
        moment_comment_id=moment_comment_id,
        content=(content or '')[:200] or None,
    )
    db.session.add(n)
    return n


def _notify_mentions(text, actor_id, post_id, comment_id=None):
    for u in _extract_mentions(text):
        _notify(u.id, actor_id, 'mention', post_id=post_id,
                comment_id=comment_id, content=f'@{u.username} 你被提及了')


def _notify_moment_mentions(text, actor_id, moment_id, moment_comment_id=None):
    """动态/动态评论里的 @ 提及：落到通知中心的 moment_id 上。"""
    for u in _extract_mentions(text):
        _notify(u.id, actor_id, 'mention', moment_id=moment_id,
                moment_comment_id=moment_comment_id,
                content=f'@{u.username} 你被提及了')


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
        elif target_type == 'moment':
            _notify(obj.author_id, None, 'hidden', moment_id=obj.id,
                    content='你的动态因多次举报已被折叠，管理员会尽快处理')
        elif target_type == 'mcomment':
            _notify(obj.author_id, None, 'hidden', moment_id=obj.moment_id,
                    moment_comment_id=obj.id, content='你的评论因多次举报已被折叠')
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
        'question': Question,
        'homework': Homework,
        'exam': Exam,
    }
    M = model_map.get(linked_type)
    if M is None:
        return False
    try:
        return db.session.get(M, int(linked_id)) is not None
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

    # hidden 过滤：老师/管理员能看到全部，普通用户只能看到未被折叠的 + 自己的被折叠帖
    if viewer and viewer.role in ('teacher', 'admin'):
        query = CommunityPost.query.filter_by(deleted=False)
    else:
        query = CommunityPost.query.filter_by(deleted=False)
        query = query.filter(or_(
            CommunityPost.hidden == False,  # noqa: E712
            CommunityPost.author_id == (viewer.id if viewer else -1),
        ))
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

    # N+1 优化：预批量查询 viewer 对这批帖子的点赞/收藏
    posts_list = paginated.items
    post_ids = [p.id for p in posts_list]
    viewer_liked_ids = set()
    viewer_fav_ids = set()
    if viewer and post_ids:
        likes = CommunityLike.query.filter(
            CommunityLike.user_id == viewer.id,
            CommunityLike.target_type == 'post',
            CommunityLike.target_id.in_(post_ids),
        ).all()
        viewer_liked_ids = {l.target_id for l in likes}
        favs = CommunityFavorite.query.filter(
            CommunityFavorite.user_id == viewer.id,
            CommunityFavorite.post_id.in_(post_ids),
        ).all()
        viewer_fav_ids = {f.post_id for f in favs}

    posts = [_post_serialize(p, viewer, viewer_liked_ids, viewer_fav_ids) for p in posts_list]
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
    post = db.session.get(CommunityPost, post_id)
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
        if not db.session.get(Course, course_id):
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

    post = db.session.get(CommunityPost, post_id)
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
            if not db.session.get(Course, cid):
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

    post = db.session.get(CommunityPost, post_id)
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

    target_type: post/comment（论坛）与 moment/mcomment（动态）共用同一张点赞表。
    返回 (ok, error, status_code)"""
    if target_type not in ('post', 'comment', 'moment', 'mcomment'):
        return False, '无效点赞目标类型', 400

    # 校验目标存在
    if target_type == 'post':
        obj = db.session.get(CommunityPost, target_id)
        if not obj or obj.deleted:
            return False, '帖子不存在或已删除', 404
    elif target_type == 'comment':
        obj = db.session.get(CommunityComment, target_id)
        if not obj or obj.deleted:
            return False, '评论不存在或已删除', 404
    elif target_type == 'moment':
        obj = db.session.get(CommunityMoment, target_id)
        if not obj or obj.deleted:
            return False, '动态不存在或已删除', 404
    else:
        obj = db.session.get(CommunityMomentComment, target_id)
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

    post = db.session.get(CommunityPost, post_id)
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

    comment = db.session.get(CommunityComment, comment_id)
    return _ok({'liked': value, 'like_count': comment.like_count})


# ───────────────────────────────────────────────────────────
# 评论
# ───────────────────────────────────────────────────────────

@api_community_bp.route('/community/posts/<int:post_id>/comments', methods=['GET'])
@limiter.limit('120/minute')
def list_comments(post_id):
    viewer = verify_token()

    post = db.session.get(CommunityPost, post_id)
    if not post or post.deleted:
        return _err('帖子不存在或已删除', 404)

    comments = CommunityComment.query.filter_by(
        post_id=post_id, deleted=False
    ).order_by(CommunityComment.created_at.asc()).all()

    # N+1 优化：预批量查询 viewer 对这批评论的点赞
    comment_ids = [c.id for c in comments]
    comment_liked_ids = set()
    if viewer and comment_ids:
        likes = CommunityLike.query.filter(
            CommunityLike.user_id == viewer.id,
            CommunityLike.target_type == 'comment',
            CommunityLike.target_id.in_(comment_ids),
        ).all()
        comment_liked_ids = {l.target_id for l in likes}

    return _ok([_comment_serialize(c, viewer, comment_liked_ids) for c in comments])


@api_community_bp.route('/community/posts/<int:post_id>/comments', methods=['POST'])
@limiter.limit('30/minute')
def create_comment(post_id):
    user, err = require_login()
    if err:
        return err

    post = db.session.get(CommunityPost, post_id)
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
        parent = db.session.get(CommunityComment, parent_id)
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

    comment = db.session.get(CommunityComment, comment_id)
    if not comment or comment.deleted:
        return _err('评论不存在或已删除', 404)

    # 权限：评论作者 / 帖子作者 / 老师 / 管理员
    post = db.session.get(CommunityPost, comment.post_id)
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

    post = db.session.get(CommunityPost, post_id)
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

    post = db.session.get(CommunityPost, post_id)
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

    n = db.session.get(CommunityNotification, notification_id)
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


REPORT_TARGET_TYPES = ('post', 'comment', 'moment', 'mcomment', 'dm_message')


def _load_report_target(target_type, target_id):
    model_map = {
        'post': CommunityPost,
        'comment': CommunityComment,
        'moment': CommunityMoment,
        'mcomment': CommunityMomentComment,
        'dm_message': CommunityDmMessage,
    }
    model = model_map.get(target_type)
    return db.session.get(model, target_id) if model else None


def _report_target(rep):
    """举报队列展示用：带出被举报内容的摘要。"""
    data = rep.to_dict()
    target = _load_report_target(rep.target_type, rep.target_id)
    if target:
        data['target_title'] = getattr(target, 'title', None)
        data['target_content'] = (target.content or '')[:200]
        data['target_author_id'] = (target.sender_id if rep.target_type == 'dm_message'
                                    else target.author_id)
        data['target_deleted'] = bool(getattr(target, 'deleted', False))
        data['target_hidden'] = bool(getattr(target, 'hidden', False))
        if rep.target_type == 'comment':
            data['target_post_id'] = target.post_id
        elif rep.target_type == 'mcomment':
            data['target_moment_id'] = target.moment_id
        elif rep.target_type == 'dm_message':
            data['target_conversation_id'] = target.conversation_id
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

    if target_type not in REPORT_TARGET_TYPES:
        return _err('无效举报对象类型')
    if not target_id or not reason or len(reason) > 200:
        return _err('举报理由必填且 ≤ 200 字')

    target = _load_report_target(target_type, target_id)
    if not target:
        return _err('举报的内容不存在或已删除', 404)
    target_author_id = target.sender_id if target_type == 'dm_message' else target.author_id
    if target_author_id == user.id:
        return _err('不能举报自己的内容')
    if target_type == 'dm_message' and user.id not in (target.sender_id, target.receiver_id):
        return _err('无权举报该私信', 403)
    if target_type != 'dm_message' and target.deleted:
        return _err('举报的内容不存在或已删除', 404)

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
    if target_type == 'dm_message':
        # 私信按合规要求保留原文，仅进入人工队列，不做自动折叠
        pending = CommunityReport.query.filter_by(
            target_type=target_type, target_id=target.id, status='pending'
        ).count()
        hidden = False
    else:
        pending = _auto_fold_if_needed(target_type, target)
        hidden = target.hidden
    db.session.commit()

    return _ok({
        'report': rep.to_dict(),
        'report_count': pending,
        'hidden': hidden,
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

    rep = db.session.get(CommunityReport, report_id)
    if not rep:
        return _err('举报记录不存在', 404)
    if rep.status != 'pending':
        return _err('该举报已处理', 400)

    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()
    if action not in ('dismiss', 'remove'):
        return _err('action 只能是 dismiss 或 remove')

    target = _load_report_target(rep.target_type, rep.target_id)

    if rep.target_type == 'dm_message':
        # 私信正文按合规要求留存，处理结论只影响举报状态，不删改原文
        if action == 'remove' and target:
            _notify(target.sender_id, user.id, 'report', content='你的一条私信因违规被管理员处理')
    elif action == 'remove' and target and not target.deleted:
        target.deleted = True
        if rep.target_type == 'post':
            _notify(target.author_id, user.id, 'report', post_id=target.id,
                    content='你的帖子因违规已被管理员删除')
        elif rep.target_type == 'comment':
            _notify(target.author_id, user.id, 'report', post_id=target.post_id,
                    comment_id=target.id, content='你的评论因违规已被管理员删除')
        elif rep.target_type == 'moment':
            _notify(target.author_id, user.id, 'report', moment_id=target.id,
                    content='你的动态因违规已被管理员删除')
        else:
            _notify(target.author_id, user.id, 'report', moment_id=target.moment_id,
                    moment_comment_id=target.id, content='你的评论因违规已被管理员删除')

    rep.status = 'handled' if action == 'remove' else 'dismissed'
    rep.handled_by = user.id
    rep.handled_at = utcnow()

    if target and rep.target_type != 'dm_message':
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

    post = db.session.get(CommunityPost, post_id)
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

    post = db.session.get(CommunityPost, post_id)
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

    comment = db.session.get(CommunityComment, comment_id)
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

    user = db.session.get(User, user_id)
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

    post = db.session.get(CommunityPost, post_id)
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

    comment = db.session.get(CommunityComment, comment_id)
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

    record = db.session.get(WrongAnswerRecord, record_id)
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


# ═══════════════════════════════════════════════════════════
# v7.25 微博化：动态（moment）
# 与论坛帖并行：一句话/短文 + 转发引用 + 话题 + 关注流 + 私信（P2 另段）
# ═══════════════════════════════════════════════════════════

def _moment_visibility_clause(viewer):
    """当前 viewer 可见的可见范围条件（不含 deleted/hidden）。"""
    public = CommunityMoment.visibility == CommunityMomentVisibilityEnum.PUBLIC
    if viewer is None:
        return public
    own = CommunityMoment.author_id == viewer.id
    followers_only = CommunityMoment.visibility == CommunityMomentVisibilityEnum.FOLLOWERS
    if viewer.role in ('teacher', 'admin'):
        return or_(public, followers_only, own)
    # 仅关注者可见：作者本人 + 关注了作者的人（相关 EXISTS 命中索引）
    followed_by_viewer = db.session.query(UserFollow.id).filter(
        UserFollow.follower_id == viewer.id,
        UserFollow.followee_id == CommunityMoment.author_id,
    ).exists()
    return or_(public, own, and_(followers_only, followed_by_viewer))


def _apply_moment_filters(query, viewer):
    """统一叠加 deleted / hidden / visibility 过滤（与帖子列表口径对齐）。"""
    query = query.filter(CommunityMoment.deleted == False)  # noqa: E712
    if not (viewer and viewer.role in ('teacher', 'admin')):
        query = query.filter(or_(
            CommunityMoment.hidden == False,  # noqa: E712
            CommunityMoment.author_id == (viewer.id if viewer else -1),
        ))
    return query.filter(_moment_visibility_clause(viewer))


def _can_view_moment(moment, viewer):
    if not moment or moment.deleted:
        return False
    if viewer and moment.author_id == viewer.id:
        return True
    if moment.visibility == CommunityMomentVisibilityEnum.PUBLIC:
        return True
    if viewer is None:
        return False
    if viewer.role in ('teacher', 'admin'):
        return moment.visibility != CommunityMomentVisibilityEnum.PRIVATE
    if moment.visibility == CommunityMomentVisibilityEnum.FOLLOWERS:
        return UserFollow.query.filter_by(
            follower_id=viewer.id, followee_id=moment.author_id
        ).first() is not None
    return False


def _moment_topics_map(moment_ids):
    """批量查动态话题，避免卡片逐条查询。"""
    if not moment_ids:
        return {}
    rows = db.session.query(
        CommunityMomentTopic.moment_id, CommunityTopic.id, CommunityTopic.name,
    ).join(
        CommunityTopic, CommunityTopic.id == CommunityMomentTopic.topic_id
    ).filter(CommunityMomentTopic.moment_id.in_(moment_ids)).all()
    mapping = {}
    for moment_id, topic_id, name in rows:
        mapping.setdefault(moment_id, []).append({'id': topic_id, 'name': name})
    return mapping


def _moment_author_followed_ids(viewer, moments):
    if not viewer or not moments:
        return set()
    author_ids = {m.author_id for m in moments if not m.is_anonymous or m.author_id == viewer.id}
    if not author_ids:
        return set()
    return {row[0] for row in db.session.query(UserFollow.followee_id).filter(
        UserFollow.follower_id == viewer.id,
        UserFollow.followee_id.in_(author_ids),
    ).all()}


def _moment_serialize(moment, viewer, liked_ids=None, fav_ids=None,
                      topics_map=None, followed_ids=None):
    data = moment.to_dict(viewer=viewer)
    data['liked'] = bool(viewer and (
        moment.id in liked_ids if liked_ids is not None else _is_liked('moment', moment.id, viewer)
    ))
    if viewer:
        data['favorited'] = bool(
            moment.id in fav_ids if fav_ids is not None else _is_moment_favorited(moment.id, viewer)
        )
    else:
        data['favorited'] = False
    data['like_count'] = _hot_like_count('moment', moment.id, moment.like_count)
    if topics_map is None:
        data['topics'] = _moment_topics_map([moment.id]).get(moment.id, [])
    else:
        data['topics'] = topics_map.get(moment.id, [])
    data['author_followed'] = bool(
        viewer and not moment.is_anonymous and moment.author_id in (followed_ids or set())
    )
    return data


def _serialize_moments(moments, viewer):
    """feed / 列表统一序列化：一次预查点赞、收藏、话题、关注关系。"""
    ids = [m.id for m in moments]
    liked_ids, fav_ids = set(), set()
    if viewer and ids:
        liked_ids = {row[0] for row in db.session.query(CommunityLike.target_id).filter(
            CommunityLike.user_id == viewer.id,
            CommunityLike.target_type == 'moment',
            CommunityLike.target_id.in_(ids),
        ).all()}
        fav_ids = {row[0] for row in db.session.query(CommunityMomentFavorite.moment_id).filter(
            CommunityMomentFavorite.user_id == viewer.id,
            CommunityMomentFavorite.moment_id.in_(ids),
        ).all()}
    topics_map = _moment_topics_map(ids)
    followed_ids = _moment_author_followed_ids(viewer, moments)
    return [
        _moment_serialize(m, viewer, liked_ids, fav_ids, topics_map, followed_ids)
        for m in moments
    ]


def _is_moment_favorited(moment_id, user):
    if not user:
        return False
    return CommunityMomentFavorite.query.filter_by(
        moment_id=moment_id, user_id=user.id
    ).first() is not None


def _mcomment_serialize(comment, viewer, liked_ids=None):
    data = comment.to_dict(viewer=viewer)
    data['liked'] = bool(viewer and (
        comment.id in liked_ids if liked_ids is not None
        else _is_liked('mcomment', comment.id, viewer)
    ))
    data['like_count'] = _hot_like_count('mcomment', comment.id, comment.like_count)
    return data


def _moment_snapshot(moment):
    """转发快照：只读、脱敏，原动态删除后仍可展示。"""
    return {
        'id': moment.id,
        'author_id': moment.author_id,
        'display_username': moment.author.username if moment.author else '未知用户',
        'content': (moment.content or '')[:500],
        'created_at': moment.created_at.isoformat() if moment.created_at else None,
    }


def _attach_topics(moment, raw_topics, user):
    """写入话题关联：同名复用，最多 4 个、每个 ≤ 30 字。返回错误消息或 None。"""
    if raw_topics in (None, ''):
        return None
    if not isinstance(raw_topics, list):
        return '话题格式无效'
    names = []
    for item in raw_topics:
        name = str(item or '').strip().lstrip('#').rstrip('#')
        if not name:
            continue
        if len(name) > 30:
            return '单个话题 ≤ 30 字'
        if name not in names:
            names.append(name)
    if len(names) > 4:
        return '最多选择 4 个话题'
    for name in names:
        topic = CommunityTopic.query.filter_by(name=name).first()
        if not topic:
            topic = CommunityTopic(name=name, created_by=user.id)
            db.session.add(topic)
            db.session.flush()
        topic.moment_count = (topic.moment_count or 0) + 1
        db.session.add(CommunityMomentTopic(moment_id=moment.id, topic_id=topic.id))
    return None


def _detach_topics(moment):
    links = CommunityMomentTopic.query.filter_by(moment_id=moment.id).all()
    for link in links:
        topic = db.session.get(CommunityTopic, link.topic_id)
        if topic:
            topic.moment_count = max(0, (topic.moment_count or 0) - 1)
        db.session.delete(link)


def _parse_moment_payload(data, partial=False):
    """解析并校验动态正文。返回 (fields, error)。"""
    fields = {}
    if not partial or 'content' in data:
        content = (data.get('content') or '').strip()
        if len(content) > 500:
            return None, '短动态正文 ≤ 500 字'
        fields['content'] = content
    if not partial or 'long_body' in data:
        long_body = (data.get('long_body') or '').strip() or None
        if long_body and len(long_body) > 20000:
            return None, '长文正文 ≤ 20000 字'
        fields['long_body'] = long_body
        fields['is_long'] = bool(long_body)
    if not partial:
        if not fields.get('content') and not fields.get('long_body'):
            return None, '动态内容不能为空'
        visibility = data.get('visibility') or CommunityMomentVisibilityEnum.PUBLIC
        if visibility not in CommunityMomentVisibilityEnum.ALL:
            return None, '无效的可见范围'
        fields['visibility'] = visibility
        fields['is_anonymous'] = bool(data.get('is_anonymous', False))
    return fields, None


@api_community_bp.route('/community/feed', methods=['GET'])
@limiter.limit('120/minute')
def moment_feed():
    """动态流：recommend 推荐 / follow 关注 / user 个人 / topic 话题。

    公开流用 before_id 游标（倒序插入下不会翻页漂移）。"""
    viewer = verify_token()
    tab = (request.args.get('tab') or 'recommend').strip()
    before_id = request.args.get('before_id', type=int)
    limit = min(50, max(1, request.args.get('limit', 20, type=int)))

    query = CommunityMoment.query
    if tab == 'follow':
        user, err = require_login()
        if err:
            return err
        viewer = user
        query = query.filter(db.session.query(UserFollow.id).filter(
            UserFollow.follower_id == viewer.id,
            UserFollow.followee_id == CommunityMoment.author_id,
        ).exists())
    elif tab == 'user':
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return _err('缺少 user_id')
        author = db.session.get(User, user_id)
        if not author:
            return _err('用户不存在', 404)
        query = query.filter(CommunityMoment.author_id == user_id)
        can_see_anon = viewer is not None and (
            viewer.id == user_id or viewer.role in ('teacher', 'admin')
        )
        if not can_see_anon:
            query = query.filter(CommunityMoment.is_anonymous == False)  # noqa: E712
    elif tab == 'topic':
        topic_id = request.args.get('topic_id', type=int)
        if not topic_id:
            return _err('缺少 topic_id')
        query = query.filter(db.session.query(CommunityMomentTopic.id).filter(
            CommunityMomentTopic.topic_id == topic_id,
            CommunityMomentTopic.moment_id == CommunityMoment.id,
        ).exists())
    elif tab != 'recommend':
        return _err('无效的动态流类型')

    query = _apply_moment_filters(query, viewer)
    if before_id:
        query = query.filter(CommunityMoment.id < before_id)
    rows = query.order_by(desc(CommunityMoment.id)).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = _serialize_moments(rows, viewer)
    return _ok({
        'items': items,
        'next_cursor': rows[-1].id if (has_more and rows) else None,
        'has_more': has_more,
    })


@api_community_bp.route('/community/moments/<int:moment_id>', methods=['GET'])
@limiter.limit('120/minute')
def get_moment(moment_id):
    viewer = verify_token()
    moment = db.session.get(CommunityMoment, moment_id)
    if not moment or not _can_view_moment(moment, viewer):
        return _err('动态不存在或已删除', 404)

    comments = CommunityMomentComment.query.filter_by(
        moment_id=moment_id, deleted=False
    ).order_by(CommunityMomentComment.created_at.asc()).all()
    comment_ids = [c.id for c in comments]
    liked_ids = set()
    if viewer and comment_ids:
        liked_ids = {row[0] for row in db.session.query(CommunityLike.target_id).filter(
            CommunityLike.user_id == viewer.id,
            CommunityLike.target_type == 'mcomment',
            CommunityLike.target_id.in_(comment_ids),
        ).all()}

    data = _serialize_moments([moment], viewer)[0]
    data['comments'] = [_mcomment_serialize(c, viewer, liked_ids) for c in comments]
    return _ok(data)


@api_community_bp.route('/community/moments', methods=['POST'])
@limiter.limit('10/minute')
def create_moment():
    user, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    fields, payload_err = _parse_moment_payload(data)
    if payload_err:
        return _err(payload_err)

    anon_index = None
    if fields['is_anonymous']:
        max_idx = db.session.query(func.max(CommunityMoment.anon_index)).filter(
            CommunityMoment.author_id == user.id,
            CommunityMoment.is_anonymous == True,  # noqa: E712
        ).scalar()
        anon_index = (max_idx or 0) + 1

    moment = CommunityMoment(
        author_id=user.id,
        content=fields['content'],
        long_body=fields['long_body'],
        is_long=fields['is_long'],
        visibility=fields['visibility'],
        is_anonymous=fields['is_anonymous'],
        anon_index=anon_index,
    )
    db.session.add(moment)
    db.session.flush()

    topic_err = _attach_topics(moment, data.get('topics'), user)
    if topic_err:
        db.session.rollback()
        return _err(topic_err)

    _notify_moment_mentions(
        f"{fields['content']}\n{fields['long_body'] or ''}", user.id, moment.id
    )
    db.session.commit()
    return _ok(_moment_serialize(moment, user)), 201


@api_community_bp.route('/community/moments/<int:moment_id>', methods=['PUT'])
@limiter.limit('60/minute')
def update_moment(moment_id):
    user, err = require_login()
    if err:
        return err

    moment = db.session.get(CommunityMoment, moment_id)
    if not moment or moment.deleted:
        return _err('动态不存在或已删除', 404)
    if moment.author_id != user.id:
        return _err('无权编辑他人动态', 403)

    data = request.get_json(silent=True) or {}
    fields, payload_err = _parse_moment_payload(data, partial=True)
    if payload_err:
        return _err(payload_err)
    if 'visibility' in data:
        visibility = data.get('visibility')
        if visibility not in CommunityMomentVisibilityEnum.ALL:
            return _err('无效的可见范围')
        fields['visibility'] = visibility
    for key, value in fields.items():
        setattr(moment, key, value)
    if not moment.content and not moment.long_body:
        db.session.rollback()
        return _err('动态内容不能为空')
    if 'content' in fields or 'long_body' in fields:
        _notify_moment_mentions(
            f"{moment.content or ''}\n{moment.long_body or ''}", user.id, moment.id
        )

    db.session.commit()
    return _ok(_moment_serialize(moment, user))


@api_community_bp.route('/community/moments/<int:moment_id>', methods=['DELETE'])
@limiter.limit('60/minute')
def delete_moment(moment_id):
    user, err = require_login()
    if err:
        return err

    moment = db.session.get(CommunityMoment, moment_id)
    if not moment or moment.deleted:
        return _err('动态不存在或已删除', 404)
    if moment.author_id != user.id and user.role not in ('teacher', 'admin'):
        return _err('无权删除', 403)

    _detach_topics(moment)
    moment.deleted = True
    db.session.commit()
    return _ok({'deleted': True})


@api_community_bp.route('/community/users/<int:user_id>/moments', methods=['GET'])
@limiter.limit('120/minute')
def list_user_moments(user_id):
    """个人主页动态列表（匿名动态只对本人/教师可见）。"""
    viewer = verify_token()
    author = db.session.get(User, user_id)
    if not author:
        return _err('用户不存在', 404)

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, max(1, request.args.get('per_page', 20, type=int)))

    query = _apply_moment_filters(CommunityMoment.query.filter_by(author_id=user_id), viewer)
    can_see_anon = viewer is not None and (
        viewer.id == user_id or viewer.role in ('teacher', 'admin')
    )
    if not can_see_anon:
        query = query.filter(CommunityMoment.is_anonymous == False)  # noqa: E712

    paginated = query.order_by(desc(CommunityMoment.id)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return _ok({
        'items': _serialize_moments(paginated.items, viewer),
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
    })


# ── 互动：点赞 / 收藏 / 评论 ─────────────────────────────

@api_community_bp.route('/community/moments/<int:moment_id>/like', methods=['POST', 'DELETE'])
@limiter.limit('60/minute')
def like_moment(moment_id):
    user, err = require_login()
    if err:
        return err

    value = request.method == 'POST'
    ok, error, code = _toggle_like('moment', moment_id, user, value)
    if not ok:
        return _err(error, code)
    moment = db.session.get(CommunityMoment, moment_id)
    return _ok({'liked': value, 'like_count': moment.like_count})


@api_community_bp.route('/community/moment-comments/<int:comment_id>/like', methods=['POST', 'DELETE'])
@limiter.limit('60/minute')
def like_moment_comment(comment_id):
    user, err = require_login()
    if err:
        return err

    value = request.method == 'POST'
    ok, error, code = _toggle_like('mcomment', comment_id, user, value)
    if not ok:
        return _err(error, code)
    comment = db.session.get(CommunityMomentComment, comment_id)
    return _ok({'liked': value, 'like_count': comment.like_count})


@api_community_bp.route('/community/moments/<int:moment_id>/favorite', methods=['POST', 'DELETE'])
@limiter.limit('60/minute')
def favorite_moment(moment_id):
    user, err = require_login()
    if err:
        return err

    moment = db.session.get(CommunityMoment, moment_id)
    if not moment or moment.deleted or not _can_view_moment(moment, user):
        return _err('动态不存在或已删除', 404)

    existing = CommunityMomentFavorite.query.filter_by(
        moment_id=moment_id, user_id=user.id
    ).first()
    if request.method == 'POST':
        if not existing:
            db.session.add(CommunityMomentFavorite(moment_id=moment_id, user_id=user.id))
            moment.favorite_count = (moment.favorite_count or 0) + 1
            db.session.commit()
        favorited = True
    else:
        if existing:
            db.session.delete(existing)
            moment.favorite_count = max(0, (moment.favorite_count or 0) - 1)
            db.session.commit()
        favorited = False
    return _ok({'favorited': favorited, 'favorite_count': moment.favorite_count})


@api_community_bp.route('/community/moments/favorites', methods=['GET'])
@limiter.limit('120/minute')
def list_moment_favorites():
    user, err = require_login()
    if err:
        return err

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, max(1, request.args.get('per_page', 20, type=int)))
    query = CommunityMoment.query.join(
        CommunityMomentFavorite, CommunityMomentFavorite.moment_id == CommunityMoment.id
    ).filter(
        CommunityMomentFavorite.user_id == user.id,
        CommunityMoment.deleted == False,  # noqa: E712
    ).order_by(desc(CommunityMomentFavorite.created_at))

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    return _ok({
        'items': _serialize_moments(paginated.items, user),
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
    })


@api_community_bp.route('/community/moments/<int:moment_id>/comments', methods=['GET'])
@limiter.limit('120/minute')
def list_moment_comments(moment_id):
    viewer = verify_token()
    moment = db.session.get(CommunityMoment, moment_id)
    if not moment or not _can_view_moment(moment, viewer):
        return _err('动态不存在或已删除', 404)

    comments = CommunityMomentComment.query.filter_by(
        moment_id=moment_id, deleted=False
    ).order_by(CommunityMomentComment.created_at.asc()).all()
    comment_ids = [c.id for c in comments]
    liked_ids = set()
    if viewer and comment_ids:
        liked_ids = {row[0] for row in db.session.query(CommunityLike.target_id).filter(
            CommunityLike.user_id == viewer.id,
            CommunityLike.target_type == 'mcomment',
            CommunityLike.target_id.in_(comment_ids),
        ).all()}
    return _ok([_mcomment_serialize(c, viewer, liked_ids) for c in comments])


@api_community_bp.route('/community/moments/<int:moment_id>/comments', methods=['POST'])
@limiter.limit('30/minute')
def create_moment_comment(moment_id):
    user, err = require_login()
    if err:
        return err

    moment = db.session.get(CommunityMoment, moment_id)
    if not moment or not _can_view_moment(moment, user):
        return _err('动态不存在或已删除', 404)

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
        parent = db.session.get(CommunityMomentComment, parent_id)
        if not parent or parent.deleted or parent.moment_id != moment_id:
            return _err('回复的评论不存在或不属于该动态')

    anon_index = None
    if is_anonymous:
        max_idx = db.session.query(func.max(CommunityMomentComment.anon_index)).filter(
            CommunityMomentComment.author_id == user.id,
            CommunityMomentComment.is_anonymous == True,  # noqa: E712
        ).scalar()
        anon_index = (max_idx or 0) + 1

    comment = CommunityMomentComment(
        moment_id=moment_id,
        author_id=user.id,
        content=content,
        parent_id=parent_id or None,
        is_anonymous=is_anonymous,
        anon_index=anon_index,
    )
    db.session.add(comment)
    moment.comment_count = (moment.comment_count or 0) + 1
    db.session.flush()

    if parent:
        _notify(parent.author_id, user.id, 'moment_reply', moment_id=moment_id,
                moment_comment_id=comment.id, content=content)
    else:
        _notify(moment.author_id, user.id, 'moment_comment', moment_id=moment_id,
                moment_comment_id=comment.id, content=content)
    _notify_moment_mentions(content, user.id, moment_id, comment.id)

    db.session.commit()
    return _ok(_mcomment_serialize(comment, user)), 201


@api_community_bp.route('/community/moment-comments/<int:comment_id>', methods=['DELETE'])
@limiter.limit('60/minute')
def delete_moment_comment(comment_id):
    user, err = require_login()
    if err:
        return err

    comment = db.session.get(CommunityMomentComment, comment_id)
    if not comment or comment.deleted:
        return _err('评论不存在或已删除', 404)

    moment = db.session.get(CommunityMoment, comment.moment_id)
    is_moment_author = moment and moment.author_id == user.id
    if (comment.author_id != user.id
            and not is_moment_author
            and user.role not in ('teacher', 'admin')):
        return _err('无权删除', 403)

    to_delete = [comment]
    queue = [comment.id]
    while queue:
        children = CommunityMomentComment.query.filter(
            CommunityMomentComment.parent_id == queue.pop(0),
            CommunityMomentComment.deleted == False,  # noqa: E712
        ).all()
        for child in children:
            to_delete.append(child)
            queue.append(child.id)
    for c in to_delete:
        c.deleted = True
    if moment:
        moment.comment_count = max(0, (moment.comment_count or 0) - len(to_delete))
    db.session.commit()
    return _ok({'deleted': True, 'affected': len(to_delete)})


# ── 转发 / 引用 ──────────────────────────────────────────

@api_community_bp.route('/community/moments/<int:moment_id>/repost', methods=['POST'])
@limiter.limit('20/minute')
def repost_moment(moment_id):
    user, err = require_login()
    if err:
        return err

    target = db.session.get(CommunityMoment, moment_id)
    if not target or target.deleted:
        return _err('动态不存在或已删除', 404)
    if target.repost_of_id:
        return _err('不能转发一条转发动态', 400)
    if target.is_anonymous:
        return _err('匿名动态不可转发', 400)
    if target.visibility != CommunityMomentVisibilityEnum.PUBLIC:
        return _err('仅公开动态可转发', 400)

    data = request.get_json(silent=True) or {}
    quote = (data.get('quote') or '').strip()
    if len(quote) > 500:
        return _err('引用评论 ≤ 500 字')

    moment = CommunityMoment(
        author_id=user.id,
        content=quote,
        repost_of_id=target.id,
        repost_type=CommunityRepostTypeEnum.QUOTE if quote else CommunityRepostTypeEnum.REPOST,
        repost_snapshot=_moment_snapshot(target),
    )
    db.session.add(moment)
    target.repost_count = (target.repost_count or 0) + 1
    db.session.flush()

    _notify(target.author_id, user.id,
            'quote' if quote else 'repost',
            moment_id=target.id, content=quote or '转发了你的动态')
    if quote:
        _notify_moment_mentions(quote, user.id, moment.id)
    db.session.commit()
    return _ok(_moment_serialize(moment, user)), 201


@api_community_bp.route('/community/moments/<int:moment_id>/repost', methods=['DELETE'])
@limiter.limit('60/minute')
def cancel_repost(moment_id):
    user, err = require_login()
    if err:
        return err

    repost = CommunityMoment.query.filter_by(
        repost_of_id=moment_id, author_id=user.id, deleted=False
    ).order_by(desc(CommunityMoment.id)).first()
    if not repost:
        return _err('你还没有转发过该动态', 404)

    repost.deleted = True
    target = db.session.get(CommunityMoment, moment_id)
    if target:
        target.repost_count = max(0, (target.repost_count or 0) - 1)
    db.session.commit()
    return _ok({'deleted': True})


@api_community_bp.route('/community/moments/<int:moment_id>/reposts', methods=['GET'])
@limiter.limit('120/minute')
def list_reposts(moment_id):
    viewer = verify_token()
    target = db.session.get(CommunityMoment, moment_id)
    if not target or target.deleted:
        return _err('动态不存在或已删除', 404)

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, max(1, request.args.get('per_page', 20, type=int)))
    query = _apply_moment_filters(
        CommunityMoment.query.filter_by(repost_of_id=moment_id), viewer
    )
    paginated = query.order_by(desc(CommunityMoment.id)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return _ok({
        'items': _serialize_moments(paginated.items, viewer),
        'total': paginated.total,
        'page': page,
        'pages': paginated.pages,
    })


# ── 话题 / @ 补全 / 提及 ─────────────────────────────────

@api_community_bp.route('/community/topics', methods=['GET'])
@limiter.limit('120/minute')
def list_topics():
    q = (request.args.get('q') or '').strip()
    sort = (request.args.get('sort') or 'hot').strip()
    limit = min(50, max(1, request.args.get('limit', 20, type=int)))

    query = CommunityTopic.query.filter_by(is_hidden=False)
    if q:
        query = query.filter(CommunityTopic.name.ilike(f'%{q}%'))
    if sort == 'new':
        query = query.order_by(desc(CommunityTopic.created_at))
    else:
        query = query.order_by(desc(CommunityTopic.moment_count), desc(CommunityTopic.created_at))
    return _ok([t.to_dict() for t in query.limit(limit).all()])


@api_community_bp.route('/community/topics', methods=['POST'])
@limiter.limit('60/minute')
def create_topic():
    user, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip().lstrip('#').rstrip('#')
    if not name or len(name) > 30:
        return _err('话题名必填且 ≤ 30 字')

    topic = CommunityTopic.query.filter_by(name=name).first()
    if not topic:
        topic = CommunityTopic(name=name, created_by=user.id)
        db.session.add(topic)
        db.session.commit()
    return _ok(topic.to_dict()), 201


@api_community_bp.route('/community/topics/<int:topic_id>/moments', methods=['GET'])
@limiter.limit('120/minute')
def list_topic_moments(topic_id):
    viewer = verify_token()
    topic = db.session.get(CommunityTopic, topic_id)
    if not topic or topic.is_hidden:
        return _err('话题不存在', 404)

    before_id = request.args.get('before_id', type=int)
    limit = min(50, max(1, request.args.get('limit', 20, type=int)))
    query = _apply_moment_filters(
        CommunityMoment.query.filter(db.session.query(CommunityMomentTopic.id).filter(
            CommunityMomentTopic.topic_id == topic_id,
            CommunityMomentTopic.moment_id == CommunityMoment.id,
        ).exists()), viewer
    )
    if before_id:
        query = query.filter(CommunityMoment.id < before_id)
    rows = query.order_by(desc(CommunityMoment.id)).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return _ok({
        'topic': topic.to_dict(),
        'items': _serialize_moments(rows, viewer),
        'next_cursor': rows[-1].id if (has_more and rows) else None,
        'has_more': has_more,
    })


@api_community_bp.route('/community/users/autocomplete', methods=['GET'])
@limiter.limit('120/minute')
def username_autocomplete():
    viewer = verify_token()
    q = (request.args.get('q') or '').strip()
    if not q:
        return _ok([])
    users = User.query.filter(User.username.ilike(f'%{q}%')).order_by(User.username).limit(20).all()
    return _ok([{
        'id': u.id,
        'username': u.username,
        'role': u.role,
        'is_self': bool(viewer and viewer.id == u.id),
    } for u in users])


@api_community_bp.route('/community/mentions', methods=['GET'])
@limiter.limit('120/minute')
def list_mentions():
    """提到我的：直接复用通知中心里的 mention（moment_id 落点）。"""
    user, err = require_login()
    if err:
        return err

    before_id = request.args.get('before_id', type=int)
    limit = min(50, max(1, request.args.get('limit', 20, type=int)))
    query = CommunityNotification.query.filter_by(user_id=user.id, type='mention').filter(
        CommunityNotification.moment_id.isnot(None)
    )
    if before_id:
        query = query.filter(CommunityNotification.id < before_id)
    rows = query.order_by(desc(CommunityNotification.id)).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return _ok({
        'items': [n.to_dict() for n in rows],
        'next_cursor': rows[-1].id if (has_more and rows) else None,
        'has_more': has_more,
    })


# ── 关注关系读取（写入复用 /api/learning/users/<uid>/follow）────

@api_community_bp.route('/community/users/<int:user_id>/relations', methods=['GET'])
@limiter.limit('120/minute')
def list_relations(user_id):
    viewer = verify_token()
    target = db.session.get(User, user_id)
    if not target:
        return _err('用户不存在', 404)

    rel_type = (request.args.get('type') or 'following').strip()
    if rel_type not in ('following', 'fans', 'mutual'):
        return _err('type 只能是 following / fans / mutual')
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(50, max(1, request.args.get('per_page', 20, type=int)))

    if rel_type == 'following':
        query = User.query.join(UserFollow, UserFollow.followee_id == User.id).filter(
            UserFollow.follower_id == user_id
        ).order_by(desc(UserFollow.created_at))
    elif rel_type == 'fans':
        query = User.query.join(UserFollow, UserFollow.follower_id == User.id).filter(
            UserFollow.followee_id == user_id
        ).order_by(desc(UserFollow.created_at))
    else:
        f1 = db.aliased(UserFollow)
        f2 = db.aliased(UserFollow)
        query = User.query.join(f1, f1.followee_id == User.id).join(
            f2, and_(f2.follower_id == User.id, f2.followee_id == user_id)
        ).filter(f1.follower_id == user_id).order_by(desc(f1.created_at))

    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    items = paginated.items

    # 预批量查互关关系，避免逐行查询
    mutual_ids = set()
    followed_ids = set()
    if viewer and items:
        uids = [u.id for u in items]
        followed_ids = {row[0] for row in db.session.query(UserFollow.followee_id).filter(
            UserFollow.follower_id == viewer.id, UserFollow.followee_id.in_(uids)
        ).all()}
        mutual_ids = {row[0] for row in db.session.query(UserFollow.follower_id).filter(
            UserFollow.followee_id == viewer.id, UserFollow.follower_id.in_(uids)
        ).all()}

    return _ok({
        'type': rel_type,
        'items': [{
            'id': u.id,
            'username': u.username,
            'role': u.role,
            'is_self': bool(viewer and viewer.id == u.id),
            'is_following': u.id in followed_ids,
            'is_mutual': u.id in mutual_ids,
        } for u in items],
        'page': page,
        'per_page': per_page,
        'total': paginated.total,
        'pages': paginated.pages,
    })


@api_community_bp.route('/community/users/<int:user_id>/follow-stats', methods=['GET'])
@limiter.limit('120/minute')
def follow_stats(user_id):
    viewer = verify_token()
    target = db.session.get(User, user_id)
    if not target:
        return _err('用户不存在', 404)

    following_count = UserFollow.query.filter_by(follower_id=user_id).count()
    fans_count = UserFollow.query.filter_by(followee_id=user_id).count()
    f1 = db.aliased(UserFollow)
    f2 = db.aliased(UserFollow)
    mutual_count = db.session.query(func.count(f1.id)).filter(
        f1.follower_id == user_id,
        db.session.query(f2.id).filter(
            f2.follower_id == f1.followee_id,
            f2.followee_id == user_id,
        ).exists(),
    ).scalar() or 0

    is_following = bool(viewer and UserFollow.query.filter_by(
        follower_id=viewer.id, followee_id=user_id
    ).first())
    is_followed_by = bool(viewer and UserFollow.query.filter_by(
        follower_id=user_id, followee_id=viewer.id
    ).first())

    return _ok({
        'user_id': user_id,
        'following_count': following_count,
        'fans_count': fans_count,
        'mutual_count': int(mutual_count),
        'is_following': is_following,
        'is_followed_by': is_followed_by,
        'is_mutual': is_following and is_followed_by,
        'is_self': bool(viewer and viewer.id == user_id),
    })


# ═══════════════════════════════════════════════════════════
# v7.25 微博化 · P2：私信 / 拉黑 / 合规留痕
# ═══════════════════════════════════════════════════════════

def _are_mutual(a_id, b_id):
    return bool(
        UserFollow.query.filter_by(follower_id=a_id, followee_id=b_id).first()
        and UserFollow.query.filter_by(follower_id=b_id, followee_id=a_id).first()
    )


def _block_row(a_id, b_id):
    return CommunityUserBlock.query.filter(or_(
        and_(CommunityUserBlock.blocker_id == a_id, CommunityUserBlock.blocked_id == b_id),
        and_(CommunityUserBlock.blocker_id == b_id, CommunityUserBlock.blocked_id == a_id),
    )).first()


def _dm_rate_guard(sender_id, receiver_id):
    """非互关的首条后限 1 条/分钟、10 条/天（应用层滑动窗口）。"""
    if _are_mutual(sender_id, receiver_id):
        return None
    now = utcnow()
    last_minute = CommunityDmMessage.query.filter(
        CommunityDmMessage.sender_id == sender_id,
        CommunityDmMessage.receiver_id == receiver_id,
        CommunityDmMessage.created_at >= now - timedelta(minutes=1),
    ).count()
    if last_minute >= 1:
        return '对方尚未关注你，1 分钟内只能发送 1 条私信'
    last_day = CommunityDmMessage.query.filter(
        CommunityDmMessage.sender_id == sender_id,
        CommunityDmMessage.receiver_id == receiver_id,
        CommunityDmMessage.created_at >= now - timedelta(days=1),
    ).count()
    if last_day >= 10:
        return '对方尚未关注你，今日私信已达上限（10 条）'
    return None


def _get_or_create_conversation(a_id, b_id):
    lo, hi = (a_id, b_id) if a_id < b_id else (b_id, a_id)
    conv = CommunityDmConversation.query.filter_by(user_a_id=lo, user_b_id=hi).first()
    if not conv:
        conv = CommunityDmConversation(user_a_id=lo, user_b_id=hi)
        db.session.add(conv)
        db.session.flush()
    return conv


def _create_dm_message(conv, sender, receiver, content, content_type='text'):
    """落一条私信并维护会话最后消息/未读；返回 (消息, 接收方此前是否已有未读)。"""
    was_unread = conv.unread_of(receiver.id) > 0
    now = utcnow()
    msg = CommunityDmMessage(
        conversation_id=conv.id,
        sender_id=sender.id,
        receiver_id=receiver.id,
        content=(content or '')[:2000],
        content_type=content_type,
        created_at=now,
    )
    db.session.add(msg)
    db.session.flush()

    conv.last_message_id = msg.id
    conv.last_message_at = now
    if conv.user_a_id == receiver.id:
        conv.a_unread = (conv.a_unread or 0) + 1
    else:
        conv.b_unread = (conv.b_unread or 0) + 1
    conv.restore_for(receiver.id)
    conv.restore_for(sender.id)
    return msg, was_unread


def _dm_conv_serialize(conv, viewer_id, last_map=None, mutual_ids=None,
                       blocked_by_me=None, blocked_me=None):
    peer = conv.peer_of(viewer_id)
    last = (last_map or {}).get(conv.last_message_id)
    if last is None and last_map is None and conv.last_message_id:
        last = db.session.get(CommunityDmMessage, conv.last_message_id)
    preview = ''
    if last:
        if last.recalled:
            preview = '［消息已撤回］'
        elif last.content_type == 'image':
            preview = '［图片］'
        else:
            preview = (last.content or '')[:40]
    if peer is None:
        is_mutual = False
        is_blocked_by_me = is_blocked_me = False
    else:
        is_mutual = (peer.id in mutual_ids) if mutual_ids is not None else _are_mutual(viewer_id, peer.id)
        is_blocked_by_me = (peer.id in blocked_by_me) if blocked_by_me is not None else bool(
            CommunityUserBlock.query.filter_by(blocker_id=viewer_id, blocked_id=peer.id).first())
        is_blocked_me = (peer.id in blocked_me) if blocked_me is not None else bool(
            CommunityUserBlock.query.filter_by(blocker_id=peer.id, blocked_id=viewer_id).first())
    return {
        'id': conv.id,
        'peer': {'id': peer.id, 'username': peer.username, 'role': peer.role} if peer else None,
        'last_preview': preview,
        'last_message_at': conv.last_message_at.isoformat() if conv.last_message_at else None,
        'unread': conv.unread_of(viewer_id),
        'is_mutual': is_mutual,
        'is_blocked_by_me': is_blocked_by_me,
        'is_blocked_me': is_blocked_me,
        'is_blocked': is_blocked_by_me or is_blocked_me,
        'created_at': conv.created_at.isoformat() if conv.created_at else None,
    }


def _dm_prefetch(uid):
    """一次算好互关/双向拉黑集合，避免会话列表 N+1。"""
    followed = {row[0] for row in db.session.query(UserFollow.followee_id).filter(
        UserFollow.follower_id == uid).all()}
    fans = {row[0] for row in db.session.query(UserFollow.follower_id).filter(
        UserFollow.followee_id == uid).all()}
    my_blocks = {row[0] for row in db.session.query(CommunityUserBlock.blocked_id).filter(
        CommunityUserBlock.blocker_id == uid).all()}
    blocked_me = {row[0] for row in db.session.query(CommunityUserBlock.blocker_id).filter(
        CommunityUserBlock.blocked_id == uid).all()}
    return followed & fans, my_blocks, blocked_me


@api_community_bp.route('/community/dm/conversations', methods=['GET'])
@limiter.limit('120/minute')
def list_dm_conversations():
    user, err = require_login()
    if err:
        return err

    convs = CommunityDmConversation.query.filter(
        or_(
            and_(CommunityDmConversation.user_a_id == user.id,
                 CommunityDmConversation.a_deleted_at.is_(None)),
            and_(CommunityDmConversation.user_b_id == user.id,
                 CommunityDmConversation.b_deleted_at.is_(None)),
        )
    ).order_by(desc(func.coalesce(
        CommunityDmConversation.last_message_at, CommunityDmConversation.created_at
    ))).all()

    last_ids = [c.last_message_id for c in convs if c.last_message_id]
    last_map = {}
    if last_ids:
        last_map = {m.id: m for m in CommunityDmMessage.query.filter(
            CommunityDmMessage.id.in_(last_ids)).all()}
    mutual_ids, my_blocks, blocked_me = _dm_prefetch(user.id)

    unread_total = sum(c.unread_of(user.id) for c in convs)
    return _ok({
        'items': [_dm_conv_serialize(c, user.id, last_map, mutual_ids, my_blocks, blocked_me)
                  for c in convs],
        'unread_total': unread_total,
    })


@api_community_bp.route('/community/dm/unread-count', methods=['GET'])
@limiter.limit('120/minute')
def dm_unread_count():
    user, err = require_login()
    if err:
        return err

    rows = db.session.query(
        CommunityDmConversation.a_unread, CommunityDmConversation.b_unread,
        CommunityDmConversation.user_a_id, CommunityDmConversation.user_b_id,
        CommunityDmConversation.a_deleted_at, CommunityDmConversation.b_deleted_at,
    ).filter(or_(
        CommunityDmConversation.user_a_id == user.id,
        CommunityDmConversation.user_b_id == user.id,
    )).all()
    unread = 0
    for a_unread, b_unread, a_id, _b_id, a_del, b_del in rows:
        if a_id == user.id:
            if a_del is None:
                unread += a_unread or 0
        elif b_del is None:
            unread += b_unread or 0
    return _ok({'unread': unread})


@api_community_bp.route('/community/dm/conversations', methods=['POST'])
@limiter.limit('10/minute')
def create_dm_conversation():
    user, err = require_login()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    peer_id = data.get('peer_id')
    try:
        peer_id = int(peer_id)
    except (TypeError, ValueError):
        return _err('缺少有效的 peer_id')
    if peer_id == user.id:
        return _err('不能给自己发私信', 400)

    peer = db.session.get(User, peer_id)
    if not peer or peer.role == 'bot':
        return _err('收信人不存在', 404)
    if _block_row(user.id, peer.id):
        return _err('你们之间存在拉黑关系，无法发起私信', 403)

    content = (data.get('content') or '').strip()
    if content and len(content) > 2000:
        return _err('私信内容 ≤ 2000 字')

    if content:
        guard = _dm_rate_guard(user.id, peer.id)
        if guard:
            return _err(guard, 429)

    conv = _get_or_create_conversation(user.id, peer.id)
    conv.restore_for(user.id)
    payload = None
    if content:
        msg, was_unread = _create_dm_message(conv, user, peer, content)
        payload = msg.to_dict()
        if not was_unread:
            create_notification(
                peer.id, '收到一条私信', content[:60],
                type='info', related_type='dm', related_id=conv.id, commit=False,
            )
    db.session.commit()
    return _ok({
        'conversation': _dm_conv_serialize(conv, user.id),
        'message': payload,
    }), 201


@api_community_bp.route('/community/dm/conversations/<int:conv_id>/messages', methods=['GET'])
@limiter.limit('120/minute')
def list_dm_messages(conv_id):
    user, err = require_login()
    if err:
        return err

    conv = db.session.get(CommunityDmConversation, conv_id)
    if not conv or user.id not in (conv.user_a_id, conv.user_b_id):
        return _err('会话不存在', 404)

    before_id = request.args.get('before_id', type=int)
    limit = min(50, max(1, request.args.get('limit', 30, type=int)))
    query = CommunityDmMessage.query.filter_by(conversation_id=conv_id)
    if before_id:
        query = query.filter(CommunityDmMessage.id < before_id)
    rows = query.order_by(desc(CommunityDmMessage.id)).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    rows.reverse()
    return _ok({
        'items': [m.to_dict() for m in rows],
        'next_cursor': rows[0].id if (has_more and rows) else None,
        'has_more': has_more,
        'peer': {
            'id': conv.peer_of(user.id).id,
            'username': conv.peer_of(user.id).username,
            'role': conv.peer_of(user.id).role,
        } if conv.peer_of(user.id) else None,
    })


@api_community_bp.route('/community/dm/conversations/<int:conv_id>/messages', methods=['POST'])
@limiter.limit('10/minute')
def send_dm_message(conv_id):
    user, err = require_login()
    if err:
        return err

    conv = db.session.get(CommunityDmConversation, conv_id)
    if not conv or user.id not in (conv.user_a_id, conv.user_b_id):
        return _err('会话不存在', 404)

    peer = conv.peer_of(user.id)
    if not peer:
        return _err('会话不存在', 404)
    if _block_row(user.id, peer.id):
        return _err('你们之间存在拉黑关系，无法发送私信', 403)

    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content or len(content) > 2000:
        return _err('私信内容必填且 ≤ 2000 字')

    guard = _dm_rate_guard(user.id, peer.id)
    if guard:
        return _err(guard, 429)

    msg, was_unread = _create_dm_message(conv, user, peer, content)
    if not was_unread:
        create_notification(
            peer.id, '收到一条私信', content[:60],
            type='info', related_type='dm', related_id=conv.id, commit=False,
        )
    db.session.commit()
    return _ok(msg.to_dict()), 201


@api_community_bp.route('/community/dm/conversations/<int:conv_id>/read', methods=['PUT'])
@limiter.limit('120/minute')
def mark_dm_read(conv_id):
    user, err = require_login()
    if err:
        return err

    conv = db.session.get(CommunityDmConversation, conv_id)
    if not conv or user.id not in (conv.user_a_id, conv.user_b_id):
        return _err('会话不存在', 404)

    now = utcnow()
    CommunityDmMessage.query.filter(
        CommunityDmMessage.conversation_id == conv_id,
        CommunityDmMessage.receiver_id == user.id,
        CommunityDmMessage.is_read == False,  # noqa: E712
    ).update({'is_read': True, 'read_at': now}, synchronize_session=False)
    if conv.user_a_id == user.id:
        conv.a_unread = 0
    else:
        conv.b_unread = 0
    db.session.commit()
    return _ok({'unread': 0})


@api_community_bp.route('/community/dm/conversations/<int:conv_id>', methods=['DELETE'])
@limiter.limit('60/minute')
def hide_dm_conversation(conv_id):
    user, err = require_login()
    if err:
        return err

    conv = db.session.get(CommunityDmConversation, conv_id)
    if not conv or user.id not in (conv.user_a_id, conv.user_b_id):
        return _err('会话不存在', 404)

    conv.hide_for(user.id)
    db.session.commit()
    return _ok({'hidden': True})


@api_community_bp.route('/community/users/<int:user_id>/block', methods=['POST', 'DELETE'])
@limiter.limit('60/minute')
def block_user(user_id):
    user, err = require_login()
    if err:
        return err
    if user_id == user.id:
        return _err('不能拉黑自己', 400)

    target = db.session.get(User, user_id)
    if not target:
        return _err('用户不存在', 404)

    existing = CommunityUserBlock.query.filter_by(
        blocker_id=user.id, blocked_id=user_id).first()
    if request.method == 'POST':
        if not existing:
            data = request.get_json(silent=True) or {}
            reason = (data.get('reason') or '').strip()[:200] or None
            db.session.add(CommunityUserBlock(
                blocker_id=user.id, blocked_id=user_id, reason=reason))
            db.session.commit()
        return _ok({'blocked': True, 'user_id': user_id})
    if existing:
        db.session.delete(existing)
        db.session.commit()
    return _ok({'blocked': False, 'user_id': user_id})


@api_community_bp.route('/community/dm/blocks', methods=['GET'])
@limiter.limit('120/minute')
def list_blocks():
    user, err = require_login()
    if err:
        return err

    rows = CommunityUserBlock.query.filter_by(blocker_id=user.id).order_by(
        desc(CommunityUserBlock.created_at)).all()
    return _ok([r.to_dict() for r in rows])


@api_community_bp.route('/community/dm/conversations/<int:conv_id>/context', methods=['GET'])
@limiter.limit('30/minute')
def dm_context_for_teacher(conv_id):
    """教师/管理员凭举报查看会话最近 50 条，并写入 access log。"""
    user, err = _require_teacher_or_admin()
    if err:
        return err

    conv = db.session.get(CommunityDmConversation, conv_id)
    if not conv:
        return _err('会话不存在', 404)

    report_id = request.args.get('report_id', type=int)
    if not report_id:
        return _err('必须携带 report_id')
    rep = db.session.get(CommunityReport, report_id)
    target = _load_report_target('dm_message', rep.target_id) if rep and rep.target_type == 'dm_message' else None
    if not rep or not target or target.conversation_id != conv_id:
        return _err('举报记录与该会话不匹配', 403)

    messages = CommunityDmMessage.query.filter_by(conversation_id=conv_id).order_by(
        desc(CommunityDmMessage.id)).limit(50).all()
    messages.reverse()

    log = CommunityDmAccessLog(
        admin_id=user.id, conversation_id=conv_id, report_id=rep.id)
    db.session.add(log)
    db.session.commit()

    return _ok({
        'conversation_id': conv_id,
        'access_log_id': log.id,
        'participants': [
            {'id': conv.user_a.id, 'username': conv.user_a.username, 'role': conv.user_a.role},
            {'id': conv.user_b.id, 'username': conv.user_b.username, 'role': conv.user_b.role},
        ],
        'report': rep.to_dict(),
        'messages': [m.to_dict() for m in messages],
    })
