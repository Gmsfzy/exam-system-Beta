<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="goBack" content="举报管理" class="back" />

    <div class="page-header">
      <div>
        <h2><el-icon :size="22" class="title-icon"><Warning /></el-icon> 举报管理</h2>
        <p class="sub-info">待处理举报达到 3 条会自动折叠内容，处理后会解除或删除</p>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-tabs v-model="status" @tab-change="reload" class="status-tabs">
      <el-tab-pane label="待处理" name="pending" />
      <el-tab-pane label="已处理" name="handled" />
      <el-tab-pane label="已驳回" name="dismissed" />
    </el-tabs>

    <el-empty v-if="!loading && !items.length" :description="emptyText" />

    <div v-else class="report-list">
      <div v-for="r in items" :key="r.id" class="report-card">
        <div class="card-head">
          <el-tag size="small" :type="r.target_type === 'post' ? 'primary' : 'warning'" effect="light">
            {{ targetLabel(r.target_type) }} #{{ r.target_id }}
          </el-tag>
          <el-tag v-if="r.target_deleted" size="small" type="danger" effect="plain">内容已删除</el-tag>
          <el-tag v-if="r.target_hidden" size="small" type="info" effect="plain">已折叠</el-tag>
          <el-tag size="small" :type="statusTag(r.status)" effect="plain">{{ statusLabel(r.status) }}</el-tag>
          <span class="spacer"></span>
          <span class="time">{{ fmtTime(r.created_at) }}</span>
        </div>

        <div class="target-box">
          <div v-if="r.target_title" class="target-title">{{ r.target_title }}</div>
          <div class="target-content">{{ r.target_content || '（内容为空或已被删除）' }}</div>
        </div>

        <div class="report-meta">
          <span>举报人：<b>{{ r.reporter_name || '未知用户' }}</b></span>
          <span>理由：{{ r.reason }}</span>
        </div>

        <div class="card-actions">
          <el-button
            v-if="r.target_type === 'dm_message'"
            size="small"
            :icon="View"
            @click="openContext(r)"
          >查看私信上下文</el-button>
          <el-button
            v-else
            size="small"
            :icon="Link"
            @click="goTarget(r)"
          >查看内容</el-button>
          <template v-if="r.status === 'pending'">
            <el-button size="small" type="success" plain @click="handle(r, 'dismiss')">驳回举报</el-button>
            <el-button size="small" type="danger" plain @click="handle(r, 'remove')">
              {{ r.target_type === 'dm_message' ? '标记违规' : '删除内容' }}
            </el-button>
          </template>
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

    <el-dialog v-model="contextVisible" title="私信上下文（最近 50 条）" width="680px">
      <div v-loading="contextLoading" class="context-body">
        <template v-if="contextData">
          <div class="context-meta">
            <span>参与者：</span>
            <el-tag v-for="p in contextData.participants" :key="p.id" size="small" effect="plain">
              {{ p.username }}
            </el-tag>
            <el-tag size="small" type="warning" effect="plain">查看留痕 #{{ contextData.access_log_id }}</el-tag>
          </div>
          <div class="context-list">
            <div v-for="m in contextData.messages" :key="m.id" class="ctx-msg">
              <span class="ctx-sender">{{ senderName(m.sender_id) }}：</span>
              <span class="ctx-text">{{ m.recalled ? '［已撤回］' : m.content }}</span>
              <span class="ctx-time">{{ fmtTime(m.created_at) }}</span>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="contextVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Warning, Refresh, Link, View } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()

const loading = ref(false)
const items = ref([])
const status = ref('pending')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const contextVisible = ref(false)
const contextLoading = ref(false)
const contextData = ref(null)

const TARGET_LABELS = {
  post: '帖子',
  comment: '评论',
  moment: '动态',
  mcomment: '动态评论',
  dm_message: '私信',
}
const targetLabel = (t) => TARGET_LABELS[t] || t
const senderName = (id) => {
  const p = (contextData.value?.participants || []).find((x) => x.id === id)
  return p ? p.username : `用户 #${id}`
}

const emptyText = computed(() => ({
  pending: '没有待处理的举报',
  handled: '还没有已处理的举报',
  dismissed: '还没有被驳回的举报',
}[status.value] || '暂无数据'))

const statusLabel = (s) => ({ pending: '待处理', handled: '已处理', dismissed: '已驳回' }[s] || s)
const statusTag = (s) => ({ pending: 'warning', handled: 'success', dismissed: 'info' }[s] || 'info')

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
    const res = await request.get('/api/community/reports', {
      params: { status: status.value, page: page.value, per_page: pageSize.value },
    })
    const data = res.data || {}
    items.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    console.error('加载举报失败:', e)
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

const goTarget = (r) => {
  if (r.target_type === 'post') {
    router.push(`/community/${r.target_id}`)
  } else if (r.target_type === 'moment') {
    router.push(`/community/moment/${r.target_id}`)
  } else if (r.target_type === 'mcomment') {
    if (r.target_moment_id) router.push(`/community/moment/${r.target_moment_id}`)
    else ElMessage.info('该评论所属动态不可用')
  } else if (r.target_post_id) {
    router.push(`/community/${r.target_post_id}`)
  } else {
    ElMessage.info('该评论所属帖子不可用')
  }
}

const openContext = async (r) => {
  if (!r.target_conversation_id) {
    ElMessage.warning('该私信会话不可用')
    return
  }
  contextVisible.value = true
  contextLoading.value = true
  contextData.value = null
  try {
    const res = await request.get(
      `/api/community/dm/conversations/${r.target_conversation_id}/context`,
      { params: { report_id: r.id } },
    )
    contextData.value = res.data
  } catch (e) {
    contextVisible.value = false
  } finally {
    contextLoading.value = false
  }
}

const handle = async (r, action) => {
  if (action === 'remove') {
    try {
      await ElMessageBox.confirm(
        r.target_type === 'dm_message'
          ? '私信原文将按合规要求留存，仅标记该举报为违规并通知发送者，确认？'
          : '删除后该内容将不再展示，确认删除？',
        r.target_type === 'dm_message' ? '标记违规' : '删除举报内容',
        { type: 'warning', confirmButtonText: '确认' }
      )
    } catch {
      return
    }
  }
  try {
    await request.put(`/api/community/reports/${r.id}`, { action })
    ElMessage.success(action === 'remove'
      ? (r.target_type === 'dm_message' ? '已标记违规' : '内容已删除')
      : '举报已驳回')
    items.value = items.value.filter((x) => x.id !== r.id)
    total.value = Math.max(0, total.value - 1)
  } catch (e) {
    console.error('处理举报失败:', e)
  }
}

onMounted(load)
</script>

<style scoped>
.back { margin-bottom: 12px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 16px; flex-wrap: wrap; }
.page-header h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.sub-info { color: var(--el-text-color-secondary, #909399); font-size: 13px; margin: 0; }
.title-icon { color: #e6a23c; }
.status-tabs { margin-bottom: 6px; }

.report-list { display: flex; flex-direction: column; gap: 12px; }
.report-card {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.card-head .spacer { flex: 1; }
.card-head .time { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.target-box { background: rgba(0, 0, 0, .025); border-radius: 8px; padding: 10px 12px; }
.target-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.target-content { font-size: 13px; color: var(--el-text-color-secondary, #909399); line-height: 1.6; word-break: break-word; }
.report-meta { display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px; color: var(--el-text-color-regular, #606266); }
.report-meta b { color: var(--el-text-color-primary, #303133); }
.card-actions { display: flex; gap: 8px; justify-content: flex-end; }
.pager { margin-top: 24px; justify-content: center; }
.context-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; font-size: 13px; }
.context-list { max-height: 420px; overflow-y: auto; border: 1px solid var(--el-border-color-lighter, #f0f2f5); border-radius: 10px; padding: 10px 12px; }
.ctx-msg { padding: 6px 0; border-bottom: 1px dashed var(--el-border-color-lighter, #f2f3f5); font-size: 13px; line-height: 1.6; }
.ctx-msg:last-child { border-bottom: none; }
.ctx-sender { font-weight: 600; color: #0f766e; }
.ctx-text { white-space: pre-wrap; word-break: break-word; }
.ctx-time { margin-left: 8px; font-size: 11px; color: var(--el-text-color-secondary); }
</style>
