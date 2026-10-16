<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>代码查重</h2>
        <p>对编程题作答做词法归一 + shingle 相似度比对，辅助人工判定抄袭（供参考，不自动定责）</p>
      </div>
      <div class="header-actions">
        <el-input-number
          v-model="threshold"
          :min="0.3" :max="1" :step="0.05" :precision="2"
          size="small" controls-position="right"
          style="width: 120px; margin-right: 10px"
        />
        <el-button type="primary" size="small" :loading="loading" @click="loadReport">
          <el-icon><Refresh /></el-icon>重新检测
        </el-button>
        <el-button size="small" @click="goBack">
          <el-icon><ArrowLeft /></el-icon>返回
        </el-button>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ checkedQuestions }}</div>
        <div class="stat-label">涉查编程题</div>
      </div>
      <div class="stat-card warn">
        <div class="stat-value">{{ totalPairs }}</div>
        <div class="stat-label">疑似相似对</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ (threshold * 100).toFixed(0) }}%</div>
        <div class="stat-label">当前阈值</div>
      </div>
    </div>

    <el-empty v-if="!loading && totalPairs === 0" description="未发现相似度达到阈值的代码对" />

    <template v-else>
      <el-card v-for="item in items" :key="item.question_id" class="section-card" shadow="never">
      <template #header>
        <span class="section-title">题目 #{{ item.question_id }}</span>
        <el-tag size="small" type="warning" effect="plain" style="margin-left: 8px">{{ item.pairs.length }} 对疑似</el-tag>
      </template>
      <el-table :data="item.pairs" border size="small">
        <el-table-column label="学生 A" min-width="120">
          <template #default="{ row }">{{ row.a.username }}</template>
        </el-table-column>
        <el-table-column label="学生 B" min-width="120">
          <template #default="{ row }">{{ row.b.username }}</template>
        </el-table-column>
        <el-table-column label="代码 token" width="110">
          <template #default="{ row }">{{ row.tokens }}</template>
        </el-table-column>
        <el-table-column label="相似度" min-width="220">
          <template #default="{ row }">
            <el-progress
              :percentage="Math.round(row.similarity * 100)"
              :stroke-width="14"
              :status="row.similarity >= 0.9 ? 'exception' : row.similarity >= 0.7 ? 'warning' : ''"
            />
          </template>
        </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const router = useRouter()

const items = ref([])
const threshold = ref(0.7)
const loading = ref(true)

const totalPairs = computed(() =>
  items.value.reduce((sum, it) => sum + (it.pairs ? it.pairs.length : 0), 0))
const checkedQuestions = computed(() => items.value.length)

async function loadReport() {
  loading.value = true
  try {
    const res = await request.get(`/api/results/plagiarism/${route.params.id}`, {
      params: { threshold: threshold.value }
    })
    items.value = res.data.items || []
    if (res.data.threshold !== undefined) threshold.value = res.data.threshold
  } catch (e) {
    console.error('加载查重结果失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadReport)

const goBack = () => router.push('/exams')
</script>

<style scoped>
.page-wrapper {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color);
}

.header-title h2 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.header-title p {
  color: var(--text-muted);
  margin: 6px 0 0;
  font-size: 14px;
}

.header-actions {
  display: flex;
  align-items: center;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 20px;
  text-align: center;
}

.stat-card .stat-value {
  font-size: 30px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-card .stat-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 4px;
}

.stat-card.warn .stat-value {
  color: #f59e0b;
}

.section-card {
  margin-bottom: 20px;
  border-radius: 16px;
}

.section-title {
  font-weight: 600;
  color: var(--text-primary);
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(1, 1fr);
  }
}
</style>
