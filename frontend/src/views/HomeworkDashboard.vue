<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Reading /></el-icon> 作业中心</h2>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 顶部统计卡 -->
    <div class="stat-cards">
      <div class="stat-card todo">
        <div class="sc-num">{{ stats.unsubmitted ?? 0 }}</div>
        <div class="sc-label">待提交</div>
      </div>
      <div class="stat-card soon">
        <div class="sc-num">{{ stats.due_soon ?? 0 }}</div>
        <div class="sc-label">临近截止（3天内）</div>
      </div>
      <div class="stat-card pending">
        <div class="sc-num">{{ stats.submitted ?? 0 }}</div>
        <div class="sc-label">待批改</div>
      </div>
      <div class="stat-card graded">
        <div class="sc-num">{{ stats.graded ?? 0 }}</div>
        <div class="sc-label">已批改</div>
      </div>
    </div>

    <div class="dash-body">
      <!-- 待办列表 -->
      <div class="list-pane">
        <div class="pane-title">待办清单（待交且临近截止优先）</div>
        <div v-if="loading && !items.length" class="center">加载中…</div>
        <el-empty v-else-if="!items.length" description="暂无相关作业" :image-size="80" />
        <div v-else class="hw-list">
          <div v-for="it in items" :key="it.id" class="hw-item" @click="open(it)">
            <div class="hi-main">
              <div class="hi-title">
                {{ it.title }}
                <el-tag size="small" effect="plain" class="hi-type">{{ it.hw_type === 'open' ? '开放式' : '题集式' }}</el-tag>
              </div>
              <div class="hi-meta">
                <span>{{ it.teacher_name }}</span>
                <span v-if="it.deadline">截止 {{ fmt(it.deadline) }}</span>
                <span v-else>无截止时间</span>
                <el-tag v-if="it.is_late" size="small" type="warning" effect="plain">迟交</el-tag>
              </div>
            </div>
            <div class="hi-side">
              <el-tag :type="statusTag(it.status_of_me)" size="small">{{ statusText(it.status_of_me) }}</el-tag>
              <div class="hi-count" :class="countClass(it)">{{ countdown(it) }}</div>
              <div v-if="it.status_of_me === 'graded'" class="hi-score">
                <template v-if="it.grade_mode === 'level'">{{ it.grade_display || '—' }}（等级）</template>
                <template v-else-if="it.grade_mode === 'comment'">评语制</template>
                <template v-else>{{ it.total_score }} / {{ it.max_score ?? '—' }}</template>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 得分趋势 -->
      <div class="trend-pane">
        <div class="pane-title">历次已批作业得分率趋势</div>
        <div v-if="trendData" class="chart-box"><Line :data="trendData" :options="trendOptions" /></div>
        <el-empty v-else description="还没有已批改的作业，完成作业后即可生成趋势" :image-size="70" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Reading, Refresh } from '@element-plus/icons-vue'
import { Chart as ChartJS, LinearScale, CategoryScale, PointElement, LineElement, Filler, Tooltip, Legend } from 'chart.js'
import { Line } from 'vue-chartjs'
import request from '../utils/request'

ChartJS.register(LinearScale, CategoryScale, PointElement, LineElement, Filler, Tooltip, Legend)

const router = useRouter()
const items = ref([])
const stats = ref({})
const trend = ref([])
const loading = ref(false)

const fmt = (v) => (v || '').slice(5, 16).replace('T', ' ')
const statusText = (s) => ({ unsubmitted: '待提交', submitted: '待批改', graded: '已批改' }[s] || s)
const statusTag = (s) => ({ unsubmitted: 'danger', submitted: 'warning', graded: 'success' }[s] || 'info')

const countdown = (it) => {
  if (it.status_of_me !== 'unsubmitted') return ''
  if (it.days_left == null) return '不限期'
  if (it.days_left < 0) return it.allow_late ? '已截止·可迟交' : '已截止'
  const d = Math.floor(it.days_left)
  if (d >= 1) return `剩 ${d} 天`
  return it.days_left <= 0.04 ? '即将截止' : '不足 1 天'
}
const countClass = (it) => {
  if (it.status_of_me !== 'unsubmitted' || it.days_left == null) return ''
  if (it.days_left < 0) return 'over'
  if (it.days_left <= 3) return 'urgent'
  return ''
}

const open = (it) => {
  // 全部跳转作答页（已交/已批时该页呈现只读结果）
  router.push(`/homeworks/${it.id}/take`)
}

const trendData = computed(() => {
  const t = trend.value || []
  if (!t.length) return null
  return {
    labels: t.map((x, i) => x.title ? `${i + 1}.${x.title}`.slice(0, 10) : `${i + 1}`),
    datasets: [{
      label: '得分率 %',
      data: t.map((x) => (x.ratio != null ? Math.round(x.ratio * 1000) / 10 : null)),
      borderColor: '#6366f1',
      backgroundColor: 'rgba(99, 102, 241, 0.14)',
      fill: true,
      tension: 0.3,
      pointRadius: 3,
    }],
  }
})
const trendOptions = {
  responsive: true,
  maintainAspectRatio: false,
  scales: { y: { min: 0, max: 100, title: { display: true, text: '得分率 %' } } },
  plugins: { legend: { display: false } },
}

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/homeworks/center')
    items.value = res.data.items || []
    stats.value = res.data.stats || {}
    trend.value = res.data.score_trend || []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.stat-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; }
.stat-card { border-radius: 12px; padding: 16px 18px; color: #fff; }
.stat-card.todo { background: linear-gradient(135deg, #f97316, #fb923c); }
.stat-card.soon { background: linear-gradient(135deg, #ef4444, #f87171); }
.stat-card.pending { background: linear-gradient(135deg, #eab308, #facc15); }
.stat-card.graded { background: linear-gradient(135deg, #22c55e, #4ade80); }
.sc-num { font-size: 30px; font-weight: 700; line-height: 1.1; }
.sc-label { font-size: 13px; opacity: 0.92; margin-top: 4px; }
.dash-body { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
.list-pane { flex: 1; min-width: 360px; border: 1px solid #ebeef5; border-radius: 12px; padding: 12px 14px; }
.trend-pane { width: 420px; border: 1px solid #ebeef5; border-radius: 12px; padding: 12px 14px; }
.pane-title { font-weight: 600; color: #303133; margin-bottom: 10px; font-size: 14px; }
.chart-box { height: 300px; }
.hw-list { display: flex; flex-direction: column; gap: 8px; max-height: 60vh; overflow: auto; }
.hw-item { display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 10px 12px; border: 1px solid #f2f3f5; border-radius: 10px; cursor: pointer; }
.hw-item:hover { background: #f8faff; border-color: #dbeafe; }
.hi-title { font-weight: 600; color: #303133; display: flex; align-items: center; gap: 8px; }
.hi-type { font-weight: 400; }
.hi-meta { display: flex; gap: 12px; font-size: 12px; color: #909399; margin-top: 4px; }
.hi-side { text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.hi-count { font-size: 12px; color: #606266; min-height: 16px; }
.hi-count.urgent { color: #e6a23c; font-weight: 600; }
.hi-count.over { color: #f56c6c; font-weight: 600; }
.hi-score { font-size: 13px; color: #67c23a; font-weight: 600; }
.center { text-align: center; padding: 30px; color: #909399; }
</style>
