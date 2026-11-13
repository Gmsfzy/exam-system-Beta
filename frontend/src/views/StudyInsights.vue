<template>
  <div class="insight-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习心得</h1>
        <p class="page-subtitle">回望一段周期，把感悟与收获、心得与总结、反思创造写下来——笔记记的是知识，心得留的是方法</p>
      </div>
      <div class="header-actions">
        <el-button @click="openDraft">
          <el-icon><MagicStick /></el-icon>&nbsp;AI 帮我起稿
        </el-button>
        <el-button type="primary" @click="openEditor(null)">
          <el-icon><Plus /></el-icon>&nbsp;写心得
        </el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-radio-group v-model="filterPeriod" @change="load">
        <el-radio-button v-for="t in periodTabs" :key="t.key" :value="t.key">
          {{ t.label }}<span class="tab-num">{{ t.count }}</span>
        </el-radio-button>
      </el-radio-group>
      <el-input v-model="q" placeholder="搜标题 / 正文 / 标签" clearable style="width: 220px"
                :prefix-icon="Search" @keyup.enter="load" @clear="load" />
      <el-select v-model="filterTag" placeholder="全部标签" clearable style="width: 140px" @change="load">
        <el-option v-for="t in allTags" :key="t" :label="t" :value="t" />
      </el-select>
      <el-button @click="load">刷新</el-button>
      <span class="count-tip">共 {{ total }} 篇</span>
    </div>

    <!-- 失败态与空态分开：接口 404 / 服务没起时说「还没有心得」会把人引向错误方向 -->
    <el-empty v-if="!loading && loadError" description="心得列表加载失败">
      <p class="err-tip">{{ loadError }}</p>
      <el-button type="primary" @click="load">重试</el-button>
    </el-empty>

    <el-empty v-else-if="!loading && !items.length" :description="emptyText">
      <el-button type="primary" @click="openEditor(null)">写第一篇心得</el-button>
    </el-empty>

    <div v-loading="loading" class="insight-grid">
      <div v-for="i in items" :key="i.id" class="ins-card" @click="openViewer(i)">
        <div class="ins-head">
          <span class="ins-title">{{ i.title }}</span>
          <el-tag v-if="i.is_public" size="small" type="success" effect="plain">已公开</el-tag>
          <el-tag v-else size="small" type="info" effect="plain">私有</el-tag>
        </div>
        <div class="ins-period">
          <span class="per-label">{{ i.period_label }}</span>
          <span class="per-text">{{ i.period_text }}</span>
          <span v-if="i.source === 'ai_draft'" class="ai-chip">AI 起稿</span>
        </div>
        <div class="ins-sections">
          <div v-for="(label, key) in SECTION_LABELS" :key="key" class="sec-line"
               :class="{ blank: !(i.previews || {})[key] }">
            <span class="sec-name">{{ label }}</span>
            <span class="sec-text">{{ (i.previews || {})[key] || '（未填写）' }}</span>
          </div>
        </div>
        <div class="ins-meta">
          <el-tag v-for="t in (i.tags || [])" :key="t" size="small" effect="plain">{{ t }}</el-tag>
          <span class="m-word">{{ i.word_count }} 字</span>
          <span v-if="i.share_post_id" class="m-share" title="已分享到社区">🔗</span>
          <span v-if="i.is_public" class="m-view">👁 {{ i.views }}</span>
          <span class="m-time">{{ fmtTime(i.updated_at) }}</span>
        </div>
      </div>
    </div>

    <el-pagination v-if="total > size" v-model:current-page="page" :page-size="size" :total="total"
                   layout="prev, pager, next" class="pager" @current-change="load" />

    <!-- ══ 阅读视图：三段并列渲染，公开/分享/编辑都在这里 ══ -->
    <el-dialog v-model="viewerVisible" :title="viewer.title || '心得'" width="800px" top="6vh">
      <div v-loading="viewerLoading" class="viewer-body">
        <div class="viewer-meta">
          <el-tag size="small" effect="plain">{{ viewer.period_label }}</el-tag>
          <span class="per-text">{{ viewer.period_text }}</span>
          <el-tag v-for="t in (viewer.tags || [])" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
          <span class="v-owner" v-if="viewer.owner">· {{ viewer.owner.username }}</span>
          <span class="v-time">{{ fmtTime(viewer.updated_at) }}</span>
        </div>
        <div v-for="(label, key) in SECTION_LABELS" :key="key" class="v-section">
          <div class="v-sec-head">
            <span class="v-sec-title">{{ label }}</span>
            <span v-if="!viewer[key]" class="v-sec-empty">这一段还没写</span>
          </div>
          <MdView :content="viewer[key] || ''" class="v-sec-body" />
        </div>
        <div v-if="isMine && viewer.share_post_id" class="v-shared">
          <el-link type="primary" :underline="false" @click="goPost(viewer.share_post_id)">
            已分享到社区中心，查看该帖
          </el-link>
        </div>
      </div>
      <template #footer>
        <template v-if="isMine">
          <el-button type="danger" plain @click="removeInsight">删除</el-button>
          <span class="switch-box">
            <el-switch v-model="viewer.is_public" @change="togglePublic" />
            <span class="switch-label">公开给同学看</span>
          </span>
          <el-button @click="shareToCommunity">分享到社区</el-button>
          <el-button type="primary" @click="editFromViewer">编辑</el-button>
        </template>
        <el-button v-else @click="viewerVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- ══ 编辑抽屉：固定三段，空段可以留空 ══ -->
    <el-drawer v-model="editorVisible" :title="editor.id ? '编辑心得' : '写心得'" size="48%">
      <div class="editor-body">
        <el-input v-model="editor.title" placeholder="标题（留空会按周期自动起名）" maxlength="200" show-word-limit />
        <div class="editor-row">
          <el-select v-model="editor.period_type" style="width: 120px">
            <el-option v-for="(label, k) in PERIOD_LABELS" :key="k" :label="label" :value="k" />
          </el-select>
          <el-date-picker v-model="editor.range" type="daterange" value-format="YYYY-MM-DD"
                          start-placeholder="起始日" end-placeholder="结束日" style="width: 260px" />
          <el-input v-model="editor.period_note" placeholder="阶段名（可留空）" maxlength="80" style="flex: 1" />
        </div>
        <el-select v-model="editor.tags" multiple filterable allow-create default-first-option
                   placeholder="标签（回车创建，最多 8 个）" style="width: 100%">
          <el-option v-for="t in allTags" :key="t" :label="t" :value="t" />
        </el-select>
        <p class="period-hint">
          {{ PERIOD_HINT[editor.period_type] || '按日/周/月不选日期时，自动取到最近的整周期' }}
        </p>
        <div v-for="(label, key) in SECTION_LABELS" :key="key" class="sec-block">
          <div class="sec-block-head">
            <span class="sec-block-title">{{ label }}</span>
            <span class="sec-block-hint">{{ SECTION_HINT[key] }}</span>
          </div>
          <el-input v-model="editor[key]" type="textarea" :rows="6" maxlength="4000" show-word-limit
                    :placeholder="SECTION_HINT[key]" />
        </div>
        <p class="tip">三段都允许留空，但至少写一段才能保存。</p>
        <div v-if="pendingDraft" class="draft-ask">
          <span class="draft-ask-text">
            本机还有一份 {{ fmtTime(new Date(pendingDraft.at).toISOString()) }} 没保存的内容（{{ pendingWords }} 字）
          </span>
          <el-button size="small" type="primary" plain @click="usePendingDraft">接着写</el-button>
          <el-button size="small" text @click="dropPendingDraft">丢掉</el-button>
        </div>
        <p v-if="draftState" class="tip draft-state">{{ draftState }}</p>
      </div>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-drawer>

    <!-- ══ AI 起稿：只喂聚合数据，草稿回来由本人改 ══ -->
    <el-dialog v-model="draftVisible" title="AI 依据学习数据起稿" width="560px">
      <div class="draft-row">
        <span class="draft-label">回看区间</span>
        <el-select v-model="draftDays" style="width: 130px">
          <el-option :value="3" label="最近 3 天" />
          <el-option :value="7" label="最近 7 天" />
          <el-option :value="14" label="最近 14 天" />
          <el-option :value="30" label="最近 30 天" />
        </el-select>
      </div>
      <el-input v-model="draftFocus" type="textarea" :rows="2" maxlength="200" show-word-limit
                placeholder="想重点聊什么？（可选，如：这周卡在矩阵那部分）" />
      <p class="draft-hint">只把你的题量、正确率、打卡、任务与薄弱知识点等聚合数据交给 AI，题目正文与笔记原文不会外传。</p>
      <div v-if="draftTip" class="draft-tip">{{ draftTip }}</div>
      <template #footer>
        <el-button @click="draftVisible = false">取消</el-button>
        <el-button type="primary" :loading="draftLoading" @click="runDraft">生成初稿</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, MagicStick } from '@element-plus/icons-vue'
import request from '../utils/request'
import { errTip } from '../utils/errs'
import MdView from '../components/MdView.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

// 段名与周期名以后端为单一来源，本地这份只做兜底（首帧不至于空标题）
const SECTION_LABELS = ref({ gains: '学习感悟与收获', summary: '我的心得与总结', reflection: '反思创造' })
const PERIOD_LABELS = ref({ day: '按日', week: '按周', month: '按月', stage: '阶段', custom: '自定义' })
const SECTION_HINT = {
  gains: '这段周期真实学到了什么？尽量落到具体的一件事、一个方法上',
  summary: '把这段周期概括成能回看的结论：做到了什么、还欠什么',
  reflection: '下一步可执行的动作与创造：拆题、编口诀、给同学讲、自己出题……',
}
const PERIOD_HINT = {
  day: '按日：不选日期就是今天',
  week: '按周：不选日期就是最近 7 天（含今天）',
  month: '按月：不选日期就是最近 30 天（含今天）',
  stage: '阶段：请填写起止日期，或给这一段起个名字',
  custom: '自定义：请填写起止日期，或写明这一段是什么',
}

const loading = ref(false)
const loadError = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(12)
const q = ref('')
const filterPeriod = ref('all')
const filterTag = ref('')
const allTags = ref([])
const tabs = ref({})

const periodTabs = computed(() => {
  const rows = [{ key: 'all', label: '全部', count: tabs.value.all || 0 }]
  for (const [k, label] of Object.entries(PERIOD_LABELS.value)) {
    rows.push({ key: k, label, count: tabs.value[k] || 0 })
  }
  return rows.filter(r => r.key === 'all' || r.count)
})
const emptyText = computed(() => filterPeriod.value === 'all' && !q.value
  ? '还没有心得：写完一段时间的学习，回来复盘三段吧'
  : '这个筛选下暂无心得')

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso
    : `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, size: size.value }
    if (filterPeriod.value !== 'all') params.period = filterPeriod.value
    if (filterTag.value) params.tag = filterTag.value
    if (q.value.trim()) params.q = q.value.trim()
    const res = await request.get('/api/learning/insights', { params })
    const d = res.data
    items.value = d.items || []
    total.value = d.total || 0
    tabs.value = d.tabs || {}
    if (d.section_labels) SECTION_LABELS.value = d.section_labels
    if (d.period_labels) PERIOD_LABELS.value = d.period_labels
    const seen = new Set()
    for (const it of items.value) for (const t of (it.tags || [])) seen.add(t)
    allTags.value = [...seen].sort()
    loadError.value = ''
  } catch (e) {
    // 拦截器已经弹了红色胶囊，这里只负责把页面从「假装没数据」改成「明说挂了」
    items.value = []
    total.value = 0
    loadError.value = errTip(e)
  }
  loading.value = false
}
onMounted(load)

// ── 阅读 ──
const viewerVisible = ref(false)
const viewerLoading = ref(false)
const viewer = ref({})
const isMine = computed(() => !viewer.value.owner || viewer.value.owner.id === auth.user?.id)

async function openViewer(row) {
  viewer.value = { ...row }
  viewerVisible.value = true
  viewerLoading.value = true
  try {
    // 列表只有 60 字预览，全文要拉详情（顺带把 owner/plan/kp 取回来）
    const res = await request.get(`/api/learning/insights/${row.id}`)
    viewer.value = res.data
  } catch (e) { /* 拦截器已提示 */ }
  viewerLoading.value = false
}

function editFromViewer() {
  const i = { ...viewer.value }
  viewerVisible.value = false
  openEditor(i)
}

function goPost(pid) {
  router.push(`/community/${pid}`)
}

async function togglePublic(on) {
  try {
    const res = await request.put(`/api/learning/insights/${viewer.value.id}/public`,
      { is_public: !!on })
    ElMessage.success(on ? '已公开，同学可在你的主页看到' : '已设为私有')
    viewer.value.views = res.data.views ?? viewer.value.views
    await load()
  } catch (e) {
    viewer.value.is_public = !on        // 失败回弹，别让开关显示成没生效的样子
  }
}

async function shareToCommunity() {
  try {
    const res = await request.post(`/api/learning/insights/${viewer.value.id}/share`, {})
    ElMessage.success(res.data.existed ? '这篇心得已经分享过了' : '已分享到社区中心')
    viewer.value.share_post_id = res.data.post_id
    viewer.value.is_public = true       // 分享即公开
    await load()
  } catch (e) { /* 拦截器已提示 */ }
}

async function removeInsight() {
  try {
    await ElMessageBox.confirm('确定删除这篇心得？已分享的社区帖不会跟着删除，需要的话请到帖子里删。', '确认')
  } catch (e) { return }
  await request.delete(`/api/learning/insights/${viewer.value.id}`)
  clearDraft(viewer.value.id)      // 顺手清掉这篇的本地暂存，免得留下没有主人的键
  ElMessage.success('已删除')
  viewerVisible.value = false
  await load()
}

// ── 编辑 ──
const editorVisible = ref(false)
const saving = ref(false)
const editor = reactive({
  id: null, title: '', period_type: 'week', range: null, period_note: '',
  tags: [], gains: '', summary: '', reflection: '', source: 'manual',
})

// ── 本机暂存（v7.20）──
// AI 起的稿子当时没点保存就找不回来了：服务端只在校验通过后才写 study_insight，
// ai_usage_log 又只有 action/status/cost_ms 不存正文。用 localStorage 兜住没提交的内容，
// 代价只是一句「回来接着写」。刻意不加后端 status='draft'：study_insight 没有状态列，
// 多一个草稿态，列表/广场/统计每处都要多挡一个条件，等真有跨设备续写需求再说。
const DRAFT_PREFIX = 'insight_draft:'
const draftState = ref('')
const pendingDraft = ref(null)   // 还没决定「接着写还是丢掉」的本机暂存，挂着时先不写，免得把那份盖掉
let draftTimer = null

function draftKeyFor(id) {
  return `${DRAFT_PREFIX}${auth.user?.id || 0}:${id || 'new'}`
}

function draftPayload() {
  return {
    title: editor.title, period_type: editor.period_type, range: editor.range,
    period_note: editor.period_note, tags: editor.tags, gains: editor.gains,
    summary: editor.summary, reflection: editor.reflection, source: editor.source,
    at: Date.now(),
  }
}

function hasWords(d) {
  return !!d && !!(String(d.gains || '') + String(d.summary || '') + String(d.reflection || '')).trim()
}

// 打开编辑器时那三段的快照：用来分辨「用户真的改过」与「只是把已存内容灌进来」。
// 少了这道判断，每点开一篇已存心得都会被 writeDraft 存一份跟库里一模一样的「暂存」，
// 下次再打开就弹横幅骗人说有份没保存的内容。
let editorBaseline = ''
function wordsSnapshot() {
  return [editor.gains, editor.summary, editor.reflection].join('\u0001')
}

function readDraft(id) {
  try {
    const raw = localStorage.getItem(draftKeyFor(id))
    return raw ? JSON.parse(raw) : null
  } catch (e) { return null }      // 坏 JSON 当成没有，不能因此挡住编辑器
}

function clearDraft(id) {
  try { localStorage.removeItem(draftKeyFor(id ?? editor.id)) } catch (e) { /* 清不掉也无害 */ }
}

function writeDraft() {
  if (pendingDraft.value) return
  const p = draftPayload()
  if (!hasWords(p)) { clearDraft(); draftState.value = ''; return }
  // 内容还是打开时那份（没动过），本机键里不该留「暂存」，存了反倒误导下一次打开的人
  if (wordsSnapshot() === editorBaseline) { clearDraft(); draftState.value = ''; return }
  try {
    localStorage.setItem(draftKeyFor(editor.id), JSON.stringify(p))
    draftState.value = `未保存的内容已留在本机 · ${fmtTime(new Date(p.at).toISOString())}`
  } catch (e) {
    // 隐私模式或超额写不进去，是本机的临时便利，不该打断用户打字
    draftState.value = ''
  }
}

watch(editor, () => {
  if (!editorVisible.value) return
  clearTimeout(draftTimer)
  draftTimer = setTimeout(writeDraft, 600)
}, { deep: true })

function applyDraft(d) {
  editor.title = d.title || ''
  editor.period_type = d.period_type || 'week'
  editor.range = Array.isArray(d.range) ? d.range : null
  editor.period_note = d.period_note || ''
  editor.tags = Array.isArray(d.tags) ? [...d.tags] : []
  editor.gains = d.gains || ''
  editor.summary = d.summary || ''
  editor.reflection = d.reflection || ''
  editor.source = d.source || 'manual'
}

// 恢复不静默做：暂存盖到刚点开的已保存内容上，等于替用户做了一个他没看见的决定。
// 所以只在编辑器里挂一条横幅，本人亲手点「接着写」才倒灌，不点就一直留着。
function showPendingDraft(id) {
  const d = readDraft(id)
  pendingDraft.value = hasWords(d) ? { ...d, _for: id } : null
}

const pendingWords = computed(() => {
  const d = pendingDraft.value
  if (!d) return 0
  return String(d.gains || '').length + String(d.summary || '').length + String(d.reflection || '').length
})

function usePendingDraft() {
  const d = pendingDraft.value
  if (!d) return
  applyDraft(d)
  pendingDraft.value = null
  draftState.value = '已恢复本机暂存，改成自己的话再保存'
  writeDraft()
}

function dropPendingDraft() {
  const d = pendingDraft.value
  if (!d) return
  clearDraft(d._for)
  pendingDraft.value = null
  draftState.value = ''
}

function openEditor(i, opts = {}) {
  editor.id = i ? i.id : null
  editor.source = i ? (i.source || 'manual') : 'manual'
  editor.title = i ? (i.title || '') : ''
  editor.period_type = i ? (i.period_type || 'week') : 'week'
  editor.range = i && i.period_start && i.period_end
    ? [i.period_start.slice(0, 10), i.period_end.slice(0, 10)] : null
  editor.period_note = i ? (i.period_note || '') : ''
  editor.tags = i ? [...(i.tags || [])] : []
  editor.gains = i ? (i.gains || '') : ''
  editor.summary = i ? (i.summary || '') : ''
  editor.reflection = i ? (i.reflection || '') : ''
  editorBaseline = wordsSnapshot()
  draftState.value = ''
  clearTimeout(draftTimer)
  editorVisible.value = true
  // AI 起稿马上要往这三段里灌新内容，横幅这时只会自相矛盾（覆盖与否由 runDraft 自己问过）
  if (opts.skipDraft) { pendingDraft.value = null; return }
  showPendingDraft(editor.id)
}

async function save() {
  if (!(editor.gains.trim() || editor.summary.trim() || editor.reflection.trim())) {
    ElMessage.warning('三段里至少要填写一段')
    return
  }
  saving.value = true
  const payload = {
    title: editor.title.trim(), period_type: editor.period_type,
    period_start: editor.range?.[0] || null, period_end: editor.range?.[1] || null,
    period_note: editor.period_note.trim() || null, tags: editor.tags,
    gains: editor.gains, summary: editor.summary, reflection: editor.reflection,
  }
  try {
    if (editor.id) {
      await request.put(`/api/learning/insights/${editor.id}`, payload)
    } else {
      payload.source = editor.source
      await request.post('/api/learning/insights', payload)
    }
    // 保存成功才清暂存：失败时用户写的字比什么都金贵
    clearDraft(editor.id)
    draftState.value = ''
    ElMessage.success('心得已保存')
    editorVisible.value = false
    await load()
  } catch (e) { /* 拦截器已提示 */ }
  saving.value = false
}

// ── AI 起稿 ──
const draftVisible = ref(false)
const draftLoading = ref(false)
const draftTip = ref('')
const draftDays = ref(7)
const draftFocus = ref('')

function openDraft() {
  draftTip.value = ''
  draftVisible.value = true
}

async function runDraft() {
  // 新初稿会盖掉本机那份没保存的暂存，覆盖用户已经写下的字不能是静默的。
  // 先问再调 AI：等初稿跑完几十秒再问，一取消就白烧一次额度；生成失败时旧暂存也原样留着。
  const old = readDraft(null)
  if (hasWords(old)) {
    try {
      await ElMessageBox.confirm(
        `本机还有一份 ${fmtTime(new Date(old.at).toISOString())} 没保存的内容，生成新初稿会把它覆盖掉。`,
        '确认', { confirmButtonText: '继续生成', cancelButtonText: '取消', type: 'warning' })
    } catch (e) { return }
  }
  draftLoading.value = true
  draftTip.value = ''
  try {
    // 后端 AI 读超时 180s，浏览器侧放宽到 200s，避免前端先 ERR_ABORTED
    const res = await request.post('/api/learning/insights/ai-draft',
      { days: draftDays.value, focus: draftFocus.value.trim() || null }, { timeout: 200000 })
    const d = res.data.draft || {}
    draftVisible.value = false
    openEditor(null, { skipDraft: true })
    editor.title = d.title || ''
    editor.gains = d.gains || ''
    editor.summary = d.summary || ''
    editor.reflection = d.reflection || ''
    editor.source = 'ai_draft'
    ElMessage.success(res.data.degraded
      ? 'AI 暂不可用，已按你的学习数据列出待填写框架'
      : '初稿已填进编辑器，改成自己的话再保存')
  } catch (e) {
    draftTip.value = '生成失败，可稍后重试或直接自己写'
  }
  draftLoading.value = false
}
</script>

<style scoped>
.insight-page { padding: 20px; max-width: 1120px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }
.header-actions { display: flex; gap: 10px; flex-shrink: 0; }

.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
.tab-num { margin-left: 4px; font-size: 11px; opacity: 0.7; }
.count-tip { font-size: 13px; color: var(--text-muted); margin-left: auto; }
.err-tip { color: var(--el-text-color-regular, #606266); font-size: 13px; margin: 0 0 10px; }

.insight-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; min-height: 60px; }
.ins-card {
  background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px;
  padding: 15px 17px; cursor: pointer; transition: border-color 0.2s, transform 0.2s;
  display: flex; flex-direction: column; gap: 9px;
}
.ins-card:hover { border-color: #8b5cf6; transform: translateY(-2px); }
.ins-head { display: flex; align-items: center; gap: 8px; }
.ins-title { flex: 1; font-size: 15px; font-weight: 600; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ins-period { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-muted); flex-wrap: wrap; }
.per-label { background: rgba(139, 92, 246, 0.1); color: #7c3aed; border-radius: 4px; padding: 1px 6px; }
.per-text { color: var(--text-muted); }
.ai-chip { font-size: 11px; color: #0891b2; }
.ins-sections { display: flex; flex-direction: column; gap: 5px; }
.sec-line { display: flex; gap: 8px; font-size: 12px; line-height: 1.6; }
.sec-line.blank .sec-text { color: var(--text-muted); opacity: 0.6; }
.sec-name { flex-shrink: 0; width: 88px; color: #7c3aed; }
.sec-text { flex: 1; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.ins-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 11px; color: var(--text-muted); }
.m-time { margin-left: auto; }
.pager { margin-top: 18px; justify-content: center; }

.viewer-body { display: flex; flex-direction: column; gap: 12px; }
.viewer-meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 12px; color: var(--text-muted); }
.v-time { margin-left: auto; }
.v-section { border: 1px solid var(--border-color); border-radius: 10px; padding: 12px 14px; }
.v-sec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.v-sec-title { font-size: 13px; font-weight: 700; color: #7c3aed; }
.v-sec-empty { font-size: 11px; color: var(--text-muted); }
.v-sec-body { font-size: 14px; color: var(--text-primary); }
.v-shared { border-top: 1px solid var(--border-color); padding-top: 8px; font-size: 12px; }
.switch-box { display: inline-flex; align-items: center; gap: 8px; margin-right: 10px; }
.switch-label { font-size: 12px; color: var(--text-muted); }

.editor-body { display: flex; flex-direction: column; gap: 12px; }
.editor-row { display: flex; gap: 10px; flex-wrap: wrap; }
.period-hint { font-size: 12px; color: var(--text-muted); margin: -4px 0 0; }
.sec-block { border-top: 1px dashed var(--border-color); padding-top: 10px; }
.sec-block-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.sec-block-title { font-size: 13px; font-weight: 700; color: #7c3aed; }
.sec-block-hint { font-size: 11px; color: var(--text-muted); }
.tip { font-size: 12px; color: var(--text-muted); }

.draft-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.draft-label { font-size: 13px; color: var(--text-primary); }
.draft-hint { font-size: 12px; color: var(--text-muted); margin: 10px 0 0; }
.draft-tip { font-size: 12px; color: #f59e0b; margin-top: 8px; }
.draft-state { color: #0891b2; }
.draft-ask {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  background: rgba(8, 145, 178, 0.08); border: 1px solid rgba(8, 145, 178, 0.3);
  border-radius: 8px; padding: 8px 10px;
}
.draft-ask-text { font-size: 12px; color: #0e7490; flex: 1; min-width: 180px; }
</style>
