<template>
  <div class="certificate-view">
    <!-- 列表模式：/learning/certificates -->
    <template v-if="!certId">
      <div class="page-header">
        <div>
          <h1 class="page-title">我的证书</h1>
          <p class="page-subtitle">完成学习路径并通过结业测评后自动颁发</p>
        </div>
      </div>

      <div v-loading="loading">
        <div v-if="list.length" class="cert-grid">
          <div v-for="c in list" :key="c.id" class="cert-item" @click="$router.push(`/learning/certificates/${c.id}`)">
            <div class="cert-medal">🏅</div>
            <div class="cert-meta">
              <div class="cert-title">{{ c.path_title || '学习路径结业证书' }}</div>
              <div class="cert-sub">{{ c.serial_no }} · {{ (c.earned_at || '').slice(0, 10) }}</div>
              <div class="cert-score">终测成绩 {{ c.final_score != null ? (c.final_score * 100).toFixed(0) + '%' : '-' }}</div>
            </div>
            <el-icon class="cert-arrow"><ArrowRight /></el-icon>
          </div>
        </div>
        <el-empty v-else-if="!loading" :image-size="80" description="还没有证书：学完一条路径并参加结业测评吧">
          <el-button type="primary" @click="$router.push('/learning/paths')">去找路径</el-button>
        </el-empty>
      </div>
    </template>

    <!-- 详情模式：/learning/certificates/:id -->
    <template v-else>
      <div class="page-header detail-header no-print">
        <el-button text @click="$router.push('/learning/certificates')">← 返回证书列表</el-button>
        <div class="header-actions">
          <el-button type="primary" @click="print">
            <el-icon><Printer /></el-icon>&nbsp;打印 / 导出 PDF
          </el-button>
        </div>
      </div>

      <div v-loading="loading" class="cert-stage">
        <div v-if="cert" ref="certRef" class="diploma">
          <div class="dp-border">
            <div class="dp-ornament top">✦ ⁘ ✦</div>
            <p class="dp-brand">智汇学场 · 终身学习认证</p>
            <h2 class="dp-title">学习路径结业证书</h2>
            <p class="dp-line">兹证明 <b class="dp-name">{{ cert.username || '学习者' }}</b></p>
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
              <b class="dp-score">{{ cert.final_score != null ? (cert.final_score * 100).toFixed(0) : '—' }} 分</b>
              ，准予结业。
            </p>
            <div class="dp-foot">
              <div class="dp-foot-item">
                <span class="dp-foot-label">证书编号</span>
                <span class="dp-foot-val mono">{{ cert.serial_no }}</span>
              </div>
              <div class="dp-seal">🎓</div>
              <div class="dp-foot-item right">
                <span class="dp-foot-label">颁发日期</span>
                <span class="dp-foot-val">{{ (cert.earned_at || '').slice(0, 10) }}</span>
              </div>
            </div>
            <div class="dp-ornament bottom">✦ ⁘ ✦</div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import request from '../utils/request'

const route = useRoute()
const certId = computed(() => route.params.id)

const loading = ref(false)
const list = ref([])
const cert = ref(null)
const certRef = ref(null)
const summary = computed(() => cert.value?.summary || {})

async function loadAll() {
  loading.value = true
  try {
    if (certId.value) {
      const res = await request.get(`/api/learning/certificates/${certId.value}`)
      cert.value = res.data
    } else {
      const res = await request.get('/api/learning/certificates/mine')
      list.value = res.data || []
    }
  } catch (e) {
    cert.value = null
  }
  loading.value = false
}

onMounted(loadAll)
watch(certId, loadAll)

function print() {
  window.print()
}
</script>

<style scoped>
.certificate-view { padding: 20px; max-width: 1000px; }

.page-header { margin-bottom: 20px; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }
.detail-header { display: flex; justify-content: space-between; align-items: center; }

/* 列表 */
.cert-grid { display: flex; flex-direction: column; gap: 12px; }
.cert-item {
  display: flex; align-items: center; gap: 16px; cursor: pointer;
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 14px; padding: 18px 20px; transition: all 0.25s;
}
.cert-item:hover { border-color: rgba(245, 158, 11, 0.5); transform: translateY(-2px); box-shadow: 0 8px 22px rgba(0,0,0,0.08); }
.cert-medal { font-size: 32px; }
.cert-meta { flex: 1; min-width: 0; }
.cert-title { font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.cert-sub { font-size: 12px; color: var(--text-muted); }
.cert-score { font-size: 13px; color: #f59e0b; font-weight: 600; margin-top: 4px; }
.cert-arrow { color: var(--text-muted); }

/* 证书本体 */
.cert-stage { display: flex; justify-content: center; padding: 10px 0 40px; }
.diploma {
  width: 720px; max-width: 100%;
  background: linear-gradient(160deg, #fffbeb 0%, #fef3c7 45%, #fde68a 100%);
  border-radius: 8px; box-shadow: 0 18px 50px rgba(120, 80, 10, 0.25);
  padding: 10px;
}
.dp-border {
  border: 3px double #b45309; outline: 1px solid #d97706; outline-offset: 6px;
  border-radius: 4px; padding: 44px 48px 36px; text-align: center; color: #451a03;
}
.dp-ornament { color: #d97706; letter-spacing: 12px; font-size: 14px; margin: 0; }
.dp-ornament.top { margin-bottom: 18px; }
.dp-ornament.bottom { margin-top: 22px; }
.dp-brand { font-size: 12px; letter-spacing: 4px; color: #92400e; margin: 0 0 10px; }
.dp-title { font-size: 30px; letter-spacing: 10px; margin: 0 0 26px; color: #78350f; font-weight: 700; }
.dp-line { font-size: 15px; margin: 8px 0; }
.dp-line.dp-small { font-size: 12.5px; color: #92400e; }
.dp-line .dot { margin: 0 8px; opacity: 0.5; }
.dp-name { font-size: 19px; border-bottom: 2px solid #d97706; padding: 0 12px 2px; }
.dp-path { font-size: 20px; font-weight: 700; color: #b45309; margin: 12px 0; }
.dp-score { font-size: 22px; color: #b45309; }
.dp-foot { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 34px; }
.dp-foot-item { display: flex; flex-direction: column; gap: 4px; min-width: 170px; }
.dp-foot-item.right { align-items: flex-end; }
.dp-foot-label { font-size: 11px; color: #92400e; letter-spacing: 2px; }
.dp-foot-val { font-size: 14px; font-weight: 600; }
.mono { font-family: Consolas, 'Courier New', monospace; letter-spacing: 1px; }
.dp-seal {
  width: 72px; height: 72px; border-radius: 50%; font-size: 34px;
  background: radial-gradient(circle, #fef3c7 0%, #fcd34d 75%);
  border: 2px solid #b45309; display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 0 4px rgba(180, 83, 9, 0.15);
}

/* 打印：只保留证书 */
@media print {
  .no-print { display: none !important; }
  .cert-stage { padding: 0; }
  .diploma { box-shadow: none; width: 100%; }
  :deep(.layout-sidebar), :deep(.layout-header) { display: none !important; }
}
</style>
