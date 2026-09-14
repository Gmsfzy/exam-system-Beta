<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>竞赛广场</h2>
        <p>参与限时积分赛，挑战速度与准确率</p>
      </div>
      <el-button type="warning" plain @click="router.push('/competitions/pk')">
        <el-icon :size="16" style="margin-right: 4px"><Trophy /></el-icon>
        PK对战大厅
      </el-button>
    </div>

    <div v-if="loading" class="loading-box">
      <el-skeleton :rows="4" animated />
    </div>

    <el-empty v-else-if="!competitions.length" description="暂无进行中的竞赛，敬请期待" />

    <div v-else class="comp-grid">
      <div v-for="comp in competitions" :key="comp.id" class="comp-card">
        <div class="card-top">
          <el-tag :type="statusTag(comp.status)" effect="dark" size="small">
            {{ statusLabel(comp.status) }}
          </el-tag>
          <span v-if="comp.my_rank" class="my-rank">我的最佳：第{{ comp.my_rank }}名</span>
        </div>
        <h3 class="comp-title">{{ comp.title }}</h3>
        <p class="comp-desc">{{ comp.description || '暂无描述' }}</p>
        <div class="comp-meta">
          <span class="meta-tag"><el-icon :size="14"><Calendar /></el-icon>{{ fmtTime(comp.start_time) }} ~ {{ fmtTime(comp.end_time) }}</span>
          <span class="meta-tag"><el-icon :size="14"><Clock /></el-icon>限时{{ comp.duration }}分钟</span>
          <span class="meta-tag"><el-icon :size="14"><List /></el-icon>{{ comp.question_count }}题 / {{ comp.total_score }}分</span>
          <span class="meta-tag"><el-icon :size="14"><User /></el-icon>{{ comp.participant_count }}人参与</span>
        </div>
        <div class="card-footer">
          <div v-if="comp.my_score !== null" class="my-score">
            我的得分：<b>{{ comp.my_score }}</b>
          </div>
          <div class="card-actions">
            <el-button v-if="!comp.my_status && comp.status !== 'ended'" size="small" type="primary" @click="join(comp)">
              报名
            </el-button>
            <el-button v-if="canTake(comp)" size="small" type="success" @click="takeCompetition(comp)">
              {{ comp.my_status === 'playing' ? '继续答题' : '开始答题' }}
            </el-button>
            <el-button v-if="canPk(comp)" size="small" type="warning" @click="createPk(comp)">
              发起PK
            </el-button>
            <el-button size="small" @click="viewLeaderboard(comp)">
              排行榜
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import { Calendar, Clock, List, User, Trophy } from '@element-plus/icons-vue'

const router = useRouter()
const competitions = ref([])
const loading = ref(true)

const statusLabel = (s) => ({ published: '未开始', ongoing: '进行中', ended: '已结束' }[s] || s)
const statusTag = (s) => ({ published: 'primary', ongoing: 'success', ended: 'danger' }[s] || 'info')

const fmtTime = (iso) => {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const canTake = (comp) => {
  return comp.my_status === 'joined' || comp.my_status === 'playing'
}

const canPk = (comp) => {
  return comp.status === 'ongoing' &&
    (comp.my_status === 'joined' || comp.my_status === 'playing' || comp.my_status === 'finished')
}

const createPk = async (comp) => {
  const res = await request.post(`/api/competitions/${comp.id}/pk`)
  ElMessage.success(res.data.message || '挑战已创建')
  router.push(`/pk/take/${res.data.battle_id}`)
}

const loadCompetitions = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/competitions/lobby')
    competitions.value = res.data
  } finally {
    loading.value = false
  }
}

const join = async (comp) => {
  await request.post(`/api/competitions/${comp.id}/join`)
  ElMessage.success('报名成功，开赛后即可答题')
  loadCompetitions()
}

const takeCompetition = (comp) => {
  router.push(`/competition/take/${comp.id}`)
}

const viewLeaderboard = (comp) => {
  router.push(`/competitions/${comp.id}/leaderboard`)
}

onMounted(loadCompetitions)
</script>

<style scoped>
.page-wrapper {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 28px;
}

.header-title h2 {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
}

.header-title p {
  font-size: 15px;
  color: var(--text-muted);
  margin: 0;
}

.loading-box {
  padding: 20px;
}

.comp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 20px;
}

.comp-card {
  display: flex;
  flex-direction: column;
  padding: 22px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  transition: all 0.3s ease;
}

.comp-card:hover {
  transform: translateY(-3px);
  border-color: rgba(245, 158, 11, 0.45);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.1);
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.my-rank {
  font-size: 12.5px;
  font-weight: 600;
  color: #d97706;
}

.comp-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 6px 0;
}

.comp-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0 0 12px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.comp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.meta-tag {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.card-footer {
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.my-score {
  font-size: 13px;
  color: var(--text-secondary);
}

.my-score b {
  color: #d97706;
  font-size: 16px;
}

.dark .comp-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
}

@media (max-width: 768px) {
  .comp-grid {
    grid-template-columns: 1fr;
  }
}
</style>
