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
                <span class="resource-type">{{ typeLabel(r.type) }}</span>
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
            <el-button
              size="small" type="primary" plain
              :loading="startingPractice" @click="startNodePractice"
            >
              <el-icon><VideoPlay /></el-icon> 开始本节点练习
            </el-button>
          </div>
          <el-empty v-if="questions.length === 0" description="该知识点暂无关联题目" :image-size="70" />
          <div v-else class="question-list">
            <div v-for="(q, i) in questions" :key="q.id" class="question-item">
              <span class="q-index">{{ i + 1 }}</span>
              <div class="q-body">
                <span class="q-type">{{ qTypeLabel(q.type) }}</span>
                <span class="q-content">{{ q.content }}</span>
              </div>
            </div>
          </div>
          <div class="panel-hint">点击「开始本节点练习」按本节点知识点出题，答题正确率计入练习记录，完成后可在此标记掌握</div>
        </div>
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

      <!-- 添加资源对话框（全民共建） -->
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
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Plus, VideoPlay, Link, EditPen, Document } from '@element-plus/icons-vue'
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

const diffLabel = (d) => ({ easy: '简单', medium: '中等', hard: '困难' }[d] || d)
const statusLabel = (s) => ({
  not_started: '未开始', in_progress: '学习中', mastered: '已掌握', skipped: '已跳过',
}[s] || s)
const typeLabel = (t) => ({
  text: '文本讲解', video: '视频', exercise: '练习', external_link: '外部链接',
}[t] || t)
const qTypeLabel = (t) => ({
  single_choice: '单选', multiple_choice: '多选', fill_blank: '填空',
  true_false: '判断', short_answer: '问答', programming: '编程',
  application: '应用', calculation: '计算',
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
