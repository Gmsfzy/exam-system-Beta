<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="$router.push('/bounties')" content="悬赏详情" class="back">
      <template #extra v-if="bounty && bounty.is_publisher">
        <el-button v-if="canEdit" size="small" :icon="EditPen" @click="openEdit">编辑</el-button>
        <el-button v-if="bounty.status === 'open'" size="small" type="warning" plain @click="closeBounty">关闭</el-button>
        <el-button v-if="!bounty.accept_count && !bounty.accepted_submission_id" size="small" type="danger" plain @click="deleteBounty">删除</el-button>
      </template>
    </el-page-header>

    <template v-if="bounty">
      <!-- 悬赏信息 -->
      <div class="bounty-head section">
        <div class="head-row">
          <el-tag :type="bounty.bounty_type === 'question' ? 'primary' : 'success'" effect="light">
            {{ bounty.bounty_type === 'question' ? '题目征集' : '答案征集' }}
          </el-tag>
          <el-tag :type="statusTag(bounty.status)" effect="plain">{{ statusText(bounty.status) }}</el-tag>
          <el-tag v-if="bounty.is_publisher" type="warning" effect="plain">我发布的</el-tag>
          <el-tag v-if="bounty.visibility === 'targeted'" type="danger" effect="plain"><el-icon><Lock /></el-icon> 定向</el-tag>
          <el-button v-if="!bounty.is_publisher" link size="small" :icon="Warning" class="report-btn" @click="report">举报</el-button>
        </div>
        <h2 class="bounty-title">{{ bounty.title }}</h2>
        <p class="bounty-desc">{{ bounty.description || '暂无详细描述' }}</p>
        <div v-if="bounty.tags" class="bounty-tags">
          <el-tag v-for="t in bounty.tags.split(',')" :key="t" size="small" effect="plain" type="info">{{ t.trim() }}</el-tag>
        </div>
        <div class="head-meta">
          <span class="reward"><el-icon><GoldMedal /></el-icon> 赏金 {{ bounty.reward_points }} 积分</span>
          <span v-if="(bounty.max_accepts || 1) > 1">采纳名额：{{ bounty.accept_count }}/{{ bounty.max_accepts }}</span>
          <span>发布者：{{ bounty.publisher_name }}</span>
          <span v-if="bounty.bounty_type === 'question'">专业：{{ bounty.major_name }}</span>
          <span>截止：{{ bounty.deadline ? bounty.deadline.slice(0, 16) : '长期有效' }}</span>
        </div>

        <!-- 答案悬赏：目标题展示 -->
        <div v-if="bounty.bounty_type === 'answer'" class="target-question">
          <div class="tq-label">目标题目：</div>
          <div v-if="targetQ" class="tq-content">
            <div>{{ targetQ.content }}</div>
            <div v-if="targetQ.options" class="tq-options">
              <div v-for="(opt, i) in normalizeOptions(targetQ.options)" :key="i">{{ opt }}</div>
            </div>
          </div>
          <div v-else-if="bounty.target_question_snapshot" class="tq-content">
            <div>{{ bounty.target_question_snapshot.content }}</div>
          </div>
        </div>
      </div>

      <!-- 已采纳结果（多档） -->
      <div v-if="acceptedList.length" class="section accepted-box">
        <h3 class="section-title"><el-icon><CircleCheck /></el-icon> 已采纳投稿（{{ acceptedList.length }}）</h3>
        <div v-for="a in acceptedList" :key="a.id" class="q-block" style="margin-bottom: 10px">
          <div class="accepted-meta">投稿人：{{ a.submitter_name }} · 获得 <b class="reward">{{ a.reward_share || bounty.reward_points }}</b> 积分</div>
          <template v-if="bounty.bounty_type === 'question'">
            <div class="q-content">{{ a.q_content }}</div>
            <div class="q-answer">答案：{{ a.q_answer }}</div>
            <div v-if="a.q_analysis" class="q-analysis">解析：{{ a.q_analysis }}</div>
            <el-alert v-if="a.accepted_question_id" type="success" :closable="false"
                      :title="`题目已收录进题库（#${a.accepted_question_id}）`" class="inq-alert" />
          </template>
          <template v-else>
            <div class="q-content">{{ a.content }}</div>
          </template>
        </div>
      </div>

      <!-- 发布者：投稿审核列表 -->
      <div v-if="bounty.is_publisher && hasSlots" class="section">
        <h3 class="section-title">投稿审核（{{ pendingSubs.length }} 待审）</h3>
        <el-empty v-if="!submissions.length" description="暂无投稿" />
        <div v-for="s in submissions" :key="s.id" class="sub-card">
          <div class="sub-head">
            <span class="sub-author">{{ s.submitter_name }}</span>
            <el-tag size="small" :type="subStatusTag(s.status)">{{ subStatusText(s.status) }}</el-tag>
            <el-button link size="small" :icon="Star" @click="vote(s)">投票 {{ s.vote_count || 0 }}</el-button>
            <span class="sub-time">{{ s.created_at?.slice(0, 16) }}</span>
          </div>
          <template v-if="bounty.bounty_type === 'question'">
            <div class="q-content">{{ s.q_content }}</div>
            <div class="q-answer">答案：{{ s.q_answer }}</div>
            <div v-if="s.q_analysis" class="q-analysis">解析：{{ s.q_analysis }}</div>
          </template>
          <template v-else>
            <div class="q-content">{{ s.content }}</div>
          </template>
          <div v-if="s.status === 'pending'" class="sub-actions">
            <el-button size="small" type="success" @click="accept(s)">采纳</el-button>
            <el-button size="small" type="danger" plain @click="reject(s)">拒绝</el-button>
          </div>
          <div v-if="s.attachments?.length" class="sub-attach">
            <span>附件：</span>
            <el-button v-for="(att, i) in s.attachments" :key="i" link type="primary" size="small" @click="downloadAttachment(s.id, i, att)">📎 附件{{ i + 1 }}（{{ fmtSize(att.size) }}）</el-button>
          </div>
          <div v-if="s.review_comment" class="review-comment">审核备注：{{ s.review_comment }}</div>
          <div v-if="s.attachments?.length" class="sub-attach">
            <span>附件：</span>
            <el-button v-for="(a, i) in s.attachments" :key="i" link type="primary" size="small" @click="downloadAttachment(s.id, i, a)">
              📎 附件{{ i + 1 }}（{{ fmtSize(a.size) }}）
            </el-button>
          </div>
        </div>
      </div>

      <!-- 非发布者：已投稿件（可撤回/修改） + 投稿表单 -->
      <div v-if="!bounty.is_publisher && bounty.status === 'open'" class="section">
        <h3 class="section-title">{{ mySubmission ? '我的投稿' : '我要投稿' }}</h3>

        <template v-if="mySubmission">
          <el-alert :type="mySubmission.status === 'accepted' ? 'success' : 'info'" :closable="false"
                    class="my-sub-alert" :title="`你的投稿状态：${subStatusText(mySubmission.status)}`" />
          <div class="q-block">
            <template v-if="bounty.bounty_type === 'question'">
              <div class="q-content">{{ mySubmission.q_content }}</div>
              <div class="q-answer">答案：{{ mySubmission.q_answer }}</div>
            </template>
            <template v-else><div class="q-content">{{ mySubmission.content }}</div></template>
          </div>
          <div v-if="mySubmission.status === 'pending'" class="sub-actions">
            <el-button size="small" @click="startEditSubmission">修改投稿</el-button>
            <el-button size="small" @click="pickAttachment">📎 上传附件</el-button>
            <el-button size="small" type="danger" plain @click="withdraw">撤回</el-button>
          </div>
          <div v-if="mySubmission.attachments?.length" class="sub-attach">
            <span>附件：</span>
            <el-button v-for="(a, i) in mySubmission.attachments" :key="i" link type="primary" size="small" @click="downloadAttachment(mySubmission.id, i, a)">
              📎 附件{{ i + 1 }}（{{ fmtSize(a.size) }}）
            </el-button>
            <template v-if="mySubmission.status === 'pending'">
              <el-button v-for="(a, i) in mySubmission.attachments" :key="'d' + i" link type="danger" size="small" @click="removeAttachment(i)">删除{{ i + 1 }}</el-button>
            </template>
          </div>
        </template>

        <el-form v-if="!mySubmission || editingSubmission" :model="form" label-width="90px" v-loading="submitting">
          <template v-if="bounty.bounty_type === 'question'">
            <el-form-item label="题干" required>
              <el-input v-model="form.q_content" type="textarea" :rows="2" placeholder="请输入完整题目" />
            </el-form-item>
            <el-form-item label="选项（每行一个，选填）">
              <el-input v-model="optionsText" type="textarea" :rows="4"
                        placeholder="A. 选项一&#10;B. 选项二&#10;C. 选项三&#10;D. 选项四" />
            </el-form-item>
            <el-form-item label="答案" required>
              <el-input v-model="form.q_answer" placeholder="如：A 或 ABC 或填空答案" />
            </el-form-item>
            <el-form-item label="解析">
              <el-input v-model="form.q_analysis" type="textarea" :rows="2" placeholder="答案解析（选填）" />
            </el-form-item>
            <el-form-item label="题型">
              <el-select v-model="form.q_type" style="width: 100%">
                <el-option v-for="(label, key) in qTypes" :key="key" :label="label" :value="key" />
              </el-select>
            </el-form-item>
            <el-form-item label="难度">
              <el-select v-model="form.q_difficulty" style="width: 100%">
                <el-option v-for="(label, key) in qDiffs" :key="key" :label="label" :value="key" />
              </el-select>
            </el-form-item>
            <el-form-item label="知识点">
              <el-input v-model="form.q_knowledge" placeholder="多个知识点用逗号分隔（选填）" />
            </el-form-item>
          </template>
          <template v-else>
            <el-form-item label="答案/解析" required>
              <el-input v-model="form.content" type="textarea" :rows="6" placeholder="请给出完整答案与解析过程" />
            </el-form-item>
          </template>
          <el-form-item label="匿名投稿">
            <el-switch v-model="form.is_anonymous" />
            <span class="hint">匿名后其他用户看不到你的身份（发布者与本人仍可见）</span>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Promotion" @click="submit">{{ editingSubmission ? '保存修改' : '提交投稿' }}</el-button>
            <el-button v-if="editingSubmission" @click="editingSubmission = false">取消</el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- 讨论区 -->
      <div class="section">
        <h3 class="section-title">讨论区（{{ comments.length }}）</h3>
        <el-empty v-if="!comments.length" :image-size="60" description="还没有讨论" />
        <div v-for="c in comments" :key="c.id" class="comment-item">
          <div class="comment-head">
            <span class="sub-author">{{ c.user_name }}</span>
            <span class="sub-time">{{ c.created_at?.slice(0, 16) }}</span>
            <el-button v-if="c.user_id === currentUserId || bounty.is_publisher" link size="small"
                       type="danger" @click="delComment(c)">删除</el-button>
          </div>
          <div class="comment-body">{{ c.content }}</div>
        </div>
        <div class="comment-form">
          <el-input v-model="newComment" type="textarea" :rows="2" placeholder="写下你的想法…" maxlength="2000" show-word-limit />
          <el-button type="primary" size="small" style="margin-top: 8px" @click="addComment">发表评论</el-button>
        </div>
      </div>
    </template>

    <!-- 编辑悬赏对话框 -->
    <el-dialog v-model="editVisible" title="编辑悬赏" width="520px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="标题"><el-input v-model="editForm.title" maxlength="100" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="editForm.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="标签"><el-input v-model="editForm.tags" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="采纳名额"><el-input-number v-model="editForm.max_accepts" :min="1" :max="20" /></el-form-item>
        <el-form-item label="截止时间">
          <el-date-picker v-model="editForm.deadline" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button></template>
    </el-dialog>

    <!-- 投稿附件选择（隐藏 input，v4.6 统一白名单） -->
    <input ref="attachInput" type="file" style="display: none"
           accept=".pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx,.csv,.zip,.rar,.7z,.png,.jpg,.jpeg,.gif,.webp,.mp4,.webm,.py,.java,.c,.cpp,.js,.ts,.html,.css,.sql"
           @change="onAttachPicked" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { GoldMedal, CircleCheck, Promotion, EditPen, Star, Lock, Warning } from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const auth = useAuthStore()
const currentUserId = computed(() => auth.user?.id)
const loading = ref(false)
const submitting = ref(false)
const bounty = ref(null)
const submissions = ref([])
const comments = ref([])
const newComment = ref('')
const optionsText = ref('')
const editingSubmission = ref(false)
const editVisible = ref(false)

// v4.6.1 枚举收敛：题型/难度单一来源 frontend/src/utils/enums.js（顺手修正旧 map 中 short_answer/essay 标签互换的漂移）
import { QUESTION_TYPE_LABELS, DIFFICULTY_LABELS } from '../utils/enums'

const qTypes = QUESTION_TYPE_LABELS
const qDiffs = DIFFICULTY_LABELS

const form = reactive({
  q_content: '', q_answer: '', q_analysis: '',
  q_type: 'single_choice', q_difficulty: 'medium', q_knowledge: '',
  content: '', is_anonymous: false,
})
const editForm = reactive({ title: '', description: '', tags: '', max_accepts: 1, deadline: '' })

const statusText = (s) => ({ open: '征集中', closed: '已采纳', expired: '已过期', cancelled: '已关闭' }[s] || s)
const statusTag = (s) => ({ open: 'warning', closed: 'success', expired: 'info', cancelled: 'info' }[s] || 'info')
const subStatusText = (s) => ({ pending: '待审核', accepted: '已采纳', rejected: '已拒绝', withdrawn: '已撤回' }[s] || s)
const subStatusTag = (s) => ({ pending: 'warning', accepted: 'success', rejected: 'danger', withdrawn: 'info' }[s] || 'info')

const mySubmission = computed(() => bounty.value?.my_submission || null)
const targetQ = computed(() => bounty.value?.target_question || null)
const acceptedList = computed(() => bounty.value?.accepted_submissions || [])
const pendingSubs = computed(() => submissions.value.filter(s => s.status === 'pending'))
const hasSlots = computed(() => bounty.value && (bounty.value.status === 'open' && bounty.value.is_publisher))
const canEdit = computed(() => bounty.value?.is_publisher && bounty.value?.status === 'open' && !(bounty.value?.accept_count > 0))

const normalizeOptions = (opts) => {
  if (Array.isArray(opts)) return opts
  if (typeof opts === 'string') { try { return JSON.parse(opts) } catch { return [opts] } }
  return []
}

const loadComments = async () => {
  try {
    const res = await request.get(`/api/bounties/${route.params.id}/comments`)
    comments.value = res.data || []
  } catch { comments.value = [] }
}

const load = async () => {
  loading.value = true
  try {
    const id = route.params.id
    const [detailRes, subRes] = await Promise.all([
      request.get(`/api/bounties/${id}`),
      request.get(`/api/bounties/${id}/submissions`).catch(() => ({ data: [] }))
    ])
    bounty.value = detailRes.data
    submissions.value = subRes.data || []
    await loadComments()
  } finally {
    loading.value = false
  }
}

const submit = async () => {
  if (bounty.value.bounty_type === 'question') {
    if (!form.q_content.trim() || !form.q_answer.trim()) return ElMessage.warning('请填写题干和答案')
  } else if (!form.content.trim()) {
    return ElMessage.warning('请填写答案/解析内容')
  }
  const payload = { ...form }
  if (bounty.value.bounty_type === 'question' && optionsText.value.trim()) {
    payload.q_options = optionsText.value.split('\n').map(s => s.trim()).filter(Boolean)
  }
  submitting.value = true
  try {
    if (editingSubmission.value) {
      await request.put(`/api/submissions/${mySubmission.value.id}`, payload)
      ElMessage.success('投稿已更新')
      editingSubmission.value = false
    } else {
      const res = await request.post(`/api/bounties/${bounty.value.id}/submissions`, payload)
      const sim = res.data?.similar_questions
      if (sim && sim.length) {
        ElMessage.warning(`检测到题库已有 ${sim.length} 道相似题，可能被判定重复`)
      }
      ElMessage.success('投稿成功，等待审核')
    }
    await load()
  } finally {
    submitting.value = false
  }
}

const startEditSubmission = () => {
  const m = mySubmission.value
  form.q_content = m.q_content || ''
  form.q_answer = m.q_answer || ''
  form.q_analysis = m.q_analysis || ''
  form.q_type = m.q_type || 'single_choice'
  form.q_difficulty = m.q_difficulty || 'medium'
  form.q_knowledge = m.q_knowledge || ''
  form.content = m.content || ''
  form.is_anonymous = !!m.is_anonymous
  optionsText.value = Array.isArray(m.q_options) ? m.q_options.join('\n') : ''
  editingSubmission.value = true
}

const withdraw = async () => {
  try {
    await ElMessageBox.confirm('确认撤回该投稿？', '撤回投稿', { type: 'warning' })
  } catch { return }
  await request.post(`/api/submissions/${mySubmission.value.id}/withdraw`)
  ElMessage.success('已撤回')
  await load()
}

// ── v4.6 投稿附件（统一白名单：文档/表格/压缩包/图片/视频/代码，≤50MB）──
const attachInput = ref(null)
const ATTACH_ACCEPT = '文档/表格/压缩包/图片/视频/代码，单个≤50MB'
const fmtSize = (n) => !n ? '0KB' : (n > 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.max(1, Math.round(n / 1024)) + 'KB')
const pickAttachment = () => attachInput.value?.click()
const onAttachPicked = async (e) => {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file || !mySubmission.value) return
  const fd = new FormData()
  fd.append('file', file)
  try {
    await request.post(`/api/bounties/${route.params.id}/submission/attachment`, fd)
    ElMessage.success(`附件「${file.name}」已上传（${ATTACH_ACCEPT}）`)
    await load()
  } catch (err) {
    ElMessage.error(err?.response?.data?.message || '附件上传失败')
  }
}
const removeAttachment = async (idx) => {
  await request.delete(`/api/bounties/${route.params.id}/submission/attachment/${idx}`)
  ElMessage.success('已删除附件')
  await load()
}
const downloadBlob = async (url, filename) => {
  const res = await request.get(url, { responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(res.data)
  link.download = filename || 'download'
  link.click()
  URL.revokeObjectURL(link.href)
}
const downloadAttachment = (sid, idx, a) => downloadBlob(`/api/submissions/${sid}/attachments/${idx}/download`, a.filename || `附件${idx + 1}${a.ext || ''}`)

const accept = async (s) => {
  const multi = (bounty.value.max_accepts || 1) > 1
  let share = bounty.value.reward_points
  const msg = multi
    ? `采纳 ${s.submitter_name} 的投稿？可调整本次发放积分（剩余名额 ${bounty.value.max_accepts - bounty.value.accept_count}）。`
    : `采纳 ${s.submitter_name} 的投稿？将发放 ${bounty.value.reward_points} 积分，采纳后悬赏关闭。`
  try {
    const r = await ElMessageBox.prompt(msg, '确认采纳', {
      type: 'warning', confirmButtonText: '确认采纳', cancelButtonText: '取消',
      inputPattern: /^\d+$/, inputErrorMessage: '请输入非负整数',
      inputValue: String(bounty.value.reward_points),
      inputPlaceholder: '发放积分数',
    })
    share = parseInt(r.value) || 0
  } catch { return }
  const res = await request.post(`/api/submissions/${s.id}/accept`, { reward_share: share })
  ElMessage.success(res.data.message || '采纳成功')
  await load()
}

const reject = async (s) => {
  let comment = ''
  try {
    const r = await ElMessageBox.prompt('请输入拒绝原因（选填）', '拒绝投稿', {
      confirmButtonText: '确认拒绝', cancelButtonText: '取消', inputType: 'textarea'
    })
    comment = r.value || ''
  } catch { return }
  await request.post(`/api/submissions/${s.id}/reject`, { review_comment: comment })
  ElMessage.success('已拒绝')
  await load()
}

const vote = async (s) => {
  const res = await request.post(`/api/submissions/${s.id}/vote`)
  s.vote_count = res.data.vote_count
  ElMessage.success(res.data.message || '已投票')
}

const addComment = async () => {
  if (!newComment.value.trim()) return ElMessage.warning('请输入内容')
  await request.post(`/api/bounties/${bounty.value.id}/comments`, { content: newComment.value.trim() })
  newComment.value = ''
  await loadComments()
}

const delComment = async (c) => {
  await request.delete(`/api/comments/${c.id}`)
  await loadComments()
}

const report = async () => {
  let reason = ''
  try {
    const r = await ElMessageBox.prompt('请描述举报理由', '举报悬赏', { inputType: 'textarea', confirmButtonText: '提交举报' })
    reason = r.value || ''
  } catch { return }
  if (!reason.trim()) return ElMessage.warning('请填写举报理由')
  await request.post('/api/bounties/report', { bounty_id: bounty.value.id, reason: reason.trim() })
  ElMessage.success('举报已提交')
}

const openEdit = () => {
  editForm.title = bounty.value.title
  editForm.description = bounty.value.description || ''
  editForm.tags = bounty.value.tags || ''
  editForm.max_accepts = bounty.value.max_accepts || 1
  editForm.deadline = bounty.value.deadline || ''
  editVisible.value = true
}

const submitEdit = async () => {
  await request.put(`/api/bounties/${bounty.value.id}`, { ...editForm })
  ElMessage.success('已保存')
  editVisible.value = false
  await load()
}

const closeBounty = async () => {
  try {
    await ElMessageBox.confirm('关闭后悬赏将不可再投稿，未处理的投稿会被退回。确认关闭？', '关闭悬赏', { type: 'warning' })
  } catch { return }
  await request.post(`/api/bounties/${bounty.value.id}/close`)
  ElMessage.success('已关闭')
  await load()
}

const deleteBounty = async () => {
  try {
    await ElMessageBox.confirm('删除后不可恢复，确认删除该悬赏？', '删除悬赏', { type: 'error' })
  } catch { return }
  await request.delete(`/api/bounties/${bounty.value.id}`)
  ElMessage.success('已删除')
  router_back()
}
const router_back = () => window.history.back()

onMounted(load)
</script>

<style scoped>
.back { margin-bottom: 16px; }
.report-btn { margin-left: auto; color: var(--el-text-color-secondary, #909399); }
.section {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px; padding: 20px; margin-bottom: 16px;
}
.section-title { font-size: 16px; font-weight: 600; margin: 0 0 16px; display: flex; align-items: center; gap: 6px; }
.head-row { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }
.bounty-title { margin: 0 0 8px; }
.bounty-desc { color: var(--el-text-color-secondary, #909399); font-size: 14px; }
.bounty-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.head-meta { display: flex; gap: 20px; flex-wrap: wrap; font-size: 13px; color: var(--el-text-color-secondary, #909399); margin-top: 12px; }
.reward { color: var(--el-color-warning, #e6a23c); font-weight: 600; display: flex; align-items: center; gap: 4px; }
.target-question { margin-top: 14px; padding: 12px; border-radius: 8px; background: var(--el-fill-color-light, #f5f7fa); }
.tq-label { font-weight: 600; margin-bottom: 6px; }
.tq-options { margin-top: 6px; font-size: 13px; color: var(--el-text-color-secondary, #909399); }
.sub-card { border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 8px; padding: 14px; margin-bottom: 12px; }
.sub-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.sub-author { font-weight: 600; }
.sub-time { font-size: 12px; color: var(--el-text-color-secondary, #909399); margin-left: auto; }
.q-content { font-size: 14px; line-height: 1.6; }
.q-answer { margin-top: 8px; color: var(--el-color-success, #67c23a); font-size: 14px; }
.q-analysis { margin-top: 6px; color: var(--el-text-color-secondary, #909399); font-size: 13px; }
.sub-actions { margin-top: 12px; display: flex; gap: 8px; }
.sub-attach { margin-top: 8px; font-size: 13px; color: var(--el-text-color-secondary, #909399); display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
.review-comment { margin-top: 8px; font-size: 13px; color: var(--el-color-danger, #f56c6c); }
.accepted-box { border-color: var(--el-color-success-light-5, #67c23a); }
.accepted-meta { font-size: 13px; color: var(--el-text-color-secondary, #909399); margin-bottom: 10px; }
.inq-alert { margin-top: 12px; }
.my-sub-alert { margin-bottom: 16px; }
.q-block { padding: 12px; background: var(--el-fill-color-light, #f5f7fa); border-radius: 8px; }
.hint { margin-left: 12px; font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.comment-item { padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter, #ebeef5); }
.comment-head { display: flex; align-items: center; gap: 10px; }
.comment-body { margin-top: 4px; font-size: 14px; }
.comment-form { margin-top: 16px; }
</style>
