<template>
  <div class="study-plan-workbench">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习规划</h1>
        <p class="page-subtitle">自定义学习主题 · AI 生成计划与建议 · 确认后一键应用为你的学习计划</p>
      </div>
      <el-radio-group v-model="mode" class="mode-switch">
        <el-radio-button value="free">自由主题闭环</el-radio-button>
        <el-radio-button value="mounted">基于已有课程</el-radio-button>
      </el-radio-group>
    </div>

    <div v-if="mode === 'free'" class="free-banner">
      <el-icon><MagicStick /></el-icon>
      <div>想学什么都可以，AI 会为你<b>从零生成知识体系</b>，确认后一键同步到 <b>专业路径 + 知识图谱 + 学习计划</b>，任务自动绑定知识点、打通掌握度与错题本，形成完整的自学闭环。</div>
    </div>

    <!-- ① 定义学习目标 -->
    <div class="panel">
      <div class="panel-head">
        <h2><el-icon><EditPen /></el-icon> ① 定义你的学习目标</h2>
      </div>
      <el-form label-position="top" class="goal-form">
        <div class="gf-row">
          <el-form-item :label="mode === 'free' ? '学习主题（想学什么）' : '计划标题'" class="gf-title">
            <el-input v-model="form.title" maxlength="60" show-word-limit :placeholder="mode === 'free' ? '例如：TensorFlow 深度学习入门 / Vue3 / 高中物理必修一' : '例如：两周内攻克数据结构二叉树'" />
          </el-form-item>
          <el-form-item label="学习周期" class="gf-date">
            <el-date-picker
              v-model="form.range"
              type="daterange"
              value-format="YYYY-MM-DD"
              range-separator="至"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              unlink-panels
            />
          </el-form-item>
        </div>
        <el-form-item label="学习目标 / 想掌握的内容（自由描述，越具体拆解越贴合）">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="例如：我是大二学生，想系统复习二叉树的遍历、BST 与平衡树，能独立应对LeetCode中等题，每天大概能学 1 小时"
          />
        </el-form-item>
      </el-form>

      <!-- 可选挂载：课程 → 章节 → 知识点 -->
      <div v-if="mode === 'mounted'" class="attach">
        <div class="attach-title">
          <el-icon><Connection /></el-icon> 可选：从现有课程 / 章节 / 知识点挂载，让计划更贴合你的教材
          <span class="attach-tip">（不挂载也可以，AI 会按你的文字目标拆解）</span>
        </div>
        <div class="attach-row">
          <el-select v-model="selCourseId" placeholder="选择课程" clearable filterable @change="onCourseChange" style="width: 200px">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <el-select v-model="selChapterId" placeholder="选择章节" clearable filterable :disabled="!selCourseId" @change="onChapterChange" style="width: 200px">
            <el-option v-for="ch in chapters" :key="ch.id" :label="ch.name" :value="ch.id" />
          </el-select>
          <el-select v-model="selKpIds" multiple collapse-tags collapse-tags-tooltip placeholder="勾选知识点" clearable :disabled="!selChapterId" style="min-width: 220px; flex: 1">
            <el-option v-for="kp in kpOptions" :key="kp.id" :label="kp.name" :value="kp.id" />
          </el-select>
          <el-button @click="addPickedKps" :disabled="!selKpIds.length">加入挂载 →</el-button>
        </div>
        <div v-if="pickedKps.length" class="picked-tags">
          <span class="pt-label">已挂载 {{ pickedKps.length }} 个知识点：</span>
          <el-tag v-for="k in pickedKps" :key="k.id" closable type="primary" effect="light" @close="removePickedKp(k.id)">{{ k.name }}</el-tag>
        </div>
      </div>

      <div class="gen-bar">
        <el-button type="primary" size="large" :loading="generating" @click="generate">
          <el-icon style="margin-right: 6px"><MagicStick /></el-icon>{{ generating ? 'AI 拆解中…' : 'AI 生成学习计划与建议' }}
        </el-button>
        <span v-if="generating" class="gen-hint gen-hint-live"><el-icon class="is-loading"><Loading /></el-icon> AI 正在拆解目标，约需 30–60 秒，请稍候…</span>
        <span v-else-if="!form.range || form.range.length !== 2" class="gen-hint">未选周期时，默认按未来两个月（八周）拆解</span>
      </div>
    </div>

    <!-- ② AI 生成结果 + 预览 -->
    <div v-if="result" class="panel">
      <div class="basis-bar">
        <div class="bb-main">
          <div class="bb-head">
            <el-icon><MagicStick /></el-icon>
            <b>② AI 已为你拆解 {{ result.tasks.length }} 个任务</b>
            <el-tag size="small" :type="result.source === 'ai' ? 'success' : 'warning'" effect="dark">
              {{ result.source === 'ai' ? 'AI 智能拆解' : '规则兜底拆解' }}
            </el-tag>
            <el-tag size="small" type="info" effect="plain">周期 {{ result.days }} 天</el-tag>
          </div>
          <div class="bb-basis">{{ result.basis }}</div>
          <div class="bb-insight">
            <span>预计总投入 <b>{{ insight.totalMinutes }}</b> 分钟</span>
            <el-divider direction="vertical" />
            <span>覆盖 <b>{{ insight.kpCount }}</b> 个知识点</span>
            <el-divider direction="vertical" />
            <span>平均每 <b>{{ insight.avgGap }}</b> 天一个里程碑</span>
            <el-divider direction="vertical" />
            <span>建议：<b>{{ insight.advice }}</b></span>
          </div>
        </div>
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="list">清单</el-radio-button>
          <el-radio-button value="gantt">甘特</el-radio-button>
        </el-radio-group>
      </div>

      <!-- 清单视图 -->
      <div v-if="viewMode === 'list'" class="list-view">
        <div v-for="grp in groupedTasks" :key="grp.week" class="week-group">
          <div class="week-head">第 {{ grp.week }} 周<span class="wh-range" v-if="grp.range">{{ grp.range }}</span></div>
          <div v-for="t in grp.items" :key="t._key" class="task-card" :class="{ unchecked: !t._checked }">
            <el-checkbox v-model="t._checked" class="tc-check" />
            <div class="tc-body">
              <el-input v-model="t.title" size="small" class="tc-title" maxlength="120" />
              <div class="tc-meta">
                <el-tag size="small" :type="typeMeta(t.task_type).tag" effect="plain">{{ typeMeta(t.task_type).label }}</el-tag>
                <el-date-picker v-model="t.due_date" type="date" value-format="YYYY-MM-DD" size="small" placeholder="截止" class="tc-date" />
                <span class="tc-field">时长
                  <el-input-number v-model="t.estimated_minutes" :min="0" :step="15" size="small" controls-position="right" class="tc-num" />分
                </span>
                <span class="tc-field" v-if="t.task_type === 'knowledge_point' || t.task_type === 'practice'">题量
                  <el-input-number v-model="t.question_count" :min="0" :max="100" size="small" controls-position="right" class="tc-num" />
                </span>
                <el-select v-if="pickedKps.length" v-model="t.knowledge_point_id" size="small" clearable placeholder="绑定知识点" class="tc-kp">
                  <el-option v-for="k in pickedKps" :key="k.id" :label="k.name" :value="k.id" />
                </el-select>
              </div>
            </div>
            <el-button text type="danger" size="small" @click="removeTask(t._key)"><el-icon><Delete /></el-icon></el-button>
          </div>
        </div>
        <div class="list-foot">
          <el-button size="small" @click="addBlankTask"><el-icon style="margin-right: 4px"><Plus /></el-icon>手动加一项</el-button>
          <el-button size="small" @click="toggleAll(true)">全选</el-button>
          <el-button size="small" @click="toggleAll(false)">清空勾选</el-button>
        </div>
      </div>

      <!-- 甘特视图 -->
      <div v-else class="gantt-view">
        <div class="gantt-ruler">
          <span v-for="w in ganttWeeks" :key="w" class="gr-tick">第{{ w }}周</span>
        </div>
        <div v-for="t in result.tasks" :key="'g' + t._key" class="gantt-row" :class="{ unchecked: !t._checked }">
          <div class="g-label" :title="t.title">
            <el-checkbox v-model="t._checked" />
            <span class="gl-text">{{ t.title }}</span>
          </div>
          <div class="g-track">
            <div class="g-dot" :style="{ left: ganttPos(t) + '%' }" :class="'dot-' + t.task_type">
              <span class="gd-tip">{{ t.due_date }}</span>
            </div>
          </div>
        </div>
        <div class="gantt-tip">圆点为该任务截止日在周期中的位置，切换回清单视图可继续编辑；勾选决定「确认应用」采纳哪些。</div>
      </div>

      <!-- 应用操作 -->
      <div class="apply-bar">
        <template v-if="!applied">
          <el-button type="success" size="large" :loading="applying"
            :disabled="mode === 'mounted' ? checkedTasks.length === 0 : !(form.title.trim() || form.description.trim())" @click="apply">
            <el-icon style="margin-right: 6px"><Check /></el-icon>{{ mode === 'free' ? '确认应用 · 生成路径+图谱+学习计划' : `确认应用（已选 ${checkedTasks.length} 项）为我的学习计划` }}
          </el-button>
          <el-button size="large" :disabled="applying" @click="generate">重新生成</el-button>
          <el-button text :disabled="applying" @click="discard">放弃</el-button>
        </template>
        <div v-else class="applied-ok">
          <el-icon color="#10b981" :size="20"><Check /></el-icon>
          <template v-if="appliedMode === 'free'">
            已生成完整自学闭环《{{ appliedTitle }}》：知识图谱 {{ appliedStats.kp }} 个知识点 · {{ appliedStats.edges }} 条关联，学习计划 {{ appliedCount }} 个任务。
          </template>
          <template v-else>已生成学习计划《{{ appliedTitle }}》，写入 {{ appliedCount }} 个任务。</template>
          <el-button v-if="appliedMode === 'free'" type="primary" size="small" text @click="go('/learning/paths/' + appliedPathId)">查看学习路径 →</el-button>
          <el-button v-if="appliedMode === 'free'" size="small" text @click="go('/learning/graph?path_id=' + appliedPathId)">查看知识图谱</el-button>
          <el-button size="small" text @click="go('/learning/plan')">前往学习计划</el-button>
          <el-button size="small" text @click="resetWorkbench">再规划一个</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { EditPen, Connection, MagicStick, Delete, Plus, Check, Loading } from '@element-plus/icons-vue'

const router = useRouter()
const go = (p) => router.push(p)

// ── 表单与挂载选择 ──
const mode = ref('free')   // 'free' 自由主题闭环 | 'mounted' 基于已有课程
const form = reactive({ title: '', description: '', range: [] })
const courses = ref([])
const chapters = ref([])
const kpOptions = ref([])
const selCourseId = ref(null)
const selChapterId = ref(null)
const selKpIds = ref([])
const pickedKps = ref([])   // [{id, name}]

// ── 生成结果 ──
const generating = ref(false)
const applying = ref(false)
const applied = ref(false)
const appliedTitle = ref('')
const appliedCount = ref(0)
const viewMode = ref('list')
const result = ref(null)     // { basis, source, days, tasks: [...] }
const appliedMode = ref('')        // '' | 'free' | 'mounted'
const appliedPathId = ref(null)
const appliedPlanId = ref(null)
const appliedStats = ref({ kp: 0, edges: 0, nodes: 0 })

const typeMeta = (t) => ({
  knowledge_point: { label: '知识点', tag: 'primary' },
  resource: { label: '资料', tag: 'info' },
  practice: { label: '刷题', tag: 'success' },
  custom: { label: '自定义', tag: 'warning' },
}[t] || { label: '自定义', tag: 'warning' })

const checkedTasks = computed(() => (result.value?.tasks || []).filter(t => t._checked))

// 按周分组（相对开始日）
const startDay = computed(() => {
  if (form.range && form.range[0]) return new Date(form.range[0])
  const dates = (result.value?.tasks || []).map(t => t.due_date).filter(Boolean).sort()
  return dates.length ? new Date(dates[0]) : new Date()
})
const groupedTasks = computed(() => {
  const groups = {}
  for (const t of result.value?.tasks || []) {
    const w = t.due_date ? Math.floor(daysFromStart(t.due_date) / 7) + 1 : 1
    ;(groups[w] ||= []).push(t)
  }
  return Object.keys(groups).map(Number).sort((a, b) => a - b).map(week => {
    const items = groups[week]
    const first = items[0]?.due_date
    const last = items[items.length - 1]?.due_date
    return { week, items, range: first ? `${first}${last && last !== first ? ' ~ ' + last : ''}` : '' }
  })
})

function daysFromStart(dateStr) {
  const d = new Date(dateStr)
  return Math.max(0, Math.floor((d - startDay.value) / 86400000))
}

// 甘特：span 取周期或任务覆盖天数
const spanDays = computed(() => {
  if (form.range && form.range[0] && form.range[1]) {
    return Math.max(1, Math.floor((new Date(form.range[1]) - new Date(form.range[0])) / 86400000))
  }
  const ds = (result.value?.tasks || []).map(t => t.due_date).filter(Boolean)
  if (!ds.length) return 56
  return Math.max(1, daysFromStart(ds.sort().slice(-1)[0]))
})
const ganttPos = (t) => t.due_date ? Math.min(98, Math.max(1, daysFromStart(t.due_date) / spanDays.value * 100)) : 50
const ganttWeeks = computed(() => Math.max(1, Math.ceil(spanDays.value / 7)))

// 顶部洞察（纯前端统计，作为「建议与参考」）
const insight = computed(() => {
  const tasks = result.value?.tasks || []
  const totalMinutes = tasks.reduce((s, t) => s + (t.estimated_minutes || 0), 0)
  const kpCount = new Set(tasks.filter(t => t.knowledge_point_id).map(t => t.knowledge_point_id)).size
  const avgGap = tasks.length ? Math.max(1, Math.round(spanDays.value / tasks.length)) : 0
  let advice = '节奏适中，按截止日推进即可'
  if (totalMinutes > 600) advice = '总投入偏大，可按实际精力删减或延长周期'
  else if (tasks.length && avgGap <= 1) advice = '任务较密集，注意留出缓冲日'
  else if (!kpCount) advice = '尚未绑定知识点，可在清单里为任务挂载以更精准刷题'
  return { totalMinutes, kpCount, avgGap, advice }
})

// ── 级联加载 ──
const loadCourses = async () => {
  try { const r = await request.get('/api/courses'); courses.value = Array.isArray(r.data) ? r.data : [] } catch (e) { /* 静默 */ }
}
const onCourseChange = async (id) => {
  selChapterId.value = null; selKpIds.value = []; chapters.value = []; kpOptions.value = []
  if (!id) return
  try { const r = await request.get('/api/chapters', { params: { course_id: id } }); chapters.value = Array.isArray(r.data) ? r.data : [] } catch (e) { chapters.value = [] }
}
const onChapterChange = async (id) => {
  selKpIds.value = []; kpOptions.value = []
  if (!id) return
  try { const r = await request.get('/api/learning/knowledge-points', { params: { chapter_id: id } }); kpOptions.value = Array.isArray(r.data) ? r.data : [] } catch (e) { kpOptions.value = [] }
}
const addPickedKps = () => {
  for (const id of selKpIds.value) {
    if (pickedKps.value.some(k => k.id === id)) continue
    const kp = kpOptions.value.find(k => k.id === id)
    if (kp) pickedKps.value.push({ id: kp.id, name: kp.name })
  }
  selKpIds.value = []
}
const removePickedKp = (id) => { pickedKps.value = pickedKps.value.filter(k => k.id !== id) }

// ── 生成 ──
const generate = async () => {
  if (!form.title.trim() && !form.description.trim()) {
    ElMessage.warning('请先填写计划标题或学习目标描述')
    return
  }
  generating.value = true
  applied.value = false
  // 把挂载知识点名称并入描述，让后端 _match_plan_kps 命中并自动绑定 knowledge_point_id
  const kpNames = pickedKps.value.map(k => k.name).join(' ')
  const desc = (form.description.trim() + (kpNames ? `。重点知识点：${kpNames}` : '')).trim()
  const payload = {
    title: form.title.trim(),
    description: desc,
    start_date: form.range?.[0] || undefined,
    end_date: form.range?.[1] || undefined,
  }
  try {
    // AI 拆解需等外部大模型返回（实测 30–35s，后端上限 60s+），远超 axios 默认 30s，
    // 故本请求单独放宽超时到 90s，避免浏览器先行 ERR_ABORTED 而错过结果。
    const r = await request.post('/api/learning/plans/ai-suggest-tasks', payload, { timeout: 90000 })
    const d = r.data || {}
    result.value = {
      basis: d.basis || '',
      source: d.source || 'rule',
      days: d.days || 56,
      tasks: (d.tasks || []).map((t, i) => ({
        _key: i,
        _checked: true,
        title: t.title || '',
        task_type: t.task_type || 'custom',
        knowledge_point_id: t.knowledge_point_id || null,
        question_count: t.question_count || null,
        estimated_minutes: t.estimated_minutes || 0,
        due_date: t.due_date || undefined,
      })),
    }
    if (!result.value.tasks.length) ElMessage.info('AI 未能拆解出任务，请补充更具体的目标描述')
    viewMode.value = 'list'
  } catch (e) {
    ElMessage.error('AI 生成失败或超时，请稍后重试（也可先不挂载知识点、简化目标后再生成）')
  } finally {
    generating.value = false
  }
}

const removeTask = (key) => { result.value.tasks = result.value.tasks.filter(t => t._key !== key) }
const toggleAll = (val) => { result.value.tasks.forEach(t => { t._checked = val }) }
let _manualKey = 100000
const addBlankTask = () => {
  result.value.tasks.push({
    _key: ++_manualKey, _checked: true, title: '新任务', task_type: 'custom',
    knowledge_point_id: null, question_count: null, estimated_minutes: 30,
    due_date: form.range?.[0] || new Date().toISOString().slice(0, 10),
  })
}

// ── 应用：建计划 + 批量落任务（≤10 分块） ──
const apply = async () => {
  if (mode.value === 'free') return applyFree()
  const chosen = checkedTasks.value
  if (!chosen.length) { ElMessage.warning('请至少勾选一个任务'); return }
  if (!form.title.trim()) { ElMessage.warning('请填写计划标题'); return }
  try {
    await ElMessageBox.confirm(
      `将创建学习计划《${form.title.trim()}》并写入 ${chosen.length} 个任务，确认应用？`,
      '确认应用学习计划', { type: 'success', confirmButtonText: '确认应用', cancelButtonText: '再看看' }
    )
  } catch (e) { return }

  applying.value = true
  try {
    const kpNames = pickedKps.value.map(k => k.name).join(' ')
    const desc = (form.description.trim() + (kpNames ? `。重点知识点：${kpNames}` : '')).trim()
    const createRes = await request.post('/api/learning/plans', {
      title: form.title.trim(),
      description: desc || null,
      start_date: form.range?.[0] || undefined,
      end_date: form.range?.[1] || undefined,
    })
    const planId = createRes.data.id
    const items = chosen.map(t => ({
      title: (t.title || '').trim(),
      task_type: t.knowledge_point_id ? 'knowledge_point' : (t.task_type || 'custom'),
      knowledge_point_id: t.knowledge_point_id || null,
      question_count: t.question_count || null,
      estimated_minutes: t.estimated_minutes || null,
      due_date: t.due_date || null,
    })).filter(it => it.title)
    let added = 0
    for (let i = 0; i < items.length; i += 10) {
      const chunk = items.slice(i, i + 10)
      const r = await request.post(`/api/learning/plans/${planId}/tasks/batch`, { items: chunk })
      added += r.data.added || 0
    }
    appliedMode.value = 'mounted'
    appliedTitle.value = form.title.trim()
    appliedCount.value = added
    applied.value = true
    ElMessage.success(`已应用：计划创建成功，写入 ${added} 个任务`)
  } catch (e) {
    ElMessage.error('应用失败，请检查网络或稍后重试')
  } finally {
    applying.value = false
  }
}

// ── 自由主题闭环：一键生成 路径+图谱+计划（任务绑知识点） ──
const applyFree = async () => {
  if (!form.title.trim() && !form.description.trim()) { ElMessage.warning('请填写学习主题或描述'); return }
  const topic = (form.title.trim() || form.description.trim()).slice(0, 60)
  try {
    await ElMessageBox.confirm(
      `将围绕主题《${topic}》由 AI 从零生成知识体系，并同步创建：学习路径 + 知识图谱 + 学习计划（任务绑定知识点）。生成需等 AI，约 30–60 秒。确认应用？`,
      '确认生成完整自学闭环', { type: 'success', confirmButtonText: '确认应用', cancelButtonText: '再看看' }
    )
  } catch (e) { return }
  applying.value = true
  try {
    const r = await request.post('/api/learning/topics/plan-full', {
      title: topic,
      description: form.description.trim() || topic,
      start_date: form.range?.[0] || undefined,
      end_date: form.range?.[1] || undefined,
    }, { timeout: 120000 })
    const d = r.data || {}
    appliedMode.value = 'free'
    appliedTitle.value = topic
    appliedCount.value = d.tasks_total || 0
    appliedPathId.value = d.path_id || null
    appliedPlanId.value = d.plan_id || null
    appliedStats.value = { kp: (d.kp_created || 0) + (d.kp_existing || 0), edges: d.edges_created || 0, nodes: d.nodes_created || 0 }
    applied.value = true
    ElMessage.success(d.message || '已生成完整自学闭环')
  } catch (e) {
    ElMessage.error('AI 生成闭环失败或超时，请稍后重试')
  } finally {
    applying.value = false
  }
}

const discard = () => { result.value = null; applied.value = false }
const resetWorkbench = () => {
  result.value = null
  applied.value = false
  appliedMode.value = ''; appliedPathId.value = null; appliedPlanId.value = null
  appliedStats.value = { kp: 0, edges: 0, nodes: 0 }
  form.title = ''; form.description = ''; form.range = []
  pickedKps.value = []
  selCourseId.value = null; selChapterId.value = null; selKpIds.value = []
  chapters.value = []; kpOptions.value = []
}

onMounted(loadCourses)
</script>

<style scoped>
.study-plan-workbench { padding: 20px; max-width: 1080px; }

.page-header { margin-bottom: 20px; display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 14px; color: var(--text-muted); margin: 0; }

.panel {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 20px 22px;
  margin-bottom: 20px;
}
.panel-head h2 { font-size: 16px; font-weight: 600; margin: 0 0 16px; color: var(--text-primary); display: flex; align-items: center; gap: 8px; }

.goal-form :deep(.el-form-item__label) { font-weight: 500; color: var(--text-muted); }
.gf-row { display: flex; gap: 20px; }
.gf-title { flex: 1; }
.gf-date { width: 320px; }
@media (max-width: 720px) { .gf-row { flex-direction: column; } .gf-date { width: 100%; } }

.attach { margin-top: 4px; padding: 16px; border: 1px dashed var(--border-color); border-radius: 12px; background: var(--bg-hover, rgba(99,102,241,0.03)); }
.attach-title { font-size: 13px; color: var(--text-primary); display: flex; align-items: center; gap: 6px; margin-bottom: 12px; }
.attach-tip { color: var(--text-muted); font-size: 12px; }
.attach-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.picked-tags { margin-top: 12px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pt-label { font-size: 12px; color: var(--text-muted); }

.gen-bar { margin-top: 18px; display: flex; align-items: center; gap: 12px; }
.gen-hint { font-size: 12px; color: var(--text-muted); }
.gen-hint-live { display: inline-flex; align-items: center; gap: 6px; color: #6366f1; font-weight: 500; }

/* 依据条 */
.basis-bar { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 18px; padding-bottom: 16px; border-bottom: 1px solid var(--border-color); }
.bb-head { display: flex; align-items: center; gap: 8px; font-size: 15px; color: var(--text-primary); }
.bb-basis { font-size: 13px; color: var(--text-muted); margin: 8px 0; line-height: 1.6; }
.bb-insight { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; font-size: 13px; color: var(--text-primary); }
.bb-insight b { color: #6366f1; }

/* 清单视图 */
.week-group { margin-bottom: 18px; }
.week-head { font-size: 13px; font-weight: 600; color: #6366f1; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.wh-range { font-weight: 400; color: var(--text-muted); font-size: 12px; }
.task-card {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 12px 14px; border: 1px solid var(--border-color); border-radius: 12px; margin-bottom: 10px;
  transition: all 0.2s;
}
.task-card:hover { border-color: rgba(99,102,241,0.4); }
.task-card.unchecked { opacity: 0.5; }
.tc-check { margin-top: 4px; }
.tc-body { flex: 1; min-width: 0; }
.tc-title { margin-bottom: 8px; }
.tc-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tc-date { width: 140px; }
.tc-field { font-size: 12px; color: var(--text-muted); display: inline-flex; align-items: center; gap: 4px; }
.tc-num { width: 96px; }
.tc-kp { width: 160px; }
.list-foot { display: flex; gap: 8px; margin-top: 4px; }

/* 甘特视图 */
.gantt-ruler { display: flex; margin-left: 220px; margin-bottom: 6px; }
.gr-tick { flex: 1; font-size: 11px; color: var(--text-muted); text-align: left; border-left: 1px dashed var(--border-color); padding-left: 4px; }
.gantt-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.gantt-row.unchecked { opacity: 0.45; }
.g-label { width: 210px; display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.gl-text { font-size: 13px; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.g-track { flex: 1; height: 22px; background: var(--bg-hover, rgba(99,102,241,0.06)); border-radius: 6px; position: relative; }
.g-dot { position: absolute; top: 50%; transform: translate(-50%, -50%); width: 12px; height: 12px; border-radius: 50%; background: #6366f1; }
.g-dot.dot-knowledge_point { background: #06b6d4; }
.g-dot.dot-practice { background: #10b981; }
.g-dot.dot-resource { background: #f59e0b; }
.g-dot.dot-custom { background: #8b5cf6; }
.gd-tip { position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%); font-size: 10px; color: var(--text-muted); white-space: nowrap; opacity: 0; }
.g-dot:hover .gd-tip { opacity: 1; }
.gantt-tip { font-size: 12px; color: var(--text-muted); margin-top: 10px; }

/* 应用条 */
.apply-bar { margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--border-color); display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.applied-ok { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--text-primary); flex-wrap: wrap; }

.mode-switch { flex-shrink: 0; }
.free-banner { display: flex; align-items: flex-start; gap: 10px; padding: 14px 16px; margin-bottom: 18px; border-radius: 12px; background: linear-gradient(135deg, rgba(99,102,241,0.10), rgba(168,85,247,0.10)); border: 1px solid rgba(99,102,241,0.22); font-size: 13px; line-height: 1.7; color: var(--text-primary); }
.free-banner .el-icon { color: #6366f1; margin-top: 2px; flex-shrink: 0; font-size: 18px; }
</style>
