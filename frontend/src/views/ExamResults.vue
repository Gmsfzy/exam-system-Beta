<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>考试成绩</h2>
        <p>查看所有学生的答题情况和成绩</p>
      </div>
      <div class="header-actions">
        <el-button @click="goBack">返回</el-button>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
          <el-icon :size="24" color="white"><User /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ results.length }}</div>
          <div class="stat-label">参考人数</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%)">
          <el-icon :size="24" color="white"><TrendCharts /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ avgScore }}</div>
          <div class="stat-label">平均分</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%)">
          <el-icon :size="24" color="white"><Trophy /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ maxScore }}</div>
          <div class="stat-label">最高分</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)">
          <el-icon :size="24" color="white"><Medal /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ passRate }}%</div>
          <div class="stat-label">及格率</div>
        </div>
      </div>
    </div>

    <div v-if="results.length > 0" class="results-table">
      <el-table :data="results" :key="results.length" border style="width: 100%" max-height="600">
        <el-table-column prop="student_name" label="学生姓名" width="150" />
        <el-table-column prop="score" label="得分" width="120">
          <template #default="{ row }">
            <span :style="{ color: getScoreColor(row.score, row.total_score) }" class="score-text">
              {{ row.score }} / {{ row.total_score }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="submitted_at" label="提交时间" width="200">
          <template #default="{ row }">{{ formatDate(row.submitted_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" @click="viewDetail(row.id)">查看详情</el-button>
            <el-button size="small" type="primary" @click="goGrading(row.student_id)">评分</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div v-else class="empty-state">
      <div class="empty-icon">
        <el-icon :size="64" color="#cbd5e1"><User /></el-icon>
      </div>
      <h3>暂无成绩</h3>
      <p>学生提交答卷后，成绩将显示在这里</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { User, TrendCharts, Trophy, Medal } from '@element-plus/icons-vue'
import request from '../utils/request'

const goBack = () => {
  window.history.back()
}

const route = useRoute()
const results = ref([])
const examId = ref(0)

const avgScore = computed(() => {
  if (results.value.length === 0) return '-'
  const total = results.value.reduce((sum, r) => sum + (r.score || 0), 0)
  return (total / results.value.length).toFixed(1)
})

const maxScore = computed(() => {
  if (results.value.length === 0) return '-'
  return Math.max(...results.value.map(r => r.score || 0))
})

const passRate = computed(() => {
  if (results.value.length === 0) return '0'
  const total = results.value[0]?.total_score || 100
  const passed = results.value.filter(r => (r.score || 0) >= total * 0.6).length
  return Math.round((passed / results.value.length) * 100)
})

onMounted(async () => {
  examId.value = parseInt(route.params.examId)
  await loadResults(examId.value)
})

const loadResults = async (examId) => {
  try {
    const res = await request.get(`/api/results/exam/${examId}`)
    results.value = res.data
  } catch (e) {
    console.error('加载成绩失败', e)
  }
}

const viewDetail = (resultId) => {
  window.location.href = `/results/${resultId}`
}

const goGrading = (studentId) => {
  window.location.href = `/grading/${examId.value}/${studentId}`
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

const getScoreColor = (score, total) => {
  const ratio = score / total
  if (ratio >= 0.8) return '#10b981'
  if (ratio >= 0.6) return '#f59e0b'
  return '#ef4444'
}
</script>

<style scoped>
.page-wrapper {
  max-width: 1000px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.header-title h2 {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.header-title p {
  color: #94a3b8;
  margin: 6px 0 0;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

.stat-card {
  background: white;
  border-radius: 16px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1e293b;
}

.stat-label {
  font-size: 14px;
  color: #64748b;
  margin-top: 4px;
}

.results-table {
  background: white;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.score-text {
  font-weight: 600;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
}

.empty-icon {
  margin-bottom: 20px;
}

.empty-state h3 {
  font-size: 18px;
  color: #64748b;
  margin: 0 0 8px;
}

.empty-state p {
  color: #94a3b8;
  margin: 0;
}

.dark .page-wrapper {
  background: transparent;
}

.dark .header-title h2 {
  color: var(--text-primary);
}

.dark .header-title p {
  color: var(--text-light);
}

.dark .stat-card {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-card);
}

.dark .stat-value {
  color: var(--text-primary);
  font-weight: 700;
}

.dark .stat-label {
  color: var(--text-light);
}

.dark .results-table {
  background: rgba(30, 41, 59, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(148, 163, 184, 0.2);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.03);
  border-radius: 16px;
  overflow: hidden;
}

.dark .empty-state h3 {
  color: var(--text-primary);
}

.dark .empty-state p {
  color: var(--text-light);
}

.dark .empty-icon {
  color: var(--border-color);
}

.dark :deep(.el-table__header-row th) {
  border-bottom: 2px solid rgba(99, 102, 241, 0.5) !important;
  border-right: 1px solid rgba(148, 163, 184, 0.15) !important;
  font-weight: 700;
  font-size: 14px;
  padding: 16px 12px !important;
  text-align: center;
}

.dark :deep(.el-table__header-row th:last-child) {
  border-right: none !important;
}

.dark :deep(.el-table__cell) {
  border-right: 1px solid rgba(148, 163, 184, 0.08) !important;
  padding: 14px 12px !important;
  font-size: 14px;
  vertical-align: middle;
}

.dark :deep(.el-table__cell:last-child) {
  border-right: none !important;
}

.dark :deep(.el-table--border) {
  border: none !important;
}

.dark :deep(.el-table__body-wrapper::-webkit-scrollbar) {
  width: 6px;
  height: 6px;
}

.dark :deep(.el-table__body-wrapper::-webkit-scrollbar-track) {
  background: rgba(15, 23, 42, 0.5);
}

.dark :deep(.el-table__body-wrapper::-webkit-scrollbar-thumb) {
  background: #475569;
  border-radius: 3px;
}

.dark :deep(.el-table__body-wrapper::-webkit-scrollbar-thumb:hover) {
  background: #64748b;
}

.dark .header-actions .el-button {
  background: rgba(51, 65, 85, 0.8) !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
  color: #e2e8f0 !important;
}

.dark .header-actions .el-button:hover {
  background: rgba(99, 102, 241, 0.2) !important;
  border-color: rgba(99, 102, 241, 0.3) !important;
}

.dark .score-text {
  font-weight: 700;
  font-size: 15px;
}

.dark .stats-row {
  gap: 16px;
}

.dark .stat-card {
  background: rgba(30, 41, 59, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.15);
}

.dark .stat-value {
  color: #ffffff;
}

.dark .stat-label {
  color: #94a3b8;
}
</style>