<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>实时监考 · {{ monitor.exam?.title || '' }}</h2>
        <p>考试作答进度、切屏监控与补考授权（每 10 秒自动刷新，交卷实时推送）</p>
      </div>
      <div class="header-actions">
        <el-tag v-if="!monitor.exam?.results_published" type="danger" style="margin-right: 12px">成绩未发布</el-tag>
        <el-button @click="loadMonitor">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
        <el-button @click="goBack">
          <el-icon><ArrowLeft /></el-icon>返回
        </el-button>
      </div>
    </div>

    <div class="stats-row" v-if="monitor.summary">
      <div class="stat-card">
        <div class="stat-value">{{ monitor.summary.total }}</div>
        <div class="stat-label">受邀总数</div>
      </div>
      <div class="stat-card running">
        <div class="stat-value">{{ monitor.summary.in_progress }}</div>
        <div class="stat-label">作答中</div>
      </div>
      <div class="stat-card submitted">
        <div class="stat-value">{{ monitor.summary.submitted }}</div>
        <div class="stat-label">已交卷</div>
      </div>
      <div class="stat-card absent">
        <div class="stat-value">{{ monitor.summary.absent }}</div>
        <div class="stat-label">未参加</div>
      </div>
    </div>

    <el-table :data="monitor.students || []" border class="monitor-table">
      <el-table-column prop="username" label="学生账号" min-width="120" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType[row.status]" size="small">{{ statusLabels[row.status] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="作答轮次" width="110">
        <template #default="{ row }">
          {{ row.attempts_used }} / {{ row.allowance ?? '—' }}
          <el-tooltip v-if="row.allowance !== null && row.attempts_used >= row.allowance" content="已用满次数，如需补考请授权">
            <el-icon color="#f59e0b"><Warning /></el-icon>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="答题进度" min-width="180">
        <template #default="{ row }">
          <el-progress
            v-if="row.total_questions"
            :percentage="Math.min(100, Math.round((row.answered || 0) / row.total_questions * 100))"
            :status="row.status === 'in_progress' ? '' : 'success'"
          />
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="切屏次数" width="100">
        <template #default="{ row }">
          <span :class="{ 'switch-warn': row.switch_count >= 2 }">{{ row.switch_count }}</span>
        </template>
      </el-table-column>
      <el-table-column label="本次得分" width="100">
        <template #default="{ row }">{{ row.last_score ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="成绩" width="120">
        <template #default="{ row }">
          <span v-if="row.result_score !== null">{{ row.result_score }}</span>
          <span v-else>—</span>
          <el-tag v-if="row.needs_manual" size="small" type="warning" style="margin-left: 6px">待批改</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="grantAttempt(row)">
            {{ row.extra_attempts ? `授权 ${row.extra_attempts} 次，调整` : '补考授权' }}
          </el-button>
          <el-button
            v-if="row.result_score !== null"
            size="small" text type="success"
            @click="viewResult(row)"
          >成绩明细</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, ArrowLeft, Warning } from '@element-plus/icons-vue'
import request from '../utils/request'
import { getSocket, joinUserRoom, authToken } from '../utils/socket'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const monitor = ref({})
let timer = null
const onExamAlert = () => loadMonitor()

const statusLabels = { in_progress: '作答中', submitted: '已交卷', absent: '未参加' }
const statusType = { in_progress: 'warning', submitted: 'success', absent: 'info' }

onMounted(async () => {
  await loadMonitor()
  timer = setInterval(loadMonitor, 10000)
  // Socket 实时推送兜底：交卷/开考/强制交卷即时刷新
  if (auth.user?.id) {
    joinUserRoom(auth.user.id, authToken())
    getSocket().on('exam_alert', onExamAlert)
  }
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  getSocket().off('exam_alert', onExamAlert)
})

const loadMonitor = async () => {
  try {
    const res = await request.get(`/api/exams/${route.params.id}/monitor`)
    monitor.value = res.data
  } catch (e) {
    console.error('加载监考数据失败', e)
  }
}

const grantAttempt = async (row) => {
  try {
    const { value } = await ElMessageBox.prompt(
      `为 ${row.username} 设置额外作答次数（0 = 撤销授权）。当前已用 ${row.attempts_used}/${row.allowance}`,
      '补考授权',
      {
        inputValue: String((row.extra_attempts || 0) + 1),
        inputPattern: /^(0|[1-9]|10)$/,
        inputErrorMessage: '请输入 0-10 的整数',
      }
    )
    await request.post(`/api/exams/${route.params.id}/grant_attempt`, {
      student_id: row.student_id,
      extra: parseInt(value)
    })
    ElMessage.success('授权成功')
    await loadMonitor()
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') console.error(e)
  }
}

const viewResult = (row) => {
  router.push(`/results/exam/${route.params.id}`)
}

const goBack = () => router.push('/exams')
</script>

<style scoped>
.page-wrapper {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.header-title h2 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.header-title p {
  color: var(--text-muted);
  margin: 6px 0 0;
  font-size: 14px;
}

.header-actions {
  display: flex;
  align-items: center;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 20px;
  text-align: center;
}

.stat-card .stat-value {
  font-size: 30px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-card .stat-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 4px;
}

.stat-card.running .stat-value { color: #f59e0b; }
.stat-card.submitted .stat-value { color: #10b981; }
.stat-card.absent .stat-value { color: #94a3b8; }

.monitor-table {
  background: var(--bg-card);
}

.switch-warn {
  color: #ef4444;
  font-weight: 700;
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
