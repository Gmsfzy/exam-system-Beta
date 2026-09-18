<template>
  <div class="certificate-view">
    <!-- 列表模式：/competitions/certificates -->
    <template v-if="!certId">
      <div class="page-header">
        <div>
          <h1 class="page-title">我的赛季证书</h1>
          <p class="page-subtitle">赛季归档时按最终积分分等级颁发</p>
        </div>
        <el-button text @click="$router.push('/rank')">← 返回段位中心</el-button>
      </div>

      <div v-loading="loading">
        <div v-if="list.length" class="cert-grid">
          <div v-for="c in list" :key="c.id" class="cert-item"
            :style="{ '--accent': gradeColor(c.grade) }"
            @click="$router.push(`/competitions/certificates/${c.id}`)">
            <div class="cert-medal">🏆</div>
            <div class="cert-meta">
              <div class="cert-title">{{ c.grade_label }} · {{ c.season }} 赛季</div>
              <div class="cert-sub">{{ c.serial_no }} · {{ (c.earned_at || '').slice(0, 10) }}</div>
              <div class="cert-score">段位 {{ c.tier || '—' }} · 第 {{ c.rank }} 名 · {{ c.points }} 分</div>
            </div>
            <el-icon class="cert-arrow"><ArrowRight /></el-icon>
          </div>
        </div>
        <el-empty v-else-if="!loading" :image-size="80"
          description="还没有赛季证书：参与限时赛积累赛季积分，赛季结束后自动评定颁发">
          <el-button type="primary" @click="$router.push('/competitions')">去竞赛广场</el-button>
        </el-empty>
      </div>
    </template>

    <!-- 详情模式：/competitions/certificates/:id -->
    <template v-else>
      <div class="page-header detail-header no-print">
        <el-button text @click="$router.push('/competitions/certificates')">← 返回证书列表</el-button>
        <div class="header-actions">
          <el-button type="primary" @click="print">
            <el-icon><Printer /></el-icon>&nbsp;打印 / 导出 PDF
          </el-button>
        </div>
      </div>

      <div v-loading="loading" class="cert-stage">
        <div v-if="cert" ref="certRef" class="diploma" :style="{ '--accent': gradeColor(cert.grade) }">
          <div class="dp-border">
            <div class="dp-ornament top">✦ ⁘ ✦</div>
            <p class="dp-brand">智汇学场 · 竞赛竞技认证</p>
            <h2 class="dp-title">赛季竞技证书</h2>
            <p class="dp-line">兹证明 <b class="dp-name">{{ cert.username || '选手' }}</b></p>
            <p class="dp-line">在 <b class="dp-season">{{ cert.season }}</b> 赛季竞技中</p>
            <p class="dp-line">
              以 <b class="dp-score">{{ cert.points }}</b> 分 位列赛季第
              <b class="dp-rank">{{ cert.rank }}</b> 名
            </p>
            <p class="dp-line dp-small">最终段位 {{ cert.tier || '—' }} · 共 {{ cert.total_players }} 位选手参与评定</p>
            <p class="dp-award">荣获 <b class="dp-grade">{{ cert.grade_label }}</b></p>
            <div class="dp-foot">
              <div class="dp-foot-item">
                <span class="dp-foot-label">证书编号</span>
                <span class="dp-foot-val mono">{{ cert.serial_no }}</span>
              </div>
              <div class="dp-seal">🏆</div>
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
import { ArrowRight, Printer } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const certId = computed(() => route.params.id)

const loading = ref(false)
const list = ref([])
const cert = ref(null)
const certRef = ref(null)

// 档名配色（对标计划：金/银/铜/纪念）
const GRADE_COLORS = { gold: '#f0c14b', silver: '#a8b4c4', bronze: '#b08d57', merit: '#7fd8d8' }
const gradeColor = (g) => GRADE_COLORS[g] || '#f0c14b'

async function loadAll() {
  loading.value = true
  try {
    if (certId.value) {
      const res = await request.get(`/api/rank/certificates/${certId.value}`)
      cert.value = res.data
    } else {
      const res = await request.get('/api/rank/certificates/mine')
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

.page-header { margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }

/* 列表 */
.cert-grid { display: flex; flex-direction: column; gap: 12px; }
.cert-item {
  display: flex; align-items: center; gap: 16px; cursor: pointer;
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-left: 4px solid var(--accent);
  border-radius: 14px; padding: 18px 20px; transition: all 0.25s;
}
.cert-item:hover { border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 8px 22px rgba(0, 0, 0, 0.08); }
.cert-medal { font-size: 32px; }
.cert-meta { flex: 1; min-width: 0; }
.cert-title { font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px; }
.cert-sub { font-size: 12px; color: var(--text-muted); }
.cert-score { font-size: 13px; color: var(--accent); font-weight: 600; margin-top: 4px; }
.cert-arrow { color: var(--text-muted); }

/* 证书本体 */
.cert-stage { display: flex; justify-content: center; padding: 10px 0 40px; }
.diploma {
  width: 720px; max-width: 100%;
  background: linear-gradient(160deg, #ffffff 0%, #fafafa 45%, #f3f4f6 100%);
  border-radius: 8px; box-shadow: 0 18px 50px rgba(0, 0, 0, 0.18);
  padding: 10px;
}
.dp-border {
  border: 3px double var(--accent); outline: 1px solid var(--accent); outline-offset: 6px;
  border-radius: 4px; padding: 44px 48px 36px; text-align: center; color: #1f2937;
}
.dp-ornament { color: var(--accent); letter-spacing: 12px; font-size: 14px; margin: 0; }
.dp-ornament.top { margin-bottom: 18px; }
.dp-ornament.bottom { margin-top: 22px; }
.dp-brand { font-size: 12px; letter-spacing: 4px; color: #6b7280; margin: 0 0 10px; }
.dp-title { font-size: 30px; letter-spacing: 8px; margin: 0 0 26px; color: var(--accent); font-weight: 700; }
.dp-line { font-size: 15px; margin: 8px 0; }
.dp-line.dp-small { font-size: 12.5px; color: #6b7280; }
.dp-name { font-size: 19px; border-bottom: 2px solid var(--accent); padding: 0 12px 2px; }
.dp-season { font-size: 17px; color: #374151; }
.dp-score, .dp-rank { font-size: 18px; color: var(--accent); }
.dp-award { font-size: 18px; margin: 16px 0 4px; }
.dp-grade { font-size: 24px; color: var(--accent); letter-spacing: 3px; }
.dp-foot { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 34px; }
.dp-foot-item { display: flex; flex-direction: column; gap: 4px; min-width: 170px; }
.dp-foot-item.right { align-items: flex-end; }
.dp-foot-label { font-size: 11px; color: #6b7280; letter-spacing: 2px; }
.dp-foot-val { font-size: 14px; font-weight: 600; }
.mono { font-family: Consolas, 'Courier New', monospace; letter-spacing: 1px; }
.dp-seal {
  width: 72px; height: 72px; border-radius: 50%; font-size: 34px;
  background: radial-gradient(circle, #ffffff 0%, var(--accent) 140%);
  border: 2px solid var(--accent); display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 0 4px rgba(0, 0, 0, 0.06);
}

/* 打印：只保留证书 */
@media print {
  .no-print { display: none !important; }
  .cert-stage { padding: 0; }
  .diploma { box-shadow: none; width: 100%; }
  :deep(.layout-sidebar), :deep(.layout-header) { display: none !important; }
}
</style>
