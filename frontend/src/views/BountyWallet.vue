<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="$router.push('/bounties')" content="赏金钱包" class="back" />

    <div class="section balance-card">
      <div class="bal-label">当前赏金余额</div>
      <div class="bal-value"><el-icon><GoldMedal /></el-icon> {{ balance }}</div>
      <div v-if="!enabled" class="escrow-tip">
        托管功能当前未启用（BOUNTY_ESCROW 关闭），发布悬赏直接以竞技积分激励；钱包账本仍可用于记账与查询。
      </div>
      <div v-else class="escrow-tip">
        托管已启用：发布悬赏将冻结赏金，采纳后释放给投稿人，过期/取消自动退回。
      </div>
    </div>

    <div class="section">
      <h3 class="section-title">充值 / 发放</h3>
      <div class="topup-row">
        <el-input-number v-model="amount" :min="1" :max="100000" :step="50" />
        <el-button type="primary" :icon="Promotion" @click="topup">充值赏金</el-button>
      </div>
    </div>

    <div class="section">
      <h3 class="section-title">收支流水</h3>
      <el-empty v-if="!transactions.length" description="暂无流水记录" />
      <el-table v-else :data="transactions" stripe>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ kindText(row.kind) }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120" align="center">
          <template #default="{ row }">
            <span :class="row.delta >= 0 ? 'in' : 'out'">{{ row.delta >= 0 ? '+' : '' }}{{ row.delta }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="balance_after" label="余额" width="100" align="center" />
        <el-table-column prop="memo" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ row.created_at?.slice(0, 19) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { GoldMedal, Promotion } from '@element-plus/icons-vue'
import request from '../utils/request'

const loading = ref(false)
const balance = ref(0)
const enabled = ref(false)
const transactions = ref([])
const amount = ref(100)

const kindText = (k) => ({
  topup: '充值', grant: '系统发放', freeze: '发布冻结',
  release: '中标入账', release_back: '冻结扣回', refund: '退回',
}[k] || k)

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/bounty/wallet')
    balance.value = res.data.balance || 0
    enabled.value = !!res.data.enabled
    transactions.value = res.data.transactions || []
  } finally {
    loading.value = false
  }
}

const topup = async () => {
  if (amount.value <= 0) return ElMessage.warning('请输入有效金额')
  await request.post('/api/bounty/wallet/topup', { amount: amount.value })
  ElMessage.success('充值成功')
  await load()
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
.section-title { font-size: 16px; font-weight: 600; margin: 0 0 16px; }
.balance-card { text-align: center; }
.bal-label { color: var(--el-text-color-secondary, #909399); font-size: 14px; }
.bal-value { font-size: 40px; font-weight: 700; color: var(--el-color-warning, #e6a23c); display: flex; align-items: center; justify-content: center; gap: 8px; margin: 8px 0; }
.escrow-tip { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.topup-row { display: flex; gap: 12px; align-items: center; }
.in { color: var(--el-color-success, #67c23a); font-weight: 600; }
.out { color: var(--el-color-danger, #f56c6c); font-weight: 600; }
</style>
