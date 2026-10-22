<template>
  <div class="page-wrapper" v-loading="loading">
    <div class="page-header" v-if="hw.id">
      <div class="header-title">
        <h2>{{ hw.title }}</h2>
        <div class="sub">
          <el-tag size="small" effect="plain">{{ hw.hw_type === 'open' ? '开放式' : '题集式' }}</el-tag>
          <el-tag v-if="hw.is_group" size="small" type="success" effect="plain">
            小组作业 · {{ myGroup?.name || '未分组' }}
            <template v-if="myGroup?.members?.length">（{{ myGroup.members.map(m => m.username).join('、') }}）</template>
          </el-tag>
          <span v-if="hw.has_deadline" :class="{ overdue: hw.is_expired }">截止 {{ (hw.deadline || '').slice(0, 16) }}</span>
          <span v-else>长期有效·不限期</span>
          <el-tag v-if="hw.is_expired" size="small" type="warning">已过截止{{ hw.allow_late ? '（可迟交）' : '（不再接收）' }}</el-tag>
        </div>
      </div>
      <el-button :icon="Back" @click="$router.push('/homeworks/my')">返回</el-button>
    </div>

    <el-alert v-if="hw.description" :closable="false" type="info" class="desc" >
      <div style="white-space: pre-wrap">{{ hw.description }}</div>
    </el-alert>

    <el-alert v-if="hw.reference" :closable="false" type="warning" class="desc">
      <span>📎 参考资料：</span>
      <el-link type="primary" @click="downloadRef">{{ hw.reference.filename }}</el-link>
    </el-alert>

    <!-- 已批改：成绩卡片 -->
    <el-card v-if="submission && submission.status === 'graded'" class="score-card" shadow="never">
      <div class="score-line">
        <span class="big">{{ submission.total_score }}</span>
        <span class="of">/ {{ submission.max_score ?? '—' }}</span>
        <el-tag type="success" size="small">已批改</el-tag>
        <el-tag v-if="hw.pass_score != null && submission.total_score != null"
                :type="submission.total_score >= hw.pass_score ? 'success' : 'danger'" size="small">
          {{ submission.total_score >= hw.pass_score ? '及格' : '未及格' }}
        </el-tag>
        <el-tag v-if="submission.is_late" type="warning" size="small">迟交</el-tag>
      </div>
      <div v-if="submission.comment" class="teacher-comment">教师评语：{{ submission.comment }}</div>
      <div v-if="hw.hw_type !== 'open'" class="wrongbook-tip">
        <router-link to="/learning/wrong">得分率不足的题目已自动收入错题本，前往复习 →</router-link>
      </div>
    </el-card>

    <!-- v5.3 班级 AI 讲评（教师发布后可见） -->
    <el-card v-if="classReview" class="review-card" shadow="never">
      <template #header>
        <span class="review-title"><el-icon><ChatLineSquare /></el-icon> 班级讲评</span>
      </template>
      <AiReviewContent :content="classReview.content" kind="class"
                       :degraded="classReview.degraded" />
    </el-card>

    <!-- v5.3 单份 AI 个性化讲评（批改后可见） -->
    <el-card v-if="personalReview" class="review-card personal" shadow="never">
      <template #header>
        <span class="review-title"><el-icon><MagicStick /></el-icon> 我的个性化讲评</span>
      </template>
      <AiReviewContent :content="personalReview.content" kind="submission"
                       :degraded="personalReview.degraded" />
    </el-card>

    <!-- v5.5 生生互评结果（批改后匿名展示） -->
    <el-card v-if="peerReview" class="review-card peer" shadow="never">
      <template #header>
        <span class="review-title"><el-icon><UserFilled /></el-icon> 同学互评（匿名）</span>
      </template>
      <div class="peer-avg">
        <span class="peer-score">{{ peerReview.avg_score ?? '—' }}</span>
        <span class="of">/ 100 互评均分 · {{ peerReview.count }} 份</span>
      </div>
      <div v-for="(c, i) in peerReview.comments" :key="i" class="peer-comment">
        <div class="peer-comment-head">
          匿名同学 {{ i + 1 }}
          <el-tag size="small" effect="plain">{{ c.score }} 分</el-tag>
        </div>
        <div class="peer-comment-body">{{ c.comment || '（未留评语）' }}</div>
      </div>
    </el-card>

    <!-- 开放式 -->
    <div v-if="hw.hw_type === 'open'" class="open-area">
      <div class="label">作业正文</div>
      <el-input v-model="content" type="textarea" :rows="12" :disabled="!editable"
                placeholder="在此作答，或下方上传附件" />
      <div class="attach-row">
        <span class="label">附件</span>
        <template v-if="editable">
          <input type="file" @change="onFile" />
          <span v-if="pickedFile" class="picked">已选：{{ pickedFile.name }}</span>
        </template>
        <a v-else-if="attachment" :href="attUrl" target="_blank">{{ attachment.filename }}</a>
        <span v-else class="muted">无</span>
      </div>
    </div>

    <!-- 题集式 -->
    <div v-else class="quiz-area">
      <div v-for="(q, i) in questions" :key="q.question_id" class="q-item">
        <div class="q-title">
          <span class="q-idx">{{ i + 1 }}</span>
          <el-tag size="small" effect="plain">{{ typeName(q.type) }}</el-tag>
          <span class="q-score">{{ q.score }} 分</span>
          <el-tag v-if="scoreMap[q.question_id] != null" size="small"
                  :type="scoreMap[q.question_id] > 0 ? 'success' : 'info'">
            得分 {{ scoreMap[q.question_id] }}
          </el-tag>
        </div>
        <div class="q-content">{{ q.content }}</div>

        <!-- 单选 / 判断 -->
        <el-radio-group v-if="isSingle(q.type)" v-model="answers[q.question_id]" :disabled="!editable">
          <el-radio v-for="(opt, idx) in optionList(q)" :key="idx" :value="letter(idx)" class="opt">
            {{ opt }}
          </el-radio>
        </el-radio-group>
        <!-- 多选 -->
        <el-checkbox-group v-else-if="q.type === 'multiple_choice'" v-model="multi[q.question_id]" :disabled="!editable">
          <el-checkbox v-for="(opt, idx) in optionList(q)" :key="idx" :value="letter(idx)" class="opt">
            {{ opt }}
          </el-checkbox>
        </el-checkbox-group>
        <!-- 编程 -->
        <el-input v-else-if="q.type === 'programming'" v-model="answers[q.question_id]" type="textarea"
                  :rows="10" class="code" :disabled="!editable" placeholder="请输入完整可运行代码" />
        <!-- 其余主观/填空 -->
        <el-input v-else v-model="answers[q.question_id]" type="textarea" :rows="3"
                  :disabled="!editable" placeholder="请输入答案" />
      </div>
    </div>

    <div class="foot-bar" v-if="editable">
      <el-button @click="saveDraft" :loading="savingDraft">保存草稿</el-button>
      <el-button type="primary" @click="doSubmit" :loading="submitting">提交作业</el-button>
    </div>
    <el-alert v-else-if="submission" :closable="false" type="success" class="done-tip"
              :title="submission.status === 'submitted' ? '已提交，等待老师批改' : '本次作业已完成'" />
    <div v-if="!editable && submission && submission.status === 'submitted' && hw.hw_type !== 'open'"
         class="wrongbook-tip">
      <router-link to="/learning/wrong">错题已自动收入错题本（正确答案与归因待批改后可见）→</router-link>
    </div>

    <!-- v5.4 作业讨论区 -->
    <el-card class="review-card discuss" shadow="never">
      <template #header>
        <span class="review-title"><el-icon><ChatDotRound /></el-icon> 作业讨论区</span>
      </template>
      <HomeworkDiscussion :homework-id="hwId" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Back, ChatLineSquare, ChatDotRound, MagicStick, UserFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import AiReviewContent from '../components/AiReviewContent.vue'
import HomeworkDiscussion from '../components/HomeworkDiscussion.vue'

const route = useRoute()
const hwId = route.params.id
const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

const loading = ref(false)
const savingDraft = ref(false)
const submitting = ref(false)
const hw = ref({})
const editable = ref(false)
const questions = ref([])
const answers = reactive({})       // 单选/判断/填空/主观/编程：字符串
const multi = reactive({})         // 多选：数组
const content = ref('')
const attachment = ref(null)
const pickedFile = ref(null)
const submission = ref(null)
const scoreMap = reactive({})      // question_id -> 学生可见得分（ graded 后）
const classReview = ref(null)      // 班级讲评（教师发布后）
const personalReview = ref(null)   // 单份 AI 讲评（批改后）
const peerReview = ref(null)       // 生生互评结果（批改后匿名）
const myGroup = ref(null)          // 小组作业：本人所在小组

const typeName = (t) => ({ single_choice: '单选', multiple_choice: '多选', true_false: '判断',
  fill_blank: '填空', programming: '编程', short_answer: '简答', essay: '论述' }[t] || t)
const isSingle = (t) => t === 'single_choice' || t === 'true_false'
const letter = (idx) => LETTERS[idx]
const optionList = (q) => (Array.isArray(q.options) ? q.options : [])
const attUrl = computed(() => `/api/homeworks/${hwId}/attachment`)

const downloadRef = async () => {
  const res = await request.get(`/api/homeworks/${hwId}/reference`, { responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(res.data)
  link.download = (hw.value.reference && hw.value.reference.filename) || 'reference'
  link.click()
  URL.revokeObjectURL(link.href)
}

const collectAnswers = () => {
  const out = {}
  questions.value.forEach(q => {
    if (q.type === 'multiple_choice') out[q.question_id] = (multi[q.question_id] || []).join('')
    else out[q.question_id] = answers[q.question_id] || ''
  })
  return out
}

const load = async () => {
  loading.value = true
  try {
    const res = await request.get(`/api/homeworks/${hwId}/take`)
    const d = res.data
    hw.value = d.homework
    editable.value = d.editable
    questions.value = d.questions || []
    const exist = d.answers || {}
    questions.value.forEach(q => {
      if (q.type === 'multiple_choice') {
        multi[q.question_id] = String(exist[q.question_id] || '').split('').filter(c => /[A-Za-z]/.test(c)).map(c => c.toUpperCase())
      } else {
        answers[q.question_id] = exist[q.question_id] || ''
      }
    })
    if (d.homework.hw_type === 'open') {
      content.value = d.content || ''
      attachment.value = d.attachment || null
    }
    submission.value = d.submission || null
    myGroup.value = d.my_group || null
    if (submission.value) await loadResult()
  } finally {
    loading.value = false
  }
}

const loadResult = async () => {
  const res = await request.get(`/api/homeworks/${hwId}/result`)
  const d = res.data
  submission.value = d.submission
  classReview.value = d.class_review || null
  personalReview.value = d.ai_review || null
  peerReview.value = d.peer_review || null
  if (submission.value.status === 'graded') {
    ;(d.answers || []).forEach(a => {
      if (a.auto_score != null) scoreMap[a.question_id] = a.auto_score
    })
  }
}

const saveDraft = async () => {
  savingDraft.value = true
  try {
    const payload = hw.value.hw_type === 'open'
      ? { content: content.value }
      : { answers: collectAnswers() }
    const res = await request.post(`/api/homeworks/${hwId}/answers`, payload)
    ElMessage.success(res.data.message || '已保存')
  } finally {
    savingDraft.value = false
  }
}

const onFile = (e) => { pickedFile.value = e.target.files[0] || null }

const doSubmit = async () => {
  if (hw.value.hw_type === 'open') {
    if (!content.value.trim() && !pickedFile.value) {
      return ElMessage.warning('请至少填写正文或上传附件')
    }
  }
  await ElMessageBox.confirm('提交后在允许重交前可修改，确认提交？', '提交作业', { type: 'warning' })
  submitting.value = true
  try {
    let res
    if (hw.value.hw_type === 'open' && pickedFile.value) {
      const fd = new FormData()
      fd.append('content', content.value)
      fd.append('file', pickedFile.value)
      res = await request.post(`/api/homeworks/${hwId}/submit`, fd,
        { headers: { 'Content-Type': 'multipart/form-data' } })
    } else {
      const payload = hw.value.hw_type === 'open'
        ? { content: content.value }
        : { answers: collectAnswers() }
      res = await request.post(`/api/homeworks/${hwId}/submit`, payload)
    }
    ElMessage.success(res.data.message || '提交成功')
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
.sub { display: flex; align-items: center; gap: 12px; margin-top: 6px; color: #606266; font-size: 13px; }
.overdue { color: #f56c6c; }
.desc { margin-bottom: 14px; }
.score-card { margin-bottom: 16px; background: #f0f9eb; border-color: #e1f3d8; }
.score-line { display: flex; align-items: baseline; gap: 8px; }
.big { font-size: 32px; font-weight: 700; color: #67c23a; }
.of { font-size: 16px; color: #909399; }
.teacher-comment { margin-top: 8px; color: #606266; }
.wrongbook-tip { margin-top: 8px; font-size: 13px; }
.wrongbook-tip a { color: var(--el-color-primary); text-decoration: none; }
.wrongbook-tip a:hover { text-decoration: underline; }
.review-card { margin-bottom: 16px; border-color: rgba(99, 102, 241, 0.2); }
.review-card.personal { border-color: rgba(6, 182, 212, 0.24); }
.review-card.peer { border-color: rgba(245, 158, 11, 0.26); }
.review-card.discuss { border-color: rgba(139, 92, 246, 0.2); }
.review-title { display: flex; align-items: center; gap: 6px; font-weight: 600; color: #4b5563; }
.review-title .el-icon { color: #6366f1; }
.review-card.personal .review-title .el-icon { color: #06b6d4; }
.review-card.peer .review-title .el-icon { color: #f59e0b; }
.review-card.discuss .review-title .el-icon { color: #8b5cf6; }
.peer-avg { display: flex; align-items: baseline; gap: 8px; margin-bottom: 10px; }
.peer-score { font-size: 28px; font-weight: 700; color: #f59e0b; }
.peer-comment { background: #fffbeb; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.peer-comment-head { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #92400e; margin-bottom: 4px; }
.peer-comment-body { color: #4b5563; line-height: 1.6; white-space: pre-wrap; }
.label { font-weight: 600; margin-bottom: 8px; display: block; }
.open-area { margin-top: 8px; }
.attach-row { margin-top: 12px; display: flex; align-items: center; gap: 10px; }
.attach-row .label { margin: 0; }
.picked { color: #67c23a; font-size: 13px; }
.q-item { border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 16px; margin-bottom: 14px; }
.q-title { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.q-idx { font-weight: 700; color: #6366f1; }
.q-score { color: #909399; font-size: 13px; }
.q-content { margin-bottom: 10px; line-height: 1.6; }
.opt { display: block; margin-bottom: 6px; }
.code :deep(textarea) { font-family: Consolas, Monaco, monospace; }
.foot-bar { position: sticky; bottom: 0; background: #fff; padding: 12px 0; border-top: 1px solid #ebeef5; text-align: right; }
.done-tip { margin-top: 12px; }
.muted { color: #909399; }
</style>
