<template>
  <div class="page-wrapper" v-loading="loading">
    <div class="page-header">
      <div>
        <h2>作业互评</h2>
        <div class="sub">匿名评审同学的作业，按准确性/完整性/规范性/创造性多维度打分；教师采纳后的互评按权重计入「互评加权分」，不改写官方成绩。</div>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button :icon="Back" @click="$router.push('/homeworks/my')">返回作业列表</el-button>
      </div>
    </div>

    <div class="progress-card" v-if="items.length">
      <div class="progress-text">
        互评进度：已完成 <b>{{ submittedItems.length }}</b> / {{ items.length }}
      </div>
      <el-progress :percentage="completionRate" :stroke-width="10"
                   :status="completionRate === 100 ? 'success' : ''" />
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane :label="`待互评 (${pendingItems.length})`" name="pending" />
      <el-tab-pane :label="`已提交 (${submittedItems.length})`" name="submitted" />
    </el-tabs>

    <template v-if="currentItems.length">
      <div v-for="it in currentItems" :key="it.review.id" class="task-card">
        <div class="task-main">
          <div class="task-title">
            {{ it.homework.title }}
            <el-tag size="small" effect="plain">
              {{ it.homework.hw_type === 'open' ? '开放式' : '题集式' }}
            </el-tag>
            <el-tag v-if="it.review.status === 'submitted'" size="small" type="success">
              已提交 · {{ it.review.score }} 分
            </el-tag>
            <el-tag v-else size="small" type="warning">待互评</el-tag>
            <el-tag v-if="it.homework.peer_review_weight > 0" size="small" type="info" effect="plain">
              权重 {{ Math.round(it.homework.peer_review_weight * 100) }}%
            </el-tag>
            <el-tag v-if="it.review.status === 'submitted' && it.review.audit_status === 'accepted'"
                    size="small" type="success" effect="dark">已采纳</el-tag>
            <el-tag v-if="it.review.status === 'submitted' && it.review.audit_status === 'rejected'"
                    size="small" type="danger" effect="plain">已驳回</el-tag>
          </div>
          <div class="task-sub">
            教师：{{ it.homework.teacher_name || '—' }}
            <span v-if="it.review.submitted_at"> · 提交于 {{ fmt(it.review.submitted_at) }}</span>
            <span v-else> · 收到于 {{ fmt(it.review.created_at) }}</span>
            <span v-if="it.homework.peer_review_deadline" class="deadline"
                  :class="{ overdue: isOverdue(it.homework.peer_review_deadline) }">
              · {{ deadlineText(it.homework.peer_review_deadline) }}
            </span>
          </div>
        </div>
        <el-button :type="it.review.status === 'pending' ? 'primary' : 'default'"
                   @click="openTask(it)">
          {{ it.review.status === 'pending' ? '开始互评' : '查看' }}
        </el-button>
      </div>
    </template>
    <el-empty v-else :description="tab === 'pending' ? '暂无待互评任务，老师分配后会通知你' : '还没有已提交的互评'" />

  <el-dialog v-model="dialogVisible" width="760px" top="6vh" destroy-on-close
             :title="detail ? `互评：${detail.homework.title}` : '作业互评'">
    <div v-if="detail" class="review-body">
      <el-alert type="info" :closable="false" show-icon
                title="匿名互评：你看不到作者信息，作者也看不到你的身份。请基于内容客观打分。" />
      <div class="submission-meta">
        <span>第 {{ detail.submission.version }} 次提交</span>
        <span v-if="detail.submission.submitted_at">提交时间：{{ fmt(detail.submission.submitted_at) }}</span>
        <el-tag v-if="detail.submission.is_late" size="small" type="warning">迟交</el-tag>
        <el-link v-if="detail.submission.attachment" type="primary" @click="downloadAtt">
          📎 {{ detail.submission.attachment.filename }}
        </el-link>
      </div>

      <div v-if="detail.homework.hw_type === 'open'" class="open-content">
        {{ detail.submission.content || '（未填写正文）' }}
      </div>
      <div v-else class="q-list">
        <div v-for="(q, i) in detail.questions" :key="q.question_id" class="q-item">
          <div class="q-head">
            <span class="q-idx">{{ i + 1 }}</span>
            <el-tag size="small" effect="plain">{{ typeName(q.type) }}</el-tag>
            <span class="q-score">{{ q.score }} 分</span>
          </div>
          <div class="q-content">{{ q.content }}</div>
          <div class="peer-answer">{{ q.peer_answer || '（未作答）' }}</div>
        </div>
      </div>

      <el-alert v-if="submitted && detail.review.audit_status !== 'pending'" :closable="false" show-icon
                :type="detail.review.audit_status === 'accepted' ? 'success' : 'warning'"
                :title="detail.review.audit_status === 'accepted' ? '教师已采纳你的互评（计入互评加权分）' : '教师已驳回该互评（不计入加权分）'">
        <div v-if="detail.review.teacher_comment">教师意见：{{ detail.review.teacher_comment }}</div>
      </el-alert>

      <div class="score-area">
        <div class="dims-head">
          <span class="label">维度评分</span>
          <span class="dim-total">加权总分 <b>{{ finalScore }}</b> / 100</span>
        </div>
        <div v-for="d in dimensions" :key="d.key" class="dim-row">
          <div class="dim-label">
            <span class="dim-name">{{ d.label }}</span>
            <span class="dim-weight">{{ Math.round(d.weight * 100) }}%</span>
            <span class="dim-hint-text">{{ d.hint }}</span>
          </div>
          <el-slider v-model="form.scores[d.key]" :min="0" :max="100" :step="1"
                     show-input :disabled="submitted" :show-input-controls="false" />
        </div>
        <el-input v-model="form.comment" type="textarea" :rows="4" maxlength="2000"
                  show-word-limit :disabled="submitted"
                  placeholder="给出具体建议：亮点、可改进之处（可选）" />
      </div>
    </div>
    <template #footer>
      <el-button @click="dialogVisible = false">关闭</el-button>
      <el-button v-if="!submitted" type="primary" :loading="submitting"
                 @click="submit">提交互评</el-button>
    </template>
  </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Back, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const loading = ref(false)
const items = ref([])
const tab = ref('pending')
const dialogVisible = ref(false)
const detail = ref(null)
const submitting = ref(false)
const dimensions = ref([])
const form = ref({ scores: {}, comment: '' })

const pendingItems = computed(() => items.value.filter(i => i.review.status === 'pending'))
const submittedItems = computed(() => items.value.filter(i => i.review.status === 'submitted'))
const currentItems = computed(() => (tab.value === 'pending' ? pendingItems.value : submittedItems.value))
const submitted = computed(() => detail.value && detail.value.review.status === 'submitted')
const completionRate = computed(() => items.value.length
  ? Math.round(submittedItems.value.length / items.value.length * 100) : 0)

// 与后端 compute_peer_final_score 同口径：已填维度按权重归一
const finalScore = computed(() => {
  let sum = 0
  let weight = 0
  dimensions.value.forEach(d => {
    const v = form.value.scores[d.key]
    if (typeof v === 'number') {
      sum += v * d.weight
      weight += d.weight
    }
  })
  return weight > 0 ? (sum / weight).toFixed(2) : '—'
})

const fmt = (v) => (v || '').slice(0, 16).replace('T', ' ')
const typeName = (t) => ({ single_choice: '单选', multiple_choice: '多选', true_false: '判断',
  fill_blank: '填空', programming: '编程', short_answer: '简答', essay: '论述' }[t] || t)

const isOverdue = (v) => new Date((v || '').replace(' ', 'T')) < new Date()
const deadlineText = (v) => {
  if (!v) return ''
  if (isOverdue(v)) return `互评已截止（${fmt(v)}）`
  const diff = new Date(v.replace(' ', 'T')) - new Date()
  const hours = Math.floor(diff / 3600000)
  const text = hours >= 24 ? `剩 ${Math.floor(hours / 24)} 天 ${hours % 24} 小时` : `剩 ${Math.max(hours, 1)} 小时`
  return `互评截止 ${fmt(v)}（${text}）`
}

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/homeworks/peer_reviews/mine')
    items.value = res.data.items || []
  } finally {
    loading.value = false
  }
}

const openTask = async (it) => {
  const res = await request.get(`/api/homeworks/${it.homework.id}/peer_reviews/${it.review.id}`)
  detail.value = res.data
  dimensions.value = res.data.dimensions || []
  const saved = res.data.review.scores || {}
  const scores = {}
  dimensions.value.forEach(d => {
    scores[d.key] = typeof saved[d.key] === 'number' ? saved[d.key] : 80
  })
  form.value = { scores, comment: res.data.review.comment || '' }
  dialogVisible.value = true
}

const downloadAtt = async () => {
  const res = await request.get(`/api/homeworks/${detail.value.homework.id}/attachment`,
    { params: { submission_id: detail.value.submission.id }, responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(res.data)
  link.download = (detail.value.submission.attachment && detail.value.submission.attachment.filename) || 'attachment'
  link.click()
  URL.revokeObjectURL(link.href)
}

const submit = async () => {
  const values = Object.values(form.value.scores)
  if (!values.length || values.some(v => typeof v !== 'number')) {
    return ElMessage.warning('请完成各维度评分')
  }
  submitting.value = true
  try {
    await request.post(`/api/homeworks/${detail.value.homework.id}/peer_reviews/${detail.value.review.id}`,
      { scores: form.value.scores, comment: form.value.comment })
    ElMessage.success('互评已提交，感谢你的反馈')
    dialogVisible.value = false
    await load()
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { padding: 20px; max-width: 960px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.page-header h2 { margin: 0; }
.sub { color: #6b7280; font-size: 13px; margin-top: 6px; }
.header-actions { display: flex; gap: 8px; }
.task-card { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 16px 18px; border: 1px solid #eef2f7; border-radius: 10px; margin-bottom: 12px;
  background: linear-gradient(135deg, #ffffff, #fafbff); transition: box-shadow .2s, transform .2s; }
.task-card:hover { box-shadow: 0 8px 24px rgba(99, 102, 241, 0.1); transform: translateY(-1px); }
.task-title { font-weight: 600; display: flex; align-items: center; gap: 8px; color: #111827; flex-wrap: wrap; }
.task-sub { font-size: 12px; color: #9ca3af; margin-top: 6px; }
.deadline { color: #6366f1; }
.deadline.overdue { color: #ef4444; }
.progress-card { padding: 12px 16px; margin-bottom: 12px; border-radius: 10px;
  background: linear-gradient(135deg, #f5f7ff, #fbfaff); border: 1px solid #eef2f7; }
.progress-text { font-size: 13px; color: #4b5563; margin-bottom: 8px; }
.dims-head { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px dashed #e5e7eb; }
.dim-total { color: #6366f1; font-size: 13px; }
.dim-total b { font-size: 18px; }
.dim-row { margin-bottom: 6px; }
.dim-label { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 2px; }
.dim-name { font-weight: 600; color: #374151; min-width: 56px; }
.dim-weight { font-size: 11px; color: #6366f1; background: #eef2ff;
  border-radius: 8px; padding: 1px 6px; }
.dim-hint-text { color: #9ca3af; font-size: 11px; }
.review-body { display: flex; flex-direction: column; gap: 12px; }
.submission-meta { display: flex; align-items: center; gap: 12px; font-size: 13px; color: #6b7280; flex-wrap: wrap; }
.open-content { white-space: pre-wrap; line-height: 1.7; background: #f8fafc; border-radius: 8px;
  padding: 14px; max-height: 320px; overflow: auto; }
.q-list { max-height: 340px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
.q-item { border: 1px solid #eef2f7; border-radius: 8px; padding: 12px; }
.q-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.q-idx { font-weight: 700; color: #6366f1; }
.q-score { font-size: 12px; color: #9ca3af; }
.q-content { line-height: 1.6; margin-bottom: 6px; }
.peer-answer { white-space: pre-wrap; background: #f8fafc; border-radius: 6px; padding: 8px 10px; color: #374151; }
.score-area { border-top: 1px solid #eef2f7; padding-top: 12px; }
.score-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.label { font-weight: 600; }
.unit { color: #9ca3af; font-size: 13px; }
</style>
