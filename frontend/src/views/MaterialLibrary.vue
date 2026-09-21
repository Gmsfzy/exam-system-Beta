<template>
  <div class="mat-page">
    <div class="page-head">
      <h2>📚 资料库</h2>
      <div class="head-right">
        <el-tag v-if="quota" size="small" :type="quota.unlimited ? 'success' : (quota.remaining > 0 ? 'info' : 'danger')">
          {{ quota.unlimited ? 'AI 额度：教师不限量' : `今日 AI 剩 ${quota.remaining}/${quota.daily_limit}` }}
        </el-tag>
        <el-input v-model="filters.q" placeholder="搜索标题/内容" clearable style="width: 200px"
                  @keyup.enter="loadMaterials" @clear="loadMaterials" />
        <el-select v-model="filters.kind" placeholder="全部类型" clearable style="width: 130px" @change="loadMaterials">
          <el-option v-for="(label, k) in KINDS" :key="k" :value="k" :label="label" />
        </el-select>
        <el-button @click="openFolderCreate">新建文件夹</el-button>
        <el-button @click="openEdit(null)">手写资料</el-button>
        <el-button type="primary" @click="genVisible = true">AI 生成</el-button>
      </div>
    </div>

    <div class="mat-body">
      <!-- 左侧：文件夹/收藏导航 -->
      <div class="folder-panel">
        <div class="folder-item" :class="{ active: nav === 'all' }" @click="setNav('all')">
          <span>全部资料</span>
        </div>
        <div class="folder-item" :class="{ active: nav === 'fav' }" @click="setNav('fav')">
          <span>⭐ 我的收藏</span>
        </div>
        <el-divider content-position="left">文件夹</el-divider>
        <div v-for="f in folders" :key="f.id" class="folder-item"
             :class="{ active: nav === 'folder' && filters.folder_id === f.id }"
             @click="setNav('folder', f.id)">
          <span class="folder-name">📁 {{ f.name }}</span>
          <span class="folder-count">{{ f.material_count }}</span>
          <el-dropdown trigger="click" @command="cmd => onFolderCmd(cmd, f)">
            <span class="folder-more" @click.stop>⋯</span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除文件夹</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <el-empty v-if="!folders.length" description="暂无文件夹" :image-size="52" />
      </div>

      <!-- 右侧：资料列表 -->
      <div class="material-panel">
        <el-empty v-if="!loading && !materials.length" :description="nav === 'fav' ? '还没有收藏，去学习广场逛逛吧' : '资料库空空如也，点右上角 AI 生成或手写一条'" />
        <div v-for="m in materials" :key="m.id" class="mat-card" v-loading="loading">
          <div class="mat-main" @click="openView(m)">
            <div class="mat-title">
              {{ m.title }}
              <el-tag size="small" :type="KIND_TAG[m.kind] || 'info'" effect="plain">{{ KINDS[m.kind] || m.kind }}</el-tag>
              <el-tag v-if="m.source === 'ai'" size="small" effect="plain">AI</el-tag>
              <el-tag v-if="m.is_public" size="small" type="success" effect="plain">已公开</el-tag>
              <el-tag v-if="m.status === 'removed'" size="small" type="danger">已下架</el-tag>
            </div>
            <div class="mat-excerpt">{{ m.excerpt || '（无正文）' }}</div>
            <div class="mat-meta">
              <span v-if="m.subject">{{ m.subject }}</span>
              <span v-if="m.difficulty">· 难度 {{ m.difficulty }}</span>
              <span>· 👁 {{ m.views }}</span>
              <span>· ❤ {{ m.fav_count }}</span>
              <span>· {{ (m.updated_at || '').slice(0, 10) }}</span>
              <span v-if="m.author && nav === 'fav'">· 作者 {{ m.author }}</span>
            </div>
          </div>
          <div class="mat-ops">
            <template v-if="nav !== 'fav'">
              <el-button size="small" text @click="openEdit(m)">编辑</el-button>
              <el-button size="small" text @click="togglePublic(m)">{{ m.is_public ? '取消公开' : '公开' }}</el-button>
              <el-popconfirm title="删除该资料？" @confirm="removeMaterial(m)">
                <template #reference><el-button size="small" text type="danger">删除</el-button></template>
              </el-popconfirm>
            </template>
            <el-button v-else size="small" text @click="openView(m)">查看</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 查看对话框 -->
    <el-dialog v-model="viewVisible" :title="viewMat?.title" width="760px" top="6vh">
      <div v-if="viewMat" class="view-head">
        <el-tag size="small" effect="plain">{{ KINDS[viewMat.kind] || viewMat.kind }}</el-tag>
        <span class="view-meta">作者 {{ viewMat.author }} · 👁 {{ viewMat.views }} · ❤ {{ viewMat.fav_count }}
          <template v-if="viewMat.subject"> · {{ viewMat.subject }}</template></span>
        <el-button v-if="viewMat.owner_id !== myId && viewMat.is_public" size="small"
                   :type="viewMat.is_favorited ? 'warning' : 'default'" @click="favToggle(viewMat)">
          {{ viewMat.is_favorited ? '已收藏' : '收藏' }}
        </el-button>
        <el-button v-if="viewMat.owner_id !== myId" size="small" @click="openProfile(viewMat.owner_id)">TA 的主页</el-button>
      </div>
      <el-scrollbar max-height="60vh">
        <MdView :content="viewMat?.content || ''" />
      </el-scrollbar>
    </el-dialog>

    <!-- 编辑/新建对话框 -->
    <el-dialog v-model="editVisible" :title="editForm.id ? '编辑资料' : '手写资料'" width="640px">
      <el-form label-width="72px">
        <el-form-item label="标题"><el-input v-model="editForm.title" maxlength="200" placeholder="资料标题" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editForm.kind" style="width: 150px">
            <el-option v-for="(label, k) in KINDS" :key="k" :value="k" :label="label" />
          </el-select>
        </el-form-item>
        <el-form-item label="文件夹">
          <el-select v-model="editForm.folder_id" clearable placeholder="不归类" style="width: 200px">
            <el-option v-for="f in folders" :key="f.id" :value="f.id" :label="f.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="学科"><el-input v-model="editForm.subject" maxlength="50" placeholder="选填" style="width: 200px" /></el-form-item>
        <el-form-item label="正文">
          <el-input v-model="editForm.content" type="textarea" :rows="10" placeholder="支持 Markdown 语法与 ```mermaid 代码块" />
        </el-form-item>
        <el-form-item label="公开"><el-switch v-model="editForm.is_public" />
          <span class="tip">公开后出现在学习广场，可被收藏/举报</span></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMaterial">保存</el-button>
      </template>
    </el-dialog>

    <!-- AI 生成对话框 -->
    <el-dialog v-model="genVisible" title="AI 生成学习资料" width="560px">
      <el-form label-width="72px">
        <el-form-item label="主题">
          <el-input v-model="genForm.prompt" type="textarea" :rows="2" maxlength="500"
                    placeholder="想学什么？如：贝叶斯定理 / 数据结构期末总复习" />
        </el-form-item>
        <el-form-item label="形态">
          <el-select v-model="genForm.kind" style="width: 200px">
            <el-option value="auto" label="智能判断（推荐）" />
            <el-option v-for="k in AI_KINDS" :key="k" :value="k" :label="KINDS[k]" />
          </el-select>
        </el-form-item>
        <el-form-item label="学科"><el-input v-model="genForm.subject" maxlength="50" placeholder="选填" style="width: 200px" /></el-form-item>
        <el-form-item label="难度">
          <el-select v-model="genForm.difficulty" clearable placeholder="选填" style="width: 120px">
            <el-option value="easy" label="入门" /><el-option value="medium" label="进阶" /><el-option value="hard" label="挑战" />
          </el-select>
        </el-form-item>
        <el-form-item label="文件夹">
          <el-select v-model="genForm.folder_id" clearable placeholder="不归类" style="width: 200px">
            <el-option v-for="f in folders" :key="f.id" :value="f.id" :label="f.name" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="genVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="doGenerate">
          {{ generating ? '生成中，约需十几秒…' : '开始生成' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import MdView from '../components/MdView.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const myId = auth.user?.id
const KINDS = { video_script: '视频脚本', mindmap: '思维导图', lecture: '讲解稿', summary: '总结要点', quiz: '自测题组', manual: '手写' }
const AI_KINDS = ['video_script', 'mindmap', 'lecture', 'summary', 'quiz']
const KIND_TAG = { video_script: 'warning', mindmap: 'success', lecture: 'primary', summary: 'info', quiz: 'danger', manual: 'info' }

const loading = ref(false)
const materials = ref([])
const folders = ref([])
const quota = ref(null)
const nav = ref('all')
const filters = reactive({ q: '', kind: '', folder_id: null })

async function loadMaterials() {
  loading.value = true
  try {
    const params = { q: filters.q || undefined, kind: filters.kind || undefined }
    if (nav.value === 'fav') params.favorite = 1
    if (nav.value === 'folder') params.folder_id = filters.folder_id
    const { data } = await request.get('/api/learning/materials', { params })
    materials.value = data.items || []
  } finally {
    loading.value = false
  }
}

async function loadFolders() {
  const { data } = await request.get('/api/learning/folders')
  folders.value = data.items || []
}

async function loadQuota() {
  try {
    const { data } = await request.get('/api/learning/ai-quota')
    quota.value = data
  } catch (e) { /* 忽略 */ }
}

function setNav(n, fid) {
  nav.value = n
  filters.folder_id = n === 'folder' ? fid : null
  loadMaterials()
}

// ── 查看 / 编辑 / 删除 ──
const viewVisible = ref(false)
const viewMat = ref(null)
async function openView(m) {
  try {
    const { data } = await request.get(`/api/learning/materials/${m.id}`)
    viewMat.value = data.material
  } catch (e) { return }
  viewVisible.value = true
}

const editVisible = ref(false)
const saving = ref(false)
const editForm = reactive({ id: null, title: '', kind: 'manual', content: '', subject: '', folder_id: null, is_public: false })
function openEdit(m) {
  if (m) {
    Object.assign(editForm, { id: m.id, title: m.title, kind: m.kind, content: m.content || '',
      subject: m.subject || '', folder_id: m.folder_id, is_public: !!m.is_public })
    if (!editForm.content) {
      request.get(`/api/learning/materials/${m.id}`).then(({ data }) => { editForm.content = data.material.content || '' })
    }
  } else {
    Object.assign(editForm, { id: null, title: '', kind: 'manual', content: '', subject: '', folder_id: filters.folder_id || null, is_public: false })
  }
  editVisible.value = true
}

async function saveMaterial() {
  if (!editForm.title.trim()) return ElMessage.warning('请填写标题')
  saving.value = true
  try {
    const payload = { title: editForm.title, kind: editForm.kind, content: editForm.content,
      subject: editForm.subject, folder_id: editForm.folder_id, is_public: editForm.is_public }
    if (editForm.id) await request.put(`/api/learning/materials/${editForm.id}`, payload)
    else await request.post('/api/learning/materials', payload)
    ElMessage.success('已保存')
    editVisible.value = false
    loadMaterials(); loadFolders()
  } catch (e) { /* 拦截器提示 */ } finally { saving.value = false }
}

async function togglePublic(m) {
  try {
    await request.put(`/api/learning/materials/${m.id}`, { is_public: !m.is_public })
    ElMessage.success(m.is_public ? '已取消公开' : '已公开到学习广场')
    loadMaterials()
  } catch (e) { /* 拦截器提示 */ }
}

async function removeMaterial(m) {
  await request.delete(`/api/learning/materials/${m.id}`)
  ElMessage.success('已删除')
  loadMaterials(); loadFolders()
}

async function favToggle(m) {
  const { data } = await request.post(`/api/learning/materials/${m.id}/favorite`)
  m.is_favorited = data.favorited
  m.fav_count = data.fav_count
  ElMessage.success(data.message)
}

function openProfile(uid) {
  if (!uid) return
  router.push(`/learning/user/${uid}`)
}

// ── 文件夹 ──
async function openFolderCreate() {
  try {
    const { value } = await ElMessageBox.prompt('文件夹名称', '新建文件夹', { inputPattern: /\S+/, inputErrorMessage: '名称不能为空' })
    await request.post('/api/learning/folders', { name: value.trim() })
    ElMessage.success('已创建')
    loadFolders()
  } catch (e) { /* 取消 */ }
}

async function onFolderCmd(cmd, f) {
  if (cmd === 'rename') {
    try {
      const { value } = await ElMessageBox.prompt('新名称', '重命名文件夹', { inputValue: f.name, inputPattern: /\S+/, inputErrorMessage: '名称不能为空' })
      await request.put(`/api/learning/folders/${f.id}`, { name: value.trim() })
      loadFolders()
    } catch (e) { /* 取消 */ }
  } else if (cmd === 'delete') {
    try {
      await ElMessageBox.confirm('删除后文件夹内资料将回到「全部资料」，不会丢失', '删除文件夹', { type: 'warning' })
      await request.delete(`/api/learning/folders/${f.id}`)
      if (filters.folder_id === f.id) setNav('all')
      ElMessage.success('已删除')
      loadFolders(); loadMaterials()
    } catch (e) { /* 取消 */ }
  }
}

// ── AI 生成 ──
const genVisible = ref(false)
const generating = ref(false)
const genForm = reactive({ prompt: '', kind: 'auto', subject: '', difficulty: '', folder_id: null })
async function doGenerate() {
  if (!genForm.prompt.trim()) return ElMessage.warning('请输入知识点主题')
  generating.value = true
  try {
    const { data } = await request.post('/api/learning/materials/generate', {
      prompt: genForm.prompt, kind: genForm.kind, subject: genForm.subject,
      difficulty: genForm.difficulty, folder_id: genForm.folder_id
    })
    genVisible.value = false
    if (data.source === 'rule') ElMessage.warning('AI 服务暂不可用，已生成规则化框架大纲')
    else ElMessage.success(`已生成「${KINDS[data.kind] || data.kind}」`)
    genForm.prompt = ''
    loadMaterials(); loadFolders(); loadQuota()
    viewMat.value = data.material
    viewVisible.value = true
  } catch (e) {
    if (e.response?.status === 429) ElMessage.error(e.response.data?.message || '今日 AI 额度已用完')
  } finally { generating.value = false }
}

onMounted(() => { loadMaterials(); loadFolders(); loadQuota() })
</script>

<style scoped>
.mat-page { padding: 4px; }
.page-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }
.page-head h2 { margin: 0; }
.head-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mat-body { display: flex; gap: 14px; align-items: flex-start; }
.folder-panel { width: 200px; flex-shrink: 0; background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 8px; padding: 8px; }
.folder-item { display: flex; align-items: center; gap: 6px; padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 14px; }
.folder-item:hover { background: var(--el-fill-color-light, #f5f7fa); }
.folder-item.active { background: var(--el-color-primary-light-9, #ecf5ff); color: var(--el-color-primary, #409eff); }
.folder-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.folder-count { color: #909399; font-size: 12px; }
.folder-more { color: #909399; padding: 0 4px; }
.material-panel { flex: 1; min-width: 0; }
.mat-card { display: flex; align-items: center; gap: 8px; background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
.mat-main { flex: 1; min-width: 0; cursor: pointer; }
.mat-title { font-weight: 600; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.mat-excerpt { color: #606266; font-size: 13px; margin: 4px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mat-meta { color: #909399; font-size: 12px; display: flex; gap: 6px; flex-wrap: wrap; }
.mat-ops { flex-shrink: 0; }
.view-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.view-meta { color: #909399; font-size: 12px; flex: 1; }
.tip { color: #909399; font-size: 12px; margin-left: 10px; }
@media (max-width: 768px) { .mat-body { flex-direction: column; } .folder-panel { width: 100%; } }
</style>
