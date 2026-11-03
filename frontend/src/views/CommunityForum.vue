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
        @keyup.enter="reload"
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

    <el-empty v-if="!loading && !posts.length" description="还没有帖子，来发第一个吧 🎉">
      <el-button type="primary" :icon="ChatLineSquare" @click="goNewPost">发第一个帖</el-button>
    </el-empty>

    <div class="post-grid" v-loading="loading" v-else>
      <div
        v-for="p in posts"
        :key="p.id"
        class="post-card"
        @click="goDetail(p.id)"
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
        <p class="card-summary">{{ p.content || '' }}</p>
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
      </div>
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
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  ChatDotRound, ChatLineSquare, Search, Star, Link, Bell, Warning, Collection,
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
const tag = ref((route.query.tag || '').trim())
const hotTags = ref([])
const circles = ref([])
const courseId = ref(parseInt(route.query.course_id, 10) || null)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const unread = ref(0)

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

const load = async () => {
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
    const data = res.data || {}
    posts.value = data.items || data.posts || []
    total.value = data.total || 0
  } catch (e) {
    console.error('加载社区帖子失败:', e)
    ElMessage.error('加载帖子失败')
  } finally {
    loading.value = false
  }
}

const reload = () => {
  page.value = 1
  load()
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
const onPage = (p) => {
  page.value = p
  load()
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

onMounted(async () => {
  await loadCategories()
  load()
  loadUnread()
  loadHotTags()
  loadCircles()
})

// 从详情页在不同关联对象间跳转时,query 变化需重新加载
watch(() => [route.query.linked_type, route.query.linked_id, route.query.tag, route.query.course_id], () => {
  tag.value = (route.query.tag || '').trim()
  courseId.value = parseInt(route.query.course_id, 10) || null
  page.value = 1
  load()
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
</style>
