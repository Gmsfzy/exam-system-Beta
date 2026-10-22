<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Notebook /></el-icon> 我的作业</h2>
      </div>
      <div class="header-actions">
        <el-badge :value="peerPending" :hidden="!peerPending" :max="99">
          <el-button :icon="UserFilled" @click="router.push('/homeworks/peer-reviews')">
            互评任务
          </el-button>
        </el-badge>
        <el-button :icon="Refresh" circle @click="load" />
      </div>
    </div>

    <el-radio-group v-model="view" style="margin-bottom: 12px">
      <el-radio-button label="all">全部</el-radio-button>
      <el-radio-button label="weekly">本周作业</el-radio-button>
    </el-radio-group>

    <template v-if="view === 'weekly'">
      <el-empty v-if="!weekly.length" description="本周暂无作业" />
      <div v-else class="cards">
        <el-card v-for="hw in weekly" :key="hw.id" class="hw-card" shadow="hover">
          <div class="card-top">
            <span class="hw-title">{{ hw.title }}</span>
            <el-tag size="small" :type="hw.submitted ? 'success' : 'warning'">
              {{ hw.submitted ? '已提交' : '待完成' }}
            </el-tag>
          </div>
          <div class="meta">
            <span>教师：{{ hw.teacher_name || '—' }}</span>
            <span v-if="hw.has_deadline" :class="{ overdue: hw.is_expired }">截止：{{ (hw.deadline || '').slice(0, 16) }}</span>
            <span v-else>不限期</span>
            <span v-if="hw.graded">成绩：{{ hw.total_score }}</span>
          </div>
          <div class="card-foot">
            <el-button type="primary" size="small" @click="router.push(`/homeworks/${hw.id}/take`)">
              {{ hw.submitted ? '查看' : '去作答' }}
            </el-button>
          </div>
        </el-card>
      </div>
    </template>

    <template v-else>
    <el-empty v-if="!items.length" description="老师还没有发布作业" />
    <div v-else class="cards">
      <el-card v-for="hw in items" :key="hw.id" class="hw-card" shadow="hover">
        <div class="card-top">
          <span class="hw-title">{{ hw.title }}</span>
          <el-tag size="small" :type="hw.hw_type === 'open' ? 'success' : 'primary'" effect="plain">
            {{ hw.hw_type === 'open' ? '开放式' : '题集式' }}
          </el-tag>
        </div>
        <div class="hw-desc" v-if="hw.description">{{ hw.description }}</div>
        <div class="meta">
          <span>教师：{{ hw.teacher_name || '—' }}</span>
          <span v-if="hw.has_deadline" :class="{ overdue: hw.is_expired }">截止：{{ (hw.deadline || '').slice(0, 16) }}</span>
          <span v-else>截止：长期有效·不限期</span>
          <span v-if="hw.hw_type !== 'open'">满分：{{ hw.total_score }}</span>
        </div>
        <div class="card-foot">
          <el-tag v-if="!hw.my_submission" size="small" type="info">未提交</el-tag>
          <el-tag v-else-if="hw.my_submission.status === 'draft'" size="small" type="info">草稿</el-tag>
          <el-tag v-else-if="hw.my_submission.status === 'submitted'" size="small" type="warning">待批改</el-tag>
          <el-tag v-else size="small" type="success">
            已批 {{ hw.my_submission.total_score }}/{{ hw.my_submission.max_score ?? '—' }}
          </el-tag>
          <el-button type="primary" size="small" @click="go(hw)">{{ btnText(hw) }}</el-button>
        </div>
      </el-card>
    </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Notebook, Refresh, UserFilled } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()
const items = ref([])
const peerPending = ref(0)
const view = ref('all')
const weekly = ref([])

const load = async () => {
  const [res, peer] = await Promise.all([
    request.get('/api/homeworks'),
    request.get('/api/homeworks/peer_reviews/mine')
  ])
  items.value = res.data.items || []
  peerPending.value = peer.data.pending_count || 0
}

const loadWeekly = async () => {
  const res = await request.get('/api/homeworks/weekly')
  weekly.value = res.data.items || []
}

watch(view, (v) => { if (v === 'weekly') loadWeekly() })

const btnText = (hw) => {
  const s = hw.my_submission?.status
  if (!s || s === 'draft') return hw.is_expired ? '查看' : '去作答'
  if (s === 'submitted') return hw.is_expired ? '查看' : '重交'
  return '查看成绩'
}

const go = (hw) => router.push(`/homeworks/${hw.id}/take`)

onMounted(load)
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.header-actions { display: flex; align-items: center; gap: 14px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.hw-card { border-radius: 10px; }
.card-top { display: flex; justify-content: space-between; align-items: center; }
.hw-title { font-size: 16px; font-weight: 600; }
.hw-desc { margin: 8px 0; font-size: 13px; color: #606266; max-height: 40px; overflow: hidden; }
.meta { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; color: #909399; margin-bottom: 12px; }
.overdue { color: #f56c6c; }
.card-foot { display: flex; justify-content: space-between; align-items: center; }
</style>
