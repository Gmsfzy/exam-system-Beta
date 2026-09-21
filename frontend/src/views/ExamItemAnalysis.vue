<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>试题分析</h2>
        <p>逐题得分率、高低分组区分度（27% 法）与选项分布，定位需改进的题目</p>
      </div>
      <div class="header-actions">
        <el-button @click="goBack">
          <el-icon><ArrowLeft /></el-icon>返回
        </el-button>
      </div>
    </div>

    <el-empty v-if="!loading && analysis.participants === 0" description="暂无成绩数据，先发布考试并有学生交卷后再来查看" />

    <template v-else>
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-value">{{ analysis.participants }}</div>
          <div class="stat-label">有效样本人数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ (analysis.questions || []).length }}</div>
          <div class="stat-label">题目数</div>
        </div>
        <div class="stat-card warn">
          <div class="stat-value">{{ lowRateCount }}</div>
          <div class="stat-label">得分率&lt;40% 题数</div>
        </div>
        <div class="stat-card warn">
          <div class="stat-value">{{ lowDiscCount }}</div>
          <div class="stat-label">区分度&lt;0.2 题数</div>
        </div>
      </div>

      <el-card class="section-card" shadow="never">
        <template #header><span class="section-title">逐题指标</span></template>
        <el-table :data="analysis.questions || []" border size="small" :default-sort="{ prop: 'score_rate', order: 'ascending' }">
          <el-table-column prop="order" label="题号" width="60" />
          <el-table-column prop="content" label="题目" min-width="220" show-overflow-tooltip />
          <el-table-column prop="type" label="题型" width="90">
            <template #default="{ row }">{{ typeLabels[row.type] || row.type }}</template>
          </el-table-column>
          <el-table-column prop="knowledge" label="知识点" width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ row.knowledge || '—' }}</template>
          </el-table-column>
          <el-table-column prop="score_rate" label="得分率" width="160" sortable>
            <template #default="{ row }">
              <el-progress
                v-if="row.score_rate !== null"
                :percentage="Math.round(row.score_rate * 100)"
                :stroke-width="12"
                :status="row.score_rate < 0.4 ? 'exception' : row.score_rate >= 0.8 ? 'success' : ''"
              />
              <span v-else>无人作答</span>
            </template>
          </el-table-column>
          <el-table-column prop="discrimination" label="区分度" width="110" sortable>
            <template #default="{ row }">
              <el-tag v-if="row.discrimination !== null" size="small"
                      :type="row.discrimination < 0.1 ? 'danger' : row.discrimination < 0.2 ? 'warning' : 'success'">
                {{ row.discrimination.toFixed(2) }}
              </el-tag>
              <span v-else>样本不足</span>
            </template>
          </el-table-column>
          <el-table-column label="选项分布" min-width="180">
            <template #default="{ row }">
              <span v-for="o in row.option_dist" :key="o.option" class="opt-chip">
                {{ o.option }}: {{ o.count }}
              </span>
              <span v-if="!row.option_dist.length">—</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="section-card" shadow="never">
        <template #header><span class="section-title">知识点掌握（按得分率升序，最薄弱在前）</span></template>
        <el-table :data="analysis.knowledge || []" border size="small">
          <el-table-column prop="knowledge" label="知识点" min-width="180">
            <template #default="{ row }">
              {{ row.knowledge }}
              <el-tag v-if="row.knowledge_point_id" size="small" type="info" effect="plain" style="margin-left: 6px">主数据</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="question_count" label="涉及题数" width="100" />
          <el-table-column prop="avg_discrimination" label="平均区分度" width="110" sortable :sort-method="(a, b) => (a.avg_discrimination ?? -9) - (b.avg_discrimination ?? -9)">
            <template #default="{ row }">{{ row.avg_discrimination !== null && row.avg_discrimination !== undefined ? row.avg_discrimination.toFixed(2) : '—' }}</template>
          </el-table-column>
          <el-table-column label="平均得分率" min-width="220">
            <template #default="{ row }">
              <el-progress :percentage="Math.round(row.avg_score_rate * 100)" :stroke-width="14"
                           :status="row.avg_score_rate < 0.4 ? 'exception' : row.avg_score_rate >= 0.8 ? 'success' : ''" />
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
import { ArrowLeft } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const router = useRouter()

const analysis = ref({})
const loading = ref(true)

// v4.6.1 枚举收敛：题型中文名单一来源 frontend/src/utils/enums.js
import { QUESTION_TYPE_LABELS } from '../utils/enums'

const typeLabels = QUESTION_TYPE_LABELS

const lowRateCount = computed(() =>
  (analysis.value.questions || []).filter(q => q.score_rate !== null && q.score_rate < 0.4).length)
const lowDiscCount = computed(() =>
  (analysis.value.questions || []).filter(q => q.discrimination !== null && q.discrimination < 0.2).length)

onMounted(async () => {
  try {
    const res = await request.get(`/api/exams/${route.params.id}/item_analysis`)
    analysis.value = res.data
  } catch (e) {
    console.error('加载试题分析失败', e)
  } finally {
    loading.value = false
  }
})

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

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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

.opt-chip {
  display: inline-block;
  padding: 2px 8px;
  margin: 2px 4px 2px 0;
  background: rgba(99, 102, 241, 0.08);
  color: #6366f1;
  border-radius: 6px;
  font-size: 12px;
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
