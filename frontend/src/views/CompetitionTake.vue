<template>
  <div class="take-wrapper">
    <header class="take-header">
      <div class="header-left">
        <el-icon :size="22" class="trophy-icon"><Trophy /></el-icon>
        <span class="comp-title">{{ state.competition?.title }}</span>
      </div>
      <div class="header-center">
        <span class="progress-text">{{ currentIndex + 1 }} / {{ state.questions.length }}</span>
        <el-progress :percentage="progress" :stroke-width="8" class="progress-bar" />
      </div>
      <div class="header-right">
        <div class="score-chip">
          <el-icon :size="16"><Star /></el-icon>
          {{ totalScore }} 分
        </div>
        <div class="timer" :class="{ danger: remaining <= 30 }">
          <el-icon :size="18"><Clock /></el-icon>
          {{ timerText }}
        </div>
      </div>
    </header>

    <main v-if="state.questions.length" class="take-main">
      <div class="question-card">
        <div class="q-meta">
          <el-tag size="small" effect="plain">{{ typeLabel(currentQuestion.q_type) }}</el-tag>
          <span class="q-score">{{ currentQuestion.score }}分</span>
        </div>
        <h2 class="q-content">{{ currentQuestion.content }}</h2>

        <!-- 单选 / 判断 -->
        <div v-if="['single_choice', 'true_false'].includes(currentQuestion.q_type)" class="options-list">
          <div
            v-for="opt in getOptions(currentQuestion.options)"
            :key="opt.key"
            class="option-item"
            :class="{
              selected: singleAnswer === opt.key,
              correct: feedback && opt.key === currentAnswerKey,
              wrong: feedback && singleAnswer === opt.key && !isCorrect
            }"
            @click="!feedback && (singleAnswer = opt.key)"
          >
            <span class="opt-key">{{ opt.key }}</span>
            <span class="opt-value">{{ opt.value }}</span>
          </div>
        </div>

        <!-- 多选 -->
        <div v-else-if="currentQuestion.q_type === 'multiple_choice'" class="options-list">
          <div
            v-for="opt in getOptions(currentQuestion.options)"
            :key="opt.key"
            class="option-item"
            :class="{ selected: multiAnswer.includes(opt.key) }"
            @click="!feedback && toggleMulti(opt.key)"
          >
            <el-checkbox :model-value="multiAnswer.includes(opt.key)" style="pointer-events: none" />
            <span class="opt-key">{{ opt.key }}</span>
            <span class="opt-value">{{ opt.value }}</span>
          </div>
        </div>

        <!-- 填空 -->
        <div v-else class="blank-box">
          <el-input v-model="blankAnswer" size="large" placeholder="输入答案" :disabled="!!feedback"
            @keyup.enter="submitAnswer" />
        </div>
      </div>

      <!-- 即时反馈 -->
      <transition name="fade-up">
        <div v-if="feedback" class="feedback-card" :class="isCorrect ? 'good' : 'bad'">
          <el-icon :size="22"><CircleCheckFilled v-if="isCorrect" /><CircleCloseFilled v-else /></el-icon>
          <span class="feedback-text">
            {{ isCorrect ? `回答正确 +${lastGained} 分` : '回答错误' }}
          </span>
        </div>
      </transition>
    </main>

    <footer class="take-footer">
      <el-button v-if="!feedback" type="primary" size="large" round
        :disabled="!hasAnswer" @click="submitAnswer">
        提交答案
      </el-button>
      <el-button v-else type="success" size="large" round @click="nextQuestion">
        {{ currentIndex + 1 >= state.questions.length ? '完成竞赛' : '下一题' }}
      </el-button>
      <el-button text type="danger" @click="confirmFinish">提前交卷</el-button>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import {
  Trophy, Star, Clock, CircleCheckFilled, CircleCloseFilled
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const compId = route.params.compId

const state = ref({ questions: [], competition: {} })
const currentIndex = ref(0)
const singleAnswer = ref('')
const multiAnswer = ref([])
const blankAnswer = ref('')
const feedback = ref(false)
const isCorrect = ref(false)
const lastGained = ref(0)
const remaining = ref(0)
let timer = null
let startTick = 0

const currentQuestion = computed(() => state.value.questions[currentIndex.value] || {})
const progress = computed(() => {
  if (!state.value.questions.length) return 0
  return Math.round(((currentIndex.value + (feedback.value ? 1 : 0)) / state.value.questions.length) * 100)
})
const totalScore = computed(() => {
  const done = state.value.questions.filter(q => q.gained_score !== undefined)
  return Math.round(done.reduce((s, q) => s + (q.gained_score || 0), 0) * 100) / 100
})
const hasAnswer = computed(() => {
  if (!currentQuestion.value.q_type) return false
  const t = currentQuestion.value.q_type
  if (t === 'multiple_choice') return multiAnswer.value.length > 0
  if (t === 'fill_blank') return blankAnswer.value.trim() !== ''
  return singleAnswer.value !== ''
})
const timerText = computed(() => {
  const m = Math.floor(remaining.value / 60)
  const s = remaining.value % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

const typeLabel = (t) => ({ single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题', fill_blank: '填空题' }[t] || t)

const getOptions = (optionsStr) => {
  try {
    const options = JSON.parse(optionsStr)
    return Object.entries(options).map(([key, value]) => ({ key, value }))
  } catch {
    return []
  }
}

const toggleMulti = (key) => {
  const idx = multiAnswer.value.indexOf(key)
  if (idx >= 0) multiAnswer.value.splice(idx, 1)
  else multiAnswer.value.push(key)
}

const startTimer = () => {
  stopTimer()
  startTick = Date.now()
  timer = setInterval(() => {
    if (remaining.value <= 0) {
      stopTimer()
      autoFinish()
      return
    }
    remaining.value -= 1
  }, 1000)
}

const stopTimer = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

const loadState = async () => {
  let data
  try {
    data = (await request.get(`/api/competitions/${compId}/play`)).data
  } catch {
    router.replace('/competitions')
    return
  }
  if (data.status === 'joined') {
    data = (await request.post(`/api/competitions/${compId}/start`)).data
  } else if (data.status === 'finished') {
    ElMessage.info('您已完成本次竞赛')
    router.replace(`/competitions/${compId}/leaderboard`)
    return
  }
  state.value = data
  remaining.value = data.remaining_seconds || 0
  resumeCurrent()
  startTimer()
}

// 刷新恢复：跳到第一道未答的题
const resumeCurrent = () => {
  const idx = state.value.questions.findIndex(q => q.gained_score === undefined)
  currentIndex.value = idx >= 0 ? idx : state.value.questions.length - 1
  restoreAnswerDraft()
}

const restoreAnswerDraft = () => {
  singleAnswer.value = ''
  multiAnswer.value = []
  blankAnswer.value = ''
  feedback.value = false
  const q = currentQuestion.value
  if (q && q.student_answer !== undefined && q.gained_score !== undefined) {
    // 已判分的题直接显示反馈
    if (['multiple_choice'].includes(q.q_type)) multiAnswer.value = Array.from(q.student_answer || '')
    else if (q.q_type === 'fill_blank') blankAnswer.value = q.student_answer
    else singleAnswer.value = q.student_answer
    isCorrect.value = q.is_correct
    lastGained.value = q.gained_score
    feedback.value = true
  }
}

const currentAnswerKey = computed(() => {
  const t = currentQuestion.value.q_type
  if (t === 'fill_blank') return null
  const ans = (currentQuestion.value.answer_key || '').toString()
  return ans
})

const submitAnswer = async () => {
  const q = currentQuestion.value
  const t = q.q_type
  const answer = t === 'multiple_choice' ? multiAnswer.value.slice().sort().join('') :
    t === 'fill_blank' ? blankAnswer.value.trim() : singleAnswer.value
  const timeSpent = Math.round((Date.now() - startTick) / 1000)

  const res = await request.post(`/api/competitions/${compId}/answer`, {
    cq_id: q.id,
    answer,
    time_spent: timeSpent,
  })
  isCorrect.value = res.data.is_correct
  lastGained.value = res.data.gained_score
  q.gained_score = res.data.gained_score
  q.is_correct = res.data.is_correct
  q.student_answer = answer
  q.answer_key = res.data.correct_answer  // 作答后高亮正确选项
  feedback.value = true
}

const nextQuestion = () => {
  if (currentIndex.value + 1 >= state.value.questions.length) {
    doFinish()
    return
  }
  currentIndex.value += 1
  startTick = Date.now()
  restoreAnswerDraft()
}

const confirmFinish = () => {
  ElMessageBox.confirm('提前交卷后未答题目不得分，确认交卷？', '交卷确认', { type: 'warning' })
    .then(() => doFinish())
    .catch(() => {})
}

const autoFinish = () => {
  ElMessage.warning('答题时间已结束，自动交卷')
  doFinish()
}

const doFinish = async () => {
  stopTimer()
  try {
    await request.post(`/api/competitions/${compId}/finish`)
  } catch (e) { /* 已结算时忽略 */ }
  router.replace(`/competitions/${compId}/leaderboard`)
}

onMounted(loadState)
onUnmounted(stopTimer)
</script>

<style scoped>
.take-wrapper {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
}

.take-header {
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 220px;
}

.trophy-icon {
  color: #d97706;
}

.comp-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}

.header-center {
  flex: 1;
  max-width: 420px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.progress-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
}

.progress-bar {
  flex: 1;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 220px;
  justify-content: flex-end;
}

.score-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 20px;
  background: rgba(245, 158, 11, 0.12);
  color: #d97706;
  font-size: 14px;
  font-weight: 700;
}

.timer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 20px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.timer.danger {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.take-main {
  flex: 1;
  width: 100%;
  max-width: 780px;
  margin: 0 auto;
  padding: 36px 24px 20px;
}

.question-card {
  padding: 32px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 18px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.06);
}

.q-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.q-score {
  font-size: 13px;
  font-weight: 600;
  color: #d97706;
}

.q-content {
  font-size: 19px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.6;
  margin: 0 0 24px;
  white-space: pre-wrap;
}

.options-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.option-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  border: 1.5px solid var(--border-color);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.option-item:hover {
  border-color: #6366f1;
}

.option-item.selected {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.08);
}

.option-item.correct {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.1);
}

.option-item.wrong {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
}

.opt-key {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--bg-tertiary);
  font-size: 14px;
  font-weight: 700;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.opt-value {
  font-size: 15px;
  color: var(--text-primary);
}

.blank-box {
  padding: 8px 0;
}

.feedback-card {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 20px;
  padding: 16px;
  border-radius: 12px;
  font-size: 16px;
  font-weight: 700;
}

.feedback-card.good {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}

.feedback-card.bad {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.take-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 20px;
  padding: 20px 0 40px;
}

.fade-up-enter-active {
  transition: all 0.35s ease;
}

.fade-up-enter-from {
  opacity: 0;
  transform: translateY(12px);
}

.dark .question-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
}

.dark .option-item.selected {
  border-color: #818cf8;
  background: rgba(99, 102, 241, 0.15);
}
</style>
