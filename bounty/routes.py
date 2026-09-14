# -*- coding: utf-8 -*-
"""征集悬赏模块 API（独立模块，Blueprint: bounty_bp，前缀 /api）

师生均可发布悬赏、投稿；发布者审核自己悬赏下的投稿；
投稿被采纳后：题目投稿入题库 / 答案投稿回填解析，并给投稿人发放竞技积分。
"""
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

from database import db
from database.models import Question, Major
from utils.timeutil import utcnow, parse_dt
from utils.security import verify_token
from bounty.models import (
    Bounty, BountySubmission,
    BountyTypeEnum, BountyStatusEnum, SubmissionStatusEnum,
)
from bounty.rewards import award_bounty

bounty_bp = Blueprint('bounty', __name__)


# ═══════════════ 查询 ═══════════════

@bounty_bp.route('/bounties', methods=['GET'])
def bounty_list():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    q = Bounty.query
    btype = request.args.get('type')
    if btype in (BountyTypeEnum.QUESTION, BountyTypeEnum.ANSWER):
        q = q.filter(Bounty.bounty_type == btype)
    status = request.args.get('status')
    if status in (BountyStatusEnum.OPEN, BountyStatusEnum.CLOSED):
        q = q.filter(Bounty.status == status)
    items = q.order_by(Bounty.created_at.desc()).all()
    return jsonify([b.to_dict(current_user_id=user.id) for b in items])


@bounty_bp.route('/bounties/mine', methods=['GET'])
def bounty_mine():
    """我发布的悬赏"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    items = (Bounty.query.filter_by(publisher_id=user.id)
             .order_by(Bounty.created_at.desc()).all())
    return jsonify([b.to_dict(current_user_id=user.id) for b in items])


@bounty_bp.route('/bounties/my-submissions', methods=['GET'])
def bounty_my_submissions():
    """我的投稿"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    subs = (BountySubmission.query.filter_by(submitter_id=user.id)
            .order_by(BountySubmission.created_at.desc()).all())
    result = []
    for s in subs:
        d = s.to_dict()
        d['bounty_title'] = s.bounty.title if s.bounty else ''
        d['bounty_type'] = s.bounty.bounty_type if s.bounty else ''
        d['reward_points'] = s.bounty.reward_points if s.bounty else 0
        d['publisher_name'] = s.bounty.publisher.username if s.bounty and s.bounty.publisher else ''
        result.append(d)
    return jsonify(result)


@bounty_bp.route('/bounties/<int:bounty_id>', methods=['GET'])
def bounty_detail(bounty_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
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
    """投稿列表：发布者看全部，其他人只看已采纳"""
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    subs = sorted(bounty.submissions, key=lambda s: s.created_at, reverse=True)
    if bounty.publisher_id != user.id:
        subs = [s for s in subs if s.status == SubmissionStatusEnum.ACCEPTED]
    return jsonify([s.to_dict() for s in subs])


# ═══════════════ 发布悬赏 ═══════════════

@bounty_bp.route('/bounties', methods=['POST'])
def bounty_create():
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    data = request.get_json(silent=True) or {}

    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'message': '悬赏标题不能为空'}), 400
    btype = data.get('bounty_type') or BountyTypeEnum.QUESTION
    if btype not in (BountyTypeEnum.QUESTION, BountyTypeEnum.ANSWER):
        return jsonify({'message': '悬赏类型不正确'}), 400

    try:
        reward = int(data.get('reward_points') or 10)
    except (TypeError, ValueError):
        return jsonify({'message': '赏金必须为整数'}), 400
    if reward <= 0:
        return jsonify({'message': '赏金必须大于 0'}), 400

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
    )
    db.session.add(bounty)
    db.session.commit()
    return jsonify(bounty.to_dict(current_user_id=user.id)), 201


# ═══════════════ 投稿 ═══════════════

@bounty_bp.route('/bounties/<int:bounty_id>/submissions', methods=['POST'])
def bounty_submit(bounty_id):
    user = verify_token()
    if not user:
        return jsonify({'message': '未登录'}), 401
    bounty = db.session.get(Bounty, bounty_id)
    if not bounty:
        return jsonify({'message': '悬赏不存在'}), 404
    if bounty.effective_status() != BountyStatusEnum.OPEN:
        return jsonify({'message': '悬赏已关闭或已过期，无法投稿'}), 400
    if bounty.publisher_id == user.id:
        return jsonify({'message': '不能给自己发布的悬赏投稿'}), 400

    data = request.get_json(silent=True) or {}
    sub = BountySubmission(bounty_id=bounty.id, submitter_id=user.id)

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
        return jsonify({'message': '你已对该悬赏投过稿，不能重复投稿'}), 400
    return jsonify(sub.to_dict()), 201


# ═══════════════ 审核：采纳 / 拒绝 ═══════════════

@bounty_bp.route('/submissions/<int:sid>/accept', methods=['POST'])
def submission_accept(sid):
    user = verify_token()
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

    # CAS 抢锁：open → closed，防止并发重复采纳
    now = utcnow()
    rowcount = db.session.execute(
        db.text('UPDATE bounty SET status = :closed, closed_at = :now, '
                'accepted_submission_id = :sid '
                'WHERE id = :bid AND status = :open'),
        {'closed': BountyStatusEnum.CLOSED, 'now': now.replace(tzinfo=None),
         'sid': sid, 'bid': bounty.id, 'open': BountyStatusEnum.OPEN}
    ).rowcount
    if rowcount != 1:
        db.session.rollback()
        return jsonify({'message': '悬赏已被处理，无法重复采纳'}), 400

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

    # 答案投稿且关联题库已有题：回填解析（原题无解析时）
    if (bounty.bounty_type == BountyTypeEnum.ANSWER
            and bounty.target_question_id and sub.content):
        tq = db.session.get(Question, bounty.target_question_id)
        if tq and not (tq.analysis or '').strip():
            tq.analysis = sub.content

    # 状态流转：采纳该投稿，其余 pending 投稿标记拒绝
    sub.status = SubmissionStatusEnum.ACCEPTED
    sub.reviewed_at = now
    sub.reviewer_id = user.id
    for other in bounty.submissions:
        if other.id != sub.id and other.status == SubmissionStatusEnum.PENDING:
            other.status = SubmissionStatusEnum.REJECTED
            other.reviewed_at = now
            other.reviewer_id = user.id
            other.review_comment = '悬赏已采纳其他投稿'

    db.session.commit()

    # 积分/勋章结算（独立事务 + Socket 推送）
    try:
        award_bounty(sub.submitter_id, bounty.reward_points, related_id=sub.id)
    except Exception as e:
        # 业务已提交，积分失败不回滚采纳结果，仅记录
        import logging
        logging.getLogger(__name__).error(f'悬赏积分发放失败 sub={sid}: {e}', exc_info=True)

    return jsonify({
        'message': '采纳成功',
        'submission': sub.to_dict(),
        'accepted_question_id': accepted_question_id,
        'reward_points': bounty.reward_points,
    })


@bounty_bp.route('/submissions/<int:sid>/reject', methods=['POST'])
def submission_reject(sid):
    user = verify_token()
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
    return jsonify({'message': '已拒绝', 'submission': sub.to_dict()})
