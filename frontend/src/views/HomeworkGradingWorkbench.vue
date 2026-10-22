<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><EditPen /></el-icon> 批改工作台</h2>
      </div>
      <div class="header-actions">
        <el-select v-model="hwFilter" placeholder="全部作业" clearable size="small"
                   style="width: 220px" @change="loadQueue">
          <el-option v-for="h in homeworks" :key="h.id" :label="`${h.title}（待批 ${h.pending}）`" :value="h.id" />
        </el-select>
        <el-button :icon="Refresh" size="small" :loading="queueLoading" @click="loadQueue">刷新</el-button>
      </div>
    </div>

    <!-- 进度看板 -->
    <div class="stats-bar">
      <span>待批 <b>{{ stats.pending_total ?? 0 }}</b> 份</span>
      <span>已批 <b>{{ stats.graded_total ?? 0 }}</b> 份</span>
      <span class="muted small">跨你所有已发布作业聚合 · 先交先批 · 支持 <kbd>Alt</kbd>+<kbd>↑/↓</kbd> 切换、<kbd>Ctrl</kbd>+<kbd>Enter</kbd> 保存</span>
    </div>

    <div class="workbench">
      <!-- 左：待批队列 -->
      <div class="queue-pane">
        <div v-if="queueLoading && !items.length" class="center">加载中…</div>
        <el-empty v-else-if="!items.length" description="队列已清空，暂无待批提交" :image-size="80" />
        <div v-else class="queue-list">
          <div v-for="(it, idx) in items" :key="it.sub_id"
               class="queue-item" :class="{ active: current && current.sub_id === it.sub_id }"
               @click="selectItem(it)">
            <div class="qi-head">
              <span class="qi-name">{{ it.username }}</span>
              <el-tag v-if="it.is_late" size="small" type="warning" effect="plain">迟交</el-tag>
              <el-tag v-if="it.blind" size="small" type="info" effect="plain">匿名</el-tag>
            </div>
            <div class="qi-sub">{{ it.homework_title }}</div>
            <div class="qi-meta">
              <span>{{ it.hw_type === 'open' ? '开放式' : '题集式' }}</span>
              <span v-if="it.hw_type !== 'open'">待批 {{ it.pending }} 题</span>
              <span>#{{ idx + 1 }} · {{ (it.submitted_at || '').slice(5, 16).replace('T', ' ') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右：批改面板 -->
      <div class="grade-pane">
        <el-empty v-if="!current" description="从左侧选择一份提交开始批改" :image-size="90" />
        <div v-else-if="panelLoading" class="center">加载批改详情…</div>
        <div v-else-if="grade">
          <div class="grade-head">
            <div>
              <b>{{ current.username }}</b>
              <span class="muted small" style="margin-left: 8px">{{ current.homework_title }}</span>
            </div>
            <el-tag v-if="grade.blind" size="small" type="info" effect="plain">匿名批改中</el-tag>
          </div>

          <!-- 开放式：正文 + 整体给分 -->
          <template v-if="grade.homework.hw_type === 'open'">
            <div class="label">学生提交内容</div>
            <pre class="content-box">{{ grade.submission.content || '（无正文）' }}</pre>
            <div class="score-row" style="margin-top: 12px">
              <span>总分 / 满分</span>
              <el-input-number v-model="openScore" :min="0" :max="1000" :step="1" size="small" controls-position="right" />
              <el-input-number v-model="openMax" :min="1" :max="1000" size="small" controls-position="right" />
            </div>
          </template>

          <!-- 题集式：逐题 -->
          <div v-else>
            <div v-for="row in rows" :key="row.id" class="answer-block" :class="{ pending: row.needs_manual }">
              <div class="q-head">
                <span class="q-type">{{ typeName(row.type) }}</span>
                <span class="q-content">{{ row.content }}</span>
                <el-tag v-if="row.needs_manual" size="small" type="warning">待批</el-tag>
                <el-tag v-else-if="row.oj_verdict" size="small" :type="row.oj_verdict === 'AC' ? 'success' : 'danger'">OJ: {{ row.oj_verdict }}</el-tag>
                <el-tag v-else size="small" :type="row.is_correct ? 'success' : 'info'">{{ row.is_correct ? '正确' : '自动判分' }}</el-tag>
              </div>
              <pre class="stu-ans">{{ row.answer || '（未作答）' }}</pre>
              <div v-if="row.reference" class="ref">参考答案：{{ row.reference }}</div>
              <div class="score-row">
                <span>得分 / {{ row.max_score }}</span>
                <el-input-number v-model="row.manual_score" :min="0" :max="row.max_score" size="small"
                                 controls-position="right" placeholder="人工分" />
                <el-input v-model="row.comment" size="small" placeholder="评语" style="flex: 1" />
              </div>
            </div>
          </div>

          <div class="label" style="margin-top: 14px">整体评语</div>
          <el-input v-model="overall" type="textarea" :rows="2" />

          <div class="grade-foot">
            <el-button v-if="grade.homework.hw_type !== 'open'" size="small" :loading="aiLoading" @click="askAi">AI 建议</el-button>
            <el-button type="primary" :loading="saving" @click="submitGrade">保存批改（Ctrl+Enter）</el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { EditPen, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const items = ref([])          // 队列条目
const homeworks = ref([])      // 每作业进度
const stats = ref({})          // 全局待批/已批
const hwFilter = ref(null)
const queueLoading = ref(false)

const current = ref(null)      // 选中的队列条目
const grade = ref(null)        // 批改详情
const rows = ref([])
const overall = ref('')
const openScore = ref(0)
const openMax = ref(100)
const panelLoading = ref(false)
const saving = ref(false)
const aiLoading = ref(false)

const typeName = (t) => ({ single_choice: '单选', multiple_choice: '多选', true_false: '判断',
  fill_blank: '填空', programming: '编程', short_answer: '简答', essay: '论述' }[t] || t)

const loadQueue = async () => {
  queueLoading.value = true
  try {
    const params = {}
    if (hwFilter.value) params.homework_id = hwFilter.value
    const res = await request.get('/api/homeworks/grading-queue', { params })
    items.value = res.data.items || []
    homeworks.value = res.data.homeworks || []
    stats.value = res.data.stats || {}
    // 当前选中若已不在队列（批完）→ 自动跳到队首，保持连贯
    if (current.value && !items.value.some(it => it.sub_id === current.value.sub_id)) {
      current.value = null
      grade.value = null
    }
  } finally {
    queueLoading.value = false
  }
}

const selectItem = async (it) => {
  if (current.value && current.value.sub_id === it.sub_id) return
  current.value = it
  panelLoading.value = true
  grade.value = null
  rows.value = []
  try {
    const res = await request.get(`/api/homeworks/${it.homework_id}/grade/${it.sub_id}`)
    grade.value = res.data
    overall.value = res.data.submission.comment || ''
    openScore.value = res.data.submission.total_score || 0
    openMax.value = res.data.submission.max_score || 100
    const qmap = {}
    ;(res.data.questions || []).forEach(q => { qmap[q.question_id] = q })
    rows.value = (res.data.answers || []).map(a => ({
      id: a.id, question_id: a.question_id, type: qmap[a.question_id]?.type,
      content: qmap[a.question_id]?.content || '', reference: qmap[a.question_id]?.answer || '',
      max_score: a.max_score ?? qmap[a.question_id]?.score ?? 100,
      answer: a.answer, is_correct: a.is_correct, oj_verdict: a.oj_verdict,
      needs_manual: a.needs_manual_grade, auto_score: a.auto_score,
      manual_score: a.manual_score, comment: a.comment || ''
    }))
  } catch {
    grade.value = null
  } finally {
    panelLoading.value = false
  }
}

const move = (delta) => {
  if (!items.value.length) return
  const idx = current.value ? items.value.findIndex(it => it.sub_id === current.value.sub_id) : -1
  let next = idx + delta
  if (next < 0) next = 0
  if (next >= items.value.length) next = items.value.length - 1
  selectItem(items.value[next])
}

const askAi = async () => {
  if (!current.value) return
  aiLoading.value = true
  try {
    const res = await request.post(
      `/api/homeworks/${current.value.homework_id}/grade/${current.value.sub_id}/ai_suggest`)
    const sg = res.data.suggestions || []
    sg.forEach(s => {
      const r = rows.value.find(x => x.id === s.answer_id)
      if (r && r.needs_manual) { r.manual_score = s.score; if (!r.comment) r.comment = s.comment }
    })
    ElMessage.success(sg.length ? `AI 已给出 ${sg.length} 题建议` : '无待批题目')
  } finally {
    aiLoading.value = false
  }
}

const submitGrade = async () => {
  if (!current.value || !grade.value) return
  saving.value = true
  try {
    const hwId = current.value.homework_id
    const subId = current.value.sub_id
    let payload
    if (grade.value.homework.hw_type === 'open') {
      payload = { comment: overall.value, score: openScore.value, max_score: openMax.value }
    } else {
      payload = {
        comment: overall.value,
        answers: rows.value
          .filter(r => r.needs_manual && (r.manual_score != null || r.comment))
          .map(r => ({ answer_id: r.id, score: r.manual_score, comment: r.comment }))
      }
    }
    const res = await request.post(`/api/homeworks/${hwId}/grade/${subId}`, payload)
    ElMessage.success(res.data.message || '已保存')
    // 刷新队列并自动进入下一份
    await loadQueue()
    if (items.value.length) selectItem(items.value[0])
  } finally {
    saving.value = false
  }
}

const onKey = (e) => {
  if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); move(-1) }
  else if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); move(1) }
  else if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); submitGrade() }
}

onMounted(() => {
  loadQueue()
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.stats-bar { display: flex; align-items: center; gap: 18px; margin-bottom: 12px;
  padding: 10px 14px; border-radius: 10px; font-size: 13px; color: #606266;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(139, 92, 246, 0.05)); }
.stats-bar b { color: #4f46e5; font-size: 16px; }
.muted { color: #909399; } .small { font-size: 12px; }
kbd { background: #f5f7fa; border: 1px solid #e4e7ed; border-radius: 4px; padding: 0 4px; font-size: 11px; }
.workbench { display: flex; gap: 14px; align-items: flex-start; }
.queue-pane { width: 320px; flex-shrink: 0; border: 1px solid #ebeef5; border-radius: 10px;
  max-height: 72vh; overflow: auto; }
.queue-item { padding: 10px 12px; border-bottom: 1px solid #f2f3f5; cursor: pointer; }
.queue-item:hover { background: #f8faff; }
.queue-item.active { background: #eef2ff; border-left: 3px solid #6366f1; }
.qi-head { display: flex; align-items: center; gap: 6px; }
.qi-name { font-weight: 600; color: #303133; }
.qi-sub { font-size: 13px; color: #4b5563; margin: 2px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qi-meta { display: flex; gap: 10px; font-size: 12px; color: #909399; }
.grade-pane { flex: 1; border: 1px solid #ebeef5; border-radius: 10px; padding: 14px 16px; min-height: 240px; }
.grade-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.center { text-align: center; padding: 40px; color: #909399; }
.label { font-weight: 500; margin-bottom: 6px; }
.answer-block { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; margin-bottom: 12px; }
.answer-block.pending { border-color: #e6a23c; }
.q-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.q-type { font-size: 12px; color: #909399; }
.q-content { flex: 1; font-weight: 500; }
.stu-ans { background: #f5f7fa; padding: 8px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; margin: 0 0 8px; max-height: 160px; overflow: auto; }
.ref { font-size: 12px; color: #67c23a; margin-bottom: 6px; }
.score-row { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #606266; }
.content-box { background: #f5f7fa; padding: 12px; border-radius: 4px; white-space: pre-wrap; max-height: 240px; overflow: auto; }
.grade-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; padding-top: 12px; border-top: 1px dashed #ebeef5; }
</style>
