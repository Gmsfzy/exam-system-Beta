<template>
  <div class="take-wrapper">
    <header class="take-header">
      <div class="header-left">
        <el-icon :size="22" class="pk-icon"><Trophy /></el-icon>
        <span class="comp-title">{{ state.competition?.title }}</span>
      </div>
      <div class="header-center">
        <span class="progress-text">{{ currentIndex + 1 }} / {{ state.questions?.length || 0 }}</span>
        <el-progress :percentage="progress" :stroke-width="8" class="progress-bar" />
      </div>
      <div class="header-right">
        <div class="timer" :class="{ danger: remaining <= 30 }">
          <el-icon :size="18"><Clock /></el-icon>
          {{ timerText }}
        </div>
      </div>
    </header>

    <!-- 实时比分条 -->
    <div class="score-bar">
      <div class="player-score" :class="{ leading: amLeading }">
        <span class="p-name">我</span>
        <span class="p-score">{{ myScore }}</span>
        <span class="p-answered">已答{{ myAnswered }}题</span>
      </div>
      <div class="vs-block">
        <span class="vs-label">VS</span>
      </div>
      <div class="player-score" :class="{ leading: !amLeading && opponentJoined }">
        <span class="p-name">{{ opponentName }}</span>
        <span class="p-score">{{ opponentScore }}</span>
        <span class="p-answered">已答{{ opponentAnswered }}题</span>
      </div>
    </div>

    <!-- 等待对手 -->
    <div v-if="battleStatus === 'waiting'" class="waiting-box">
      <el-icon :size="44" class="waiting-icon"><Trophy /></el-icon>
      <h3>挑战已发出，等待对手接受...</h3>
      <p>页面会自动进入对战，也可以把对战码 <b>{{ battleId }}</b> 告诉对方，让对方在 PK 大厅应战</p>
      <el-button @click="$router.push('/competitions/pk')">返回PK大厅</el-button>
    </div>

    <!-- 对战题目 -->
    <main v-else-if="battleStatus === 'playing' && state.questions?.length" class="take-main">
      <div class="question-card">
        <div class="q-meta">
          <el-tag size="small" effect="plain">{{ typeLabel(currentQuestion.q_type) }}</el-tag>
          <span class="q-score">{{ currentQuestion.score }}分</span>
        </div>
        <h2 class="q-content">{{ currentQuestion.content }}</h2>

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

        <div v-else class="blank-box">
          <el-input v-model="blankAnswer" size="large" placeholder="输入答案" :disabled="!!feedback"
            @keyup.enter="submitAnswer" />
        </div>
      </div>

      <transition name="fade-up">
        <div v-if="feedback" class="feedback-card" :class="isCorrect ? 'good' : 'bad'">
          <el-icon :size="22"><CircleCheckFilled v-if="isCorrect" /><CircleCloseFilled v-else /></el-icon>
          <span class="feedback-text">
            {{ isCorrect ? `回答正确 +${lastGained} 分` : '回答错误' }}
          </span>
        </div>
      </transition>
    </main>

    <!-- 我已交卷等待对方 -->
    <div v-if="iFinished && battleStatus === 'playing'" class="waiting-box">
      <h3>你已完成作答，等待对方完成...</h3>
    </div>

    <footer v-if="battleStatus === 'playing' && !iFinished" class="take-footer">
      <el-button v-if="!feedback" type="primary" size="large" round
        :disabled="!hasAnswer" @click="submitAnswer">
        提交答案
      </el-button>
      <el-button v-else type="success" size="large" round @click="nextQuestion">
        {{ currentIndex + 1 >= state.questions.length ? '完成对战' : '下一题' }}
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
import { getSocket, authToken } from '../utils/socket'
import { useAuthStore } from '../stores/auth'
import { Trophy, Clock, CircleCheckFilled, CircleCloseFilled } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const battleId = route.params.battleId

const state = ref({ battle: {}, questions: [], competition: {} })
const role = ref('challenger')
const currentIndex = ref(0)
const singleAnswer = ref('')
const multiAnswer = ref([])
const blankAnswer = ref('')
const feedback = ref(false)
const isCorrect = ref(false)
const lastGained = ref(0)
const remaining = ref(0)
const iFinished = ref(false)
let timer = null
let pollTimer = null
let socket = null
let startTick = 0

const battleStatus = computed(() => state.value.battle?.status || 'waiting')
const currentQuestion = computed(() => state.value.questions?.[currentIndex.value] || {})
const opponentName = computed(() =>
  role.value === 'challenger' ? (state.value.battle.opponent || '等待中') : state.value.battle.challenger)
const opponentJoined = computed(() => role.value === 'challenger' ? !!state.value.battle.opponent_id : true)
const myScore = computed(() => role.value === 'challenger'
  ? state.value.battle.challenger_score : state.value.battle.opponent_score)
const opponentScore = computed(() => role.value === 'challenger'
  ? state.value.battle.opponent_score : state.value.battle.challenger_score)
const myAnswered = computed(() => role.value === 'challenger'
  ? state.value.battle.challenger_answered : state.value.battle.opponent_answered)
const opponentAnswered = computed(() => role.value === 'challenger'
  ? state.value.battle.opponent_answered : state.value.battle.challenger_answered)
const amLeading = computed(() => myScore.value >= opponentScore.value)
const progress = computed(() => {
  if (!state.value.questions?.length) return 0
  return Math.round(((currentIndex.value + (feedback.value ? 1 : 0)) / state.value.questions.length) * 100)
})
const hasAnswer = computed(() => {
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
const currentAnswerKey = computed(() => {
  const t = currentQuestion.value.q_type
  if (t === 'fill_blank') return null
  return (currentQuestion.value.answer_key || '').toString()
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

const applyState = (data) => {
  const prev = state.value.battle
  state.value = data
  if (data.remaining_seconds !== undefined) remaining.value = data.remaining_seconds
  if (data.status === 'playing' && !state.value._resumed) {
    state.value._resumed = true
    resumeCurrent()
  }
  // 对方已接受（从 waiting 切入 playing）时重置计时起点
  if (prev?.status === 'waiting' && data.battle?.status === 'playing') {
    startTick = Date.now()
    ElMessage.success('对手已就位，对战开始！')
  }
}

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
    if (q.q_type === 'multiple_choice') multiAnswer.value = Array.from(q.student_answer || '')
    else if (q.q_type === 'fill_blank') blankAnswer.value = q.student_answer
    else singleAnswer.value = q.student_answer
    isCorrect.value = q.is_correct
    lastGained.value = q.gained_score
    feedback.value = true
  }
}

const loadState = async () => {
  const res = await request.get(`/api/pk/${battleId}/state`)
  applyState(res.data)
  if (state.value.battle.status === 'finished') showResult()
}

const startTimer = () => {
  stopTimer()
  timer = setInterval(() => {
    if (remaining.value <= 0) {
      stopTimer()
      loadState()
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

const setupSocket = () => {
  try {
    socket = getSocket()
    socket.emit('join_battle', { battle_id: Number(battleId), token: authToken() })
    socket.on('battle_update', (battle) => {
      if (battle?.id === Number(battleId)) {
        state.value.battle = { ...state.value.battle, ...battle }
      }
    })
    socket.on('battle_end', (battle) => {
      if (battle?.id === Number(battleId)) {
        state.value.battle = { ...state.value.battle, ...battle }
        showResult()
      }
    })
    socket.on('battle_accepted', (battle) => {
      if (battle?.id === Number(battleId)) {
        loadState()
      }
    })
  } catch { /* socket 不可用时靠轮询 */ }
}

const showResult = () => {
  stopTimer()
  const b = state.value.battle
  const result = !b.winner_id ? 'draw'
    : b.winner_id === auth.user?.id ? 'win' : 'lose'
  const text = { win: '恭喜，你赢了！', lose: '惜败，再接再厉！', draw: '平局，势均力敌！' }[result]
  ElMessageBox.alert(
    `最终比分 ${b.challenger_score} : ${b.opponent_score}`,
    text,
    { confirmButtonText: '返回PK大厅', type: result === 'win' ? 'success' : result === 'lose' ? 'error' : 'info' }
  ).then(() => router.replace('/competitions/pk')).catch(() => router.replace('/competitions/pk'))
}

const submitAnswer = async () => {
  const q = currentQuestion.value
  const t = q.q_type
  const answer = t === 'multiple_choice' ? multiAnswer.value.slice().sort().join('') :
    t === 'fill_blank' ? blankAnswer.value.trim() : singleAnswer.value
  const timeSpent = Math.round((Date.now() - startTick) / 1000)

  try {
    const res = await request.post(`/api/pk/${battleId}/answer`, {
      cq_id: q.id,
      answer,
      time_spent: timeSpent,
    })
    isCorrect.value = res.data.is_correct
    lastGained.value = res.data.gained_score
    q.gained_score = res.data.gained_score
    q.is_correct = res.data.is_correct
    q.student_answer = answer
    q.answer_key = res.data.correct_answer
    feedback.value = true
  } catch (e) {
    // 对战已结束时后端返回 400
    if (e?.response?.data?.finished) loadState()
  }
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
  ElMessageBox.confirm('提前交卷后剩余题目不得分，确认交卷？', '交卷确认', { type: 'warning' })
    .then(() => doFinish())
    .catch(() => {})
}

const doFinish = async () => {
  stopTimer()
  try {
    const res = await request.post(`/api/pk/${battleId}/finish`)
    iFinished.value = true
    feedback.value = false
    if (res.data.settled) {
      loadState()
    } else {
      ElMessage.info('已交卷，等待对方完成...')
    }
  } catch (e) {
    loadState()
  }
}

onMounted(async () => {
  try {
    await loadState()
  } catch {
    router.replace('/competitions/pk')
    return
  }
  startTimer()
  setupSocket()
  // 兜底轮询（socket 未连接时保底刷新比分）
  pollTimer = setInterval(() => {
    if (battleStatus.value === 'playing') loadState()
  }, 8000)
})

onUnmounted(() => {
  stopTimer()
  if (pollTimer) clearInterval(pollTimer)
  if (socket) {
    socket.emit('leave_battle', { battle_id: Number(battleId) })
    socket.off('battle_update')
    socket.off('battle_end')
    socket.off('battle_accepted')
  }
})
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

.pk-icon {
  color: #d97706;
}

.comp-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}

.header-center {
  flex: 1;
  max-width: 380px;
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

.score-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 26px;
  padding: 16px 32px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-color);
}

.player-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 130px;
  padding: 8px 20px;
  border-radius: 12px;
  opacity: 0.75;
  transition: all 0.3s ease;
}

.player-score.leading {
  opacity: 1;
  background: rgba(245, 158, 11, 0.1);
}

.p-name {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 600;
}

.p-score {
  font-size: 26px;
  font-weight: 800;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.player-score.leading .p-score {
  color: #d97706;
}

.p-answered {
  font-size: 11.5px;
  color: var(--text-light);
}

.vs-block {
  padding: 0 8px;
}

.vs-label {
  font-size: 20px;
  font-weight: 900;
  font-style: italic;
  color: #ef4444;
}

.waiting-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 60px 24px;
  text-align: center;
}

.waiting-icon {
  color: #d97706;
  animation: pulse 1.6s ease-in-out infinite;
}

.waiting-box h3 {
  font-size: 20px;
  color: var(--text-primary);
  margin: 0;
}

.waiting-box p {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.12); opacity: 0.75; }
}

.take-main {
  flex: 1;
  width: 100%;
  max-width: 780px;
  margin: 0 auto;
  padding: 28px 24px 16px;
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
  padding: 18px 0 36px;
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
