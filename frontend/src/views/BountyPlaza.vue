<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Money /></el-icon> 征集悬赏</h2>
        <p><span class="sub-info">发布题目/答案需求，投稿被采纳即可获得竞技积分</span></p>
      </div>
      <el-button type="primary" :icon="EditPen" @click="$router.push('/bounties/publish')">发布悬赏</el-button>
    </div>

    <div class="filters">
      <el-radio-group v-model="typeFilter" @change="load">
        <el-radio-button label="">全部类型</el-radio-button>
        <el-radio-button label="question">题目征集</el-radio-button>
        <el-radio-button label="answer">答案征集</el-radio-button>
      </el-radio-group>
      <el-radio-group v-model="statusFilter" @change="load">
        <el-radio-button label="">全部状态</el-radio-button>
        <el-radio-button label="open">征集中</el-radio-button>
        <el-radio-button label="closed">已采纳</el-radio-button>
      </el-radio-group>
    </div>

    <el-empty v-if="!loading && !bounties.length" description="暂无悬赏，去发布第一个吧" />

    <div class="bounty-grid">
      <div v-for="b in bounties" :key="b.id" class="bounty-card" @click="$router.push(`/bounties/${b.id}`)">
        <div class="card-top">
          <el-tag size="small" :type="b.bounty_type === 'question' ? 'primary' : 'success'" effect="light">
            {{ b.bounty_type === 'question' ? '题目征集' : '答案征集' }}
          </el-tag>
          <el-tag size="small" :type="statusTag(b.status)" effect="plain">{{ statusText(b.status) }}</el-tag>
        </div>
        <div class="card-title">{{ b.title }}</div>
        <div class="card-desc">{{ b.description || '暂无详细描述' }}</div>
        <div class="card-meta">
          <span class="reward"><el-icon><GoldMedal /></el-icon> {{ b.reward_points }} 积分</span>
          <span class="meta-item">投稿 {{ b.submission_count }}</span>
        </div>
        <div class="card-foot">
          <span class="publisher">{{ b.publisher_name }}</span>
          <span class="deadline">截止：{{ b.deadline ? b.deadline.slice(0, 16) : '长期有效' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Money, EditPen, GoldMedal } from '@element-plus/icons-vue'
import request from '../utils/request'

const bounties = ref([])
const loading = ref(false)
const typeFilter = ref('')
const statusFilter = ref('')

const statusText = (s) => ({ open: '征集中', closed: '已采纳', expired: '已过期' }[s] || s)
const statusTag = (s) => ({ open: 'warning', closed: 'success', expired: 'info' }[s] || 'info')

const load = async () => {
  loading.value = true
  try {
    const params = {}
    if (typeFilter.value) params.type = typeFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await request.get('/api/bounties', { params })
    bounties.value = res.data || []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.bounty-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
.bounty-card {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px;
  padding: 18px;
  cursor: pointer;
  transition: all .2s;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.bounty-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(0,0,0,.08);
  border-color: var(--el-color-primary, #409eff);
}
.card-top {
  display: flex;
  justify-content: space-between;
}
.card-title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
}
.card-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary, #909399);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 36px;
}
.card-meta {
  display: flex;
  gap: 16px;
  align-items: center;
  font-size: 14px;
}
.reward {
  color: var(--el-color-warning, #e6a23c);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 4px;
}
.meta-item {
  color: var(--el-text-color-secondary, #909399);
}
.card-foot {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  border-top: 1px dashed var(--el-border-color-lighter, #ebeef5);
  padding-top: 8px;
}
</style>
