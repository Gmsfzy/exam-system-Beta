<template>
  <div class="gov-page">
    <div class="page-head">
      <h2>🛡️ AI 用量治理</h2>
      <div class="head-right">
        <el-select v-model="days" style="width: 120px" @change="loadSummary">
          <el-option :value="7" label="近 7 天" /><el-option :value="14" label="近 14 天" /><el-option :value="30" label="近 30 天" />
        </el-select>
      </div>
    </div>

    <el-row :gutter="12" class="stat-row">
      <el-col :span="6"><div class="stat-card"><div class="num">{{ summary.total_calls ?? '-' }}</div><div class="lbl">总调用次数</div></div></el-col>
      <el-col :span="6"><div class="stat-card ok"><div class="num">{{ sumStatus('success') }}</div><div class="lbl">成功</div></div></el-col>
      <el-col :span="6"><div class="stat-card warn"><div class="num">{{ sumStatus('degraded') }}</div><div class="lbl">降级（AI 不可用）</div></div></el-col>
      <el-col :span="6"><div class="stat-card bad"><div class="num">{{ sumStatus('fail') }}</div><div class="lbl">失败</div></div></el-col>
    </el-row>

    <div class="gov-grid">
      <div class="panel">
        <h3>每日用量</h3>
        <el-table :data="summary.per_day || []" size="small" max-height="300">
          <el-table-column prop="day" label="日期" width="110" />
          <el-table-column prop="total" label="调用" width="70" />
          <el-table-column label="成/降/败" width="110">
            <template #default="{ row }">
              <span class="c-ok">{{ row.success }}</span> / <span class="c-warn">{{ row.degraded }}</span> / <span class="c-bad">{{ row.fail }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="avg_cost_ms" label="均耗时(ms)" align="right" />
        </el-table>
      </div>
      <div class="panel">
        <h3>额度占用 TOP（默认学生 30 次/天，教师不限量）</h3>
        <el-table :data="summary.top_users || []" size="small" max-height="300">
          <el-table-column prop="username" label="用户" min-width="100" />
          <el-table-column prop="calls" label="期内调用" width="90" />
          <el-table-column label="当前上限" width="150" align="center">
            <template #default="{ row }">
              <el-input-number v-model="row._limit" size="small" :min="0" :max="1000" controls-position="right" style="width: 100px" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="saveQuota(row)">保存</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="panel">
      <h3>调用日志明细</h3>
      <div class="log-filters">
        <el-input v-model="logAction" placeholder="按动作筛选，如 chat / material" clearable style="width: 220px" @keyup.enter="loadLogs(1)" @clear="loadLogs(1)" />
        <el-button size="small" @click="loadLogs(1)">查询</el-button>
      </div>
      <el-table :data="logs" size="small">
        <el-table-column prop="created_at" label="时间" width="160" :formatter="row => (row.created_at || '').replace('T', ' ').slice(0, 19)" />
        <el-table-column prop="user" label="用户" width="120" />
        <el-table-column prop="action" label="动作" min-width="130" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_TAG[row.status] || 'info'" effect="plain">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="cost_ms" label="耗时(ms)" width="90" align="right" />
      </el-table>
      <el-pagination class="pager" layout="prev, pager, next, total" :total="logTotal"
                     :page-size="logSize" :current-page="logPage" @current-change="loadLogs" />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const days = ref(14)
const summary = reactive({ per_day: [], top_users: [], total_calls: 0 })
const logs = ref([])
const logPage = ref(1)
const logSize = 20
const logTotal = ref(0)
const logAction = ref('')
const STATUS_TAG = { success: 'success', degraded: 'warning', fail: 'danger' }

function sumStatus(s) {
  return (summary.per_day || []).reduce((acc, d) => acc + (d[s] || 0), 0)
}

async function loadSummary() {
  try {
    const { data } = await request.get('/api/learning/ai-governance/summary', { params: { days: days.value } })
    Object.assign(summary, { per_day: data.per_day || [], total_calls: data.total_calls || 0,
      top_users: (data.top_users || []).map(u => ({ ...u, _limit: u.daily_limit })) })
  } catch (e) { /* 拦截器提示 */ }
}

async function saveQuota(row) {
  try {
    await request.put(`/api/learning/ai-governance/quota/${row.user_id}`, { daily_limit: row._limit })
    ElMessage.success(`已把 ${row.username} 的每日上限设为 ${row._limit}`)
  } catch (e) { /* 拦截器提示 */ }
}

async function loadLogs(page) {
  logPage.value = page || 1
  try {
    const { data } = await request.get('/api/learning/ai-governance/logs', {
      params: { page: logPage.value, size: logSize, action: logAction.value || undefined }
    })
    logs.value = data.items || []
    logTotal.value = data.total || 0
  } catch (e) { /* 拦截器提示 */ }
}

onMounted(() => { loadSummary(); loadLogs(1) })
</script>

<style scoped>
.gov-page { padding: 4px; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.page-head h2 { margin: 0; }
.stat-row { margin-bottom: 12px; }
.stat-card { background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 10px; padding: 14px; text-align: center; }
.stat-card .num { font-size: 24px; font-weight: 700; }
.stat-card .lbl { color: #909399; font-size: 12px; margin-top: 2px; }
.stat-card.ok .num { color: #67c23a; } .stat-card.warn .num { color: #e6a23c; } .stat-card.bad .num { color: #f56c6c; }
.gov-grid { display: grid; grid-template-columns: 1fr 1.2fr; gap: 12px; margin-bottom: 12px; }
.panel { background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 10px; padding: 14px; margin-bottom: 12px; }
.panel h3 { margin: 0 0 10px; font-size: 15px; }
.c-ok { color: #67c23a; } .c-warn { color: #e6a23c; } .c-bad { color: #f56c6c; }
.log-filters { display: flex; gap: 8px; margin-bottom: 10px; }
.pager { margin-top: 10px; justify-content: flex-end; }
@media (max-width: 900px) { .gov-grid { grid-template-columns: 1fr; } }
</style>
