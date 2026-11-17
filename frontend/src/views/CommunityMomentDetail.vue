<template>
  <div class="page-wrapper">
    <el-page-header class="back" @back="goBack" content="动态详情" />

    <div v-if="loading" class="detail-skeleton" aria-busy="true">
      <div class="sk sk-title" />
      <div class="sk sk-line" />
      <div class="sk sk-line mid" />
    </div>

    <el-result
      v-else-if="notFound"
      icon="warning"
      title="动态不存在或已删除"
      sub-title="它可能被作者删除，或你没有查看权限"
    >
      <template #extra>
        <el-button type="primary" @click="router.push('/community')">回到动态广场</el-button>
      </template>
    </el-result>

    <template v-else-if="moment">
      <MomentCard
        :moment="moment"
        :current-user-id="currentUserId"
        :compact="false"
        @open="openLinkedMoment"
        @like="toggleLike"
        @favorite="toggleFavorite"
        @comment="focusComment"
        @repost="repost"
        @follow="toggleFollow"
        @topic="(t) => router.push(`/community/topic/${t.id}`)"
      />

      <section class="comments">
        <h3 class="c-title">评论 <span>{{ moment.comment_count || 0 }}</span></h3>

        <div v-if="isLoggedIn" class="c-form">
          <div class="reply-hint" v-if="replyTo">
            回复 <b>@{{ replyTo.display_anon || replyTo.display_username }}</b>
            <el-button link size="small" @click="replyTo = null">取消</el-button>
          </div>
          <el-input
            ref="commentInput"
            v-model="commentText"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            maxlength="2000"
            show-word-limit
            resize="none"
            :placeholder="replyTo ? '写下你的回复…' : '友善评论，一起把讨论变得更好'"
          />
          <div class="c-actions">
            <el-switch v-model="commentAnon" size="small" active-text="匿名" />
            <div class="spacer" />
            <el-button type="primary" size="small" :loading="commenting" :disabled="commenting || !commentText.trim()" @click="submitComment">
              发布评论
            </el-button>
          </div>
        </div>
        <el-alert v-else type="info" :closable="false" show-icon title="登录后即可参与评论" class="login-tip" />

        <el-empty v-if="!comments.length" :image-size="70" description="还没有评论，来说两句吧" />

        <div v-else class="c-list">
          <div v-for="c in comments" :key="c.id" class="c-item">
            <div class="c-avatar" :class="{ anon: c.is_anonymous }">{{ avatarOf(c) }}</div>
            <div class="c-main">
              <div class="c-head">
                <span class="c-name">{{ c.display_anon || c.display_username || '未知用户' }}</span>
                <el-tag v-if="c.is_anonymous" size="small" type="info" effect="plain">匿名</el-tag>
                <span class="c-time">{{ fmtTime(c.created_at) }}</span>
              </div>
              <div class="c-content">
                <span v-if="c.parent_id && parentName(c)" class="c-reply">回复 @{{ parentName(c) }}：</span>
                {{ c.content }}
              </div>
              <div class="c-foot">
                <button type="button" class="c-act" :class="{ active: c.liked }" @click="likeComment(c)">
                  <el-icon><Pointer /></el-icon>{{ c.like_count || 0 }}
                </button>
                <button v-if="isLoggedIn" type="button" class="c-act" @click="startReply(c)">回复</button>
                <button v-if="canDelete(c)" type="button" class="c-act danger" @click="removeComment(c)">删除</button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Pointer } from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import MomentCard from '../components/MomentCard.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const isLoggedIn = computed(() => !!auth.token)
const currentUserId = computed(() => auth.user?.id || null)

const loading = ref(false)
const notFound = ref(false)
const moment = ref(null)
const comments = ref([])
const commentText = ref('')
const commentAnon = ref(false)
const commenting = ref(false)
const following = ref(false)
const replyTo = ref(null)
const commentInput = ref(null)

const momentId = computed(() => Number(route.params.id))

const fmtTime = (s) => {
  if (!s) return ''
  const d = new Date(s)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)} 天前`
  return s.slice(0, 16).replace('T', ' ')
}

const avatarOf = (c) => (c.display_username || c.display_anon || '?').slice(0, 1).toUpperCase()

const parentName = (c) => {
  if (!c.parent_id) return ''
  const p = comments.value.find((x) => x.id === c.parent_id)
  return p ? (p.display_anon || p.display_username || '') : ''
}

const load = async () => {
  loading.value = true
  notFound.value = false
  try {
    const res = await request.get(`/api/community/moments/${momentId.value}`)
    moment.value = res.data
    comments.value = res.data.comments || []
  } catch (e) {
    notFound.value = true
  } finally {
    loading.value = false
  }
}

const goBack = () => {
  if (window.history.length > 1) router.back()
  else router.push('/community')
}

const openLinkedMoment = (target) => {
  if (target?.id && target.id !== moment.value?.id) {
    router.push(`/community/moment/${target.id}`)
  }
}

const requireLogin = () => {
  if (isLoggedIn.value) return true
  ElMessage.warning('请先登录')
  router.push({ path: '/login', query: { redirect: route.fullPath } })
  return false
}

const toggleLike = async () => {
  if (!requireLogin()) return
  try {
    const res = moment.value.liked
      ? await request.delete(`/api/community/moments/${momentId.value}/like`)
      : await request.post(`/api/community/moments/${momentId.value}/like`)
    moment.value.liked = res.data.liked
    moment.value.like_count = res.data.like_count
  } catch (e) { /* 已提示 */ }
}

const toggleFavorite = async () => {
  if (!requireLogin()) return
  try {
    const res = moment.value.favorited
      ? await request.delete(`/api/community/moments/${momentId.value}/favorite`)
      : await request.post(`/api/community/moments/${momentId.value}/favorite`)
    moment.value.favorited = res.data.favorited
    moment.value.favorite_count = res.data.favorite_count
  } catch (e) { /* 已提示 */ }
}

const toggleFollow = async () => {
  if (!requireLogin() || following.value) return
  following.value = true
  try {
    const res = await request.post(`/api/learning/users/${moment.value.author_id}/follow`)
    moment.value.author_followed = !!res.data.following
    ElMessage.success(res.data.following ? '已关注' : '已取消关注')
  } catch (e) { /* 已提示 */ } finally {
    following.value = false
  }
}

const repost = async () => {
  if (!requireLogin()) return
  let value = ''
  try {
    const r = await ElMessageBox.prompt('可以写一句转发语，留空即纯转发', '转发动态', {
      confirmButtonText: '转发',
      cancelButtonText: '取消',
      inputPlaceholder: '转发语（可留空，≤ 500 字）',
      inputValidator: (v) => !v || v.length <= 500 || '转发语 ≤ 500 字',
    })
    value = r.value || ''
  } catch {
    return
  }
  try {
    const res = await request.post(`/api/community/moments/${momentId.value}/repost`, { quote: value })
    moment.value.repost_count = (moment.value.repost_count || 0) + 1
    ElMessage.success('已转发')
    router.push(`/community/moment/${res.data.id}`)
  } catch (e) { /* 已提示 */ }
}

const focusComment = () => {
  const el = commentInput.value?.$el?.querySelector('textarea')
  if (el) el.focus()
}

const startReply = (c) => {
  if (!requireLogin()) return
  replyTo.value = c
  focusComment()
}

const submitComment = async () => {
  if (!requireLogin() || commenting.value) return
  const content = commentText.value.trim()
  if (!content) return
  commenting.value = true
  try {
    const res = await request.post(`/api/community/moments/${momentId.value}/comments`, {
      content,
      is_anonymous: commentAnon.value,
      parent_id: replyTo.value?.id || null,
    })
    comments.value.push(res.data)
    moment.value.comment_count = (moment.value.comment_count || 0) + 1
    commentText.value = ''
    replyTo.value = null
    ElMessage.success('评论成功')
  } catch (e) { /* 已提示 */ } finally {
    commenting.value = false
  }
}

const likeComment = async (c) => {
  if (!requireLogin()) return
  try {
    const res = c.liked
      ? await request.delete(`/api/community/moment-comments/${c.id}/like`)
      : await request.post(`/api/community/moment-comments/${c.id}/like`)
    c.liked = res.data.liked
    c.like_count = res.data.like_count
  } catch (e) { /* 已提示 */ }
}

const canDelete = (c) => {
  if (!isLoggedIn.value) return false
  return c.author_id === currentUserId.value
    || moment.value?.author_id === currentUserId.value
    || ['teacher', 'admin'].includes(auth.user?.role)
}

const collectDescendants = (id, acc = new Set()) => {
  comments.value.forEach((x) => {
    if (x.parent_id === id && !acc.has(x.id)) {
      acc.add(x.id)
      collectDescendants(x.id, acc)
    }
  })
  return acc
}

const removeComment = async (c) => {
  try {
    await ElMessageBox.confirm('删除后不可恢复，确定删除这条评论吗？', '删除评论', { type: 'warning' })
  } catch {
    return
  }
  try {
    await request.delete(`/api/community/moment-comments/${c.id}`)
    const removed = collectDescendants(c.id)
    removed.add(c.id)
    comments.value = comments.value.filter((x) => !removed.has(x.id))
    moment.value.comment_count = Math.max(0, (moment.value.comment_count || 0) - removed.size)
    ElMessage.success('已删除')
  } catch (e) { /* 已提示 */ }
}

watch(momentId, () => {
  moment.value = null
  comments.value = []
  commentText.value = ''
  replyTo.value = null
  load()
}, { immediate: true })
</script>

<style scoped>
.back { margin-bottom: 14px; }
.detail-skeleton {
  background: #fff; border: 1px solid var(--el-border-color-light, #ebeef5);
  border-radius: 14px; padding: 24px; display: flex; flex-direction: column; gap: 12px;
}
.sk { background: linear-gradient(90deg, #eef1f5 25%, #f8fafc 37%, #eef1f5 63%); background-size: 400% 100%; animation: shimmer 1.4s ease infinite; border-radius: 6px; }
.sk-title { height: 20px; width: 42%; }
.sk-line { height: 13px; }
.sk-line.mid { width: 70%; }
@keyframes shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }

.comments {
  margin-top: 18px; background: #fff;
  border: 1px solid var(--el-border-color-light, #ebeef5);
  border-radius: 14px; padding: 18px;
}
.c-title { margin: 0 0 14px; font-size: 16px; display: flex; align-items: center; gap: 6px; }
.c-title span { color: #14b8a6; font-size: 13px; font-weight: 500; }
.c-form { margin-bottom: 16px; }
.reply-hint { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 6px; }
.c-actions { display: flex; align-items: center; margin-top: 8px; gap: 8px; }
.c-actions .spacer { flex: 1; }
.login-tip { margin-bottom: 16px; }
.c-list { display: flex; flex-direction: column; gap: 14px; }
.c-item { display: flex; gap: 10px; }
.c-avatar {
  width: 34px; height: 34px; flex: 0 0 34px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #14b8a6, #0ea5e9);
  color: #fff; font-size: 13px; font-weight: 700;
}
.c-avatar.anon { background: linear-gradient(135deg, #94a3b8, #cbd5e1); }
.c-main { flex: 1; min-width: 0; }
.c-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.c-name { font-size: 13px; font-weight: 600; }
.c-time { font-size: 11px; color: var(--el-text-color-secondary); }
.c-content { margin-top: 4px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.c-reply { color: #0d9488; font-size: 13px; }
.c-foot { display: flex; gap: 4px; margin-top: 4px; }
.c-act {
  border: none; background: none; cursor: pointer;
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 12px; color: var(--el-text-color-secondary);
  padding: 3px 8px; border-radius: 6px;
}
.c-act:hover { background: rgba(20, 184, 166, .08); color: #0d9488; }
.c-act.active { color: #f43f5e; }
.c-act.danger:hover { background: rgba(244, 63, 94, .08); color: #f43f5e; }
@media (max-width: 640px) {
  .comments { padding: 14px; }
}
</style>
