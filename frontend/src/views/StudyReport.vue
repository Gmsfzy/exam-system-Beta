<template>
  <div class="study-report">
    <div class="page-header">
      <h1>学习报告</h1>
      <p class="subtitle">近 {{ overview.period_days }} 天的学习数据聚合</p>
    </div>

    <!-- 核心指标 -->
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="m-num">{{ overview.total_questions }}</div>
        <div class="m-lbl">总刷题数</div>
      </div>
      <div class="metric-card">
        <div class="m-num">{{ overview.sessions_count }}</div>
        <div class="m-lbl">练习次数</div>
      </div>
      <div class="metric-card">
        <div class="m-num">{{ (overview.score_ratio * 100).toFixed(1) }}%</div>
        <div class="m-lbl">平均正确率</div>
      </div>
      <div class="metric-card">
        <div class="m-num">{{ formatTime(overview.total_time_sec) }}</div>
        <div class="m-lbl">累计用时</div>
      </div>
      <div class="metric-card danger">
        <div class="m-num">{{ overview.wrong_unmastered }}</div>
        <div class="m-lbl">待攻克错题</div>
      </div>
      <div class="metric-card success">
        <div class="m-num">{{ overview.wrong_mastered }}</div>
        <div class="m-lbl">已掌握错题</div>
      </div>
    </div>

    <!-- 每日学习柱状图 -->
    <div class="chart-card">
      <h3>每日练习量</h3>
      <div class="daily-bars">
        <div v-for="(data, day) in dailyArray" :key="day" class="day-col">
          <div class="bar-wrap">
            <div class="bar" :style="{ height: barHeight(data.total) + '%' }">
              <span class="bar-val">{{ data.total || '' }}</span>
            </div>
          </div>
          <div class="day-label">{{ day.slice(5) }}</div>
        </div>
      </div>
    </div>

    <!-- 每日正确率折线 -->
    <div class="chart-card">
      <h3>每日正确率</h3>
      <div class="rate-line">
        <div v-for="(data, day) in dailyArray" :key="'r-' + day" class="rate-col">
          <div class="rate-dot" :style="{ bottom: rateY(data.ratio) + '%' }">
            <span>{{ data.total ? (data.ratio * 100).toFixed(0) + '%' : '' }}</span>
          </div>
          <div class="rate-line-x"></div>
        </div>
      </div>
    </div>

    <!-- 学习日志明细 -->
    <div class="chart-card">
      <h3>学习日志明细</h3>
      <el-empty v-if="!loading && dailyLogs.length === 0" description="暂无日志数据" />
      <table v-else class="log-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>类型</th>
            <th>题数</th>
            <th>答对</th>
            <th>正确率</th>
            <th>用时</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in dailyLogs" :key="l.id">
            <td>{{ l.studied_at }}</td>
            <td><el-tag size="small">{{ logTypeLabel(l.log_type) }}</el-tag></td>
            <td>{{ l.total_questions }}</td>
            <td>{{ l.correct_count }}</td>
            <td>{{ l.total_questions ? (l.correct_count / l.total_questions * 100).toFixed(1) + '%' : '-' }}</td>
            <td>{{ formatTime(l.time_spent_sec) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import request from '../utils/request'

const overview = ref({
  period_days: 30, total_questions: 0, correct_count: 0, score_ratio: 0,
  total_time_sec: 0, sessions_count: 0,
  wrong_total: 0, wrong_unmastered: 0, wrong_mastered: 0, active_plans: 0,
  daily: {},
})
const dailyLogs = ref([])
const loading = ref(false)

const dailyArray = computed(() => {
  const d = overview.value.daily || {}
  // 按日期排序（新 → 旧）
  return Object.entries(d).sort((a, b) => a[0].localeCompare(b[0]))
})

const maxTotal = computed(() => {
  let m = 0
  for (const [, v] of dailyArray.value) if (v.total > m) m = v.total
  return Math.max(m, 1)
})

function barHeight(total) { return maxTotal.value ? Math.max(total / maxTotal.value * 100, total ? 4 : 0) : 0 }
function rateY(ratio) { return ratio !== undefined && ratio !== null ? (1 - ratio) * 85 + 5 : 50 }  // y 轴翻转

function logTypeLabel(t) { return { exam: '考试', competition: '竞赛', practice: '练习' }[t] || t }
function formatTime(sec) {
  if (!sec) return '-'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (h) return `${h}h ${m}m`
  return `${m}m`
}

async function load() {
  loading.value = true
  try {
    const [ov, logs] = await Promise.all([
      request.get('/api/learning/report/overview?days=30'),
      request.get('/api/learning/report/daily?days=30'),
    ])
    overview.value = ov.data
    dailyLogs.value = logs.data || []
  } catch (e) {}
  loading.value = false
}

onMounted(load)
</script>

<style scoped>
.study-report { padding: 20px; max-width: 1100px; }
.page-header { margin-bottom: 20px; }
.page-header h1 { font-size: 22px; margin: 0 0 4px; color: var(--text-primary); }
.subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }

.metrics-grid {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; margin-bottom: 24px;
}
.metric-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 18px 16px; text-align: center;
}
.metric-card.danger { border-color: rgba(239,68,68,0.3); }
.metric-card.success { border-color: rgba(16,185,129,0.3); }
.m-num { font-size: 26px; font-weight: 700; color: var(--text-primary); }
.m-lbl { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

.chart-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 20px 24px; margin-bottom: 16px;
}
.chart-card h3 { font-size: 15px; margin: 0 0 18px; color: var(--text-primary); }

.daily-bars { display: flex; align-items: flex-end; gap: 12px; height: 160px; padding: 0 10px; }
.day-col { flex: 1; display: flex; flex-direction: column; align-items: center; }
.bar-wrap { width: 100%; height: 120px; display: flex; align-items: flex-end; }
.bar {
  width: 100%; background: linear-gradient(180deg, #6366f1 0%, #8b5cf6 100%);
  border-radius: 4px 4px 0 0; min-height: 2px;
  display: flex; align-items: flex-start; justify-content: center;
}
.bar-val { font-size: 10px; color: white; padding-top: 2px; }
.day-label { font-size: 11px; color: var(--text-muted); margin-top: 6px; }

.rate-line { display: flex; gap: 12px; height: 140px; padding: 0 10px; }
.rate-col { flex: 1; position: relative; }
.rate-dot { position: absolute; left: 50%; transform: translateX(-50%); }
.rate-dot span {
  display: block; background: #f59e0b; color: white; font-size: 10px;
  padding: 2px 6px; border-radius: 10px; white-space: nowrap;
}
.rate-line-x { position: absolute; bottom: 0; left: 0; right: 0; height: 1px; background: var(--border-color); }

.log-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.log-table th, .log-table td {
  text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border-color);
}
.log-table th { color: var(--text-muted); font-weight: 500; font-size: 12px; }
.log-table td { color: var(--text-primary); }

@media (max-width: 900px) {
  .metrics-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
