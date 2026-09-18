<template>
  <div class="study-plan">
    <div class="page-header">
      <div>
        <h1>学习计划</h1>
        <p class="subtitle">目标拆解 · 时间追踪 · 答题自动核销</p>
      </div>
      <div class="header-actions">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="card">卡片</el-radio-button>
          <el-radio-button value="gantt">甘特</el-radio-button>
        </el-radio-group>
        <el-button @click="openFromPath">
          <el-icon style="margin-right: 4px"><Download /></el-icon>从学习路径导入
        </el-button>
        <el-button type="primary" @click="showDialog()">+ 新建计划</el-button>
      </div>
    </div>

    <!-- 统计条 -->
    <div class="stat-bar">
      <div class="stat-cell">
        <span class="num">{{ stats.active }}</span><span class="lab">进行中计划</span>
      </div>
      <div class="stat-cell">
        <span class="num">{{ stats.todo }}</span><span class="lab">待完成任务</span>
      </div>
      <div class="stat-cell accent">
        <span class="num">{{ stats.weekDone }}</span><span class="lab">近 7 天完成</span>
      </div>
      <div class="stat-cell" :class="{ danger: stats.overdue > 0 }">
        <span class="num">{{ stats.overdue }}</span><span class="lab">逾期任务</span>
      </div>
    </div>

    <el-empty v-if="plans.length === 0 && !loading" description="还没有学习计划：新建一个目标，试试用 AI 一键拆解任务">
      <el-button type="primary" @click="showDialog()">+ 新建计划</el-button>
    </el-empty>

    <!-- ══ 甘特视图 ══ -->
    <div v-else-if="viewMode === 'gantt'" class="gantt-panel">
      <template v-if="gantt.rows.length">
        <div class="gantt-legend">
          <span><i class="lg lg-time"></i>时间跨度</span>
          <span><i class="lg lg-done"></i>任务完成</span>
          <span><i class="lg lg-today"></i>今天</span>
        </div>
        <div v-for="g in gantt.rows" :key="g.id" class="gantt-row">
          <div class="g-label" :title="g.title">
            {{ g.title }}
            <el-tag v-if="g.lagging" size="small" type="danger" effect="plain">落后</el-tag>
          </div>
          <div class="g-track">
            <div class="g-bar" :class="{ lag: g.lagging }" :style="{ left: g.left + '%', width: g.width + '%' }">
              <div class="g-fill" :style="{ width: g.progress + '%' }"></div>
            </div>
            <div class="g-today" :style="{ left: gantt.todayPct + '%' }"></div>
          </div>
          <div class="g-pct">{{ Math.round(g.progress) }}%</div>
        </div>
        <div v-if="gantt.unscheduled" class="gantt-tip">{{ gantt.unscheduled }} 个计划未设置日期范围，未显示在时间轴上</div>
      </template>
      <el-empty v-else :image-size="70" description="暂无带日期范围（开始+结束）的计划" />
    </div>

    <!-- ══ 卡片视图 ══ -->
    <div v-else class="plan-grid">
      <div v-for="p in plans" :key="p.id" class="plan-card" :class="'st-' + p.status">
        <div class="plan-header">
          <div class="ph-left">
            <span class="plan-ico">{{ statusIcon(p.status) }}</span>
            <h3>{{ p.title }}</h3>
          </div>
          <div class="plan-header-tags">
            <el-tag v-if="p.overdue_count" size="small" type="danger">逾期 {{ p.overdue_count }}</el-tag>
            <el-tag v-if="p.lagging" size="small" type="danger" effect="plain">进度落后</el-tag>
            <el-tag :type="statusTagType(p.status)" size="small">{{ statusLabel(p.status) }}</el-tag>
          </div>
        </div>
        <p class="plan-desc">{{ p.description || '—' }}</p>

        <!-- 时间轴带：时间进度 vs 完成进度双条对比 -->
        <div v-if="p.time_pct !== null" class="timeline">
          <div class="tl-track">
            <div class="tl-time" :class="{ lag: p.lagging }" :style="{ width: p.time_pct + '%' }"></div>
            <div class="tl-done" :style="{ width: Math.min(100, p.progress) + '%' }"></div>
          </div>
          <div class="tl-labels">
            <span>{{ p.start_date }} ~ {{ p.end_date }}</span>
            <span class="tl-pct">时间 {{ p.time_pct }}% · 完成 {{ Math.round(p.progress) }}%</span>
          </div>
        </div>
        <div v-else class="tl-labels no-range">
          <span class="plan-dates">{{ p.start_date || '未设定' }} ~ {{ p.end_date || '长期' }}</span>
          <el-button size="small" text type="primary" @click="showDialog(p)">补充日期范围</el-button>
        </div>

        <div class="progress-wrap">
          <el-progress
            :percentage="Math.min(100, p.progress)"
            :stroke-width="8"
            :color="p.progress >= 100 ? '#10b981' : '#06b6d4'"
            :format="() => `${p.tasks_done}/${p.tasks_total}`"
          />
          <!-- 近 14 天完成热力点 -->
          <div class="heat" title="近 14 天每天完成的任务数">
            <i v-for="(c, i) in heatCells(p)" :key="i" :class="['heat-cell', 'lv' + c]"></i>
          </div>
        </div>

        <!-- 任务清单（active 计划可拖拽排序） -->
        <div class="task-list">
          <div v-if="p.tasks.length === 0" class="task-empty">
            暂无任务——下方快速添加，或点「✨ AI 拆任务」一键生成
          </div>
          <div
            v-for="t in p.tasks" :key="t.id" class="task-item"
            :class="{ done: t.status === 'done', overdue: t.overdue, dragging: drag && drag.planId === p.id && drag.fromIdx === p.tasks.indexOf(t) }"
            :draggable="p.status === 'active'"
            @dragstart="onDragStart(p, t, $event)"
            @dragover.prevent="onDragOver(p, t)"
            @drop="onDrop(p, t)"
            @dragend="drag = null"
          >
            <span v-if="p.status === 'active'" class="drag-handle">⋮⋮</span>
            <el-checkbox :model-value="t.status === 'done'" @change="toggleTask(p, t)" />
            <div class="task-body">
              <span class="task-title">
                <span class="type-ico">{{ typeIcon(t.task_type) }}</span>
                {{ t.title }}
                <el-tag v-if="t.auto_done" size="small" type="success" effect="plain" class="auto-badge">自动</el-tag>
              </span>
              <span class="task-meta">
                <span v-if="t.estimated_minutes" class="task-minutes">{{ t.estimated_minutes }} 分钟</span>
                <el-date-picker
                  :model-value="t.due_date" type="date" size="small" value-format="YYYY-MM-DD"
                  placeholder="截止日" class="due-picker" :class="{ 'due-over': t.overdue }"
                  :clearable="true" @update:model-value="(v) => setTaskDue(p, t, v)"
                />
              </span>
              <!-- 刷题任务：答题自动核销进度 -->
              <div v-if="t.task_type === 'practice' && t.question_count && t.status !== 'done'" class="task-progress">
                <el-progress
                  :percentage="Math.min(100, Math.round((t.progress_count || 0) / t.question_count * 100))"
                  :stroke-width="6" :show-label="false" color="#06b6d4" style="flex: 1"
                />
                <span class="progress-num">{{ t.progress_count || 0 }}/{{ t.question_count }} 题</span>
              </div>
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
          <el-date-picker v-model="newTaskDue" type="date" size="small" value-format="YYYY-MM-DD"
            placeholder="截止日" style="width: 130px" />
          <el-button size="small" type="primary" plain @click="addTask(p)">添加</el-button>
        </div>

        <div class="plan-actions">
          <el-button size="small" type="warning" plain :loading="aiLoadingId === p.id" @click="aiForPlan(p)">
            ✨ AI 拆任务
          </el-button>
          <el-button size="small" v-if="p.status !== 'completed'" @click="toggleStatus(p)">
            {{ p.status === 'paused' ? '恢复' : '暂停' }}
          </el-button>
          <el-button size="small" @click="showDialog(p)">编辑</el-button>
          <el-button size="small" type="danger" @click="removePlan(p)">删除</el-button>
        </div>
      </div>
    </div>

    <!-- 创建/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑计划' : '新建学习计划'" width="560px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" placeholder="如：两周攻克数据结构基础" maxlength="100" />
        </el-form-item>
        <el-form-item label="目标描述">
          <el-input v-model="form.description" type="textarea" :rows="2"
            placeholder="想达成什么？写具体点，AI 拆解更准（可留空）" />
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
      </el-form>

      <!-- 新建时：AI 生成任务建议 → 勾选随计划一并创建 -->
      <template v-if="!editing">
        <div class="ai-gen-row">
          <el-button type="warning" plain :loading="formAiLoading" @click="aiForForm">
            ✨ AI 帮我拆解任务
          </el-button>
          <span v-if="!formTasks.length" class="form-hint-inline">输入目标后一键拆解，勾选即随计划创建</span>
        </div>
        <div v-if="formTasks.length" class="ai-task-list">
          <div class="ai-list-head">
            <el-checkbox v-model="formAllPicked" :indeterminate="formPicked.length < formTasks.length"
              @change="toggleFormAll">全选（{{ formPicked.length }}/{{ formTasks.length }}）</el-checkbox>
            <el-tag size="small" :type="formAiSource === 'ai' ? 'success' : 'info'" effect="plain">
              {{ formAiSource === 'ai' ? 'AI 生成' : '规则生成' }}
            </el-tag>
          </div>
          <el-checkbox-group v-model="formPicked">
            <div v-for="(t, i) in formTasks" :key="i" class="ai-task-item">
              <el-checkbox :value="i">
                <span class="type-ico">{{ typeIcon(t.task_type) }}</span>
                {{ t.title }}
                <span class="ai-sub">{{ t.estimated_minutes || 30 }} 分钟<template v-if="t.due_date"> · 截止 {{ t.due_date }}</template></span>
              </el-checkbox>
            </div>
          </el-checkbox-group>
        </div>
      </template>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 卡片入口：AI 拆任务建议弹窗 -->
    <el-dialog v-model="aiDlg" title="AI 任务建议" width="540px">
      <div class="ai-basis">
        <el-tag size="small" :type="aiDlgSource === 'ai' ? 'success' : 'info'" effect="plain">
          {{ aiDlgSource === 'ai' ? 'AI 生成' : '规则兜底' }}
        </el-tag>
        <span>{{ aiDlgBasis }}</span>
      </div>
      <div class="ai-list-head" style="margin-top: 10px">
        <el-checkbox v-model="aiAllPicked" :indeterminate="aiPicked.length < aiTasks.length"
          @change="toggleAiAll">全选（{{ aiPicked.length }}/{{ aiTasks.length }}）</el-checkbox>
      </div>
      <el-checkbox-group v-model="aiPicked" class="ai-check-group">
        <div v-for="(t, i) in aiTasks" :key="i" class="ai-task-item">
          <el-checkbox :value="i">
            <span class="type-ico">{{ typeIcon(t.task_type) }}</span>
            {{ t.title }}
            <span class="ai-sub">{{ t.estimated_minutes || 30 }} 分钟<template v-if="t.due_date"> · 截止 {{ t.due_date }}</template></span>
          </el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="aiDlg = false">取消</el-button>
        <el-button type="primary" :loading="aiAdopting" :disabled="!aiPicked.length" @click="adoptAiTasks">
          采纳 {{ aiPicked.length }} 条入库
        </el-button>
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
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()

const plans = ref([])
const loading = ref(false)
const viewMode = ref('card')          // card / gantt
const dialogVisible = ref(false)
const editing = ref(null)
const dateRange = ref([])
const form = ref({ title: '', description: '', start_date: null, end_date: null })

// 新建弹窗内的 AI 拆解
const formTasks = ref([])
const formPicked = ref([])
const formAllPicked = ref(true)
const formAiLoading = ref(false)
const formAiSource = ref('rule')

// 卡片入口的 AI 拆解弹窗
const aiDlg = ref(false)
const aiDlgPlan = ref(null)
const aiTasks = ref([])
const aiPicked = ref([])
const aiAllPicked = ref(true)
const aiLoadingId = ref(null)
const aiAdopting = ref(false)
const aiDlgBasis = ref('')
const aiDlgSource = ref('rule')

// 行内加任务
const newTaskTitle = ref('')
const newTaskMinutes = ref(30)
const newTaskDue = ref(null)

// 拖拽排序
const drag = ref(null)   // { planId, fromIdx }

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
function statusIcon(s) { return { active: '🎯', paused: '⏸️', completed: '✅' }[s] || '📋' }
function typeIcon(t) { return { knowledge_point: '📖', practice: '✏️', resource: '🎥', custom: '📌' }[t] || '📌' }
function taskLabel(t) { return { knowledge_point: '知识点', resource: '资源', practice: '刷题', custom: '任务' }[t] || t }
function formatMinutes(min) {
  if (!min) return '0 分钟'
  if (min < 60) return `${min} 分钟`
  return `${Math.round(min / 60 * 10) / 10} 小时`
}

const stats = computed(() => {
  let active = 0, todo = 0, weekDone = 0, overdue = 0
  const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 6)
  const cutoffKey = localDateKey(cutoff)
  for (const p of plans.value) {
    if (p.status === 'active') {
      active += 1
      todo += (p.tasks_total - p.tasks_done)
    }
    overdue += p.overdue_count || 0
    for (const [day, n] of Object.entries(p.heat || {})) {
      if (day >= cutoffKey) weekDone += n
    }
  }
  return { active, todo, weekDone, overdue }
})

// ── 甘特视图数据：全局时间范围内每计划一根横条 ──
const gantt = computed(() => {
  const dated = plans.value.filter(p => p.start_date && p.end_date)
  const undated = plans.value.length - dated.length
  if (!dated.length) return { rows: [], todayPct: 0, unscheduled: undated }
  let min = dated[0].start_date, max = dated[0].end_date
  for (const p of dated) {
    if (p.start_date < min) min = p.start_date
    if (p.end_date > max) max = p.end_date
  }
  const today = localDateKey(new Date())
  if (today < min) min = today
  if (today > max) max = today
  const span = Math.max((new Date(max) - new Date(min)) / 86400000, 1)
  const pos = d => ((new Date(d) - new Date(min)) / 86400000) / span * 100
  return {
    rows: dated.map(p => ({
      id: p.id, title: p.title, lagging: p.lagging, progress: p.progress || 0,
      left: pos(p.start_date), width: Math.max(pos(p.end_date) - pos(p.start_date), 1.5),
    })),
    todayPct: pos(today),
    unscheduled: undated,
  }
})

function localDateKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// 近 14 天热力点：0/1/2/3+ 四档
function heatCells(p) {
  const cells = []
  const today = new Date()
  for (let i = 13; i >= 0; i--) {
    const d = new Date(today); d.setDate(d.getDate() - i)
    cells.push(Math.min(p.heat?.[localDateKey(d)] || 0, 3))
  }
  return cells
}

async function load() {
  loading.value = true
  const prevStatus = {}
  for (const p of plans.value) prevStatus[p.id] = p.status
  try {
    const res = await request.get('/api/learning/plans')
    plans.value = res.data || []
    // active → completed 的新流转触发庆祝
    const newly = plans.value.filter(p => p.status === 'completed' && prevStatus[p.id] && prevStatus[p.id] !== 'completed')
    if (newly.length) celebrate(newly[0].title)
  } catch (e) {}
  loading.value = false
}

// ── 完成庆祝：彩色粒子雨 ──
function celebrate(title) {
  ElMessage.success({ message: `🎉 恭喜完成计划「${title}」！`, duration: 3500 })
  const box = document.createElement('div')
  box.className = 'confetti-box'
  const colors = ['#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#3b82f6']
  for (let i = 0; i < 36; i++) {
    const s = document.createElement('i')
    s.style.left = Math.random() * 100 + 'vw'
    s.style.background = colors[i % colors.length]
    s.style.animationDelay = (Math.random() * 0.5) + 's'
    s.style.animationDuration = (1.3 + Math.random() * 1.2) + 's'
    s.style.transform = `rotate(${Math.random() * 360}deg)`
    box.appendChild(s)
  }
  document.body.appendChild(box)
  setTimeout(() => box.remove(), 3000)
}

function showDialog(p = null) {
  editing.value = p
  formTasks.value = []
  formPicked.value = []
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
      const res = await request.post('/api/learning/plans', payload)
      const planId = res.data?.id
      // 勾选的 AI 建议任务随新计划一并入库
      if (planId && formPicked.value.length) {
        const items = formPicked.value.map(i => formTasks.value[i])
        await request.post(`/api/learning/plans/${planId}/tasks/batch`, { items })
        ElMessage.success(`已创建计划并采纳 ${items.length} 个任务`)
      } else {
        ElMessage.success('已创建，来添加第一个任务吧')
      }
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
      due_date: newTaskDue.value || undefined,
    })
    newTaskTitle.value = ''
    newTaskMinutes.value = 30
    newTaskDue.value = null
    load()
  } catch (e) {}
}

async function toggleTask(p, t) {
  try {
    const res = await request.put(`/api/learning/plans/${p.id}/tasks/${t.id}`, {
      status: t.status === 'done' ? 'pending' : 'done',
    })
    ElMessage.success(res.data?.message || '已更新')
    if (res.data?.plan_status === 'completed' && p.status !== 'completed') celebrate(p.title)
    load()
  } catch (e) {}
}

async function setTaskDue(p, t, val) {
  try {
    await request.put(`/api/learning/plans/${p.id}/tasks/${t.id}`, { due_date: val || null })
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

// ── 拖拽排序（active 计划，前端即时移动 + 后端落库） ──
function onDragStart(p, t) {
  drag.value = { planId: p.id, fromIdx: p.tasks.indexOf(t) }
}
function onDragOver(p, t) {
  if (!drag.value || drag.value.planId !== p.id) return
  const from = drag.value.fromIdx
  const to = p.tasks.indexOf(t)
  if (from === to) return
  const arr = p.tasks.slice()
  arr.splice(from, 1)
  arr.splice(to, 0, p.tasks[drag.value.fromIdx])
  p.tasks = arr
  drag.value.fromIdx = to
}
async function onDrop(p) {
  if (!drag.value || drag.value.planId !== p.id) return
  drag.value = null
  try {
    await request.post(`/api/learning/plans/${p.id}/tasks/reorder`, {
      task_ids: p.tasks.map(t => t.id),
    })
  } catch (e) { load() }
}

// ── AI 拆任务 ──
async function suggestTasks(title, description, startDate, endDate) {
  const res = await request.post('/api/learning/plans/ai-suggest-tasks', {
    title, description, start_date: startDate || undefined, end_date: endDate || undefined,
  })
  return res.data || {}
}

async function aiForForm() {
  if (!form.value.title.trim() && !form.value.description.trim()) {
    ElMessage.warning('先写个标题或目标描述，AI 拆得更准'); return
  }
  formAiLoading.value = true
  try {
    const d = await suggestTasks(form.value.title, form.value.description, dateRange.value?.[0], dateRange.value?.[1])
    formTasks.value = d.tasks || []
    formPicked.value = formTasks.value.map((_, i) => i)
    formAllPicked.value = true
    formAiSource.value = d.source || 'rule'
  } catch (e) {}
  formAiLoading.value = false
}
function toggleFormAll(v) {
  formPicked.value = v ? formTasks.value.map((_, i) => i) : []
}

async function aiForPlan(p) {
  aiLoadingId.value = p.id
  try {
    const d = await suggestTasks(p.title, p.description, p.start_date, p.end_date)
    aiDlgPlan.value = p
    aiTasks.value = d.tasks || []
    aiPicked.value = aiTasks.value.map((_, i) => i)
    aiAllPicked.value = true
    aiDlgBasis.value = d.basis || ''
    aiDlgSource.value = d.source || 'rule'
    aiDlg.value = true
  } catch (e) {}
  aiLoadingId.value = null
}
function toggleAiAll(v) {
  aiPicked.value = v ? aiTasks.value.map((_, i) => i) : []
}

async function adoptAiTasks() {
  const p = aiDlgPlan.value
  if (!p) return
  aiAdopting.value = true
  try {
    const items = aiPicked.value.map(i => aiTasks.value[i])
    const res = await request.post(`/api/learning/plans/${p.id}/tasks/batch`, { items })
    ElMessage.success(`已采纳 ${res.data?.added ?? items.length} 条任务`)
    aiDlg.value = false
    load()
  } catch (e) {}
  aiAdopting.value = false
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
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-header h1 { font-size: 22px; margin: 0 0 4px; color: var(--text-primary); }
.subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }
.header-actions { display: flex; gap: 10px; align-items: center; }

/* 统计条 */
.stat-bar { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 18px; }
.stat-cell {
  background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 10px;
  padding: 12px 16px; display: flex; flex-direction: column; gap: 2px;
}
.stat-cell .num { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.stat-cell .lab { font-size: 12px; color: var(--text-muted); }
.stat-cell.accent .num { color: #06b6d4; }
.stat-cell.danger .num { color: #ef4444; }

.plan-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); gap: 16px; }

.plan-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 18px 20px; position: relative; overflow: hidden;
}
/* 左侧状态色条 */
.plan-card::before {
  content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
}
.plan-card.st-active::before { background: linear-gradient(180deg, #06b6d4, #3b82f6); }
.plan-card.st-paused::before { background: #94a3b8; }
.plan-card.st-completed::before { background: #10b981; }

.plan-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.ph-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.plan-ico { font-size: 16px; }
.plan-header h3 { font-size: 16px; margin: 0; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plan-header-tags { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
.plan-desc { font-size: 13px; color: var(--text-muted); margin: 0 0 10px; }

/* 时间轴带 */
.timeline { margin-bottom: 10px; }
.tl-track {
  position: relative; height: 8px; border-radius: 5px; overflow: hidden;
  background: var(--bg-tertiary, rgba(100, 116, 139, 0.15));
}
.tl-time { position: absolute; left: 0; top: 0; bottom: 0; background: rgba(148, 163, 184, 0.45); }
.tl-time.lag { background: rgba(239, 68, 68, 0.4); }
.tl-done { position: absolute; left: 0; top: 0; bottom: 0; background: linear-gradient(90deg, #06b6d4, #10b981); border-radius: 5px; }
.tl-labels { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted); margin-top: 4px; }
.tl-labels.no-range { justify-content: space-between; align-items: center; }
.tl-pct { font-variant-numeric: tabular-nums; }
.plan-meta { display: flex; gap: 14px; align-items: center; margin-bottom: 12px; }
.plan-dates { font-size: 12px; color: var(--text-muted); }
.plan-meta span { font-size: 12px; color: var(--text-muted); }

.progress-wrap { margin-bottom: 12px; display: flex; align-items: center; gap: 12px; }
.progress-wrap .el-progress { flex: 1; }

/* 热力点 */
.heat { display: flex; gap: 3px; flex-shrink: 0; }
.heat-cell { width: 8px; height: 8px; border-radius: 2px; background: var(--bg-tertiary, rgba(100, 116, 139, 0.18)); }
.heat-cell.lv1 { background: #67e8f9; }
.heat-cell.lv2 { background: #06b6d4; }
.heat-cell.lv3 { background: #0e7490; }

.task-list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.task-empty { font-size: 12px; color: var(--text-muted); text-align: center; padding: 10px 0; }
.task-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: 8px; transition: background 0.15s;
  border: 1px dashed transparent;
}
.task-item:hover { background: var(--bg-hover, rgba(6, 182, 212, 0.06)); }
.task-item.done .task-title { text-decoration: line-through; color: var(--text-muted); }
.task-item.overdue:not(.done) { background: rgba(239, 68, 68, 0.06); }
.task-item.overdue:not(.done) .task-title { color: #ef4444; }
.task-item.dragging { opacity: 0.5; border: 1px dashed #06b6d4; }
.drag-handle { cursor: grab; color: var(--text-muted); font-size: 12px; user-select: none; opacity: 0.55; }
.drag-handle:active { cursor: grabbing; }
.task-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.task-title { font-size: 13px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.type-ico { margin-right: 4px; }
.auto-badge { margin-left: 6px; vertical-align: middle; }
.task-meta { display: flex; gap: 6px; align-items: center; }
.task-minutes { font-size: 11px; color: var(--text-muted); }
.task-progress { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
.task-progress .progress-num { font-size: 11px; color: var(--text-muted); white-space: nowrap; }

/* 任务行内截止日选择器：平时压缩显示 */
.due-picker { width: 118px !important; }
.due-picker :deep(.el-input__wrapper) { box-shadow: none; background: transparent; padding: 0 6px; }
.due-picker :deep(.el-input__inner) { font-size: 11px; color: var(--text-muted); }
.due-picker.due-over :deep(.el-input__inner) { color: #ef4444; font-weight: 600; }
.due-picker:hover :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px var(--border-color) inset; }

.add-task-row { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.add-task-row .el-input { flex: 1; min-width: 140px; }

.plan-actions { display: flex; gap: 8px; }

.form-hint { font-size: 12px; color: var(--text-muted); margin: 0 0 8px 80px; }
.ai-gen-row { display: flex; align-items: center; gap: 12px; margin: 4px 0 10px 80px; }
.form-hint-inline { font-size: 12px; color: var(--text-muted); }

/* AI 建议清单 */
.ai-task-list { margin: 0 0 8px 80px; border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 12px; max-height: 260px; overflow-y: auto; }
.ai-list-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.ai-check-group { display: flex; flex-direction: column; }
.ai-task-item { padding: 4px 0; border-bottom: 1px dashed var(--border-color, #e5e7eb); }
.ai-task-item:last-child { border-bottom: none; }
.ai-sub { font-size: 11px; color: var(--text-muted); margin-left: 6px; }
.ai-basis { display: flex; gap: 8px; align-items: flex-start; font-size: 12px; color: var(--text-muted); background: var(--bg-tertiary, rgba(100,116,139,.08)); border-radius: 8px; padding: 8px 12px; }

/* 甘特视图 */
.gantt-panel { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; padding: 18px 20px; }
.gantt-legend { display: flex; gap: 18px; font-size: 12px; color: var(--text-muted); margin-bottom: 14px; }
.gantt-legend .lg { display: inline-block; width: 14px; height: 8px; border-radius: 4px; margin-right: 5px; vertical-align: middle; }
.lg-time { background: rgba(148, 163, 184, 0.55); }
.lg-done { background: linear-gradient(90deg, #06b6d4, #10b981); }
.lg-today { background: #f59e0b; width: 3px !important; height: 12px !important; }
.gantt-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.g-label { width: 180px; flex-shrink: 0; font-size: 13px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: flex; gap: 6px; align-items: center; }
.g-track { position: relative; flex: 1; height: 20px; background: var(--bg-tertiary, rgba(100,116,139,.08)); border-radius: 6px; }
.g-bar { position: absolute; top: 3px; bottom: 3px; background: rgba(148, 163, 184, 0.5); border-radius: 5px; overflow: hidden; min-width: 6px; }
.g-bar.lag { background: rgba(239, 68, 68, 0.45); }
.g-fill { height: 100%; background: linear-gradient(90deg, #06b6d4, #10b981); border-radius: 5px; }
.g-today { position: absolute; top: -2px; bottom: -2px; width: 2px; background: #f59e0b; }
.g-pct { width: 44px; text-align: right; font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.gantt-tip { font-size: 12px; color: var(--text-muted); margin-top: 6px; }

.node-check-list { width: 100%; max-height: 260px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 12px; }
.node-check-item { margin-bottom: 4px; }
.node-check-item :deep(.el-checkbox__label) { font-size: 13px; }
</style>

<style>
/* 完成庆祝粒子雨（动态挂到 body，需全局样式） */
.confetti-box { position: fixed; inset: 0; pointer-events: none; z-index: 3000; overflow: hidden; }
.confetti-box i {
  position: absolute; top: -12px; width: 8px; height: 14px; border-radius: 2px;
  animation: confetti-fall linear forwards;
}
@keyframes confetti-fall {
  0% { transform: translateY(-2vh) rotate(0deg); opacity: 1; }
  100% { transform: translateY(105vh) rotate(720deg); opacity: 0.6; }
}
</style>
