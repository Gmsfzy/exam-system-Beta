<template>
  <div class="page-wrapper" v-loading="loading">
    <div class="page-header">
      <div>
        <h2><el-icon :size="24" class="title-icon"><Setting /></el-icon> 社区管理</h2>
        <p class="sub-info">帖子 / 评论治理 · 折叠与恢复 · 违规删除</p>
      </div>
      <el-button :icon="Warning" type="warning" plain @click="router.push('/community/reports')">
        举报队列
      </el-button>
    </div>

    <div class="stat-grid">
      <div v-for="s in statCards" :key="s.key" class="stat-card">
        <span class="num">{{ stats[s.key] ?? 0 }}</span>
        <span class="label">{{ s.label }}</span>
      </div>
    </div>

    <div class="toolbar">
      <el-radio-group v-model="tab" @change="reload">
        <el-radio-button value="posts">帖子管理</el-radio-button>
        <el-radio-button value="comments">评论管理</el-radio-button>
      </el-radio-group>
      <el-select v-model="status" style="width: 150px" @change="reload">
        <el-option label="全部状态" value="all" />
        <el-option label="正常" value="normal" />
        <el-option label="已折叠" value="hidden" />
        <el-option label="已删除" value="deleted" />
        <el-option v-if="tab === 'posts'" label="已解决" value="resolved" />
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

    <el-empty v-if="!loading && !items.length" description="没有匹配的内容" />

    <el-table v-else :data="items" border stripe class="admin-table">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column v-if="tab === 'posts'" label="标题" min-width="220">
        <template #default="{ row }">
          <span class="link-text" @click="router.push(`/community/${row.id}`)">{{ row.title }}</span>
        </template>
      </el-table-column>
      <el-table-column v-else label="评论内容" min-width="240">
        <template #default="{ row }">
          <span class="content-text">{{ row.content }}</span>
          <div v-if="row.post_title" class="sub-text">帖子：{{ row.post_title }}</div>
        </template>
      </el-table-column>
      <el-table-column label="作者" width="150">
        <template #default="{ row }">
          {{ row.author_username || row.display_username || row.display_anon || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="150">
        <template #default="{ row }">
          <el-tag v-if="row.deleted" size="small" type="danger">已删除</el-tag>
          <el-tag v-else-if="row.hidden" size="small" type="info">已折叠</el-tag>
          <el-tag v-else size="small" type="success">正常</el-tag>
          <el-tag v-if="tab === 'posts' && row.is_resolved" size="small" type="success" effect="plain" class="ml4">已解决</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="举报" width="80">
        <template #default="{ row }">{{ row.report_count || 0 }}</template>
      </el-table-column>
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <template v-if="!row.deleted">
            <el-button
              size="small"
              :type="row.hidden ? 'success' : 'warning'"
              plain
              @click="toggleVisibility(row)"
            >{{ row.hidden ? '恢复' : '折叠' }}</el-button>
            <el-popconfirm title="确认删除该内容？" @confirm="removeItem(row)">
              <template #reference>
                <el-button size="small" type="danger" plain>删除</el-button>
              </template>
            </el-popconfirm>
          </template>
          <span v-else class="sub-text">不可操作</span>
        </template>
      </el-table-column>
    </el-table>

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
import { Setting, Warning, Search } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()

const loading = ref(false)
const tab = ref('posts')
const status = ref('all')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const items = ref([])
const stats = ref({})

const statCards = [
  { key: 'total_posts', label: '帖子总数' },
  { key: 'total_comments', label: '评论总数' },
  { key: 'today_posts', label: '今日新帖' },
  { key: 'active_authors', label: '活跃作者' },
  { key: 'resolved_posts', label: '已解决' },
  { key: 'hidden_posts', label: '折叠帖子' },
  { key: 'hidden_comments', label: '折叠评论' },
  { key: 'pending_reports', label: '待处理举报' },
]

const fmtTime = (s) => (s ? new Date(s).toISOString().slice(0, 16).replace('T', ' ') : '')

const loadStats = async () => {
  try {
    const res = await request.get('/api/community/admin/stats')
    stats.value = res.data || {}
  } catch {
    stats.value = {}
  }
}

const load = async () => {
  loading.value = true
  try {
    const params = { page: page.value, per_page: pageSize.value, status: status.value }
    if (keyword.value.trim()) params.q = keyword.value.trim()
    const url = tab.value === 'posts'
      ? '/api/community/admin/posts'
      : '/api/community/admin/comments'
    const res = await request.get(url, { params })
    const data = res.data || {}
    items.value = data.items || []
    total.value = data.total || 0
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

const toggleVisibility = async (row) => {
  const hidden = !row.hidden
  try {
    const url = tab.value === 'posts'
      ? `/api/community/admin/posts/${row.id}/visibility`
      : `/api/community/admin/comments/${row.id}/visibility`
    await request.put(url, { hidden })
    row.hidden = hidden
    ElMessage.success(hidden ? '已折叠' : '已恢复')
    loadStats()
  } catch (e) {
    // request 拦截器已提示
  }
}

const removeItem = async (row) => {
  try {
    if (tab.value === 'posts') {
      await request.delete(`/api/community/posts/${row.id}`)
    } else {
      await request.delete(`/api/community/comments/${row.id}`)
    }
    ElMessage.success('已删除')
    load()
    loadStats()
  } catch (e) {
    // request 拦截器已提示
  }
}

onMounted(() => {
  loadStats()
  load()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
  gap: 16px;
  flex-wrap: wrap;
}
.page-header h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.title-icon { color: #14b8a6; }
.sub-info { margin: 0; font-size: 13px; color: var(--el-text-color-secondary, #909399); }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.stat-card {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 10px;
  padding: 16px;
  text-align: center;
}
.stat-card .num { display: block; font-size: 22px; font-weight: 600; color: #14b8a6; }
.stat-card .label { font-size: 12px; color: var(--el-text-color-secondary, #909399); }

.toolbar { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; align-items: center; }

.admin-table { width: 100%; }
.link-text { color: #14b8a6; cursor: pointer; }
.link-text:hover { text-decoration: underline; }
.content-text { word-break: break-word; }
.sub-text { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.ml4 { margin-left: 4px; }

.pager { margin-top: 20px; justify-content: center; }
</style>
