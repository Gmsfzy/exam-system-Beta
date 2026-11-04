<template>
  <div class="ach-page" v-loading="loading">
    <div class="page-header">
      <h2><el-icon :size="22"><Trophy /></el-icon> 我的成就</h2>
      <p class="sub">聚合竞赛 / 悬赏 / 社区三大成长体系（只读展示，积分互不打通）</p>
    </div>

    <div class="ach-grid">
      <!-- 竞赛 -->
      <el-card class="ach-card" shadow="hover">
        <template #header>
          <div class="card-head">
            <el-icon color="#6366f1"><Trophy /></el-icon>
            <span>答题竞赛</span>
            <el-tag size="small" effect="plain">{{ data.competition.season || '-' }} 赛季</el-tag>
          </div>
        </template>
        <div class="tier-block" :style="{ borderColor: data.competition.tier_color || '#ddd' }">
          <div class="tier-name" :style="{ color: data.competition.tier_color || '#333' }">
            {{ data.competition.tier || '未定级' }}
          </div>
          <div class="tier-points">{{ data.competition.points }} 积分</div>
        </div>
        <div class="stat-row">
          <span>赛季排名</span><strong>{{ data.competition.rank ?? '-' }} / {{ data.competition.total_players ?? '-' }}</strong>
        </div>
        <div class="stat-row">
          <span>Elo 评分</span><strong>{{ data.competition.elo ?? '-' }}（峰值 {{ data.competition.peak_elo ?? '-' }}）</strong>
        </div>
        <div class="stat-row">
          <span>对战场次</span><strong>{{ data.competition.games ?? '-' }}</strong>
        </div>
      </el-card>

      <!-- 悬赏 -->
      <el-card class="ach-card" shadow="hover">
        <template #header>
          <div class="card-head">
            <el-icon color="#f59e0b"><Money /></el-icon>
            <span>征集悬赏</span>
            <el-tag size="small" type="warning" effect="plain">{{ data.bounty.granted_count }} 枚勋章</el-tag>
          </div>
        </template>
        <div class="badge-list">
          <div v-for="b in data.bounty.badges" :key="b.code" class="badge-item">
            <el-icon color="#f59e0b"><Medal /></el-icon>
            <span>{{ b.name }}</span>
          </div>
          <el-empty v-if="!data.bounty.badges?.length" description="暂无勋章，去悬赏大厅投稿吧" :image-size="60" />
        </div>
      </el-card>

      <!-- 社区 -->
      <el-card class="ach-card" shadow="hover">
        <template #header>
          <div class="card-head">
            <el-icon color="#14b8a6"><ChatDotRound /></el-icon>
            <span>社区交流</span>
            <el-tag size="small" type="success" effect="plain">Lv.{{ data.community.level }}</el-tag>
          </div>
        </template>
        <div class="tier-block" style="border-color:#14b8a6">
          <div class="tier-name" style="color:#14b8a6">{{ data.community.level_name }}</div>
          <div class="tier-points">{{ data.community.points }} 积分</div>
        </div>
        <div class="stat-row">
          <span>社区排名</span><strong>{{ data.community.rank ?? '-' }}</strong>
        </div>
        <div class="stat-row">
          <span>下一档门槛</span>
          <strong>{{ data.community.level_threshold != null ? data.community.level_threshold + ' 分' : '已达最高档' }}</strong>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Trophy, Money, Medal, ChatDotRound } from '@element-plus/icons-vue'
import request from '../utils/request'

const loading = ref(false)
const data = ref({
  competition: { season: '', points: 0, tier: '', tier_color: '', rank: null, total_players: null, elo: null, peak_elo: null, games: null },
  bounty: { granted_count: 0, badges: [] },
  community: { points: 0, level: 1, level_name: '新手上路', level_threshold: 0, rank: null },
})

onMounted(async () => {
  loading.value = true
  try {
    const res = await request.get('/api/achievements')
    data.value = { ...data.value, ...res.data }
  } catch (e) {
    // request 拦截器已提示
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.ach-page { max-width: 1100px; margin: 0 auto; }
.page-header { margin-bottom: 20px; }
.page-header h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.sub { color: var(--el-text-color-secondary, #909399); font-size: 13px; margin: 0; }

.ach-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 18px;
}
.card-head { display: flex; align-items: center; gap: 8px; font-weight: 600; }
.card-head .el-tag { margin-left: auto; }

.tier-block {
  border: 2px solid #ddd;
  border-radius: 10px;
  padding: 18px;
  text-align: center;
  margin-bottom: 14px;
  background: linear-gradient(135deg, #fafafa, #fff);
}
.tier-name { font-size: 26px; font-weight: 700; margin-bottom: 4px; }
.tier-points { color: var(--el-text-color-secondary, #909399); font-size: 13px; }

.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter, #f0f0f0);
  font-size: 14px;
}
.stat-row:last-child { border-bottom: none; }

.badge-list { display: flex; flex-direction: column; gap: 10px; }
.badge-item { display: flex; align-items: center; gap: 8px; font-size: 14px; }
</style>
