<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="goBack" content="消息中心" class="back" />

    <div class="page-header">
      <div>
        <h2><el-icon :size="22" class="title-icon"><Bell /></el-icon> 消息中心</h2>
        <p class="sub-info">
          评论、回复、@提及与举报处理结果都会出现在这里
          <el-badge v-if="unread" :value="unread" class="unread-badge" />
        </p>
      </div>
      <div class="header-actions">
        <el-switch
          v-model="unreadOnly"
          active-text="只看未读"
          @change="reload"
        />
        <el-button :icon="Check" :disabled="!unread" @click="readAll">全部已读</el-button>
        <el-button :icon="ChatDotRound" @click="router.push('/community')">回到论坛</el-button>
      </div>
    </div>

    <el-empty v-if="!loading && !items.length" description="暂时没有新消息" />

    <div v-else class="notice-list">
      <div
        v-for="n in items"
        :key="n.id"
        class="notice-item"
        :class="{ unread: !n.is_read }"
        @click="openNotification(n)"
      >
        <div class="notice-icon">
          <el-icon :size="18"><component :is="typeIcon(n.type)" /></el-icon>
        </div>
        <div class="notice-main">
          <div class="notice-title">
            <span class="actor">{{ n.actor_name || '系统' }}</span>
            <span class="action">{{ n.type_label }}</span>
            <el-tag v-if="!n.is_read" size="small" type="danger" effect="plain">未读</el-tag>
          </div>
          <div v-if="n.post_title" class="notice-target">
            帖子：{{ n.post_title }}
          </div>
          <div v-if="n.content" class="notice-content">{{ n.content }}</div>
        </div>
        <div class="notice-side">
          <span class="time">{{ fmtTime(n.created_at) }}</span>
          <el-button
            v-if="!n.is_read"
            link
            size="small"
            type="primary"
            @click.stop="markRead(n)"
          >标记已读</el-button>
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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Bell, Check, ChatDotRound, ChatLineSquare, Star, Warning,
} from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()

const loading = ref(false)
const items = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const unread = ref(0)
const unreadOnly = ref(false)

const typeIcon = (type) => ({
  comment: ChatDotRound,
  reply: ChatLineSquare,
  mention: Star,
  resolve: Check,
  hidden: Warning,
  report: Warning,
}[type] || Bell)

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

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/community/notifications', {
      params: {
        page: page.value,
        per_page: pageSize.value,
        unread_only: unreadOnly.value ? 1 : 0,
      },
    })
    const data = res.data || {}
    items.value = data.items || []
    total.value = data.total || 0
    unread.value = data.unread || 0
  } catch (e) {
    console.error('加载消息失败:', e)
  } finally {
    loading.value = false
  }
}

const reload = () => {
  page.value = 1
  load()
}
const onPage = (p) => {
  page.value = p
  load()
}
const goBack = () => window.history.back()

const markRead = async (n) => {
  if (n.is_read) return
  try {
    await request.put(`/api/community/notifications/${n.id}/read`)
    n.is_read = true
    unread.value = Math.max(0, unread.value - 1)
  } catch (e) {
    console.error('标记已读失败:', e)
  }
}

const openNotification = async (n) => {
  await markRead(n)
  if (n.post_id) router.push(`/community/${n.post_id}`)
}

const readAll = async () => {
  try {
    await request.put('/api/community/notifications/read-all')
    items.value.forEach((n) => { n.is_read = true })
    unread.value = 0
    ElMessage.success('已全部标记为已读')
    if (unreadOnly.value) reload()
  } catch (e) {
    console.error('全部已读失败:', e)
  }
}

onMounted(load)
</script>

<style scoped>
.back { margin-bottom: 12px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; gap: 16px; flex-wrap: wrap; }
.page-header h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.sub-info { color: var(--el-text-color-secondary, #909399); font-size: 13px; margin: 0; display: flex; align-items: center; gap: 8px; }
.title-icon { color: #14b8a6; }
.unread-badge { margin-left: 4px; }
.header-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

.notice-list { display: flex; flex-direction: column; gap: 10px; }
.notice-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all .2s;
}
.notice-item:hover { border-color: #14b8a6; box-shadow: 0 4px 14px rgba(20, 184, 166, .1); }
.notice-item.unread { background: rgba(20, 184, 166, .05); border-color: rgba(20, 184, 166, .35); }
.notice-icon { color: #14b8a6; flex: 0 0 auto; padding-top: 2px; }
.notice-main { flex: 1; min-width: 0; }
.notice-title { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 14px; }
.notice-title .actor { font-weight: 600; color: var(--el-text-color-primary, #303133); }
.notice-title .action { color: var(--el-text-color-regular, #606266); }
.notice-target { margin-top: 4px; font-size: 13px; color: #14b8a6; }
.notice-content { margin-top: 4px; font-size: 13px; color: var(--el-text-color-secondary, #909399); word-break: break-word; }
.notice-side { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex: 0 0 auto; }
.notice-side .time { font-size: 12px; color: var(--el-text-color-secondary, #909399); white-space: nowrap; }
.pager { margin-top: 24px; justify-content: center; }
</style>
