<template>
  <div class="practice-detail">
    <div v-if="!session && !loading" class="empty">
      <el-empty description="练习不存在或已结束" />
      <el-button @click="$router.push('/learning/practice')">返回列表</el-button>
    </div>

    <template v-else-if="session">
      <div class="header">
        <div>
          <h2>{{ session.title }}</h2>
          <p class="meta">
            <span>{{ session.questions_count }} 题</span>
            <span class="dot">·</span>
            <span>{{ answeredCount }}/{{ session.questions_count }} 已答</span>
            <span class="dot">·</span>
            <span v-if="session.status === 'completed'" class="success">已完成</span>
            <span v-else class="warning">进行中</span>
          </p>
        </div>
        <div class="header-actions">
          <el-button v-if="session.status !== 'completed'" @click="submitAll" type="primary">完成练习</el-button>
          <el-button @click="$router.push('/learning/practice')">返回</el-button>
        </div>
      </div>

      <!-- 题目导航 -->
      <div class="nav-panel">
        <div class="nav-grid">
          <div v-for="(_, idx) in questions" :key="idx"
               :class="['nav-item', { answered: answers[idx] !== undefined, active: currentIdx === idx }]"
               @click="goTo(idx)">{{ idx + 1 }}</div>
        </div>
        <div class="progress">
          进度 {{ answeredCount }} / {{ questions.length }}
        </div>
      </div>

      <!-- 答题区 -->
      <div v-if="currentQ && session.status !== 'completed'" class="question-panel">
        <div class="q-header">
          <span class="q-num">第 {{ currentIdx + 1 }} 题</span>
          <el-tag size="small" v-if="currentQ.type">{{ typeLabel(currentQ.type) }}</el-tag>
        </div>
        <div class="q-content">{{ currentQ.content }}</div>

        <!-- 选择题 -->
        <div v-if="isChoiceType(currentQ.type)" class="q-options">
          <div v-for="(opt, i) in currentQ.options" :key="i"
               :class="['q-option', { selected: isOptionSelected(i) }]"
               @click="selectOption(i)">
            <span class="opt-label">{{ optionLabel(i) }}</span>
            <span class="opt-text">{{ opt }}</span>
          </div>
        </div>

        <!-- 判断题 -->
        <div v-else-if="currentQ.type === 'true_false'" class="q-tf">
          <el-radio-group v-model="currentAnswer" @change="submitCurrent" size="large">
            <el-radio-button value="A">正确</el-radio-button>
            <el-radio-button value="B">错误</el-radio-button>
          </el-radio-group>
        </div>

        <!-- 填空/简答 -->
        <div v-else class="q-text">
          <el-input v-model="currentAnswer" type="textarea" :rows="4" placeholder="请输入你的答案" />
          <el-button type="primary" @click="submitCurrent" style="margin-top:10px">提交此题</el-button>
        </div>

        <div class="q-footer">
          <el-button :disabled="currentIdx === 0" @click="goTo(currentIdx - 1)">上一题</el-button>
          <el-button :disabled="currentIdx >= questions.length - 1" @click="goTo(currentIdx + 1)">下一题</el-button>
        </div>
      </div>

      <!-- 已完成视图：显示所有答案 + 解析 -->
      <div v-else-if="session.status === 'completed'" class="result-panel">
        <div class="result-summary">
          <div class="summary-item">
            <span class="val">{{ session.correct_count }}</span>
            <span class="lbl">答对</span>
          </div>
          <div class="summary-item">
            <span class="val">{{ session.questions_count - session.correct_count }}</span>
            <span class="lbl">答错</span>
          </div>
          <div class="summary-item">
            <span class="val">{{ session.score_ratio ? (session.score_ratio * 100).toFixed(1) + '%' : '-' }}</span>
            <span class="lbl">正确率</span>
          </div>
          <div class="summary-item">
            <span class="val">{{ formatTime(session.total_time_sec) }}</span>
            <span class="lbl">用时</span>
          </div>
        </div>

        <div v-for="(ans, idx) in session.answers" :key="idx" class="result-card">
          <div class="res-header">
            <span>第 {{ idx + 1 }} 题</span>
            <el-tag :type="ans.is_correct ? 'success' : 'danger'" size="small">
              {{ ans.is_correct ? '答对' : '答错' }}
            </el-tag>
          </div>
          <div class="res-q">{{ ans.question_content }}</div>
          <div class="res-a">
            <div class="res-row"><span class="label">你的作答：</span>{{ ans.student_answer || '（空）' }}</div>
            <div class="res-row correct"><span class="label">正确答案：</span>{{ ans.correct_answer }}</div>
          </div>
          <div v-if="ans.analysis" class="res-analysis">
            <el-divider content-position="left">解析</el-divider>
            <div>{{ ans.analysis }}</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '../utils/request'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()
const router = useRouter()

const sessionId = computed(() => route.params.sessionId)
const session = ref(null)
const questions = ref([])  // 会话创建时返回的题目列表
const answers = ref({})   // { idx: { student_answer, is_correct } } 本地缓存
const currentIdx = ref(0)
const currentAnswer = ref('')
const loading = ref(true)

const currentQ = computed(() => questions.value[currentIdx.value])
const answeredCount = computed(() => Object.keys(answers.value).length)

function isChoiceType(t) { return ['single_choice', 'multiple_choice'].includes(t) }
function typeLabel(t) {
  return { single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题', fill_blank: '填空题', essay: '简答题' }[t] || t
}
function optionLabel(i) { return String.fromCharCode(65 + i) }
function isOptionSelected(i) {
  const a = answers.value[currentIdx.value]?.student_answer || ''
  return a.includes(optionLabel(i))
}

function selectOption(i) {
  const label = optionLabel(i)
  if (currentQ.value.type === 'single_choice') {
    currentAnswer.value = label
  } else if (currentQ.value.type === 'multiple_choice') {
    let set = new Set((currentAnswer.value || '').split('').filter(Boolean))
    set.has(label) ? set.delete(label) : set.add(label)
    currentAnswer.value = Array.from(set).sort().join('')
  }
}

function goTo(idx) {
  currentIdx.value = idx
  currentAnswer.value = answers.value[idx]?.student_answer || ''
}

async function submitCurrent() {
  if (!currentQ.value) return
  const student_answer = (currentAnswer.value || '').trim()
  const idx = currentIdx.value
  try {
    const res = await request.post(`/api/learning/practice/${sessionId.value}/answer`, {
      question_id: currentQ.value.id,
      student_answer,
      time_spent_sec: 0,
    })
    answers.value[idx] = { student_answer, is_correct: res.data.is_correct, detail: res.data }
    const ok = res.data.is_correct
    ElMessage(ok ? { message: '✓ 答对了！', type: 'success' } : { message: '✗ 答错了', type: 'error' })
    // 自动跳到下一题
    if (idx < questions.value.length - 1) goTo(idx + 1)
  } catch (e) { /* ignore */ }
}

async function submitAll() {
  try {
    await ElMessageBox.confirm(`确认完成练习？已答 ${answeredCount.value}/${questions.value.length} 题`, '完成练习')
    const res = await request.post(`/api/learning/practice/${sessionId.value}/submit`)
    ElMessage.success(`练习完成！正确率 ${(res.data.score_ratio * 100).toFixed(1)}%`)
    loadDetail()  // 刷新为已完成视图
  } catch (e) { /* 用户取消或请求错误 */ }
}

function formatTime(sec) {
  if (!sec) return '-'
  const m = Math.floor(sec / 60); const s = sec % 60
  return `${m}分${s}秒`
}

async function loadDetail() {
  loading.value = true
  try {
    const res = await request.get(`/api/learning/practice/${sessionId.value}`)
    session.value = res.data
    // 如果后端返回的是历史数据（已完成），没有 questions 原始列表
    if (res.data.answers) {
      // 从历史恢复 answers 字典
      res.data.answers.forEach((a, i) => {
        answers.value[i] = { student_answer: a.student_answer, is_correct: a.is_correct, detail: a }
      })
      // 构造 questions 数组（只有 content/type）
      questions.value = res.data.answers.map((a, i) => ({
        id: i, content: a.question_content, type: res.data.answers[i]?.question_type || '',
        options: [],
      }))
    }
  } catch (e) {}
  loading.value = false
}

onMounted(async () => {
  // 尝试直接加载（如果是已有会话），失败则回退到待新创建
  await loadDetail()
  // 如果 questions 为空，可能是直接从 URL 进来的，返回列表
})
</script>

<style scoped>
.practice-detail { padding: 20px; max-width: 880px; }
.empty { text-align: center; padding: 80px 0; }

.header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.header h2 { margin: 0 0 6px; font-size: 20px; color: var(--text-primary); }
.meta { font-size: 13px; color: var(--text-muted); margin: 0; }
.meta .dot { margin: 0 6px; }
.meta .success { color: #10b981; }
.meta .warning { color: #f59e0b; }

.nav-panel {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 14px 16px; margin-bottom: 18px;
}
.nav-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.nav-item {
  width: 32px; height: 32px; border-radius: 6px; display: flex;
  align-items: center; justify-content: center;
  background: var(--bg-tertiary); font-size: 13px; cursor: pointer;
  color: var(--text-muted); transition: all 0.2s;
}
.nav-item.answered { background: var(--primary-bg); color: var(--primary-color); }
.nav-item.active { background: var(--primary-color); color: white; }
.progress { margin-top: 10px; font-size: 12px; color: var(--text-muted); }

.question-panel {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 24px;
}
.q-header { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.q-num { font-size: 14px; color: var(--text-muted); }
.q-content { font-size: 15px; line-height: 1.7; color: var(--text-primary); margin-bottom: 20px; white-space: pre-wrap; }

.q-options { display: flex; flex-direction: column; gap: 10px; }
.q-option {
  display: flex; align-items: flex-start; gap: 12px; padding: 12px 16px;
  border: 1px solid var(--border-color); border-radius: 10px;
  cursor: pointer; transition: all 0.2s;
}
.q-option:hover { border-color: var(--primary-color); }
.q-option.selected { background: var(--primary-bg); border-color: var(--primary-color); }
.opt-label { font-weight: 600; color: var(--text-muted); min-width: 20px; }
.opt-text { flex: 1; font-size: 14px; }

.q-tf { margin: 20px 0; }

.q-footer { display: flex; justify-content: space-between; margin-top: 24px; }

.result-summary {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px;
}
.summary-item {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 10px; padding: 16px; text-align: center;
}
.summary-item .val { display: block; font-size: 22px; font-weight: 700; color: var(--text-primary); }
.summary-item .lbl { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

.result-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 10px; padding: 18px 20px; margin-bottom: 12px;
}
.res-header { display: flex; gap: 10px; align-items: center; font-size: 13px; color: var(--text-muted); margin-bottom: 10px; }
.res-q { font-size: 14px; line-height: 1.6; color: var(--text-primary); margin-bottom: 10px; white-space: pre-wrap; }
.res-row { font-size: 13px; color: var(--text-muted); margin-bottom: 4px; }
.res-row.correct { color: var(--text-primary); }
.res-row .label { color: var(--text-muted); }
.res-analysis { font-size: 13px; color: var(--text-secondary); }
</style>
