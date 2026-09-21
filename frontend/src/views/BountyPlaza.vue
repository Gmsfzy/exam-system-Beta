<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Money /></el-icon> 征集悬赏</h2>
        <p><span class="sub-info">发布题目/答案需求，投稿被采纳即可获得竞技积分</span></p>
      </div>
      <div class="header-actions">
        <el-button :icon="Trophy" @click="$router.push('/bounties/leaderboard')">贡献榜</el-button>
        <el-button :icon="Wallet" @click="$router.push('/bounties/wallet')">赏金钱包</el-button>
        <el-button type="primary" :icon="EditPen" @click="$router.push('/bounties/publish')">发布悬赏</el-button>
      </div>
    </div>

    <!-- v4.5 待审核悬赏（教师互审） -->
    <div v-if="isTeacher && pendingList.length" class="pending-panel">
      <h3>🔍 待审核悬赏（{{ pendingList.length }}）</h3>
      <div v-for="p in pendingList" :key="p.id" class="pending-row">
        <div class="p-info">
          <span class="p-title">{{ p.title }}</span>
          <span class="p-meta">{{ p.publisher_name }} · {{ p.bounty_type === 'question' ? '题目征集' : '答案征集' }} · {{ p.reward_points }} 积分<template v-if="p.frozen_points">（已托管 {{ p.frozen_points }}）</template></span>
        </div>
        <span class="p-ops">
          <el-button size="small" type="success" @click="reviewBounty(p, 'approve')">通过</el-button>
          <el-button size="small" type="danger" plain @click="reviewBounty(p, 'reject')">驳回</el-button>
        </span>
      </div>
    </div>

    <div class="filters">
      <el-input v-model="keyword" placeholder="搜索标题 / 描述 / 标签" clearable
                :prefix-icon="Search" style="max-width: 260px" @keyup.enter="reload" @clear="reload" />
      <el-select v-model="typeFilter" placeholder="全部类型" style="width: 130px" @change="reload">
        <el-option label="全部类型" value="" />
        <el-option label="题目征集" value="question" />
        <el-option label="答案征集" value="answer" />
      </el-select>
      <el-select v-model="statusFilter" placeholder="全部状态" style="width: 130px" @change="reload">
        <el-option label="全部状态" value="" />
        <el-option label="征集中" value="open" />
        <el-option label="已采纳" value="closed" />
        <el-option label="已过期" value="expired" />
        <el-option label="已关闭" value="cancelled" />
      </el-select>
      <el-select v-model="sort" placeholder="排序" style="width: 130px" @change="reload">
        <el-option label="最新发布" value="created" />
        <el-option label="赏金最高" value="reward" />
        <el-option label="最近截止" value="deadline" />
        <el-option label="最热门" value="hot" />
      </el-select>
    </div>

    <el-empty v-if="!loading && !bounties.length" description="暂无悬赏，去发布第一个吧" />

    <div class="bounty-grid" v-loading="loading">
      <div v-for="b in bounties" :key="b.id" class="bounty-card" @click="$router.push(`/bounties/${b.id}`)">
        <div class="card-top">
          <el-tag size="small" :type="b.bounty_type === 'question' ? 'primary' : 'success'" effect="light">
            {{ b.bounty_type === 'question' ? '题目征集' : '答案征集' }}
          </el-tag>
          <el-tag size="small" :type="statusTag(b.status)" effect="plain">{{ statusText(b.status) }}</el-tag>
        </div>
        <div class="card-title">{{ b.title }}</div>
        <div class="card-desc">{{ b.description || '暂无详细描述' }}</div>
        <div v-if="b.tags" class="card-tags">
          <el-tag v-for="t in b.tags.split(',').slice(0,4)" :key="t" size="small" effect="plain" type="info">{{ t.trim() }}</el-tag>
        </div>
        <div class="card-meta">
          <span class="reward"><el-icon><GoldMedal /></el-icon> {{ b.reward_points }} 积分</span>
          <span class="meta-item">投稿 {{ b.submission_count }}</span>
          <span v-if="(b.max_accepts || 1) > 1" class="meta-item">可采纳 {{ b.accept_count }}/{{ b.max_accepts }}</span>
          <span v-if="b.visibility === 'targeted'" class="meta-item targeted"><el-icon><Lock /></el-icon> 定向</span>
        </div>
        <div class="card-foot">
          <span class="publisher">{{ b.publisher_name }}</span>
          <span class="deadline">截止：{{ b.deadline ? b.deadline.slice(0, 16) : '长期有效' }}</span>
        </div>
      </div>
    </div>

    <el-pagination v-if="total > pageSize" class="pager" background layout="prev, pager, next, total"
                   :current-page="page" :page-size="pageSize" :total="total" @current-change="onPage" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Money, EditPen, GoldMedal, Search, Trophy, Wallet, Lock } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isTeacher = computed(() => auth.user?.role === 'teacher')

const bounties = ref([])
const loading = ref(false)
const typeFilter = ref('')
const statusFilter = ref('')
const sort = ref('created')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(12)
const total = ref(0)

const statusText = (s) => ({ open: '征集中', closed: '已采纳', expired: '已过期', cancelled: '已关闭', reviewing: '待审核', rejected: '被驳回' }[s] || s)
const statusTag = (s) => ({ open: 'warning', closed: 'success', expired: 'info', cancelled: 'info', reviewing: 'warning', rejected: 'danger' }[s] || 'info')

// v4.5 待审核列表（教师）
const pendingList = ref([])
const loadPending = async () => {
  if (!isTeacher.value) return
  try {
    const res = await request.get('/api/bounties/pending')
    pendingList.value = res.data || []
  } catch (e) { /* 忽略 */ }
}
const reviewBounty = async (p, action) => {
  if (action === 'approve') {
    try {
      await ElMessageBox.confirm(`确认通过「${p.title}」？通过后将上架悬赏广场`, '审核通过')
    } catch (e) { return }
    await request.post(`/api/bounties/${p.id}/review`, { action })
    ElMessage.success('已通过')
  } else {
    try {
      const { value } = await ElMessageBox.prompt(`驳回「${p.title}」，请填写理由（托管赏金将退回发布者）`, '审核驳回', { inputPattern: /\S+/, inputErrorMessage: '请填写理由' })
      await request.post(`/api/bounties/${p.id}/review`, { action, reason: value })
      ElMessage.success('已驳回')
    } catch (e) { return }
  }
  loadPending(); load()
}

const load = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value, sort: sort.value }
    if (typeFilter.value) params.type = typeFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    if (keyword.value.trim()) params.q = keyword.value.trim()
    const res = await request.get('/api/bounties', { params })
    const data = res.data || {}
    bounties.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const reload = () => { page.value = 1; load() }
const onPage = (p) => { page.value = p; load() }

onMounted(() => { load(); loadPending() })
</script>

<style scoped>
.pending-panel { background: #fffbeb; border: 1px solid #f3d19e; border-radius: 10px; padding: 12px 16px; margin-bottom: 14px; }
.pending-panel h3 { margin: 0 0 8px; font-size: 15px; }
.pending-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-top: 1px dashed #f0dcb2; flex-wrap: wrap; }
.p-info { display: flex; flex-direction: column; gap: 2px; }
.p-title { font-weight: 600; }
.p-meta { color: #909399; font-size: 12px; }
.header-actions { display: flex; gap: 8px; }
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
  min-height: 120px;
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
.card-top { display: flex; justify-content: space-between; }
.card-title { font-size: 16px; font-weight: 600; line-height: 1.4; }
.card-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary, #909399);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 36px;
}
.card-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.card-meta { display: flex; gap: 16px; align-items: center; font-size: 14px; flex-wrap: wrap; }
.reward { color: var(--el-color-warning, #e6a23c); font-weight: 600; display: flex; align-items: center; gap: 4px; }
.meta-item { color: var(--el-text-color-secondary, #909399); display: flex; align-items: center; gap: 2px; }
.meta-item.targeted { color: var(--el-color-danger, #f56c6c); }
.card-foot {
  display: flex; justify-content: space-between; font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  border-top: 1px dashed var(--el-border-color-lighter, #ebeef5); padding-top: 8px;
}
.pager { margin-top: 24px; justify-content: center; }
</style>
