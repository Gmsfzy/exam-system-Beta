<template>
  <div class="exp-page">
    <div class="page-head">
      <h2>🌐 学习广场</h2>
      <div class="head-right">
        <el-input v-model="q" placeholder="搜索公开资料" clearable style="width: 200px" @keyup.enter="load" @clear="load" />
        <el-select v-model="kind" placeholder="全部类型" clearable style="width: 120px" @change="load">
          <el-option v-for="(label, k) in KINDS" :key="k" :value="k" :label="label" />
        </el-select>
        <el-select v-model="subject" placeholder="全部学科" clearable filterable style="width: 130px" @change="load">
          <el-option v-for="s in subjects" :key="s" :value="s" :label="s" />
        </el-select>
        <el-radio-group v-model="sort" @change="load">
          <el-radio-button value="latest">最新</el-radio-button>
          <el-radio-button value="hot">最热</el-radio-button>
        </el-radio-group>
        <el-button v-if="isTeacher" @click="openReports">
          举报处理<el-badge v-if="reportCount" :value="reportCount" class="rp-badge" />
        </el-button>
        <el-dropdown trigger="click" @command="onUserPick">
          <el-button>找同学</el-button>
          <template #dropdown>
            <el-dropdown-menu v-if="userOptions.length">
              <el-dropdown-item v-for="u in userOptions" :key="u.user_id" :command="u">
                {{ u.username }}（{{ u.role === 'teacher' ? '教师' : '同学' }} · {{ u.public_count }} 篇公开）
              </el-dropdown-item>
            </el-dropdown-menu>
            <el-dropdown-menu v-else><el-dropdown-item disabled>先输入名字搜索</el-dropdown-item></el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-input v-model="userQ" placeholder="搜用户" size="small" style="width: 120px" @input="searchUsers" />
      </div>
    </div>

    <el-empty v-if="!loading && !items.length" description="还没有人公开资料，去资料库点亮第一篇吧" />
    <div class="exp-grid">
      <div v-for="m in items" :key="m.id" class="exp-card">
        <div class="exp-title" @click="openView(m)">
          {{ m.title }}
          <el-tag size="small" effect="plain" :type="KIND_TAG[m.kind]">{{ KINDS[m.kind] || m.kind }}</el-tag>
        </div>
        <div class="exp-excerpt" @click="openView(m)">{{ m.excerpt || '（无正文）' }}</div>
        <div class="exp-meta">
          <a class="author" @click="openProfile(m.owner_id)">{{ m.author }}</a>
          <span v-if="m.subject">· {{ m.subject }}</span>
          <span>· 👁 {{ m.views }}</span>
          <span>· ❤ {{ m.fav_count }}</span>
        </div>
        <div class="exp-ops">
          <el-button size="small" :type="m.is_favorited ? 'warning' : 'default'" @click="favToggle(m)">
            {{ m.is_favorited ? '已收藏' : '收藏' }}
          </el-button>
          <el-button v-if="m.owner_id !== myId" size="small" text @click="openReport(m)">举报</el-button>
        </div>
      </div>
    </div>

    <!-- 查看对话框 -->
    <el-dialog v-model="viewVisible" :title="viewMat?.title" width="760px" top="6vh">
      <div v-if="viewMat" class="view-head">
        <el-tag size="small" effect="plain">{{ KINDS[viewMat.kind] || viewMat.kind }}</el-tag>
        <span class="view-meta">作者
          <a class="author" @click="openProfile(viewMat.owner_id)">{{ viewMat.author }}</a>
          · 👁 {{ viewMat.views }} · ❤ {{ viewMat.fav_count }}</span>
        <el-button v-if="viewMat.owner_id !== myId && viewMat.is_public" size="small"
                   :type="viewMat.is_favorited ? 'warning' : 'default'" @click="favToggle(viewMat)">
          {{ viewMat.is_favorited ? '已收藏' : '收藏' }}
        </el-button>
      </div>
      <el-scrollbar max-height="60vh">
        <MdView :content="viewMat?.content || ''" />
      </el-scrollbar>
    </el-dialog>

    <!-- 举报对话框 -->
    <el-dialog v-model="reportVisible" title="举报资料" width="420px">
      <p class="rp-hint">举报「{{ reportMat?.title }}」，教师核实后处理</p>
      <el-input v-model="reportReason" type="textarea" :rows="3" maxlength="200" show-word-limit
                placeholder="请说明违规原因（色情暴力/抄袭/虚假内容…）" />
      <template #footer>
        <el-button @click="reportVisible = false">取消</el-button>
        <el-button type="danger" :loading="reporting" @click="submitReport">提交举报</el-button>
      </template>
    </el-dialog>

    <!-- 教师：举报处理抽屉 -->
    <el-drawer v-model="rpDrawer" title="举报处理（待处理）" size="520px">
      <el-empty v-if="!reports.length" description="没有待处理举报" />
      <div v-for="r in reports" :key="r.id" class="rp-item">
        <div class="rp-title">{{ r.material_title }}
          <el-tag size="small" type="danger" effect="plain">被{{ r.reporter }}举报</el-tag></div>
        <div class="rp-reason">原因：{{ r.reason || '未填写' }} · 作者 {{ r.author }} · {{ (r.created_at || '').slice(0, 16) }}</div>
        <div class="rp-ops">
          <el-button size="small" @click="openReportView(r)">查看资料</el-button>
          <el-button size="small" type="danger" @click="handleReport(r, 'remove')">下架</el-button>
          <el-button size="small" @click="handleReport(r, 'reject')">驳回举报</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import MdView from '../components/MdView.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const isTeacher = computed(() => auth.user?.role === 'teacher')
const myId = auth.user?.id
const KINDS = { video_script: '视频脚本', mindmap: '思维导图', lecture: '讲解稿', summary: '总结要点', quiz: '自测题组', manual: '手写' }
const KIND_TAG = { video_script: 'warning', mindmap: 'success', lecture: '', summary: 'info', quiz: 'danger', manual: 'info' }

const loading = ref(false)
const items = ref([])
const subjects = ref([])
const q = ref('')
const kind = ref('')
const subject = ref('')
const sort = ref('latest')

async function load() {
  loading.value = true
  try {
    const { data } = await request.get('/api/learning/explore', {
      params: { q: q.value || undefined, kind: kind.value || undefined,
                subject: subject.value || undefined, sort: sort.value }
    })
    items.value = data.items || []
    subjects.value = data.subjects || []
  } finally { loading.value = false }
}

async function openView(m) {
  try {
    const { data } = await request.get(`/api/learning/materials/${m.id}`)
    viewMat.value = data.material
    viewVisible.value = true
  } catch (e) { /* 拦截器提示 */ }
}
const viewVisible = ref(false)
const viewMat = ref(null)

async function favToggle(m) {
  try {
    const { data } = await request.post(`/api/learning/materials/${m.id}/favorite`)
    m.is_favorited = data.favorited
    m.fav_count = data.fav_count
    ElMessage.success(data.message)
  } catch (e) { /* 拦截器提示 */ }
}

// ── 举报 ──
const reportVisible = ref(false)
const reportMat = ref(null)
const reportReason = ref('')
const reporting = ref(false)
function openReport(m) {
  reportMat.value = m
  reportReason.value = ''
  reportVisible.value = true
}
async function submitReport() {
  reporting.value = true
  try {
    const { data } = await request.post(`/api/learning/materials/${reportMat.value.id}/report`,
      { reason: reportReason.value })
    ElMessage.success(data.message)
    reportVisible.value = false
  } catch (e) { /* 409 等由拦截器提示 */ } finally { reporting.value = false }
}

// ── 教师举报处理 ──
const rpDrawer = ref(false)
const reports = ref([])
const reportCount = ref(0)
async function openReports() {
  await loadReports()
  rpDrawer.value = true
}
async function loadReports() {
  try {
    const { data } = await request.get('/api/learning/material-reports', { params: { status: 'pending' } })
    reports.value = data.items || []
    reportCount.value = reports.value.length
  } catch (e) { /* 拦截器提示 */ }
}
function openReportView(r) {
  request.get(`/api/learning/materials/${r.material_id}`).then(({ data }) => {
    viewMat.value = data.material
    viewVisible.value = true
  }).catch(() => ElMessage.warning('资料可能已被下架或删除'))
}
async function handleReport(r, action) {
  let note = ''
  if (action === 'remove') {
    try {
      const { value } = await ElMessageBox.prompt('下架说明（将通知作者）', '下架资料', { inputPattern: /\S+/, inputErrorMessage: '请填写说明' })
      note = value
    } catch (e) { return }
  }
  try {
    const { data } = await request.post(`/api/learning/material-reports/${r.id}/handle`,
      { action, note })
    ElMessage.success(data.message)
    loadReports(); load()
  } catch (e) { /* 拦截器提示 */ }
}

// ── 找同学（用户搜索 → 主页） ──
const userQ = ref('')
const userOptions = ref([])
let userTimer = null
function searchUsers() {
  clearTimeout(userTimer)
  if (!userQ.value.trim()) { userOptions.value = []; return }
  userTimer = setTimeout(async () => {
    try {
      const { data } = await request.get('/api/learning/users/search', { params: { q: userQ.value.trim() } })
      userOptions.value = data.items || []
    } catch (e) { /* 忽略 */ }
  }, 350)
}
function onUserPick(u) {
  userQ.value = ''
  openProfile(u.user_id)
}
function openProfile(uid) {
  if (uid) router.push(`/learning/user/${uid}`)
}

onMounted(() => {
  load()
  if (isTeacher.value) loadReports()
})
</script>

<style scoped>
.exp-page { padding: 4px; }
.page-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }
.page-head h2 { margin: 0; }
.head-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.exp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.exp-card { background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 10px; padding: 14px; display: flex; flex-direction: column; gap: 6px; }
.exp-title { font-weight: 600; cursor: pointer; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.exp-title:hover { color: var(--el-color-primary, #409eff); }
.exp-excerpt { color: #606266; font-size: 13px; cursor: pointer; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 38px; }
.exp-meta { color: #909399; font-size: 12px; display: flex; gap: 5px; flex-wrap: wrap; align-items: center; }
.author { color: var(--el-color-primary, #409eff); cursor: pointer; }
.exp-ops { display: flex; justify-content: flex-end; gap: 4px; }
.view-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.view-meta { color: #909399; font-size: 12px; flex: 1; }
.rp-hint { color: #606266; font-size: 13px; margin: 0 0 8px; }
.rp-item { border-bottom: 1px solid var(--el-border-color-lighter, #ebeef5); padding: 10px 0; }
.rp-title { font-weight: 600; display: flex; align-items: center; gap: 8px; }
.rp-reason { color: #909399; font-size: 12px; margin: 6px 0; }
.rp-ops { display: flex; gap: 6px; justify-content: flex-end; }
:deep(.rp-badge) { margin-left: 2px; }
</style>
