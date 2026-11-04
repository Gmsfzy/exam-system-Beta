# -*- coding: utf-8 -*-
"""v6.1 跨模块 → 社区 桥接工具。

把悬赏/作业等模块的优质内容一键同步为社区帖，避免各模块各自实现发帖逻辑。
设计原则：
  - 作者 = 触发同步的 actor（教师/悬赏发布者），**不暴露原作答/投稿人身份**；
  - 可选匿名（is_anonymous=True 时用 actor 的 anon_index 递增）；
  - 不引入新表，幂等性由调用方按业务语义控制（悬赏采纳天然一次性；
    作业展示墙由前端按钮一次性触发）。
"""
from sqlalchemy import func

from database import db
from database.models import CommunityPost


def _normalize_tags(raw):
    if raw in (None, ''):
        return None
    if isinstance(raw, str):
        items = raw.replace('，', ',').split(',')
    elif isinstance(raw, (list, tuple)):
        items = raw
    else:
        return None
    cleaned = []
    for item in items:
        t = str(item or '').strip().lstrip('#')
        if not t or len(t) > 20:
            continue
        if t not in cleaned:
            cleaned.append(t)
    return ','.join(cleaned[:5]) or None


def sync_to_community(
    *,
    actor_id,
    category,
    title,
    content,
    linked_type=None,
    linked_id=None,
    tags=None,
    course_id=None,
    anonymous=True,
):
    """把外部模块内容同步为一篇社区帖，返回新建的 CommunityPost。

    参数:
        actor_id: 发帖人（教师/悬赏发布者），**不是原作答人/投稿人**。
        category: 社区分类（experience / resource / discussion ...）。
        title: 帖子标题（≤100，超长截断）。
        content: 帖子正文。
        linked_type/linked_id: 关联题目/作业/考试（可选）。
        tags: 标签（数组或逗号串，最多 5 个）。
        course_id: 课程圈子 ID（可选）。
        anonymous: 是否匿名发帖（默认 True，保护原作者）。
    """
    if not actor_id:
        raise ValueError('actor_id required')
    title = (title or '').strip()[:100]
    if not title:
        raise ValueError('title required')
    content = (content or '').strip()
    if not content:
        raise ValueError('content required')

    anon_index = None
    if anonymous:
        max_idx = db.session.query(func.max(CommunityPost.anon_index)).filter(
            CommunityPost.author_id == actor_id,
            CommunityPost.is_anonymous == True,  # noqa: E712
        ).scalar()
        anon_index = (max_idx or 0) + 1

    post = CommunityPost(
        title=title,
        content=content,
        category=category,
        author_id=actor_id,
        linked_type=linked_type,
        linked_id=linked_id,
        is_anonymous=bool(anonymous),
        anon_index=anon_index,
        tags=_normalize_tags(tags),
        course_id=course_id,
    )
    db.session.add(post)
    db.session.flush()
    return post
