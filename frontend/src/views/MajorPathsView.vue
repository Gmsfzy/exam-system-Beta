<template>
  <div class="paths-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">专业学习路径</h1>
        <p class="page-subtitle">为自己规划一条学习路径：定目标、排周期，按节点一步步学完</p>
      </div>
      <div class="header-actions">
        <el-select v-model="filterMajorId" placeholder="全部专业" clearable style="width: 200px" @change="loadPaths">
          <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="全部状态" clearable style="width: 130px" @change="loadPaths">
          <el-option label="草稿" value="draft" />
          <el-option label="已发布" value="published" />
          <el-option label="已归档" value="archived" />
        </el-select>
        <el-button type="primary" plain @click="openAiDlg">
          <el-icon style="margin-right: 4px"><MagicStick /></el-icon>AI 生成路径
        </el-button>
        <el-button type="primary" @click="openCreateDlg">
          <el-icon style="margin-right: 4px"><Plus /></el-icon>新建路径
        </el-button>
      </div>
    </div>

    <div v-if="loading" class="empty-tip">加载中...</div>
    <el-empty v-else-if="paths.length === 0" description="暂无学习路径" />

    <div v-else class="path-grid">
      <div v-for="p in paths" :key="p.id" class="path-card" @click="goDetail(p)">
        <div class="card-top">
          <span class="path-title">{{ p.title }}</span>
          <el-tag :type="statusTagType(p.status)" size="small">{{ statusLabel(p.status) }}</el-tag>
        </div>
        <p class="path-desc">{{ p.description || '暂无简介' }}</p>
        <div v-if="p.learning_goal" class="path-goal">
          <el-icon color="#06b6d4"><Aim /></el-icon>
          <span>{{ p.learning_goal }}</span>
        </div>
        <div class="path-meta">
          <el-tag size="small" effect="plain">{{ p.major_name || '未关联专业' }}</el-tag>
          <el-tag v-if="p.is_creator" size="small" type="success">我的路径</el-tag>
          <span>{{ p.nodes_count }} 个节点</span>
          <span>约 {{ formatMinutes(p.total_minutes) }}</span>
          <span v-if="p.target_hours">目标 {{ p.target_hours }} 学时</span>
        </div>
        <div v-if="p.start_date || p.target_end_date" class="path-meta">
          <el-icon color="#f59e0b"><Calendar /></el-icon>
          <span>{{ p.start_date || '未设定' }} ~ {{ p.target_end_date || '长期' }}</span>
          <span v-if="daysLeft(p) !== null" :class="daysLeft(p) < 0 ? 'days-over' : 'days-left'">
            {{ daysLeft(p) < 0 ? `已超期 ${-daysLeft(p)} 天` : `剩余 ${daysLeft(p)} 天` }}
          </span>
        </div>

        <div v-if="p.my_enrollment && p.my_enrollment.total_count" class="progress-row">
          <el-progress
            :percentage="p.my_enrollment.progress"
            :stroke-width="8"
            :color="progressColor"
          />
          <span class="progress-text">{{ p.my_enrollment.completed_count }}/{{ p.my_enrollment.total_count }} 已掌握</span>
        </div>

        <div class="card-footer">
          <span class="creator">创建者：{{ p.creator_name || '-' }}</span>
          <el-button
            v-if="!p.is_creator && (!p.my_enrollment || p.my_enrollment.status === 'abandoned')"
            type="primary" size="small" @click.stop="enroll(p)"
          >加入学习</el-button>
          <el-button v-else size="small" @click.stop="goDetail(p)">
            {{ p.my_enrollment && p.my_enrollment.status === 'active' ? '继续学习' : '查看详情' }}
          </el-button>
        </div>
      </div>
    </div>

    <!-- 新建学习路径对话框（给自己规划） -->
    <el-dialog v-model="createDlg" title="新建我的学习路径" width="560px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="所属专业" required>
          <el-select v-model="form.major_id" placeholder="选择专业" style="width: 100%">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="路径标题" required>
          <el-input v-model="form.title" placeholder="如：软件工程入门路线" maxlength="100" />
        </el-form-item>
        <el-form-item label="学习目标">
          <el-input
            v-model="form.learning_goal" type="textarea" :rows="2"
            placeholder="学完后希望达到什么程度，如：能独立完成一个 Web 小项目"
          />
        </el-form-item>
        <el-form-item label="计划周期">
          <el-date-picker
            v-model="form.date_range" type="daterange" value-format="YYYY-MM-DD"
            range-separator="至" start-placeholder="开始日期" end-placeholder="目标完成日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="这条路径包含哪些内容（可留空）" />
        </el-form-item>
        <el-form-item label="目标学时">
          <el-input-number v-model="form.target_hours" :min="1" :max="999" />
        </el-form-item>
        <el-form-item label="难度">
          <el-select v-model="form.difficulty" style="width: 100%">
            <el-option label="简单" value="easy" />
            <el-option label="中等" value="medium" />
            <el-option label="困难" value="hard" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="form-hint">这是你给自己规划的学习路径，创建后即可添加节点开始学习</div>
      <template #footer>
        <el-button @click="createDlg = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createPath">创建并开始</el-button>
      </template>
    </el-dialog>

    <!-- AI 生成路径对话框（全民可用） -->
    <el-dialog
      v-model="aiDlg" title="AI 生成学习路径" width="560px"
      :close-on-click-modal="false"
      :close-on-press-escape="!aiGenerating"
      :show-close="!aiGenerating"
    >
      <el-alert
        type="info" :closable="false" show-icon style="margin-bottom: 16px"
        title="AI 将按所选章节拆解知识点、生成依赖关系与推荐学习顺序，创建为草稿路径，可再手动调整后发布"
      />
      <el-form :model="aiForm" label-width="90px">
        <el-form-item label="所属专业" required>
          <el-select
            v-model="aiForm.major_id" placeholder="选择专业" style="width: 100%"
            :loading="aiLoadingChapters" @change="loadChapterTree"
          >
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择章节" required>
          <el-select
            v-model="aiForm.chapter_ids" multiple placeholder="先选专业，再勾选章节" style="width: 100%"
            :disabled="!aiForm.major_id" :loading="aiLoadingChapters"
          >
            <el-option-group v-for="g in chapterTree" :key="g.course_id" :label="g.course_name">
              <el-option v-for="c in g.chapters" :key="c.id" :label="c.name" :value="c.id" />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="路径标题" required>
          <el-input v-model="aiForm.title" placeholder="如：数据结构核心路线" maxlength="100" />
        </el-form-item>
        <el-form-item label="学习目标">
          <el-input
            v-model="aiForm.learning_goal" type="textarea" :rows="2"
            placeholder="学完后希望达到什么程度（可留空）"
          />
        </el-form-item>
        <el-form-item label="计划周期">
          <el-date-picker
            v-model="aiForm.date_range" type="daterange" value-format="YYYY-MM-DD"
            range-separator="至" start-placeholder="开始日期" end-placeholder="目标完成日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="aiForm.description" type="textarea" :rows="2" placeholder="这条路径包含哪些内容（可留空）" />
        </el-form-item>
      </el-form>
      <!-- 生成中加载状态提示 -->
      <div v-if="aiGenerating" class="ai-gen-loading">
        <el-icon class="gen-spinner"><Loading /></el-icon>
        <div class="gen-body">
          <span class="gen-title">AI 正在生成路径骨架…</span>
          <span class="gen-step" :key="aiGenStageIdx">{{ aiGenStage }}</span>
        </div>
        <div class="gen-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
      <template #footer>
        <el-button :disabled="aiGenerating" @click="aiDlg = false">取消</el-button>
        <el-button type="primary" :loading="aiGenerating" @click="generatePath">
          {{ aiGenerating ? 'AI 生成中（约 10~30 秒）' : '开始生成' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- AI 学习助手 -->
    <AIChatDialog :context="aiContext" :suggestions="aiSuggestions" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, MagicStick, Aim, Calendar, Loading } from '@element-plus/icons-vue'
import request from '../utils/request'
import AIChatDialog from '../components/AIChatDialog.vue'

const router = useRouter()

const majors = ref([])
const paths = ref([])
const loading = ref(true)
const filterMajorId = ref(null)
const filterStatus = ref(null)

const createDlg = ref(false)
const creating = ref(false)
const emptyForm = () => ({
  major_id: null, title: '', description: '', learning_goal: '',
  target_hours: 20, difficulty: 'medium', date_range: [],
})
const form = ref(emptyForm())

const openCreateDlg = () => {
  form.value = emptyForm()
  createDlg.value = true
}

// ── AI 生成路径 ────────────────────────────────────────────────────
const aiDlg = ref(false)
const aiGenerating = ref(false)
const aiLoadingChapters = ref(false)
const chapterTree = ref([])   // [{course_id, course_name, chapters:[{id,name}]}]
const aiForm = ref({ major_id: null, chapter_ids: [], title: '', description: '', learning_goal: '', date_range: [] })

// 生成中分阶段提示：按时间推进显示 AI 当前在做什么，提升用户等待体验
const AI_GEN_STAGES = [
  '正在分析所选章节的内容…',
  '拆解知识点并识别关键概念…',
  '建立知识点之间的依赖关系…',
  '生成学习节点与推荐学习顺序…',
  '收尾整理，即将完成…',
]
const aiGenStageIdx = ref(0)
const aiGenStageTimer = ref(null)
const aiGenStage = computed(() => AI_GEN_STAGES[aiGenStageIdx.value])

const startAiGenStage = () => {
  aiGenStageIdx.value = 0
  if (aiGenStageTimer.value) clearInterval(aiGenStageTimer.value)
  aiGenStageTimer.value = setInterval(() => {
    if (aiGenStageIdx.value < AI_GEN_STAGES.length - 1) {
      aiGenStageIdx.value++
    }
  }, 5000)
}
const stopAiGenStage = () => {
  if (aiGenStageTimer.value) {
    clearInterval(aiGenStageTimer.value)
    aiGenStageTimer.value = null
  }
}

const openAiDlg = () => {
  aiForm.value = { major_id: null, chapter_ids: [], title: '', description: '', learning_goal: '', date_range: [] }
  chapterTree.value = []
  aiGenStageIdx.value = 0
  aiDlg.value = true
}

// 选定专业后：拉课程列表，再按课程拉章节，聚成分组结构
const loadChapterTree = async (majorId) => {
  aiForm.value.chapter_ids = []
  chapterTree.value = []
  if (!majorId) return
  aiLoadingChapters.value = true
  try {
    const res = await request.get('/api/courses', { params: { major_id: majorId } })
    const courses = res.data || []
    const groups = await Promise.all(courses.map(async (c) => {
      try {
        const r = await request.get('/api/chapters', { params: { course_id: c.id } })
        return { course_id: c.id, course_name: c.name, chapters: r.data || [] }
      } catch (e) {
        return { course_id: c.id, course_name: c.name, chapters: [] }
      }
    }))
    chapterTree.value = groups.filter(g => g.chapters.length > 0)
    if (chapterTree.value.length === 0) {
      ElMessage.warning('该专业下暂无章节，请先在课程管理中创建')
    }
  } catch (e) { /* 拦截器已提示 */ }
  aiLoadingChapters.value = false
}

const generatePath = async () => {
  if (!aiForm.value.major_id || !aiForm.value.title.trim()) {
    ElMessage.warning('请选择专业并填写路径标题')
    return
  }
  if (!aiForm.value.chapter_ids.length) {
    ElMessage.warning('请至少选择一个章节')
    return
  }
  aiGenerating.value = true
  startAiGenStage()
  try {
    const payload = {
      major_id: aiForm.value.major_id,
      chapter_ids: aiForm.value.chapter_ids,
      title: aiForm.value.title,
      description: aiForm.value.description,
      learning_goal: aiForm.value.learning_goal,
      start_date: aiForm.value.date_range?.[0] || null,
      target_end_date: aiForm.value.date_range?.[1] || null,
    }
    const res = await request.post('/api/learning/paths/ai-generate', payload)
    const d = res.data
    ElMessage.success(
      `生成完成：新建知识点 ${d.kp_created} 个（复用 ${d.kp_existing} 个）、关系边 ${d.edges_created} 条、节点 ${d.nodes_created} 个`
    )
    aiDlg.value = false
    router.push(`/learning/paths/${d.id}`)
  } catch (e) { /* 拦截器已提示 */ }
  aiGenerating.value = false
  stopAiGenStage()
}

const progressColor = '#06b6d4'

const loadMajors = async () => {
  try {
    const res = await request.get('/api/majors')
    majors.value = res.data || []
  } catch (e) { /* 静默 */ }
}

const loadPaths = async () => {
  loading.value = true
  try {
    const params = {}
    if (filterMajorId.value) params.major_id = filterMajorId.value
    if (filterStatus.value) params.status = filterStatus.value
    const res = await request.get('/api/learning/paths', { params })
    paths.value = res.data || []
  } catch (e) { /* request 拦截器已提示 */ }
  loading.value = false
}

const enroll = async (p) => {
  try {
    await request.post(`/api/learning/paths/${p.id}/enrollments`)
    ElMessage.success('加入成功，开始学习吧')
    loadPaths()
  } catch (e) { /* 拦截器已提示 */ }
}

const createPath = async () => {
  if (!form.value.major_id || !form.value.title.trim()) {
    ElMessage.warning('请选择专业并填写标题')
    return
  }
  creating.value = true
  try {
    const payload = {
      ...form.value,
      start_date: form.value.date_range?.[0] || null,
      target_end_date: form.value.date_range?.[1] || null,
    }
    delete payload.date_range
    const res = await request.post('/api/learning/paths', payload)
    ElMessage.success('创建成功，已加入我的学习路径')
    createDlg.value = false
    router.push(`/learning/paths/${res.data.id}`)
  } catch (e) { /* 拦截器已提示 */ }
  creating.value = false
}

const goDetail = (p) => router.push(`/learning/paths/${p.id}`)

// ── AI 助手上下文 ─────────────────────────────────────────────────
const aiContext = computed(() => {
  const majorName = majors.value.find(m => m.id === filterMajorId.value)?.name
  return `学习者正在「专业学习路径」页浏览学习路径${majorName ? `（当前筛选专业：${majorName}）` : ''}，` +
    `页面共 ${paths.value.length} 条路径。正在考虑选哪条路径、如何安排学习顺序。`
})
const aiSuggestions = [
  '如何选择适合我的学习路径？',
  '路径学习应该按什么节奏推进？',
  '给我一些坚持学完路径的建议',
]

const statusLabel = (s) => ({ draft: '草稿', published: '已发布', archived: '已归档' }[s] || s)
const statusTagType = (s) => ({ draft: 'info', published: 'success', archived: 'warning' }[s] || 'info')
const formatMinutes = (min) => {
  if (!min) return '0 分钟'
  if (min < 60) return `${min} 分钟`
  return `${Math.round(min / 60 * 10) / 10} 小时`
}
// 距计划完成日的天数：无完成日期返回 null
const daysLeft = (p) => {
  if (!p.target_end_date) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const end = new Date(`${p.target_end_date}T00:00:00`)
  return Math.round((end - today) / 86400000)
}

onMounted(() => {
  loadMajors()
  loadPaths()
})

// 组件卸载时兜底清理阶段定时器，避免泄漏
onBeforeUnmount(() => {
  stopAiGenStage()
})
</script>

<style scoped>
.paths-page {
  padding: 20px;
  max-width: 1200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 12px;
  flex-wrap: wrap;
}

.page-title {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--text-primary);
}

.page-subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.path-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 18px;
}

.path-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.25s ease;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.path-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.1);
  border-color: rgba(6, 182, 212, 0.45);
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.path-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.path-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.path-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 12px;
  color: var(--text-muted);
  flex-wrap: wrap;
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.progress-row :deep(.el-progress) {
  flex: 1;
}

.progress-text {
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
}

.creator {
  font-size: 12px;
  color: var(--text-muted);
}

.path-goal {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-secondary, var(--text-muted));
  background: rgba(6, 182, 212, 0.07);
  border-left: 3px solid #06b6d4;
  border-radius: 6px;
  padding: 7px 10px;
  line-height: 1.5;
}

.path-goal span {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.days-left { color: #059669; font-weight: 600; }
.days-over { color: #dc2626; font-weight: 600; }

.form-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: -4px;
  line-height: 1.5;
}

/* AI 生成中加载提示 */
.ai-gen-loading {
  display: flex;
  align-items: center;
  gap: 14px;
  background: linear-gradient(135deg, rgba(6, 182, 212, 0.08) 0%, rgba(99, 102, 241, 0.08) 100%);
  border: 1px solid rgba(6, 182, 212, 0.28);
  border-radius: 12px;
  padding: 16px 18px;
  margin: 4px 0 16px;
}

.gen-spinner {
  font-size: 26px;
  color: #06b6d4;
  animation: ai-gen-spin 1.4s linear infinite;
  flex-shrink: 0;
}

@keyframes ai-gen-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.gen-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.gen-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

/* :key 变化触发淡入，让阶段切换更柔和 */
.gen-step {
  font-size: 12.5px;
  color: var(--text-muted);
  animation: ai-gen-fade 0.4s ease;
}

@keyframes ai-gen-fade {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.gen-dots {
  display: flex;
  gap: 5px;
  flex-shrink: 0;
}

.gen-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #06b6d4;
  opacity: 0.4;
  animation: ai-gen-pulse 1.2s ease-in-out infinite;
}

.gen-dots span:nth-child(2) { animation-delay: 0.2s; }
.gen-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes ai-gen-pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.15); }
}

.empty-tip {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 0;
}
</style>
