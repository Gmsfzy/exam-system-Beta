<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>成绩分析</h2>
        <p>可视化分析学生考试成绩数据</p>
      </div>
    </div>

    <div class="exam-selector">
      <el-select v-model="selectedExamId" placeholder="请选择考试" @change="loadAnalysis">
        <el-option v-for="exam in exams" :key="exam.id" :label="exam.title" :value="exam.id" />
      </el-select>
    </div>

    <div v-if="selectedExamId && analysisData" class="analysis-content">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon bg-blue">
            <el-icon :size="24"><User /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ analysisData.total_students }}</div>
            <div class="stat-label">参考人数</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon bg-green">
            <el-icon :size="24"><TrendCharts /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ analysisData.avg_score }}</div>
            <div class="stat-label">平均分</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon bg-purple">
            <el-icon :size="24"><Medal /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ analysisData.highest_score }}</div>
            <div class="stat-label">最高分</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon bg-orange">
            <el-icon :size="24"><Trophy /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ analysisData.pass_rate }}%</div>
            <div class="stat-label">及格率</div>
          </div>
        </div>
      </div>

      <div class="charts-grid">
        <div class="chart-card">
          <h3 class="chart-title">成绩分布</h3>
          <div class="chart-container">
            <Bar :data="scoreDistributionChart" :options="barChartOptions" />
          </div>
        </div>
        <div class="chart-card">
          <h3 class="chart-title">分数段占比</h3>
          <div class="chart-container">
            <Doughnut :data="scoreSegmentChart" :options="doughnutOptions" />
          </div>
        </div>
      </div>

      <div class="chart-card full-width">
        <h3 class="chart-title">各题型得分分析</h3>
        <div class="chart-container wide">
          <Bar :data="questionTypeChart" :options="horizontalBarOptions" />
        </div>
      </div>

      <div class="chart-card full-width">
        <h3 class="chart-title">学生成绩排名</h3>
        <div class="ranking-table">
          <el-table :data="analysisData.rankings" border :header-cell-style="{ background: '#f8fafc' }">
            <el-table-column prop="rank" label="排名" width="80">
              <template #default="scope">
                <span :class="getRankClass(scope.row.rank)">{{ scope.row.rank }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="student_name" label="学生姓名" />
            <el-table-column prop="score" label="得分" />
            <el-table-column prop="total_score" label="满分" />
            <el-table-column prop="percentage" label="得分率" />
            <el-table-column prop="rank_percentage" label="超越比例" />
          </el-table>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <div class="empty-icon">
        <el-icon :size="64" color="#cbd5e1"><PieChart /></el-icon>
      </div>
      <h3>暂无数据</h3>
      <p>选择一个考试查看成绩分析</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { User, TrendCharts, Medal, Trophy, PieChart } from '@element-plus/icons-vue'
import { Bar, Doughnut } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement
} from 'chart.js'
import request from '../utils/request'

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend, ArcElement)

const exams = ref([])
const selectedExamId = ref(null)
const analysisData = ref(null)

onMounted(async () => {
  await loadExams()
})

const loadExams = async () => {
  try {
    const res = await request.get('/api/exams')
    exams.value = res.data.filter(e => e.status === 'published' || e.status === 'ended')
    if (exams.value.length > 0) {
      selectedExamId.value = exams.value[0].id
    }
  } catch (e) {
    console.error('加载考试列表失败', e)
  }
}

const loadAnalysis = async () => {
  if (!selectedExamId.value) return
  try {
    const res = await request.get(`/api/results/analysis/${selectedExamId.value}`)
    analysisData.value = res.data
  } catch (e) {
    console.error('加载成绩分析失败', e)
  }
}

watch(selectedExamId, () => {
  loadAnalysis()
})

const barChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: { callbacks: { label: (context) => `${context.raw} 人` } }
  },
  scales: {
    x: { grid: { display: false }, ticks: { color: '#64748b' } },
    y: { beginAtZero: true, ticks: { color: '#64748b', stepSize: 1 } }
  }
}

const doughnutOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { position: 'bottom', labels: { padding: 20, usePointStyle: true } }
  },
  cutout: '60%'
}

const horizontalBarOptions = {
  indexAxis: 'y',
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: { callbacks: { label: (context) => `${context.raw}分` } }
  },
  scales: {
    x: { beginAtZero: true, max: 100, ticks: { color: '#64748b', callback: (value) => `${value}分` } },
    y: { grid: { display: false }, ticks: { color: '#64748b' } }
  }
}

const scoreDistributionChart = computed(() => {
  if (!analysisData.value) return { labels: [], datasets: [] }
  const data = analysisData.value.score_distribution
  return {
    labels: Object.keys(data),
    datasets: [{
      label: '人数',
      data: Object.values(data),
      backgroundColor: 'rgba(99, 102, 241, 0.8)',
      borderRadius: 8,
      barThickness: 40
    }]
  }
})

const scoreSegmentChart = computed(() => {
  if (!analysisData.value) return { labels: [], datasets: [] }
  const segments = analysisData.value.score_segments
  return {
    labels: Object.keys(segments),
    datasets: [{
      data: Object.values(segments),
      backgroundColor: ['rgba(34, 197, 94, 0.8)', 'rgba(16, 185, 129, 0.8)', 'rgba(251, 191, 36, 0.8)', 'rgba(249, 115, 22, 0.8)', 'rgba(239, 68, 68, 0.8)'],
      borderWidth: 0
    }]
  }
})

const questionTypeChart = computed(() => {
  if (!analysisData.value) return { labels: [], datasets: [] }
  const types = analysisData.value.question_type_analysis
  return {
    labels: types.map(t => t.type),
    datasets: [{
      label: '平均得分率',
      data: types.map(t => Math.round(t.avg_score_percentage)),
      backgroundColor: 'rgba(147, 51, 234, 0.8)',
      borderRadius: 8
    }]
  }
})

const getRankClass = (rank) => {
  if (rank === 1) return 'rank-gold'
  if (rank === 2) return 'rank-silver'
  if (rank === 3) return 'rank-bronze'
  return 'rank-normal'
}
</script>

<style scoped>
.page-wrapper { max-width: 1200px; margin: 0 auto; padding: 20px; }
.page-header { margin-bottom: 24px; }
.header-title h2 { font-size: 24px; font-weight: 700; color: #1e293b; margin: 0; }
.header-title p { color: #94a3b8; margin: 6px 0 0; }
.exam-selector { margin-bottom: 24px; }
.exam-selector .el-select { width: 300px; }
.analysis-content { display: flex; flex-direction: column; gap: 24px; }
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.stat-card { background: white; border-radius: 16px; padding: 20px; display: flex; align-items: center; gap: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.stat-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; color: white; }
.stat-icon.bg-blue { background: linear-gradient(135deg, #3b82f6, #2563eb); }
.stat-icon.bg-green { background: linear-gradient(135deg, #22c55e, #16a34a); }
.stat-icon.bg-purple { background: linear-gradient(135deg, #a855f7, #9333ea); }
.stat-icon.bg-orange { background: linear-gradient(135deg, #f97316, #ea580c); }
.stat-info { flex: 1; }
.stat-value { font-size: 28px; font-weight: 700; color: #1e293b; }
.stat-label { font-size: 13px; color: #94a3b8; margin-top: 4px; }
.charts-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; }
.chart-card { background: white; border-radius: 16px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.chart-card.full-width { grid-column: 1 / -1; }
.chart-title { font-size: 16px; font-weight: 600; color: #1e293b; margin: 0 0 20px; }
.chart-container { height: 300px; }
.chart-container.wide { height: 350px; }
.ranking-table { margin-top: 8px; }
.ranking-table .el-table { border-radius: 12px; overflow: hidden; }
.rank-gold { background: linear-gradient(135deg, #fcd34d, #fbbf24); color: #78350f; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.rank-silver { background: linear-gradient(135deg, #e5e7eb, #d1d5db); color: #4b5563; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.rank-bronze { background: linear-gradient(135deg, #fdba74, #fb923c); color: #92400e; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.rank-normal { color: #64748b; font-weight: 500; }
.empty-state { text-align: center; padding: 60px 20px; }
.empty-icon { margin-bottom: 20px; }
.empty-state h3 { font-size: 18px; color: #64748b; margin: 0 0 8px; }
.empty-state p { color: #94a3b8; margin: 0; }
.dark .header-title h2 { color: #f1f5f9; }
.dark .header-title p { color: #94a3b8; }
.dark .stat-card, .dark .chart-card { background: #1e293b; border: 1px solid #334155; }
.dark .stat-value, .dark .chart-title { color: #f1f5f9; }
.dark .stat-label { color: #94a3b8; }
.dark .empty-state h3 { color: #f1f5f9; }
.dark .empty-state p { color: #94a3b8; }
.dark .empty-icon { color: #334155; }
.dark .el-select .el-input__inner { background: #1e293b; border-color: #334155; color: #f1f5f9; }
.dark .el-table { background: #1e293b; }
.dark .el-table th { background: #334155 !important; color: #f1f5f9; }
.dark .el-table td { background: #1e293b; color: #f1f5f9; border-color: #334155; }
.dark .el-table--border th, .dark .el-table--border td { border-color: #334155; }
</style>
