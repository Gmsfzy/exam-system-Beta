<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-left" @click="goBack">
        <el-icon :size="18"><ArrowLeft /></el-icon>
        <span>返回</span>
      </div>
      <div class="header-title">
        <h2>
          <span class="avatar">{{ (profile.user?.username || '?').slice(0, 1).toUpperCase() }}</span>
          {{ profile.user?.username }}
          <el-tag v-if="profile.user?.sanctioned" size="small" type="danger" effect="dark" class="sanc-tag">已受限</el-tag>
        </h2>
        <p><span class="sub-info">选手公开主页 · 赛季 {{ profile.season }}</span></p>
      </div>
    </div>

    <div v-if="loaded" class="tier-card" :style="{ '--tier-color': standing.tier_color }">
      <div class="tier-main">
        <div class="tier-badge" :style="{ background: standing.tier_color }">
          {{ standing.tier }}
        </div>
        <div class="tier-info">
          <div class="points-line">
            <span class="points-value">{{ standing.points }}</span>
            <span class="points-unit">竞技积分</span>
            <el-tag v-if="standing.rank" type="warning" effect="plain" size="small">
              赛季第 {{ standing.rank }} / {{ standing.total_players }} 名
            </el-tag>
          </div>
          <div class="arena-line" v-if="profile.arena">
            <span>Elo <b>{{ profile.arena.elo }}</b>（峰值 {{ profile.arena.peak_elo }}）</span>
            <span class="dot">·</span>
            <span>计入 {{ profile.arena.games }} 场</span>
          </div>
        </div>
      </div>
      <div class="tier-stats">
        <div class="t-stat"><span class="v">{{ standing.pk_win }}</span><span class="l">PK胜</span></div>
        <div class="t-stat"><span class="v">{{ standing.pk_lose }}</span><span class="l">PK负</span></div>
        <div class="t-stat"><span class="v">{{ standing.pk_draw }}</span><span class="l">PK平</span></div>
        <div class="t-stat"><span class="v">{{ standing.max_streak }}</span><span class="l">最高连胜</span></div>
        <div class="t-stat"><span class="v">{{ standing.timed_finished }}</span><span class="l">完赛场次</span></div>
      </div>
    </div>

    <div v-if="loaded" class="history-card">
      <h3 class="card-title">本赛季积分走势</h3>
      <div class="history-box">
        <Line v-if="historyData" :data="historyData" :options="historyOptions" />
        <el-empty v-else description="本赛季还没有积分记录" :image-size="70" />
      </div>
    </div>

    <div v-if="loaded" class="badge-card">
      <h3 class="card-title">勋章墙</h3>
      <el-empty v-if="!profile.badges?.length" description="还没有获得勋章" :image-size="60" />
      <div v-else class="badge-wall">
        <div v-for="b in profile.badges" :key="b.code" class="badge-item earned">
          <div class="badge-icon">{{ b.icon }}</div>
          <div class="badge-name">{{ b.name }}</div>
          <div class="badge-time">{{ fmtTime(b.granted_at) }}</div>
        </div>
      </div>
    </div>

    <div v-if="loaded && profile.archives?.length" class="archive-card">
      <h3 class="card-title">历史赛季</h3>
      <el-table :data="profile.archives" stripe>
        <el-table-column prop="season" label="赛季" min-width="140" />
        <el-table-column prop="rank" label="名次" width="90" align="center" />
        <el-table-column label="段位" width="90" align="center">
          <template #default="{ row }">
            <span class="tier-mini" :style="{ color: tierColor(row.tier) }">{{ row.tier }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="points" label="积分" width="100" align="center" />
      </el-table>
    </div>

    <el-empty v-if="loadError" :description="loadError" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { Chart as ChartJS, LinearScale, CategoryScale, PointElement, LineElement, Filler, Tooltip, Legend } from 'chart.js'
import { Line } from 'vue-chartjs'
import request from '../utils/request'

ChartJS.register(LinearScale, CategoryScale, PointElement, LineElement, Filler, Tooltip, Legend)

const route = useRoute()
const router = useRouter()
const userId = route.params.userId

const TIER_COLORS = {
  青铜: '#b08d57', 白银: '#a8b4c4', 黄金: '#f0c14b',
  铂金: '#7fd8d8', 钻石: '#7db9f5', 星耀: '#c084fc', 王者: '#ff7a45',
}

const profile = ref({})
const loaded = ref(false)
const loadError = ref('')

const standing = computed(() => profile.value.standing || {})

const historyData = computed(() => {
  const h = profile.value.history || []
  if (!h.length) return null
  return {
    labels: h.map((x) => x.day),
    datasets: [
      {
        label: '竞技积分', data: h.map((x) => x.points),
        borderColor: '#f0c14b', backgroundColor: 'rgba(240, 193, 75, 0.16)',
        yAxisID: 'y', fill: true, tension: 0.35, pointRadius: 3,
      },
      {
        label: '对战 Elo', data: h.map((x) => x.elo),
        borderColor: '#7db9f5', backgroundColor: 'rgba(125, 185, 245, 0.12)',
        yAxisID: 'y1', fill: false, tension: 0.35, pointRadius: 3,
      },
    ],
  }
})

const historyOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index', intersect: false },
  scales: {
    y: { position: 'left', title: { display: true, text: '积分' }, ticks: { precision: 0 } },
    y1: { position: 'right', grid: { drawOnChartArea: false }, title: { display: true, text: 'Elo' } },
  },
  plugins: { legend: { display: true, labels: { boxWidth: 12 } } },
}

const tierColor = (t) => TIER_COLORS[t] || 'inherit'

const fmtTime = (iso) => {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

const goBack = () => router.back()

const load = async () => {
  try {
    const res = await request.get(`/api/rank/public/${userId}`)
    profile.value = res.data || {}
    loaded.value = true
  } catch (e) {
    loadError.value = e.response?.data?.message || '无法加载选手主页'
  }
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { max-width: 860px; margin: 0 auto; }
.page-header { display: flex; align-items: center; gap: 20px; margin-bottom: 24px; }
.header-left { display: flex; align-items: center; gap: 6px; cursor: pointer; color: var(--text-muted); padding: 10px 14px; border-radius: 10px; }
.header-left:hover { background: var(--bg-tertiary); color: var(--text-primary); }
.header-title h2 { font-size: 24px; font-weight: 700; color: var(--text-primary); margin: 0 0 8px 0; display: flex; align-items: center; gap: 10px; }
.avatar { display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg, #fbbf24, #d97706); color: #fff; font-size: 18px; }
.sanc-tag { margin-left: 4px; }
.sub-info { font-size: 13.5px; color: var(--text-muted); }
.tier-card { display: flex; align-items: center; justify-content: space-between; gap: 24px; flex-wrap: wrap; padding: 24px 28px; border-radius: 16px; background: linear-gradient(135deg, var(--bg-secondary), var(--bg-tertiary)); border: 1px solid var(--border-color); border-left: 4px solid var(--tier-color, #f0c14b); margin-bottom: 20px; }
.tier-main { display: flex; align-items: center; gap: 20px; }
.tier-badge { min-width: 84px; height: 84px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 800; color: #fff; box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18); }
.points-line { display: flex; align-items: baseline; gap: 8px; }
.points-value { font-size: 34px; font-weight: 800; color: var(--text-primary); }
.points-unit { font-size: 13px; color: var(--text-muted); }
.arena-line { margin-top: 8px; font-size: 13px; color: var(--text-muted); }
.arena-line b { color: #7db9f5; }
.arena-line .dot { margin: 0 6px; color: var(--text-light); }
.tier-stats { display: flex; gap: 22px; flex-wrap: wrap; }
.t-stat { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.t-stat .v { font-size: 20px; font-weight: 700; color: var(--text-primary); }
.t-stat .l { font-size: 12px; color: var(--text-muted); }
.card-title { margin: 0 0 12px 0; font-size: 15px; font-weight: 700; color: var(--text-primary); }
.history-card, .badge-card, .archive-card { padding: 18px 24px; margin-bottom: 20px; border-radius: 14px; background: var(--bg-secondary); border: 1px solid var(--border-color); }
.history-box { height: 260px; position: relative; }
.badge-wall { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 16px; }
.badge-item { border: 1px solid #f0c14b; border-radius: 14px; padding: 18px 12px; text-align: center; background: var(--bg-card); box-shadow: 0 4px 14px rgba(240, 193, 75, 0.16); }
.badge-icon { font-size: 38px; line-height: 1; margin-bottom: 10px; }
.badge-name { font-weight: 700; color: var(--text-primary); margin-bottom: 6px; }
.badge-time { font-size: 12px; color: #f0c14b; }
.tier-mini { font-weight: 700; }
</style>
