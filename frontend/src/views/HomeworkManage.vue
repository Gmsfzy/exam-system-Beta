<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Notebook /></el-icon> 作业管理</h2>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建作业</el-button>
    </div>

    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane label="草稿" name="draft" />
      <el-tab-pane label="已发布" name="published" />
      <el-tab-pane label="已关闭" name="closed" />
    </el-tabs>

    <el-empty v-if="!items.length" description="还没有作业，点击右上角新建" />
    <el-table v-else :data="items" stripe>
      <el-table-column prop="title" label="标题" min-width="200">
        <template #default="{ row }">
          <router-link :to="`/homeworks/${row.id}/grade`" class="link">{{ row.title }}</router-link>
          <el-tag size="small" effect="plain" style="margin-left: 8px">
            {{ row.hw_type === 'open' ? '开放式' : '题集式' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="提交/名单" width="110" align="center">
        <template #default="{ row }">
          {{ row.stats?.submitted_count ?? 0 }} / {{ row.stats?.student_count ?? 0 }}
        </template>
      </el-table-column>
      <el-table-column label="截止" width="160">
        <template #default="{ row }">
          <span v-if="row.has_deadline" :class="{ overdue: row.is_expired }">{{ (row.deadline || '').slice(0, 16) }}</span>
          <el-tag v-else size="small" type="info" effect="plain">不限期</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)" :disabled="row.status !== 'draft'">编辑</el-button>
          <el-button v-if="row.status === 'draft'" size="small" type="success" @click="doPublish(row)">发布</el-button>
          <el-button v-if="row.status === 'published'" size="small" type="warning" @click="doClose(row)">关闭</el-button>
          <el-dropdown trigger="click" style="margin-left: 8px" @command="(c) => onRowCommand(c, row)">
            <el-button size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="stats">成绩统计</el-dropdown-item>
                <el-dropdown-item command="copy">复制为草稿</el-dropdown-item>
                <el-dropdown-item command="urge" :disabled="row.status !== 'published'">催交未交</el-dropdown-item>
                <el-dropdown-item command="export">导出成绩</el-dropdown-item>
                <el-dropdown-item command="delete" :disabled="row.status !== 'draft'" divided>删除草稿</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="dialog" :title="form.id ? '编辑作业' : '新建作业'" width="760px" top="6vh">
      <el-form :model="form" label-width="96px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" placeholder="作业标题" />
        </el-form-item>
        <el-form-item label="形态">
          <el-radio-group v-model="form.hw_type" :disabled="!!form.id">
            <el-radio-button value="question_set">题集式</el-radio-button>
            <el-radio-button value="open">开放式</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="作业说明（开放式必填）" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-switch v-model="form.has_deadline" active-text="设置截止时间" />
          <el-date-picker v-if="form.has_deadline" v-model="form.deadline" type="datetime"
                          value-format="YYYY-MM-DDTHH:mm:ss" placeholder="选择截止日期时间"
                          style="margin-left: 12px" />
          <span v-else class="hint">未设截止：作业长期有效，学生随时可交</span>
        </el-form-item>
        <el-form-item v-if="form.has_deadline" label="提前提醒">
          <el-input-number v-model="form.remind_before" :min="0" :max="10080" :step="60" />
          <span class="hint">分钟（0=不提醒，截止前 N 分钟提醒未交学生）</span>
        </el-form-item>
        <el-form-item label="及格线">
          <el-input-number v-model="form.pass_score" :min="0" :max="1000" :step="5" :precision="1"
                           :value-on-clear="null" controls-position="right" style="width: 160px" placeholder="留空不设" />
          <span class="hint">用于统计及格率/优秀率（优秀=满分90%），留空则不设</span>
        </el-form-item>
        <el-form-item label="规则">
          <el-checkbox v-model="form.allow_late" :disabled="!form.has_deadline">允许迟交</el-checkbox>
          <el-checkbox v-model="form.allow_resubmit">允许重交</el-checkbox>
        </el-form-item>
        <el-form-item label="参考资料">
          <div v-if="form.reference" class="ref-row">
            <el-link type="primary" @click="downloadRef">{{ form.reference.filename }}</el-link>
            <el-button size="small" text type="danger" @click="removeRef">删除</el-button>
          </div>
          <div v-else-if="!form.id" class="hint">保存草稿后，可在“编辑”中上传供学生下载的参考资料</div>
          <el-upload v-else :show-file-list="false" :http-request="uploadRef" action="#">
            <el-button size="small" :icon="Upload">上传参考资料</el-button>
            <span class="hint">学生作答页可下载查看</span>
          </el-upload>
        </el-form-item>

        <el-form-item v-if="form.hw_type === 'question_set'" label="题目">
          <div class="picker">
            <div class="picker-head">
              <div class="picker-tools">
                <el-select v-model="pickMajor" filterable placeholder="按专业筛选题库" clearable
                           style="width: 180px" @change="loadQuestions">
                  <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
                </el-select>
                <el-select v-model="randDifficulty" placeholder="难度" clearable size="small" style="width: 96px">
                  <el-option v-for="d in DIFFICULTY_OPTIONS" :key="d" :label="difficultyLabel(d)" :value="d" />
                </el-select>
                <el-input-number v-model="randCount" :min="1" :max="50" size="small" controls-position="right" style="width: 92px" />
                <el-button size="small" :icon="MagicStick" @click="randomPick">随机抽题</el-button>
              </div>
              <span class="hint">已选 {{ form.questions.length }} 题，总分 {{ totalScore }}</span>
            </div>
            <el-table :data="questionPool" height="220" size="small" @select="onPick" @select-all="onPickAll">
              <el-table-column type="selection" width="46" :selectable="() => true" />
              <el-table-column prop="content" label="题干" min-width="220" show-overflow-tooltip />
              <el-table-column prop="type" label="类型" width="100" />
            </el-table>
            <div v-if="form.questions.length" class="chosen">
              <div v-for="(q, i) in form.questions" :key="q.question_id" class="chosen-row">
                <span class="idx">{{ i + 1 }}</span>
                <span class="ct" :title="q.content">{{ q.content }}</span>
                <el-input-number v-model="q.score" :min="0.5" :max="100" size="small" controls-position="right" />
                <el-button size="small" text type="danger" :icon="Delete" @click="removeQ(i)" />
              </div>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="发布名单">
          <el-select v-model="form.student_ids" multiple filterable placeholder="选择学生" style="width: 100%">
            <el-option v-for="s in students" :key="s.id" :label="s.username" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存草稿</el-button>
      </template>
    </el-dialog>

    <!-- 成绩统计对话框 -->
    <el-dialog v-model="statsDialog" :title="`成绩统计 - ${statsHomework}`" width="560px">
      <el-descriptions :column="2" border v-loading="statsLoading">
        <el-descriptions-item label="发布名单">{{ stats.student_count ?? 0 }} 人</el-descriptions-item>
        <el-descriptions-item label="已提交">{{ stats.submitted_count ?? 0 }} 人（{{ stats.submitted_rate ?? 0 }}%）</el-descriptions-item>
        <el-descriptions-item label="已批改">{{ stats.graded_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="待批改">{{ stats.pending_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="平均分">{{ stats.avg_score ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="满分">{{ stats.full_score ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="最高分">{{ stats.max_score_value ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="最低分">{{ stats.min_score_value ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="及格率">{{ stats.pass_rate != null ? stats.pass_rate + '%' : '未设及格线' }}</el-descriptions-item>
        <el-descriptions-item label="优秀率">{{ stats.excellent_rate != null ? stats.excellent_rate + '%' : '—' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="statsDialog = false">关闭</el-button>
        <el-button type="primary" :icon="Download" @click="doExportStats">导出成绩</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { Notebook, Plus, Delete, ArrowDown, Upload, MagicStick, Download } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { DIFFICULTY_OPTIONS, difficultyLabel } from '../utils/enums'

const tab = ref('all')
const items = ref([])
const dialog = ref(false)
const saving = ref(false)
const majors = ref([])
const students = ref([])
const questionPool = ref([])
const pickMajor = ref(null)
const randDifficulty = ref('')
const randCount = ref(5)
const statsDialog = ref(false)
const statsLoading = ref(false)
const stats = ref({})
const statsHomework = ref('')
const statsId = ref(null)

const form = reactive({
  id: null, title: '', description: '', hw_type: 'question_set', deadline: '', has_deadline: true,
  allow_late: true, allow_resubmit: true, remind_before: 0, pass_score: null, reference: null,
  questions: [], student_ids: []
})

const totalScore = computed(() =>
  form.questions.reduce((s, q) => s + (Number(q.score) || 0), 0).toFixed(1))

const statusText = (s) => ({ draft: '草稿', published: '已发布', closed: '已关闭' }[s] || s)
const statusTag = (s) => ({ draft: 'info', published: 'success', closed: 'warning' }[s] || 'info')

const load = async () => {
  const params = tab.value === 'all' ? {} : { status: tab.value }
  const res = await request.get('/api/homeworks', { params })
  items.value = res.data.items || []
}

const loadMeta = async () => {
  const [m, s] = await Promise.all([request.get('/api/majors'), request.get('/api/students')])
  majors.value = Array.isArray(m.data) ? m.data : (m.data.items || [])
  students.value = Array.isArray(s.data) ? s.data : (s.data.items || [])
}

const loadQuestions = async () => {
  const params = pickMajor.value ? { major_id: pickMajor.value } : {}
  const res = await request.get('/api/questions', { params })
  questionPool.value = Array.isArray(res.data) ? res.data : []
}

const openCreate = () => {
  Object.assign(form, {
    id: null, title: '', description: '', hw_type: 'question_set', deadline: '', has_deadline: true,
    allow_late: true, allow_resubmit: true, remind_before: 0, pass_score: null, reference: null,
    questions: [], student_ids: []
  })
  pickMajor.value = null
  questionPool.value = []
  dialog.value = true
}

const openEdit = async (row) => {
  const res = await request.get(`/api/homeworks/${row.id}`)
  const hw = res.data
  Object.assign(form, {
    id: hw.id, title: hw.title, description: hw.description || '', hw_type: hw.hw_type,
    deadline: hw.deadline || '', has_deadline: !!hw.has_deadline,
    allow_late: hw.allow_late, allow_resubmit: hw.allow_resubmit,
    remind_before: hw.remind_before || 0, pass_score: hw.pass_score ?? null, reference: hw.reference || null,
    questions: (hw.questions || []).map(q => ({ question_id: q.question_id, content: q.content, score: q.score })),
    student_ids: hw.student_ids || []
  })
  await loadQuestions()
  dialog.value = true
}

const qKey = (id) => `q${id}`
const onPick = (selection, row) => {
  if (selection.includes(row) && !form.questions.find(q => q.question_id === row.id)) {
    form.questions.push({ question_id: row.id, content: row.content, score: 5 })
  }
}
const onPickAll = (selection) => {
  selection.forEach(row => {
    if (!form.questions.find(q => q.question_id === row.id)) {
      form.questions.push({ question_id: row.id, content: row.content, score: 5 })
    }
  })
}
const removeQ = (i) => form.questions.splice(i, 1)

const save = async () => {
  if (!form.title.trim()) return ElMessage.warning('请填写标题')
  if (form.has_deadline && !form.deadline) return ElMessage.warning('请选择截止时间，或关闭“设置截止时间”')
  saving.value = true
  try {
    const payload = {
      title: form.title, description: form.description, hw_type: form.hw_type,
      deadline: form.has_deadline ? form.deadline : '', allow_late: form.allow_late,
      allow_resubmit: form.allow_resubmit, remind_before: form.has_deadline ? form.remind_before : 0,
      pass_score: form.pass_score, student_ids: form.student_ids
    }
    if (form.hw_type === 'question_set') {
      payload.questions = form.questions.map(q => ({ question_id: q.question_id, score: q.score }))
    }
    if (form.id) await request.put(`/api/homeworks/${form.id}`, payload)
    else await request.post('/api/homeworks', payload)
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const doPublish = async (row) => {
  const res = await request.post(`/api/homeworks/${row.id}/publish`)
  ElMessage.success(res.data.message || '已发布')
  load()
}
const doClose = async (row) => {
  await ElMessageBox.confirm(`确认关闭作业《${row.title}》？关闭后不再接收提交。`, '提示', { type: 'warning' })
  await request.post(`/api/homeworks/${row.id}/close`)
  ElMessage.success('已关闭')
  load()
}
const doDelete = async (row) => {
  await ElMessageBox.confirm(`确认删除草稿《${row.title}》？`, '提示', { type: 'warning' })
  await request.delete(`/api/homeworks/${row.id}`)
  ElMessage.success('已删除')
  load()
}

const onRowCommand = (cmd, row) => {
  if (cmd === 'stats') return openStats(row)
  if (cmd === 'copy') return doCopy(row)
  if (cmd === 'urge') return doUrge(row)
  if (cmd === 'export') return doExport(row)
  if (cmd === 'delete') return doDelete(row)
}

const doUrge = async (row) => {
  const res = await request.post(`/api/homeworks/${row.id}/urge`)
  ElMessage.success(res.data.message || '已催交')
}

const doCopy = async (row) => {
  await request.post(`/api/homeworks/${row.id}/copy`)
  ElMessage.success('已复制为草稿')
  tab.value = 'draft'
  load()
}

const downloadBlob = async (url, filename) => {
  const res = await request.get(url, { responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(res.data)
  link.download = filename || 'download'
  link.click()
  URL.revokeObjectURL(link.href)
}

const doExport = (row) => downloadBlob(`/api/homeworks/${row.id}/export`, `homework_${row.id}_scores.csv`)

const openStats = async (row) => {
  statsId.value = row.id
  statsHomework.value = row.title
  stats.value = {}
  statsDialog.value = true
  statsLoading.value = true
  try {
    const res = await request.get(`/api/homeworks/${row.id}/stats`)
    stats.value = res.data.stats || {}
  } finally {
    statsLoading.value = false
  }
}
const doExportStats = () => doExport({ id: statsId.value })

const randomPick = async () => {
  const params = { count: randCount.value || 5 }
  if (pickMajor.value) params.major_id = pickMajor.value
  if (randDifficulty.value) params.difficulty = randDifficulty.value
  const exclude = form.questions.map(q => q.question_id)
  if (exclude.length) params.exclude = exclude
  const res = await request.get('/api/homeworks/random_questions', { params })
  const items = res.data.items || []
  if (!items.length) return ElMessage.warning('题库无匹配题目')
  items.forEach(it => {
    if (!form.questions.find(q => q.question_id === it.question_id)) {
      form.questions.push({ question_id: it.question_id, content: it.content, score: it.score || 5 })
    }
  })
  ElMessage.success(`已随机抽取 ${items.length} 题`)
}

const uploadRef = async ({ file }) => {
  const fd = new FormData()
  fd.append('file', file)
  const res = await request.post(`/api/homeworks/${form.id}/reference`, fd,
    { headers: { 'Content-Type': 'multipart/form-data' } })
  form.reference = res.data.reference || null
  ElMessage.success(res.data.message || '已上传')
  load()
}
const removeRef = async () => {
  const res = await request.delete(`/api/homeworks/${form.id}/reference`)
  form.reference = null
  ElMessage.success(res.data.message || '已删除')
  load()
}
const downloadRef = () => form.reference &&
  downloadBlob(`/api/homeworks/${form.id}/reference`, form.reference.filename)

onMounted(() => { load(); loadMeta(); loadQuestions() })
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.link { color: var(--el-color-primary, #409eff); }
.link:hover { text-decoration: underline; }
.overdue { color: #f56c6c; }
.hint { margin-left: 10px; font-size: 12px; color: #909399; }
.picker { width: 100%; }
.picker-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.picker-tools { display: flex; align-items: center; gap: 8px; }
.ref-row { display: flex; align-items: center; gap: 12px; }
.chosen { margin-top: 10px; max-height: 180px; overflow: auto; }
.chosen-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px dashed #ebeef5; }
.chosen-row .idx { width: 22px; color: #909399; }
.chosen-row .ct { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
