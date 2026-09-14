<template>
  <div class="exam-wrapper">
    <div class="exam-header">
      <div class="exam-info">
        <h2>{{ examInfo.title }}</h2>
        <p>{{ examInfo.description }}</p>
      </div>
      <div class="exam-timer" :class="{ warning: remainingTime < 300 }">
        <el-icon :size="20"><Clock /></el-icon>
        <span>{{ formatTime(remainingTime) }}</span>
      </div>
    </div>

    <transition name="slide-down">
      <div v-if="showSwitchWarning" class="switch-warning">
        <el-icon :size="20"><Warning /></el-icon>
        <span>检测到切屏行为！已记录第 {{ switchCount }} 次切屏，请返回考试界面继续作答。</span>
      </div>
    </transition>

    <div class="exam-body">
      <div class="question-nav">
        <h3>题目导航</h3>
        <div class="nav-grid">
          <div
            v-for="(q, index) in questions"
            :key="q.id"
            class="nav-item"
            :class="{ active: currentIndex === index, answered: answers[q.id] }"
            @click="currentIndex = index"
          >
            {{ index + 1 }}
          </div>
        </div>
        <div class="nav-legend">
          <span><span class="legend-dot answered"></span>已答</span>
          <span><span class="legend-dot"></span>未答</span>
        </div>
      </div>

      <div class="question-area">
        <div class="question-header">
          <div class="question-meta">
            <span class="badge-type" :class="currentQuestion.type">{{ typeLabels[currentQuestion.type] }}</span>
            <span class="badge-diff" :class="currentQuestion.difficulty">{{ diffLabels[currentQuestion.difficulty] }}</span>
          </div>
          <span class="question-number">第 {{ currentIndex + 1 }} / {{ questions.length }} 题</span>
        </div>

        <div class="question-content">
          <p>{{ currentQuestion.content }}</p>
        </div>

        <div v-if="currentQuestion.type === 'single_choice'" class="options-list">
          <div
            v-for="(opt, idx) in getOptions(currentQuestion.options)"
            :key="idx"
            class="option-item"
            :class="{ selected: answers[currentQuestion.id] === opt.key }"
            @click="selectOption(opt.key)"
          >
            <span class="option-key">{{ opt.key }}</span>
            <span class="option-text">{{ opt.value }}</span>
          </div>
        </div>

        <div v-else-if="currentQuestion.type === 'multiple_choice'" class="options-list">
          <div
            v-for="(opt, idx) in getOptions(currentQuestion.options)"
            :key="idx"
            class="option-item"
            :class="{ selected: isOptionSelected(currentQuestion.id, opt.key) }"
            @click="toggleOption(currentQuestion.id, opt.key)"
          >
            <span class="option-key">{{ opt.key }}</span>
            <span class="option-text">{{ opt.value }}</span>
          </div>
        </div>

        <div v-else-if="currentQuestion.type === 'true_false'" class="options-list">
          <div
            class="option-item"
            :class="{ selected: answers[currentQuestion.id] === 'true' }"
            @click="answers[currentQuestion.id] = 'true'"
          >
            <span class="option-key">√</span>
            <span class="option-text">正确</span>
          </div>
          <div
            class="option-item"
            :class="{ selected: answers[currentQuestion.id] === 'false' }"
            @click="answers[currentQuestion.id] = 'false'"
          >
            <span class="option-key">×</span>
            <span class="option-text">错误</span>
          </div>
        </div>

        <div v-else class="answer-input">
          <el-input
            v-model="answers[currentQuestion.id]"
            type="textarea"
            :rows="4"
            placeholder="请输入您的答案..."
            @input="saveAnswer"
          />
        </div>

        <div class="question-footer">
          <el-button v-if="currentIndex > 0" @click="prevQuestion">上一题</el-button>
          <el-button v-if="currentIndex < questions.length - 1" type="primary" @click="nextQuestion">下一题</el-button>
          <el-button v-if="currentIndex === questions.length - 1" type="success" @click="submitExam">提交试卷</el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="showSubmitConfirm" title="确认提交" width="400px">
      <p>您已完成 <span class="highlight">{{ answeredCount }}</span> / {{ questions.length }} 道题目</p>
      <p v-if="unansweredCount > 0" class="warning-text">还有 {{ unansweredCount }} 道题目未作答</p>
      <p>提交后将无法修改，确定要提交吗？</p>
      <template #footer>
        <el-button @click="showSubmitConfirm = false">继续答题</el-button>
        <el-button type="danger" @click="confirmSubmit">确认提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Clock, Warning } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const router = useRouter()

const examInfo = ref({ title: '', description: '', duration: 60 })
const questions = ref([])
const currentIndex = ref(0)
const answers = ref({})
const sessionId = ref(null)
const remainingTime = ref(0)
const showSubmitConfirm = ref(false)
let timer = null

const typeLabels = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  fill_blank: '填空题',
  true_false: '判断题',
  short_answer: '问答题',
  programming: '编程题',
  application: '应用题',
  calculation: '计算题'
}

const diffLabels = {
  easy: '简单',
  medium: '中等',
  hard: '困难'
}

const currentQuestion = computed(() => questions.value[currentIndex.value] || {})

const answeredCount = computed(() => {
  return questions.value.filter(q => answers.value[q.id] && String(answers.value[q.id]).trim()).length
})

const unansweredCount = computed(() => questions.value.length - answeredCount.value)

const switchCount = ref(0)
const showSwitchWarning = ref(false)
let switchWarningTimer = null

const handleVisibilityChange = async () => {
  if (document.hidden && sessionId.value) {
    try {
      const res = await request.post(`/api/exam/${route.params.examId}/report_switch`)
      switchCount.value = res.data.switch_count
      showSwitchWarning.value = true
      if (switchWarningTimer) clearTimeout(switchWarningTimer)
      switchWarningTimer = setTimeout(() => { showSwitchWarning.value = false }, 4000)
    } catch (e) { /* 静默失败，不影响答题 */ }
  }
}

const handleWindowBlur = async () => {
  if (sessionId.value) {
    try {
      const res = await request.post(`/api/exam/${route.params.examId}/report_switch`)
      switchCount.value = res.data.switch_count
      showSwitchWarning.value = true
      if (switchWarningTimer) clearTimeout(switchWarningTimer)
      switchWarningTimer = setTimeout(() => { showSwitchWarning.value = false }, 4000)
    } catch (e) { /* 静默 */ }
  }
}

onMounted(async () => {
  const examId = parseInt(route.params.examId)
  await loadExam(examId)
  startTimer()
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('blur', handleWindowBlur)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (switchWarningTimer) clearTimeout(switchWarningTimer)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('blur', handleWindowBlur)
})

const loadExam = async (examId) => {
  try {
    const res = await request.get(`/api/exam/${examId}/take`)
    examInfo.value = res.data.exam
    questions.value = res.data.questions
    sessionId.value = res.data.session_id
    
    questions.value.forEach(q => {
      if (q.student_answer) {
        answers.value[q.id] = q.student_answer
      }
    })
    
    const endTime = new Date(examInfo.value.end_time)
    const now = new Date()
    remainingTime.value = Math.max(0, Math.floor((endTime - now) / 1000))
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '加载考试失败')
    router.push('/')
  }
}

const startTimer = () => {
  timer = setInterval(() => {
    if (remainingTime.value > 0) {
      remainingTime.value--
    } else {
      clearInterval(timer)
      submitExam()
    }
  }, 1000)
}

const formatTime = (seconds) => {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

const getOptions = (optionsStr) => {
  try {
    const options = JSON.parse(optionsStr)
    return Object.entries(options).map(([key, value]) => ({ key, value }))
  } catch {
    return []
  }
}

const selectOption = (key) => {
  answers.value[currentQuestion.value.id] = key
  saveAnswer()
}

const isOptionSelected = (qId, key) => {
  const val = answers.value[qId]
  if (!val) return false
  return val.includes(key)
}

const toggleOption = (qId, key) => {
  let current = answers.value[qId] || ''
  if (current.includes(key)) {
    current = current.replace(key, '').replace(/,,/g, ',').replace(/^,|,$/g, '')
  } else {
    current = (current + ',' + key).replace(/^,/, '')
  }
  answers.value[qId] = current
  saveAnswer()
}

const saveAnswer = async () => {
  if (!sessionId.value) return
  const qId = currentQuestion.value.id
  try {
    await request.post(`/api/exam/${route.params.examId}/save_answer`, {
      session_id: sessionId.value,
      question_id: qId,
      answer: answers.value[qId] || ''
    })
  } catch (e) {
    console.error('保存答案失败', e)
  }
}

const prevQuestion = () => {
  if (currentIndex.value > 0) {
    currentIndex.value--
  }
}

const nextQuestion = () => {
  if (currentIndex.value < questions.value.length - 1) {
    currentIndex.value++
  }
}

const submitExam = () => {
  showSubmitConfirm.value = true
}

const confirmSubmit = async () => {
  showSubmitConfirm.value = false
  try {
    await request.post(`/api/exam/${route.params.examId}/submit`, {
      session_id: sessionId.value
    })
    ElMessage.success('提交成功！')
    setTimeout(() => {
      router.push('/')
    }, 1500)
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '提交失败')
  }
}
</script>

<style scoped>
.exam-wrapper {
  min-height: 100vh;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
}

.exam-header {
  background: white;
  padding: 20px 32px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.exam-info h2 {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.exam-info p {
  color: #64748b;
  margin: 4px 0 0;
}

.exam-timer {
  display: flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 10px 20px;
  border-radius: 30px;
  font-size: 18px;
  font-weight: 600;
}

.exam-timer.warning {
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.8; }
}

.exam-body {
  flex: 1;
  display: flex;
  padding: 24px;
  gap: 24px;
}

.question-nav {
  width: 200px;
  background: white;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.question-nav h3 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 16px;
}

.nav-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
}

.nav-item {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f1f5f9;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  color: #64748b;
  transition: all 0.2s;
}

.nav-item:hover {
  background: #e2e8f0;
}

.nav-item.active {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.nav-item.answered {
  background: #dcfce7;
  color: #16a34a;
}

.nav-item.active.answered {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.nav-legend {
  display: flex;
  justify-content: space-around;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
  font-size: 12px;
  color: #94a3b8;
}

.legend-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 4px;
  background: #f1f5f9;
  margin-right: 4px;
}

.legend-dot.answered {
  background: #dcfce7;
}

.question-area {
  flex: 1;
  background: white;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.question-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.question-meta {
  display: flex;
  gap: 10px;
}

.badge-type, .badge-diff {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
}

.badge-type {
  background: #e0e7ff;
  color: #6366f1;
}

.badge-diff.easy {
  background: #dcfce7;
  color: #16a34a;
}

.badge-diff.medium {
  background: #fef3c7;
  color: #d97706;
}

.badge-diff.hard {
  background: #fee2e2;
  color: #dc2626;
}

.question-number {
  font-size: 14px;
  color: #94a3b8;
}

.question-content {
  margin-bottom: 24px;
}

.question-content p {
  font-size: 18px;
  line-height: 1.8;
  color: #1e293b;
  margin: 0;
}

.options-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.option-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 12px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: all 0.2s;
}

.option-item:hover {
  background: #f1f5f9;
  border-color: #e2e8f0;
}

.option-item.selected {
  background: #eef2ff;
  border-color: #6366f1;
}

.option-key {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: white;
  border-radius: 50%;
  font-size: 14px;
  font-weight: 600;
  color: #64748b;
  flex-shrink: 0;
}

.option-item.selected .option-key {
  background: #6366f1;
  color: white;
}

.option-text {
  flex: 1;
  font-size: 15px;
  color: #334155;
  line-height: 1.6;
}

.answer-input {
  margin-bottom: 24px;
}

.question-footer {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding-top: 20px;
  border-top: 1px solid #f1f5f9;
}

.highlight {
  color: #667eea;
  font-weight: 700;
  font-size: 18px;
}

.warning-text {
  color: #ef4444;
}

.dark .exam-wrapper {
  background: var(--bg-secondary);
}

.dark .exam-header {
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-color);
}

.dark .exam-info h2 {
  color: var(--text-primary);
}

.dark .exam-info p {
  color: var(--text-light);
}

.dark .nav-item {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.dark .nav-item:hover {
  background: var(--bg-hover);
}

.dark .nav-item.answered {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.dark .nav-legend {
  border-top-color: var(--border-color);
  color: var(--text-light);
}

.dark .legend-dot {
  background: var(--bg-tertiary);
}

.dark .legend-dot.answered {
  background: rgba(16, 185, 129, 0.2);
}

.dark .question-area {
  background: var(--bg-card);
  border: 1px solid var(--glass-border);
}

.dark .badge-type {
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
}

.dark .badge-diff.easy {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.dark .badge-diff.medium {
  background: rgba(245, 158, 11, 0.2);
  color: #fcd34d;
}

.dark .badge-diff.hard {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
}

.dark .question-number {
  color: var(--text-light);
}

.dark .question-content p {
  color: var(--text-primary);
}

.dark .option-item {
  background: var(--bg-tertiary);
  border-color: transparent;
}

.dark .option-item:hover {
  background: var(--bg-hover);
  border-color: var(--border-color);
}

.dark .option-item.selected {
  background: rgba(99, 102, 241, 0.15);
  border-color: #6366f1;
}

.dark .option-key {
  background: var(--bg-card);
  color: var(--text-light);
}

.dark .option-item.selected .option-key {
  background: #6366f1;
  color: white;
}

.dark .option-text {
  color: var(--text-secondary);
}

.dark .question-footer {
  border-top-color: var(--border-color);
}

.dark .highlight {
  color: #818cf8;
}

.dark .warning-text {
  color: #f87171;
}

.switch-warning {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  background: linear-gradient(90deg, #fee2e2 0%, #fecaca 100%);
  border-left: 4px solid #ef4444;
  border-radius: 8px;
  color: #991b1b;
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 16px;
  animation: pulse-warning 0.5s ease;
}

@keyframes pulse-warning {
  0% { transform: scale(0.98); opacity: 0; }
  50% { transform: scale(1.01); }
  100% { transform: scale(1); opacity: 1; }
}

.slide-down-enter-active, .slide-down-leave-active {
  transition: all 0.3s ease;
}
.slide-down-enter-from, .slide-down-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
