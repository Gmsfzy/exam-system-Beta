<template>
  <div class="node-learn">
    <div class="top-bar">
      <el-button text @click="goBack">
        <el-icon><ArrowLeft /></el-icon> 返回路径
      </el-button>
    </div>

    <div v-if="loading" class="empty-tip">加载中...</div>
    <template v-else-if="node">
      <!-- 节点信息头 -->
      <div class="node-header">
        <div class="header-main">
          <h1 class="node-title">{{ node.title }}</h1>
          <p v-if="node.description" class="node-desc">{{ node.description }}</p>
          <div class="node-meta">
            <el-tag size="small" effect="plain">第 {{ node.order_num }} 步</el-tag>
            <el-tag v-if="node.difficulty" size="small">{{ diffLabel(node.difficulty) }}</el-tag>
            <span>预计 {{ node.estimated_minutes || 30 }} 分钟</span>
            <span v-if="progressStatus" :class="statusClass">{{ statusLabel(progressStatus) }}</span>
          </div>
        </div>

        <div class="learn-actions">
          <template v-if="enrollmentId">
            <el-button
              v-if="progressStatus !== 'mastered' && progressStatus !== 'in_progress'"
              type="primary" plain @click="updateProgress('in_progress')"
            >开始学习</el-button>
            <el-button
              v-if="progressStatus !== 'mastered'"
              type="success" @click="updateProgress('mastered')"
            >标记已掌握</el-button>
            <el-tag v-else type="success" size="large">已掌握 ✓</el-tag>
          </template>
          <el-button v-else type="primary" @click="goPathEnroll">加入路径后可跟踪进度</el-button>
        </div>
      </div>

      <div class="content-grid">
        <!-- 学习资源 -->
        <div class="panel">
          <div class="panel-head">
            <h2>学习资源</h2>
            <el-button size="small" @click="openAddResource">
              <el-icon><Plus /></el-icon> 添加资源
            </el-button>
          </div>
          <el-empty v-if="resources.length === 0" description="暂无学习资源" :image-size="70" />
          <div v-else class="resource-list">
            <div v-for="r in resources" :key="r.id" class="resource-item">
              <div class="resource-icon" :class="r.type">
                <el-icon :size="18">
                  <VideoPlay v-if="r.type === 'video'" />
                  <Link v-else-if="r.type === 'external_link'" />
                  <EditPen v-else-if="r.type === 'exercise'" />
                  <Document v-else />
                </el-icon>
              </div>
              <div class="resource-body">
                <span class="resource-title">{{ r.title }}</span>
                <span class="resource-type">{{ resTypeLabel(r.type) }}</span>
                <p v-if="r.content && r.type === 'text'" class="resource-content">{{ r.content }}</p>
              </div>
              <el-button
                v-if="r.url && r.type === 'video'" size="small" text type="primary"
                @click="openVideo(r)"
              >观看</el-button>
              <el-button
                v-else-if="r.url" size="small" text type="primary"
                @click="openUrl(r.url)"
              >打开</el-button>
              <el-button size="small" text type="danger" @click="deleteResource(r)">删除</el-button>
            </div>
          </div>
        </div>

        <!-- 配套题目 -->
        <div class="panel">
          <div class="panel-head">
            <h2>配套题目</h2>
            <div class="head-btns">
              <el-button
                size="small" type="warning" plain
                v-if="node.knowledge_point_id"
                :loading="quiz.starting" @click="startQuiz"
              >
                <el-icon><AlarmClock /></el-icon> 节点小测
              </el-button>
              <el-button
                size="small" type="primary" plain
                :loading="startingPractice" @click="startNodePractice"
              >
                <el-icon><VideoPlay /></el-icon> 开始本节点练习
              </el-button>
            </div>
          </div>
          <el-empty v-if="questions.length === 0" description="该知识点暂无关联题目" :image-size="70" />
          <div v-else class="question-list">
            <div v-for="(q, i) in questions" :key="q.id" class="question-item">
              <span class="q-index">{{ i + 1 }}</span>
              <div class="q-body">
                <span class="q-type">{{ typeLabel(q.type) }}</span>
                <span class="q-content">{{ q.content }}</span>
              </div>
            </div>
          </div>
          <div class="panel-hint">「节点小测」限时自测：达到 80% 自动标记本节点已掌握；「练习」可边看答案边做</div>
        </div>
      </div>

      <!-- 我的笔记（按知识点一篇总结） -->
      <div v-if="node.knowledge_point_id" class="panel note-panel">
        <div class="panel-head">
          <h2>我的笔记</h2>
          <div class="head-btns">
            <el-button size="small" type="primary" plain :loading="polishing" @click="polishNote">
              <el-icon><MagicStick /></el-icon> AI 润色提炼
            </el-button>
            <el-button size="small" type="primary" :loading="savingNote" @click="saveNote">保存笔记</el-button>
          </div>
        </div>
        <el-input v-model="noteText" type="textarea" :rows="5" maxlength="5000" show-word-limit
                  placeholder="用自己的话总结这个知识点：核心概念、易错点、记忆方法…（保存后可在「我的知识库」查看）" />
        <div v-if="noteUpdatedAt" class="note-updated">上次保存：{{ noteUpdatedAt }}</div>
      </div>

      <!-- 视频播放对话框 -->
      <el-dialog v-model="videoDlg" :title="currentVideo?.title || '视频资源'" width="760px" destroy-on-close>
        <video
          v-if="currentVideo?.url" :src="currentVideo.url" controls autoplay
          class="video-player"
        ></video>
        <div v-if="currentVideo?.url" class="video-fallback">
          无法播放？<a :href="currentVideo.url" target="_blank" rel="noopener">在新窗口打开</a>
        </div>
      </el-dialog>

      <!-- 节点小测弹窗 -->
      <el-dialog v-model="quiz.visible" title="节点小测" width="640px" :close-on-click-modal="false" destroy-on-close>
        <template v-if="quiz.step === 'quiz' && quiz.questions.length">
          <div class="qz-head">
            <span>第 {{ quiz.idx + 1 }} / {{ quiz.questions.length }} 题</span>
            <el-tag size="small">{{ typeLabel(quizCurrent.type) }}</el-tag>
          </div>
          <div class="qz-content">{{ quizCurrent.content }}</div>
          <div v-if="isChoice(quizCurrent.type)" class="qz-options">
            <div v-for="(opt, i) in (quizCurrent.options || [])" :key="i"
                 :class="['qz-option', { selected: isPicked(i) }]" @click="pick(i)">
              <span class="opt-label">{{ String.fromCharCode(65 + i) }}</span>
              <span>{{ opt }}</span>
            </div>
          </div>
          <div v-else-if="quizCurrent.type === 'true_false'" class="qz-options">
            <div v-for="lab in ['A', 'B']" :key="lab" :class="['qz-option', { selected: quiz.draft === lab }]" @click="quiz.draft = lab">
              <span class="opt-label">{{ lab }}</span><span>{{ lab === 'A' ? '正确' : '错误' }}</span>
            </div>
          </div>
          <el-input v-else v-model="quiz.draft" type="textarea" :rows="3" placeholder="请输入答案" />
          <div class="qz-foot">
            <el-button :disabled="quiz.idx === 0" @click="prevQuestion">上一题</el-button>
            <el-button v-if="quiz.idx < quiz.questions.length - 1" type="primary"
                       :disabled="!quiz.draft.trim()" :loading="quiz.saving" @click="nextQuestion">下一题</el-button>
            <el-button v-else type="success" :disabled="!quiz.draft.trim()" :loading="quiz.saving" @click="finishQuiz">交卷</el-button>
          </div>
        </template>

        <template v-else-if="quiz.step === 'result'">
          <div class="qz-result" :class="quiz.result.passed ? 'pass' : 'fail'">
            <div class="qz-score">{{ Math.round((quiz.result.score_ratio || 0) * 100) }} 分</div>
            <div class="qz-stat">答对 {{ quiz.result.correct_count }} / {{ quiz.result.total }} 题</div>
            <div class="qz-verdict">
              {{ quiz.result.passed
                 ? '🎉 通过！本节点已自动标记为已掌握'
                 : '未达 80% 通过线，可复习后再考一次' }}
            </div>
          </div>
          <div class="qz-foot">
            <el-button @click="quiz.visible = false">关闭</el-button>
            <el-button type="primary" @click="retakeQuiz">再考一次</el-button>
          </div>
        </template>
      </el-dialog>
      <el-dialog v-model="resDlg" title="添加学习资源" width="520px">
        <el-form :model="resForm" label-width="80px">
          <el-form-item label="标题" required>
            <el-input v-model="resForm.title" maxlength="120" placeholder="资源标题" />
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="resForm.type" style="width: 100%">
              <el-option label="文本讲解" value="text" />
              <el-option label="视频" value="video" />
              <el-option label="练习" value="exercise" />
              <el-option label="外部链接" value="external_link" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="resForm.type === 'text'" label="内容">
            <el-input v-model="resForm.content" type="textarea" :rows="5" placeholder="文本讲解内容" />
          </el-form-item>
          <el-form-item v-if="resForm.type !== 'text'" label="链接">
            <el-input v-model="resForm.url" placeholder="https://..." />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="resDlg = false">取消</el-button>
          <el-button type="primary" :loading="savingRes" @click="addResource">添加</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Plus, VideoPlay, Link, EditPen, Document, AlarmClock, MagicStick } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const router = useRouter()

const nodeId = Number(route.params.nodeId)
const pathId = Number(route.query.path || 0)

const path = ref(null)
const node = ref(null)
const loading = ref(true)
const resources = ref([])
const questions = ref([])
const resDlg = ref(false)
const savingRes = ref(false)
const resForm = ref({ title: '', type: 'text', content: '', url: '' })
const videoDlg = ref(false)
const currentVideo = ref(null)
const startingPractice = ref(false)

const enrollmentId = computed(() => path.value?.my_enrollment?.id ?? null)

// ── 我的笔记 ───────────────────────────────────────────────
const noteText = ref('')
const noteUpdatedAt = ref('')
const savingNote = ref(false)
const polishing = ref(false)

const loadNote = async () => {
  const kpId = node.value?.knowledge_point_id
  if (!kpId) return
  try {
    const res = await request.get('/api/learning/kp-notes', { params: { knowledge_point_id: kpId } })
    noteText.value = res.data.content || ''
    noteUpdatedAt.value = res.data.updated_at || ''
  } catch (e) { /* ignore */ }
}
watch(node, loadNote)

const saveNote = async () => {
  if (!node.value?.knowledge_point_id) return
  savingNote.value = true
  try {
    const res = await request.put(`/api/learning/kp-notes/${node.value.knowledge_point_id}`, { content: noteText.value })
    noteUpdatedAt.value = res.data.updated_at || ''
    ElMessage.success('笔记已保存')
  } catch (e) { /* 拦截器已提示 */ }
  savingNote.value = false
}

const polishNote = async () => {
  if (!noteText.value.trim()) { ElMessage.warning('请先输入笔记内容'); return }
  polishing.value = true
  try {
    const res = await request.post(`/api/learning/kp-notes/${node.value.knowledge_point_id}/ai-polish`, { content: noteText.value })
    noteText.value = res.data.polished
    ElMessage.success('已用 AI 润色结果替换草稿，确认后请保存')
  } catch (e) { /* 拦截器已提示 */ }
  polishing.value = false
}

// ── 节点小测 ───────────────────────────────────────────────
const quiz = reactive({
  visible: false, starting: false, saving: false,
  step: 'quiz', attemptId: null, questions: [], idx: 0, draft: '',
  picked: {}, result: {},
})

const currentQuizQ = computed(() => quiz.questions[quiz.idx])
const quizCurrent = computed(() => quiz.questions[quiz.idx] || {})

const isChoice = hasOptions
const isPicked = (i) => (quiz.draft || '').includes(String.fromCharCode(65 + i))
const pick = (i) => {
  const label = String.fromCharCode(65 + i)
  if (currentQuizQ.value?.type === 'single_choice') {
    quiz.draft = label
  } else {
    const set = new Set((quiz.draft || '').split('').filter(Boolean))
    set.has(label) ? set.delete(label) : set.add(label)
    quiz.draft = Array.from(set).sort().join('')
  }
}

const startQuiz = async () => {
  quiz.starting = true
  try {
    const res = await request.post('/api/learning/quizzes/start', { node_id: nodeId })
    quiz.attemptId = res.data.attempt_id
    quiz.questions = res.data.questions || []
    quiz.idx = 0
    quiz.draft = ''
    quiz.picked = {}
    quiz.step = 'quiz'
    quiz.visible = true
  } catch (e) { /* 题量不足等 409 提示由拦截器弹出 */ }
  quiz.starting = false
}

const saveCurrentAnswer = async () => {
  const q = currentQuizQ.value
  if (!q?.id) return false
  try {
    await request.post(`/api/learning/quizzes/${quiz.attemptId}/answer`, {
      question_id: q.id, student_answer: quiz.draft.trim(),
    })
    quiz.picked[q.id] = quiz.draft.trim()
    return true
  } catch (e) { return false }
}

const prevQuestion = async () => {
  await saveCurrentAnswer()
  if (quiz.idx > 0) {
    quiz.idx -= 1
    quiz.draft = quiz.picked[quizCurrent.value.id] || ''
  }
}

const nextQuestion = async () => {
  quiz.saving = true
  const ok = await saveCurrentAnswer()
  quiz.saving = false
  if (!ok) return
  quiz.idx += 1
  quiz.draft = quiz.picked[quizCurrent.value.id] || ''
}

const finishQuiz = async () => {
  quiz.saving = true
  const ok = await saveCurrentAnswer()
  if (ok) {
    try {
      const res = await request.post(`/api/learning/quizzes/${quiz.attemptId}/submit`)
      quiz.result = res.data
      quiz.step = 'result'
      if (res.data.passed) loadPath()  // 通过后节点状态已自动置掌握，刷新页面
    } catch (e) { /* 拦截器已提示 */ }
  }
  quiz.saving = false
}

const retakeQuiz = () => { startQuiz() }
const progressStatus = computed(() => {
  const found = path.value?.nodes?.find(n => n.id === nodeId)
  return found?.progress_status || null
})
const statusClass = computed(() => ({
  mastered: 'status-mastered', in_progress: 'status-doing', skipped: 'status-skip',
}[progressStatus.value] || ''))

const loadPath = async () => {
  try {
    const res = await request.get(`/api/learning/paths/${pathId}`)
    path.value = res.data
    node.value = (res.data.nodes || []).find(n => n.id === nodeId)
    if (!node.value) {
      ElMessage.error('节点不存在或不属于该路径')
      return
    }
    await Promise.all([loadResources(), loadQuestions()])
  } catch (e) { /* 拦截器已提示 */ }
  loading.value = false
}

const loadResources = async () => {
  if (!node.value) return
  try {
    const params = node.value.knowledge_point_id
      ? { knowledge_point_id: node.value.knowledge_point_id }
      : { chapter_id: node.value.chapter_id }
    const res = await request.get('/api/learning/resources', { params })
    resources.value = res.data || []
  } catch (e) { resources.value = [] }
}

const loadQuestions = async () => {
  if (!node.value?.knowledge_point_id) {
    questions.value = []
    return
  }
  try {
    const res = await request.get(`/api/learning/knowledge-points/${node.value.knowledge_point_id}/questions`)
    questions.value = res.data || []
  } catch (e) { questions.value = [] }
}

const updateProgress = async (status) => {
  if (!enrollmentId.value) return
  try {
    await request.post(`/api/learning/enrollments/${enrollmentId.value}/nodes/${nodeId}/progress`, { status })
    ElMessage.success(status === 'mastered' ? '太棒了，已标记掌握！' : '已开始学习')
    loadPath()
  } catch (e) { /* 拦截器已提示 */ }
}

const goPathEnroll = () => router.push(`/learning/paths/${pathId}`)

const openVideo = (r) => {
  currentVideo.value = r
  videoDlg.value = true
}

const startNodePractice = async () => {
  if (!node.value) return
  const payload = { count: 10, title: `节点练习 · ${node.value.title}` }
  if (node.value.knowledge_point_id) {
    payload.knowledge_point_id = node.value.knowledge_point_id
  } else if (node.value.chapter_id) {
    payload.chapter_id = node.value.chapter_id
  } else {
    ElMessage.warning('该节点未关联知识点或章节，无法出题')
    return
  }
  startingPractice.value = true
  try {
    const res = await request.post('/api/learning/practice/start', payload)
    router.push(`/learning/practice/${res.data.session_id}`)
  } catch (e) { /* 拦截器已提示 */ }
  startingPractice.value = false
}

const openAddResource = () => {
  resForm.value = { title: '', type: 'text', content: '', url: '' }
  resDlg.value = true
}

const addResource = async () => {
  if (!resForm.value.title.trim()) {
    ElMessage.warning('请填写资源标题')
    return
  }
  savingRes.value = true
  try {
    await request.post('/api/learning/resources', {
      ...resForm.value,
      knowledge_point_id: node.value.knowledge_point_id,
      chapter_id: node.value.knowledge_point_id ? null : node.value.chapter_id,
    })
    ElMessage.success('资源已添加')
    resDlg.value = false
    loadResources()
  } catch (e) { /* 拦截器已提示 */ }
  savingRes.value = false
}

const deleteResource = async (r) => {
  try {
    await ElMessageBox.confirm(`确定删除资源「${r.title}」？`, '删除资源', { type: 'warning' })
  } catch { return }
  try {
    await request.delete(`/api/learning/resources/${r.id}`)
    ElMessage.success('已删除')
    loadResources()
  } catch (e) { /* 拦截器已提示 */ }
}

const openUrl = (url) => window.open(url, '_blank')

const goBack = () => {
  if (pathId) router.push(`/learning/paths/${pathId}`)
  else router.push('/learning/paths')
}

// v4.6.1 枚举收敛：题型/难度单一来源 frontend/src/utils/enums.js（简称统一为全称）
import { difficultyLabel, typeLabel, hasOptions } from '../utils/enums'
const diffLabel = difficultyLabel
const statusLabel = (s) => ({
  not_started: '未开始', in_progress: '学习中', mastered: '已掌握', skipped: '已跳过',
}[s] || s)
const resTypeLabel = (t) => ({
  text: '文本讲解', video: '视频', exercise: '练习', external_link: '外部链接',
}[t] || t)

onMounted(() => {
  if (!pathId) {
    ElMessage.error('缺少路径参数')
    loading.value = false
    return
  }
  loadPath()
})
</script>

<style scoped>
.node-learn {
  padding: 20px;
  max-width: 1100px;
}

.top-bar {
  margin-bottom: 12px;
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 22px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.node-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 8px;
  color: var(--text-primary);
}

.node-desc {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0 0 10px;
  line-height: 1.6;
}

.node-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 12px;
  color: var(--text-muted);
  flex-wrap: wrap;
}

.status-mastered { color: #10b981; font-weight: 600; }
.status-doing { color: #06b6d4; font-weight: 600; }
.status-skip { color: #f59e0b; }

.learn-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

.panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 18px 20px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.panel-head h2 {
  font-size: 16px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
}

.panel-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-color);
}

.resource-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.resource-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.resource-icon {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
  background: linear-gradient(135deg, #06b6d4 0%, #0891b2 100%);
}

.resource-icon.video { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); }
.resource-icon.external_link { background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); }
.resource-icon.exercise { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }

.resource-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.resource-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.resource-type {
  font-size: 12px;
  color: var(--text-muted);
}

.resource-content {
  font-size: 13px;
  color: var(--text-muted);
  margin: 4px 0 0;
  line-height: 1.6;
  white-space: pre-wrap;
}

.question-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.question-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.q-index {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: rgba(6, 182, 212, 0.12);
  color: #06b6d4;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.q-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.q-type {
  font-size: 11px;
  color: var(--text-muted);
}

.q-content {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.empty-tip {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 0;
}

.head-btns {
  display: flex;
  gap: 8px;
  align-items: center;
}

.note-panel {
  margin-top: 18px;
}

.note-updated {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 8px;
}

.qz-head {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 10px;
}

.qz-content {
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-primary);
  margin-bottom: 16px;
  white-space: pre-wrap;
}

.qz-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.qz-option {
  display: flex;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 14px;
  color: var(--text-primary);
}

.qz-option:hover { border-color: #f59e0b; }
.qz-option.selected { background: rgba(245, 158, 11, 0.1); border-color: #f59e0b; }
.qz-option .opt-label { font-weight: 600; color: var(--text-muted); }

.qz-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 18px;
}

.qz-foot > :first-child { margin-right: auto; }
.qz-foot .el-button + .el-button { margin-left: 8px; }

.qz-result {
  text-align: center;
  padding: 26px 0 10px;
}

.qz-result .qz-score { font-size: 44px; font-weight: 800; }
.qz-result.pass .qz-score { color: #10b981; }
.qz-result.fail .qz-score { color: #ef4444; }
.qz-result .qz-stat { font-size: 14px; color: var(--text-muted); margin-top: 6px; }
.qz-result .qz-verdict { font-size: 15px; color: var(--text-primary); margin-top: 12px; }

.video-player {
  width: 100%;
  max-height: 480px;
  border-radius: 10px;
  background: #000;
  outline: none;
}

.video-fallback {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 10px;
  text-align: center;
}

.video-fallback a {
  color: #06b6d4;
  text-decoration: none;
}

@media (max-width: 900px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>
