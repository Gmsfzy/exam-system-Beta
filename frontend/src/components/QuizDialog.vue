<template>
  <el-dialog :model-value="modelValue" :title="title" width="640px"
             :close-on-click-modal="false" destroy-on-close @update:model-value="close">
    <template v-if="step === 'quiz' && questions.length">
      <div class="qz-head">
        <span>第 {{ idx + 1 }} / {{ questions.length }} 题</span>
        <el-tag size="small">{{ typeLabel(current.type) }}</el-tag>
      </div>
      <div class="qz-content">{{ current.content }}</div>
      <div v-if="isChoice(current.type)" class="qz-options">
        <div v-for="(opt, i) in (current.options || [])" :key="i"
             :class="['qz-option', { selected: isPicked(i) }]" @click="pick(i)">
          <span class="opt-label">{{ String.fromCharCode(65 + i) }}</span>
          <span>{{ opt }}</span>
        </div>
      </div>
      <div v-else-if="current.type === 'true_false'" class="qz-options">
        <div v-for="lab in ['A', 'B']" :key="lab" :class="['qz-option', { selected: draft === lab }]" @click="draft = lab">
          <span class="opt-label">{{ lab }}</span><span>{{ lab === 'A' ? '正确' : '错误' }}</span>
        </div>
      </div>
      <el-input v-else v-model="draft" type="textarea" :rows="3" placeholder="请输入答案" />
      <div class="qz-foot">
        <el-button :disabled="idx === 0" @click="prev">上一题</el-button>
        <el-button v-if="idx < questions.length - 1" type="primary"
                   :disabled="!draft.trim()" :loading="saving" @click="next">下一题</el-button>
        <el-button v-else type="success" :disabled="!draft.trim()" :loading="saving" @click="finish">交卷</el-button>
      </div>
    </template>

    <template v-else-if="step === 'result'">
      <div class="qz-result" :class="result.passed ? 'pass' : 'fail'">
        <div class="qz-score">{{ Math.round((result.score_ratio || 0) * 100) }} 分</div>
        <div class="qz-stat">答对 {{ result.correct_count }} / {{ result.total }} 题</div>
        <div class="qz-verdict">
          <template v-if="scope === 'node'">
            {{ result.passed ? '🎉 通过！本节点已自动标记为已掌握' : '未达 80% 通过线，可复习后再考一次' }}
          </template>
          <template v-else>
            {{ result.passed
               ? (result.certificate_issued ? '🏅 恭喜通过结业测评，证书已颁发！' : '🏅 恭喜通过结业测评！')
               : '未达 80% 通过线，温故后随时可以再考' }}
          </template>
        </div>
      </div>
      <div class="qz-foot">
        <el-button @click="close(false)">关闭</el-button>
        <el-button v-if="result.passed && scope === 'path_final'" type="warning" @click="goCertificate">
          查看证书 →
        </el-button>
        <el-button v-else type="primary" :loading="starting" @click="start">再考一次</el-button>
      </div>
    </template>

    <el-empty v-else-if="step === 'error'" :image-size="60" description="组卷失败，请确认该范围客观题数量充足" />
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import request from '../utils/request'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  payload: { type: Object, required: true },   // {node_id} 或 {path_id}
  title: { type: String, default: '小测' },
})
const emit = defineEmits(['update:modelValue', 'finished'])
const router = useRouter()

const step = ref('quiz')       // quiz / result / error
const starting = ref(false)
const saving = ref(false)
const attemptId = ref(null)
const questions = ref([])
const idx = ref(0)
const draft = ref('')
const picked = ref({})
const result = ref({})

const current = computed(() => questions.value[idx.value] || {})
const scope = computed(() => props.payload.node_id ? 'node' : 'path_final')

// v4.6.1 枚举收敛：题型/选项题型单一来源 frontend/src/utils/enums.js
import { typeLabel, hasOptions } from '../utils/enums'
const isChoice = hasOptions
const isPicked = (i) => (draft.value || '').includes(String.fromCharCode(65 + i))

function pick(i) {
  const label = String.fromCharCode(65 + i)
  if (current.value.type === 'single_choice') {
    draft.value = label
  } else {
    const set = new Set((draft.value || '').split('').filter(Boolean))
    set.has(label) ? set.delete(label) : set.add(label)
    draft.value = Array.from(set).sort().join('')
  }
}

async function start() {
  starting.value = true
  try {
    const res = await request.post('/api/learning/quizzes/start', props.payload)
    attemptId.value = res.data.attempt_id
    questions.value = res.data.questions || []
    idx.value = 0
    draft.value = ''
    picked.value = {}
    step.value = 'quiz'
  } catch (e) {
    step.value = 'error'
  }
  starting.value = false
}

async function saveCurrent() {
  if (!current.value?.id) return false
  try {
    await request.post(`/api/learning/quizzes/${attemptId.value}/answer`, {
      question_id: current.value.id, student_answer: draft.value.trim(),
    })
    picked.value[current.value.id] = draft.value.trim()
    return true
  } catch (e) { return false }
}

async function prev() {
  await saveCurrent()
  if (idx.value > 0) {
    idx.value -= 1
    draft.value = picked.value[current.value.id] || ''
  }
}

async function next() {
  saving.value = true
  const ok = await saveCurrent()
  saving.value = false
  if (!ok) return
  idx.value += 1
  draft.value = picked.value[current.value.id] || ''
}

async function finish() {
  saving.value = true
  const ok = await saveCurrent()
  if (ok) {
    try {
      const res = await request.post(`/api/learning/quizzes/${attemptId.value}/submit`)
      result.value = res.data
      step.value = 'result'
      emit('finished', res.data)
    } catch (e) { /* 拦截器已提示 */ }
  }
  saving.value = false
}

function goCertificate() {
  close(false)
  router.push('/learning/certificates')
}

function close(v) {
  emit('update:modelValue', !!v)
}

watch(() => props.modelValue, (v) => {
  if (v) start()
})
</script>

<style scoped>
.qz-head { display: flex; gap: 10px; align-items: center; font-size: 13px; color: var(--text-muted); margin-bottom: 10px; }
.qz-content { font-size: 15px; line-height: 1.7; color: var(--text-primary); margin-bottom: 16px; white-space: pre-wrap; }
.qz-options { display: flex; flex-direction: column; gap: 8px; }
.qz-option {
  display: flex; gap: 10px; padding: 10px 14px; border: 1px solid var(--border-color);
  border-radius: 9px; cursor: pointer; transition: all 0.2s; font-size: 14px; color: var(--text-primary);
}
.qz-option:hover { border-color: #f59e0b; }
.qz-option.selected { background: rgba(245, 158, 11, 0.1); border-color: #f59e0b; }
.qz-option .opt-label { font-weight: 600; color: var(--text-muted); }
.qz-foot { display: flex; justify-content: space-between; margin-top: 18px; }
.qz-foot > :first-child { margin-right: auto; }
.qz-foot .el-button + .el-button { margin-left: 8px; }
.qz-result { text-align: center; padding: 26px 0 10px; }
.qz-result .qz-score { font-size: 44px; font-weight: 800; }
.qz-result.pass .qz-score { color: #10b981; }
.qz-result.fail .qz-score { color: #ef4444; }
.qz-result .qz-stat { font-size: 14px; color: var(--text-muted); margin-top: 6px; }
.qz-result .qz-verdict { font-size: 15px; color: var(--text-primary); margin-top: 12px; }
</style>
