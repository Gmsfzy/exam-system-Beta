<template>
  <div class="page-wrapper">
    <el-page-header class="back" @back="goBack" content="话题" />

    <div class="topic-head" v-if="topic">
      <div class="hash">#</div>
      <div class="topic-info">
        <h2>{{ topic.name }}</h2>
        <p>{{ topic.moment_count }} 条动态<template v-if="topic.is_official"> · 官方话题</template></p>
      </div>
      <el-button type="primary" plain @click="joinTopic">参与讨论</el-button>
    </div>

    <div v-if="loading && !items.length" class="skeleton-list">
      <div v-for="n in 3" :key="`sk-${n}`" class="sk-card">
        <div class="sk sk-avatar" />
        <div class="sk-main"><div class="sk sk-line short" /><div class="sk sk-line" /></div>
      </div>
    </div>

    <el-empty v-else-if="!items.length" :image-size="90" description="这个话题还没有动态，来发第一条">
      <el-button type="primary" @click="joinTopic">发一条</el-button>
    </el-empty>

    <div v-else class="moment-list">
      <MomentCard
        v-for="m in items"
        :key="m.id"
        :moment="m"
        :current-user-id="currentUserId"
        @open="openMoment"
        @comment="openMoment"
        @like="toggleLike"
        @favorite="toggleFavorite"
        @repost="repost"
        @follow="toggleFollow"
        @topic="openTopic"
      />
    </div>

    <div v-if="items.length" class="load-more">
      <el-button v-if="hasMore" :loading="loadingMore" plain @click="loadMore">加载更多</el-button>
      <span v-else class="end">已经到底了</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import MomentCard from '../components/MomentCard.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const isLoggedIn = computed(() => !!auth.token)
const currentUserId = computed(() => auth.user?.id || null)

const topicId = computed(() => Number(route.params.id))
const topic = ref(null)
const items = ref([])
const loading = ref(false)
const loadingMore = ref(false)
const nextCursor = ref(null)
const hasMore = ref(false)
const followPending = new Set()

const goBack = () => {
  if (window.history.length > 1) router.back()
  else router.push('/community')
}

const load = async (reset = true) => {
  loading.value = true
  try {
    const params = { limit: 20 }
    if (!reset && nextCursor.value) params.before_id = nextCursor.value
    const res = await request.get(`/api/community/topics/${topicId.value}/moments`, { params })
    const data = res.data || {}
    topic.value = data.topic || topic.value
    items.value = reset ? (data.items || []) : [...items.value, ...(data.items || [])]
    nextCursor.value = data.next_cursor || null
    hasMore.value = !!data.has_more
  } catch (e) {
    if (reset) topic.value = null
  } finally {
    loading.value = false
  }
}

const loadMore = async () => {
  if (!hasMore.value || loadingMore.value) return
  loadingMore.value = true
  try {
    await load(false)
  } finally {
    loadingMore.value = false
  }
}

const requireLogin = () => {
  if (isLoggedIn.value) return true
  ElMessage.warning('请先登录')
  router.push({ path: '/login', query: { redirect: route.fullPath } })
  return false
}

const joinTopic = () => {
  if (!requireLogin()) return
  router.push({ path: '/community', query: { compose: topic.value?.name || '' } })
}

const openMoment = (m) => router.push(`/community/moment/${m.id}`)
const openTopic = (t) => router.push(`/community/topic/${t.id}`)

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
  if (!requireLogin() || m.author_id === currentUserId.value || followPending.has(m.author_id)) return
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
    const res = await request.post(`/api/community/moments/${m.id}/repost`, { quote: value })
    m.repost_count = (m.repost_count || 0) + 1
    ElMessage.success('已转发')
    if ((res.data.topics || []).some((t) => t.id === topicId.value)) {
      items.value = [res.data, ...items.value]
    }
  } catch (e) { /* 已提示 */ }
}

watch(topicId, () => {
  topic.value = null
  items.value = []
  nextCursor.value = null
  hasMore.value = false
  load(true)
}, { immediate: true })
</script>

<style scoped>
.back { margin-bottom: 14px; }
.topic-head {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 20px; margin-bottom: 16px;
  border-radius: 16px;
  background: linear-gradient(120deg, rgba(20, 184, 166, .12), rgba(14, 165, 233, .08));
  border: 1px solid rgba(20, 184, 166, .25);
}
.hash {
  width: 46px; height: 46px; flex: 0 0 46px; border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  background: #14b8a6; color: #fff; font-size: 24px; font-weight: 700;
}
.topic-info { flex: 1; min-width: 0; }
.topic-info h2 { margin: 0; font-size: 20px; }
.topic-info p { margin: 4px 0 0; font-size: 13px; color: var(--el-text-color-secondary); }
.moment-list { display: flex; flex-direction: column; gap: 12px; max-width: 820px; margin: 0 auto; }
.load-more { display: flex; justify-content: center; padding: 12px 0 24px; }
.load-more .end { font-size: 12px; color: var(--el-text-color-placeholder); }
.skeleton-list { display: flex; flex-direction: column; gap: 12px; max-width: 820px; margin: 0 auto; }
.sk-card { display: flex; gap: 12px; padding: 18px; background: #fff; border: 1px solid var(--el-border-color-light, #ebeef5); border-radius: 14px; }
.sk-main { flex: 1; display: flex; flex-direction: column; gap: 10px; }
.sk { background: linear-gradient(90deg, #eef1f5 25%, #f8fafc 37%, #eef1f5 63%); background-size: 400% 100%; animation: shimmer 1.4s ease infinite; border-radius: 6px; }
.sk-avatar { width: 40px; height: 40px; border-radius: 50%; flex: 0 0 40px; }
.sk-line { height: 13px; }
.sk-line.short { width: 36%; }
@keyframes shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
</style>
