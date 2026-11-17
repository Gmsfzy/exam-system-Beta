<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><ChatDotRound /></el-icon> 社区中心</h2>
        <p><span class="sub-info">论坛讨论 · 经验共创 · 匿名保护 · 关联题目/作业/考试自动反向聚合</span></p>
      </div>
      <div class="header-actions">
        <el-badge v-if="isLoggedIn" :value="unread" :hidden="!unread" class="msg-badge">
          <el-button :icon="Bell" @click="goNotifications">消息中心</el-button>
        </el-badge>
        <el-button v-if="isLoggedIn" :icon="Star" @click="router.push('/community/favorites')">
          我的收藏
        </el-button>
        <el-button
          v-if="isTeacherOrAdmin"
          type="warning"
          plain
          :icon="Warning"
          @click="router.push('/community/reports')"
        >举报管理</el-button>
        <el-button type="primary" :icon="ChatLineSquare" @click="goNewPost">
          发帖讨论
        </el-button>
      </div>
    </div>

    <!-- Task 8: 关联过滤提示条(从题目/作业/考试详情页跳入时显示) -->
    <el-alert
      v-if="linkedType && linkedId"
      type="success"
      :closable="false"
      class="linked-banner"
    >
      <template #title>
        正在查看关联 {{ linkedLabel(linkedType) }} #{{ linkedId }} 的讨论
        <el-button size="small" text type="primary" @click="clearLinked">查看全部帖子</el-button>
      </template>
    </el-alert>

    <!-- 分类 Tab -->
    <el-tabs v-model="category" @tab-change="reload" class="cat-tabs">
      <el-tab-pane label="全部" name="" />
      <el-tab-pane
        v-for="c in categories"
        :key="c.key"
        :label="c.name"
        :name="c.key"
      />
    </el-tabs>

    <div class="filters">
      <el-radio-group v-model="sort" @change="reload" size="default">
        <el-radio-button value="new">最新</el-radio-button>
        <el-radio-button value="hot">热门</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="resolved" @change="reload" size="default">
        <el-radio-button value="">全部状态</el-radio-button>
        <el-radio-button value="1">已解决</el-radio-button>
        <el-radio-button value="0">未解决</el-radio-button>
      </el-radio-group>
      <el-select
        v-model="courseId"
        placeholder="全部圈子"
        clearable
        filterable
        style="width: 220px"
        @change="reload"
      >
        <el-option
          v-for="c in circles"
          :key="c.course_id"
          :label="`${c.name}（${c.post_count} 帖）`"
          :value="c.course_id"
        />
      </el-select>
      <el-input
        v-model="keyword"
        placeholder="搜索标题或正文…"
        clearable
        :prefix-icon="Search"
        style="max-width: 280px"
        @keyup.enter="onSearchEnter"
        @clear="reload"
      />
    </div>

    <!-- 热门标签 -->
    <div v-if="hotTags.length" class="tag-bar">
      <span class="tag-bar-label">热门标签：</span>
      <el-check-tag
        v-for="t in hotTags"
        :key="t.tag"
        :checked="tag === t.tag"
        class="hot-tag"
        @change="toggleTag(t.tag)"
      >#{{ t.tag }} <span class="tag-count">{{ t.count }}</span></el-check-tag>
    </div>

    <!-- 空态区分：筛选无结果 与 社区还没有帖子是两件事 -->
    <el-empty
      v-if="!loading && !posts.length && hasActiveFilter"
      :image-size="90"
      description="没有匹配的帖子，换个筛选条件试试"
    >
      <el-button :icon="RefreshLeft" @click="resetFilters">清空筛选</el-button>
    </el-empty>
    <el-empty
      v-else-if="!loading && !posts.length"
      :image-size="90"
      description="还没有帖子，来发第一个吧"
    >
      <el-button type="primary" :icon="ChatLineSquare" @click="goNewPost">发第一个帖</el-button>
    </el-empty>

    <!-- 首屏骨架：避免加载时一片空白 -->
    <div v-else-if="loading && !posts.length" class="post-grid">
      <div v-for="n in 6" :key="`sk-${n}`" class="post-card skeleton-card" aria-hidden="true">
        <div class="sk sk-tag"></div>
        <div class="sk sk-title"></div>
        <div class="sk sk-line"></div>
        <div class="sk sk-line short"></div>
      </div>
    </div>

    <div class="post-grid" v-else v-loading="loading" :aria-busy="loading">
      <article
        v-for="p in posts"
        :key="p.id"
        class="post-card"
        role="button"
        tabindex="0"
        :aria-label="`查看帖子：${p.title}`"
        @click="goDetail(p.id)"
        @keydown.enter.prevent="goDetail(p.id)"
        @keydown.space.prevent="goDetail(p.id)"
      >
        <div class="card-top">
          <el-tag size="small" :type="catTagType(p.category)" effect="light">
            {{ catName(p.category) }}
          </el-tag>
          <el-tag v-if="p.course_name" size="small" type="primary" effect="plain">
            👥 {{ p.course_name }}
          </el-tag>
          <el-tag v-if="p.bounty_points" size="small" type="danger" effect="dark">
            悬赏 {{ p.bounty_points }} 分{{ p.bounty_rewarded ? '（已发放）' : '' }}
          </el-tag>
          <el-tag v-if="p.is_anonymous" size="small" type="info" effect="plain">🫥 匿名</el-tag>
          <el-tag v-if="p.is_resolved" size="small" type="success" effect="dark">已解决</el-tag>
          <el-tag v-if="p.hidden" size="small" type="info" effect="plain">已折叠</el-tag>
        </div>
        <h3 class="card-title">{{ p.title }}</h3>
        <div v-if="p.tags && p.tags.length" class="card-tags">
          <el-tag
            v-for="t in p.tags"
            :key="t"
            size="small"
            type="info"
            effect="plain"
            class="card-tag"
            @click.stop="toggleTag(t)"
          >#{{ t }}</el-tag>
        </div>
        <p class="card-summary">{{ summaryOf(p) }}</p>
        <div v-if="p.linked_type" class="card-linked">
          <el-tag size="small" type="warning" effect="plain" class="linked-tag">
            <el-icon><Link /></el-icon>
            关联：{{ linkedLabel(p.linked_type) }}#{{ p.linked_id }}
          </el-tag>
        </div>
        <div class="card-meta">
          <span class="author">
            {{ p.is_anonymous ? (p.display_anon || '匿名用户') : (p.display_username || p.username) }}
          </span>
          <span class="dot">·</span>
          <span>{{ fmtTime(p.created_at) }}</span>
          <span class="spacer"></span>
          <span><el-icon><Star /></el-icon> {{ p.like_count || 0 }}</span>
          <span><el-icon><ChatDotRound /></el-icon> {{ p.comment_count || 0 }}</span>
          <span><el-icon><Collection /></el-icon> {{ p.favorite_count || 0 }}</span>
        </div>
      </article>
    </div>

    <el-pagination
      v-if="total > pageSize"
      class="pager"
      background
      layout="prev, pager, next, total"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      @current-change="onPage"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  ChatDotRound, ChatLineSquare, Search, Star, Link, Bell, Warning, Collection, RefreshLeft,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const isLoggedIn = computed(() => !!auth.token)
const isTeacherOrAdmin = computed(() => ['teacher', 'admin'].includes(auth.user?.role))

// Task 8 轻联动:从题目/作业/考试详情页跳进来的关联过滤
const linkedType = computed(() => (route.query.linked_type || '').trim())
const linkedId = computed(() => parseInt(route.query.linked_id, 10) || null)
const linkedLabel = (t) => ({ question: '题目', homework: '作业', exam: '考试' }[t] || t)
const clearLinked = () => router.push('/community')

const loading = ref(false)
const posts = ref([])
const categories = ref([])
const category = ref('')
const sort = ref('new')
const resolved = ref('')
const keyword = ref('')
const tag = ref('')
const hotTags = ref([])
const circles = ref([])
const courseId = ref(null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const unread = ref(0)

const hasActiveFilter = computed(() => !!(
  category.value || keyword.value.trim() || tag.value || courseId.value ||
  resolved.value !== '' || sort.value !== 'new' || (linkedType.value && linkedId.value)
))

// ── 地址栏同步：筛选条件写入 query，刷新 / 分享 / 从详情页返回都不丢状态 ──
let appliedQ = '' // 已生效的搜索词，用来区分“用户输入”与“地址栏回填”

const normalize = (obj) => JSON.stringify(
  Object.keys(obj).sort().reduce((acc, k) => {
    if (obj[k] !== '' && obj[k] != null) acc[k] = String(obj[k])
    return acc
  }, {})
)

const buildQuery = () => {
  const q = {}
  if (category.value) q.category = category.value
  if (sort.value === 'hot') q.sort = 'hot'
  if (resolved.value !== '') q.resolved = resolved.value
  if (keyword.value.trim()) q.q = keyword.value.trim()
  if (tag.value) q.tag = tag.value
  if (courseId.value) q.course_id = String(courseId.value)
  if (page.value > 1) q.page = String(page.value)
  if (linkedType.value && linkedId.value) {
    q.linked_type = linkedType.value
    q.linked_id = String(linkedId.value)
  }
  return q
}

const applyRouteQuery = () => {
  const q = route.query || {}
  category.value = (q.category || '').trim()
  sort.value = q.sort === 'hot' ? 'hot' : 'new'
  resolved.value = ['1', '0'].includes(q.resolved) ? q.resolved : ''
  keyword.value = (q.q || '').trim()
  appliedQ = keyword.value
  tag.value = (q.tag || '').trim()
  courseId.value = parseInt(q.course_id, 10) || null
  page.value = Math.max(1, parseInt(q.page, 10) || 1)
}

const syncQuery = () => {
  const next = buildQuery()
  appliedQ = keyword.value.trim()
  if (normalize(next) === normalize(route.query || {})) return
  router.replace({ path: '/community', query: next })
}

applyRouteQuery()

const DEFAULT_CATEGORIES = [
  { key: 'discussion', name: '错题讨论' },
  { key: 'solution', name: '解法分享' },
  { key: 'help', name: '求助答疑' },
  { key: 'experience', name: '经验交流' },
  { key: 'resource', name: '资源下载' },
  { key: 'other', name: '其他' },
]

const catTagType = (k) => ({
  discussion: 'danger',
  solution: 'success',
  help: 'warning',
  experience: 'primary',
  resource: '',
  other: 'info',
}[k] || 'info')

const catName = (k) => {
  const c = categories.value.find((c) => c.key === k)
  return c?.name || k
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
    return d.toISOString().slice(0, 10)
  } catch {
    return s
  }
}

// 摘要：去掉 Markdown 标记并截断，避免把整篇正文（最多 5000 字）塞进列表 DOM
const summaryOf = (p) => {
  const raw = (p?.content || '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '[图片]')
    .replace(/```[\s\S]*?```/g, '[代码]')
    .replace(/[#>*`~]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return raw.length > 140 ? `${raw.slice(0, 140)}…` : raw
}

const loadCategories = async () => {
  try {
    const res = await request.get('/api/community/categories')
    const data = res.data
    if (Array.isArray(data) && data.length) {
      // 后端返回 [{value, label}],映射为前端 {key, name}
      categories.value = data.map((c) => ({ key: c.value, name: c.label }))
    } else {
      categories.value = DEFAULT_CATEGORIES
    }
  } catch {
    categories.value = DEFAULT_CATEGORIES
  }
}

// 请求竞态守卫：只接受最后一次请求的结果，避免快速切换筛选时旧响应覆盖新响应
let loadSeq = 0

const load = async () => {
  const seq = ++loadSeq
  loading.value = true
  try {
    const params = { page: page.value, per_page: pageSize.value, sort: sort.value }
    if (category.value) params.category = category.value
    if (keyword.value.trim()) params.q = keyword.value.trim()
    if (tag.value) params.tag = tag.value
    if (courseId.value) params.course_id = courseId.value
    if (resolved.value !== '') params.resolved = resolved.value
    // Task 8 轻联动:?linked_type=question&linked_id=123 过滤关联讨论
    if (linkedType.value && linkedId.value) {
      params.linked_type = linkedType.value
      params.linked_id = linkedId.value
    }
    const res = await request.get('/api/community/posts', { params })
    if (seq !== loadSeq) return
    const data = res.data || {}
    posts.value = data.items || data.posts || []
    total.value = data.total || 0
  } catch (e) {
    if (seq !== loadSeq) return
    console.error('加载社区帖子失败:', e)
    ElMessage.error('加载帖子失败')
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

// 筛选变化：回到第一页、写回地址栏、再请求
const reload = () => {
  page.value = 1
  syncQuery()
  load()
}

const onPage = (p) => {
  if (p === page.value) return
  page.value = p
  syncQuery()
  load()
}

const resetFilters = () => {
  category.value = ''
  sort.value = 'new'
  resolved.value = ''
  keyword.value = ''
  tag.value = ''
  courseId.value = null
  page.value = 1
  appliedQ = ''
  router.replace({ path: '/community' })
  load()
}

// 搜索防抖：停顿 350ms 自动搜索，回车立即搜索
let searchTimer = null
watch(keyword, (val) => {
  if (val.trim() === appliedQ) return // 由地址栏回填/重置触发，跳过
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => reload(), 350)
})
const onSearchEnter = () => {
  clearTimeout(searchTimer)
  reload()
}

const loadHotTags = async () => {
  try {
    const res = await request.get('/api/community/tags')
    hotTags.value = Array.isArray(res.data) ? res.data : []
  } catch {
    hotTags.value = []
  }
}

const loadCircles = async () => {
  try {
    const res = await request.get('/api/community/circles')
    circles.value = res.data?.items || []
  } catch {
    circles.value = []
  }
}

const toggleTag = (t) => {
  tag.value = tag.value === t ? '' : t
  reload()
}

const goDetail = (id) => router.push(`/community/${id}`)
const goNewPost = () => router.push('/community/new')
const goNotifications = () => router.push('/community/notifications')

const loadUnread = async () => {
  if (!isLoggedIn.value) return
  try {
    const res = await request.get('/api/community/notifications/unread-count')
    unread.value = (res.data || {}).unread || 0
  } catch {
    unread.value = 0
  }
}

// 未读角标轮询：仅页面可见时刷新，切到后台不打扰
let unreadTimer = null
const startUnreadPolling = () => {
  if (!isLoggedIn.value) return
  unreadTimer = setInterval(() => {
    if (document.visibilityState === 'visible') loadUnread()
  }, 60000)
}

onMounted(async () => {
  await loadCategories()
  load()
  loadUnread()
  loadHotTags()
  loadCircles()
  startUnreadPolling()
})

// 地址栏变化（前进/后退/外部跳转）时恢复筛选并重新加载
watch(() => route.fullPath, () => {
  if (route.path !== '/community') return
  const before = normalize(buildQuery())
  applyRouteQuery()
  if (normalize(buildQuery()) !== before) load()
})

onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  clearInterval(unreadTimer)
})
</script>

<style scoped>
.linked-banner { margin-bottom: 14px; }
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
  gap: 16px;
  flex-wrap: wrap;
}
.header-title h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.sub-info { color: var(--el-text-color-secondary, #909399); font-size: 13px; margin: 0; }
.title-icon { color: #14b8a6; }
.header-actions { display: flex; gap: 8px; }

.cat-tabs { margin-bottom: 4px; }

.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
  align-items: center;
}

.post-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
  min-height: 120px;
}

.tag-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 18px;
}
.tag-bar-label { font-size: 13px; color: var(--el-text-color-secondary, #909399); }
.hot-tag { margin-right: 2px; }
.tag-count { opacity: .6; font-size: 12px; }
.card-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.card-tag { cursor: pointer; }

.post-card {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.25s;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.post-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(20, 184, 166, 0.12);
  border-color: #14b8a6;
}
.post-card:focus-visible {
  outline: 2px solid #14b8a6;
  outline-offset: 2px;
}

.card-top { display: flex; gap: 6px; align-items: center; }
.card-title { font-size: 16px; font-weight: 600; line-height: 1.4; margin: 0; color: var(--el-text-color-primary, #303133); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-summary {
  font-size: 13px;
  color: var(--el-text-color-secondary, #909399);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 42px;
  line-height: 1.6;
}
.card-linked .linked-tag { font-size: 12px; }
.card-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  border-top: 1px dashed var(--el-border-color-lighter, #ebeef5);
  padding-top: 10px;
  margin-top: auto;
}
.card-meta .author { font-weight: 500; color: var(--el-text-color-primary, #303133); }
.card-meta .spacer { flex: 1; }
.card-meta .el-icon { margin-right: 2px; }

.pager { margin-top: 24px; justify-content: center; }

/* 首屏骨架 */
.skeleton-card { pointer-events: none; }
.sk {
  border-radius: 6px;
  background: linear-gradient(90deg, rgba(0,0,0,.06) 25%, rgba(0,0,0,.10) 37%, rgba(0,0,0,.06) 63%);
  background-size: 400% 100%;
  animation: sk-shimmer 1.4s ease infinite;
}
.sk-tag { width: 64px; height: 20px; }
.sk-title { width: 78%; height: 20px; margin-top: 4px; }
.sk-line { width: 100%; height: 12px; }
.sk-line.short { width: 62%; }
@keyframes sk-shimmer {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}
@media (prefers-reduced-motion: reduce) {
  .sk { animation: none; background: rgba(0,0,0,.07); }
}

/* 小屏：单列卡片，筛选控件占满整行 */
@media (max-width: 640px) {
  .post-grid { grid-template-columns: 1fr; gap: 12px; }
  .header-actions { flex-wrap: wrap; }
  .filters { gap: 8px; }
  .filters :deep(.el-select),
  .filters :deep(.el-input) { width: 100% !important; max-width: 100% !important; }
  .post-card { padding: 14px; }
}
</style>
