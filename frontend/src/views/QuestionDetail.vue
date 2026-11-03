<template>
  <div class="page-wrapper" v-loading="loading">
    <div class="page-header">
      <div class="header-title">
        <h2>
          <el-icon :size="22" class="title-icon"><Document /></el-icon> 题目详情
          <span v-if="q" class="q-id">#{{ q.id }}</span>
        </h2>
        <p class="sub-info">题库单题详情 · 供社区「题目关联」一步直达</p>
      </div>
      <div class="header-actions" v-if="q">
        <el-button :icon="ChatDotRound" @click="goDiscuss">讨论区</el-button>
        <el-button text :icon="Back" @click="goBack">返回</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" class="err-alert" />

    <el-empty v-else-if="!loading && !q" description="题目不存在或已删除" />

    <div v-if="q" class="detail-card">
      <div class="detail-badges">
        <span class="badge badge-type">{{ typeLabels[q.type] || q.type }}</span>
        <span class="badge badge-diff">{{ diffLabels[q.difficulty] || q.difficulty }}</span>
        <span class="badge badge-source">{{ sourceLabels[q.source] || '手动输入' }}</span>
        <span v-if="q.is_public" class="badge badge-public">公共题库</span>
        <span v-if="q.major_name" class="badge badge-plain">{{ q.major_name }}</span>
        <span v-if="q.course_name" class="badge badge-plain">{{ q.course_name }}</span>
      </div>

      <div v-if="q.material" class="section">
        <h4 class="sec-title">材料</h4>
        <div class="rich"><RichContent :content="String(q.material)" /></div>
      </div>

      <div class="section">
        <h4 class="sec-title">题目内容</h4>
        <div class="rich"><RichContent :content="String(q.content || '')" /></div>
      </div>

      <div v-if="opts.length" class="section">
        <h4 class="sec-title">选项</h4>
        <div v-for="(opt, idx) in opts" :key="idx" class="opt-row">
          <span class="opt-label">{{ ['A', 'B', 'C', 'D', 'E', 'F'][idx] }}</span>
          <span class="opt-body"><RichContent :content="String(opt ?? '')" /></span>
        </div>
      </div>

      <div class="section">
        <h4 class="sec-title">答案</h4>
        <div v-if="isTeacher" class="rich answer"><RichContent :content="String(q.answer || '')" /></div>
        <div v-else class="masked">答案仅教师可见</div>
      </div>

      <div v-if="isTeacher && q.analysis" class="section">
        <h4 class="sec-title">解析</h4>
        <div class="rich"><RichContent :content="String(q.analysis)" /></div>
      </div>

      <div v-if="knowledgeList.length" class="section">
        <h4 class="sec-title">知识点</h4>
        <div class="tag-wrap">
          <el-tag v-for="(k, i) in knowledgeList" :key="'k' + i" size="small" effect="plain">{{ k }}</el-tag>
        </div>
      </div>

      <div v-if="q.tags && q.tags.length" class="section">
        <h4 class="sec-title">标签</h4>
        <div class="tag-wrap">
          <el-tag v-for="(t, i) in q.tags" :key="'t' + i" size="small" type="success" effect="plain">{{ t }}</el-tag>
        </div>
      </div>

      <div class="meta-foot">
        <span v-if="q.creator_name">出题人：{{ q.creator_name }}</span>
        <span v-if="q.created_at">创建时间：{{ q.created_at }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Document, ChatDotRound, Back } from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import { QUESTION_TYPE_LABELS as typeLabels, DIFFICULTY_LABELS as diffLabels } from '../utils/enums'
import RichContent from '../components/RichContent.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const sourceLabels = { manual: '手动输入', ai: 'AI生成', past_exam: '历年真题' }

const loading = ref(false)
const error = ref('')
const q = ref(null)

const isTeacher = computed(() => auth.user?.role === 'teacher')

const opts = computed(() => {
  const o = q.value && q.value.options
  if (Array.isArray(o)) return o
  if (typeof o === 'string' && o.trim()) {
    try { const r = JSON.parse(o); return Array.isArray(r) ? r : [] } catch { return [] }
  }
  return []
})

const knowledgeList = computed(() =>
  (q.value?.knowledge || '').split(',').map((t) => t.trim()).filter(Boolean))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request.get(`/api/questions/${route.params.id}`)
    q.value = res.data
  } catch (e) {
    const status = e?.response?.status
    if (status === 404) error.value = '题目不存在或已删除'
    else if (status === 401) error.value = '请先登录后查看题目'
    else if (status === 403) error.value = '无权查看该题目'
    else error.value = '加载题目失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const goDiscuss = () =>
  router.push({ path: '/community', query: { linked_type: 'question', linked_id: route.params.id } })

const goBack = () => {
  if (window.history.length > 1) router.back()
  else router.push(isTeacher.value ? '/questions' : '/portal')
}

onMounted(load)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.header-title h2 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 20px; }
.title-icon { color: #409eff; }
.q-id { color: #909399; font-weight: 400; font-size: 15px; }
.sub-info { color: #909399; font-size: 13px; margin: 6px 0 0; }
.err-alert { margin-bottom: 12px; }
.detail-card { background: #fff; border-radius: 10px; padding: 20px 22px; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05); }
.detail-badges { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.badge { font-size: 12px; padding: 2px 10px; border-radius: 12px; color: #fff; }
.badge-type { background: #11998e; }
.badge-diff { background: #f093fb; }
.badge-source { background: #60a5fa; }
.badge-public { background: #e6a23c; }
.badge-plain { background: #f4f4f5; color: #606266; border: 1px solid #e9e9eb; }
.section { margin-bottom: 18px; }
.sec-title { margin: 0 0 8px; font-size: 14px; color: #303133; border-left: 3px solid #409eff; padding-left: 8px; }
.rich { line-height: 1.7; color: #303133; word-break: break-word; }
.answer { color: #67c23a; font-weight: 500; }
.masked { color: #a8abb2; font-style: italic; }
.opt-row { display: flex; gap: 10px; align-items: baseline; padding: 4px 0; }
.opt-label { flex: none; width: 22px; height: 22px; line-height: 22px; text-align: center; border-radius: 50%; background: #ecf5ff; color: #409eff; font-size: 12px; }
.opt-body { flex: 1; }
.tag-wrap { display: flex; flex-wrap: wrap; gap: 6px; }
.meta-foot { display: flex; gap: 20px; flex-wrap: wrap; padding-top: 12px; border-top: 1px dashed #ebeef5; color: #909399; font-size: 13px; }
</style>
