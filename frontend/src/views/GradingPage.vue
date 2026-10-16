<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>人工评分</h2>
        <p>为学生的主观题进行人工评分</p>
      </div>
      <div class="header-info">
        <span>学生：{{ gradingData.student_name }}</span>
        <span v-if="gradingData.attempt_no > 1">第 {{ gradingData.attempt_no }} 次作答</span>
        <span>当前得分：{{ gradingData.current_score }} / {{ gradingData.total_score }}</span>
      </div>
    </div>

    <div v-if="gradingData.answers && gradingData.answers.length > 0" class="questions-section">
      <div v-for="answer in gradingData.answers" :key="answer.answer_id" class="question-item" :class="{ pending: answer.needs_manual_grade }">
        <div class="question-header">
          <span class="question-number">第 {{ gradingData.answers.indexOf(answer) + 1 }} 题</span>
          <span class="badge-type">{{ typeLabels[answer.type] }}</span>
          <span v-if="answer.oj_verdict" class="badge-oj" :class="{ ac: answer.oj_verdict === 'AC' }">OJ {{ answer.oj_verdict }}</span>
          <span v-if="answer.needs_manual_grade" class="badge-pending">需人工评分</span>
        </div>
        <div class="question-content"><RichContent :content="answer.content || ''" /></div>
        <div v-if="answer.options" class="options-list">
          <div v-for="(opt, idx) in getOptions(answer.options)" :key="idx" class="option-item">
            <span class="option-key">{{ opt.key }}</span>
            <span class="option-text"><RichContent :content="String(opt.value ?? '')" /></span>
          </div>
        </div>
        <div class="answer-section">
          <div class="answer-row">
            <span class="answer-label">学生答案：</span>
            <span class="answer-value">{{ answer.student_answer || '未作答' }}</span>
          </div>
          <div class="answer-row">
            <span class="answer-label">正确答案：</span>
            <span class="answer-value correct"><RichContent :content="String(answer.correct_answer ?? '')" /></span>
          </div>
        </div>
        <div v-if="answer.needs_manual_grade" class="grading-section">
          <div class="grading-row">
            <span class="grading-label">AI评分：</span>
            <span class="grading-value">{{ answer.ai_score || 0 }} / {{ answer.score_weight }}</span>
          </div>
          <div class="grading-row">
            <span class="grading-label">人工评分：</span>
            <el-input-number
              v-model="answer.manual_score"
              :min="0"
              :max="answer.score_weight"
              class="score-input"
            />
          </div>
          <div class="grading-row">
            <span class="grading-label">评语：</span>
            <el-input
              v-model="answer.manual_comment"
              type="textarea"
              :rows="2"
              placeholder="输入评语..."
              class="comment-input"
            />
          </div>
        </div>
        <div v-else class="graded-section">
          <div v-if="answer.oj_verdict" class="grading-row">
            <span class="grading-label">OJ 评测：</span>
            <span class="grading-value">{{ answer.oj_verdict === 'AC' ? '全部用例通过' : answer.oj_verdict + '（按用例通过率得分）' }}</span>
          </div>
          <div class="grading-row">
            <span class="grading-label">最终得分：</span>
            <span class="grading-value">{{ answer.manual_score || answer.ai_score || 0 }} / {{ answer.score_weight }}</span>
          </div>
          <div v-if="answer.manual_comment" class="grading-row">
            <span class="grading-label">评语：</span>
            <span class="grading-value">{{ answer.manual_comment }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="page-footer">
      <el-button @click="goBack">返回</el-button>
      <el-button
        v-if="pendingCount > 0"
        type="warning"
        plain
        @click="acceptAiAll"
      >一键采纳 AI 评分（{{ pendingCount }} 题）</el-button>
      <el-button type="primary" @click="saveGrading">保存评分</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import RichContent from '../components/RichContent.vue'

const route = useRoute()
const router = useRouter()

const gradingData = ref({
  student_name: '',
  current_score: 0,
  total_score: 0,
  answers: []
})

// v4.6.1 枚举收敛：题型中文名单一来源 frontend/src/utils/enums.js
import { QUESTION_TYPE_LABELS } from '../utils/enums'

const typeLabels = QUESTION_TYPE_LABELS

onMounted(async () => {
  const examId = parseInt(route.params.examId)
  const studentId = parseInt(route.params.studentId)
  await loadGrading(examId, studentId)
})

const loadGrading = async (examId, studentId) => {
  try {
    const res = await request.get(`/api/results/grading/${examId}/${studentId}`)
    gradingData.value = res.data
  } catch (e) {
    console.error('加载评分数据失败', e)
    console.error('响应状态:', e.response?.status)
    console.error('响应数据:', e.response?.data)
  }
}

const getOptions = (optionsStr) => {
  try {
    const options = JSON.parse(optionsStr)
    return Object.entries(options).map(([key, value]) => ({ key, value }))
  } catch {
    return []
  }
}

const pendingCount = computed(() =>
  (gradingData.value.answers || []).filter(a => a.needs_manual_grade).length)

// v4.3 批改提效：待人工题一键采用 AI 评分
const acceptAiAll = async () => {
  try {
    await ElMessageBox.confirm(
      `确认将 ${pendingCount.value} 道待人工题直接采纳 AI 评分？采纳后仍可在保存前手动调整`,
      '一键采纳 AI 评分', { type: 'warning' }
    )
  } catch (e) { return }
  const examId = parseInt(route.params.examId)
  const studentId = parseInt(route.params.studentId)
  try {
    const res = await request.post(`/api/results/grading/${examId}/${studentId}`, { accept_ai_all: true })
    ElMessage.success(res.data.message || '已采纳 AI 评分')
    await loadGrading(examId, studentId)
  } catch (e) {
    console.error(e)
  }
}

const saveGrading = async () => {
  const examId = parseInt(route.params.examId)
  const studentId = parseInt(route.params.studentId)
  
  try {
    await request.post(`/api/results/grading/${examId}/${studentId}`, {
      answers: gradingData.value.answers.map(a => ({
        answer_id: a.answer_id,
        manual_score: a.manual_score,
        manual_comment: a.manual_comment
      }))
    })
    ElMessage.success('评分保存成功')
    goBack()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '保存失败')
  }
}

const goBack = () => {
  router.push('/exams')
}
</script>

<style scoped>
.page-wrapper {
  max-width: 800px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
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

.header-info {
  display: flex;
  gap: 20px;
  font-size: 14px;
  color: #64748b;
}

.questions-section {
  background: white;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.question-item {
  padding: 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  background: #f8fafc;
  border-left: 4px solid #e2e8f0;
}

.question-item.pending {
  border-left-color: #f59e0b;
  background: #fffbeb;
}

.question-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.question-number {
  font-size: 14px;
  font-weight: 600;
  color: #334155;
}

.badge-type {
  padding: 4px 10px;
  background: #e0e7ff;
  color: #6366f1;
  border-radius: 16px;
  font-size: 12px;
}

.badge-pending {
  padding: 4px 10px;
  background: #fef3c7;
  color: #d97706;
  border-radius: 16px;
  font-size: 12px;
}

.badge-oj {
  padding: 4px 10px;
  background: #ffedd5;
  color: #ea580c;
  border-radius: 16px;
  font-size: 12px;
}

.badge-oj.ac {
  background: #dcfce7;
  color: #16a34a;
}

.question-content {
  font-size: 15px;
  line-height: 1.6;
  color: #1e293b;
  margin-bottom: 16px;
}

.options-list {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}

.option-item {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  background: white;
  border-radius: 8px;
  font-size: 14px;
}

.option-key {
  font-weight: 600;
  color: #64748b;
}

.option-text {
  color: #475569;
}

.answer-section {
  background: white;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}

.answer-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.answer-row:last-child {
  margin-bottom: 0;
}

.answer-label {
  font-size: 14px;
  font-weight: 500;
  color: #64748b;
}

.answer-value {
  font-size: 14px;
  color: #1e293b;
}

.answer-value.correct {
  color: #10b981;
  font-weight: 600;
}

.grading-section {
  background: #fffbeb;
  border-radius: 8px;
  padding: 16px;
}

.grading-row {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
  align-items: center;
}

.grading-row:last-child {
  margin-bottom: 0;
}

.grading-label {
  font-size: 14px;
  font-weight: 500;
  color: #92400e;
  width: 70px;
}

.grading-value {
  font-size: 14px;
  color: #78350f;
}

.score-input {
  width: 120px;
}

.comment-input {
  flex: 1;
}

.graded-section {
  background: #f0fdf4;
  border-radius: 8px;
  padding: 16px;
}

.page-footer {
  margin-top: 24px;
  text-align: center;
}

.dark .header-title h2 {
  color: #f1f5f9;
}

.dark .header-title p {
  color: #94a3b8;
}

.dark .header-info {
  color: #94a3b8;
}

.dark .questions-section {
  background: #1e293b;
  border: 1px solid #334155;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

.dark .question-item {
  background: #0f172a;
  border-left-color: #475569;
}

.dark .question-item.pending {
  border-left-color: #f59e0b;
  background: rgba(245, 158, 11, 0.1);
}

.dark .question-number {
  color: #cbd5e1;
}

.dark .badge-type {
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
}

.dark .badge-oj {
  background: rgba(234, 88, 12, 0.2);
  color: #fdba74;
}

.dark .badge-oj.ac {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.dark .badge-pending {
  background: rgba(245, 158, 11, 0.2);
  color: #fcd34d;
}

.dark .question-content {
  color: #f1f5f9;
}

.dark .option-item {
  background: #1e293b;
}

.dark .option-key {
  color: #94a3b8;
}

.dark .option-text {
  color: #cbd5e1;
}

.dark .answer-section {
  background: #0f172a;
}

.dark .answer-label {
  color: #94a3b8;
}

.dark .answer-value {
  color: #f1f5f9;
}

.dark .grading-section {
  background: rgba(245, 158, 11, 0.1);
}

.dark .grading-label {
  color: #fcd34d;
}

.dark .grading-value {
  color: #fef3c7;
}

.dark .graded-section {
  background: rgba(16, 185, 129, 0.1);
}
</style>