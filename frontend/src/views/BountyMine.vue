<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Tickets /></el-icon> 我的悬赏</h2>
      </div>
    </div>

    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane label="我发布的" name="published">
        <el-empty v-if="!published.length" description="还没有发布过悬赏" />
        <el-table v-else :data="published" stripe @row-click="(r) => goDetail(r.id)">
          <el-table-column prop="title" label="标题" min-width="200">
            <template #default="{ row }">
              <span class="link">{{ row.title }}</span>
              <el-tag size="small" :type="row.bounty_type === 'question' ? 'primary' : 'success'"
                      effect="plain" style="margin-left: 8px">
                {{ row.bounty_type === 'question' ? '题目' : '答案' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reward_points" label="赏金" width="90" align="center">
            <template #default="{ row }">{{ row.reward_points }} 分</template>
          </el-table-column>
          <el-table-column label="待审核" width="90" align="center">
            <template #default="{ row }">
              <el-badge v-if="row.pending_count" :value="row.pending_count" type="danger">
                <span class="badge-cell">{{ row.submission_count }} 条</span>
              </el-badge>
              <span v-else>{{ row.submission_count }} 条</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="发布时间" width="160">
            <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="我的投稿" name="submitted">
        <el-empty v-if="!submitted.length" description="还没有投稿过" />
        <el-table v-else :data="submitted" stripe @row-click="(r) => goDetail(r.bounty_id)">
          <el-table-column prop="bounty_title" label="悬赏" min-width="200">
            <template #default="{ row }">
              <span class="link">{{ row.bounty_title }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="publisher_name" label="发布者" width="120" />
          <el-table-column prop="reward_points" label="赏金" width="90" align="center">
            <template #default="{ row }">{{ row.reward_points }} 分</template>
          </el-table-column>
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="subStatusTag(row.status)">{{ subStatusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="投稿时间" width="160">
            <template #default="{ row }">{{ row.created_at?.slice(0, 16) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Tickets } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()
const tab = ref('published')
const published = ref([])
const submitted = ref([])

const statusText = (s) => ({ open: '征集中', closed: '已采纳', expired: '已过期' }[s] || s)
const statusTag = (s) => ({ open: 'warning', closed: 'success', expired: 'info' }[s] || 'info')
const subStatusText = (s) => ({ pending: '待审核', accepted: '已采纳', rejected: '已拒绝' }[s] || s)
const subStatusTag = (s) => ({ pending: 'warning', accepted: 'success', rejected: 'danger' }[s] || 'info')

const goDetail = (id) => router.push(`/bounties/${id}`)

const load = async () => {
  if (tab.value === 'published') {
    const res = await request.get('/api/bounties/mine')
    published.value = res.data || []
  } else {
    const res = await request.get('/api/bounties/my-submissions')
    submitted.value = res.data || []
  }
}

onMounted(load)
</script>

<style scoped>
.link { color: var(--el-color-primary, #409eff); cursor: pointer; }
.link:hover { text-decoration: underline; }
.badge-cell { padding: 0 12px; }
:deep(.el-table__row) { cursor: pointer; }
</style>
