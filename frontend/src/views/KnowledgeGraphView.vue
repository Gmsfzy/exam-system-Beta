<template>
  <div class="kg-view">
    <div class="page-header">
      <h1 class="page-title">知识图谱</h1>
      <p class="page-subtitle">知识点关系全景 · 前置依赖一目了然 · 点击节点查看详情</p>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-row">
        <el-radio-group v-model="mode" @change="onModeChange">
          <el-radio-button value="major">按专业</el-radio-button>
          <el-radio-button value="path">按路径</el-radio-button>
        </el-radio-group>

        <el-select
          v-if="mode === 'major'" v-model="majorId" filterable placeholder="选择专业"
          style="width: 200px" @change="loadGraph"
        >
          <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-select
          v-else v-model="pathId" filterable placeholder="选择学习路径"
          style="width: 240px" @change="loadGraph"
        >
          <el-option
            v-for="p in paths" :key="p.id"
            :label="p.title + (p.status !== 'published' ? `（${statusLabel(p.status)}）` : '')"
            :value="p.id"
          />
        </el-select>

        <el-radio-group v-model="layoutName">
          <el-radio-button value="cose">力导向</el-radio-button>
          <el-radio-button value="breadthfirst">层次</el-radio-button>
          <el-radio-button value="circle">环形</el-radio-button>
        </el-radio-group>

        <div class="toolbar-spacer"></div>
        <span class="stat-text">{{ nodes.length }} 个知识点 · {{ edges.length }} 条关系</span>
        <el-button type="primary" plain @click="openCreateKp">
          <el-icon><Plus /></el-icon> 新建知识点
        </el-button>
        <el-button type="primary" plain @click="openCreateEdge">
          <el-icon><Connection /></el-icon> 新建关系
        </el-button>
      </div>

      <!-- 图例 -->
      <div class="legend-row">
        <span class="legend-title">难度：</span>
        <span class="legend-item"><i class="dot" style="background:#10b981"></i>简单</span>
        <span class="legend-item"><i class="dot" style="background:#f59e0b"></i>中等</span>
        <span class="legend-item"><i class="dot" style="background:#ef4444"></i>困难</span>
        <el-divider direction="vertical" />
        <span class="legend-item"><i class="line solid"></i>前置依赖</span>
        <span class="legend-item"><i class="line dashed"></i>相关</span>
        <span class="legend-item"><i class="line dotted"></i>衍生</span>
        <el-divider direction="vertical" />
        <span class="legend-tip">拖拽节点调整位置 · 滚轮缩放 · 点击节点/边查看详情</span>
      </div>
    </div>

    <!-- 图谱 -->
    <div class="graph-card">
      <KnowledgeGraph
        :nodes="nodes" :edges="edges" :layout="layoutName"
        height="560px" :editable="true"
        @node-tap="onNodeTap" @edge-tap="onEdgeTap"
      />
    </div>

    <!-- 节点详情对话框 -->
    <el-dialog v-model="nodeDlg" :title="currentNode?.name || '知识点详情'" width="480px">
      <template v-if="currentNode">
        <div class="detail-meta">
          <el-tag size="small" :type="diffTagType(currentNode.difficulty)">{{ diffLabel(currentNode.difficulty) }}</el-tag>
          <el-tag v-if="currentNode.chapter_name" size="small" effect="plain">{{ currentNode.chapter_name }}</el-tag>
        </div>
        <p class="detail-desc">{{ currentNode.description || '暂无简介' }}</p>
        <div class="detail-questions" v-loading="loadingQ">
          <template v-if="nodeQuestions.length">
            <div class="dq-head">关联题目（{{ nodeQuestions.length }}）</div>
            <div v-for="q in nodeQuestions.slice(0, 5)" :key="q.id" class="dq-item">
              <span class="q-type">{{ qTypeLabel(q.type) }}</span>
              <span class="q-content">{{ q.content }}</span>
            </div>
            <div v-if="nodeQuestions.length > 5" class="dq-more">等 {{ nodeQuestions.length }} 道题</div>
          </template>
          <div v-else-if="!loadingQ" class="dq-empty">该知识点暂无关联题目</div>
        </div>
      </template>
      <template #footer>
        <el-button v-if="currentNode" type="primary" @click="practiceFromKp">针对此知识点练习</el-button>
        <el-button type="danger" plain :disabled="!currentNode" @click="deprecateKp">下线该知识点</el-button>
        <el-button @click="nodeDlg = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 边详情对话框 -->
    <el-dialog v-model="edgeDlg" title="知识点关系" width="440px">
      <template v-if="currentEdge">
        <div class="edge-flow">
          <div class="edge-node">
            <span class="edge-node-label">{{ sourceName(currentEdge.source) }}</span>
            <span class="edge-node-role">源 · {{ relationLabel(currentEdge.relation_type) }}</span>
          </div>
          <el-icon class="edge-arrow" :size="22" color="#06b6d4"><Right /></el-icon>
          <div class="edge-node">
            <span class="edge-node-label">{{ sourceName(currentEdge.target) }}</span>
            <span class="edge-node-role">目标</span>
          </div>
        </div>
        <p class="detail-desc">关系类型：{{ relationLabel(currentEdge.relation_type) }} · 强度 {{ currentEdge.weight ?? 1 }}</p>
      </template>
      <template #footer>
        <el-button type="danger" plain @click="removeEdge">删除该关系</el-button>
        <el-button @click="edgeDlg = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新建知识点（全民共建） -->
    <el-dialog v-model="kpDlg" title="新建知识点" width="520px">
      <el-form :model="kpForm" label-width="90px">
        <el-form-item label="专业" required>
          <el-select v-model="kpForm.major_id" filterable style="width: 100%" @change="onKpMajorChange">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="课程" required>
          <el-select v-model="kpForm.course_id" filterable :disabled="!kpForm.major_id" style="width: 100%" @change="onKpCourseChange">
            <el-option v-for="c in kpCourses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="章节" required>
          <el-select v-model="kpForm.chapter_id" filterable :disabled="!kpForm.course_id" style="width: 100%">
            <el-option v-for="ch in kpChapters" :key="ch.id" :label="ch.name" :value="ch.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="kpForm.name" maxlength="80" placeholder="知识点名称" />
        </el-form-item>
        <el-form-item label="难度">
          <el-radio-group v-model="kpForm.difficulty">
            <el-radio value="easy">简单</el-radio>
            <el-radio value="medium">中等</el-radio>
            <el-radio value="hard">困难</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="kpForm.description" type="textarea" :rows="3" placeholder="一句话描述该知识点" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="kpDlg = false">取消</el-button>
        <el-button type="primary" :loading="savingKp" @click="createKp">创建</el-button>
      </template>
    </el-dialog>

    <!-- 新建关系（全民共建） -->
    <el-dialog v-model="edgeCreateDlg" title="新建知识点关系" width="520px">
      <el-alert
        v-if="nodes.length < 2" type="warning" :closable="false"
        title="当前图谱知识点不足 2 个，请先创建知识点" style="margin-bottom: 14px"
      />
      <el-form :model="edgeForm" label-width="110px">
        <el-form-item label="源知识点（前）" required>
          <el-select v-model="edgeForm.source_id" filterable style="width: 100%">
            <el-option
              v-for="n in nodes" :key="n.id"
              :label="`${n.name}（${n.chapter_name || ''}）`" :value="n.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="目标知识点" required>
          <el-select v-model="edgeForm.target_id" filterable style="width: 100%">
            <el-option
              v-for="n in nodes" :key="n.id"
              :label="`${n.name}（${n.chapter_name || ''}）`" :value="n.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="关系类型">
          <el-radio-group v-model="edgeForm.relation_type">
            <el-radio value="prerequisite">前置依赖</el-radio>
            <el-radio value="related">相关</el-radio>
            <el-radio value="derived">衍生</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <div class="form-hint">前置依赖：源知识点是目标知识点的基础，箭头由源指向目标</div>
      <template #footer>
        <el-button @click="edgeCreateDlg = false">取消</el-button>
        <el-button type="primary" :loading="savingEdge" :disabled="nodes.length < 2" @click="createEdge">创建</el-button>
      </template>
    </el-dialog>

    <!-- AI 学习助手 -->
    <AIChatDialog :context="aiContext" :suggestions="aiSuggestions" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Connection, Right } from '@element-plus/icons-vue'
import request from '../utils/request'
import KnowledgeGraph from '../components/KnowledgeGraph.vue'
import AIChatDialog from '../components/AIChatDialog.vue'

const router = useRouter()

// ── 数据源与图谱 ──
const mode = ref('major')
const majorId = ref(null)
const pathId = ref(null)
const majors = ref([])
const paths = ref([])
const nodes = ref([])
const edges = ref([])
const layoutName = ref('cose')

// ── AI 助手上下文 ──
const aiContext = computed(() => {
  const scope = mode.value === 'path'
    ? `路径「${paths.value.find(p => p.id === pathId.value)?.title || ''}」`
    : `专业「${majors.value.find(m => m.id === majorId.value)?.name || ''}」`
  const diffs = nodes.value.reduce((acc, n) => { acc[n.difficulty] = (acc[n.difficulty] || 0) + 1; return acc }, {})
  return `学习者正在「知识图谱」页查看${scope}的知识图谱，共 ${nodes.value.length} 个知识点、${edges.value.length} 条关系边` +
    `（简单 ${diffs.easy || 0} / 中等 ${diffs.medium || 0} / 困难 ${diffs.hard || 0}）。想弄懂知识点之间的关系和学习顺序。`
})
const aiSuggestions = [
  '结合图谱帮我规划复习顺序',
  '先学哪个知识点收益最大？',
  '图谱里的依赖关系怎么看？',
]

const loadMajors = async () => {
  try {
    const res = await request.get('/api/majors')
    majors.value = res.data || []
    if (!majorId.value && majors.value.length) {
      majorId.value = majors.value[0].id
    }
  } catch (e) { /* 拦截器已提示 */ }
}

const loadPaths = async () => {
  try {
    const res = await request.get('/api/learning/paths')
    paths.value = res.data || []
  } catch (e) { paths.value = [] }
}

const loadGraph = async () => {
  if (mode.value === 'major' && !majorId.value) return
  if (mode.value === 'path' && !pathId.value) return
  try {
    const params = mode.value === 'major' ? { major_id: majorId.value } : { path_id: pathId.value }
    const res = await request.get('/api/learning/knowledge-graph', { params })
    nodes.value = res.data.nodes || []
    edges.value = res.data.edges || []
  } catch (e) {
    nodes.value = []
    edges.value = []
  }
}

const onModeChange = async () => {
  if (mode.value === 'path' && paths.value.length === 0) {
    await loadPaths()
    if (paths.value.length && !pathId.value) pathId.value = paths.value[0].id
  }
  loadGraph()
}

// ── 节点详情 ──
const nodeDlg = ref(false)
const currentNode = ref(null)
const nodeQuestions = ref([])
const loadingQ = ref(false)

const onNodeTap = async (n) => {
  currentNode.value = n
  nodeQuestions.value = []
  nodeDlg.value = true
  loadingQ.value = true
  try {
    const res = await request.get(`/api/learning/knowledge-points/${n.id}/questions`)
    nodeQuestions.value = res.data || []
  } catch (e) { nodeQuestions.value = [] }
  loadingQ.value = false
}

const practiceFromKp = async () => {
  if (!currentNode.value) return
  try {
    const res = await request.post('/api/learning/practice/start', {
      knowledge_point_id: currentNode.value.id,
      count: 10,
      title: `知识点练习 · ${currentNode.value.name}`,
    })
    nodeDlg.value = false
    router.push(`/learning/practice/${res.data.session_id}`)
  } catch (e) { /* 拦截器已提示 */ }
}

const deprecateKp = async () => {
  if (!currentNode.value) return
  try {
    await ElMessageBox.confirm(
      `下线后「${currentNode.value.name}」将不再出现在图谱与新路径中（历史数据保留），确定下线？`,
      '下线知识点', { type: 'warning' }
    )
  } catch { return }
  try {
    await request.delete(`/api/learning/knowledge-points/${currentNode.value.id}`)
    ElMessage.success('已下线')
    nodeDlg.value = false
    loadGraph()
  } catch (e) { /* 拦截器已提示 */ }
}

// ── 边详情 ──
const edgeDlg = ref(false)
const currentEdge = ref(null)

const onEdgeTap = (e) => {
  currentEdge.value = e
  edgeDlg.value = true
}

const sourceName = (kpId) => nodes.value.find(n => n.id === kpId)?.name || `#${kpId}`

const removeEdge = async () => {
  if (!currentEdge.value) return
  try {
    await ElMessageBox.confirm('确定删除该知识点关系？', '删除关系', { type: 'warning' })
  } catch { return }
  try {
    await request.delete(`/api/learning/knowledge-edges/${currentEdge.value.id}`)
    ElMessage.success('已删除')
    edgeDlg.value = false
    loadGraph()
  } catch (e) { /* 拦截器已提示 */ }
}

// ── 新建知识点（教师） ──
const kpDlg = ref(false)
const savingKp = ref(false)
const kpCourses = ref([])
const kpChapters = ref([])
const kpForm = ref({ major_id: null, course_id: null, chapter_id: null, name: '', difficulty: 'easy', description: '' })

const openCreateKp = () => {
  kpForm.value = { major_id: majorId.value, course_id: null, chapter_id: null, name: '', difficulty: 'easy', description: '' }
  kpCourses.value = []
  kpChapters.value = []
  if (kpForm.value.major_id) loadKpCourses()
  kpDlg.value = true
}

const loadKpCourses = async () => {
  try {
    const res = await request.get('/api/courses', { params: { major_id: kpForm.value.major_id } })
    kpCourses.value = res.data || []
  } catch (e) { kpCourses.value = [] }
}

const loadKpChapters = async () => {
  try {
    const res = await request.get('/api/chapters', { params: { course_id: kpForm.value.course_id } })
    kpChapters.value = res.data || []
  } catch (e) { kpChapters.value = [] }
}

const onKpMajorChange = () => {
  kpForm.value.course_id = null
  kpForm.value.chapter_id = null
  kpCourses.value = []
  kpChapters.value = []
  if (kpForm.value.major_id) loadKpCourses()
}

const onKpCourseChange = () => {
  kpForm.value.chapter_id = null
  kpChapters.value = []
  if (kpForm.value.course_id) loadKpChapters()
}

const createKp = async () => {
  const f = kpForm.value
  if (!f.chapter_id) { ElMessage.warning('请选择章节'); return }
  if (!f.name.trim()) { ElMessage.warning('请填写知识点名称'); return }
  savingKp.value = true
  try {
    await request.post('/api/learning/knowledge-points', {
      chapter_id: f.chapter_id,
      name: f.name.trim(),
      difficulty: f.difficulty,
      description: f.description.trim() || null,
    })
    ElMessage.success('知识点已创建')
    kpDlg.value = false
    loadGraph()
  } catch (e) { /* 拦截器已提示 */ }
  savingKp.value = false
}

// ── 新建关系（教师） ──
const edgeCreateDlg = ref(false)
const savingEdge = ref(false)
const edgeForm = ref({ source_id: null, target_id: null, relation_type: 'prerequisite' })

const openCreateEdge = () => {
  edgeForm.value = { source_id: null, target_id: null, relation_type: 'prerequisite' }
  edgeCreateDlg.value = true
}

const createEdge = async () => {
  const f = edgeForm.value
  if (!f.source_id || !f.target_id) { ElMessage.warning('请选择两个知识点'); return }
  if (f.source_id === f.target_id) { ElMessage.warning('不能选择同一个知识点'); return }
  savingEdge.value = true
  try {
    await request.post('/api/learning/knowledge-edges', f)
    ElMessage.success('关系已创建')
    edgeCreateDlg.value = false
    loadGraph()
  } catch (e) { /* 拦截器已提示 */ }
  savingEdge.value = false
}

// ── 文案工具 ──
const diffLabel = (d) => ({ easy: '简单', medium: '中等', hard: '困难' }[d] || d)
const diffTagType = (d) => ({ easy: 'success', medium: 'warning', hard: 'danger' }[d] || 'info')
const statusLabel = (s) => ({ draft: '草稿', published: '已发布', archived: '已归档' }[s] || s)
const relationLabel = (t) => ({ prerequisite: '前置依赖', related: '相关', derived: '衍生' }[t] || t)
const qTypeLabel = (t) => ({
  single_choice: '单选', multiple_choice: '多选', fill_blank: '填空',
  true_false: '判断', short_answer: '问答', programming: '编程',
  application: '应用', calculation: '计算',
}[t] || t)

onMounted(async () => {
  await loadMajors()
  loadGraph()
})
</script>

<style scoped>
.kg-view {
  padding: 20px;
  max-width: 1200px;
}

.page-header {
  margin-bottom: 20px;
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

.toolbar {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 14px 18px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.toolbar-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-spacer {
  flex: 1;
}

.stat-text {
  font-size: 13px;
  color: var(--text-muted);
  white-space: nowrap;
}

.legend-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-muted);
}

.legend-title {
  font-weight: 600;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.line {
  width: 22px;
  height: 0;
  border-top: 2px solid #64748b;
  display: inline-block;
}

.line.dashed { border-top-style: dashed; }
.line.dotted { border-top-style: dotted; }

.legend-tip {
  opacity: 0.85;
}

.graph-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
}

.detail-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.detail-desc {
  font-size: 14px;
  color: var(--text-muted);
  line-height: 1.7;
  margin: 0 0 14px;
}

.detail-questions {
  border-top: 1px dashed var(--border-color);
  padding-top: 12px;
  min-height: 40px;
}

.dq-head {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.dq-item {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 5px 0;
}

.q-type {
  font-size: 11px;
  color: #06b6d4;
  background: rgba(6, 182, 212, 0.1);
  border-radius: 4px;
  padding: 1px 6px;
  flex-shrink: 0;
}

.q-content {
  font-size: 13px;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.dq-more {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.dq-empty {
  font-size: 13px;
  color: var(--text-muted);
}

.edge-flow {
  display: flex;
  align-items: center;
  gap: 14px;
  justify-content: center;
  margin-bottom: 14px;
}

.edge-node {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 10px;
  background: linear-gradient(135deg, rgba(6, 182, 212, 0.08), rgba(8, 145, 178, 0.04));
  border: 1px solid rgba(6, 182, 212, 0.25);
  border-radius: 10px;
}

.edge-node-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  text-align: center;
}

.edge-node-role {
  font-size: 11px;
  color: var(--text-muted);
}

.edge-arrow {
  flex-shrink: 0;
}

.form-hint {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}
</style>
