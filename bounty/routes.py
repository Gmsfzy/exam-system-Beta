# -*- coding: utf-8 -*-
"""征集悬赏模块 API（独立模块，Blueprint: bounty_bp，前缀 /api）

师生均可发布悬赏、投稿；发布者审核自己悬赏下的投稿；投稿被采纳后：
题目投稿入题库 / 答案投稿回填解析，并给投稿人发放竞技积分。

P0 治理闭环：编辑/关闭/删除悬赏、撤回/改投投稿、通知接入。
P1 发现激励：搜索/分页/排序/专业标签过滤、贡献榜。
P2 评审增强：多档采纳、讨论区评论、投稿投票、择优回填。
P3 经济治理：赏金钱包托管/充值账单、定向悬赏、举报、相似题查重提示。

v4.6 投稿附件：统一文件白名单（文档/表格/压缩包/图片/视频/代码）上传/下载/删除。
"""
import logging
import os

from flask import Blueprint, request, jsonify, send_from_directory
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from database import db
from database.models import Question, Major, User, RoleEnum
from utils.timeutil import utcnow, parse_dt
from utils.security import verify_token
from utils.uploads import save_upload, UPLOAD_DIR
from bounty.models import (
    Bounty, BountySubmission, BountyComment, BountyVote, BountyReport,
    BountyTypeEnum, BountyStatusEnum, SubmissionStatusEnum,
)
from bounty.rewards import award_bounty, award_publisher_badge, thank_you
from bounty import engine, wallet
from utils.permissions import require_teacher

bounty_bp = Blueprint('bounty', __name__)

logger = logging.getLogger(__name__)


def _get_user():
    return verify_token()


def _parse_int(name, data, default=None):
    """从 data 取整型字段；返回 (value, error_response)。"""
    raw = data.get(name, default)
    if raw is None or raw == '':
        return default, None
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, (jsonify({'message': f'{name} 必须为整数'}), 400)


# ═══════════════ 查询（P1：搜索 / 分页 / 排序 / 定向过滤）═══════════════

@bounty_bp.route('/bounties', methods=['GET'])
def bounty_list():
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    q = Bounty.query.options(
        # 广场序列化为每行遍历 submissions/comments/publisher/major，预加载消除 N+1（v4.6.1）；
        # targeted 可见性仍需内存过滤，数据量增长后可再将可见性条件下推 SQL
        selectinload(Bounty.submissions).joinedload(BountySubmission.submitter),
        selectinload(Bounty.comments),
        joinedload(Bounty.publisher),
        joinedload(Bounty.major),
    )
    btype = request.args.get('type')
    if btype in (BountyTypeEnum.QUESTION, BountyTypeEnum.ANSWER):
        q = q.filter(Bounty.bounty_type == btype)
    status = request.args.get('status')
    if status in (BountyStatusEnum.OPEN, BountyStatusEnum.CLOSED,
                  BountyStatusEnum.EXPIRED, BountyStatusEnum.CANCELLED,
                  BountyStatusEnum.REVIEWING, BountyStatusEnum.REJECTED):
        q = q.filter(Bounty.status == status)
    else:
        # v4.5 审核门禁：广场默认不展示待审核/被驳回悬赏
        q = q.filter(Bounty.status.notin_([BountyStatusEnum.REVIEWING,
                                           BountyStatusEnum.REJECTED]))
    major_id = request.args.get('major_id', type=int)
    if major_id:
        q = q.filter(Bounty.major_id == major_id)
    tag = (request.args.get('tag') or '').strip()
    if tag:
        q = q.filter(Bounty.tags.like(f'%{tag}%'))
    keyword = (request.args.get('q') or request.args.get('keyword') or '').strip()
    if keyword:
        like = f'%{keyword}%'
        q = q.filter(db.or_(Bounty.title.like(like), Bounty.description.like(like),
                            Bounty.tags.like(like)))

    items = [b for b in q.all() if b.visible_to(user)]

    sort = request.args.get('sort') or 'created'
    if sort == 'reward':
        items.sort(key=lambda b: b.reward_points or 0, reverse=True)
    elif sort == 'deadline':
        items.sort(key=lambda b: (b.deadline is None, b.deadline or utcnow()))
    elif sort == 'hot':
        items.sort(key=lambda b: len(b.submissions), reverse=True)
    else:  # created (default)
        items.sort(key=lambda b: b.created_at, reverse=True)

    total = len(items)
    page = max(1, request.args.get('page', type=int) or 1)
    page_size = request.args.get('page_size', type=int) or 12
    page_size = max(1, min(page_size, 100))
    start = (page - 1) * page_size
    window = items[start:start + page_size]
    return jsonify({
        'items': [b.to_dict(current_user_id=user.id) for b in window],
        'total': total, 'page': page, 'page_size': page_size,
        'pages': (total + page_size - 1) // page_size,
    })


@bounty_bp.route('/bounties/mine', methods=['GET'])
def bounty_mine():
    """我发布的悬赏"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    q = Bounty.query.filter_by(publisher_id=user.id)
    status = request.args.get('status')
    if status in (BountyStatusEnum.OPEN, BountyStatusEnum.CLOSED,
                  BountyStatusEnum.EXPIRED, BountyStatusEnum.CANCELLED,
                  BountyStatusEnum.REVIEWING, BountyStatusEnum.REJECTED):
        q = q.filter(Bounty.status == status)
    items = q.order_by(Bounty.created_at.desc()).all()
    return jsonify([b.to_dict(current_user_id=user.id) for b in items])


@bounty_bp.route('/bounties/my-submissions', methods=['GET'])
def bounty_my_submissions():
    """我的投稿"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    subs = (BountySubmission.query.filter_by(submitter_id=user.id)
            .order_by(BountySubmission.created_at.desc()).all())
    result = []
    for s in subs:
        d = s.to_dict(viewer_id=user.id, is_publisher=False)
        d['bounty_title'] = s.bounty.title if s.bounty else ''
        d['bounty_type'] = s.bounty.bounty_type if s.bounty else ''
        d['reward_points'] = s.bounty.reward_points if s.bounty else 0
        d['bounty_status'] = s.bounty.effective_status() if s.bounty else ''
        d['publisher_name'] = s.bounty.publisher.username if s.bounty and s.bounty.publisher else ''
        result.append(d)
    return jsonify(result)


@bounty_bp.route('/bounties/<int:bounty_id>', methods=['GET'])
def bounty_detail(bounty_id):
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    # v4.5 审核门禁：未公开悬赏仅发布者/教师可见
    if bounty.status in (BountyStatusEnum.REVIEWING, BountyStatusEnum.REJECTED) \
            and bounty.publisher_id != user.id and not user.is_teacher():
        return jsonify({'message': '悬赏不存在'}), 404
    if not bounty.visible_to(user):
        return jsonify({'message': '该悬赏为定向发布，你不在可见范围内'}), 403
    data = bounty.to_dict(current_user_id=user.id)
    # 答案悬赏关联题库已有题时，带出题目内容供展示
    if bounty.target_question_id and bounty.target_question:
        tq = bounty.target_question
        tq_data = {
            'id': tq.id, 'content': tq.content, 'options': tq.options,
            'type': tq.type, 'difficulty': tq.difficulty,
        }
        # 题库题正确答案/解析仅教师可见（与题库接口脱敏策略一致），
        # 学生在悬赏场景只需题干即可投稿，不应借此获取题库答案
        if user.is_teacher():
            tq_data['answer'] = tq.answer
            tq_data['analysis'] = tq.analysis
        data['target_question'] = tq_data
    return jsonify(data)


@bounty_bp.route('/bounties/<int:bounty_id>/submissions', methods=['GET'])
def bounty_submissions(bounty_id):
    """投稿列表：发布者看全部（含答案脱敏），其他人只看已采纳 + 匿名/投票脱敏"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    is_pub = bounty.publisher_id == user.id
    subs = list(bounty.submissions)
    if not is_pub:
        subs = [s for s in subs if s.status == SubmissionStatusEnum.ACCEPTED]
    # 发布者视图按社区投票排序，便于择优
    subs.sort(key=lambda s: (len(s.votes) if s.votes else 0, s.created_at),
              reverse=not is_pub)
    if is_pub:
        subs.sort(key=lambda s: (len(s.votes) if s.votes else 0), reverse=True)
    return jsonify([s.to_dict(viewer_id=user.id, is_publisher=is_pub) for s in subs])


# ═══════════════ 发布 / 编辑 / 关闭 / 删除（P0 治理 + P3 托管/定向）═══════════════

@bounty_bp.route('/bounties', methods=['POST'])
def bounty_create():
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}

    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '悬赏标题不能为空'}), 400
    btype = data.get('bounty_type') or BountyTypeEnum.QUESTION
    if btype not in (BountyTypeEnum.QUESTION, BountyTypeEnum.ANSWER):
        return jsonify({'message': '悬赏类型不正确'}), 400

    reward, err = _parse_int('reward_points', data, 10)
    if err:
        return err
    if reward <= 0:
        return jsonify({'message': '赏金必须大于 0'}), 400

    max_accepts, err = _parse_int('max_accepts', data, 1)
    if err:
        return err
    max_accepts = max(1, min(max_accepts, 20))

    major_id = data.get('major_id')
    target_question_id = data.get('target_question_id')
    snapshot = data.get('target_question_snapshot')

    if btype == BountyTypeEnum.QUESTION:
        if not major_id:
            return jsonify({'message': '题目征集悬赏必须选择所属专业'}), 400
        if not db.session.get(Major, major_id):
            return jsonify({'message': '所选专业不存在'}), 400
    elif btype == BountyTypeEnum.ANSWER:
        if target_question_id:
            if not db.session.get(Question, target_question_id):
                return jsonify({'message': '关联题目不存在'}), 400
        elif snapshot:
            if not (snapshot.get('content') or '').strip():
                return jsonify({'message': '自带题目快照缺少题干'}), 400

    deadline = None
    if data.get('deadline'):
        try:
            deadline = parse_dt(data['deadline'])
        except ValueError:
            return jsonify({'message': '截止时间格式不正确'}), 400

    # 定向悬赏（P3）
    visibility = data.get('visibility') or 'public'
    if visibility not in ('public', 'targeted'):
        visibility = 'public'
    target_json = None
    if visibility == 'targeted':
        tgt = data.get('target') or {}
        target_json = {
            'user_ids': [int(x) for x in (tgt.get('user_ids') or []) if str(x).isdigit()],
            'major_ids': [int(x) for x in (tgt.get('major_ids') or []) if str(x).isdigit()],
        }

    tags = (data.get('tags') or '').strip()[:200] or None

    bounty = Bounty(
        publisher_id=user.id,
        bounty_type=btype,
        title=title[:100],
        description=(data.get('description') or '').strip() or None,
        target_question_id=target_question_id,
        target_question_snapshot=snapshot if btype == BountyTypeEnum.ANSWER else None,
        major_id=major_id if btype == BountyTypeEnum.QUESTION else None,
        q_type=data.get('q_type') or None,
        q_difficulty=data.get('q_difficulty') or None,
        reward_points=reward,
        deadline=deadline,
        max_accepts=max_accepts,
        tags=tags,
        visibility=visibility,
        target_json=target_json,
    )

    # 赏金托管（P3）：启用时冻结发布赏金，余额不足拒绝发布
    if wallet.escrow_enabled():
        escrow_total = reward * (max_accepts if max_accepts > 1 else 1)
        db.session.add(bounty)
        db.session.flush()
        txn = wallet.freeze(user.id, escrow_total, bounty.id)
        if txn is None:
            db.session.rollback()
            return jsonify({'message': f'钱包余额不足，需冻结 {escrow_total} 赏金，请先充值'}), 400
        bounty.frozen_points = escrow_total
    else:
        db.session.add(bounty)

    # v4.5 发布审核门禁：存在其他教师则交叉审核，无其他教师时自动通过
    reviewers = User.query.filter(User.role == RoleEnum.TEACHER,
                                  User.id != user.id).all()
    if reviewers:
        bounty.status = BountyStatusEnum.REVIEWING
    db.session.commit()

    try:
        award_publisher_badge(user.id, related_id=bounty.id)
    except Exception:
        logger.exception('非关键勋章发放失败 publish bounty=%s', bounty.id)
    if bounty.status == BountyStatusEnum.REVIEWING:
        for t in reviewers[:50]:
            engine._notify(t.id, '有悬赏待审核',
                           f'「{bounty.title}」已提交发布，待你审核。',
                           type='info', related_id=bounty.id)
    return jsonify(bounty.to_dict(current_user_id=user.id)), 201


@bounty_bp.route('/bounties/pending', methods=['GET'])
def bounty_pending():
    """v4.5 审核门禁：待审核悬赏列表（教师）"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    items = (Bounty.query.filter_by(status=BountyStatusEnum.REVIEWING)
             .order_by(Bounty.created_at.asc()).all())
    return jsonify([b.to_dict(current_user_id=user.id) for b in items])


@bounty_bp.route('/bounties/<int:bounty_id>/review', methods=['POST'])
def bounty_review(bounty_id):
    """v4.5 审核门禁：教师交叉审核（审核人不可为发布者）；驳回退回托管赏金"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty or bounty.status != BountyStatusEnum.REVIEWING:
        return jsonify({'message': '悬赏不存在或不在待审核状态'}), 404
    if bounty.publisher_id == user.id:
        return jsonify({'message': '不能审核自己发布的悬赏'}), 403
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('approve', 'reject'):
        return jsonify({'message': '参数错误：action 须为 approve/reject'}), 400
    reason = str(data.get('reason') or '').strip()[:200]
    bounty.reviewer_id = user.id
    bounty.reviewed_at = utcnow()
    if action == 'approve':
        bounty.status = BountyStatusEnum.OPEN
        bounty.review_reason = None
        db.session.commit()
        engine._notify(bounty.publisher_id, '悬赏审核通过',
                       f'「{bounty.title}」已通过审核，现已上架悬赏广场。',
                       type='success', related_id=bounty.id)
        return jsonify({'message': '已通过', 'bounty': bounty.to_dict(current_user_id=user.id)})
    bounty.status = BountyStatusEnum.REJECTED
    bounty.review_reason = reason or '内容不符合发布要求'
    had_frozen = (bounty.frozen_points or 0) > 0
    if had_frozen:
        wallet.refund(bounty, commit=False)
    db.session.commit()
    engine._notify(bounty.publisher_id, '悬赏审核驳回',
                   f'「{bounty.title}」驳回原因：{bounty.review_reason}。'
                   + ('托管赏金已退回钱包。' if had_frozen else '')
                   + '可修改后重新发布。',
                   type='warning', related_id=bounty.id)
    return jsonify({'message': '已驳回', 'bounty': bounty.to_dict(current_user_id=user.id)})


@bounty_bp.route('/bounties/<int:bounty_id>/archive', methods=['POST'])
def bounty_archive(bounty_id):
    """v4.5 悬赏归档：把已采纳的题目投稿正式入公共题库（教师操作）"""
    user, err = require_teacher(deny_msg='无权访问', unauth_msg='无权访问', unauth_status=403)
    if err:
        return err
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    archived, majors = 0, set()
    for s in bounty.submissions:
        if s.status == SubmissionStatusEnum.ACCEPTED and s.accepted_question_id:
            q = db.session.get(Question, s.accepted_question_id)
            if q and not q.is_public:
                q.is_public = True
                archived += 1
                if q.major_id:
                    majors.add(q.major_id)
    db.session.commit()
    if archived:
        from utils.redis_cache import invalidate_question_cache
        for mid in majors:
            invalidate_question_cache(major_id=mid)
    return jsonify({'message': f'已归档 {archived} 道采纳题入公共题库', 'archived': archived})


@bounty_bp.route('/bounties/<int:bounty_id>', methods=['PUT'])
def bounty_update(bounty_id):
    """编辑悬赏（P0）：仅发布者、仅征集中、且尚未有采纳时可改标题/说明/截止/赏金/标签/名额。"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    if bounty.publisher_id != user.id:
        return jsonify({'message': '只有发布者可以编辑悬赏'}), 403
    if bounty.effective_status() != BountyStatusEnum.OPEN:
        return jsonify({'message': '悬赏已关闭/过期，无法编辑'}), 400
    if (bounty.accept_count or 0) > 0:
        return jsonify({'message': '已有采纳，无法编辑'}), 400

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        t = (data.get('title') or '').strip()
        if not t:
            return jsonify({'message': '悬赏标题不能为空'}), 400
        bounty.title = t[:100]
    if 'description' in data:
        bounty.description = (data.get('description') or '').strip() or None
    if 'tags' in data:
        bounty.tags = (data.get('tags') or '').strip()[:200] or None
    if 'deadline' in data:
        if data.get('deadline'):
            try:
                bounty.deadline = parse_dt(data['deadline'])
            except ValueError:
                return jsonify({'message': '截止时间格式不正确'}), 400
        else:
            bounty.deadline = None
    if 'max_accepts' in data:
        ma, err = _parse_int('max_accepts', data, bounty.max_accepts)
        if err:
            return err
        bounty.max_accepts = max(1, min(ma, 20))
    if 'reward_points' in data and not wallet.escrow_enabled():
        rp, err = _parse_int('reward_points', data, bounty.reward_points)
        if err:
            return err
        if rp <= 0:
            return jsonify({'message': '赏金必须大于 0'}), 400
        bounty.reward_points = rp
    db.session.commit()
    return jsonify(bounty.to_dict(current_user_id=user.id))


@bounty_bp.route('/bounties/<int:bounty_id>/close', methods=['POST'])
def bounty_close(bounty_id):
    """主动关闭/撤销悬赏（P0）：置 CANCELLED，退回托管赏金，通知未处理投稿人。"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    if bounty.publisher_id != user.id:
        return jsonify({'message': '只有发布者可以关闭悬赏'}), 403
    if bounty.status in (BountyStatusEnum.CLOSED, BountyStatusEnum.CANCELLED):
        return jsonify({'message': '悬赏已关闭'}), 400

    now = utcnow()
    bounty.status = BountyStatusEnum.CANCELLED
    bounty.closed_at = now
    if wallet.escrow_enabled() and (bounty.frozen_points or 0) > 0:
        wallet.refund(bounty, commit=False)
    db.session.commit()
    engine._notify(bounty.publisher_id, '悬赏已关闭',
                   f'「{bounty.title}」已关闭，托管赏金已退回钱包。',
                   type='info', related_id=bounty.id)
    return jsonify({'message': '已关闭', 'bounty': bounty.to_dict(current_user_id=user.id)})


@bounty_bp.route('/bounties/<int:bounty_id>', methods=['DELETE'])
def bounty_delete(bounty_id):
    """删除悬赏（P0）：仅发布者；有采纳记录禁止删除；退回托管后级联删除投稿/评论。"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    if bounty.publisher_id != user.id:
        return jsonify({'message': '只有发布者可以删除悬赏'}), 403
    if (bounty.accept_count or 0) > 0 or bounty.accepted_submission_id:
        return jsonify({'message': '已有采纳记录，禁止删除（可关闭）'}), 400
    if wallet.escrow_enabled() and (bounty.frozen_points or 0) > 0:
        wallet.refund(bounty, commit=False)
    db.session.delete(bounty)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ═══════════════ 投稿（P0 匿名/查重 + P0 撤回/改投）═══════════════

@bounty_bp.route('/bounties/<int:bounty_id>/submissions', methods=['POST'])
def bounty_submit(bounty_id):
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    if not bounty.visible_to(user):
        return jsonify({'message': '该悬赏为定向发布，你不在可见范围内'}), 403
    if bounty.effective_status() != BountyStatusEnum.OPEN:
        return jsonify({'message': '悬赏已关闭或已过期，无法投稿'}), 400
    if bounty.publisher_id == user.id:
        return jsonify({'message': '不能给自己发布的悬赏投稿'}), 400

    data = request.get_json(silent=True) or {}
    sub = BountySubmission(bounty_id=bounty.id, submitter_id=user.id)
    sub.is_anonymous = bool(data.get('is_anonymous'))

    similar = []
    if bounty.bounty_type == BountyTypeEnum.QUESTION:
        q_content = (data.get('q_content') or '').strip()
        q_answer = (data.get('q_answer') or '').strip()
        if not q_content or not q_answer:
            return jsonify({'message': '题目投稿必须填写题干和答案'}), 400
        sub.q_content = q_content
        sub.q_options = data.get('q_options') or None
        sub.q_answer = q_answer
        sub.q_analysis = (data.get('q_analysis') or '').strip() or None
        sub.q_type = data.get('q_type') or bounty.q_type or 'single_choice'
        sub.q_difficulty = data.get('q_difficulty') or bounty.q_difficulty or 'medium'
        sub.q_knowledge = (data.get('q_knowledge') or '').strip() or None
        if not data.get('ignore_dup'):
            similar = engine.find_similar_questions(q_content, bounty.major_id)
    else:
        content = (data.get('content') or '').strip()
        if not content:
            return jsonify({'message': '答案投稿必须填写答案/解析内容'}), 400
        sub.content = content

    db.session.add(sub)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'message': '你已对该悬赏投过稿，不能重复投稿（可用“修改投稿”）'}), 400
    try:
        engine.notify_new_submission(bounty, sub)
    except Exception:
        logger.exception('非关键通知失败 submission=%s', sub.id)
    resp = sub.to_dict(viewer_id=user.id, is_publisher=False)
    if similar:
        resp['similar_questions'] = similar
    return jsonify(resp), 201


# ═══════════════ v4.6 投稿附件（统一白名单 utils/uploads.py）═══════════════

_UPLOAD_DIR = UPLOAD_DIR  # 与竞赛/学习/作业/DS 共用 utils/uploads 公共落盘目录


def _get_own_submission(bounty_id, user):
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return None, None, (jsonify({'message': '悬赏不存在'}), 404)
    sub = BountySubmission.query.filter_by(bounty_id=bounty.id, submitter_id=user.id).first()
    if not sub:
        return bounty, None, (jsonify({'message': '请先投稿再上传附件'}), 400)
    return bounty, sub, None


@bounty_bp.route('/bounties/<int:bounty_id>/submission/attachment', methods=['POST'])
def bounty_submit_attachment(bounty_id):
    """投稿附件上传（multipart file）：统一白名单 50MB；仅投稿人本人，待审状态可传"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty, sub, err = _get_own_submission(bounty_id, user)
    if err:
        return err
    if sub.status != SubmissionStatusEnum.PENDING:
        return jsonify({'message': '该投稿已被处理，无法追加附件'}), 400
    file = request.files.get('file')
    try:
        stored, size = save_upload(file, 'bounty_sub', _UPLOAD_DIR)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    atts = list(sub.attachment_json or [])
    atts.append({'filename': file.filename, 'stored_name': stored, 'size': size,
                 'uploaded_at': utcnow().isoformat()})
    sub.attachment_json = atts
    db.session.commit()
    return jsonify({'message': '附件已上传', 'attachments': len(atts)}), 201


@bounty_bp.route('/bounties/<int:bounty_id>/submission/attachment/<int:idx>', methods=['DELETE'])
def bounty_delete_attachment(bounty_id, idx):
    """删除本人投稿附件（仅待审状态）"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty, sub, err = _get_own_submission(bounty_id, user)
    if err:
        return err
    if sub.status != SubmissionStatusEnum.PENDING:
        return jsonify({'message': '该投稿已被处理，无法删除附件'}), 400
    atts = list(sub.attachment_json or [])
    if idx < 0 or idx >= len(atts):
        return jsonify({'message': '附件不存在'}), 404
    atts.pop(idx)
    sub.attachment_json = atts
    db.session.commit()
    return jsonify({'message': '已删除附件', 'attachments': len(atts)})


@bounty_bp.route('/submissions/<int:sid>/attachments/<int:idx>/download', methods=['GET'])
def bounty_download_attachment(sid, idx):
    """附件下载：投稿人本人 / 悬赏发布者 / 教师可下载（原始文件名仅下载时披露）"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    sub = db.session.get(BountySubmission, sid)
    if not sub:
        return jsonify({'message': '投稿不存在'}), 404
    allowed = (sub.submitter_id == user.id
               or sub.bounty.publisher_id == user.id
               or user.is_teacher())
    if not allowed:
        return jsonify({'message': '无权下载该附件'}), 403
    atts = sub.attachment_json or []
    if idx < 0 or idx >= len(atts):
        return jsonify({'message': '附件不存在'}), 404
    att = atts[idx]
    return send_from_directory(_UPLOAD_DIR, att['stored_name'],
                               as_attachment=True, download_name=att.get('filename'))


@bounty_bp.route('/submissions/<int:sid>', methods=['PUT'])
def submission_update(sid):
    """改投/修改投稿（P0）：仅投稿人、悬赏征集中、投稿仍为待审。"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    sub = db.session.get(BountySubmission, sid)
    if not sub:
        return jsonify({'message': '投稿不存在'}), 404
    if sub.submitter_id != user.id:
        return jsonify({'message': '只能修改自己的投稿'}), 403
    if sub.bounty.publisher_id == user.id:
        return jsonify({'message': '不能给自己发布的悬赏投稿'}), 400
    if sub.bounty.effective_status() != BountyStatusEnum.OPEN:
        return jsonify({'message': '悬赏已关闭，无法修改投稿'}), 400
    if sub.status != SubmissionStatusEnum.PENDING:
        return jsonify({'message': '该投稿已被处理，无法修改'}), 400

    data = request.get_json(silent=True) or {}
    if sub.bounty.bounty_type == BountyTypeEnum.QUESTION:
        if 'q_content' in data:
            c = (data.get('q_content') or '').strip()
            if not c:
                return jsonify({'message': '题干不能为空'}), 400
            sub.q_content = c
        if 'q_answer' in data:
            a = (data.get('q_answer') or '').strip()
            if not a:
                return jsonify({'message': '答案不能为空'}), 400
            sub.q_answer = a
        for f in ('q_options', 'q_type', 'q_difficulty'):
            if f in data:
                setattr(sub, f, data.get(f) or None)
        if 'q_analysis' in data:
            sub.q_analysis = (data.get('q_analysis') or '').strip() or None
        if 'q_knowledge' in data:
            sub.q_knowledge = (data.get('q_knowledge') or '').strip() or None
    else:
        if 'content' in data:
            c = (data.get('content') or '').strip()
            if not c:
                return jsonify({'message': '答案/解析内容不能为空'}), 400
            sub.content = c
    if 'is_anonymous' in data:
        sub.is_anonymous = bool(data.get('is_anonymous'))
    sub.edited_at = utcnow()
    db.session.commit()
    return jsonify(sub.to_dict(viewer_id=user.id, is_publisher=False))


@bounty_bp.route('/submissions/<int:sid>/withdraw', methods=['POST'])
def submission_withdraw(sid):
    """撤回投稿（P0）：仅投稿人、待审状态可撤回为 WITHDRAWN。"""
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    sub = db.session.get(BountySubmission, sid)
    if not sub:
        return jsonify({'message': '投稿不存在'}), 404
    if sub.submitter_id != user.id:
        return jsonify({'message': '只能撤回自己的投稿'}), 403
    if sub.status != SubmissionStatusEnum.PENDING:
        return jsonify({'message': '该投稿已被处理，无法撤回'}), 400
    sub.status = SubmissionStatusEnum.WITHDRAWN
    sub.edited_at = utcnow()
    db.session.commit()
    return jsonify({'message': '已撤回', 'submission': sub.to_dict(viewer_id=user.id)})


# ═══════════════ 审核：采纳（P2 多档 + P3 释放）/ 拒绝（P2 通知+感谢积分）═══════════════

@bounty_bp.route('/submissions/<int:sid>/accept', methods=['POST'])
def submission_accept(sid):
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    sub = db.session.get(BountySubmission, sid)
    if not sub:
        return jsonify({'message': '投稿不存在'}), 404
    bounty = sub.bounty
    if bounty.publisher_id != user.id:
        return jsonify({'message': '只有悬赏发布者可以审核投稿'}), 403
    if sub.status != SubmissionStatusEnum.PENDING:
        return jsonify({'message': '该投稿已被处理'}), 400
    if bounty.effective_status() != BountyStatusEnum.OPEN:
        return jsonify({'message': '悬赏已关闭/过期，无法采纳'}), 400
    if bounty.accepts_remaining() <= 0:
        return jsonify({'message': '采纳名额已用完'}), 400

    data = request.get_json(silent=True) or {}
    share, err = _parse_int('reward_share', data, bounty.reward_points)
    if err:
        return err
    share = max(0, share)
    # 托管超额防护：已托管悬赏的单次分赏不得超过冻结池剩余额度
    # （未托管的老悬赏 frozen_points=0，不走钱包释放，仅结算竞技积分）
    if wallet.escrow_enabled() and share > (bounty.frozen_points or 0):
        return jsonify({'message': f'分赏额 {share} 超出该悬赏托管剩余赏金 {bounty.frozen_points or 0}'}), 400
    review_comment = (data.get('review_comment') or '').strip() or None

    now = utcnow()
    db_now = now.replace(tzinfo=None)
    # 原子占坑（中危防护）：把“名额扣减 + 托管池校验”合并进单条 UPDATE，
    # 在 SQLite 写锁上串行化，防并发多采超发/同一冻结池两笔请求各自超额付款：
    # frozen_points<=0 为未托管老悬赏（仅结算竞技积分）也放行。
    rowcount = db.session.execute(
        db.text('UPDATE bounty SET accept_count = accept_count + 1, updated_at = :at '
                'WHERE id = :bid AND status = :open '
                'AND accept_count < max_accepts '
                'AND (frozen_points >= :share OR frozen_points <= 0)'),
        {'at': db_now, 'bid': bounty.id, 'open': BountyStatusEnum.OPEN, 'share': share}
    ).rowcount
    if rowcount != 1:
        db.session.rollback()
        return jsonify({'message': '悬赏已被并发处理（名额已用完或状态已变更），请刷新重试'}), 400
    # 占坑投稿：条件更新防同一投稿被并发双采纳双发钱（ORM 预检与写库存在窗口）
    sub_rowcount = db.session.execute(
        db.text('UPDATE bounty_submission SET status = :acc '
                'WHERE id = :sid AND status = :pend'),
        {'acc': SubmissionStatusEnum.ACCEPTED, 'sid': sid,
         'pend': SubmissionStatusEnum.PENDING}
    ).rowcount
    if sub_rowcount != 1:
        db.session.rollback()
        return jsonify({'message': '该投稿已被处理'}), 400
    # 内存镜像与已扣减的 DB 行保持一致（后续 accepts_remaining/关闭 CAS 判断用）
    bounty.accept_count = (bounty.accept_count or 0) + 1
    accepted_question_id = None
    # 题目投稿：入库为正式题目（source=bounty 标记来源）
    if bounty.bounty_type == BountyTypeEnum.QUESTION and sub.q_content:
        q = Question(
            content=sub.q_content,
            options=sub.q_options,
            answer=sub.q_answer or '',
            analysis=sub.q_analysis,
            knowledge=sub.q_knowledge,
            major_id=bounty.major_id,
            type=sub.q_type or 'single_choice',
            difficulty=sub.q_difficulty or 'medium',
            source='bounty',
        )
        db.session.add(q)
        db.session.flush()
        accepted_question_id = q.id
        sub.accepted_question_id = q.id

    # 答案投稿且关联题库已有题：回填解析（择优回填——原题无解析时）
    if (bounty.bounty_type == BountyTypeEnum.ANSWER
            and bounty.target_question_id and sub.content):
        tq = db.session.get(Question, bounty.target_question_id)
        force = bool(data.get('overwrite_analysis'))
        if tq and (force or not (tq.analysis or '').strip()):
            tq.analysis = sub.content

    # 采纳该投稿（状态已由上方条件 UPDATE 抢占，这里同步 ORM 对象并补写其余字段）
    sub.status = SubmissionStatusEnum.ACCEPTED
    sub.reward_share = share
    sub.reviewed_at = now
    sub.reviewer_id = user.id
    sub.review_comment = review_comment
    if not bounty.accepted_submission_id:
        bounty.accepted_submission_id = sub.id

    # 多档：仍有名额则保持 open；名额用完 → CAS 关闭并拒绝其余待审
    single_close = False
    if bounty.accepts_remaining() <= 0:
        rowcount = db.session.execute(
            db.text('UPDATE bounty SET status = :closed, closed_at = :now '
                    'WHERE id = :bid AND status = :open'),
            {'closed': BountyStatusEnum.CLOSED, 'now': now.replace(tzinfo=None),
             'bid': bounty.id, 'open': BountyStatusEnum.OPEN}
        ).rowcount
        if rowcount != 1 and (bounty.max_accepts or 1) == 1:
            db.session.rollback()
            return jsonify({'message': '悬赏已被处理，无法重复采纳'}), 400
        single_close = True
        bounty.status = BountyStatusEnum.CLOSED
        bounty.closed_at = now

    rejected_subs = []
    if single_close:
        for other in bounty.submissions:
            if other.id != sub.id and other.status == SubmissionStatusEnum.PENDING:
                other.status = SubmissionStatusEnum.REJECTED
                other.reviewed_at = now
                other.reviewer_id = user.id
                other.review_comment = '悬赏已采纳其他投稿'
                rejected_subs.append(other)

    # 托管释放（P3）：从冻结池核销并转入投稿人钱包；未托管老悬赏（frozen_points=0）跳过
    if wallet.escrow_enabled() and share > 0 and (bounty.frozen_points or 0) > 0:
        try:
            wallet.release_to(bounty, [(sub.submitter_id, share)])
        except ValueError as e:
            db.session.rollback()
            return jsonify({'message': str(e)}), 400
    # 名额用尽关闭时，把少发/未发的剩余冻结赏金退回发布者，避免托管池永久挂账
    if single_close and wallet.escrow_enabled() and (bounty.frozen_points or 0) > 0:
        wallet.refund(bounty, commit=False)

    db.session.commit()

    # 积分/勋章结算（独立事务 + Socket 推送）
    try:
        award_bounty(sub.submitter_id, share, related_id=sub.id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f'悬赏积分发放失败 sub={sid}: {e}', exc_info=True)
    try:
        engine.notify_decision(bounty, sub, accepted=True)
        for rs in rejected_subs:
            engine.notify_decision(bounty, rs, accepted=False)
    except Exception:
        logger.exception('非关键评审通知失败 sub=%s', sid)

    return jsonify({
        'message': '采纳成功',
        'submission': sub.to_dict(viewer_id=user.id, is_publisher=True),
        'accepted_question_id': accepted_question_id,
        'reward_share': share,
        'accept_count': bounty.accept_count,
        'max_accepts': bounty.max_accepts,
    })


@bounty_bp.route('/submissions/<int:sid>/reject', methods=['POST'])
def submission_reject(sid):
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    sub = db.session.get(BountySubmission, sid)
    if not sub:
        return jsonify({'message': '投稿不存在'}), 404
    if sub.bounty.publisher_id != user.id:
        return jsonify({'message': '只有悬赏发布者可以审核投稿'}), 403
    if sub.status != SubmissionStatusEnum.PENDING:
        return jsonify({'message': '该投稿已被处理'}), 400
    data = request.get_json(silent=True) or {}
    sub.status = SubmissionStatusEnum.REJECTED
    sub.review_comment = (data.get('review_comment') or '').strip() or None
    sub.reviewed_at = utcnow()
    sub.reviewer_id = user.id
    db.session.commit()
    try:
        engine.notify_decision(sub.bounty, sub, accepted=False)
    except Exception:
        logger.exception('非关键评审通知失败 sub=%s', sid)
    # 落选感谢积分（可选，鼓励参与）
    thanks, err = _parse_int('thanks_points', data, 0)
    if not err and thanks and thanks > 0:
        try:
            thank_you(sub.submitter_id, thanks, related_id=sub.id)
        except Exception:
            logger.exception('非关键感谢积分发放失败 sub=%s', sid)
    return jsonify({'message': '已拒绝', 'submission': sub.to_dict(viewer_id=user.id, is_publisher=True)})


# ═══════════════ 讨论区（P2）═══════════════

@bounty_bp.route('/bounties/<int:bounty_id>/comments', methods=['GET'])
def comment_list(bounty_id):
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    return jsonify([c.to_dict() for c in bounty.comments])


@bounty_bp.route('/bounties/<int:bounty_id>/comments', methods=['POST'])
def comment_create(bounty_id):
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    if not bounty.visible_to(user):
        return jsonify({'message': '无权访问该悬赏'}), 403
    data = request.get_json(silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'message': '评论内容不能为空'}), 400
    submission_id = data.get('submission_id')
    if submission_id:
        s = db.session.get(BountySubmission, submission_id)
        if not s or s.bounty_id != bounty.id:
            return jsonify({'message': '关联投稿不存在'}), 400
    c = BountyComment(bounty_id=bounty.id, submission_id=submission_id,
                      user_id=user.id, content=content[:2000])
    db.session.add(c)
    db.session.commit()
    return jsonify(c.to_dict()), 201


@bounty_bp.route('/comments/<int:cid>', methods=['DELETE'])
def comment_delete(cid):
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    c = db.session.get(BountyComment, cid)
    if not c:
        return jsonify({'message': '评论不存在'}), 404
    is_pub = c.bounty and c.bounty.publisher_id == user.id
    if c.user_id != user.id and not is_pub:
        return jsonify({'message': '无权删除该评论'}), 403
    db.session.delete(c)
    db.session.commit()
    return jsonify({'message': '已删除'})


# ═══════════════ 投稿投票（P2）═══════════════

@bounty_bp.route('/submissions/<int:sid>/vote', methods=['POST'])
def submission_vote(sid):
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    sub = db.session.get(BountySubmission, sid)
    if not sub:
        return jsonify({'message': '投稿不存在'}), 404
    if sub.submitter_id == user.id:
        return jsonify({'message': '不能给自己的投稿投票'}), 400
    existing = BountyVote.query.filter_by(submission_id=sid, user_id=user.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'message': '已取消投票', 'vote_count': len(sub.votes) - 1 if sub.votes else 0})
    db.session.add(BountyVote(submission_id=sid, user_id=user.id, value=1))
    db.session.commit()
    return jsonify({'message': '已投票', 'vote_count': (len(sub.votes) if sub.votes else 0)})


# ═══════════════ 举报（P3）═══════════════

@bounty_bp.route('/bounties/report', methods=['POST'])
def report_create():
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    bounty_id = data.get('bounty_id')
    submission_id = data.get('submission_id')
    if not bounty_id and not submission_id:
        return jsonify({'message': '请指定举报对象'}), 400
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'message': '请填写举报理由'}), 400
    if submission_id and not db.session.get(BountySubmission, submission_id):
        return jsonify({'message': '投稿不存在'}), 404
    if bounty_id and not db.session.get(Bounty, bounty_id):
        return jsonify({'message': '悬赏不存在'}), 404
    rep = BountyReport(bounty_id=bounty_id, submission_id=submission_id,
                       reporter_id=user.id, reason=reason[:300])
    db.session.add(rep)
    db.session.commit()
    return jsonify({'message': '举报已提交，我们会尽快处理', 'report': rep.to_dict()}), 201


# ═══════════════ 贡献榜（P1）═══════════════

@bounty_bp.route('/bounty/leaderboard', methods=['GET'])
def bounty_leaderboard():
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    kind = request.args.get('kind') or 'accept'
    limit = request.args.get('limit', type=int) or 50
    return jsonify({'kind': kind, 'items': engine.leaderboard(kind=kind, limit=limit)})


# ═══════════════ 赏金钱包（P3）═══════════════

@bounty_bp.route('/bounty/wallet', methods=['GET'])
def bounty_wallet_get():
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    from ledger import core as ledger
    txns = ledger.txns_of(user.id, 'bounty', limit=50)
    return jsonify({
        'enabled': wallet.escrow_enabled(),
        'balance': wallet.balance_of(user.id),
        'transactions': [t.to_dict() for t in txns],
    })


@bounty_bp.route('/bounty/wallet/topup', methods=['POST'])
def bounty_wallet_topup():
    user = _get_user()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}
    amount, err = _parse_int('amount', data, 0)
    if err:
        return err
    if amount <= 0:
        return jsonify({'message': '充值金额必须大于 0'}), 400
    try:
        wallet.topup(user.id, amount, memo=data.get('memo'))
    except ValueError as e:
        return jsonify({'message': str(e)}), 400
    return jsonify({'message': '充值成功', 'balance': wallet.balance_of(user.id)})
