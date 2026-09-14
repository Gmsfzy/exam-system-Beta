<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><TrendCharts /></el-icon> 学情画像</h2>
        <p>
          <span class="sub-info">综合考试成绩与竞赛表现的学习能力分析</span>
          <el-select v-if="isTeacher" v-model="studentId" placeholder="选择学生"
                     class="student-select" @change="load" filterable>
            <el-option v-for="s in students" :key="s.id" :label="s.username" :value="s.id" />
          </el-select>
        </p>
      </div>
    </div>

    <el-empty v-if="!profile" description="暂无数据" />

    <template v-else>
      <!-- 综合五维雷达 + 概览 -->
      <div class="overview-row">
        <div class="radar-card">
          <h3 class="card-title">综合能力</h3>
          <div class="radar-box">
            <Radar v-if="radarData" :data="radarData" :options="radarOptions" />
            <el-empty v-else description="暂无足够数据" :image-size="80" />
          </div>
        </div>
        <div class="stat-cards">
          <div class="stat-card">
            <span class="sc-label">考试均分率</span>
            <span class="sc-value">{{ profile.exam.avg_score_rate != null ? (profile.exam.avg_score_rate * 100).toFixed(0) + '%' : '—' }}</span>
            <span class="sc-sub">{{ profile.exam.exam_count }} 场考试</span>
          </div>
          <div class="stat-card tier">
            <span class="sc-label">当前段位</span>
            <span class="sc-value" :style="{ color: tierColor(profile.competition.tier) }">{{ profile.competition.tier }}</span>
            <span class="sc-sub">{{ profile.competition.points }} 竞技积分</span>
          </div>
          <div class="stat-card">
            <span class="sc-label">PK 胜率</span>
            <span class="sc-value">{{ profile.competition.pk.win_rate != null ? (profile.competition.pk.win_rate * 100).toFixed(0) + '%' : '—' }}</span>
            <span class="sc-sub">{{ profile.competition.pk.total }} 场对战</span>
          </div>
          <div class="stat-card">
            <span class="sc-label">平均答题速度</span>
            <span class="sc-value">{{ profile.competition.avg_speed_seconds != null ? profile.competition.avg_speed_seconds + 's' : '—' }}</span>
            <span class="sc-sub">每题耗时</span>
          </div>
        </div>
      </div>

      <!-- 考试区块 -->
      <div class="section">
        <h3 class="section-title">考试成绩</h3>
        <div class="chart-grid">
          <div class="chart-card">
            <h4>得分率趋势</h4>
            <Line v-if="trendData" :data="trendData" :options="lineOptions" />
            <el-empty v-else description="暂无考试记录" :image-size="70" />
          </div>
          <div class="chart-card">
            <h4>题型正确率</h4>
            <Bar v-if="examTypeData" :data="examTypeData" :options="hBarOptions" />
            <el-empty v-else description="暂无作答记录" :image-size="70" />
          </div>
        </div>
      </div>

      <!-- 竞赛区块 -->
      <div class="section">
        <h3 class="section-title">竞赛表现</h3>
        <div class="chart-grid">
          <div class="chart-card">
            <h4>竞赛题型正确率</h4>
            <Bar v-if="compTypeData" :data="compTypeData" :options="hBarOptions" />
            <el-empty v-else description="暂无竞赛作答记录" :image-size="70" />
          </div>
          <div class="chart-card">
            <h4>最近战绩</h4>
            <el-empty v-if="!profile.competition.recent.length" description="暂无完赛记录" :image-size="70" />
            <div v-else class="recent-list">
              <div v-for="(r, i) in profile.competition.recent" :key="i" class="recent-item">
                <el-tag :type="r.kind === 'pk' ? 'danger' : 'primary'" size="small" effect="plain">
                  {{ r.kind === 'pk' ? 'PK' : '限时赛' }}
                </el-tag>
                <span class="r-title">{{ r.title }}</span>
                <span class="r-meta" v-if="r.kind === 'pk'">
                  <el-tag :type="r.result === 'win' ? 'success' : r.result === 'draw' ? 'info' : 'danger'" size="small">
                    {{ r.result === 'win' ? '胜' : r.result === 'draw' ? '平' : '负' }}
                  </el-tag>
                  得分 {{ r.score }}
                </span>
                <span class="r-meta" v-else>得分 {{ r.score }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  Chart as ChartJS, RadialLinearScale, LinearScale, CategoryScale,
  PointElement, LineElement, BarElement, Filler, Tooltip, Legend,
} from 'chart.js'
import { Radar, Line, Bar } from 'vue-chartjs'
import { TrendCharts } from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

ChartJS.register(RadialLinearScale, LinearScale, CategoryScale,
  PointElement, LineElement, BarElement, Filler, Tooltip, Legend)

const auth = useAuthStore()
const isTeacher = computed(() => auth.user?.role === 'teacher')

const TIER_COLORS = {
  青铜: '#b08d57', 白银: '#a8b4c4', 黄金: '#f0c14b',
  铂金: '#7fd8d8', 钻石: '#7db9f5', 王者: '#ff7a45',
}
const tierColor = (t) => TIER_COLORS[t] || 'var(--text-primary)'

const profile = ref(null)
const students = ref([])
const studentId = ref(null)

const trendData = computed(() => {
  const t = profile.value?.exam?.trend || []
  if (!t.length) return null
  return {
    labels: t.map((x) => x.title),
    datasets: [{
      label: '得分率 %',
      data: t.map((x) => Math.round(x.score_rate * 100)),
      borderColor: '#7db9f5',
      backgroundColor: 'rgba(125, 185, 245, 0.18)',
      fill: true,
      tension: 0.35,
      pointRadius: 4,
    }],
  }
})

const examTypeData = computed(() => {
  const s = profile.value?.exam?.type_stats || []
  if (!s.length) return null
  return {
    labels: s.map((x) => x.label),
    datasets: [{
      label: '正确率 %',
      data: s.map((x) => Math.round(x.accuracy * 100)),
      backgroundColor: 'rgba(103, 194, 58, 0.65)',
      borderRadius: 6,
    }],
  }
})

const compTypeData = computed(() => {
  const s = profile.value?.competition?.type_stats || []
  if (!s.length) return null
  return {
    labels: s.map((x) => x.label),
    datasets: [{
      label: '正确率 %',
      data: s.map((x) => Math.round(x.accuracy * 100)),
      backgroundColor: 'rgba(255, 122, 69, 0.65)',
      borderRadius: 6,
    }],
  }
})

const radarData = computed(() => {
  const r = profile.value?.radar
  if (!r) return null
  if (Object.values(r).every((v) => v == null)) return null
  const fill = (v) => (v == null ? 0 : v)
  return {
    labels: ['准确率', '速度', '竞技力', '稳定度', '活跃度'],
    datasets: [{
      label: '能力值',
      data: [fill(r.accuracy), fill(r.speed), fill(r.competitive), fill(r.stability), fill(r.activity)],
      backgroundColor: 'rgba(125, 185, 245, 0.25)',
      borderColor: '#7db9f5',
      pointBackgroundColor: '#7db9f5',
      pointRadius: 4,
    }],
  }
})

const radarOptions = {
  responsive: true,
  maintainAspectRatio: false,
  scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, display: false } } },
  plugins: { legend: { display: false } },
}
const lineOptions = {
  responsive: true,
  maintainAspectRatio: false,
  scales: { y: { min: 0, max: 100, ticks: { callback: (v) => v + '%' } } },
  plugins: { legend: { display: false } },
}
const hBarOptions = {
  responsive: true,
  maintainAspectRatio: false,
  indexAxis: 'y',
  scales: { x: { min: 0, max: 100, ticks: { callback: (v) => v + '%' } } },
  plugins: { legend: { display: false } },
}

const load = async () => {
  const url = isTeacher.value && studentId.value
    ? `/api/profile/study/${studentId.value}`
    : '/api/profile/study'
  const res = await request.get(url)
  profile.value = res.data
}

onMounted(async () => {
  if (isTeacher.value) {
    // 教师端拉取学生列表用于选择
    try {
      const res = await request.get('/api/students')
      students.value = res.data || []
      if (students.value.length) {
        studentId.value = students.value[0].id
      }
    } catch (e) {
      console.warn('获取学生列表失败', e)
    }
  }
  load()
})
</script>

<style scoped>
.page-wrapper {
  max-width: 960px;
  margin: 0 auto;
}

.page-header h2 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  color: #67c23a;
}

.page-header p {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 14px;
}

.sub-info {
  font-size: 13.5px;
  color: var(--text-muted);
}

.student-select {
  width: 200px;
}

.overview-row {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 18px;
  margin-bottom: 24px;
}

@media (max-width: 820px) {
  .overview-row {
    grid-template-columns: 1fr;
  }
}

.radar-card,
.chart-card {
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 18px;
  background: var(--bg-secondary);
}

.card-title,
.chart-card h4 {
  margin: 0 0 10px 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.radar-box {
  height: 260px;
  position: relative;
}

.stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.stat-card {
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 18px 20px;
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-card.tier {
  border-color: rgba(240, 193, 75, 0.5);
}

.sc-label {
  font-size: 12.5px;
  color: var(--text-muted);
}

.sc-value {
  font-size: 26px;
  font-weight: 800;
  color: var(--text-primary);
}

.sc-sub {
  font-size: 12px;
  color: var(--text-muted);
}

.section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 12px 0;
}

.chart-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

@media (max-width: 820px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }
}

.chart-card {
  min-height: 280px;
}

.chart-card :deep(canvas) {
  max-height: 240px;
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 10px;
  background: var(--bg-tertiary);
}

.r-title {
  flex: 1;
  font-size: 13.5px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.r-meta {
  font-size: 12.5px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
