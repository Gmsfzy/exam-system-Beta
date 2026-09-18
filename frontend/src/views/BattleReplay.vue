<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-left" @click="goBack">
        <el-icon :size="18"><ArrowLeft /></el-icon>
        <span>返回</span>
      </div>
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><VideoCamera /></el-icon> 对战回放</h2>
        <p><span class="sub-info">{{ battle.challenger }} vs {{ battle.opponent }}</span></p>
      </div>
    </div>

    <div v-if="loaded" class="result-card">
      <div class="vs-line">
        <div class="side">
          <router-link class="side-name" :to="'/rank/player/' + battle.challenger_id">{{ battle.challenger }}</router-link>
          <div class="side-score">{{ battle.challenger_score }}</div>
          <div class="elo-delta" v-if="battle.delta_challenger">{{ fmtDelta(battle.delta_challenger) }}</div>
        </div>
        <div class="vs-mid">
          <div class="vs-badge">VS</div>
          <div class="vs-verdict">{{ verdictText }}</div>
        </div>
        <div class="side right">
          <router-link class="side-name" :to="'/rank/player/' + battle.opponent_id">{{ battle.opponent }}</router-link>
          <div class="side-score">{{ battle.opponent_score }}</div>
          <div class="elo-delta" v-if="battle.delta_opponent">{{ fmtDelta(battle.delta_opponent) }}</div>
        </div>
      </div>
      <div class="result-actions">
        <el-button type="primary" :icon="Download" size="small" @click="saveCard">生成战报卡</el-button>
      </div>
    </div>

    <div v-if="loaded" class="board-card">
      <ReplayTimeline :timeline="timeline" :duration="duration" />
    </div>

    <DiscussionPanel v-if="loaded && competitionId" :competition-id="competitionId" />

    <el-empty v-if="loadError" :description="loadError" />
    <canvas ref="cardCanvas" width="800" height="440" style="display:none"></canvas>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, VideoCamera, Download } from '@element-plus/icons-vue'
import request from '../utils/request'
import ReplayTimeline from '../components/ReplayTimeline.vue'
import DiscussionPanel from '../components/DiscussionPanel.vue'

const route = useRoute()
const router = useRouter()
const battleId = route.params.battleId

const battle = ref({})
const timeline = ref([])
const duration = ref(0)
const competitionId = ref(null)
const loaded = ref(false)
const loadError = ref('')
const cardCanvas = ref(null)

const verdictText = computed(() => {
  if (!battle.value.winner) return '平局'
  if (battle.value.winner === battle.value.challenger) return `${battle.value.challenger} 获胜`
  return `${battle.value.winner} 获胜`
})

const fmtDelta = (d) => (d > 0 ? `+${d}` : `${d}`)

const goBack = () => router.back()

const load = async () => {
  try {
    const res = await request.get(`/api/pk/${battleId}/replay`)
    const d = res.data
    battle.value = d.battle || {}
    timeline.value = d.timeline || []
    duration.value = (d.duration || 0) * 60
    competitionId.value = d.competition_id
    loaded.value = true
  } catch (e) {
    loadError.value = e.response?.data?.message || '无法加载回放'
  }
}

// 用原生 Canvas 2D 绘制战报卡（不引入额外依赖），导出 PNG
const saveCard = () => {
  const cv = cardCanvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  const W = cv.width, H = cv.height
  // 背景
  const g = ctx.createLinearGradient(0, 0, W, H)
  g.addColorStop(0, '#1f2430'); g.addColorStop(1, '#2b3244')
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H)
  // 标题条
  ctx.fillStyle = '#f0c14b'; ctx.font = 'bold 34px "Microsoft YaHei", sans-serif'
  ctx.fillText('竞技对战 · 战报', 48, 74)
  ctx.fillStyle = '#9aa4b8'; ctx.font = '16px "Microsoft YaHei", sans-serif'
  ctx.fillText('exam_system 竞赛中心', 48, 102)
  // 双方
  const c = battle.value, left = c.challenger || '', right = c.opponent || ''
  ctx.textAlign = 'center'
  ctx.fillStyle = '#7db9f5'; ctx.font = 'bold 26px "Microsoft YaHei", sans-serif'
  ctx.fillText(left, 210, 200)
  ctx.fillStyle = '#ff7a45'
  ctx.fillText(right, 590, 200)
  ctx.fillStyle = '#ffffff'; ctx.font = 'bold 72px "Microsoft YaHei", sans-serif'
  ctx.fillText(String(c.challenger_score ?? 0), 210, 286)
  ctx.fillText(String(c.opponent_score ?? 0), 590, 286)
  ctx.fillStyle = '#6b7488'; ctx.font = 'bold 30px sans-serif'
  ctx.fillText('VS', 400, 250)
  // 结果 + Elo
  ctx.fillStyle = '#e8eefc'; ctx.font = '20px "Microsoft YaHei", sans-serif'
  ctx.fillText(c.winner ? (c.winner === left ? left + ' 取胜！' : right + ' 取胜！') : '势均力敌 · 平局', 400, 348)
  if (!c.is_bot && (c.delta_challenger || c.delta_opponent)) {
    ctx.font = '16px "Microsoft YaHei", sans-serif'
    ctx.fillStyle = (c.delta_challenger >= 0 ? '#8fd18f' : '#e08a8a')
    ctx.fillText('Elo ' + fmtDelta(c.delta_challenger), 210, 380)
    ctx.fillStyle = (c.delta_opponent >= 0 ? '#8fd18f' : '#e08a8a')
    ctx.fillText('Elo ' + fmtDelta(c.delta_opponent), 590, 380)
  }
  ctx.textAlign = 'left'
  cv.toBlob((blob) => {
    if (!blob) { ElMessage.error('生成失败'); return }
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `battle-${battleId}-report.png`
    document.body.appendChild(a); a.click()
    document.body.removeChild(a); URL.revokeObjectURL(url)
    ElMessage.success('战报卡已保存')
  }, 'image/png')
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { max-width: 860px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 20px; margin-bottom: 24px; }
.header-left { display: flex; align-items: center; gap: 6px; cursor: pointer; color: var(--text-muted); padding: 10px 14px; border-radius: 10px; }
.header-left:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.header-title h2 { font-size: 24px; font-weight: 700; color: var(--text-primary); margin: 0 0 8px 0; display: flex; align-items: center; gap: 10px; }
.title-icon { color: #7db9f5; }
.sub-info { font-size: 13.5px; color: var(--text-muted); }
.result-card {
  position: relative;
  padding: 28px 24px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  margin-bottom: 20px;
}
.vs-line { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.side { flex: 1; text-align: center; }
.side.right { text-align: center; }
.side-name { font-size: 16px; font-weight: 700; color: var(--text-primary); text-decoration: none; }
.side-name:hover { color: #d97706; }
.side-score { font-size: 44px; font-weight: 800; color: var(--text-primary); line-height: 1.2; }
.elo-delta { font-size: 13px; color: #7db9f5; }
.vs-mid { width: 120px; text-align: center; }
.vs-badge { font-size: 22px; font-weight: 800; color: var(--text-light); }
.vs-verdict { font-size: 13px; color: #d97706; margin-top: 4px; }
.result-actions { position: absolute; top: 16px; right: 18px; }
.board-card { padding: 20px 24px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 16px; }
.dark .result-card, .dark .board-card { background: var(--glass-bg); border-color: var(--glass-border); }
</style>
