<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>成绩详情</h2>
        <p>{{ resultData.exam_title }}</p>
      </div>
      <div class="header-score" v-if="resultData.published !== false">
        <div class="score-circle">
          <span class="score-num">{{ resultData.score }}</span>
          <span class="score-label">分</span>
        </div>
        <div class="score-total">满分 {{ resultData.total_score }}</div>
      </div>
    </div>

    <!-- v4.3 成绩发布控制：未发布占位 -->
    <el-card v-if="resultData.published === false" shadow="never" style="margin-bottom: 24px">
      <el-result icon="info" title="成绩尚未发布" sub-title="教师发布成绩后，您即可查看得分与每题解析">
      </el-result>
      <template #footer>
        <el-button @click="goBack">返回</el-button>
      </template>
    </el-card>

    <!-- v4.3 成绩申诉状态条 -->
    <div v-if="resultData.published !== false && resultData.review_status && resultData.review_status !== 'none'" :class="['review-bar', resultData.review_status]">
      <template v-if="resultData.review_status === 'requested'">
        <el-icon><Clock /></el-icon> 申诉复核中，请耐心等待教师处理
      </template>
      <template v-else-if="resultData.review_status === 'resolved'">
        <el-icon><Check /></el-icon> 申诉已成立<span v-if="resultData.review_reply">：{{ resultData.review_reply }}</span>
      </template>
      <template v-else-if="resultData.review_status === 'rejected'">
        <el-icon><Close /></el-icon> 申诉未通过<span v-if="resultData.review_reply">：{{ resultData.review_reply }}</span>
      </template>
    </div>

    <div v-if="resultData.ai_analysis" class="analysis-card">
      <h3 class="card-title">
        <el-icon><InfoFilled /></el-icon> AI分析报告
      </h3>
      <div class="analysis-content">{{ resultData.ai_analysis }}</div>
    </div>

    <el-alert
      v-if="resultData.answers_released === false"
      title="考试尚未结束，正确答案与解析暂未公布"
      description="到达考试截止时间或教师结束考试后，即可在此查看每题的正确答案与解析。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    />

    <div class="questions-section" v-if="resultData.published !== false">
      <h3 class="section-title">答题详情</h3>
      <div v-for="(answer, index) in resultData.answers" :key="answer.question_id" class="question-item" :class="{ correct: answer.is_correct, wrong: !answer.is_correct && answer.student_answer }">
        <div class="question-header">
          <span class="question-number">第 {{ index + 1 }} 题</span>
          <span class="badge-type">{{ typeLabels[answer.type] }}</span>
          <span v-if="answer.oj_verdict" class="badge-oj" :class="{ ac: answer.oj_verdict === 'AC' }">OJ {{ answer.oj_verdict }}</span>
          <span v-if="answer.is_correct" class="badge-result correct">
            <el-icon><Check /></el-icon>正确
          </span>
          <span v-else-if="answer.student_answer" class="badge-result wrong">
            <el-icon><Close /></el-icon>错误
          </span>
          <span v-else class="badge-result">
            <el-icon><Minus /></el-icon>未答
          </span>
        </div>
        <div class="question-content">{{ answer.content }}</div>
        <div v-if="answer.options" class="options-list">
          <div v-for="(opt, idx) in getOptions(answer.options)" :key="idx" class="option-item">
            <span class="option-key">{{ opt.key }}</span>
            <span class="option-text">{{ opt.value }}</span>
          </div>
        </div>
        <div class="answer-section">
          <div class="answer-row">
            <span class="answer-label">您的答案：</span>
            <span class="answer-value">{{ answer.student_answer || '未作答' }}</span>
          </div>
          <div v-if="resultData.answers_released" class="answer-row">
            <span class="answer-label">正确答案：</span>
            <span class="answer-value correct">{{ answer.correct_answer }}</span>
          </div>
          <div v-if="resultData.answers_released && answer.analysis" class="answer-row">
            <span class="answer-label">解析：</span>
            <span class="answer-value analysis">{{ answer.analysis }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="page-footer" v-if="resultData.published !== false">
      <el-button
        v-if="resultData.can_review"
        type="warning"
        plain
        @click="submitReview"
      >成绩申诉</el-button>
      <el-button @click="goBack">返回</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled, Check, Close, Minus, Clock } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const router = useRouter()

const resultData = ref({
  exam_title: '',
  score: 0,
  total_score: 0,
  ai_analysis: '',
  answers: []
})

// v4.6.1 枚举收敛：题型中文名单一来源 frontend/src/utils/enums.js
import { QUESTION_TYPE_LABELS } from '../utils/enums'

const typeLabels = QUESTION_TYPE_LABELS

onMounted(async () => {
  const resultId = parseInt(route.params.id)
  await loadResult(resultId)
})

const loadResult = async (id) => {
  try {
    const res = await request.get(`/api/results/${id}`)
    resultData.value = { ...res.data }
  } catch (e) {
    console.error('加载成绩详情失败', e)
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

const goBack = () => {
  router.push('/results')
}

// v4.3 成绩申诉
const submitReview = async () => {
  try {
    const { value } = await ElMessageBox.prompt(
      '请说明申诉理由（如：某题答案应为正确、评分系统误判等），教师将人工复核',
      '成绩申诉',
      { inputType: 'textarea', inputValidator: (v) => (v && v.trim().length >= 5) || '至少输入 5 个字', confirmButtonText: '提交申诉' }
    )
    await request.post(`/api/results/${route.params.id}/review`, { reason: value.trim() })
    ElMessage.success('申诉已提交，复核结果将通知您')
    await loadResult(parseInt(route.params.id))
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') console.error(e)
  }
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
  color: #64748b;
  margin: 6px 0 0;
}

.header-score {
  text-align: center;
}

.score-circle {
  width: 100px;
  height: 100px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: white;
}

.score-num {
  font-size: 32px;
  font-weight: 700;
}

.score-label {
  font-size: 14px;
}

.score-total {
  margin-top: 8px;
  font-size: 14px;
  color: #64748b;
}

.analysis-card {
  background: linear-gradient(135deg, #f0fdf4 0%, #fef3c7 100%);
  border-radius: 16px;
  padding: 20px;
  margin-bottom: 24px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 12px;
}

.analysis-content {
  font-size: 14px;
  color: #475569;
  line-height: 1.8;
}

.questions-section {
  background: white;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 20px;
}

.question-item {
  padding: 20px;
  border-radius: 12px;
  margin-bottom: 16px;
  background: #f8fafc;
  border-left: 4px solid #e2e8f0;
}

.question-item.correct {
  border-left-color: #10b981;
}

.question-item.wrong {
  border-left-color: #ef4444;
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

.badge-oj {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  background: #ffedd5;
  color: #ea580c;
}

.badge-oj.ac {
  background: #dcfce7;
  color: #16a34a;
}

.badge-result {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 4px;
}

.badge-result.correct {
  background: #dcfce7;
  color: #16a34a;
}

.badge-result.wrong {
  background: #fee2e2;
  color: #dc2626;
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
}

.answer-value.analysis {
  color: #64748b;
}

.page-footer {
  text-align: center;
  margin-top: 24px;
}

.review-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-radius: 12px;
  margin-bottom: 16px;
  font-size: 14px;
}

.review-bar.requested {
  background: #fef3c7;
  color: #92400e;
}

.review-bar.resolved {
  background: #dcfce7;
  color: #166534;
}

.review-bar.rejected {
  background: #f1f5f9;
  color: #475569;
}

.dark .review-bar.requested {
  background: rgba(245, 158, 11, 0.15);
  color: #fcd34d;
}

.dark .review-bar.resolved {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

.dark .review-bar.rejected {
  background: rgba(100, 116, 139, 0.15);
  color: #94a3b8;
}

/* 暗色模式 */
.dark .header-title h2 {
  color: #f1f5f9;
}

.dark .header-title p {
  color: #94a3b8;
}

.dark .score-total {
  color: #94a3b8;
}

.dark .analysis-card {
  background: linear-gradient(135deg, #1e3a3a 0%, #3a2a1e 100%);
}

.dark .card-title {
  color: #f1f5f9;
}

.dark .analysis-content {
  color: #cbd5e1;
}

.dark .questions-section {
  background: #1e293b;
  border: 1px solid #334155;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

.dark .section-title {
  color: #f1f5f9;
}

.dark .question-item {
  background: #0f172a;
  border-left-color: #475569;
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

.dark .badge-result {
  background: #334155;
  color: #cbd5e1;
}

.dark .badge-result.correct {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.dark .badge-result.wrong {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
}

.dark .question-content {
  color: #e2e8f0;
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
  background: #1e293b;
}

.dark .answer-label {
  color: #94a3b8;
}

.dark .answer-value {
  color: #e2e8f0;
}

.dark .answer-value.correct {
  color: #34d399;
}

.dark .answer-value.analysis {
  color: #94a3b8;
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
</style>