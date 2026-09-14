<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Trophy /></el-icon> PK对战大厅</h2>
        <p>向同场竞赛的同学发起 1v1 实时对战，得分高者获胜</p>
      </div>
    </div>

    <div class="lobby-grid">
      <!-- 等待中的挑战 -->
      <div class="lobby-card">
        <div class="card-title">等待对手的挑战</div>
        <el-empty v-if="!waiting.length" description="暂无等待中的挑战，去竞赛广场发起一个吧" :image-size="80" />
        <div v-else class="battle-list">
          <div v-for="b in waiting" :key="b.id" class="battle-item">
            <div class="battle-info">
              <div class="battle-players">
                <el-icon :size="16" class="vs-icon"><Trophy /></el-icon>
                <b>{{ b.challenger }}</b>
                <span class="vs-text">发起挑战</span>
              </div>
              <div class="battle-comp">{{ b.competition_title }} · {{ b.question_count }}题 / {{ b.total_score }}分 · 限时{{ b.duration }}分钟</div>
            </div>
            <el-button v-if="b.is_mine" size="small" type="info" plain disabled>等待中</el-button>
            <el-button v-else size="small" type="danger" @click="accept(b)">应战</el-button>
          </div>
        </div>
      </div>

      <!-- 我的对战 -->
      <div class="lobby-card">
        <div class="card-title">我的对战</div>
        <el-empty v-if="!mine.length" description="还没有对战记录" :image-size="80" />
        <div v-else class="battle-list">
          <div v-for="b in mine" :key="b.id" class="battle-item">
            <div class="battle-info">
              <div class="battle-players">
                <span class="player-me">我</span>
                <span class="vs-text big">VS</span>
                <b>{{ b.challenger_id === auth.user?.id ? (b.opponent || '???') : b.challenger }}</b>
                <el-tag v-if="b.status === 'finished'" size="small" :type="resultTag(b.result)" effect="dark">
                  {{ resultLabel(b.result) }}
                </el-tag>
                <el-tag v-else-if="b.status === 'playing'" size="small" type="warning" effect="dark">对战中</el-tag>
                <el-tag v-else size="small" type="info">等待中</el-tag>
              </div>
              <div class="battle-comp">{{ b.competition_title }} · 比分 {{ b.challenger_score }} : {{ b.opponent_score }}</div>
            </div>
            <el-button v-if="b.status === 'playing'" size="small" type="success" @click="$router.push(`/pk/take/${b.id}`)">
              继续对战
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { getSocket } from '../utils/socket'
import { useAuthStore } from '../stores/auth'
import { Trophy } from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuthStore()
const waiting = ref([])
const mine = ref([])
let pollTimer = null
let socket = null

const resultLabel = (r) => ({ win: '胜利', lose: '惜败', draw: '平局' }[r] || r)
const resultTag = (r) => ({ win: 'success', lose: 'danger', draw: 'info' }[r] || 'info')

const loadLobby = async () => {
  const res = await request.get('/api/pk/lobby')
  waiting.value = res.data.waiting
  mine.value = res.data.mine
}

const accept = (b) => {
  ElMessageBox.confirm(`接受 ${b.challenger} 的挑战？双方将立即开始对战`, '确认应战', { type: 'warning' })
    .then(async () => {
      await request.post(`/api/pk/${b.id}/accept`)
      router.push(`/pk/take/${b.id}`)
    }).catch(() => {})
}

const setupSocket = () => {
  try {
    socket = getSocket()
    // 有新挑战或对战状态变化时刷新大厅（简洁起见监听 battle 类广播后重拉）
    socket.on('connect', () => { loadLobby() })
  } catch { /* 忽略 */ }
}

onMounted(() => {
  loadLobby()
  setupSocket()
  pollTimer = setInterval(loadLobby, 8000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (socket) {
    socket.off('connect')
  }
})
</script>

<style scoped>
.page-wrapper {
  max-width: 1100px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
}

.header-title h2 {
  font-size: 26px;
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
  font-size: 15px;
  color: var(--text-muted);
  margin: 0;
}

.lobby-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.lobby-card {
  padding: 22px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.battle-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.battle-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  transition: all 0.25s ease;
}

.battle-item:hover {
  border-color: rgba(245, 158, 11, 0.5);
}

.battle-info {
  min-width: 0;
}

.battle-players {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14.5px;
  color: var(--text-primary);
}

.vs-icon {
  color: #d97706;
}

.vs-text {
  font-size: 12.5px;
  color: var(--text-muted);
}

.vs-text.big {
  font-weight: 700;
  color: #d97706;
  font-size: 13px;
}

.player-me {
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
  font-size: 12px;
  font-weight: 700;
}

.battle-comp {
  margin-top: 6px;
  font-size: 12.5px;
  color: var(--text-muted);
}

.dark .lobby-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
}

.dark .battle-item {
  border-color: var(--glass-border);
}

@media (max-width: 900px) {
  .lobby-grid {
    grid-template-columns: 1fr;
  }
}
</style>
