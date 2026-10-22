<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Warning /></el-icon> 防作弊监测</h2>
      </div>
      <el-button :icon="Refresh" @click="loadHomeworks">刷新作业列表</el-button>
    </div>

    <div class="toolbar">
      <span class="label">选择作业</span>
      <el-select v-model="hwId" filterable placeholder="选择要查看的作业" style="width: 320px"
                 @change="loadMonitor">
        <el-option v-for="h in homeworks" :key="h.id" :label="h.title" :value="h.id">
          <span>{{ h.title }}</span>
          <el-tag v-if="h.enable_monitor" size="small" type="success" effect="plain"
                  style="margin-left: 8px">已开启监测</el-tag>
        </el-option>
      </el-select>
      <span v-if="hwId && !data.homework?.enable_monitor" class="muted small">
        该作业未开启防作弊监测（可在作业管理勾选「防作弊监测」）
      </span>
    </div>

    <el-skeleton v-if="loading" :rows="5" animated style="padding: 12px" />
    <el-empty v-else-if="!hwId" description="请选择一个作业查看监测看板" />
    <template v-else>
      <div class="summary">
        <span>异常学生 <b>{{ data.summary?.students_with_events ?? 0 }}</b> 人</span>
        <span>事件总数 <b>{{ data.summary?.total_events ?? 0 }}</b></span>
      </div>

      <el-empty v-if="!students.length" description="暂无异常事件记录（作答未触发或该生行为正常）" />
      <el-table v-else :data="students" stripe>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="timeline">
              <div v-for="(ev, i) in row.timeline" :key="i" class="tl-item">
                <el-tag size="small" :type="typeTag(ev.type)">{{ typeText(ev.type) }}</el-tag>
                <span class="tl-at">{{ fmt(ev.at) }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="学生" min-width="140" />
        <el-table-column label="异常总数" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.total >= 5 ? 'danger' : (row.total >= 3 ? 'warning' : 'info')">
              {{ row.total }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-for="t in types" :key="t" :label="typeText(t)" width="110" align="center">
          <template #default="{ row }">{{ row.counts[t] || 0 }}</template>
        </el-table-column>
      </el-table>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Warning, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const homeworks = ref([])
const hwId = ref(null)
const loading = ref(false)
const data = ref({})

const students = computed(() => data.value.students || [])
const types = computed(() => data.value.event_types || ['tab_switch', 'blur', 'paste', 'copy'])

const TYPE_LABELS = { tab_switch: '切屏', blur: '失焦', paste: '粘贴', copy: '复制' }
const typeText = (t) => TYPE_LABELS[t] || t
const typeTag = (t) => (t === 'paste' || t === 'copy' ? 'danger' : 'warning')
const fmt = (v) => (v || '').slice(0, 19).replace('T', ' ')

const loadHomeworks = async () => {
  const res = await request.get('/api/homeworks')
  homeworks.value = (res.data.items || []).filter(h => h.status !== 'draft')
}

const loadMonitor = async () => {
  if (!hwId.value) return
  loading.value = true
  data.value = {}
  try {
    const res = await request.get(`/api/homeworks/${hwId.value}/monitor`)
    data.value = res.data
  } catch (e) {
    ElMessage.error('加载监测数据失败')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadHomeworks()
  const first = homeworks.value.find(h => h.enable_monitor)
  if (first) { hwId.value = first.id; loadMonitor() }
})
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #f56c6c; }
.toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.label { font-weight: 500; color: #4b5563; }
.summary {
  display: flex; gap: 20px; align-items: center; padding: 10px 14px; margin-bottom: 12px;
  border-radius: 10px; font-size: 14px; color: #606266;
  background: linear-gradient(135deg, rgba(245, 108, 108, 0.08), rgba(245, 158, 11, 0.05));
}
.summary b { color: #d97706; font-size: 17px; }
.muted { color: #909399; }
.small { font-size: 12px; }
.timeline { display: flex; flex-direction: column; gap: 6px; padding: 8px 24px; }
.tl-item { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.tl-at { color: #6b7280; }
:deep(.el-table__row) { cursor: default; }
</style>
