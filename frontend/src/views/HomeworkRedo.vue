<template>
  <div class="page-wrapper" v-loading="loading">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><EditPen /></el-icon> 待订正</h2>
        <div class="sub">老师退回的作业可在此查看反馈并重新提交</div>
      </div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <el-empty v-if="!loading && !items.length" description="暂无待订正作业" />
    <div v-else class="redo-list">
      <el-card v-for="it in items" :key="it.homework_id" class="redo-card" shadow="never">
        <div class="card-head">
          <span class="hw-title">{{ it.title }}</span>
          <el-tag size="small" effect="plain">{{ it.hw_type === 'open' ? '开放式' : '题集式' }}</el-tag>
          <el-tag v-if="it.is_group" size="small" type="success" effect="plain">小组</el-tag>
          <el-tag size="small" type="warning">第 {{ it.revision_round + 1 }} 次订正</el-tag>
        </div>
        <div class="card-meta">
          <span v-if="it.has_deadline">截止 {{ (it.deadline || '').slice(0, 16) }}</span>
          <span v-else>长期有效·不限期</span>
          <span v-if="it.total_score != null" class="prev-score">
            上次得分 <b>{{ it.total_score }}</b><span v-if="it.max_score"> / {{ it.max_score }}</span>
          </span>
        </div>
        <div class="feedback">
          <span class="fb-label">老师退回意见：</span>
          <span class="fb-text">{{ it.comment || '（未填写，请结合批改反馈订正）' }}</span>
        </div>
        <div class="card-foot">
          <el-button type="primary" :icon="EditPen" @click="goRedo(it)">开始订正</el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { EditPen, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const router = useRouter()
const loading = ref(false)
const items = ref([])

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/homeworks/redo')
    items.value = res.data.items || []
  } catch (e) {
    ElMessage.error('加载待订正列表失败')
  } finally {
    loading.value = false
  }
}

const goRedo = (it) => router.push(`/homeworks/${it.homework_id}/take`)

onMounted(load)
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.header-title h2 { margin: 0; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #e6a23c; }
.sub { font-size: 13px; color: #909399; margin-top: 4px; }
.redo-list { display: flex; flex-direction: column; gap: 14px; }
.redo-card { border-radius: 12px; }
.card-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hw-title { font-size: 16px; font-weight: 600; color: #303133; }
.card-meta { display: flex; align-items: center; gap: 16px; font-size: 13px; color: #606266; margin-top: 8px; }
.prev-score b { color: #f56c6c; font-size: 16px; }
.feedback { margin-top: 10px; padding: 10px 12px; border-radius: 8px; font-size: 13px;
  background: #fdf6ec; border: 1px solid #faecd8; color: #b88230; line-height: 1.6; }
.fb-label { font-weight: 600; }
.fb-text { color: #7c5c1e; }
.card-foot { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
