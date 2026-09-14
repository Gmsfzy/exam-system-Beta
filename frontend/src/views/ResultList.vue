<template>
  <div class="page-wrapper">
    <!-- 教师：成绩管理（所创建考试的学生成绩统计） -->
    <template v-if="isTeacher">
      <div class="page-header">
        <div class="header-title">
          <h2>成绩管理</h2>
          <p>查看您创建的考试的学生成绩</p>
        </div>
      </div>

      <div v-if="exams.length > 0" class="exam-list">
        <div v-for="exam in exams" :key="exam.id" class="exam-card">
          <div class="exam-info">
            <div class="exam-icon">
              <el-icon :size="40" color="#6366f1">
                <Document />
              </el-icon>
            </div>
            <div class="exam-details">
              <h3 class="exam-title">{{ exam.title }}</h3>
              <div class="exam-meta">
                <span class="meta-item">
                  <el-icon :size="14"><Calendar /></el-icon>
                  {{ formatDate(exam.created_at) }}
                </span>
                <span class="meta-item">
                  <el-icon :size="14"><User /></el-icon>
                  {{ exam.student_count }} 名学生参加
                </span>
              </div>
            </div>
          </div>
          <div class="exam-score">
            <div class="stat-item">
              <div class="stat-value">{{ exam.avg_score || 0 }}</div>
              <div class="stat-label">平均分</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">{{ exam.highest_score || 0 }}</div>
              <div class="stat-label">最高分</div>
            </div>
          </div>
          <div class="exam-actions">
            <el-button type="primary" @click="viewExamResults(exam.id)">
              <el-icon><List /></el-icon>查看成绩
            </el-button>
          </div>
        </div>
      </div>

      <div v-else class="empty-state">
        <div class="empty-icon">
          <el-icon :size="64" color="#cbd5e1"><Document /></el-icon>
        </div>
        <h3>暂无考试</h3>
        <p>创建考试后，学生的成绩将显示在这里</p>
      </div>
    </template>

    <!-- 学生：成绩查询（本人各场考试成绩） -->
    <template v-else>
      <div class="page-header">
        <div class="header-title">
          <h2>成绩查询</h2>
          <p>查看您参加过的所有考试成绩</p>
        </div>
      </div>

      <div v-if="results.length > 0" class="exam-list">
        <div v-for="r in results" :key="r.id" class="exam-card">
          <div class="exam-info">
            <div class="exam-icon">
              <el-icon :size="40" color="#6366f1">
                <Document />
              </el-icon>
            </div>
            <div class="exam-details">
              <h3 class="exam-title">{{ r.exam_title }}</h3>
              <div class="exam-meta">
                <span class="meta-item">
                  <el-icon :size="14"><Calendar /></el-icon>
                  提交时间：{{ formatDate(r.submitted_at) }}
                </span>
              </div>
            </div>
          </div>
          <div class="exam-score">
            <div class="stat-item">
              <div class="stat-value">{{ r.score ?? '待评' }}</div>
              <div class="stat-label">我的得分</div>
            </div>
            <div class="stat-item">
              <div class="stat-value">{{ r.total_score || 0 }}</div>
              <div class="stat-label">总分</div>
            </div>
          </div>
          <div class="exam-actions">
            <el-button type="primary" @click="viewResultDetail(r.id)">
              <el-icon><List /></el-icon>查看详情
            </el-button>
          </div>
        </div>
      </div>

      <div v-else class="empty-state">
        <div class="empty-icon">
          <el-icon :size="64" color="#cbd5e1"><Document /></el-icon>
        </div>
        <h3>暂无成绩</h3>
        <p>完成考试后，成绩将显示在这里</p>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Document, Calendar, User, List } from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isTeacher = computed(() => auth.user?.role === 'teacher')

const exams = ref([])
const results = ref([])

onMounted(async () => {
  if (isTeacher.value) {
    await loadExams()
  } else {
    await loadMyResults()
  }
})

// ── 教师：所创建考试的成绩统计 ──
const loadExams = async () => {
  try {
    const res = await request.get('/api/exams')
    exams.value = res.data.map(exam => ({
      ...exam,
      student_count: 0,
      avg_score: 0,
      highest_score: 0
    }))
    await loadExamStats()
  } catch (e) {
    console.error('加载考试列表失败', e)
  }
}

const loadExamStats = async () => {
  for (const exam of exams.value) {
    try {
      const res = await request.get(`/api/results/exam/${exam.id}`)
      const examResults = res.data
      exam.student_count = examResults.length
      if (examResults.length > 0) {
        const scores = examResults.map(r => r.score)
        exam.avg_score = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
        exam.highest_score = Math.max(...scores)
      }
    } catch (e) {
      console.error(`加载考试 ${exam.id} 统计失败`, e)
    }
  }
}

const viewExamResults = (examId) => {
  window.location.href = `/results/exam/${examId}`
}

// ── 学生：本人各场考试成绩 ──
const loadMyResults = async () => {
  try {
    const res = await request.get('/api/results/me')
    results.value = res.data
  } catch (e) {
    console.error('加载我的成绩失败', e)
  }
}

const viewResultDetail = (resultId) => {
  window.location.href = `/results/${resultId}`
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}
</script>

<style scoped>
.page-wrapper {
  max-width: 800px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
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

.exam-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.exam-card {
  background: white;
  border-radius: 16px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.exam-info {
  display: flex;
  gap: 16px;
  flex: 1;
}

.exam-icon {
  width: 56px;
  height: 56px;
  background: #e0e7ff;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.exam-details h3 {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 8px;
}

.exam-meta {
  display: flex;
  gap: 16px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #94a3b8;
}

.exam-score {
  display: flex;
  gap: 24px;
  min-width: 160px;
}

.stat-item {
  text-align: center;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
}

.stat-label {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
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

/* 暗色模式 */
.dark .page-wrapper {
  background: #0f172a;
}

.dark .header-title h2 {
  color: #f1f5f9;
}

.dark .header-title p {
  color: #94a3b8;
}

.dark .exam-card {
  background: #1e293b;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

.dark .exam-icon {
  background: rgba(99, 102, 241, 0.2);
}

.dark .exam-details h3 {
  color: #f1f5f9;
}

.dark .meta-item {
  color: #94a3b8;
}

.dark .stat-value {
  color: #f1f5f9;
}

.dark .stat-label {
  color: #94a3b8;
}

.dark .empty-state {
  background: transparent;
}

.dark .empty-state h3 {
  color: #f1f5f9;
}

.dark .empty-state p {
  color: #94a3b8;
}

.dark .empty-icon {
  color: #334155;
}

.dark .exam-card {
  border: 1px solid #334155;
}

.dark .el-button {
  background: #334155;
  border-color: #475569;
  color: #f1f5f9;
}

.dark .el-button:hover {
  background: #475569;
  border-color: #64748b;
}

.dark .el-button--primary {
  background: #6366f1;
  border-color: #6366f1;
}

.dark .el-button--primary:hover {
  background: #4f46e5;
  border-color: #4f46e5;
}
</style>