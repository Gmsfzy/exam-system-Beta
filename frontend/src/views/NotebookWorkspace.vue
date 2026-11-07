<template>
  <div class="nb-workspace">
    <!-- ── 列表模式 ─────────────────────────────────────────── -->
    <template v-if="!embedded && !notebook">
      <div class="nb-list-head">
        <h2>代码笔记本</h2>
        <div>
          <el-radio-group v-model="scope" size="small" @change="loadList">
            <el-radio-button label="mine">我的</el-radio-button>
            <el-radio-button label="public">公开</el-radio-button>
          </el-radio-group>
          <el-button type="primary" style="margin-left: 12px" :icon="Plus" @click="createVisible = true">新建笔记本</el-button>
          <el-button style="margin-left: 8px" :icon="Upload" :loading="importing" @click="triggerImport">导入 .ipynb</el-button>
          <input ref="importInput" type="file" accept=".ipynb,application/json" style="display: none" @change="onImportFile" />
        </div>
      </div>
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 14px"
                title="Jupyter 式代码笔记本：变量跨单元保留，支持 matplotlib 图表与 DataFrame 表格输出" />
      <el-empty v-if="!list.length" description="还没有笔记本，点右上角新建一个" />
      <div class="nb-card-grid">
        <el-card v-for="nb in list" :key="nb.id" shadow="hover" class="nb-card" @click="openNotebook(nb.id)">
          <div class="nb-card-title">
            {{ nb.title }}
            <el-tag v-if="nb.visibility === 'public'" size="small" type="success">公开</el-tag>
            <el-tag v-if="nb.user_id !== currentUserId" size="small" type="info">只读</el-tag>
          </div>
          <div class="nb-card-desc">{{ nb.description || '（无描述）' }}</div>
          <div class="nb-card-meta">{{ nb.cell_count || 0 }} 个单元 · 更新于 {{ fmtTime(nb.updated_at) }}</div>
          <div class="nb-card-actions" v-if="nb.user_id === currentUserId">
            <el-button size="small" text type="danger" :icon="Delete" @click.stop="removeNotebook(nb)">删除</el-button>
          </div>
          <!-- v6.7 社区接入：他人公开本可一键 fork 为自己的可编辑副本 -->
          <div class="nb-card-actions" v-else-if="nb.visibility === 'public'">
            <el-button size="small" text type="primary" :icon="CopyDocument" @click.stop="forkNotebook(nb)">Fork 到我的笔记本</el-button>
          </div>
        </el-card>
      </div>

      <el-dialog v-model="createVisible" title="新建笔记本" width="420px">
        <el-form label-width="70px">
          <el-form-item label="标题" required>
            <el-input v-model="form.title" maxlength="120" placeholder="例如： pandas 练习 / 梯度下降实验" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" />
          </el-form-item>
          <el-form-item label="可见性">
            <el-radio-group v-model="form.visibility">
              <el-radio label="private">私有</el-radio>
              <el-radio label="public">公开</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="doCreate">创建</el-button>
        </template>
      </el-dialog>
    </template>

    <!-- ── 编辑模式 ─────────────────────────────────────────── -->
    <template v-else>
      <div class="nb-editor-head">
        <el-button v-if="!embedded" text :icon="Back" @click="goBack">返回</el-button>
        <el-input v-model="notebook.title" class="nb-title" maxlength="120" :disabled="readonly" @blur="saveMeta" />
        <el-tag :type="meta.backend === 'docker' ? 'success' : 'warning'" size="small">
          {{ meta.backend === 'docker' ? '容器隔离' : '本机防呆级' }}
        </el-tag>
        <span class="nb-spacer"></span>
        <el-button size="small" :icon="Download" @click="exportIpynb">导出 .ipynb</el-button>
        <template v-if="!readonly">
          <el-button size="small" :icon="Plus" @click="addCell('code')">代码单元</el-button>
          <el-button size="small" :icon="DocumentAdd" @click="addCell('markdown')">Markdown 单元</el-button>
          <el-button size="small" type="success" :icon="VideoPlay" :loading="runningAll" @click="runAll">运行全部</el-button>
          <el-button size="small" :icon="RefreshLeft" @click="resetKernel">重置 kernel</el-button>
          <el-button size="small" type="primary" :icon="Checked" :loading="saving" @click="saveAll">保存</el-button>
        </template>
        <el-tag v-else type="info">只读浏览</el-tag>
      </div>

      <NotebookCell v-for="(c, i) in cells" :key="c.id" :cell="c" :index="i" :total="cells.length"
                    :running="runningId === c.id" :answer-mode="answerMode" @run="runCell" @delete="deleteCell"
                    @use-answer="(src) => emit('use-answer', src)" @interrupt="stopCell"
                    @move-up="moveCell($event, -1)" @move-down="moveCell($event, 1)" />
      <el-empty v-if="!cells.length" description="还没有单元，点上方按钮添加" />
    </template>
  </div>
</template>

<script setup>
// 代码笔记本工作台（v6.6）：列表 + 编辑双形态同页切换（路由 /learning/notebook[/:id]）
// 编辑态：cell 列表由 NotebookCell.vue 渲染；「运行」= 先 PUT 保存源码再 POST run（持久 kernel 跨 cell 保留状态）
// 后端 meta 提供隔离级别提示（docker=容器级 / subprocess=本机防呆级），只读笔记本（他人公开）禁止编辑
// v6.7 六模块接入：embedded 模式由其他模块（作业/考试/竞赛/悬赏）通过 props 传入 ctx，
// 走 /notebooks/ctx get-or-create；answerMode 下每个代码单元可「用作作答」回传给宿主
import { ref, reactive, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Back, VideoPlay, RefreshLeft, Checked, DocumentAdd, CopyDocument, Upload, Download } from '@element-plus/icons-vue'
import request from '../utils/request'
import NotebookCell from '../components/NotebookCell.vue'
import { useAuthStore } from '../stores/auth'

const props = defineProps({
  embedded: { type: Boolean, default: false },     // 嵌入其他模块（无列表/无返回）
  ctxType: { type: String, default: '' },          // homework/exam/competition/bounty
  ctxId: { type: [Number, String], default: 0 },
  ctxTitle: { type: String, default: '' },
  answerMode: { type: Boolean, default: false },   // 代码单元附「用作作答」按钮
})
const emit = defineEmits(['use-answer'])

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const currentUserId = ref(auth.user?.id)

const meta = reactive({ backend: 'subprocess', timeout: 30, max_cells: 200, max_source: 20000 })
const scope = ref('mine')
const list = ref([])
const createVisible = ref(false)
const creating = ref(false)
const form = reactive({ title: '', description: '', visibility: 'private' })
// v6.9 阶段 4：.ipynb 导入/导出
const importing = ref(false)
const importInput = ref(null)

const notebook = ref(null)
const cells = ref([])
const runningId = ref(0)
const runningAll = ref(false)
const saving = ref(false)
const readonly = ref(false)

const fmtTime = (iso) => { try { return new Date(iso).toLocaleString() } catch (e) { return iso } }

// ── 列表 ────────────────────────────────────────────────────
const loadList = async () => {
  const { data } = await request.get('/notebooks', { params: { scope: scope.value } })
  list.value = data.items || []
}

const doCreate = async () => {
  if (!form.title.trim()) { ElMessage.warning('请填写标题'); return }
  creating.value = true
  try {
    const { data } = await request.post('/notebooks', { ...form })
    createVisible.value = false
    form.title = ''; form.description = ''
    router.push(`/learning/notebook/${data.id}`)
  } finally { creating.value = false }
}

const removeNotebook = async (nb) => {
  await ElMessageBox.confirm(`确定删除笔记本「${nb.title}」？单元与输出将一并删除`, '提示', { type: 'warning' })
  await request.delete(`/notebooks/${nb.id}`)
  ElMessage.success('已删除')
  loadList()
}

const forkNotebook = async (nb) => {
  const { data } = await request.post(`/notebooks/${nb.id}/fork`)
  ElMessage.success('已 fork 为我的副本')
  router.push(`/learning/notebook/${data.id}`)
}

// v6.9 阶段 4：上传 .ipynb 导入为本人的可编辑笔记本
const triggerImport = () => importInput.value && importInput.value.click()
const onImportFile = async (ev) => {
  const file = ev.target.files && ev.target.files[0]
  if (!file) return
  importing.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const { data } = await request.post('/notebooks/import', fd, {
      headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000,
    })
    ElMessage.success(`已导入「${data.title}」（${(data.cells || []).length} 个单元）`)
    router.push(`/learning/notebook/${data.id}`)
  } catch (e) { /* 拦截器已提示 */ } finally {
    importing.value = false
    ev.target.value = ''   // 允许重复导入同一文件
  }
}

// v6.9 阶段 4：导出当前笔记本为 .ipynb（本人或公开只读本均可）
const exportIpynb = async () => {
  if (!notebook.value) return
  try {
    const resp = await request.get(`/notebooks/${notebook.value.id}/export`, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([resp.data]))
    const link = document.createElement('a')
    link.href = url
    link.download = `${(notebook.value.title || 'notebook').replace(/[\\/:*?"<>|]+/g, '_')}.ipynb`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (e) { /* 拦截器已提示 */ }
}

// ── 打开 / 路由同步 ─────────────────────────────────────────
const openNotebook = (id) => router.push(`/learning/notebook/${id}`)
const goBack = () => router.push('/learning/notebook')

const loadNotebook = async (id) => {
  const { data } = await request.get(`/notebooks/${id}`)
  notebook.value = data
  cells.value = data.cells || []
  readonly.value = data.user_id !== currentUserId.value
}

// v6.7 嵌入式：按上下文 get-or-create，同一用户×同一作业/考试/竞赛/悬赏复用一个笔记本
const loadCtx = async () => {
  const { data } = await request.get('/notebooks/ctx', {
    params: { ctx_type: props.ctxType, ctx_id: props.ctxId, title: props.ctxTitle || undefined },
  })
  notebook.value = data.notebook
  cells.value = data.notebook.cells || []
  readonly.value = false
}

const loadMeta = async () => {
  try {
    const { data } = await request.get('/notebooks/meta')
    Object.assign(meta, data)
  } catch (e) { /* meta 失败不阻塞主流程 */ }
}

watch(() => route.params.id, (id) => {
  if (id) { loadNotebook(id) } else { notebook.value = null; loadList() }
}, { immediate: false })

onMounted(async () => {
  await loadMeta()
  if (props.embedded) { loadCtx(); return }
  if (route.params.id) { loadNotebook(route.params.id) } else { loadList() }
})

// ── 编辑态操作 ──────────────────────────────────────────────
const saveMeta = async () => {
  if (readonly.value || !notebook.value) return
  try { await request.put(`/notebooks/${notebook.value.id}`, { title: notebook.value.title }) } catch (e) { /* 拦截器已提示 */ }
}

const addCell = async (cellType) => {
  const { data } = await request.post(`/notebooks/${notebook.value.id}/cells`, { cell_type: cellType, source: '' })
  cells.value.push(data)
}

const deleteCell = async (cell) => {
  await ElMessageBox.confirm('确定删除该单元？', '提示', { type: 'warning' })
  await request.delete(`/notebooks/${notebook.value.id}/cells/${cell.id}`)
  cells.value = cells.value.filter(c => c.id !== cell.id)
}

const moveCell = async (cell, delta) => {
  const idx = cells.value.findIndex(c => c.id === cell.id)
  const to = idx + delta
  if (to < 0 || to >= cells.value.length) return
  const arr = cells.value.slice()
  const [it] = arr.splice(idx, 1)
  arr.splice(to, 0, it)
  const { data } = await request.post(`/notebooks/${notebook.value.id}/cells/reorder`, { order: arr.map(c => c.id) })
  cells.value = data.cells
}

// 运行单个 cell：先保存源码（保证后端执行的是编辑器当前内容），再进持久 kernel 执行
const runCell = async (cell) => {
  runningId.value = cell.id
  try {
    await request.put(`/notebooks/${notebook.value.id}/cells/${cell.id}`, { source: cell.source })
    const { data } = await request.post(`/notebooks/${notebook.value.id}/cells/${cell.id}/run`, {}, {
      timeout: (Number(meta.timeout) || 30) * 1000 + 40000,
    })
    const idx = cells.value.findIndex(c => c.id === cell.id)
    if (idx >= 0) cells.value[idx] = data.cell
    if (data.timed_out) ElMessage.warning('执行超时，kernel 已重启（跨单元状态丢失）')
    if (data.backend && data.backend !== meta.backend) meta.backend = data.backend
  } catch (e) { /* 拦截器已提示 */ } finally { runningId.value = 0 }
}

// v6.9 阶段 5：「停止」向持久 kernel 下发软中断（纯 Python 计算可打断；卡在 C 调用则由 runCell 超时兑底）
// 与 runCell 阻塞等待响应并发，故不持前端锁，fire-and-forget，失败静默（拦截器已提示）
const stopCell = async () => {
  if (!notebook.value) return
  try {
    await request.post(`/notebooks/${notebook.value.id}/kernel/interrupt`)
  } catch (e) { /* 拦截器已提示 */ }
}

const runAll = async () => {
  runningAll.value = true
  try {
    for (const c of cells.value.filter(x => x.cell_type === 'code')) {
      await runCell(c)
    }
  } finally { runningAll.value = false }
}

const resetKernel = async () => {
  await ElMessageBox.confirm('重置后跨单元保留的变量/导入将全部清空（相当于 Restart Kernel），确定？', '提示', { type: 'warning' })
  await request.post(`/notebooks/${notebook.value.id}/kernel/reset`)
  ElMessage.success('kernel 已重置')
}

const saveAll = async () => {
  saving.value = true
  try {
    for (const c of cells.value) {
      if (c.cell_type === 'code' || c.source != null) {
        await request.put(`/notebooks/${notebook.value.id}/cells/${c.id}`, { source: c.source })
      }
    }
    ElMessage.success('已保存')
  } finally { saving.value = false }
}
</script>

<style scoped>
.nb-workspace { padding: 4px; }
.nb-list-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; }
.nb-list-head h2 { margin: 0; }
.nb-card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.nb-card { cursor: pointer; }
.nb-card-title { font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 8px; }
.nb-card-desc { color: #606266; font-size: 13px; margin: 8px 0; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.nb-card-meta { color: #909399; font-size: 12px; }
.nb-card-actions { text-align: right; margin-top: 4px; }
.nb-editor-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.nb-title { max-width: 360px; font-size: 16px; font-weight: 600; }
.nb-spacer { flex: 1; }
</style>
