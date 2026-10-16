<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><EditPen /></el-icon> {{ hw.title || '作业批改' }}</h2>
        <el-tag size="small" effect="plain" style="margin-left: 10px">
          {{ hw.hw_type === 'open' ? '开放式' : '题集式' }}
        </el-tag>
      </div>
      <el-button :icon="Back" @click="$router.push('/homeworks/manage')">返回</el-button>
    </div>

    <div class="summary">
      名单 {{ studentCount }} 人 · 已提交 {{ items.length }} 份
      <span v-if="notSubmitted.length" class="not-sub">· 未提交：{{ notSubmitted.map(n => n.username).join('、') }}</span>
    </div>

    <el-empty v-if="!items.length" description="还没有学生提交" />
    <el-table v-else :data="items" stripe @row-click="openGrade">
      <el-table-column prop="username" label="学生" width="140" />
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="70" align="center">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column label="得分" width="130" align="center">
        <template #default="{ row }">
          <span v-if="row.status === 'graded'">{{ row.total_score }} / {{ row.max_score ?? '—' }}</span>
          <span v-else class="muted">待批改</span>
        </template>
      </el-table-column>
      <el-table-column label="迟交" width="70" align="center">
        <template #default="{ row }"><el-tag v-if="row.is_late" size="small" type="warning">迟交</el-tag></template>
      </el-table-column>
      <el-table-column label="提交时间" width="160">
        <template #default="{ row }">{{ (row.submitted_at || '').slice(0, 16) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click.stop="openGrade(row)">批改</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 批改抽屉 -->
    <el-drawer v-model="drawer" :title="`批改：${current?.username || ''}`" size="660px">
      <div v-if="loading" class="center">加载中…</div>
      <div v-else-if="grade">
        <!-- 开放式：正文 + 附件 + 整体给分 -->
        <template v-if="grade.homework.hw_type === 'open'">
          <div class="label">学生提交内容</div>
          <pre class="content-box">{{ grade.submission.content || '（无正文）' }}</pre>
          <div v-if="grade.submission.attachment" class="attach">
            附件：<a :href="attachUrl(grade.submission.id)" target="_blank">{{ grade.submission.attachment.filename }}</a>
          </div>
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
      </div>
      <template #footer>
        <el-button v-if="grade && grade.homework.hw_type !== 'open'" :loading="aiLoading" @click="askAi">AI 建议</el-button>
        <el-button type="primary" :loading="saving" @click="submitGrade">保存批改</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { EditPen, Back } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const route = useRoute()
const hwId = route.params.id
const hw = ref({})
const items = ref([])
const notSubmitted = ref([])
const studentCount = ref(0)
const drawer = ref(false)
const loading = ref(false)
const saving = ref(false)
const aiLoading = ref(false)
const grade = ref(null)
const rows = ref([])          // 题集式：答案与题面合并视图
const current = ref(null)
const overall = ref('')
const openScore = ref(0)
const openMax = ref(100)

const statusText = (s) => ({ submitted: '待批改', graded: '已批改' }[s] || s)
const statusTag = (s) => ({ submitted: 'warning', graded: 'success' }[s] || 'info')
const typeName = (t) => ({ single_choice: '单选', multiple_choice: '多选', true_false: '判断',
  fill_blank: '填空', programming: '编程', short_answer: '简答', essay: '论述' }[t] || t)

const load = async () => {
  const [detail, subs] = await Promise.all([
    request.get(`/api/homeworks/${hwId}`),
    request.get(`/api/homeworks/${hwId}/submissions`)
  ])
  hw.value = detail.data
  items.value = subs.data.items || []
  notSubmitted.value = subs.data.not_submitted || []
  studentCount.value = subs.data.student_count || 0
}

const openGrade = async (row) => {
  current.value = row
  drawer.value = true
  loading.value = true
  grade.value = null
  rows.value = []
  try {
    const res = await request.get(`/api/homeworks/${hwId}/grade/${row.id}`)
    grade.value = res.data
    overall.value = res.data.submission.comment || ''
    openScore.value = res.data.submission.total_score || 0
    openMax.value = res.data.submission.max_score || 100
    // 题面元数据（content/type/answer）在 questions 里，按 question_id 合并到逐题行
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
  } finally {
    loading.value = false
  }
}

const attachUrl = (subId) => `/api/homeworks/${hwId}/attachment?submission_id=${subId}`

const askAi = async () => {
  aiLoading.value = true
  try {
    const res = await request.post(`/api/homeworks/${hwId}/grade/${current.value.id}/ai_suggest`)
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
  saving.value = true
  try {
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
    const res = await request.post(`/api/homeworks/${hwId}/grade/${current.value.id}`, payload)
    ElMessage.success(res.data.message || '已保存')
    drawer.value = false
    load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.summary { margin-bottom: 12px; color: #606266; font-size: 14px; }
.not-sub { color: #f56c6c; }
.muted { color: #909399; }
.center { text-align: center; padding: 40px; color: #909399; }
.answer-block { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; margin-bottom: 12px; }
.answer-block.pending { border-color: #e6a23c; }
.q-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.q-type { font-size: 12px; color: #909399; }
.q-content { flex: 1; font-weight: 500; }
.stu-ans { background: #f5f7fa; padding: 8px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; margin: 0 0 8px; max-height: 160px; overflow: auto; }
.ref { font-size: 12px; color: #67c23a; margin-bottom: 6px; }
.score-row { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #606266; }
.content-box { background: #f5f7fa; padding: 12px; border-radius: 4px; white-space: pre-wrap; max-height: 240px; overflow: auto; }
.label { font-weight: 500; margin-bottom: 6px; }
.attach { margin: 8px 0; }
:deep(.el-table__row) { cursor: pointer; }
</style>
