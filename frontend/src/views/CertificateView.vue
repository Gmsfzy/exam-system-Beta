<template>
  <div class="certificate-view">
    <!-- ══════════ 列表模式：/learning/certificates ══════════ -->
    <template v-if="!isDetail">
      <div class="page-header">
        <div>
          <h1 class="page-title">我的证书</h1>
          <p class="page-subtitle">汇聚系统结业、跨模块与社会实践证书，一处纵览你的全部认证</p>
        </div>
        <div class="header-actions">
          <el-button v-if="isTeacher" @click="openReview">
            <el-icon><Stamp /></el-icon>&nbsp;核验中心
            <span v-if="reviewPendingCount" class="pend-dot">{{ reviewPendingCount }}</span>
          </el-button>
          <el-button type="primary" @click="openSubmit">
            <el-icon><Plus /></el-icon>&nbsp;上传证书
          </el-button>
        </div>
      </div>

      <el-tabs v-model="activeTab" class="cert-tabs">
        <el-tab-pane v-for="t in tabs" :key="t.key" :name="t.key">
          <template #label>
            <span class="tab-label">{{ t.label }}
              <span class="tab-count">{{ tabCount(t.key) }}</span>
            </span>
          </template>
        </el-tab-pane>
      </el-tabs>

      <div v-loading="loading" class="cert-body">
        <div v-if="activeTab === 'module'" class="tab-hint">
          <el-icon><InfoFilled /></el-icon>
          赛季证书在此汇总展示，也可前往
          <el-link type="primary" :underline="false" @click="$router.push('/competitions/certificates')">竞赛 › 我的赛季证书</el-link>
          查看独立列表。
        </div>
        <div v-if="filtered.length" class="cert-grid">
          <div v-for="c in filtered" :key="c.uid" class="cert-card"
               :class="'k-' + c.kind" @click="goDetail(c)">
            <div class="cc-ribbon" :class="'vs-' + c.verify_status">
              {{ c.verify_label || '' }}
            </div>
            <div class="cc-icon">{{ kindIcon(c) }}</div>
            <div class="cc-title">{{ c.title }}</div>
            <div class="cc-sub">{{ c.subtitle || c.category_label }}</div>
            <div class="cc-foot">
              <span class="cc-serial mono">{{ c.serial_no }}</span>
              <span class="cc-date">{{ (c.earned_at || '').slice(0, 10) }}</span>
            </div>
          </div>
        </div>
        <el-empty v-else-if="!loading" :image-size="90" :description="emptyText">
          <el-button type="primary" @click="openSubmit">上传我的第一张证书</el-button>
        </el-empty>
      </div>
    </template>

    <!-- ══════════ 详情模式：/learning/certificates/:kind/:id ══════════ -->
    <template v-else>
      <div class="page-header detail-header no-print">
        <el-button text @click="$router.push('/learning/certificates')">← 返回证书墙</el-button>
        <div class="header-actions">
          <el-button v-if="detail && detail.kind === 'module'"
                     @click="$router.push(`/competitions/certificates/${detail.id}`)">
            <el-icon><Trophy /></el-icon>&nbsp;在竞赛页查看
          </el-button>
          <el-button v-if="detail && detail.kind === 'social' && canManage" type="danger" plain
                     @click="removeSocial">删除</el-button>
          <el-button type="primary" @click="print">
            <el-icon><Printer /></el-icon>&nbsp;打印 / 导出 PDF
          </el-button>
        </div>
      </div>

      <div v-loading="loading" class="cert-stage">
        <!-- 系统结业：金色学术文凭 -->
        <div v-if="detail && detail.kind === 'system'" class="diploma dp-system">
          <div class="dp-border">
            <div class="dp-ornament top">✦  ✦</div>
            <p class="dp-brand">为学空间 · 终身学习认证</p>
            <h2 class="dp-title">学习路径结业证书</h2>
            <p class="dp-line">兹证明 <b class="dp-name">{{ detail.username || '学习者' }}</b></p>
            <p class="dp-line">已完成专业学习路径</p>
            <p class="dp-path">《{{ summary.path_title || '—' }}》</p>
            <p class="dp-line dp-small">
              专业：{{ summary.major_name || '—' }}
              <span class="dot">·</span>节点 {{ summary.nodes ?? '—' }} 个
              <span class="dot">·</span>知识点 {{ summary.kps ?? '—' }} 个
              <span class="dot">·</span>累计学习 {{ summary.minutes ?? 0 }} 分钟
            </p>
            <p class="dp-line">
              结业测评成绩
              <b class="dp-score">{{ detail.final_score != null ? (detail.final_score * 100).toFixed(0) : '—' }} 分</b>
              ，准予结业。
            </p>
            <div class="dp-foot">
              <div class="dp-foot-item">
                <span class="dp-foot-label">证书编号</span>
                <span class="dp-foot-val mono">{{ detail.serial_no }}</span>
              </div>
              <div class="dp-seal">🎓</div>
              <div class="dp-foot-item right">
                <span class="dp-foot-label">颁发日期</span>
                <span class="dp-foot-val">{{ (detail.earned_at || '').slice(0, 10) }}</span>
              </div>
            </div>
            <div class="dp-ornament bottom">✦ ⁘ </div>
          </div>
        </div>

        <!-- 跨模块赛季：奖牌绶带风 -->
        <div v-else-if="detail && detail.kind === 'module'" class="diploma dp-module"
             :style="{ '--mg': gradeTheme.grad, '--mb': gradeTheme.border }">
          <div class="dp-border">
            <div class="dp-ornament top">✦ ✦ ✦</div>
            <p class="dp-brand">为学空间 · 赛季竞技认证</p>
            <h2 class="dp-title">赛季竞技证书</h2>
            <div class="dp-medal">{{ gradeTheme.seal }}</div>
            <p class="dp-line">兹证明 <b class="dp-name">{{ detail.username || '竞技者' }}</b></p>
            <p class="dp-line">在 <b>{{ detail.season }}</b> 赛季中荣获</p>
            <p class="dp-path">{{ detail.grade_label }}</p>
            <p class="dp-line dp-small">
              最终段位 {{ detail.tier || '—' }}
              <span class="dot">·</span>赛季名次 {{ detail.rank ? ('第 ' + detail.rank + ' 名') : '—' }}
              <span class="dot">·</span>赛季积分 {{ detail.points ?? 0 }}
              <span class="dot">·</span>共 {{ detail.total_players ?? 0 }} 人参与
            </p>
            <div class="dp-foot">
              <div class="dp-foot-item">
                <span class="dp-foot-label">证书编号</span>
                <span class="dp-foot-val mono">{{ detail.serial_no }}</span>
              </div>
              <div class="dp-seal md">🏅</div>
              <div class="dp-foot-item right">
                <span class="dp-foot-label">颁发日期</span>
                <span class="dp-foot-val">{{ (detail.earned_at || '').slice(0, 10) }}</span>
              </div>
            </div>
            <div class="dp-ornament bottom">✦ ✦ </div>
          </div>
        </div>

        <!-- 社会/第三方：庄重学术 + 核验印章 -->
        <div v-else-if="detail && detail.kind === 'social'" class="diploma dp-social">
          <div class="dp-border">
            <div class="verify-stamp" :class="'vs-' + detail.verify_status">
              {{ detail.verify_label }}
            </div>
            <div class="dp-ornament top">❖ ✦ </div>
            <p class="dp-brand">{{ detail.issuer || '为学空间 · 社会实践认证' }}</p>
            <h2 class="dp-title">{{ detail.title }}</h2>
            <p class="dp-line">兹证明 <b class="dp-name">{{ detail.username || '持证人' }}</b></p>
            <p class="dp-line dp-small">获得 {{ detail.category_label }}类 证书认证</p>
            <p v-if="detail.grade" class="dp-line">成绩/等级：<b class="dp-score">{{ detail.grade }}</b></p>
            <div class="dp-meta">
              <div v-if="detail.cert_no"><span class="ml">证书编号</span><span class="mv mono">{{ detail.cert_no }}</span></div>
              <div v-if="detail.earned_date"><span class="ml">获证日期</span><span class="mv">{{ detail.earned_date.slice(0, 10) }}</span></div>
              <div><span class="ml">登记编号</span><span class="mv mono">{{ detail.serial_no }}</span></div>
            </div>
            <p v-if="detail.note" class="dp-note">{{ detail.note }}</p>
            <div v-if="detail.file" class="dp-file">
              <el-link type="primary" @click="downloadFile(detail)">
                <el-icon><Document /></el-icon>&nbsp;佐证附件：{{ detail.file.orig }}
              </el-link>
            </div>
            <div v-if="detail.verify_note" class="dp-verify-note">
              教师意见：{{ detail.verify_note }}
            </div>
            <div class="dp-ornament bottom">❖ ✦ ❖</div>
          </div>
        </div>
      </div>
    </template>

    <!-- ══════════ 上传证书弹窗 ══════════ -->
    <el-dialog v-model="submitVisible" title="上传社会 / 第三方证书" width="560px" top="8vh">
      <el-form :model="form" label-width="90px" label-position="right">
        <el-form-item label="证书类别">
          <el-select v-model="form.category" placeholder="请选择" style="width:100%">
            <el-option v-for="(label, key) in categoryLabels" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="证书名称" required>
          <el-input v-model="form.title" maxlength="200" placeholder="如：全国大学英语六级证书 / 一级建造师" />
        </el-form-item>
        <el-form-item label="发证机构">
          <el-input v-model="form.issuer" maxlength="120" placeholder="如：教育部教育考试院 / 住房和城乡建设部" />
        </el-form-item>
        <el-form-item label="证书编号">
          <el-input v-model="form.cert_no" maxlength="80" placeholder="现实证书编号（可留空）" />
        </el-form-item>
        <el-form-item label="成绩/等级">
          <el-input v-model="form.grade" maxlength="60" placeholder="如：425 分 / 合格 / 优秀" />
        </el-form-item>
        <el-form-item label="获证日期">
          <el-date-picker v-model="form.earned_date" type="date" value-format="YYYY-MM-DD"
                          placeholder="选择日期" style="width:100%" />
        </el-form-item>
        <el-form-item label="佐证附件">
          <input type="file" ref="fileInput" @change="onFilePick"
                 accept=".pdf,.jpg,.jpeg,.png,.gif,.webp,.doc,.docx" />
          <div class="file-hint">支持 PDF / 图片 / Word，≤50MB；教师将据此核验。</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" maxlength="2000" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="submitVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCert">提交核验</el-button>
      </template>
    </el-dialog>

    <!-- ══════════ 教师核验抽屉 ══════════ -->
    <el-drawer v-model="reviewVisible" title="证书核验中心 · 待核验" size="520px">
      <div v-loading="reviewLoading">
        <el-empty v-if="!pendingList.length && !reviewLoading" description="暂无待核验证书" />
        <div v-for="c in pendingList" :key="c.id" class="rv-card">
          <div class="rv-head">
            <span class="rv-title">{{ c.title }}</span>
            <el-tag size="small" type="info">{{ c.category_label }}</el-tag>
          </div>
          <div class="rv-meta">
            提交人：<b>{{ c.owner?.username || '—' }}</b>
            <span v-if="c.issuer"> · {{ c.issuer }}</span>
            <span v-if="c.grade"> · {{ c.grade }}</span>
          </div>
          <div v-if="c.file" class="rv-file">
            <el-link type="primary" @click="downloadFile(c)">
              <el-icon><Document /></el-icon>&nbsp;{{ c.file.orig }}
            </el-link>
          </div>
          <el-input v-model="c._note" size="small" placeholder="核验意见（可留空）" class="rv-note" />
          <div class="rv-actions">
            <el-button size="small" type="success" @click="doVerify(c, 'verify')">通过核验</el-button>
            <el-button size="small" type="danger" @click="doVerify(c, 'reject')">驳回</el-button>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, reactive, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const isDetail = computed(() => !!(route.params.kind && route.params.id))
const isTeacher = computed(() => auth.user?.role === 'teacher')

const loading = ref(false)
const items = ref([])
const tabsMeta = ref({})
const categoryLabels = ref({ language: '外语等级', it: '计算机等级', practice: '职业资格', academic: '学历学位', award: '竞赛获奖', other: '其他' })
const activeTab = ref('all')

const tabs = [
  { key: 'all', label: '全部' },
  { key: 'system', label: '系统结业' },
  { key: 'module', label: '跨模块' },
  { key: 'social', label: '社会第三方' },
]
function tabCount(key) {
  return tabsMeta.value[key] ?? 0
}
const filtered = computed(() =>
  activeTab.value === 'all' ? items.value : items.value.filter(c => c.group === activeTab.value))
const emptyText = computed(() =>
  activeTab.value === 'social'
    ? '还没有社会证书：四六级、计算机等级、职业资格、毕业学位等都可以上传登记'
    : '这个分类下还没有证书')

function kindIcon(c) {
  if (c.kind === 'system') return '🎓'
  if (c.kind === 'module') return { gold: '🥇', silver: '🥈', bronze: '🥉', merit: '' }[c.extra?.grade] || '🏅'
  return { language: '', it: '', practice: '️', academic: '📜', award: '🏆', other: '📃' }[c.category] || '📃'
}

async function loadWall() {
  loading.value = true
  try {
    const res = await request.get('/api/learning/certificates/wall')
    items.value = res.data.items || []
    tabsMeta.value = res.data.tabs || {}
    categoryLabels.value = res.data.category_labels || categoryLabels.value
    reviewPendingCount.value = res.data.pending_mine || 0
  } catch (e) { /* 拦截器已提示 */ }
  loading.value = false
}

function goDetail(c) {
  router.push(`/learning/certificates/${c.kind}/${c.id}`)
}

// ── 详情 ──
const detail = ref(null)
const summary = computed(() => detail.value?.summary || {})
const canManage = computed(() =>
  detail.value && (isTeacher.value || detail.value.owner?.id === auth.user?.id))
const gradeTheme = computed(() => {
  const g = detail.value?.grade
  return {
    gold:   { seal: '🥇', grad: 'radial-gradient(circle at 50% 0,#fff7e0,#fde68a 55%,#f59e0b)', border: '#b45309' },
    silver: { seal: '🥈', grad: 'radial-gradient(circle at 50% 0,#f8fafc,#e2e8f0 55%,#94a3b8)', border: '#475569' },
    bronze: { seal: '🥉', grad: 'radial-gradient(circle at 50% 0,#fdf0e6,#fcd9b6 55%,#c2703d)', border: '#9a3412' },
    merit:  { seal: '🏅', grad: 'radial-gradient(circle at 50% 0,#eef2ff,#e0e7ff 55%,#a5b4fc)', border: '#4338ca' },
  }[g] || { seal: '🏅', grad: 'radial-gradient(circle at 50% 0,#f8fafc,#e2e8f0 55%,#94a3b8)', border: '#475569' }
})

async function loadDetail() {
  loading.value = true
  detail.value = null
  try {
    const res = await request.get(`/api/learning/certificates/${route.params.kind}/${route.params.id}`)
    detail.value = res.data
  } catch (e) { /* ignore */ }
  loading.value = false
}

async function downloadFile(c) {
  // 附件下载走 API（携带 Authorization 头），以 blob 方式落盘，避开查询参数传 token
  if (!c || !c.file || !c.file.url) return
  try {
    const res = await request.get(c.file.url, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = c.file.orig || 'certificate'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  } catch (e) { /* 拦截器已提示 */ }
}

async function removeSocial() {
  try {
    await ElMessageBox.confirm('确定删除该证书？删除后不可恢复。', '删除确认', { type: 'warning' })
  } catch (e) { return }
  await request.delete(`/api/learning/certificates/social/${detail.value.id}`)
  ElMessage.success('已删除')
  router.push('/learning/certificates')
}

function print() { window.print() }

// ── 上传弹窗 ──
const submitVisible = ref(false)
const submitting = ref(false)
const fileInput = ref(null)
const pickedFile = ref(null)
const form = reactive({
  category: 'language', title: '', issuer: '', cert_no: '',
  grade: '', earned_date: '', note: '',
})
function openSubmit() {
  Object.assign(form, { category: 'language', title: '', issuer: '', cert_no: '', grade: '', earned_date: '', note: '' })
  pickedFile.value = null
  submitVisible.value = true
}
function onFilePick(ev) {
  pickedFile.value = ev.target.files?.[0] || null
}
async function submitCert() {
  if (!form.title.trim()) { ElMessage.warning('请填写证书名称'); return }
  submitting.value = true
  try {
    const fd = new FormData()
    Object.entries(form).forEach(([k, v]) => { if (v) fd.append(k, v) })
    if (pickedFile.value) fd.append('file', pickedFile.value)
    await request.post('/api/learning/certificates/social', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success('已提交，等待教师核验')
    submitVisible.value = false
    loadWall()
  } catch (e) { /* ignore */ }
  submitting.value = false
}

// ── 教师核验 ──
const reviewVisible = ref(false)
const reviewLoading = ref(false)
const pendingList = ref([])
const reviewPendingCount = ref(0)
async function openReview() {
  reviewVisible.value = true
  await loadPending()
}
async function loadPending() {
  reviewLoading.value = true
  try {
    const res = await request.get('/api/learning/certificates/social/pending')
    pendingList.value = (res.data.items || []).map(c => ({ ...c, _note: '' }))
  } catch (e) { /* ignore */ }
  reviewLoading.value = false
}
async function doVerify(c, action) {
  await request.post(`/api/learning/certificates/social/${c.id}/verify`,
    { action, note: c._note })
  ElMessage.success(action === 'verify' ? '已通过核验' : '已驳回')
  pendingList.value = pendingList.value.filter(x => x.id !== c.id)
  reviewPendingCount.value = Math.max(0, reviewPendingCount.value - 1)
}

function loadAll() {
  if (isDetail.value) loadDetail()
  else loadWall()
}
onMounted(loadAll)
watch(() => [route.params.kind, route.params.id], loadAll)
watch(isDetail, loadAll)
</script>

<style scoped>
.certificate-view { padding: 20px; max-width: 1080px; }

.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }
.header-actions { display: flex; gap: 10px; }
.detail-header { align-items: center; }
.pend-dot { display: inline-block; min-width: 18px; height: 18px; line-height: 18px; padding: 0 5px;
  margin-left: 6px; border-radius: 9px; background: #f56c6c; color: #fff; font-size: 12px; text-align: center; }

.cert-tabs { margin-bottom: 8px; }
.tab-hint { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  font-size: 13px; color: var(--text-muted); margin-bottom: 14px; padding: 10px 14px;
  background: rgba(99, 102, 241, 0.08); border: 1px solid rgba(99, 102, 241, 0.18); border-radius: 10px; }
.tab-label { font-size: 14px; }
.tab-count { display: inline-block; margin-left: 6px; padding: 0 7px; border-radius: 10px;
  background: rgba(99, 102, 241, 0.12); color: #6366f1; font-size: 12px; font-weight: 600; }

/* 卡片墙 */
.cert-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }
.cert-card { position: relative; cursor: pointer; padding: 22px 20px 16px; border-radius: 16px;
  background: var(--bg-card); border: 1px solid var(--border-color); overflow: hidden;
  transition: transform .25s, box-shadow .25s, border-color .25s; }
.cert-card:hover { transform: translateY(-4px); box-shadow: 0 12px 30px rgba(0,0,0,.12); }
.cert-card.k-system { border-top: 3px solid #d97706; }
.cert-card.k-module { border-top: 3px solid #6366f1; }
.cert-card.k-social { border-top: 3px solid #0ea5e9; }
.cc-icon { font-size: 34px; margin-bottom: 10px; }
.cc-title { font-size: 16px; font-weight: 700; color: var(--text-primary); line-height: 1.4; margin-bottom: 4px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.cc-sub { font-size: 12.5px; color: var(--text-muted); margin-bottom: 14px; min-height: 18px; }
.cc-foot { display: flex; justify-content: space-between; align-items: center;
  border-top: 1px dashed var(--border-color); padding-top: 10px; font-size: 11.5px; color: var(--text-muted); }
.cc-serial { letter-spacing: .5px; }
.cc-ribbon { position: absolute; top: 12px; right: -30px; transform: rotate(35deg);
  font-size: 11px; padding: 2px 34px; color: #fff; }
.cc-ribbon.vs-pending { background: #f59e0b; }
.cc-ribbon.vs-verified { background: #10b981; }
.cc-ribbon.vs-rejected { background: #ef4444; }
.cc-ribbon:empty { display: none; }

/* 详情舞台 */
.cert-stage { display: flex; justify-content: center; padding: 10px 0 40px; }
.diploma { width: 720px; max-width: 100%; border-radius: 8px; padding: 10px; }
.dp-border { border-radius: 4px; padding: 44px 48px 36px; text-align: center; position: relative; }
.dp-ornament { color: inherit; letter-spacing: 12px; font-size: 14px; margin: 0; opacity: .7; }
.dp-ornament.top { margin-bottom: 18px; }
.dp-ornament.bottom { margin-top: 22px; }
.dp-brand { font-size: 12px; letter-spacing: 4px; margin: 0 0 10px; opacity: .8; }
.dp-title { font-size: 28px; letter-spacing: 8px; margin: 0 0 24px; font-weight: 700; }
.dp-line { font-size: 15px; margin: 8px 0; }
.dp-line.dp-small { font-size: 12.5px; opacity: .8; }
.dp-line .dot { margin: 0 8px; opacity: .5; }
.dp-name { font-size: 19px; border-bottom: 2px solid currentColor; padding: 0 12px 2px; }
.dp-path { font-size: 22px; font-weight: 700; margin: 12px 0; }
.dp-score { font-size: 20px; }
.dp-medal { font-size: 56px; margin: 4px 0 10px; }
.dp-foot { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 34px; }
.dp-foot-item { display: flex; flex-direction: column; gap: 4px; min-width: 170px; text-align: left; }
.dp-foot-item.right { align-items: flex-end; text-align: right; }
.dp-foot-label { font-size: 11px; letter-spacing: 2px; opacity: .75; }
.dp-foot-val { font-size: 14px; font-weight: 600; }
.mono { font-family: Consolas, 'Courier New', monospace; letter-spacing: 1px; }
.dp-seal { width: 72px; height: 72px; border-radius: 50%; font-size: 34px;
  display: flex; align-items: center; justify-content: center; border: 2px solid currentColor; }
.dp-seal.md { font-size: 38px; }

/* 系统：金色学术 */
.dp-system { background: linear-gradient(160deg, #fffbeb 0%, #fef3c7 45%, #fde68a 100%);
  box-shadow: 0 18px 50px rgba(120, 80, 10, 0.25); }
.dp-system .dp-border { border: 3px double #b45309; outline: 1px solid #d97706; outline-offset: 6px; color: #451a03; }
.dp-system .dp-brand, .dp-system .dp-title { color: #78350f; }
.dp-system .dp-path, .dp-system .dp-score { color: #b45309; }
.dp-system .dp-seal { background: radial-gradient(circle, #fef3c7 0%, #fcd34d 75%); box-shadow: 0 0 0 4px rgba(180,83,9,.15); }

/* 赛季：奖牌渐变 */
.dp-module { background: var(--mg); box-shadow: 0 18px 50px rgba(30, 30, 80, 0.28); }
.dp-module .dp-border { border: 3px double var(--mb); outline: 1px solid var(--mb); outline-offset: 6px; color: #1e293b; }
.dp-module .dp-title, .dp-module .dp-path { color: var(--mb); }

/* 社会：庄重学术 */
.dp-social { background: linear-gradient(160deg, #f8fafc 0%, #eef2ff 50%, #e0e7ff 100%);
  box-shadow: 0 18px 50px rgba(40, 50, 120, 0.22); }
.dp-social .dp-border { border: 3px double #3730a3; outline: 1px solid #4f46e5; outline-offset: 6px; color: #1e1b4b; }
.dp-social .dp-title { color: #312e81; }
.dp-social .dp-meta { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px 34px; margin: 20px 0 6px; }
.dp-social .dp-meta > div { display: flex; flex-direction: column; gap: 3px; min-width: 150px; text-align: center; }
.dp-social .ml { font-size: 11px; letter-spacing: 2px; opacity: .7; }
.dp-social .mv { font-size: 14px; font-weight: 600; }
.dp-social .dp-note { font-size: 13px; margin: 14px auto 0; max-width: 520px; opacity: .85; line-height: 1.6; }
.dp-social .dp-file { margin-top: 14px; font-size: 13px; }
.dp-social .dp-verify-note { margin-top: 12px; font-size: 12.5px; color: #b45309; }
.verify-stamp { position: absolute; top: 22px; right: 26px; width: 88px; height: 88px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 700;
  border: 3px solid currentColor; transform: rotate(-14deg); opacity: .9; letter-spacing: 1px; }
.verify-stamp.vs-pending { color: #d97706; }
.verify-stamp.vs-verified { color: #059669; }
.verify-stamp.vs-rejected { color: #dc2626; }

/* 上传弹窗 */
.file-hint { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

/* 核验抽屉 */
.rv-card { border: 1px solid var(--border-color); border-radius: 12px; padding: 14px 16px; margin-bottom: 14px;
  background: var(--bg-card); }
.rv-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.rv-title { font-size: 15px; font-weight: 700; color: var(--text-primary); }
.rv-meta { font-size: 12.5px; color: var(--text-muted); margin-bottom: 8px; }
.rv-file { margin-bottom: 8px; font-size: 13px; }
.rv-note { margin-bottom: 10px; }
.rv-actions { display: flex; justify-content: flex-end; gap: 8px; }

@media (max-width: 640px) {
  .dp-border { padding: 30px 20px 24px; }
  .dp-title { font-size: 22px; letter-spacing: 4px; }
}
/* 打印：只保留证书 */
@media print {
  .no-print, .cert-tabs, .page-header.detail-header { display: none !important; }
  .cert-stage { padding: 0; }
  .diploma { box-shadow: none; width: 100%; }
  :deep(.layout-sidebar), :deep(.layout-header) { display: none !important; }
}
</style>
