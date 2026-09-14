<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-left" @click="goBack">
        <el-icon :size="18"><ArrowLeft /></el-icon>
        <span>返回</span>
      </div>
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Trophy /></el-icon> {{ comp.title }}</h2>
        <p>
          <el-tag :type="statusTag(comp.status)" size="small" effect="dark">{{ statusLabel(comp.status) }}</el-tag>
          <span class="sub-info">卷面总分 {{ comp.total_score }} 分</span>
        </p>
      </div>
      <div class="header-right"></div>
    </div>

    <div v-if="my && my.rank" class="my-banner">
      <div class="my-stat">
        <span class="stat-label">我的名次</span>
        <span class="stat-value rank">{{ my.rank }}</span>
      </div>
      <div class="my-stat">
        <span class="stat-label">我的得分</span>
        <span class="stat-value">{{ my.score }}</span>
      </div>
      <div class="my-stat">
        <span class="stat-label">我的用时</span>
        <span class="stat-value">{{ fmtDuration(my.used_time) }}</span>
      </div>
    </div>

    <div class="board-card">
      <div class="board-title">
        <span>排行榜</span>
        <span class="refresh-tip">{{ liveMode ? '实时更新中' : '每 30 秒自动刷新' }}</span>
      </div>
      <el-empty v-if="!rows.length" description="暂无选手上榜，报名并开始答题后即可上榜" />
      <el-table v-else :data="rows" stripe>
        <el-table-column label="名次" width="90" align="center">
          <template #default="{ row }">
            <span class="rank-badge" :class="rankClass(row.rank)">{{ row.rank <= 3 ? '' : row.rank }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="选手" min-width="140">
          <template #default="{ row }">
            <span>{{ row.username }}</span>
            <el-tag v-if="row.status === 'playing'" size="small" type="warning" effect="plain" style="margin-left: 8px">答题中</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="得分" width="120" align="center">
          <template #default="{ row }">
            <span class="score-text">{{ row.score }}</span>
          </template>
        </el-table-column>
        <el-table-column label="用时" width="110" align="center">
          <template #default="{ row }">{{ row.status === 'finished' ? fmtDuration(row.used_time) : '—' }}</template>
        </el-table-column>
        <el-table-column label="完成时间" width="170" align="center">
          <template #default="{ row }">{{ fmtTime(row.finished_at) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '../utils/request'
import { getSocket, authToken } from '../utils/socket'
import { ArrowLeft, Trophy } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const compId = route.params.compId

const comp = ref({})
const rows = ref([])
const my = ref(null)
const liveMode = ref(false)
let pollTimer = null
let socket = null

const statusLabel = (s) => ({ draft: '草稿', published: '未开始', ongoing: '进行中', ended: '已结束' }[s] || s)
const statusTag = (s) => ({ draft: 'info', published: 'primary', ongoing: 'success', ended: 'danger' }[s] || 'info')

// Socket.IO 实时更新为主，30 秒轮询兜底
const setupSocket = () => {
  try {
    socket = getSocket()
    socket.on('connect', () => {
      socket.emit('join_competition', { competition_id: Number(compId), token: authToken() })
      liveMode.value = true
    })
    socket.on('leaderboard_update', (payload) => {
      if (payload?.competition_id === Number(compId)) {
        rows.value = payload.leaderboard || []
        loadBoard() // 静默刷新完整数据（含我的名次）
      }
    })
    socket.on('disconnect', () => { liveMode.value = false })
  } catch {
    liveMode.value = false
  }
}

const loadBoard = async () => {
  const res = await request.get(`/api/competitions/${compId}/leaderboard`)
  comp.value = res.data.competition
  rows.value = res.data.leaderboard
  my.value = res.data.my
}

const rankClass = (rank) => ({ 1: 'gold', 2: 'silver', 3: 'bronze' }[rank] || '')

const fmtDuration = (sec) => {
  if (sec === null || sec === undefined) return '-'
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m}分${s}秒` : `${s}秒`
}

const fmtTime = (iso) => {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const goBack = () => router.push('/competitions')

onMounted(() => {
  loadBoard()
  setupSocket()
  pollTimer = setInterval(loadBoard, 30000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (socket) {
    socket.emit('leave_competition', { competition_id: Number(compId) })
    socket.off('connect')
    socket.off('leaderboard_update')
    socket.off('disconnect')
  }
})
</script>

<style scoped>
.page-wrapper {
  max-width: 860px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: var(--text-muted);
  padding: 10px 14px;
  border-radius: 10px;
  transition: all 0.25s ease;
}

.header-left:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.header-title h2 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  color: #d97706;
}

.header-title p {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.sub-info {
  font-size: 13.5px;
  color: var(--text-muted);
}

.header-right {
  min-width: 60px;
}

.my-banner {
  display: flex;
  gap: 16px;
  padding: 20px 28px;
  margin-bottom: 20px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.12) 0%, rgba(217, 119, 6, 0.08) 100%);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 16px;
}

.my-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 110px;
}

.stat-label {
  font-size: 12.5px;
  color: var(--text-muted);
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.rank {
  color: #d97706;
}

.board-card {
  padding: 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
}

.board-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.refresh-tip {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-light);
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  font-weight: 700;
  font-size: 14px;
  color: var(--text-secondary);
}

.rank-badge.gold,
.rank-badge.silver,
.rank-badge.bronze {
  color: white;
}

.rank-badge.gold {
  background: linear-gradient(135deg, #fbbf24 0%, #d97706 100%);
  box-shadow: 0 3px 10px rgba(217, 119, 6, 0.4);
}

.rank-badge.silver {
  background: linear-gradient(135deg, #cbd5e1 0%, #94a3b8 100%);
  box-shadow: 0 3px 10px rgba(148, 163, 184, 0.4);
}

.rank-badge.bronze {
  background: linear-gradient(135deg, #d97706 0%, #b45309 100%);
  box-shadow: 0 3px 10px rgba(180, 83, 9, 0.4);
}

.score-text {
  font-weight: 700;
  color: #d97706;
}

.dark .board-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
}

.dark .my-banner {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.15) 0%, rgba(217, 119, 6, 0.06) 100%);
  border-color: rgba(245, 158, 11, 0.25);
}
</style>
