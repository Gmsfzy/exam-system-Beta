<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Medal /></el-icon> 我的段位</h2>
        <p><span class="sub-info">当前赛季 {{ me.season || currentSeasonLabel }} · 竞技积分决定你的段位</span></p>
      </div>
    </div>

    <!-- 段位档案卡 -->
    <div v-if="me.season" class="tier-card" :style="{ '--tier-color': me.tier_progress.tier_color }">
      <div class="tier-main">
        <div class="tier-badge" :style="{ background: me.tier_progress.tier_color }">
          {{ me.tier_progress.tier }}
        </div>
        <div class="tier-info">
          <div class="points-line">
            <span class="points-value">{{ me.tier_progress.points }}</span>
            <span class="points-unit">竞技积分</span>
            <el-tag v-if="me.rank" type="warning" effect="plain" size="small" class="rank-tag">赛季第 {{ me.rank }} 名</el-tag>
          </div>
          <div class="progress-line" v-if="me.tier_progress.next_tier">
            <el-progress :percentage="me.tier_progress.percent" :stroke-width="8"
                         :color="me.tier_progress.tier_color" :show-text="false" class="tier-progress" />
            <span class="progress-text">距 {{ me.tier_progress.next_tier }} 还需 {{ Math.max(0, me.tier_progress.next_at - me.tier_progress.points) }} 分</span>
          </div>
          <div class="progress-line" v-else>
            <span class="progress-text max">已达最高段位</span>
          </div>
        </div>
      </div>
      <div class="tier-stats">
        <div class="t-stat"><span class="v">{{ me.stats.pk_win }}</span><span class="l">PK胜</span></div>
        <div class="t-stat"><span class="v">{{ me.stats.pk_lose }}</span><span class="l">PK负</span></div>
        <div class="t-stat"><span class="v">{{ me.stats.streak }}</span><span class="l">当前连胜</span></div>
        <div class="t-stat"><span class="v">{{ me.stats.max_streak }}</span><span class="l">最高连胜</span></div>
        <div class="t-stat"><span class="v">{{ me.stats.timed_finished }}</span><span class="l">完赛场次</span></div>
        <div class="t-stat"><span class="v">{{ me.total_players }}</span><span class="l">赛季人数</span></div>
      </div>
    </div>

    <!-- 赛季排行 / 往届归档 -->
    <el-tabs v-model="activeTab" class="rank-tabs">
      <el-tab-pane label="本赛季排行" name="current">
        <el-empty v-if="!board.length" description="本赛季暂无选手上榜，参加竞赛或PK即可上榜" />
        <el-table v-else :data="board" stripe>
          <el-table-column label="名次" width="80" align="center">
            <template #default="{ row }">
              <span class="rank-badge" :class="rankClass(row.rank)">{{ row.rank <= 3 ? '' : row.rank }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="username" label="选手" min-width="120" />
          <el-table-column label="段位" width="90" align="center">
            <template #default="{ row }">
              <span class="tier-mini" :style="{ color: tierColor(row.tier) }">{{ row.tier }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="points" label="积分" width="90" align="center" />
          <el-table-column label="PK战绩" width="110" align="center">
            <template #default="{ row }">{{ row.pk_total ? `${row.pk_win}/${row.pk_total}` : '—' }}</template>
          </el-table-column>
          <el-table-column prop="timed_finished" label="完赛" width="80" align="center" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="往届赛季" name="archive">
        <el-select v-model="selectedSeason" placeholder="选择赛季" class="season-select" @change="loadSeason">
          <el-option v-for="s in seasons" :key="s.season" :label="seasonLabel(s.season, s.archived)"
                     :value="s.season" :disabled="!s.archived && s.season !== currentSeasonLabel" />
        </el-select>
        <el-empty v-if="!seasonBoard.length" description="选择已结算的赛季查看归档排名" />
        <el-table v-else :data="seasonBoard" stripe>
          <el-table-column prop="rank" label="名次" width="80" align="center" />
          <el-table-column prop="username" label="选手" min-width="120" />
          <el-table-column label="段位" width="90" align="center">
            <template #default="{ row }">
              <span class="tier-mini" :style="{ color: tierColor(row.tier) }">{{ row.tier }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="points" label="赛季积分" width="100" align="center" />
          <el-table-column label="PK战绩" width="110" align="center">
            <template #default="{ row }">{{ row.pk_total ? `${row.pk_win}/${row.pk_total}` : '—' }}</template>
          </el-table-column>
          <el-table-column prop="timed_finished" label="完赛" width="80" align="center" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="我的勋章" name="badges">
        <div class="badge-wall">
          <div v-for="b in badges" :key="b.code" class="badge-item" :class="{ earned: b.granted }">
            <div class="badge-icon">{{ b.icon }}</div>
            <div class="badge-name">{{ b.name }}</div>
            <div class="badge-desc">{{ b.description }}</div>
            <div class="badge-time" v-if="b.granted">{{ fmtTime(b.granted_at) }}</div>
            <el-tag v-if="!b.granted" size="small" type="info" effect="plain" class="badge-lock">未解锁</el-tag>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Medal, ArrowLeft } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()
const TIER_COLORS = {
  青铜: '#b08d57', 白银: '#a8b4c4', 黄金: '#f0c14b',
  铂金: '#7fd8d8', 钻石: '#7db9f5', 王者: '#ff7a45',
}

const me = ref({ season: '', tier_progress: {}, stats: {}, total_players: 0 })
const currentSeasonLabel = ref('')
const board = ref([])
const seasons = ref([])
const selectedSeason = ref('')
const seasonBoard = ref([])
const badges = ref([])
const activeTab = ref('current')
let pollTimer = null

const tierColor = (t) => TIER_COLORS[t] || 'inherit'

const rankClass = (rank) => (rank === 1 ? 'gold' : rank === 2 ? 'silver' : rank === 3 ? 'bronze' : '')

const seasonLabel = (s, archived) => `${s}${archived ? '（已结算）' : ''}`
const fmtTime = (iso) => {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

const loadMe = async () => {
  const res = await request.get('/api/rank/me')
  me.value = res.data
  currentSeasonLabel.value = res.data.season
}
const loadBoard = async () => {
  const res = await request.get(`/api/rank/season/${currentSeasonLabel.value || 'current'}`)
  if (res.data.season) currentSeasonLabel.value = res.data.season
  board.value = res.data.leaderboard || []
}
const loadSeasons = async () => {
  const res = await request.get('/api/rank/seasons')
  seasons.value = res.data
  const cur = seasons.value.find((s) => s.season === currentSeasonLabel.value)
  const done = seasons.value.filter((s) => s.archived)
  if (done.length) {
    selectedSeason.value = done[0].season
    loadSeason()
  }
}
const loadSeason = async () => {
  if (!selectedSeason.value) return
  const res = await request.get(`/api/rank/season/${selectedSeason.value}`)
  seasonBoard.value = res.data.leaderboard || []
}
const loadBadges = async () => {
  const res = await request.get('/api/badges/me')
  badges.value = res.data.all || []
}

onMounted(async () => {
  await loadMe()
  loadBoard()
  loadSeasons()
  loadBadges()
  pollTimer = setInterval(() => { loadMe(); loadBoard() }, 30000)
})
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.page-wrapper {
  max-width: 860px;
  margin: 0 auto;
}

.page-header h2 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  color: #f0c14b;
}

.sub-info {
  font-size: 13.5px;
  color: var(--text-muted);
}

.tier-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  padding: 24px 28px;
  border-radius: 16px;
  background: linear-gradient(135deg, var(--bg-secondary), var(--bg-tertiary));
  border: 1px solid var(--border-color);
  border-left: 4px solid var(--tier-color, #f0c14b);
  margin-bottom: 20px;
}

.tier-main {
  display: flex;
  align-items: center;
  gap: 20px;
}

.tier-badge {
  min-width: 84px;
  height: 84px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 800;
  color: #fff;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.18);
}

.points-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.points-value {
  font-size: 34px;
  font-weight: 800;
  color: var(--text-primary);
}

.points-unit {
  font-size: 13px;
  color: var(--text-muted);
}

.rank-tag {
  margin-left: 6px;
}

.progress-line {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.tier-progress {
  width: 220px;
}

.progress-text {
  font-size: 12.5px;
  color: var(--text-muted);
}

.progress-text.max {
  color: #f56c6c;
  font-weight: 600;
}

.tier-stats {
  display: flex;
  gap: 22px;
  flex-wrap: wrap;
}

.t-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.t-stat .v {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.t-stat .l {
  font-size: 12px;
  color: var(--text-muted);
}

.rank-tabs {
  margin-top: 4px;
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  font-weight: 700;
  color: var(--text-secondary);
}

.rank-badge.gold {
  color: #f0c14b;
}

.rank-badge.silver {
  color: #a8b4c4;
}

.rank-badge.bronze {
  color: #b08d57;
}

.tier-mini {
  font-weight: 700;
}

.season-select {
  margin-bottom: 14px;
}

.badge-wall {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
  padding: 8px 2px;
}

.badge-item {
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 20px 16px;
  text-align: center;
  background: var(--bg-secondary);
  opacity: 0.45;
  filter: grayscale(1);
  transition: all 0.25s ease;
}

.badge-item.earned {
  opacity: 1;
  filter: none;
  border-color: #f0c14b;
  box-shadow: 0 4px 14px rgba(240, 193, 75, 0.16);
}

.badge-item.earned:hover {
  transform: translateY(-3px);
}

.badge-icon {
  font-size: 40px;
  line-height: 1;
  margin-bottom: 10px;
}

.badge-name {
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.badge-desc {
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.5;
  min-height: 38px;
}

.badge-time {
  margin-top: 8px;
  font-size: 12px;
  color: #f0c14b;
}

.badge-lock {
  margin-top: 8px;
}
</style>
