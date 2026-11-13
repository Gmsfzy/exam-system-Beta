<template>
  <div class="cert-square">
    <div class="page-header">
      <div>
        <h1 class="page-title">证书广场</h1>
        <p class="page-subtitle">同学们公开出来的荣誉证书：系统结业、跨模块赛季、社会第三方都在这一面墙上</p>
      </div>
      <div class="header-actions">
        <el-button @click="$router.push('/learning/certificates')">
          <el-icon><Medal /></el-icon>&nbsp;我的证书
        </el-button>
      </div>
    </div>

    <div class="filter-bar">
      <el-radio-group v-model="kind" @change="reload">
        <el-radio-button value="">全部类型</el-radio-button>
        <el-radio-button v-for="(label, k) in kindLabels" :key="k" :value="k">{{ label }}</el-radio-button>
      </el-radio-group>
      <el-select v-model="category" placeholder="全部类别" clearable style="width: 140px" @change="reload">
        <el-option v-for="(label, k) in categoryLabels" :key="k" :label="label" :value="k" />
      </el-select>
      <el-input v-model="q" placeholder="搜证书名称 / 发证机构" clearable style="width: 220px"
                :prefix-icon="Search" @keyup.enter="reload" @clear="reload" />
      <el-radio-group v-model="sort" @change="reload">
        <el-radio-button value="latest">最新获证</el-radio-button>
        <el-radio-button value="hot">最多浏览</el-radio-button>
      </el-radio-group>
      <span class="count-tip">共 {{ total }} 张</span>
    </div>

    <div class="notice">
      <el-icon><InfoFilled /></el-icon>
      广场只展示证书的荣誉信息：现实证书编号、教师核验意见与佐证附件不会外发；核验状态以角标形式跟着展示，未核验的证书也能公开。
    </div>

    <!-- 失败态与空态分开：接口挂了却告诉你「还没有人公开证书」，你会去翻开关而不是去查后端 -->
    <el-empty v-if="!loading && loadError" description="证书广场加载失败">
      <p class="err-tip">{{ loadError }}</p>
      <el-button type="primary" @click="load">重试</el-button>
    </el-empty>

    <el-empty v-else-if="!loading && !items.length" description="还没有人公开证书：在「我的证书」里打开某张证书的公开开关就会出现在这里" />

    <div v-loading="loading" class="sq-grid">
      <div v-for="c in items" :key="c.uid" class="sq-card" :class="'k-' + c.kind" @click="openDetail(c)">
        <div class="sq-ribbon" :class="'vs-' + c.verify_status">{{ c.verify_label }}</div>
        <div class="sq-icon">{{ kindIcon(c) }}</div>
        <div class="sq-title">{{ c.title }}</div>
        <div class="sq-sub">{{ c.subtitle || c.category_label }}</div>
        <div class="sq-owner">
          <a @click.stop="openProfile(c.owner.id)">{{ c.owner.username || '学习者' }}</a>
        </div>
        <div class="sq-foot">
          <span class="sq-date">{{ (c.earned_at || '').slice(0, 10) }}</span>
          <span class="sq-views">👁 {{ c.views }}</span>
        </div>
      </div>
    </div>

    <el-pagination v-if="total > size" v-model:current-page="page" :page-size="size" :total="total"
                   layout="prev, pager, next" class="pager" @current-change="load" />

    <!-- 详情：读的是后端脱敏视图，顺带累计一次浏览 -->
    <el-dialog v-model="detailVisible" :title="detail?.title || '证书详情'" width="600px" top="8vh">
      <div v-loading="detailLoading" class="dt-body">
        <div class="dt-head" :class="'k-' + detail?.kind">
          <span class="dt-icon">{{ kindIcon(detail || {}) }}</span>
          <div>
            <div class="dt-title">{{ detail?.title }}</div>
            <div class="dt-sub">{{ detail?.subtitle || detail?.category_label }}</div>
          </div>
          <el-tag size="small" effect="plain">{{ detail?.cert_kind_label }}</el-tag>
        </div>
        <div class="dt-rows">
          <div class="dt-row"><span class="dt-k">持证同学</span>
            <span class="dt-v"><a class="author" @click="openProfile(detail?.owner?.id)">{{ detail?.owner?.username || '—' }}</a></span>
          </div>
          <div v-if="detail?.issuer" class="dt-row"><span class="dt-k">发证机构</span><span class="dt-v">{{ detail.issuer }}</span></div>
          <div v-if="detail?.grade" class="dt-row"><span class="dt-k">成绩/等级</span><span class="dt-v">{{ detail.grade }}</span></div>
          <div class="dt-row"><span class="dt-k">获证时间</span><span class="dt-v">{{ (detail?.earned_at || '').slice(0, 10) || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">核验状态</span>
            <span class="dt-v">{{ detail?.verify_label }}<span class="dt-note">（系统颁发的证书默认可核验）</span></span>
          </div>
          <div class="dt-row"><span class="dt-k">站内编号</span><span class="dt-v mono">{{ detail?.serial_no }}</span></div>
          <div class="dt-row"><span class="dt-k">浏览</span><span class="dt-v">{{ detail?.views }} 次</span></div>
        </div>
        <p class="dt-tip">证书本体材料由持证人自己保管，广场不做代存；想问细节可以去他/她的主页看看公开的学习心得。</p>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="primary" @click="openProfile(detail?.owner?.id)">看看 TA 的主页</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Medal, InfoFilled } from '@element-plus/icons-vue'
import request from '../utils/request'
import { errTip } from '../utils/errs'

const router = useRouter()

const loading = ref(false)
const loadError = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(24)
const kind = ref('')
const category = ref('')
const q = ref('')
const sort = ref('latest')
const kindLabels = ref({ system: '系统结业', module: '跨模块', social: '社会第三方' })
const categoryLabels = ref({})

function kindIcon(c) {
  if (c.kind === 'system') return '🎓'
  if (c.kind === 'module') {
    return { gold: '🥇', silver: '🥈', bronze: '🥉' }[c.extra?.grade] || '🏅'
  }
  return { language: '🗣', it: '💻', practice: '🧰', academic: '📜', award: '🏆', other: '📃' }[c.category] || '📃'
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, size: size.value, sort: sort.value }
    if (kind.value) params.kind = kind.value
    if (category.value) params.category = category.value
    if (q.value.trim()) params.q = q.value.trim()
    const res = await request.get('/api/learning/certificates/square', { params })
    const d = res.data
    items.value = d.items || []
    total.value = d.total || 0
    if (d.kind_labels) kindLabels.value = d.kind_labels
    if (d.category_labels) categoryLabels.value = d.category_labels
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

function reload() {
  page.value = 1
  load()
}

// ── 详情：走统一详情接口，他人读到的是脱敏视图并由后端计一次浏览 ──
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)

async function openDetail(c) {
  detail.value = c
  detailVisible.value = true
  detailLoading.value = true
  try {
    const res = await request.get(`/api/learning/certificates/${c.kind}/${c.id}`)
    detail.value = res.data
    // 后端刚加了一次浏览，本地卡片同步一下，免得「看回来还是旧数字」
    const row = items.value.find(x => x.uid === c.uid)
    if (row) row.views = res.data.views ?? row.views
  } catch (e) { /* 拦截器已提示 */ }
  detailLoading.value = false
}

function openProfile(uid) {
  if (!uid) return
  router.push(`/learning/user/${uid}`)
}
</script>

<style scoped>
.cert-square { padding: 20px; max-width: 1180px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }
.header-actions { display: flex; gap: 10px; flex-shrink: 0; }

.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.count-tip { font-size: 13px; color: var(--text-muted); margin-left: auto; }
.err-tip { color: var(--el-text-color-regular, #606266); font-size: 13px; margin: 0 0 10px; }
.notice {
  display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-muted);
  background: rgba(139, 92, 246, 0.06); border: 1px solid rgba(139, 92, 246, 0.18);
  border-radius: 8px; padding: 8px 12px; margin-bottom: 16px;
}

.sq-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; min-height: 80px; }
.sq-card {
  position: relative; background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 14px; padding: 20px 16px 14px; cursor: pointer; overflow: hidden;
  display: flex; flex-direction: column; gap: 6px; text-align: center;
  transition: transform 0.2s, box-shadow 0.2s;
}
.sq-card:hover { transform: translateY(-3px); box-shadow: 0 8px 22px rgba(15, 23, 42, 0.12); }
.sq-card.k-system { background: linear-gradient(180deg, #fffdf5, #fdf3d8); border-color: #e7c86a; }
.sq-card.k-module { background: linear-gradient(180deg, #f7f8ff, #e8ebff); border-color: #b9c1f0; }
.sq-card.k-social { background: linear-gradient(180deg, #f6fdfa, #e2f5ea); border-color: #a7d8bc; }
.sq-ribbon {
  position: absolute; top: 8px; right: -26px; transform: rotate(38deg);
  font-size: 10px; padding: 2px 26px; color: #fff; background: #94a3b8;
}
.sq-ribbon.vs-verified { background: #16a34a; }
.sq-ribbon.vs-pending { background: #f59e0b; }
.sq-ribbon.vs-rejected { background: #dc2626; }
.sq-icon { font-size: 30px; line-height: 1; }
.sq-title { font-size: 14px; font-weight: 700; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.sq-sub { font-size: 12px; color: var(--text-muted); }
.sq-owner { font-size: 12px; color: #7c3aed; }
.sq-owner a { cursor: pointer; }
.sq-owner a:hover { text-decoration: underline; }
.sq-foot { display: flex; justify-content: center; gap: 12px; font-size: 11px; color: var(--text-muted); border-top: 1px dashed rgba(15, 23, 42, 0.12); padding-top: 8px; }
.pager { margin-top: 18px; justify-content: center; }

.dt-body { display: flex; flex-direction: column; gap: 12px; }
.dt-head { display: flex; align-items: center; gap: 12px; border-radius: 12px; padding: 14px 16px; }
.dt-head.k-system { background: linear-gradient(180deg, #fffdf5, #fdf3d8); }
.dt-head.k-module { background: linear-gradient(180deg, #f7f8ff, #e8ebff); }
.dt-head.k-social { background: linear-gradient(180deg, #f6fdfa, #e2f5ea); }
.dt-icon { font-size: 30px; }
.dt-title { font-size: 16px; font-weight: 700; color: var(--text-primary); }
.dt-sub { font-size: 12px; color: var(--text-muted); }
.dt-rows { display: flex; flex-direction: column; gap: 6px; }
.dt-row { display: flex; gap: 12px; font-size: 13px; }
.dt-k { width: 78px; flex-shrink: 0; color: var(--text-muted); }
.dt-v { color: var(--text-primary); }
.dt-note { font-size: 11px; color: var(--text-muted); }
.author { color: #0891b2; cursor: pointer; }
.author:hover { text-decoration: underline; }
.dt-tip { font-size: 12px; color: var(--text-muted); background: rgba(148, 163, 184, 0.12); border-radius: 8px; padding: 8px 10px; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
