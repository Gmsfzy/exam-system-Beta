<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="$router.push('/bounties')" content="悬赏贡献榜" class="back" />

    <div class="section">
      <el-radio-group v-model="kind" @change="load">
        <el-radio-button label="accept">答疑之星（被采纳数）</el-radio-button>
        <el-radio-button label="publish">悬赏达人（发布数）</el-radio-button>
      </el-radio-group>
    </div>

    <div class="section">
      <el-empty v-if="!items.length" description="暂无榜单数据" />
      <div v-else>
        <div v-for="(row, i) in items" :key="row.user_id" class="rank-row" :class="{ top: i < 3 }">
          <span class="rank-no">{{ rankIcon(i) }}</span>
          <span class="rank-name">{{ row.username }}</span>
          <span class="rank-count">{{ row.count }} {{ kind === 'publish' ? '条悬赏' : '次采纳' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import request from '../utils/request'

const loading = ref(false)
const kind = ref('accept')
const items = ref([])

const rankIcon = (i) => ['🥇', '🥈', '🥉'][i] || (i + 1)

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/bounty/leaderboard', { params: { kind: kind.value, limit: 50 } })
    items.value = res.data.items || []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.back { margin-bottom: 16px; }
.section {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px; padding: 20px; margin-bottom: 16px;
}
.rank-row {
  display: flex; align-items: center; gap: 16px; padding: 12px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter, #ebeef5);
}
.rank-row.top { background: var(--el-fill-color-light, #f5f7fa); border-radius: 8px; }
.rank-no { width: 40px; text-align: center; font-size: 18px; font-weight: 700; }
.rank-name { flex: 1; font-size: 15px; font-weight: 600; }
.rank-count { color: var(--el-color-warning, #e6a23c); font-weight: 600; }
</style>
