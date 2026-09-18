<template>
  <div class="study-plan">
    <div class="page-header">
      <div>
        <h1>学习计划</h1>
        <p class="subtitle">计划由具体任务组成，完成一项勾选一项</p>
      </div>
      <div class="header-actions">
        <el-button @click="openFromPath">
          <el-icon style="margin-right: 4px"><Download /></el-icon>从学习路径导入
        </el-button>
        <el-button type="primary" @click="showDialog()">+ 新建计划</el-button>
      </div>
    </div>

    <el-empty v-if="plans.length === 0 && !loading" description="还没有学习计划，创建一个开始吧" />

    <div class="plan-grid">
      <div v-for="p in plans" :key="p.id" class="plan-card">
        <div class="plan-header">
          <h3>{{ p.title }}</h3>
          <el-tag :type="statusTagType(p.status)" size="small">{{ statusLabel(p.status) }}</el-tag>
        </div>
        <p class="plan-desc">{{ p.description || '—' }}</p>

        <div class="plan-meta">
          <span class="plan-dates">{{ p.start_date }} ~ {{ p.end_date || '长期' }}</span>
          <span>约 {{ formatMinutes(p.total_minutes) }}</span>
        </div>

        <div class="progress-wrap">
          <el-progress
            :percentage="Math.min(100, p.progress)"
            :stroke-width="8"
            :color="p.progress >= 100 ? '#10b981' : '#06b6d4'"
            :format="() => `${p.tasks_done}/${p.tasks_total}`"
          />
        </div>

        <!-- 任务清单 -->
        <div class="task-list">
          <div v-if="p.tasks.length === 0" class="task-empty">暂无任务，在下方添加或从路径导入</div>
          <div v-for="t in p.tasks" :key="t.id" class="task-item" :class="{ done: t.status === 'done' }">
            <el-checkbox
              :model-value="t.status === 'done'"
              @change="toggleTask(p, t)"
            />
            <div class="task-body">
              <span class="task-title">{{ t.title }}</span>
              <span class="task-meta">
                <el-tag size="small" effect="plain" :type="taskTagType(t.task_type)">{{ taskLabel(t.task_type) }}</el-tag>
                <span v-if="t.estimated_minutes" class="task-minutes">{{ t.estimated_minutes }} 分钟</span>
              </span>
            </div>
            <el-button
              v-if="t.knowledge_point_id" size="small" text type="primary"
              :loading="practicingTaskId === t.id" @click="goPractice(t)"
            >去练习</el-button>
            <el-button size="small" text type="danger" @click="removeTask(p, t)">删除</el-button>
          </div>
        </div>

        <!-- 行内加任务 -->
        <div class="add-task-row">
          <el-input
            v-model="newTaskTitle" size="small" placeholder="添加任务，如：看完第 3 章视频"
            maxlength="200" @keyup.enter="addTask(p)"
          />
          <el-input-number v-model="newTaskMinutes" size="small" :min="5" :max="600" :step="5" style="width: 105px" />
          <el-button size="small" type="primary" plain @click="addTask(p)">添加</el-button>
        </div>

        <div class="plan-actions">
          <el-button size="small" v-if="p.status !== 'completed'" @click="toggleStatus(p)">
            {{ p.status === 'paused' ? '恢复' : '暂停' }}
          </el-button>
          <el-button size="small" @click="showDialog(p)">编辑</el-button>
          <el-button size="small" type="danger" @click="removePlan(p)">删除</el-button>
        </div>
      </div>
    </div>

    <!-- 创建/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑计划' : '新建学习计划'" width="520px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="如：两周攻克数据结构基础" maxlength="100" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="这个计划要达成什么（可留空）" />
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
      </el-form>
      <div class="form-hint">创建后可在计划卡片中添加具体任务，或从学习路径一键导入任务清单</div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 从学习路径导入弹窗 -->
    <el-dialog v-model="pathDlg" title="从学习路径导入计划" width="560px" :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="选择路径" required>
          <el-select
            v-model="importPathId" filterable placeholder="选择学习路径"
            style="width: 100%" :loading="loadingPaths" @change="onImportPathChange"
          >
            <el-option
              v-for="pt in importPaths" :key="pt.id"
              :label="pt.title" :value="pt.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="计划标题">
          <el-input v-model="importTitle" placeholder="留空则默认为「路径计划：xxx」" maxlength="100" />
        </el-form-item>
        <el-form-item v-if="importNodes.length" label="选择节点">
          <div class="node-check-list">
            <el-checkbox
              :model-value="importNodeIds.length === importNodes.length"
              :indeterminate="importNodeIds.length > 0 && importNodeIds.length < importNodes.length"
              @change="toggleAllNodes"
            >全选（{{ importNodes.length }} 个节点）</el-checkbox>
            <el-checkbox-group v-model="importNodeIds">
              <div v-for="(n, i) in importNodes" :key="n.id" class="node-check-item">
                <el-checkbox :value="n.id">{{ i + 1 }}. {{ n.title }}（约 {{ n.estimated_minutes || 30 }} 分钟）</el-checkbox>
              </div>
            </el-checkbox-group>
          </div>
        </el-form-item>
      </el-form>
      <div v-if="importPathId" class="form-hint">每个节点将生成一个任务：学该知识点 + 配套练习 5 题，可打卡推进</div>
      <template #footer>
        <el-button @click="pathDlg = false">取消</el-button>
        <el-button type="primary" :loading="importing" :disabled="!importPathId || importNodeIds.length === 0" @click="doImport">
          生成计划
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()

const plans = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const dateRange = ref([])
const form = ref({ title: '', description: '', start_date: null, end_date: null })

// 行内加任务
const newTaskTitle = ref('')
const newTaskMinutes = ref(30)

// 从路径导入
const pathDlg = ref(false)
const importPaths = ref([])
const importPathId = ref(null)
const importNodes = ref([])
const importNodeIds = ref([])
const importTitle = ref('')
const loadingPaths = ref(false)
const importing = ref(false)

// 去练习
const practicingTaskId = ref(null)

function statusLabel(s) { return { active: '进行中', paused: '已暂停', completed: '已完成' }[s] || s }
function statusTagType(s) { return { active: 'success', paused: 'info', completed: '' }[s] || '' }
function taskLabel(t) { return { knowledge_point: '知识点', resource: '资源', practice: '刷题', custom: '任务' }[t] || t }
function taskTagType(t) { return { knowledge_point: 'success', resource: 'warning', practice: '', custom: 'info' }[t] || 'info' }
function formatMinutes(min) {
  if (!min) return '0 分钟'
  if (min < 60) return `${min} 分钟`
  return `${Math.round(min / 60 * 10) / 10} 小时`
}

async function load() {
  loading.value = true
  try {
    const res = await request.get('/api/learning/plans')
    plans.value = res.data || []
  } catch (e) {}
  loading.value = false
}

function showDialog(p = null) {
  editing.value = p
  if (p) {
    form.value = { title: p.title, description: p.description, start_date: p.start_date, end_date: p.end_date }
    dateRange.value = p.end_date ? [p.start_date, p.end_date] : [p.start_date, null]
  } else {
    form.value = { title: '', description: '', start_date: null, end_date: null }
    dateRange.value = []
  }
  dialogVisible.value = true
}

async function save() {
  if (!form.value.title.trim()) { ElMessage.warning('请填写标题'); return }
  const start = dateRange.value?.[0] || new Date().toISOString().slice(0, 10)
  const end = dateRange.value?.[1] || null
  const payload = { ...form.value, start_date: start, end_date: end }
  try {
    if (editing.value) {
      await request.put(`/api/learning/plans/${editing.value.id}`, payload)
      ElMessage.success('已更新')
    } else {
      await request.post('/api/learning/plans', payload)
      ElMessage.success('已创建，来添加第一个任务吧')
    }
    dialogVisible.value = false
    load()
  } catch (e) {}
}

async function toggleStatus(p) {
  try {
    await request.post(`/api/learning/plans/${p.id}/pause`)
    ElMessage.success('已更新')
    load()
  } catch (e) {}
}

async function removePlan(p) {
  await ElMessageBox.confirm(`确定删除计划「${p.title}」？任务清单将一并删除。`, '确认')
  try {
    await request.delete(`/api/learning/plans/${p.id}`)
    ElMessage.success('已删除')
    load()
  } catch (e) {}
}

// ── 任务条目 ──
async function addTask(p) {
  const title = newTaskTitle.value.trim()
  if (!title) { ElMessage.warning('请填写任务标题'); return }
  try {
    await request.post(`/api/learning/plans/${p.id}/tasks`, {
      title, task_type: 'custom', estimated_minutes: newTaskMinutes.value,
    })
    newTaskTitle.value = ''
    newTaskMinutes.value = 30
    load()
  } catch (e) {}
}

async function toggleTask(p, t) {
  try {
    const res = await request.put(`/api/learning/plans/${p.id}/tasks/${t.id}`, {
      status: t.status === 'done' ? 'pending' : 'done',
    })
    ElMessage.success(res.data?.message || '已更新')
    load()
  } catch (e) {}
}

async function removeTask(p, t) {
  try {
    await request.delete(`/api/learning/plans/${p.id}/tasks/${t.id}`)
    ElMessage.success('任务已删除')
    load()
  } catch (e) {}
}

// 任务挂知识点：按知识点直接开练习（练习流：start → 跳答题页）
async function goPractice(t) {
  practicingTaskId.value = t.id
  try {
    const res = await request.post('/api/learning/practice/start', {
      title: `计划练习：${t.title}`.slice(0, 80),
      knowledge_point_id: t.knowledge_point_id,
      count: t.question_count || 5,
    })
    router.push(`/learning/practice/${res.data.session_id}`)
  } catch (e) {}
  practicingTaskId.value = null
}

// ── 从学习路径导入 ──
async function openFromPath() {
  pathDlg.value = true
  importPathId.value = null
  importNodes.value = []
  importNodeIds.value = []
  importTitle.value = ''
  loadingPaths.value = true
  try {
    const res = await request.get('/api/learning/paths')
    importPaths.value = (res.data || []).filter(pt => pt.nodes_count > 0)
    if (importPaths.value.length === 0) ElMessage.info('暂无可导入的学习路径（需含节点）')
  } catch (e) {}
  loadingPaths.value = false
}

async function onImportPathChange(pathId) {
  importNodes.value = []
  importNodeIds.value = []
  const pt = importPaths.value.find(x => x.id === pathId)
  if (!pt) return
  try {
    const res = await request.get(`/api/learning/paths/${pathId}`)
    importNodes.value = res.data?.nodes || []
    importNodeIds.value = importNodes.value.map(n => n.id)  // 默认全选
  } catch (e) {}
}

function toggleAllNodes(val) {
  importNodeIds.value = val ? importNodes.value.map(n => n.id) : []
}

async function doImport() {
  importing.value = true
  try {
    const res = await request.post('/api/learning/plans/from-path', {
      path_id: importPathId.value,
      node_ids: importNodeIds.value,
      title: importTitle.value.trim() || undefined,
    })
    ElMessage.success(`已生成计划，共 ${res.data.tasks_created} 个任务`)
    pathDlg.value = false
    load()
  } catch (e) {}
  importing.value = false
}

onMounted(load)
</script>

<style scoped>
.study-plan { padding: 20px; max-width: 1100px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-header h1 { font-size: 22px; margin: 0 0 4px; color: var(--text-primary); }
.subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }
.header-actions { display: flex; gap: 10px; }

.plan-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 16px; }

.plan-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 18px 20px;
}
.plan-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.plan-header h3 { font-size: 16px; margin: 0; color: var(--text-primary); }
.plan-desc { font-size: 13px; color: var(--text-muted); margin: 0 0 10px; }
.plan-meta { display: flex; gap: 14px; align-items: center; margin-bottom: 12px; }
.plan-dates { font-size: 12px; color: var(--text-muted); }
.plan-meta span { font-size: 12px; color: var(--text-muted); }

.progress-wrap { margin-bottom: 12px; }

.task-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.task-empty { font-size: 12px; color: var(--text-muted); text-align: center; padding: 10px 0; }
.task-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 8px; transition: background 0.15s;
}
.task-item:hover { background: var(--bg-hover, rgba(6, 182, 212, 0.06)); }
.task-item.done .task-title { text-decoration: line-through; color: var(--text-muted); }
.task-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.task-title { font-size: 13px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { display: flex; gap: 6px; align-items: center; }
.task-minutes { font-size: 11px; color: var(--text-muted); }

.add-task-row { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.add-task-row .el-input { flex: 1; }

.plan-actions { display: flex; gap: 8px; }

.form-hint { font-size: 12px; color: var(--text-muted); margin: 0 0 8px 80px; }

.node-check-list { width: 100%; max-height: 260px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 12px; }
.node-check-item { margin-bottom: 4px; }
.node-check-item :deep(.el-checkbox__label) { font-size: 13px; }
</style>
