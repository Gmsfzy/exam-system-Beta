<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="goBack" content="帖子详情" class="back">
      <template #extra>
        <template v-if="post && canEditPost">
          <el-button size="small" :icon="EditPen" @click="openEdit">编辑</el-button>
        </template>
        <template v-if="post && canDeletePost">
          <el-button
            size="small"
            type="danger"
            plain
            :icon="Delete"
            @click="deletePost"
          >删除</el-button>
        </template>
      </template>
    </el-page-header>

    <template v-if="post">
      <!-- 帖子信息 -->
      <div class="section post-head">
        <div class="head-row">
          <el-tag size="small" :type="catTagType(post.category)" effect="light">
            {{ catName(post.category) }}
          </el-tag>
          <el-tag
            v-if="post.course_name"
            size="small"
            type="primary"
            effect="plain"
            class="circle-tag"
            @click="router.push({ path: '/community', query: { course_id: post.course_id } })"
          >👥 {{ post.course_name }}</el-tag>
          <el-tag v-if="post.bounty_points" size="small" type="danger" effect="dark">
            悬赏 {{ post.bounty_points }} 分{{ post.bounty_rewarded ? '（已发放）' : '' }}
          </el-tag>
          <el-tag v-if="post.is_anonymous" size="small" type="info" effect="plain">🫥 匿名</el-tag>
          <el-tag v-if="post.is_author" size="small" type="warning" effect="plain">我发的</el-tag>
          <el-tag v-if="post.is_resolved" size="small" type="success" effect="dark">
            <el-icon><Check /></el-icon> 已解决
          </el-tag>
          <el-tag v-if="post.hidden" size="small" type="info" effect="plain">已折叠</el-tag>
        </div>
        <h1 class="post-title">{{ post.title }}</h1>

        <div v-if="post.tags && post.tags.length" class="tag-line">
          <el-tag
            v-for="t in post.tags"
            :key="t"
            size="small"
            type="info"
            effect="plain"
            class="post-tag"
            @click="router.push({ path: '/community', query: { tag: t } })"
          >#{{ t }}</el-tag>
        </div>

        <!-- 元信息 -->
        <div class="head-meta">
          <span class="author">
            <router-link
              v-if="!post.is_anonymous"
              :to="`/community/users/${post.author_id}`"
              class="author-link"
            ><strong>{{ displayPostAuthor }}</strong></router-link>
            <strong v-else>{{ displayPostAuthor }}</strong>
            <span
              v-if="showRealUsername(post)"
              class="real-username"
            >（真实：{{ post.display_username }}）</span>
          </span>
          <span class="dot">·</span>
          <span>发布于 {{ fmtTime(post.created_at) }}</span>
          <span v-if="post.updated_at !== post.created_at" class="dot">·</span>
          <span v-if="post.updated_at !== post.created_at">更新于 {{ fmtTime(post.updated_at) }}</span>
          <span v-if="post.is_resolved && post.resolved_at" class="dot">·</span>
          <span v-if="post.is_resolved && post.resolved_at">解决于 {{ fmtTime(post.resolved_at) }}</span>
        </div>

        <!-- 关联跳转 -->
        <div v-if="post.linked_type && post.linked_id" class="linked-box">
          <el-icon><Link /></el-icon>
          <span class="linked-label">关联：</span>
          <router-link :to="linkedRoute(post.linked_type, post.linked_id)" class="linked-link">
            {{ linkedLabel(post.linked_type) }}#{{ post.linked_id }}
          </router-link>
        </div>

        <!-- 悬赏提示 -->
        <el-alert
          v-if="post.bounty_points"
          type="warning"
          :closable="false"
          show-icon
          class="bounty-alert"
          :title="post.bounty_rewarded
            ? `悬赏 ${post.bounty_points} 分已发放给最佳答案作者`
            : `悬赏 ${post.bounty_points} 分：采纳答案后自动转给最佳答主`"
        />

        <!-- 折叠提示 -->
        <el-alert
          v-if="post.hidden"
          type="warning"
          :closable="false"
          show-icon
          class="fold-alert"
          :title="post.can_view_content ? '该帖子因多次举报已被折叠，你是作者或管理员，可查看原文' : '该内容因多次举报已被折叠'"
        />

        <!-- 正文 -->
        <RichContent class="post-body" :content="post.content" />

        <!-- 投票 -->
        <div v-if="post.poll" class="poll-box">
          <div class="poll-head">
            <span class="poll-title">投票</span>
            <span class="poll-total">{{ post.poll.total_votes }} 人参与</span>
          </div>
          <div
            v-for="o in post.poll.options"
            :key="o.id"
            class="poll-option"
            :class="{ voted: post.poll.voted_option_id === o.id }"
            @click="vote(o.id)"
          >
            <div class="poll-bar" :style="{ width: o.percent + '%' }"></div>
            <div class="poll-row">
              <span class="poll-text">
                <el-icon v-if="post.poll.voted_option_id === o.id" class="poll-check"><Check /></el-icon>
                {{ o.text }}
              </span>
              <span class="poll-meta">{{ o.vote_count }} 票 · {{ o.percent }}%</span>
            </div>
          </div>
          <p v-if="!isLoggedIn" class="poll-hint">登录后可参与投票</p>
        </div>

        <!-- 操作区 -->
        <div class="post-actions">
          <el-button
            :class="{ liked }"
            :icon="liked ? Sunny : Star"
            :type="liked ? 'danger' : 'default'"
            plain
            round
            @click="toggleLike"
          >
            {{ liked ? '已点赞' : '点赞' }} <b>{{ likeCount }}</b>
          </el-button>
          <el-button
            :icon="favorited ? StarFilled : Star"
            :type="favorited ? 'warning' : 'default'"
            plain
            round
            @click="toggleFavorite"
          >
            {{ favorited ? '已收藏' : '收藏' }} <b>{{ favoriteCount }}</b>
          </el-button>
          <el-button
            v-if="canResolve"
            :type="post.is_resolved ? 'success' : 'default'"
            plain
            round
            :icon="Check"
            @click="toggleResolve"
          >{{ post.is_resolved ? '取消已解决' : '标记已解决' }}</el-button>
          <el-button
            v-if="isLoggedIn && !post.is_author"
            type="warning"
            plain
            round
            :icon="Warning"
            @click="openReport('post', post.id)"
          >举报</el-button>
          <span class="spacer"></span>
          <el-button
            v-if="canDeletePost && !canEditPost"
            type="danger"
            plain
            :icon="Delete"
            @click="deletePost"
          >删除帖子</el-button>
        </div>
      </div>

      <!-- 评论区 -->
      <div class="section">
        <h3 class="section-title">
          <el-icon><ChatDotRound /></el-icon>
          评论
          <span class="count">({{ post.comment_count || 0 }})</span>
        </h3>

        <!-- 未登录提示 -->
        <div v-if="!isLoggedIn" class="login-tip">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="请先登录才能评论"
            class="login-alert"
          >
            <template #default>
              <el-button link type="primary" @click="goLogin">立即登录</el-button>
            </template>
          </el-alert>
        </div>

        <!-- 评论输入 -->
        <div v-else class="comment-form">
          <div v-if="replyTarget" class="reply-banner">
            <span>
              正在回复 <b>@{{ replyTarget.name }}</b>
            </span>
            <el-button link type="primary" size="small" @click="cancelReply">取消回复</el-button>
          </div>
          <el-input
            ref="commentInputRef"
            v-model="newComment.content"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 8 }"
            maxlength="2000"
            show-word-limit
            :placeholder="replyTarget ? `回复 @${replyTarget.name}…` : '写下你的想法… 输入 @用户名 可提醒对方'"
          />
          <div class="form-row">
            <div class="anon-switch">
              <el-switch
                v-model="newComment.is_anonymous"
                active-text="匿名评论"
                inactive-text="实名评论"
              />
            </div>
            <el-button
              type="primary"
              :icon="ChatDotRound"
              :loading="submittingComment"
              @click="submitComment"
            >{{ replyTarget ? '发表回复' : '发表评论' }}</el-button>
          </div>
        </div>

        <!-- 评论列表（楼中楼） -->
        <el-empty v-if="!threadedComments.length" :image-size="60" description="还没有评论，来抢沙发吧 👋" />
        <div
          v-for="c in threadedComments"
          :key="c.id"
          class="comment-item"
          :class="{ reply: c.depth > 0, folded: c.hidden }"
          :style="{ marginLeft: Math.min(c.depth, 5) * 28 + 'px' }"
        >
          <div class="comment-head">
            <div class="author-line">
              <router-link
                v-if="!c.is_anonymous"
                :to="`/community/users/${c.author_id}`"
                class="comment-author author-link"
              >{{ displayCommentAuthor(c) }}</router-link>
              <span v-else class="comment-author">{{ displayCommentAuthor(c) }}</span>
              <span v-if="c.is_anonymous" class="anon-tag">🫥</span>
              <el-tag v-if="c.is_accepted" size="small" type="success" effect="dark">最佳答案</el-tag>
              <span
                v-if="showRealUsernameForComment(c)"
                class="real-username"
              >（真实：{{ c.display_username }}）</span>
              <span v-if="c.parentAuthor" class="reply-to">
                回复 @{{ c.parentAuthor }}
              </span>
            </div>
            <span class="comment-time">{{ fmtTime(c.created_at) }}</span>
          </div>
          <RichContent class="comment-body" :content="c.content" />
          <div class="comment-actions">
            <el-button
              link
              size="small"
              :type="c.liked ? 'danger' : 'default'"
              @click="toggleCommentLike(c)"
            >
              <el-icon><Star /></el-icon> {{ c.like_count || 0 }}
            </el-button>
            <el-button
              v-if="post.is_author && !c.is_accepted && c.can_view_content !== false"
              link
              size="small"
              type="success"
              @click="acceptAnswer(c.id)"
            >采纳</el-button>
            <el-button
              v-if="post.is_author && c.is_accepted"
              link
              size="small"
              type="info"
              @click="clearAccepted"
            >取消采纳</el-button>
            <el-button
              v-if="isLoggedIn && c.can_view_content !== false"
              link
              size="small"
              type="primary"
              @click="startReply(c)"
            >回复</el-button>
            <el-button
              v-if="isLoggedIn && c.author_id !== currentUserId"
              link
              size="small"
              type="warning"
              @click="openReport('comment', c.id)"
            >举报</el-button>
            <el-popconfirm
              v-if="canDeleteComment(c)"
              title="确认删除这条评论？其下回复会一并删除"
              @confirm="deleteComment(c)"
            >
              <template #reference>
                <el-button link size="small" type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </div>

      <!-- 编辑弹窗 -->
      <el-dialog v-model="editVisible" title="编辑帖子" width="560px">
        <el-form :model="editForm" label-width="70px">
          <el-form-item label="标题"><el-input v-model="editForm.title" maxlength="100" show-word-limit /></el-form-item>
          <el-form-item label="正文">
            <el-input
              v-model="editForm.body"
              type="textarea"
              :autosize="{ minRows: 6, maxRows: 14 }"
              maxlength="5000"
              show-word-limit
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEdit">保存</el-button>
        </template>
      </el-dialog>

      <!-- 举报弹窗 -->
      <el-dialog v-model="reportVisible" title="举报内容" width="440px">
        <p class="report-hint">请简要说明举报理由，提交后管理员会尽快处理。</p>
        <el-input
          v-model="reportForm.reason"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 6 }"
          maxlength="200"
          show-word-limit
          placeholder="例如：包含广告、人身攻击、与学习无关的内容…"
        />
        <template #footer>
          <el-button @click="reportVisible = false">取消</el-button>
          <el-button type="warning" :loading="submittingReport" @click="submitReport">提交举报</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound, Star, StarFilled, Sunny, EditPen, Delete, Link,
  Check, Warning,
} from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import RichContent from '../components/RichContent.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const submitting = ref(false)
const submittingComment = ref(false)
const submittingReport = ref(false)

const post = ref(null)
const comments = ref([])

const liked = ref(false)
const likeCount = ref(0)
const favorited = ref(false)
const favoriteCount = ref(0)

const newComment = reactive({ content: '', is_anonymous: false })
const replyTarget = ref(null)
const commentInputRef = ref(null)

const editVisible = ref(false)
const editForm = reactive({ title: '', body: '' })

const reportVisible = ref(false)
const reportForm = reactive({ targetType: 'post', targetId: null, reason: '' })

const isLoggedIn = computed(() => !!auth.token)
const currentUserId = computed(() => auth.user?.id)
const currentRole = computed(() => auth.user?.role)

const DEFAULT_CATEGORIES = [
  { key: 'discussion', name: '错题讨论' },
  { key: 'solution', name: '解法分享' },
  { key: 'help', name: '求助答疑' },
  { key: 'experience', name: '经验交流' },
  { key: 'resource', name: '资源下载' },
  { key: 'other', name: '其他' },
]
const catMap = Object.fromEntries(DEFAULT_CATEGORIES.map((c) => [c.key, c.name]))
const catTagType = (k) => ({
  discussion: 'danger',
  solution: 'success',
  help: 'warning',
  experience: 'primary',
  resource: '',
  other: 'info',
}[k] || 'info')
const catName = (k) => catMap[k] || k

const linkedLabel = (t) => ({ question: '题目', homework: '作业', exam: '考试' }[t] || t)
// 关联对象一步直达：均指向真实存在的详情页路由（v6.1 新建 questions/:id 与 exams/:id）。
// 题目/考试单题、单卷详情页角色脱敏由后端 API 把关；作业按 教师|学生 进 批改|作答。
const linkedRoute = (type, id) => {
  const isTeacher = currentRole.value === 'teacher'
  if (type === 'question') return `/questions/${id}`
  if (type === 'homework') return isTeacher ? `/homeworks/${id}/grade` : `/homeworks/${id}/take`
  if (type === 'exam') return `/exams/${id}`
  return '#'
}

const fmtTime = (s) => {
  if (!s) return ''
  try {
    const d = new Date(s)
    const now = new Date()
    const diff = (now - d) / 1000
    if (diff < 60) return '刚刚'
    if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前'
    if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前'
    if (diff < 7 * 86400) return Math.floor(diff / 86400) + ' 天前'
    return d.toISOString().slice(0, 16).replace('T', ' ')
  } catch {
    return s
  }
}

// 帖子作者显示名
const displayPostAuthor = computed(() => {
  if (!post.value) return ''
  if (post.value.is_anonymous) return post.value.display_anon || '匿名用户'
  return post.value.display_username || '未知用户'
})

// 评论作者显示名
const displayCommentAuthor = (c) => {
  if (!c) return ''
  if (c.is_anonymous) return c.display_anon || '匿名用户'
  return c.display_username || '未知用户'
}

const showRealUsername = (p) => {
  if (!p?.is_anonymous) return false
  return currentRole.value === 'teacher' || currentRole.value === 'admin'
}
const showRealUsernameForComment = (c) => {
  if (!c?.is_anonymous) return false
  return currentRole.value === 'teacher' || currentRole.value === 'admin'
}

// 编辑/删除权限
const canEditPost = computed(() => post.value?.is_author)
const canDeletePost = computed(() => {
  if (!post.value) return false
  return (
    post.value.is_author ||
    currentRole.value === 'teacher' ||
    currentRole.value === 'admin'
  )
})
const canResolve = computed(() => {
  if (!post.value) return false
  return (
    post.value.is_author ||
    currentRole.value === 'teacher' ||
    currentRole.value === 'admin'
  )
})

const canDeleteComment = (c) => {
  if (!c) return false
  return (
    c.author_id === currentUserId.value ||
    currentRole.value === 'teacher' ||
    currentRole.value === 'admin'
  )
}

// 楼中楼：把扁平评论构建成树后按 DFS 展平（带 depth / 父作者名）
const threadedComments = computed(() => {
  const nodes = new Map()
  comments.value.forEach((c) => nodes.set(c.id, { ...c, children: [], parentAuthor: '' }))
  const roots = []
  comments.value.forEach((c) => {
    const node = nodes.get(c.id)
    const parent = c.parent_id ? nodes.get(c.parent_id) : null
    if (parent) {
      parent.children.push(node)
      node.parentAuthor = displayCommentAuthor(parent)
    } else {
      roots.push(node)
    }
  })
  const flat = []
  const walk = (list, depth) => {
    list.forEach((n) => {
      flat.push({ ...n, depth })
      walk(n.children, depth + 1)
    })
  }
  walk(roots, 0)
  return flat
})

const goBack = () => window.history.back()
const goLogin = () => router.push(`/login?redirect=${encodeURIComponent(route.fullPath)}`)

// ── 加载数据 ──
const load = async () => {
  loading.value = true
  try {
    const id = route.params.id
    const res = await request.get(`/api/community/posts/${id}`)
    const data = res.data || {}
    post.value = data.post || data
    liked.value = !!post.value.liked
    likeCount.value = post.value.like_count || 0
    favorited.value = !!post.value.favorited
    favoriteCount.value = post.value.favorite_count || 0
    comments.value = post.value.comments || []
  } catch (e) {
    console.error('加载帖子详情失败:', e)
  } finally {
    loading.value = false
  }
}

// ── 点赞 / 取消点赞（帖子） ──
const toggleLike = async () => {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return goLogin()
  }
  const prevLiked = liked.value
  const prevCount = likeCount.value
  liked.value = !liked.value
  likeCount.value += liked.value ? 1 : -1
  try {
    if (liked.value) {
      await request.post(`/api/community/posts/${post.value.id}/like`)
    } else {
      await request.delete(`/api/community/posts/${post.value.id}/like`)
    }
  } catch (e) {
    liked.value = prevLiked
    likeCount.value = prevCount
    console.error('点赞操作失败:', e)
  }
}

// ── 收藏 / 取消收藏 ──
const toggleFavorite = async () => {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return goLogin()
  }
  const prevFavorited = favorited.value
  const prevCount = favoriteCount.value
  favorited.value = !favorited.value
  favoriteCount.value = Math.max(0, favoriteCount.value + (favorited.value ? 1 : -1))
  try {
    const res = favorited.value
      ? await request.post(`/api/community/posts/${post.value.id}/favorite`)
      : await request.delete(`/api/community/posts/${post.value.id}/favorite`)
    const d = res.data || {}
    favorited.value = !!d.favorited
    favoriteCount.value = d.favorite_count ?? favoriteCount.value
    ElMessage.success(favorited.value ? '已加入收藏' : '已取消收藏')
  } catch (e) {
    favorited.value = prevFavorited
    favoriteCount.value = prevCount
    console.error('收藏操作失败:', e)
  }
}

// ── 已解决标记 ──
const toggleResolve = async () => {
  try {
    const res = await request.put(`/api/community/posts/${post.value.id}/resolve`, {
      resolved: !post.value.is_resolved,
    })
    const updated = res.data || {}
    post.value.is_resolved = !!updated.is_resolved
    post.value.resolved_at = updated.resolved_at
    post.value.resolved_by = updated.resolved_by
    ElMessage.success(post.value.is_resolved ? '已标记为已解决' : '已取消已解决标记')
  } catch (e) {
    console.error('标记已解决失败:', e)
  }
}

// ── 投票 ──
const vote = async (optionId) => {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return goLogin()
  }
  try {
    const res = await request.post(`/api/community/posts/${post.value.id}/vote`, {
      option_id: optionId,
    })
    post.value.poll = res.data
  } catch (e) {
    // request 拦截器已提示
  }
}

// ── 采纳 / 取消采纳最佳答案 ──
const applyAccepted = (updated) => {
  post.value.accepted_comment_id = updated.accepted_comment_id ?? null
  post.value.is_resolved = !!updated.is_resolved
  post.value.resolved_at = updated.resolved_at
  comments.value = comments.value.map((c) => ({
    ...c,
    is_accepted: c.id === post.value.accepted_comment_id,
  }))
}

const acceptAnswer = async (commentId) => {
  try {
    const res = await request.put(`/api/community/posts/${post.value.id}/accept`, {
      comment_id: commentId,
    })
    applyAccepted(res.data || {})
    ElMessage.success('已采纳为最佳答案')
  } catch (e) {
    // request 拦截器已提示
  }
}

const clearAccepted = async () => {
  try {
    const res = await request.put(`/api/community/posts/${post.value.id}/accept`, {
      comment_id: null,
    })
    applyAccepted(res.data || {})
    ElMessage.success('已取消采纳')
  } catch (e) {
    // request 拦截器已提示
  }
}

// ── 评论点赞 ──
const toggleCommentLike = async (c) => {
  if (!isLoggedIn.value) return goLogin()
  const prevLiked = c.liked
  const prevCount = c.like_count || 0
  c.liked = !c.liked
  c.like_count = c.liked ? prevCount + 1 : Math.max(0, prevCount - 1)
  try {
    if (c.liked) {
      await request.post(`/api/community/comments/${c.id}/like`)
    } else {
      await request.delete(`/api/community/comments/${c.id}/like`)
    }
  } catch {
    c.liked = prevLiked
    c.like_count = prevCount
  }
}

// ── 回复某条评论 ──
const startReply = (c) => {
  replyTarget.value = { id: c.id, name: displayCommentAuthor(c) }
  nextTick(() => {
    const textarea = commentInputRef.value?.textarea
    if (textarea) textarea.focus()
  })
}
const cancelReply = () => {
  replyTarget.value = null
}

// ── 提交评论 / 回复 ──
const submitComment = async () => {
  if (!newComment.content.trim()) return ElMessage.warning('请输入评论内容')
  submittingComment.value = true
  try {
    const payload = {
      content: newComment.content.trim(),
      is_anonymous: newComment.is_anonymous,
    }
    if (replyTarget.value) payload.parent_id = replyTarget.value.id
    const res = await request.post(`/api/community/posts/${post.value.id}/comments`, payload)
    const comment = res.data?.comment || res.data
    if (comment) comments.value.push(comment)
    if (post.value) post.value.comment_count = (post.value.comment_count || 0) + 1
    newComment.content = ''
    newComment.is_anonymous = false
    replyTarget.value = null
    ElMessage.success(payload.parent_id ? '回复发表成功' : '评论发表成功')
  } catch (e) {
    // request 拦截器已提示
  } finally {
    submittingComment.value = false
  }
}

// ── 删除评论（含其下回复） ──
const deleteComment = async (c) => {
  try {
    await request.delete(`/api/community/comments/${c.id}`)
    ElMessage.success('评论已删除')
    load()
  } catch (e) {
    console.error('删除评论失败:', e)
  }
}

// ── 举报 ──
const openReport = (targetType, targetId) => {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录')
    return goLogin()
  }
  reportForm.targetType = targetType
  reportForm.targetId = targetId
  reportForm.reason = ''
  reportVisible.value = true
}

const submitReport = async () => {
  if (!reportForm.reason.trim()) return ElMessage.warning('请填写举报理由')
  submittingReport.value = true
  try {
    await request.post('/api/community/reports', {
      target_type: reportForm.targetType,
      target_id: reportForm.targetId,
      reason: reportForm.reason.trim(),
    })
    reportVisible.value = false
    ElMessage.success('举报已提交，管理员会尽快处理')
    if (reportForm.targetType === 'post') load()
  } catch (e) {
    // request 拦截器已提示
  } finally {
    submittingReport.value = false
  }
}

// ── 删除帖子 ──
const deletePost = async () => {
  try {
    await ElMessageBox.confirm(
      '删除后不可恢复，确认删除该帖子？',
      '删除帖子',
      { type: 'error', confirmButtonText: '确认删除' }
    )
  } catch {
    return
  }
  try {
    await request.delete(`/api/community/posts/${post.value.id}`)
    ElMessage.success('帖子已删除')
    router.push('/community')
  } catch (e) {
    console.error('删除帖子失败:', e)
  }
}

// ── 编辑帖子 ──
const openEdit = () => {
  editForm.title = post.value?.title || ''
  editForm.body = post.value?.content || ''
  editVisible.value = true
}

const submitEdit = async () => {
  if (!editForm.title.trim()) return ElMessage.warning('请填写标题')
  if (!editForm.body.trim()) return ElMessage.warning('请填写正文')
  submitting.value = true
  try {
    const res = await request.put(`/api/community/posts/${post.value.id}`, {
      title: editForm.title.trim(),
      content: editForm.body.trim(),
    })
    const updated = res.data?.post || res.data
    if (updated) post.value = { ...post.value, ...updated }
    editVisible.value = false
    ElMessage.success('已保存')
  } catch (e) {
    console.error('编辑帖子失败:', e)
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.back { margin-bottom: 12px; }

.section {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 16px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 16px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.section-title .count { color: var(--el-text-color-secondary, #909399); font-weight: normal; font-size: 14px; }

/* 帖子头部 */
.post-head { padding: 28px; }
.head-row { display: flex; gap: 8px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; }
.circle-tag { cursor: pointer; }
.post-title { margin: 0 0 10px; font-size: 24px; line-height: 1.35; color: var(--el-text-color-primary, #303133); }

.tag-line { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.post-tag { cursor: pointer; }
.author-link { color: inherit; text-decoration: none; }
.author-link:hover { color: #14b8a6; text-decoration: underline; }

.head-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--el-text-color-secondary, #909399);
  padding-bottom: 14px;
  border-bottom: 1px dashed var(--el-border-color-lighter, #ebeef5);
  margin-bottom: 14px;
}
.head-meta .author strong { color: var(--el-text-color-primary, #303133); }
.head-meta .real-username { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.head-meta .dot { color: var(--el-border-color, #dcdfe6); }

.linked-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  background: rgba(20, 184, 166, 0.08);
  border: 1px solid rgba(20, 184, 166, 0.25);
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--el-text-color-primary, #303133);
}
.linked-box .linked-label { color: var(--el-text-color-secondary, #909399); }
.linked-box .linked-link {
  color: #14b8a6;
  font-weight: 500;
  text-decoration: none;
}
.linked-box .linked-link:hover { text-decoration: underline; }

.fold-alert { margin-bottom: 14px; }
.bounty-alert { margin-bottom: 14px; }

.post-body {
  font-size: 15px;
  line-height: 1.9;
  color: var(--el-text-color-primary, #303133);
  word-break: break-word;
}

/* 投票 */
.poll-box {
  margin-top: 18px;
  padding: 16px;
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 10px;
  background: var(--el-fill-color-lighter, #fafafa);
}
.poll-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.poll-title { font-weight: 600; font-size: 15px; }
.poll-total { font-size: 13px; color: var(--el-text-color-secondary, #909399); }
.poll-option {
  position: relative;
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
  cursor: pointer;
  background: #fff;
  transition: border-color .2s;
}
.poll-option:hover { border-color: #14b8a6; }
.poll-option.voted { border-color: #14b8a6; }
.poll-bar {
  position: absolute;
  inset: 0 auto 0 0;
  background: rgba(20, 184, 166, 0.16);
  transition: width .3s;
}
.poll-row {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  font-size: 14px;
}
.poll-text { display: flex; align-items: center; gap: 4px; }
.poll-check { color: #14b8a6; }
.poll-meta { color: var(--el-text-color-secondary, #909399); font-size: 12px; }
.poll-hint { margin: 6px 0 0; font-size: 12px; color: var(--el-text-color-secondary, #909399); }

.post-actions {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px dashed var(--el-border-color-lighter, #ebeef5);
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.post-actions .spacer { flex: 1; }
.post-actions .liked {
  border-color: #f56c6c !important;
  color: #f56c6c !important;
  background: rgba(245, 108, 108, 0.08) !important;
}

/* 评论区 */
.login-tip { margin-bottom: 16px; }
.login-alert { margin: 0; }

.comment-form { margin-bottom: 20px; }
.reply-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  color: var(--el-text-color-regular, #606266);
  background: rgba(20, 184, 166, 0.08);
  border: 1px solid rgba(20, 184, 166, 0.25);
  border-radius: 8px;
  padding: 6px 12px;
  margin-bottom: 8px;
}
.form-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
}
.anon-switch { font-size: 13px; color: var(--el-text-color-secondary, #909399); }

.comment-item {
  padding: 14px 0;
  border-bottom: 1px solid var(--el-border-color-lighter, #ebeef5);
}
.comment-item.reply {
  border-left: 3px solid rgba(20, 184, 166, 0.35);
  padding-left: 14px;
}
.comment-item.folded { opacity: .8; }
.comment-item:last-child { border-bottom: none; }

.comment-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.author-line { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.comment-author { font-weight: 600; font-size: 14px; color: var(--el-text-color-primary, #303133); }
.anon-tag { margin-left: 2px; font-size: 13px; }
.real-username { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.reply-to { font-size: 12px; color: #14b8a6; }
.comment-time { font-size: 12px; color: var(--el-text-color-secondary, #909399); }

.comment-body { font-size: 14px; line-height: 1.7; color: var(--el-text-color-primary, #303133); word-break: break-word; }

.comment-actions {
  margin-top: 6px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.report-hint { margin: 0 0 10px; font-size: 13px; color: var(--el-text-color-secondary, #909399); }
</style>
