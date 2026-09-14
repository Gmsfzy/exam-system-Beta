<template>
  <div class="study-plan">
    <div class="page-header">
      <h1>学习计划</h1>
      <p class="subtitle">设定目标，追踪进度</p>
      <el-button type="primary" @click="showDialog()">+ 新建计划</el-button>
    </div>

    <el-empty v-if="plans.length === 0 && !loading" description="还没有学习计划，创建一个开始吧" />

    <div class="plan-grid">
      <div v-for="p in plans" :key="p.id" class="plan-card">
        <div class="plan-header">
          <h3>{{ p.title }}</h3>
          <el-tag :type="statusTagType(p.status)" size="small">{{ statusLabel(p.status) }}</el-tag>
        </div>
        <p class="plan-desc">{{ p.description || '—' }}</p>

        <div class="plan-meta">
          <el-tag v-if="p.major_name" size="small">{{ p.major_name }}</el-tag>
          <el-tag v-if="p.course_name" size="small" type="info">{{ p.course_name }}</el-tag>
          <span class="plan-dates">{{ p.start_date }} ~ {{ p.end_date || '长期' }}</span>
        </div>

        <div class="progress-wrap">
          <el-progress
            :percentage="Math.min(100, p.progress)"
            :stroke-width="8"
            :color="p.progress >= 100 ? '#10b981' : '#6366f1'"
            :format="() => `${p.completed_count}/${p.target_count}`"
          />
        </div>

        <div class="plan-actions">
          <el-button size="small" v-if="p.status !== 'completed'" @click="toggleStatus(p)">
            {{ p.status === 'paused' ? '恢复' : '暂停' }}
          </el-button>
          <el-button size="small" @click="showDialog(p)">编辑</el-button>
          <el-button size="small" type="danger" @click="removePlan(p)">删除</el-button>
        </div>
      </div>
    </div>

    <!-- 创建/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑计划' : '新建学习计划'" width="520px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="如：《数据结构》每日刷题" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="目标题数">
          <el-input-number v-model="form.target_count" :min="1" :max="1000" />
        </el-form-item>
        <el-form-item label="专业">
          <el-select v-model="form.major_id" placeholder="可选" clearable style="width:100%">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import request from '../utils/request'
import { ElMessage, ElMessageBox } from 'element-plus'

const plans = ref([])
const majors = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const dateRange = ref([])

const form = ref({
  title: '', description: '', target_count: 50,
  major_id: null, course_id: null, chapter_id: null,
  start_date: null, end_date: null,
})

function statusLabel(s) { return { active: '进行中', paused: '已暂停', completed: '已完成' }[s] || s }
function statusTagType(s) { return { active: 'success', paused: 'info', completed: '' }[s] || '' }

async function load() {
  loading.value = true
  try {
    const res = await request.get('/api/learning/plans')
    plans.value = res.data || []
  } catch (e) {}
  loading.value = false
}

async function loadMajors() {
  try { majors.value = (await request.get('/api/majors')).data || [] } catch (e) {}
}

function showDialog(p = null) {
  editing.value = p
  if (p) {
    form.value = {
      title: p.title, description: p.description,
      target_count: p.target_count, major_id: p.major_id,
      course_id: p.course_id, chapter_id: p.chapter_id,
      start_date: p.start_date, end_date: p.end_date,
    }
    dateRange.value = p.end_date ? [p.start_date, p.end_date] : [p.start_date, null]
  } else {
    form.value = { title: '', description: '', target_count: 50, major_id: null, start_date: null, end_date: null }
    dateRange.value = []
  }
  dialogVisible.value = true
}

async function save() {
  if (!form.value.title.trim()) { ElMessage.warning('请填写标题'); return }
  const start = dateRange.value?.[0] || new Date().toISOString().slice(0, 10)
  const end = dateRange.value?.[1] || null
  const payload = { ...form.value, start_date: start, end_date: end }
  try {
    if (editing.value) {
      await request.put(`/api/learning/plans/${editing.value.id}`, payload)
      ElMessage.success('已更新')
    } else {
      await request.post('/api/learning/plans', payload)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    load()
  } catch (e) {}
}

async function toggleStatus(p) {
  try {
    await request.post(`/api/learning/plans/${p.id}/pause`)
    ElMessage.success('已更新')
    load()
  } catch (e) {}
}

async function removePlan(p) {
  await ElMessageBox.confirm(`确定删除计划「${p.title}」？`, '确认')
  try {
    await request.delete(`/api/learning/plans/${p.id}`)
    ElMessage.success('已删除')
    load()
  } catch (e) {}
}

onMounted(() => { load(); loadMajors() })
</script>

<style scoped>
.study-plan { padding: 20px; max-width: 1000px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-header h1 { font-size: 22px; margin: 0 0 4px; color: var(--text-primary); }
.subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }

.plan-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }

.plan-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 18px 20px;
}
.plan-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.plan-header h3 { font-size: 16px; margin: 0; color: var(--text-primary); }
.plan-desc { font-size: 13px; color: var(--text-muted); margin: 0 0 10px; }
.plan-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.plan-dates { font-size: 12px; color: var(--text-muted); margin-left: auto; }

.progress-wrap { margin-bottom: 14px; }
.plan-actions { display: flex; gap: 8px; }
</style>
