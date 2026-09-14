<template>
  <div class="practice-list">
    <div class="page-header">
      <h1>自由刷题</h1>
      <p class="subtitle">按专业/课程/章节筛选，随时练习不计分</p>
    </div>

    <!-- 筛选区 -->
    <div class="filter-panel">
      <div class="filter-row">
        <label>专业</label>
        <el-select v-model="filter.major_id" placeholder="全部" clearable style="width:180px" @change="loadCourses">
          <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <label>课程</label>
        <el-select v-model="filter.course_id" placeholder="全部" clearable style="width:180px" @change="loadChapters">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <label>章节</label>
        <el-select v-model="filter.chapter_id" placeholder="全部" clearable style="width:180px">
          <el-option v-for="c in chapters" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </div>
      <div class="filter-row">
        <label>题数</label>
        <el-input-number v-model="filter.count" :min="1" :max="50" :step="5" />
        <label>练习名称</label>
        <el-input v-model="filter.title" placeholder="可选" style="width:220px" />
        <el-button type="primary" @click="startPractice">开始练习</el-button>
      </div>
    </div>

    <!-- 练习历史 -->
    <h3 class="section-title">最近练习</h3>
    <el-empty v-if="!loading && history.length === 0" description="还没有练习记录，开始你的第一次刷题吧" />
    <div v-for="s in history" :key="s.id" class="history-card" @click="goDetail(s.id)">
      <div class="h-title">{{ s.title }}</div>
      <div class="h-meta">
        <el-tag v-if="s.status === 'completed'" type="success" size="small">已完成</el-tag>
        <el-tag v-else type="warning" size="small">进行中</el-tag>
        <span>{{ s.questions_count }} 题</span>
        <span v-if="s.score_ratio !== undefined">正确率 {{ (s.score_ratio * 100).toFixed(1) }}%</span>
        <span>{{ formatTime(s.total_time_sec) }}</span>
      </div>
      <div class="h-time">{{ s.start_time }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import request from '../utils/request'
import { ElMessage } from 'element-plus'

const router = useRouter()
const filter = ref({ major_id: null, course_id: null, chapter_id: null, count: 10, title: '' })
const majors = ref([])
const courses = ref([])
const chapters = ref([])
const history = ref([])
const loading = ref(false)

async function loadMajors() {
  try { const res = await request.get('/api/majors'); majors.value = res.data || [] } catch (e) {}
}
async function loadCourses() {
  if (!filter.value.major_id) { courses.value = []; return }
  try {
    const res = await request.get('/api/courses', { params: { major_id: filter.value.major_id } })
    courses.value = res.data || []
  } catch (e) {}
  filter.value.course_id = null
  chapters.value = []
}
async function loadChapters() {
  if (!filter.value.course_id) { chapters.value = []; return }
  try {
    const res = await request.get('/api/chapters', { params: { course_id: filter.value.course_id } })
    chapters.value = res.data || []
  } catch (e) {}
  filter.value.chapter_id = null
}

async function loadHistory() {
  loading.value = true
  try {
    const res = await request.get('/api/learning/practice/history')
    history.value = res.data || []
  } catch (e) {}
  loading.value = false
}

async function startPractice() {
  try {
    const res = await request.post('/api/learning/practice/start', filter.value)
    router.push(`/learning/practice/${res.data.session_id}`)
  } catch (e) { /* 错误已由拦截器处理 */ }
}

function goDetail(id) { router.push(`/learning/practice/${id}`) }

function formatTime(sec) {
  if (!sec) return ''
  const m = Math.floor(sec / 60); const s = sec % 60
  return `${m}分${s}秒`
}

onMounted(() => { loadMajors(); loadHistory() })
</script>

<style scoped>
.practice-list { padding: 20px; max-width: 960px; }
.page-header { margin-bottom: 20px; }
.page-header h1 { font-size: 22px; margin: 0 0 4px; color: var(--text-primary); }
.subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }

.filter-panel {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 18px 20px; margin-bottom: 28px;
}
.filter-row { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.filter-row:last-child { margin-bottom: 0; }
.filter-row label { font-size: 13px; color: var(--text-muted); min-width: 48px; }

.section-title { font-size: 16px; margin: 20px 0 14px; color: var(--text-primary); }

.history-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 10px; padding: 14px 16px; margin-bottom: 10px;
  cursor: pointer; transition: all 0.2s;
}
.history-card:hover { border-color: rgba(99,102,241,0.5); box-shadow: 0 4px 12px rgba(0,0,0,0.06); }
.h-title { font-size: 15px; font-weight: 500; margin-bottom: 6px; color: var(--text-primary); }
.h-meta { display: flex; gap: 14px; font-size: 13px; color: var(--text-muted); align-items: center; }
.h-time { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
</style>
