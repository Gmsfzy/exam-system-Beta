<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>我的考试</h2>
        <p>查看您被邀请参加的所有考试</p>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%)">
          <el-icon :size="24" color="white"><VideoPlay /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ availableCount }}</div>
          <div class="stat-label">可参加</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%)">
          <el-icon :size="24" color="white"><Clock /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ upcomingCount }}</div>
          <div class="stat-label">即将开始</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)">
          <el-icon :size="24" color="white"><CircleCheck /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ completedCount }}</div>
          <div class="stat-label">已完成</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
          <el-icon :size="24" color="white"><Medal /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ avgScore }}</div>
          <div class="stat-label">平均分</div>
        </div>
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="statusFilter" placeholder="全部状态" @change="loadExams">
        <el-option label="全部" value="" />
        <el-option label="可参加" value="available" />
        <el-option label="即将开始" value="upcoming" />
        <el-option label="已结束" value="ended" />
      </el-select>
      <el-input
        v-model="joinCode"
        placeholder="输入邀请码加入考试"
        clearable
        class="join-input"
        @keyup.enter="joinByCode()"
      >
        <template #append>
          <el-button type="primary" @click="joinByCode()">加入考试</el-button>
        </template>
      </el-input>
    </div>

    <div class="exam-list">
      <div v-for="exam in filteredExams" :key="exam.id" class="exam-item" :class="getExamClass(exam)">
        <div class="exam-info">
          <div class="exam-icon" :class="getExamClass(exam)">
            <el-icon :size="32" color="white">
              <VideoPlay v-if="canTakeExam(exam)" />
              <Clock v-else-if="isUpcoming(exam)" />
              <Check v-else />
            </el-icon>
          </div>
          <div class="exam-details">
            <h3 class="exam-title">{{ exam.title }}</h3>
            <p class="exam-desc">{{ exam.description || '暂无描述' }}</p>
            <div class="exam-meta">
              <span class="meta-tag">
                <el-icon :size="14"><Calendar /></el-icon>
                {{ formatDate(exam.start_time) }}
              </span>
              <span class="meta-tag">
                <el-icon :size="14"><Clock /></el-icon>
                {{ exam.duration }}分钟
              </span>
              <span class="meta-tag">
                <el-icon :size="14"><Document /></el-icon>
                {{ exam.question_count }}题
              </span>
            </div>
          </div>
        </div>
        <div class="exam-actions">
          <el-button
            v-if="canTakeExam(exam)"
            type="primary"
            @click="startExam(exam.id)"
          >
            <el-icon><Star /></el-icon>开始答题
          </el-button>
          <el-button
            v-else-if="isCompleted(exam.id)"
            type="success"
            @click="viewResult(exam.id)"
          >
            <el-icon><User /></el-icon>查看成绩
          </el-button>
          <el-button v-else type="info" disabled>
            {{ isUpcoming(exam) ? '等待开始' : '考试已结束' }}
          </el-button>
        </div>
      </div>
    </div>

    <div v-if="filteredExams.length === 0" class="empty-state">
      <div class="empty-icon">
        <el-icon :size="64" color="#cbd5e1"><Calendar /></el-icon>
      </div>
      <h3>暂无考试</h3>
      <p>教师还没有邀请您参加任何考试</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { VideoPlay, Clock, Check, CircleCheck, Calendar, Medal, Star, User } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const exams = ref([])
const results = ref([])
const statusFilter = ref('')
const joinCode = ref('')

const availableCount = computed(() => exams.value.filter(e => canTakeExam(e)).length)
const upcomingCount = computed(() => exams.value.filter(e => isUpcoming(e)).length)
const completedCount = computed(() => results.value.length)

const avgScore = computed(() => {
  if (results.value.length === 0) return '-'
  const total = results.value.reduce((sum, r) => sum + (r.score || 0), 0)
  return (total / results.value.length).toFixed(1)
})

const filteredExams = computed(() => {
  let result = exams.value
  if (statusFilter.value === 'available') {
    result = result.filter(e => canTakeExam(e))
  } else if (statusFilter.value === 'upcoming') {
    result = result.filter(e => isUpcoming(e))
  } else if (statusFilter.value === 'ended') {
    result = result.filter(e => e.status === 'ended')
  }
  return result
})

onMounted(async () => {
  // 邀请链接 /student?join=CODE 落地后自动加入
  if (route.query.join) {
    await joinByCode(route.query.join, { silent: true })
  }
  await loadExams()
  await loadResults()
})

const joinByCode = async (code, options = {}) => {
  const c = String(code || joinCode.value || '').trim()
  if (!c) {
    if (!options.silent) ElMessage.warning('请输入邀请码')
    return
  }
  try {
    const res = await request.post(`/api/exam/join/${encodeURIComponent(c.toUpperCase())}`)
    ElMessage.success(res.data.message)
    joinCode.value = ''
    await loadExams()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '加入考试失败')
  }
}

const loadExams = async () => {
  try {
    const res = await request.get('/api/exams')
    exams.value = res.data
  } catch (e) {
    console.error('加载考试失败', e)
  }
}

const loadResults = async () => {
  try {
    const res = await request.get('/api/results/me')
    results.value = res.data
  } catch (e) {
    console.error('加载成绩失败', e)
  }
}

const canTakeExam = (exam) => {
  if (exam.status !== 'published') return false
  if (isCompleted(exam.id)) return false
  const now = new Date()
  const start = new Date(exam.start_time)
  const end = new Date(exam.end_time)
  return now >= start && now <= end
}

const isUpcoming = (exam) => {
  if (exam.status !== 'published') return false
  if (isCompleted(exam.id)) return false
  const now = new Date()
  const start = new Date(exam.start_time)
  return now < start
}

const isCompleted = (examId) => {
  return results.value.some(r => r.exam_id === examId)
}

const getExamClass = (exam) => {
  if (canTakeExam(exam)) return 'available'
  if (isUpcoming(exam)) return 'upcoming'
  return 'completed'
}

const startExam = async (examId) => {
  try {
    const res = await request.post(`/api/exam/${examId}/start`)
    ElMessage.success('开始考试')
    setTimeout(() => {
      window.location.href = `/exam/take/${examId}`
    }, 500)
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '无法开始考试')
  }
}

const viewResult = (examId) => {
  const result = results.value.find(r => r.exam_id === examId)
  if (result) {
    window.location.href = `/results/${result.id}`
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}
</script>

<style scoped>
.page-wrapper {
  max-width: 900px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 32px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border-color);
}

.header-title h2 {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.header-title p {
  color: var(--text-muted);
  margin: 6px 0 0;
  font-size: 15px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 32px;
}

.stat-card {
  background: var(--bg-card);
  border-radius: 20px;
  padding: 28px;
  display: flex;
  align-items: center;
  gap: 20px;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border-color);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.stat-card::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -50%;
  width: 100%;
  height: 100%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.05) 0%, transparent 70%);
  opacity: 0;
  transition: opacity 0.4s ease;
}

.stat-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-lg);
  border-color: rgba(99, 102, 241, 0.15);
}

.stat-card:hover::before {
  opacity: 1;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.3s ease;
}

.stat-card:hover .stat-icon {
  transform: scale(1.1);
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.stat-label {
  font-size: 14px;
  color: var(--text-muted);
  margin-top: 6px;
  font-weight: 500;
}

.filter-bar {
  margin-bottom: 28px;
  padding: 16px 20px;
  background: var(--bg-card);
  border-radius: 14px;
  border: 1px solid var(--border-color);
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 16px;
}

.filter-bar .el-select {
  width: 200px;
}

.join-input {
  width: 300px;
}

.filter-bar :deep(.el-input__wrapper) {
  border-radius: 10px;
  background: var(--bg-tertiary);
  border-color: transparent;
}

.filter-bar :deep(.el-input__wrapper):focus-within {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.exam-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.exam-item {
  background: var(--bg-card);
  border-radius: 20px;
  padding: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: var(--shadow-sm);
  border: 1px solid var(--border-color);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.exam-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  transition: width 0.3s ease;
}

.exam-item.available::before { background: linear-gradient(180deg, #10b981 0%, #059669 100%); }
.exam-item.upcoming::before { background: linear-gradient(180deg, #f59e0b 0%, #d97706 100%); }
.exam-item.completed::before { background: linear-gradient(180deg, #8b5cf6 0%, #7c3aed 100%); }

.exam-item:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-lg);
  border-color: rgba(99, 102, 241, 0.15);
}

.exam-info {
  display: flex;
  gap: 20px;
  flex: 1;
}

.exam-icon {
  width: 68px;
  height: 68px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.3s ease;
}

.exam-item:hover .exam-icon {
  transform: scale(1.05);
}

.exam-icon.available {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  box-shadow: 0 4px 15px rgba(16, 185, 129, 0.3);
}

.exam-icon.upcoming {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  box-shadow: 0 4px 15px rgba(245, 158, 11, 0.3);
}

.exam-icon.completed {
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
  box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3);
}

.exam-details {
  flex: 1;
}

.exam-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.exam-desc {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0 0 14px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.exam-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}

.meta-tag {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-light);
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-radius: 10px;
  font-weight: 500;
}

.exam-actions {
  flex-shrink: 0;
}

.exam-actions .el-button {
  border-radius: 12px;
  padding: 12px 24px;
  font-weight: 600;
}

.exam-actions .el-button--primary {
  background: var(--gradient-primary);
  border: none;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.35);
}

.exam-actions .el-button--primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(102, 126, 234, 0.45);
}

.empty-state {
  text-align: center;
  padding: 80px 20px;
  background: var(--bg-card);
  border-radius: 24px;
  border: 1px dashed var(--border-color);
}

.empty-icon {
  margin-bottom: 20px;
}

.empty-state h3 {
  font-size: 20px;
  color: var(--text-primary);
  margin: 0 0 10px;
}

.empty-state p {
  color: var(--text-muted);
  margin: 0;
  font-size: 15px;
}

.dark .page-wrapper {
  background: var(--bg-secondary);
}

.dark .page-header {
  border-bottom-color: var(--glass-border);
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

.dark .stat-card:hover {
  border-color: var(--border-glow);
  box-shadow: var(--shadow-glow), var(--shadow-card);
}

.dark .stat-value {
  color: var(--text-primary);
}

.dark .stat-label {
  color: var(--text-light);
}

.dark .filter-bar {
  background: var(--bg-card);
  border: 1px solid var(--glass-border);
}

.dark .filter-bar :deep(.el-input__wrapper) {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
}

.dark .filter-bar :deep(.el-input__inner) {
  color: var(--text-primary);
}

.dark .filter-bar :deep(.el-select-dropdown) {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-color);
}

.dark .filter-bar :deep(.el-option) {
  color: var(--text-secondary);
}

.dark .filter-bar :deep(.el-option:hover) {
  background: var(--bg-hover);
}

.dark .exam-item {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-card);
}

.dark .exam-item::after {
  content: '';
  position: absolute;
  top: 0;
  left: 4px;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, rgba(99, 102, 241, 0.2) 0%, transparent 50%);
}

.dark .exam-item:hover {
  border-color: var(--border-glow);
  box-shadow: var(--shadow-glow), var(--shadow-card);
}

.dark .exam-item.available:hover {
  border-color: rgba(16, 185, 129, 0.35);
  box-shadow: 0 0 40px rgba(16, 185, 129, 0.2), var(--shadow-card);
}

.dark .exam-item.upcoming:hover {
  border-color: rgba(245, 158, 11, 0.35);
  box-shadow: 0 0 40px rgba(245, 158, 11, 0.2), var(--shadow-card);
}

.dark .exam-item.completed:hover {
  border-color: rgba(139, 92, 246, 0.35);
  box-shadow: 0 0 40px rgba(139, 92, 246, 0.2), var(--shadow-card);
}

.dark .exam-title {
  color: var(--text-primary);
}

.dark .exam-desc {
  color: var(--text-secondary);
}

.dark .meta-tag {
  color: var(--text-secondary);
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--glass-border);
}

.dark .empty-state {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px dashed var(--glass-border);
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

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .exam-item {
    flex-direction: column;
    gap: 20px;
    align-items: flex-start;
  }
  .exam-info {
    width: 100%;
  }
  .exam-actions {
    width: 100%;
  }
  .exam-actions .el-button {
    width: 100%;
  }
}
</style>