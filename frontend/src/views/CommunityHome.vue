<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><ChatDotRound /></el-icon> 社区中心</h2>
        <p><span class="sub-info">动态广场 · 关注互动 · 话题讨论 · 与论坛并行</span></p>
      </div>
      <div class="header-actions">
        <el-badge v-if="isLoggedIn" :value="unread" :hidden="!unread">
          <el-button :icon="Bell" @click="router.push('/community/notifications')">消息中心</el-button>
        </el-badge>
        <el-badge v-if="isLoggedIn" :value="dmUnread" :hidden="!dmUnread">
          <el-button :icon="Message" @click="router.push('/community/messages')">私信</el-button>
        </el-badge>
        <el-button v-if="isLoggedIn" :icon="Star" @click="router.push('/community/favorites')">
          我的收藏
        </el-button>
        <el-button :icon="ChatLineSquare" @click="router.push('/community/forum')">论坛</el-button>
        <el-button type="primary" :icon="EditPen" @click="focusComposer">发动态</el-button>
      </div>
    </div>

    <div class="section-tabs" role="tablist">
      <button type="button" class="seg active" role="tab" aria-selected="true">动态</button>
      <button type="button" class="seg" role="tab" aria-selected="false" @click="router.push('/community/forum')">论坛</button>
    </div>

    <div class="feed-shell">
      <MomentComposer v-if="isLoggedIn" :initial-topics="initialTopics" @published="onPublished" />

      <div v-else class="login-hint">
        <span>登录后即可发布动态、关注同学与老师</span>
        <el-button size="small" type="primary" plain @click="goLogin">去登录</el-button>
      </div>

      <div class="feed-bar">
        <div class="feed-tabs">
          <button
            v-for="t in feedTabs"
            :key="t.key"
            type="button"
            class="feed-tab"
            :class="{ active: feedTab === t.key }"
            @click="switchFeed(t.key)"
          >{{ t.label }}</button>
        </div>
        <el-button text size="small" :icon="Refresh" :loading="loading" @click="load(true)">刷新</el-button>
      </div>

      <div v-if="topics.length" class="topic-bar">
        <span class="topic-label">热门话题</span>
        <button
          v-for="t in topics"
          :key="t.id"
          type="button"
          class="topic-chip"
          @click="router.push(`/community/topic/${t.id}`)"
        >#{{ t.name }}<em>{{ t.moment_count }}</em></button>
      </div>

      <div v-if="loading && !items.length" class="skeleton-list">
        <div v-for="n in 3" :key="`sk-${n}`" class="sk-card">
          <div class="sk sk-avatar" />
          <div class="sk-main">
            <div class="sk sk-line short" />
            <div class="sk sk-line" />
            <div class="sk sk-line mid" />
          </div>
        </div>
      </div>

      <el-empty
        v-else-if="!items.length"
        :image-size="96"
        :description="feedTab === 'follow' ? '关注的人还没有发动态，去发现页看看吧' : '还没有动态，发第一条吧'"
      >
        <el-button v-if="feedTab === 'follow'" type="primary" plain @click="switchFeed('recommend')">去推荐</el-button>
      </el-empty>

      <div v-else class="moment-list">
        <MomentCard
          v-for="m in items"
          :key="m.id"
          :moment="m"
          :current-user-id="currentUserId"
          @open="openMoment"
          @like="toggleLike"
          @favorite="toggleFavorite"
          @comment="openMoment"
          @repost="repost"
          @follow="toggleFollow"
          @topic="openTopic"
        />
      </div>

      <div v-if="items.length" class="load-more">
        <el-button
          v-if="hasMore"
          :loading="loadingMore"
          plain
          @click="loadMore"
        >加载更多</el-button>
        <span v-else class="end">已经到底了</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Bell, ChatDotRound, ChatLineSquare, EditPen, Message, Refresh, Star,
} from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import MomentCard from '../components/MomentCard.vue'
import MomentComposer from '../components/MomentComposer.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const isLoggedIn = computed(() => !!auth.token)
const currentUserId = computed(() => auth.user?.id || null)
const initialTopics = computed(() => {
  const name = route.query.compose
  return typeof name === 'string' && name ? [name] : []
})

const feedTab = ref('recommend')
const feedTabs = computed(() => ([
  { key: 'recommend', label: '推荐' },
  { key: 'follow', label: '关注' },
  { key: 'mine', label: '我的' },
]))

const items = ref([])
const topics = ref([])
const loading = ref(false)
const loadingMore = ref(false)
const nextCursor = ref(null)
const hasMore = ref(false)
const unread = ref(0)
const dmUnread = ref(0)
const followPending = new Set()

let loadSeq = 0
let unreadTimer = null

const goLogin = () => router.push({ path: '/login', query: { redirect: '/community' } })

const focusComposer = () => {
  if (!isLoggedIn.value) return goLogin()
  const el = document.querySelector('.composer textarea')
  if (el) el.focus()
}

const paramsFor = (beforeId) => {
  const params = { limit: 20 }
  if (beforeId) params.before_id = beforeId
  if (feedTab.value === 'follow') params.tab = 'follow'
  else if (feedTab.value === 'mine') {
    params.tab = 'user'
    params.user_id = currentUserId.value
  } else params.tab = 'recommend'
  return params
}

const load = async (reset = true) => {
  if (feedTab.value === 'mine' && !currentUserId.value) {
    goLogin()
    return
  }
  const seq = ++loadSeq
  loading.value = true
  if (reset) nextCursor.value = null
  try {
    const res = await request.get('/api/community/feed', {
      params: paramsFor(reset ? null : nextCursor.value),
    })
    if (seq !== loadSeq) return
    const data = res.data || {}
    items.value = reset ? (data.items || []) : [...items.value, ...(data.items || [])]
    nextCursor.value = data.next_cursor || null
    hasMore.value = !!data.has_more
  } catch (e) {
    if (seq === loadSeq) console.error('加载动态失败:', e)
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

const loadMore = async () => {
  if (!hasMore.value || loadingMore.value) return
  loadingMore.value = true
  const seq = loadSeq
  try {
    const res = await request.get('/api/community/feed', {
      params: paramsFor(nextCursor.value),
    })
    if (seq !== loadSeq) return
    const data = res.data || {}
    items.value = [...items.value, ...(data.items || [])]
    nextCursor.value = data.next_cursor || null
    hasMore.value = !!data.has_more
  } catch (e) {
    console.error('加载更多失败:', e)
  } finally {
    loadingMore.value = false
  }
}

const switchFeed = (key) => {
  if (key === feedTab.value) return
  if ((key === 'follow' || key === 'mine') && !isLoggedIn.value) {
    ElMessage.warning('登录后才能查看')
    return goLogin()
  }
  feedTab.value = key
  load(true)
}

const loadTopics = async () => {
  try {
    const res = await request.get('/api/community/topics', { params: { limit: 8, sort: 'hot' } })
    topics.value = Array.isArray(res.data) ? res.data : []
  } catch {
    topics.value = []
  }
}

const loadUnread = async () => {
  if (!isLoggedIn.value) return
  try {
    const res = await request.get('/api/community/notifications/unread-count')
    unread.value = (res.data || {}).unread || 0
  } catch {
    unread.value = 0
  }
  try {
    const res = await request.get('/api/community/dm/unread-count')
    dmUnread.value = (res.data || {}).unread || 0
  } catch {
    dmUnread.value = 0
  }
}

const onPublished = (moment) => {
  if (feedTab.value === 'recommend' || feedTab.value === 'mine') {
    items.value = [moment, ...items.value]
  } else {
    load(true)
  }
}

const openMoment = (m) => router.push(`/community/moment/${m.id}`)
const openTopic = (t) => router.push(`/community/topic/${t.id}`)

const requireLogin = () => {
  if (isLoggedIn.value) return true
  ElMessage.warning('请先登录')
  goLogin()
  return false
}

const toggleLike = async (m) => {
  if (!requireLogin()) return
  try {
    const res = m.liked
      ? await request.delete(`/api/community/moments/${m.id}/like`)
      : await request.post(`/api/community/moments/${m.id}/like`)
    m.liked = res.data.liked
    m.like_count = res.data.like_count
  } catch (e) { /* 已提示 */ }
}

const toggleFavorite = async (m) => {
  if (!requireLogin()) return
  try {
    const res = m.favorited
      ? await request.delete(`/api/community/moments/${m.id}/favorite`)
      : await request.post(`/api/community/moments/${m.id}/favorite`)
    m.favorited = res.data.favorited
    m.favorite_count = res.data.favorite_count
  } catch (e) { /* 已提示 */ }
}

const toggleFollow = async (m) => {
  if (!requireLogin()) return
  if (m.author_id === currentUserId.value || followPending.has(m.author_id)) return
  followPending.add(m.author_id)
  try {
    const res = await request.post(`/api/learning/users/${m.author_id}/follow`)
    const following = !!res.data.following
    items.value.forEach((x) => {
      if (x.author_id === m.author_id) x.author_followed = following
    })
    ElMessage.success(following ? '已关注' : '已取消关注')
  } catch (e) { /* 已提示 */ } finally {
    followPending.delete(m.author_id)
  }
}

const repost = async (m) => {
  if (!requireLogin()) return
  let value = ''
  try {
    const r = await ElMessageBox.prompt('可以写一句转发语，留空即纯转发', `转发 @${m.display_username} 的动态`, {
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
    const res = await request.post(`/api/community/moments/${m.id}/repost`, { quote: value })
    m.repost_count = (m.repost_count || 0) + 1
    ElMessage.success('已转发')
    if (feedTab.value === 'recommend' || feedTab.value === 'mine') {
      items.value = [res.data, ...items.value]
    }
  } catch (e) { /* 已提示 */ }
}

onMounted(() => {
  load(true)
  loadTopics()
  loadUnread()
  unreadTimer = setInterval(loadUnread, 60000)
})

onBeforeUnmount(() => {
  clearInterval(unreadTimer)
})
</script>

<style scoped>
.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  gap: 16px; flex-wrap: wrap; margin-bottom: 18px;
}
.header-title h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.sub-info { color: var(--el-text-color-secondary, #909399); font-size: 13px; }
.title-icon { color: #14b8a6; }
.header-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

.section-tabs {
  display: flex; gap: 6px;
  background: var(--el-fill-color-light, #f3f4f6);
  padding: 4px; border-radius: 12px;
  width: fit-content; margin-bottom: 16px;
}
.seg {
  border: none; background: none; cursor: pointer;
  padding: 7px 22px; border-radius: 9px;
  font-size: 14px; color: var(--el-text-color-regular);
  transition: all .2s;
}
.seg.active {
  background: #fff; color: #0f766e; font-weight: 600;
  box-shadow: 0 2px 8px rgba(20, 184, 166, .16);
}

.feed-shell { max-width: 820px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
.login-hint {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 16px 18px; border-radius: 14px;
  background: linear-gradient(90deg, rgba(20, 184, 166, .08), rgba(14, 165, 233, .06));
  border: 1px dashed rgba(20, 184, 166, .4);
  color: var(--el-text-color-regular); font-size: 14px;
}
.feed-bar { display: flex; align-items: center; justify-content: space-between; }
.feed-tabs { display: flex; gap: 4px; }
.feed-tab {
  border: none; background: none; cursor: pointer;
  padding: 6px 14px; border-radius: 8px; font-size: 14px;
  color: var(--el-text-color-regular);
  transition: all .18s;
}
.feed-tab:hover { background: rgba(20, 184, 166, .08); }
.feed-tab.active { color: #0f766e; font-weight: 600; background: rgba(20, 184, 166, .12); }

.topic-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.topic-label { font-size: 12px; color: var(--el-text-color-secondary); }
.topic-chip {
  border: 1px solid rgba(20, 184, 166, .28); background: #fff;
  color: #0f766e; border-radius: 999px; padding: 3px 12px;
  font-size: 12px; cursor: pointer; transition: all .18s;
}
.topic-chip:hover { background: rgba(20, 184, 166, .1); border-color: #14b8a6; }
.topic-chip em { font-style: normal; margin-left: 4px; color: #94a3b8; font-size: 11px; }

.moment-list { display: flex; flex-direction: column; gap: 12px; }
.load-more { display: flex; justify-content: center; padding: 10px 0 24px; }
.load-more .end { font-size: 12px; color: var(--el-text-color-placeholder); }

.skeleton-list { display: flex; flex-direction: column; gap: 12px; }
.sk-card {
  display: flex; gap: 12px; padding: 18px;
  background: #fff; border: 1px solid var(--el-border-color-light, #ebeef5);
  border-radius: 14px;
}
.sk-main { flex: 1; display: flex; flex-direction: column; gap: 10px; }
.sk { background: linear-gradient(90deg, #eef1f5 25%, #f8fafc 37%, #eef1f5 63%); background-size: 400% 100%; animation: shimmer 1.4s ease infinite; border-radius: 6px; }
.sk-avatar { width: 40px; height: 40px; border-radius: 50%; flex: 0 0 40px; }
.sk-line { height: 13px; }
.sk-line.short { width: 32%; }
.sk-line.mid { width: 68%; }
@keyframes shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }

@media (max-width: 640px) {
  .header-actions { width: 100%; }
  .section-tabs { width: 100%; justify-content: space-between; }
  .seg { flex: 1; }
}
</style>
