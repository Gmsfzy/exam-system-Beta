<template>
  <div class="path-detail">
    <div class="top-bar">
      <el-button text @click="$router.push('/learning/paths')">
        <el-icon><ArrowLeft /></el-icon> 返回路径列表
      </el-button>
    </div>

    <div v-if="loading" class="empty-tip">加载中...</div>
    <template v-else-if="path">
      <!-- 路径头部 -->
      <div class="path-header">
        <div class="header-main">
          <div class="title-row">
            <h1 class="path-title">{{ path.title }}</h1>
            <el-tag :type="statusTagType(path.status)" size="small">
              {{ statusLabel(path.status) }}
            </el-tag>
          </div>
          <p class="path-desc">{{ path.description || '暂无简介' }}</p>
          <div v-if="path.learning_goal" class="path-goal">
            <el-icon color="#06b6d4"><Aim /></el-icon>
            <div>
              <span class="goal-label">学习目标</span>
              <p>{{ path.learning_goal }}</p>
            </div>
          </div>
          <div class="path-meta">
            <el-tag size="small" effect="plain">{{ path.major_name || '未关联专业' }}</el-tag>
            <el-tag v-if="path.is_creator" size="small" type="success">我的路径</el-tag>
            <span>{{ path.nodes_count }} 个节点</span>
            <span>约 {{ formatMinutes(path.total_minutes) }}</span>
            <span v-if="path.target_hours">目标 {{ path.target_hours }} 学时</span>
            <span>创建者：{{ path.creator_name || '-' }}</span>
          </div>
          <div v-if="path.start_date || path.target_end_date" class="path-meta plan-dates">
            <el-icon color="#f59e0b"><Calendar /></el-icon>
            <span>计划周期：{{ path.start_date || '未设定' }} 至 {{ path.target_end_date || '长期' }}</span>
            <span v-if="daysLeft !== null" :class="daysLeft < 0 ? 'days-over' : 'days-left'">
              {{ daysLeft < 0 ? `已超期 ${-daysLeft} 天` : (daysLeft === 0 ? '今天到期' : `剩余 ${daysLeft} 天`) }}
            </span>
          </div>
        </div>

        <div class="header-actions">
          <!-- 别人发布的路径：只能加入/退出学习 -->
          <template v-if="!path.is_creator">
            <el-button v-if="path.my_enrollment && path.my_enrollment.status !== 'abandoned'"
              type="danger" plain @click="abandon">退出学习</el-button>
            <el-button v-else type="primary" @click="enroll">加入学习</el-button>
          </template>
          <!-- 自己的路径：管理操作 -->
          <template v-else>
            <el-button @click="openEdit">
              <el-icon style="margin-right: 4px"><Edit /></el-icon>编辑计划
            </el-button>
            <el-button v-if="path.status === 'draft'" type="success" @click="changeStatus('published')">发布路径</el-button>
            <el-button v-if="path.status === 'published'" type="warning" plain @click="changeStatus('archived')">归档</el-button>
            <el-button v-if="path.status === 'archived'" type="success" plain @click="changeStatus('published')">重新发布</el-button>
            <el-button type="primary" @click="openAddNode">添加节点</el-button>
            <el-button type="danger" plain @click="deletePath">删除</el-button>
          </template>
        </div>
      </div>

      <!-- 我的进度概览 -->
      <div v-if="path.my_enrollment && path.my_enrollment.total_count" class="progress-card">
        <el-progress
          :percentage="path.my_enrollment.progress"
          :stroke-width="10"
          :color="progressColor"
        />
        <span class="progress-text">
          已掌握 {{ path.my_enrollment.completed_count }}/{{ path.my_enrollment.total_count }} 个节点
        </span>
      </div>

      <!-- 结业测评 / 证书入口 -->
      <div v-if="myCert || enrollmentCompleted" class="final-banner" :class="{ certified: myCert }">
        <div class="fb-icon">{{ myCert ? '🏅' : '🎓' }}</div>
        <div class="fb-main">
          <span class="fb-title">{{ myCert ? '你已获得本路径结业证书' : '全部节点已掌握，参加一次结业测评即可获颁证书' }}</span>
          <span v-if="myCert" class="fb-sub">编号 {{ myCert.serial_no }} · 终测 {{ Math.round((myCert.final_score || 0) * 100) }} 分</span>
          <span v-else class="fb-sub">结业测评达到 80% 通过，从核心知识点自动组卷，可反复重考</span>
        </div>
        <el-button v-if="myCert" type="warning" @click="$router.push(`/learning/certificates/${myCert.id}`)">查看证书 →</el-button>
        <el-button v-else type="primary" @click="finalDlg = true">参加结业测评</el-button>
      </div>

      <!-- 知识图谱导航（懒加载） -->
      <div class="graph-panel">
        <div class="graph-panel-head" @click="toggleGraph">
          <div class="gp-title">
            <el-icon color="#06b6d4"><Connection /></el-icon>
            <h2>知识图谱导航</h2>
            <span class="gp-hint">青色高亮 = 已掌握节点，点击图中知识点直接进入学习</span>
          </div>
          <el-button size="small" text type="primary">{{ showGraph ? '收起' : '展开' }}</el-button>
        </div>
        <div v-if="showGraph" class="graph-panel-body">
          <KnowledgeGraph
            :nodes="graphNodes" :edges="graphEdges" layout="cose" height="380px"
            :highlight-ids="masteredKpIds" @node-tap="onGraphTap"
          />
        </div>
      </div>

      <!-- 节点列表 -->
      <el-empty
        v-if="path.nodes.length === 0"
        :description="path.is_creator ? '还没有学习节点，点击「添加节点」规划第一步学什么' : '创建者还没有添加学习节点'"
      />
      <div v-else class="node-list">
        <div
          v-for="(n, idx) in path.nodes" :key="n.id"
          class="node-item"
          :class="{ current: n.id === currentNodeId, done: n.progress_status === 'mastered' }"
          @click="goNode(n)"
        >
          <div class="node-order" :class="{ done: n.progress_status === 'mastered' }">
            {{ n.progress_status === 'mastered' ? '✓' : idx + 1 }}
          </div>
          <div class="node-body">
            <div class="node-title-row">
              <span class="node-title">{{ n.title }}</span>
              <el-tag v-if="n.role === 'elective'" size="small" type="info">选修</el-tag>
              <el-tag v-else-if="n.role === 'review'" size="small" type="warning">复习</el-tag>
              <el-tag v-if="n.difficulty" size="small" effect="plain">{{ diffLabel(n.difficulty) }}</el-tag>
            </div>
            <div class="node-meta">
              <span>约 {{ n.estimated_minutes || 30 }} 分钟</span>
              <span v-if="n.progress_status === 'mastered'" class="status-mastered">已掌握</span>
              <span v-else-if="n.progress_status === 'in_progress'" class="status-doing">学习中</span>
              <span v-else-if="n.progress_status === 'skipped'" class="status-skip">已跳过</span>
            </div>
          </div>
          <div v-if="path.is_creator" class="node-ops" @click.stop>
            <el-button size="small" text :disabled="idx === 0" @click="moveNode(n, -1)">上移</el-button>
            <el-button size="small" text :disabled="idx === path.nodes.length - 1" @click="moveNode(n, 1)">下移</el-button>
            <el-button size="small" text type="danger" :disabled="path.status !== 'draft'" @click="deleteNode(n)">删除</el-button>
          </div>
        </div>
      </div>

      <!-- 添加节点对话框（规划自己的学习步骤） -->
      <el-dialog v-model="addDlg" title="添加学习节点" width="500px">
        <el-form :model="nodeForm" label-width="90px">
          <el-form-item label="知识点" required>
            <el-select v-model="nodeForm.knowledge_point_id" filterable placeholder="选择知识点" style="width: 100%">
              <el-option
                v-for="kp in knowledgePoints" :key="kp.id"
                :label="`${kp.name}（${kp.chapter_name || ''}）`" :value="kp.id"
              />
            </el-select>
            <div class="form-hint">按学习先后顺序添加，节点就是你计划里的每一步</div>
          </el-form-item>
          <el-form-item label="节点角色">
            <el-select v-model="nodeForm.role" style="width: 100%">
              <el-option label="核心" value="core" />
              <el-option label="选修" value="elective" />
              <el-option label="复习" value="review" />
            </el-select>
          </el-form-item>
          <el-form-item label="预计分钟">
            <el-input-number v-model="nodeForm.estimated_minutes" :min="5" :max="600" :step="5" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="addDlg = false">取消</el-button>
          <el-button type="primary" :loading="adding" @click="addNode">添加</el-button>
        </template>
      </el-dialog>

      <!-- 编辑学习计划对话框（仅创建者） -->
      <el-dialog v-model="editDlg" title="编辑学习计划" width="560px">
        <el-form :model="editForm" label-width="90px">
          <el-form-item label="路径标题" required>
            <el-input v-model="editForm.title" maxlength="100" />
          </el-form-item>
          <el-form-item label="学习目标">
            <el-input
              v-model="editForm.learning_goal" type="textarea" :rows="2"
              placeholder="学完后希望达到什么程度"
            />
          </el-form-item>
          <el-form-item label="计划周期">
            <el-date-picker
              v-model="editForm.date_range" type="daterange" value-format="YYYY-MM-DD"
              range-separator="至" start-placeholder="开始日期" end-placeholder="目标完成日期"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item label="简介">
            <el-input v-model="editForm.description" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="目标学时">
            <el-input-number v-model="editForm.target_hours" :min="1" :max="999" />
          </el-form-item>
          <el-form-item label="难度">
            <el-select v-model="editForm.difficulty" style="width: 100%">
              <el-option label="简单" value="easy" />
              <el-option label="中等" value="medium" />
              <el-option label="困难" value="hard" />
            </el-select>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editDlg = false">取消</el-button>
          <el-button type="primary" :loading="savingEdit" @click="saveEdit">保存</el-button>
        </template>
      </el-dialog>

      <!-- 结业测评弹窗 -->
      <QuizDialog v-model="finalDlg" :payload="{ path_id: pathId }" title="路径结业测评" @finished="onFinalFinished" />
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Connection, Aim, Calendar, Edit } from '@element-plus/icons-vue'
import request from '../utils/request'
import KnowledgeGraph from '../components/KnowledgeGraph.vue'
import QuizDialog from '../components/QuizDialog.vue'

const route = useRoute()
const router = useRouter()

const pathId = Number(route.params.id)
const path = ref(null)
const loading = ref(true)
const progressColor = '#06b6d4'

const addDlg = ref(false)
const adding = ref(false)
const knowledgePoints = ref([])
const nodeForm = ref({ knowledge_point_id: null, role: 'core', estimated_minutes: 30 })

const currentNodeId = computed(() => path.value?.my_enrollment?.current_node_id ?? null)

// ── 结业测评与证书 ──
const finalDlg = ref(false)
const myCert = ref(null)
const enrollmentCompleted = computed(() =>
  path.value?.my_enrollment?.status === 'completed')

const loadMyCert = async () => {
  myCert.value = null
  if (!path.value?.my_enrollment) return
  try {
    const res = await request.get('/api/learning/certificates/mine')
    myCert.value = (res.data || []).find(c => c.path_id === pathId) || null
  } catch (e) { /* 静默 */ }
}

const onFinalFinished = async () => {
  await loadPath()
  await loadMyCert()
}

// 距计划完成日的天数（无完成日期为 null）
const daysLeft = computed(() => {
  const end = path.value?.target_end_date
  if (!end) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((new Date(`${end}T00:00:00`) - today) / 86400000)
})

const loadPath = async () => {
  loading.value = true
  try {
    const res = await request.get(`/api/learning/paths/${pathId}`)
    path.value = res.data
    loadMyCert()
  } catch (e) { /* 拦截器已提示 */ }
  loading.value = false
}

const loadKnowledgePoints = async () => {
  if (!path.value) return
  try {
    const res = await request.get('/api/learning/knowledge-points', {
      params: { major_id: path.value.major_id, all: 1 },
    })
    knowledgePoints.value = res.data || []
  } catch (e) { /* 静默 */ }
}

const enroll = async () => {
  try {
    await request.post(`/api/learning/paths/${pathId}/enrollments`)
    ElMessage.success('加入成功')
    loadPath()
  } catch (e) { /* 拦截器已提示 */ }
}

const abandon = async () => {
  try {
    await ElMessageBox.confirm('退出后进度将保留，确定退出该路径？', '退出学习', { type: 'warning' })
  } catch { return }
  try {
    await request.post(`/api/learning/paths/${pathId}/abandon`)
    ElMessage.success('已退出')
    loadPath()
  } catch (e) { /* 拦截器已提示 */ }
}

const changeStatus = async (status) => {
  try {
    await request.put(`/api/learning/paths/${pathId}`, { status })
    ElMessage.success('状态已更新')
    loadPath()
  } catch (e) { /* 拦截器已提示 */ }
}

const deletePath = async () => {
  try {
    await ElMessageBox.confirm('确定删除该路径？已发布路径将转为归档。', '删除路径', { type: 'warning' })
  } catch { return }
  try {
    await request.delete(`/api/learning/paths/${pathId}`)
    ElMessage.success('已删除')
    router.push('/learning/paths')
  } catch (e) { /* 拦截器已提示 */ }
}

// ── 编辑学习计划（标题/目标/周期/简介/学时/难度） ──
const editDlg = ref(false)
const savingEdit = ref(false)
const editForm = ref({})

const openEdit = () => {
  editForm.value = {
    title: path.value.title,
    description: path.value.description || '',
    learning_goal: path.value.learning_goal || '',
    target_hours: path.value.target_hours || 20,
    difficulty: path.value.difficulty || 'medium',
    date_range: (path.value.start_date || path.value.target_end_date)
      ? [path.value.start_date, path.value.target_end_date]
      : [],
  }
  editDlg.value = true
}

const saveEdit = async () => {
  if (!editForm.value.title?.trim()) {
    ElMessage.warning('请填写路径标题')
    return
  }
  savingEdit.value = true
  try {
    await request.put(`/api/learning/paths/${pathId}`, {
      title: editForm.value.title,
      description: editForm.value.description,
      learning_goal: editForm.value.learning_goal,
      target_hours: editForm.value.target_hours,
      difficulty: editForm.value.difficulty,
      start_date: editForm.value.date_range?.[0] || null,
      target_end_date: editForm.value.date_range?.[1] || null,
    })
    ElMessage.success('学习计划已更新')
    editDlg.value = false
    loadPath()
  } catch (e) { /* 拦截器已提示 */ }
  savingEdit.value = false
}

const openAddNode = () => {
  nodeForm.value = { knowledge_point_id: null, role: 'core', estimated_minutes: 30 }
  addDlg.value = true
  loadKnowledgePoints()
}

const addNode = async () => {
  if (!nodeForm.value.knowledge_point_id) {
    ElMessage.warning('请选择知识点')
    return
  }
  adding.value = true
  try {
    await request.post(`/api/learning/paths/${pathId}/nodes`, {
      node_type: 'knowledge_point',
      ...nodeForm.value,
    })
    ElMessage.success('节点已添加')
    addDlg.value = false
    loadPath()
  } catch (e) { /* 拦截器已提示 */ }
  adding.value = false
}

const moveNode = async (n, dir) => {
  const idx = path.value.nodes.findIndex(x => x.id === n.id)
  const target = path.value.nodes[idx + dir]
  if (!target) return
  try {
    await request.put(`/api/learning/paths/${pathId}/nodes/${n.id}`, { order_num: target.order_num })
    loadPath()
  } catch (e) { /* 拦截器已提示 */ }
}

const deleteNode = async (n) => {
  try {
    await ElMessageBox.confirm(`确定删除节点「${n.title}」？`, '删除节点', { type: 'warning' })
  } catch { return }
  try {
    await request.delete(`/api/learning/paths/${pathId}/nodes/${n.id}`)
    ElMessage.success('节点已删除')
    loadPath()
  } catch (e) { /* 拦截器已提示 */ }
}

const goNode = (n) => router.push(`/learning/node/${n.id}?path=${pathId}`)

// ── 知识图谱导航（首次展开时懒加载） ──
const showGraph = ref(false)
const graphNodes = ref([])
const graphEdges = ref([])
const graphLoaded = ref(false)

const masteredKpIds = computed(() => (path.value?.nodes || [])
  .filter(n => n.progress_status === 'mastered' && n.knowledge_point_id)
  .map(n => n.knowledge_point_id))

const toggleGraph = async () => {
  showGraph.value = !showGraph.value
  if (showGraph.value && !graphLoaded.value) {
    try {
      const res = await request.get('/api/learning/knowledge-graph', { params: { path_id: pathId } })
      graphNodes.value = res.data.nodes || []
      graphEdges.value = res.data.edges || []
    } catch (e) {
      graphNodes.value = []
      graphEdges.value = []
    }
    graphLoaded.value = true
  }
}

const onGraphTap = (n) => {
  const pathNode = (path.value?.nodes || []).find(x => x.knowledge_point_id === n.id)
  if (pathNode) goNode(pathNode)
  else ElMessage.info(`「${n.name}」不在当前路径中，可前往「知识图谱」页查看`)
}

// v4.6.1 枚举收敛：难度中文名单一来源 frontend/src/utils/enums.js
import { difficultyLabel } from '../utils/enums'
const statusLabel = (s) => ({ draft: '草稿', published: '已发布', archived: '已归档' }[s] || s)
const statusTagType = (s) => ({ draft: 'info', published: 'success', archived: 'warning' }[s] || 'info')
const diffLabel = difficultyLabel
const formatMinutes = (min) => {
  if (!min) return '0 分钟'
  if (min < 60) return `${min} 分钟`
  return `${Math.round(min / 60 * 10) / 10} 小时`
}

onMounted(loadPath)
</script>

<style scoped>
.path-detail {
  padding: 20px;
  max-width: 1000px;
}

.top-bar {
  margin-bottom: 12px;
}

.path-header {
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

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.path-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}

.path-desc {
  font-size: 14px;
  color: var(--text-muted);
  margin: 8px 0 10px;
  line-height: 1.6;
}

.path-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 12px;
  color: var(--text-muted);
  flex-wrap: wrap;
}

.plan-dates {
  margin-top: 8px;
  font-size: 12.5px;
}

.days-left { color: #059669; font-weight: 600; }
.days-over { color: #dc2626; font-weight: 600; }

.path-goal {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: rgba(6, 182, 212, 0.07);
  border-left: 3px solid #06b6d4;
  border-radius: 8px;
  padding: 10px 12px;
  margin: 10px 0;
}

.path-goal .goal-label {
  font-size: 12px;
  font-weight: 600;
  color: #06b6d4;
}

.path-goal p {
  margin: 2px 0 0;
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.progress-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  margin-bottom: 20px;
}

.progress-card :deep(.el-progress) {
  flex: 1;
}

.progress-text {
  font-size: 13px;
  color: var(--text-muted);
  white-space: nowrap;
}

.final-banner {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 12px;
  padding: 16px 20px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.10) 0%, rgba(239, 68, 68, 0.08) 100%);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 14px;
}

.final-banner.certified {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(245, 158, 11, 0.08) 100%);
  border-color: rgba(16, 185, 129, 0.35);
}

.fb-icon { font-size: 30px; }
.fb-main { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.fb-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.fb-sub { font-size: 12px; color: var(--text-muted); }

.graph-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  margin-bottom: 20px;
  overflow: hidden;
}

.graph-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  cursor: pointer;
  user-select: none;
}

.graph-panel-head:hover {
  background: rgba(6, 182, 212, 0.04);
}

.gp-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.gp-title h2 {
  font-size: 15px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
}

.gp-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: 6px;
}

.graph-panel-body {
  padding: 0 8px 8px;
}

.node-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.node-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.node-item:hover {
  border-color: rgba(6, 182, 212, 0.5);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.08);
}

.node-item.current {
  border-color: #06b6d4;
  box-shadow: 0 0 0 2px rgba(6, 182, 212, 0.18);
}

.node-item.done {
  opacity: 0.75;
}

.node-order {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, #06b6d4 0%, #0891b2 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.node-order.done {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.node-body {
  flex: 1;
  min-width: 0;
}

.node-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.node-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.node-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.status-mastered { color: #10b981; }
.status-doing { color: #06b6d4; }
.status-skip { color: #f59e0b; }

.node-ops {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.form-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
  line-height: 1.5;
}

.empty-tip {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 0;
}
</style>
