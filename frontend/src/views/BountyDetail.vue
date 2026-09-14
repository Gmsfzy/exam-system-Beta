<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="$router.push('/bounties')" content="悬赏详情" class="back" />

    <template v-if="bounty">
      <!-- 悬赏信息 -->
      <div class="bounty-head section">
        <div class="head-row">
          <el-tag :type="bounty.bounty_type === 'question' ? 'primary' : 'success'" effect="light">
            {{ bounty.bounty_type === 'question' ? '题目征集' : '答案征集' }}
          </el-tag>
          <el-tag :type="statusTag(bounty.status)" effect="plain">{{ statusText(bounty.status) }}</el-tag>
          <el-tag v-if="bounty.is_publisher" type="warning" effect="plain">我发布的</el-tag>
        </div>
        <h2 class="bounty-title">{{ bounty.title }}</h2>
        <p class="bounty-desc">{{ bounty.description || '暂无详细描述' }}</p>
        <div class="head-meta">
          <span class="reward"><el-icon><GoldMedal /></el-icon> 赏金 {{ bounty.reward_points }} 积分</span>
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

      <!-- 已采纳结果 -->
      <div v-if="bounty.accepted_submission" class="section accepted-box">
        <h3 class="section-title"><el-icon><CircleCheck /></el-icon> 已采纳投稿</h3>
        <div class="accepted-meta">投稿人：{{ bounty.accepted_submission.submitter_name }}</div>
        <template v-if="bounty.bounty_type === 'question'">
          <div class="q-block">
            <div class="q-content">{{ bounty.accepted_submission.q_content }}</div>
            <div class="q-answer">答案：{{ bounty.accepted_submission.q_answer }}</div>
            <div v-if="bounty.accepted_submission.q_analysis" class="q-analysis">解析：{{ bounty.accepted_submission.q_analysis }}</div>
          </div>
          <el-alert v-if="bounty.accepted_submission.accepted_question_id" type="success" :closable="false"
                    :title="`题目已收录进题库（#${bounty.accepted_submission.accepted_question_id}）`" class="inq-alert" />
        </template>
        <template v-else>
          <div class="q-content">{{ bounty.accepted_submission.content }}</div>
        </template>
      </div>

      <!-- 发布者：投稿审核列表 -->
      <div v-if="bounty.is_publisher && bounty.status === 'open'" class="section">
        <h3 class="section-title">投稿审核（{{ submissions.length }}）</h3>
        <el-empty v-if="!submissions.length" description="暂无投稿" />
        <div v-for="s in submissions" :key="s.id" class="sub-card">
          <div class="sub-head">
            <span class="sub-author">{{ s.submitter_name }}</span>
            <el-tag size="small" :type="subStatusTag(s.status)">{{ subStatusText(s.status) }}</el-tag>
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
          <div v-if="s.review_comment" class="review-comment">审核备注：{{ s.review_comment }}</div>
        </div>
      </div>

      <!-- 投稿人：投稿表单 -->
      <div v-if="!bounty.is_publisher && bounty.status === 'open'" class="section">
        <h3 class="section-title">
          {{ mySubmission ? '我的投稿' : '我要投稿' }}
        </h3>

        <el-alert v-if="mySubmission" :type="mySubmission.status === 'accepted' ? 'success' : 'info'"
                  :closable="false" class="my-sub-alert"
                  :title="`你已投稿，状态：${subStatusText(mySubmission.status)}`" />

        <el-form v-else :model="form" label-width="90px" v-loading="submitting">
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
              <el-input v-model="form.content" type="textarea" :rows="6"
                        placeholder="请给出完整答案与解析过程" />
            </el-form-item>
          </template>
          <el-form-item>
            <el-button type="primary" :icon="Promotion" @click="submit">提交投稿</el-button>
          </el-form-item>
        </el-form>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { GoldMedal, CircleCheck, Promotion } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const loading = ref(false)
const submitting = ref(false)
const bounty = ref(null)
const submissions = ref([])
const optionsText = ref('')

const qTypes = {
  single_choice: '单选题', multiple_choice: '多选题', fill_blank: '填空题',
  true_false: '判断题', short_answer: '简答题', essay: '问答题'
}
const qDiffs = { easy: '简单', medium: '中等', hard: '困难' }

const form = reactive({
  q_content: '', q_answer: '', q_analysis: '',
  q_type: 'single_choice', q_difficulty: 'medium', q_knowledge: '',
  content: '',
})

const statusText = (s) => ({ open: '征集中', closed: '已采纳', expired: '已过期' }[s] || s)
const statusTag = (s) => ({ open: 'warning', closed: 'success', expired: 'info' }[s] || 'info')
const subStatusText = (s) => ({ pending: '待审核', accepted: '已采纳', rejected: '已拒绝' }[s] || s)
const subStatusTag = (s) => ({ pending: 'warning', accepted: 'success', rejected: 'danger' }[s] || 'info')

const mySubmission = computed(() => bounty.value?.my_submission || null)
const targetQ = computed(() => bounty.value?.target_question || null)

const normalizeOptions = (opts) => {
  if (Array.isArray(opts)) return opts
  if (typeof opts === 'string') {
    try { return JSON.parse(opts) } catch { return [opts] }
  }
  return []
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
  } finally {
    loading.value = false
  }
}

const submit = async () => {
  if (bounty.value.bounty_type === 'question') {
    if (!form.q_content.trim() || !form.q_answer.trim())
      return ElMessage.warning('请填写题干和答案')
  } else if (!form.content.trim()) {
    return ElMessage.warning('请填写答案/解析内容')
  }
  const payload = { ...form }
  if (bounty.value.bounty_type === 'question' && optionsText.value.trim()) {
    payload.q_options = optionsText.value.split('\n').map(s => s.trim()).filter(Boolean)
  }
  submitting.value = true
  try {
    await request.post(`/api/bounties/${bounty.value.id}/submissions`, payload)
    ElMessage.success('投稿成功，等待审核')
    await load()
  } finally {
    submitting.value = false
  }
}

const accept = async (s) => {
  try {
    await ElMessageBox.confirm(
      `采纳 ${s.submitter_name} 的投稿？将发放 ${bounty.value.reward_points} 积分，采纳后悬赏关闭。`,
      '确认采纳', { type: 'warning', confirmButtonText: '确认采纳', cancelButtonText: '取消' })
  } catch { return }
  const res = await request.post(`/api/submissions/${s.id}/accept`)
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

onMounted(load)
</script>

<style scoped>
.back { margin-bottom: 16px; }
.section {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
}
.section-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 16px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.head-row { display: flex; gap: 8px; margin-bottom: 12px; }
.bounty-title { margin: 0 0 8px; }
.bounty-desc { color: var(--el-text-color-secondary, #909399); font-size: 14px; }
.head-meta {
  display: flex; gap: 20px; flex-wrap: wrap;
  font-size: 13px; color: var(--el-text-color-secondary, #909399);
  margin-top: 12px;
}
.reward { color: var(--el-color-warning, #e6a23c); font-weight: 600; display: flex; align-items: center; gap: 4px; }
.target-question {
  margin-top: 14px; padding: 12px; border-radius: 8px;
  background: var(--el-fill-color-light, #f5f7fa);
}
.tq-label { font-weight: 600; margin-bottom: 6px; }
.tq-options { margin-top: 6px; font-size: 13px; color: var(--el-text-color-secondary, #909399); }
.sub-card {
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 8px; padding: 14px; margin-bottom: 12px;
}
.sub-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.sub-author { font-weight: 600; }
.sub-time { font-size: 12px; color: var(--el-text-color-secondary, #909399); margin-left: auto; }
.q-content { font-size: 14px; line-height: 1.6; }
.q-answer { margin-top: 8px; color: var(--el-color-success, #67c23a); font-size: 14px; }
.q-analysis { margin-top: 6px; color: var(--el-text-color-secondary, #909399); font-size: 13px; }
.sub-actions { margin-top: 12px; }
.review-comment { margin-top: 8px; font-size: 13px; color: var(--el-color-danger, #f56c6c); }
.accepted-box { border-color: var(--el-color-success-light-5, #67c23a); }
.accepted-meta { font-size: 13px; color: var(--el-text-color-secondary, #909399); margin-bottom: 10px; }
.inq-alert { margin-top: 12px; }
.my-sub-alert { margin-bottom: 16px; }
.q-block { padding: 12px; background: var(--el-fill-color-light, #f5f7fa); border-radius: 8px; }
</style>
