<template>
  <div class="study-notes">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习笔记</h1>
        <p class="page-subtitle">随手记下每一个灵感与总结，日积月累就是你的知识资产</p>
      </div>
      <div class="header-actions">
        <el-button @click="explainVisible = true; loadCards()">
          <el-icon><MagicStick /></el-icon>&nbsp;即问即讲
        </el-button>
        <el-button type="primary" @click="openEditor(null)">
          <el-icon><Plus /></el-icon>&nbsp;新建笔记
        </el-button>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="filter-bar">
      <el-input v-model="searchKey" placeholder="搜索标题 / 内容" clearable style="width: 220px"
                :prefix-icon="Search" @keyup.enter="load" @clear="load" />
      <el-select v-model="filterTag" placeholder="全部标签" clearable style="width: 150px" @change="load">
        <el-option v-for="t in allTags" :key="t" :label="t" :value="t" />
      </el-select>
      <el-select v-model="filterCategory" placeholder="全部分类" clearable style="width: 150px" @change="load">
        <el-option v-for="c in allCategories" :key="c" :label="c" :value="c" />
      </el-select>
      <el-button @click="load">刷新</el-button>
      <span class="count-tip">共 {{ notes.length }} 篇</span>
    </div>

    <el-empty v-if="!loading && !notes.length" description="还没有笔记，写一篇或让 AI 讲一个知识点转存吧" />

    <div class="note-grid">
      <!-- 单击卡片进阅读视图；编辑入口在阅读视图内（不绑双击，避免 click+dblclick 连发弹两层） -->
      <div v-for="n in notes" :key="n.id" class="note-card" :class="{ pinned: n.pinned }"
           @click="openViewer(n)">
        <div class="note-card-head">
          <span class="note-title">{{ n.title }}</span>
          <el-icon v-if="n.pinned" class="pin-icon" title="已置顶" @click.stop="togglePin(n)"><Top /></el-icon>
          <el-icon v-else class="pin-icon hidden" @click.stop="togglePin(n)"><Top /></el-icon>
        </div>
        <div class="note-excerpt">{{ n.excerpt || '（空白笔记）' }}</div>
        <div class="note-meta">
          <el-tag v-if="n.category" size="small" effect="plain">{{ n.category }}</el-tag>
          <el-tag v-for="t in (n.tags || [])" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
          <el-tag v-if="n.source === 'explain'" size="small" type="warning" effect="plain">AI 讲解</el-tag>
          <el-tag v-if="n.attachments?.length" size="small" type="info" effect="dark">📎 {{ n.attachments.length }}</el-tag>
          <span class="note-time">{{ fmtTime(n.updated_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 笔记阅读视图（单击卡片：直接看渲染后的正文） -->
    <el-dialog v-model="viewerVisible" :title="viewer.title || '笔记'" width="760px" top="6vh">
      <div v-loading="viewerLoading" class="viewer-body">
        <div class="viewer-meta">
          <el-tag v-if="viewer.category" size="small" effect="plain">{{ viewer.category }}</el-tag>
          <el-tag v-for="t in (viewer.tags || [])" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
          <el-tag v-if="viewer.source === 'explain'" size="small" type="warning" effect="plain">AI 讲解</el-tag>
          <span class="note-time">{{ fmtTime(viewer.updated_at) }}</span>
        </div>
        <el-scrollbar max-height="60vh">
          <RichContent :content="viewer.content || '（空白笔记）'" class="viewer-content" />
        </el-scrollbar>
        <div v-if="(viewer.attachments || []).length" class="viewer-attach">
          <span class="img-label">附件：</span>
          <a v-for="(a, i) in viewer.attachments" :key="i" class="att-link" @click="downloadFromViewer(i, a)">
            {{ a.filename }}（{{ fmtSize(a.size) }}）
          </a>
        </div>
      </div>
      <template #footer>
        <el-button type="danger" plain @click="removeNoteFromViewer">删除</el-button>
        <el-button @click="viewerVisible = false">关闭</el-button>
        <el-button type="primary" @click="editFromViewer">编辑</el-button>
      </template>
    </el-dialog>

    <!-- 笔记编辑抽屉 -->
    <el-drawer v-model="editorVisible" :title="editor.id ? '编辑笔记' : '新建笔记'" size="46%">
      <div class="editor-body">
        <el-input v-model="editor.title" placeholder="笔记标题" maxlength="200" show-word-limit />
        <div class="editor-row">
          <el-select v-model="editor.category" placeholder="分类（可选）" clearable filterable allow-create style="width: 200px">
            <el-option v-for="c in allCategories" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select v-model="editor.tags" multiple filterable allow-create default-first-option
                     placeholder="标签（回车创建）" style="flex: 1">
            <el-option v-for="t in allTags" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <div class="editor-tools">
          <el-button size="small" :loading="uploading" @click="pickImage">
            <el-icon><Picture /></el-icon>&nbsp;插入图片
          </el-button>
          <el-button size="small" :loading="attaching" @click="pickAttachment">
            <el-icon><Paperclip /></el-icon>&nbsp;上传附件
          </el-button>
          <el-checkbox v-model="editor.pinned" size="small">置顶</el-checkbox>
          <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/gif,image/webp"
                 style="display: none" @change="onFileChange" />
          <input ref="attachInput" type="file" style="display: none"
                 accept=".pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx,.csv,.zip,.rar,.7z,.png,.jpg,.jpeg,.gif,.webp,.mp4,.webm,.py,.java,.c,.cpp,.js,.ts,.html,.css,.sql"
                 @change="onAttachChange" />
        </div>
        <div v-if="editorAttachments.length" class="editor-attach">
          <span class="img-label">附件：</span>
          <a v-for="(a, i) in editorAttachments" :key="i" class="att-link" @click="downloadAttachment(i, a)">
            {{ a.filename }}（{{ fmtSize(a.size) }}）
          </a>
          <el-button v-for="(a, i) in editorAttachments" :key="'d' + i" link type="danger" size="small"
                     @click="removeAttachment(i)">删{{ i + 1 }}</el-button>
        </div>
        <div v-else-if="!editor.id" class="attach-hint">附件可传文档/表格(含csv)/压缩包/图片/视频/代码，≤50MB；新建笔记需先保存后再上传附件</div>
        <div class="editor-mode">
          <el-radio-group v-model="editMode" size="small">
            <el-radio-button value="write">编写</el-radio-button>
            <el-radio-button value="preview">预览</el-radio-button>
          </el-radio-group>
          <span class="mode-hint">正文支持 Markdown 与 LaTeX 公式（$...$），预览即最终阅读效果</span>
        </div>
        <el-input v-show="editMode === 'write'" v-model="editor.content" type="textarea" :rows="14"
                  maxlength="20000" show-word-limit
                  placeholder="支持 Markdown 语法；插入的图片以链接形式嵌入，保存后可在阅读视图直接看到" />
        <el-scrollbar v-if="editMode === 'preview'" max-height="42vh" class="editor-preview">
          <RichContent :content="editor.content || '（暂无内容）'" />
        </el-scrollbar>
        <div v-if="editorImages.length" class="editor-images">
          <span class="img-label">已插入图片：</span>
          <a v-for="(u, i) in editorImages" :key="i" :href="u" target="_blank" class="img-link">图 {{ i + 1 }}</a>
        </div>
      </div>
      <template #footer>
        <el-button v-if="editor.id" type="danger" plain @click="removeNote">删除</el-button>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!editor.title.trim()" @click="saveNote">保存</el-button>
      </template>
    </el-drawer>

    <!-- 即问即讲弹窗 -->
    <el-dialog v-model="explainVisible" title="即问即讲 · 知识点讲解卡" width="620px" top="6vh">
      <div class="explain-row">
        <el-input v-model="explainTopic" placeholder="输入任意知识点或问题，如：梯度下降、定积分的几何意义"
                  maxlength="200" clearable @keyup.enter="generateCard" />
        <el-button type="primary" :loading="explainLoading" @click="generateCard">讲解</el-button>
      </div>
      <div v-if="explainTip" class="explain-tip">{{ explainTip }}</div>
      <div v-if="currentCard" class="explain-card-box">
        <div class="explain-card-title">{{ currentCard.topic }}</div>
        <div class="explain-card-content">{{ currentCard.content }}</div>
        <el-button size="small" type="success" plain :loading="toNoteLoading" @click="cardToNote(currentCard)">
          转存为笔记
        </el-button>
      </div>
      <div v-if="cards.length" class="history-cards">
        <div class="history-label">历史讲解卡</div>
        <div v-for="c in cards" :key="c.id" class="history-card-item">
          <span class="hc-topic" @click="currentCard = c">{{ c.topic }}</span>
          <span class="hc-time">{{ fmtTime(c.created_at) }}</span>
          <el-button size="small" text @click="cardToNote(c)">转笔记</el-button>
          <el-button size="small" text type="danger" @click="removeCard(c.id)">删</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, Top, Picture, Paperclip, MagicStick } from '@element-plus/icons-vue'
import request from '../utils/request'
import RichContent from '../components/RichContent.vue'

const notes = ref([])
const allTags = ref([])
const allCategories = ref([])
const loading = ref(false)
const searchKey = ref('')
const filterTag = ref('')
const filterCategory = ref('')

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function load() {
  loading.value = true
  try {
    const params = {}
    if (searchKey.value.trim()) params.q = searchKey.value.trim()
    if (filterTag.value) params.tag = filterTag.value
    if (filterCategory.value) params.category = filterCategory.value
    const res = await request.get('/api/learning/notes', { params })
    notes.value = res.data.items || []
    allTags.value = res.data.tags || []
    allCategories.value = res.data.categories || []
  } catch (e) { /* 拦截器已提示 */ }
  loading.value = false
}
onMounted(load)

// ── 阅读视图（单击卡片）：正文走全站统一 RichContent 渲染，不直接进编辑器 ──
const viewerVisible = ref(false)
const viewerLoading = ref(false)
const viewer = reactive({ id: null, title: '', content: '', category: '', tags: [], source: '', pinned: false, attachments: [], updated_at: '' })

async function openViewer(n) {
  viewer.id = n.id
  viewer.title = n.title
  viewer.content = ''
  viewer.category = n.category || ''
  viewer.tags = [...(n.tags || [])]
  viewer.source = n.source || ''
  viewer.pinned = !!n.pinned
  viewer.attachments = [...(n.attachments || [])]
  viewer.updated_at = n.updated_at || ''
  viewerVisible.value = true
  viewerLoading.value = true
  try {
    // 列表只给 excerpt，正文需拉详情
    const res = await request.get(`/api/learning/notes/${n.id}`)
    const d = res.data
    viewer.content = d.content || ''
    viewer.attachments = [...(d.attachments || [])]
    viewer.updated_at = d.updated_at || viewer.updated_at
  } catch (e) { /* 拦截器已提示 */ }
  viewerLoading.value = false
}

function editFromViewer() {
  const n = { ...viewer, attachments: viewer.attachments }
  viewerVisible.value = false
  openEditor(n)
}

async function removeNoteFromViewer() {
  try {
    await ElMessageBox.confirm('确定删除这篇笔记？', '确认')
    await request.delete(`/api/learning/notes/${viewer.id}`)
    ElMessage.success('已删除')
    viewerVisible.value = false
    await load()
  } catch (e) { /* 取消或失败 */ }
}

async function downloadFromViewer(idx, a) {
  try {
    const res = await request.get(`/api/learning/attachments/${viewer.id}/${idx}/download`, { responseType: 'blob' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(res.data)
    link.download = a.filename || 'download'
    link.click()
    URL.revokeObjectURL(link.href)
  } catch (e) { /* ignore */ }
}

// ── 编辑器 ──
const editorVisible = ref(false)
const saving = ref(false)
const uploading = ref(false)
const fileInput = ref(null)
const editMode = ref('write')
const editor = reactive({ id: null, title: '', content: '', category: '', tags: [], pinned: false })

const editorImages = computed(() =>
  (editor.content.match(/\/uploads\/[\w.\-/]+/g) || []))

function openEditor(n) {
  editMode.value = 'write'
  editor.id = n ? n.id : null
  editor.title = n ? n.title : ''
  editor.content = ''
  editor.category = n ? (n.category || '') : ''
  editor.tags = n ? [...(n.tags || [])] : []
  editor.pinned = n ? !!n.pinned : false
  editorAttachments.value = n ? [...(n.attachments || [])] : []
  if (n) {
    request.get(`/api/learning/notes/${n.id}`)
      .then(res => { editor.content = res.data.content || '' })
      .catch(() => {})
  }
  editorVisible.value = true
}

async function saveNote() {
  saving.value = true
  try {
    const payload = {
      title: editor.title.trim(), content: editor.content,
      category: editor.category || null, tags: editor.tags,
    }
    if (editor.id) {
      payload.pinned = editor.pinned
      await request.put(`/api/learning/notes/${editor.id}`, payload)
    } else {
      await request.post('/api/learning/notes', payload)
    }
    ElMessage.success('已保存')
    editorVisible.value = false
    await load()
  } catch (e) { /* ignore */ }
  saving.value = false
}

async function removeNote() {
  try {
    await ElMessageBox.confirm('确定删除这篇笔记？', '确认')
    await request.delete(`/api/learning/notes/${editor.id}`)
    ElMessage.success('已删除')
    editorVisible.value = false
    await load()
  } catch (e) { /* 取消或失败 */ }
}

async function togglePin(n) {
  try {
    await request.put(`/api/learning/notes/${n.id}`, { title: n.title, pinned: !n.pinned })
    await load()
  } catch (e) { /* ignore */ }
}

// ── 图片上传（笔记配图） ──
function pickImage() {
  fileInput.value?.click()
}

async function onFileChange(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file) return
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.error('图片大小不能超过 5MB')
    return
  }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await request.post('/api/learning/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    editor.content += `\n![${res.data.name}](${res.data.url})\n`
    ElMessage.success('图片已插入')
  } catch (e) { /* ignore */ }
  uploading.value = false
}

// ── 附件上传（v4.6 统一白名单：文档/表格/压缩包/图片/视频/代码，≤50MB）──
const attaching = ref(false)
const attachInput = ref(null)
const editorAttachments = ref([])
const fmtSize = (n) => !n ? '0KB' : (n > 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.max(1, Math.round(n / 1024)) + 'KB')

function pickAttachment() {
  if (!editor.id) {
    ElMessage.warning('请先保存笔记，再上传附件')
    return
  }
  attachInput.value?.click()
}

async function onAttachChange(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file || !editor.id) return
  attaching.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('note_id', String(editor.id))
    await request.post('/api/learning/attachments', fd)
    editorAttachments.value.push({ filename: file.name, size: file.size })
    ElMessage.success(`附件「${file.name}」已上传`)
    await load()
  } catch (e) { /* 拦截器已提示 */ }
  attaching.value = false
}

async function downloadAttachment(idx, a) {
  try {
    const res = await request.get(`/api/learning/attachments/${editor.id}/${idx}/download`, { responseType: 'blob' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(res.data)
    link.download = a.filename || 'download'
    link.click()
    URL.revokeObjectURL(link.href)
  } catch (e) { /* ignore */ }
}

async function removeAttachment(idx) {
  try {
    await request.delete(`/api/learning/attachments/${editor.id}/${idx}`)
    editorAttachments.value.splice(idx, 1)
    ElMessage.success('已删除附件')
    await load()
  } catch (e) { /* ignore */ }
}

// ── 即问即讲讲解卡 ──
const explainVisible = ref(false)
const explainTopic = ref('')
const explainLoading = ref(false)
const explainTip = ref('')
const currentCard = ref(null)
const cards = ref([])
const toNoteLoading = ref(false)

async function loadCards() {
  try {
    const res = await request.get('/api/learning/explain/list')
    cards.value = res.data.items || []
  } catch (e) { /* ignore */ }
}

async function generateCard() {
  const topic = explainTopic.value.trim()
  if (!topic) return
  explainLoading.value = true
  explainTip.value = ''
  try {
    const res = await request.post('/api/learning/explain', { topic })
    currentCard.value = res.data.card
    if (res.data.source === 'rule') explainTip.value = 'AI 服务暂不可用，本卡片为系统框架提示，稍后可重新生成'
    await loadCards()
  } catch (e) {
    explainTip.value = '讲解卡生成失败，请稍后重试'
  }
  explainLoading.value = false
}

async function cardToNote(card) {
  toNoteLoading.value = true
  try {
    const res = await request.post(`/api/learning/explain/${card.id}/to-note`)
    ElMessage.success('已转存为笔记')
    explainVisible.value = false
    await load()
    if (res.data.note) {
      // 打开刚转存的笔记确认（转存结果以阅读视图呈现，不直接进编辑态）
      openViewer({ id: res.data.note.id, title: res.data.note.title, category: res.data.note.category, tags: res.data.note.tags, pinned: false, attachments: [] })
    }
  } catch (e) { /* ignore */ }
  toNoteLoading.value = false
}

async function removeCard(cid) {
  try {
    await request.delete(`/api/learning/explain/${cid}`)
    if (currentCard.value?.id === cid) currentCard.value = null
    await loadCards()
  } catch (e) { /* ignore */ }
}
</script>

<style scoped>
.study-notes { padding: 20px; max-width: 1100px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }
.header-actions { display: flex; gap: 10px; flex-shrink: 0; }

.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.count-tip { font-size: 13px; color: var(--text-muted); margin-left: auto; }

.note-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.note-card {
  background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px;
  padding: 16px 18px; cursor: pointer; transition: border-color 0.2s, transform 0.2s;
  display: flex; flex-direction: column; gap: 8px; min-width: 0;
}
.note-card:hover { border-color: #06b6d4; transform: translateY(-2px); }
.note-card.pinned { border-left: 3px solid #f59e0b; }
.note-card-head { display: flex; align-items: flex-start; gap: 8px; }
.note-title {
  flex: 1; font-size: 15px; font-weight: 600; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.pin-icon { color: #f59e0b; flex-shrink: 0; }
.pin-icon.hidden { opacity: 0; }
.note-card:hover .pin-icon.hidden { opacity: 0.6; }
.note-excerpt { font-size: 13px; color: var(--text-muted); line-height: 1.6; flex: 1;
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.note-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.note-time { font-size: 11px; color: var(--text-muted); margin-left: auto; }

.editor-body { display: flex; flex-direction: column; gap: 12px; }
.editor-row { display: flex; gap: 10px; }
.editor-tools { display: flex; align-items: center; gap: 14px; }
.editor-mode { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.mode-hint { font-size: 12px; color: var(--text-muted); }
.editor-preview { border: 1px solid var(--border-color); border-radius: 8px; padding: 12px 14px; min-height: 180px; }

.viewer-body { display: flex; flex-direction: column; gap: 10px; }
.viewer-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.viewer-content { font-size: 14px; color: var(--text-primary); padding-right: 12px; }
.viewer-attach { font-size: 12px; color: var(--text-muted); display: flex; align-items: center; flex-wrap: wrap; gap: 6px; border-top: 1px solid var(--border-color); padding-top: 10px; }
.editor-images { font-size: 12px; color: var(--text-muted); }
.img-label { margin-right: 6px; }
.img-link { color: #0891b2; margin-right: 10px; }
.editor-attach { font-size: 12px; color: var(--text-muted); display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.att-link { color: #0891b2; cursor: pointer; }
.att-link:hover { text-decoration: underline; }
.attach-hint { font-size: 12px; color: var(--text-muted); }

.explain-row { display: flex; gap: 10px; margin-bottom: 10px; }
.explain-tip { font-size: 12px; color: #f59e0b; margin-bottom: 10px; }
.explain-card-box {
  background: rgba(6, 182, 212, 0.05); border: 1px solid rgba(6, 182, 212, 0.25);
  border-radius: 12px; padding: 16px 18px; margin-bottom: 14px;
}
.explain-card-title { font-size: 15px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; }
.explain-card-content { font-size: 13px; line-height: 1.8; color: var(--text-primary); white-space: pre-wrap; margin-bottom: 12px; }
.history-cards { border-top: 1px solid var(--border-color); padding-top: 10px; }
.history-label { font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
.history-card-item { display: flex; align-items: center; gap: 8px; padding: 5px 4px; font-size: 13px; }
.hc-topic { flex: 1; color: var(--text-primary); cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hc-topic:hover { color: #0891b2; }
.hc-time { font-size: 11px; color: var(--text-muted); }
</style>
