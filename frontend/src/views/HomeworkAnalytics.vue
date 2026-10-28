<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><DataAnalysis /></el-icon> 学情分析看板</h2>
        <span class="sub">跨作业完成率 / 得分趋势 / 知识点薄弱热力 / 每题得分率与区分度（只读聚合）</span>
      </div>
      <div class="toolbar">
        <span class="label">范围</span>
        <el-select v-model="hwId" filterable clearable placeholder="全部作业" style="width: 260px"
                   @change="load">
          <el-option v-for="h in homeworks" :key="h.id" :label="h.title" :value="h.id" />
        </el-select>
        <el-button :icon="Refresh" @click="reload">刷新</el-button>
      </div>
    </div>

    <el-skeleton v-if="loading" :rows="6" animated />
    <template v-else>
      <div class="stat-cards">
        <div class="stat-card c1"><div class="num">{{ summary.homework_count ?? 0 }}</div><div class="cap">分析作业数</div></div>
        <div class="stat-card c2"><div class="num">{{ pct(summary.avg_submitted_rate) }}%</div><div class="cap">平均完成率</div></div>
        <div class="stat-card c3"><div class="num">{{ pct(toRatio(summary.avg_score_rate)) }}%</div><div class="cap">平均得分率</div></div>
        <div class="stat-card c4"><div class="num">{{ summary.graded_submissions ?? 0 }}<span class="of">/{{ summary.total_submissions ?? 0 }}</span></div><div class="cap">已批 / 已交份数</div></div>
      </div>

      <el-empty v-if="!trend.length" description="暂无可分析的作业数据（需有学生提交并批改）" />
      <template v-else>
        <div class="pane">
          <div class="pane-title">得分趋势（逐作业）</div>
          <div class="chart-box"><Line :data="trendData" :options="trendOptions" /></div>
        </div>

        <div class="two-col">
          <div class="pane">
            <div class="pane-title">知识点薄弱热力（得分率升序，最弱在前）</div>
            <el-empty v-if="!knowledge.length" description="暂无知识点数据（题目未标注知识点）" :image-size="60" />
            <div v-else class="heat-list">
              <div v-for="k in knowledge" :key="k.id" class="heat-row">
                <span class="heat-name" :title="k.name">{{ k.name }}</span>
                <el-progress :percentage="pct(k.avg_ratio)" :color="heatColor(k.avg_ratio)"
                             :stroke-width="12" class="heat-bar" />
                <span class="heat-meta">{{ k.question_count }}题·{{ k.hw_count }}份</span>
              </div>
            </div>
          </div>

          <div class="pane">
            <div class="pane-title">逐作业完成率 / 及格率</div>
            <el-table :data="trend" size="small" max-height="320">
              <el-table-column prop="title" label="作业" min-width="120" show-overflow-tooltip />
              <el-table-column label="完成率" width="90" align="center">
                <template #default="{ row }">{{ row.submitted_rate }}%</template>
              </el-table-column>
              <el-table-column label="得分率" width="90" align="center">
                <template #default="{ row }">
                  <el-tag :type="ratioTag(row.avg_ratio)" size="small" effect="plain">
                    {{ pct(row.avg_ratio) }}%
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="及格率" width="80" align="center">
                <template #default="{ row }">{{ row.pass_rate != null ? row.pass_rate + '%' : '—' }}</template>
              </el-table-column>
            </el-table>
          </div>
        </div>

        <div class="pane">
          <div class="pane-title">薄弱题目（跨作业每题得分率升序 + 27% 区分度）</div>
          <el-empty v-if="!weak.length" description="暂无题集式作业的题目级数据" :image-size="60" />
          <el-table v-else :data="weak" size="small" stripe>
            <el-table-column prop="content" label="题目" min-width="200" show-overflow-tooltip />
            <el-table-column prop="homework_title" label="来源作业" width="150" show-overflow-tooltip />
            <el-table-column prop="type" label="题型" width="90" />
            <el-table-column label="作答" width="70" align="center">
              <template #default="{ row }">{{ row.answers }}</template>
            </el-table-column>
            <el-table-column label="得分率" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="ratioTag(row.avg_ratio)" size="small">{{ pct(row.avg_ratio) }}%</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="正确率" width="90" align="center">
              <template #default="{ row }">{{ row.correct_rate != null ? row.correct_rate + '%' : '—' }}</template>
            </el-table-column>
            <el-table-column label="区分度" width="100" align="center">
              <template #default="{ row }">
                <span v-if="row.discrimination == null" class="muted">样本不足</span>
                <el-tag v-else :type="discTag(row.discrimination)" size="small" effect="plain">
                  {{ row.discrimination.toFixed(2) }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { DataAnalysis, Refresh } from '@element-plus/icons-vue'
import { useThemeStore } from '../stores/theme'
import { Chart as ChartJS, LinearScale, CategoryScale, PointElement, LineElement, Filler, Tooltip, Legend } from 'chart.js'
import { Line } from 'vue-chartjs'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

ChartJS.register(LinearScale, CategoryScale, PointElement, LineElement, Filler, Tooltip, Legend)

const homeworks = ref([])
const theme = useThemeStore()
const hwId = ref(null)
const loading = ref(false)
const summary = ref({})
const trend = ref([])
const knowledge = ref([])
const weak = ref([])

const pct = (v) => (v == null ? 0 : Math.round(v * 10) / 10)
const toRatio = (v) => (v == null ? null : v)   // avg_score_rate 已是 0~1 比率
const ratioTag = (r) => (r == null ? 'info' : (r < 0.6 ? 'danger' : (r < 0.8 ? 'warning' : 'success')))
const heatColor = (r) => (r < 0.6 ? '#f56c6c' : (r < 0.8 ? '#e6a23c' : '#67c23a'))
const discTag = (d) => (d >= 0.4 ? 'success' : (d >= 0.3 ? 'warning' : 'danger'))

const trendData = computed(() => {
  const t = trend.value || []
  if (!t.length) return null
  return {
    labels: t.map((x, i) => `${i + 1}.${(x.title || '').slice(0, 8)}`),
    datasets: [
      { label: '得分率 %', data: t.map((x) => (x.avg_ratio != null ? pct(x.avg_ratio * 100) : null)),
        borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.14)', fill: true, tension: 0.3, yAxisID: 'y' },
      { label: '完成率 %', data: t.map((x) => pct(x.submitted_rate)),
        borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.10)', fill: false, tension: 0.3, yAxisID: 'y' },
    ],
  }
})
const trendOptions = computed(() => {
  // 坐标轴/图例/标题文字色随暗色主题切换（否则框变暗后默认深灰刻度看不清）
  const axis = theme.isDark ? '#a3a9b5' : '#606266'
  const grid = theme.isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'
  return {
    responsive: true, maintainAspectRatio: false,
    scales: {
      x: { ticks: { color: axis }, grid: { color: grid } },
      y: { min: 0, max: 100, ticks: { color: axis }, grid: { color: grid },
           title: { display: true, text: '百分比 %', color: axis } },
    },
    plugins: { legend: { display: true, position: 'bottom', labels: { color: axis } } },
  }
})

const loadHomeworks = async () => {
  const res = await request.get('/api/homeworks')
  homeworks.value = (res.data.items || []).filter(h => h.status !== 'draft')
}

const load = async () => {
  loading.value = true
  try {
    const params = hwId.value ? { homework_id: hwId.value } : {}
    const res = await request.get('/api/homeworks/analytics', { params })
    summary.value = res.data.summary || {}
    trend.value = res.data.trend || []
    knowledge.value = res.data.knowledge_heat || []
    weak.value = res.data.weak_questions || []
  } catch (e) {
    ElMessage.error('加载学情分析失败')
  } finally {
    loading.value = false
  }
}

const reload = async () => { await loadHomeworks(); await load() }

onMounted(async () => { await loadHomeworks(); await load() })
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; flex-wrap: wrap; gap: 10px; }
.header-title h2 { margin: 0; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.sub { font-size: 12px; color: #909399; }
.toolbar { display: flex; align-items: center; gap: 10px; }
.label { font-weight: 500; color: var(--el-text-color-regular, #4b5563); font-size: 14px; }
.stat-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; }
.stat-card { border-radius: 12px; padding: 16px 18px; color: #fff; }
.stat-card .num { font-size: 26px; font-weight: 700; line-height: 1.2; }
.stat-card .of { font-size: 15px; font-weight: 400; opacity: 0.8; }
.stat-card .cap { font-size: 13px; opacity: 0.9; margin-top: 4px; }
.stat-card.c1 { background: linear-gradient(135deg, #6366f1, #818cf8); }
.stat-card.c2 { background: linear-gradient(135deg, #0ea5e9, #38bdf8); }
.stat-card.c3 { background: linear-gradient(135deg, #f59e0b, #fbbf24); }
.stat-card.c4 { background: linear-gradient(135deg, #10b981, #34d399); }
.pane { background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; }
.pane-title { font-weight: 600; color: var(--el-text-color-primary, #303133); margin-bottom: 12px; font-size: 15px; }
.chart-box { height: 280px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.heat-list { display: flex; flex-direction: column; gap: 10px; }
.heat-row { display: flex; align-items: center; gap: 10px; }
.heat-name { width: 120px; font-size: 13px; color: var(--el-text-color-regular, #4b5563); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.heat-bar { flex: 1; }
.heat-meta { width: 92px; font-size: 12px; color: #909399; text-align: right; }
.muted { color: #c0c4cc; font-size: 12px; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } .stat-cards { grid-template-columns: repeat(2, 1fr); } }
</style>
