<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-left" @click="goBack">
        <el-icon :size="18"><ArrowLeft /></el-icon>
        <span>返回大厅</span>
      </div>
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Lightning /></el-icon> 快速对战</h2>
        <p>任选知识点即时抽题，就近匹配同水平对手；无人应答可与训练对手开局</p>
      </div>
      <div class="header-right"></div>
    </div>

    <!-- 配置面板 -->
    <div v-if="phase === 'config'" class="config-card">
      <div class="field">
        <span class="field-label">题目范围</span>
        <el-radio-group v-model="form.scope_type" @change="resetScopeId">
          <el-radio-button label="all">综合速赛</el-radio-button>
          <el-radio-button label="major">专业速赛</el-radio-button>
          <el-radio-button label="chapter">章节速赛</el-radio-button>
        </el-radio-group>
      </div>

      <div v-if="form.scope_type === 'major'" class="field">
        <span class="field-label">选择专业</span>
        <el-select v-model="form.scope_id" placeholder="选择专业" filterable class="scope-select">
          <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
      </div>

      <template v-if="form.scope_type === 'chapter'">
        <div class="field">
          <span class="field-label">选择专业</span>
          <el-select v-model="chMajor" placeholder="选择专业" filterable class="scope-select" @change="onMajorChange">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </div>
        <div class="field">
          <span class="field-label">选择课程</span>
          <el-select v-model="chCourse" placeholder="选择课程" filterable :disabled="!chMajor" class="scope-select" @change="onCourseChange">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </div>
        <div class="field">
          <span class="field-label">选择章节</span>
          <el-select v-model="form.scope_id" placeholder="选择章节" filterable :disabled="!chCourse" class="scope-select">
            <el-option v-for="c in chapters" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </div>
      </template>

      <div class="field">
        <span class="field-label">题目数量</span>
        <el-slider v-model="form.count" :min="3" :max="15" :step="1" show-stops class="slider" />
        <span class="field-value">{{ form.count }} 题</span>
      </div>
      <div class="field">
        <span class="field-label">对战时长</span>
        <el-slider v-model="form.duration" :min="1" :max="15" :step="1" show-stops class="slider" />
        <span class="field-value">{{ form.duration }} 分钟</span>
      </div>

      <el-button type="warning" size="large" class="start-btn" :loading="starting" @click="startMatch">
        <el-icon style="margin-right: 6px"><Lightning /></el-icon>开始匹配对手
      </el-button>
    </div>

    <!-- 匹配中 -->
    <div v-else-if="phase === 'matching'" class="match-card">
      <el-icon :size="46" class="spin"><Loading /></el-icon>
      <h3>正在为你寻找势均力敌的对手…</h3>
      <p class="match-sub">{{ matchingMsg }}</p>
      <div class="countdown-ring">
        <el-progress type="circle" :percentage="matchPercent" :width="120" :stroke-width="8" />
        <div class="cd-text">{{ secondsLeft }}s</div>
      </div>
      <div class="match-actions">
        <el-button type="success" @click="joinBot">和训练对手开局</el-button>
        <el-button @click="cancelMatch">取消</el-button>
      </div>
      <p v-if="secondsLeft <= 0" class="match-tip">暂未匹配到真人对手，可与训练对手立即开始，或继续等待</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import { ArrowLeft, Lightning, Loading } from '@element-plus/icons-vue'

const router = useRouter()
const phase = ref('config')
const starting = ref(false)

const form = ref({ scope_type: 'all', scope_id: null, count: 6, duration: 5 })
const majors = ref([])
const courses = ref([])
const chapters = ref([])
const chMajor = ref(null)
const chCourse = ref(null)

const MATCH_TIMEOUT = 30
const secondsLeft = ref(MATCH_TIMEOUT)
const matchingMsg = ref('正在为你寻找对手…')
let battleId = null
let pollTimer = null
let cdTimer = null

const matchPercent = computed(() => Math.round((secondsLeft.value / MATCH_TIMEOUT) * 100))

const loadMajors = async () => {
  try {
    const res = await request.get('/api/majors')
    majors.value = res.data || []
  } catch (e) { /* 静默 */ }
}

const onMajorChange = async (val) => {
  chCourse.value = null
  form.value.scope_id = null
  courses.value = []
  chapters.value = []
  if (!val) return
  const res = await request.get('/api/courses', { params: { major_id: val } })
  courses.value = res.data || []
}

const onCourseChange = async (val) => {
  form.value.scope_id = null
  chapters.value = []
  if (!val) return
  const res = await request.get('/api/chapters', { params: { course_id: val } })
  chapters.value = res.data || []
}

const resetScopeId = () => { form.value.scope_id = null }

const startMatch = async () => {
  if ((form.value.scope_type === 'major' || form.value.scope_type === 'chapter') && !form.value.scope_id) {
    return ElMessage.warning('请先选择具体的题目范围')
  }
  starting.value = true
  try {
    const payload = {
      scope_type: form.value.scope_type,
      scope_id: form.value.scope_id,
      count: form.value.count,
      duration: form.value.duration,
    }
    const res = await request.post('/api/pk/quick', payload)
    const d = res.data
    if (d.matched === 'human') {
      ElMessage.success(d.message || '已匹配到对手')
      router.push(`/pk/take/${d.battle_id}`)
      return
    }
    battleId = d.battle_id
    phase.value = 'matching'
    secondsLeft.value = MATCH_TIMEOUT
    startPolling()
  } finally {
    starting.value = false
  }
}

const startPolling = () => {
  pollTimer = setInterval(async () => {
    try {
      const res = await request.get(`/api/pk/${battleId}/state`)
      const st = res.data.battle?.status
      if (st === 'playing') {
        stopTimers()
        router.push(`/pk/take/${battleId}`)
      }
    } catch (e) { /* 忽略单次轮询失败 */ }
  }, 3000)
  cdTimer = setInterval(() => {
    secondsLeft.value = Math.max(0, secondsLeft.value - 1)
    if (secondsLeft.value === 0) {
      matchingMsg.value = '暂未匹配到真人对手'
    }
  }, 1000)
}

const joinBot = async () => {
  stopTimers()
  try {
    const res = await request.post(`/api/pk/quick/${battleId}/bot`)
    ElMessage.success(res.data.message || '训练对手已就绪')
    router.push(`/pk/take/${battleId}`)
  } catch (e) {
    phase.value = 'config'
  }
}

const cancelMatch = () => {
  stopTimers()
  battleId = null
  phase.value = 'config'
}

const stopTimers = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  if (cdTimer) { clearInterval(cdTimer); cdTimer = null }
}

const goBack = () => router.push('/competitions/pk')

onMounted(loadMajors)
onUnmounted(stopTimers)
</script>

<style scoped>
.page-wrapper {
  max-width: 720px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: var(--text-muted);
  padding: 8px 12px;
  border-radius: 10px;
  transition: all 0.25s ease;
}

.header-left:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.header-title {
  flex: 1;
}

.header-title h2 {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  color: #d97706;
}

.header-title p {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

.header-right {
  min-width: 80px;
}

.config-card,
.match-card {
  padding: 28px 32px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
}

.field {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 22px;
}

.field-label {
  min-width: 72px;
  font-size: 14px;
  color: var(--text-secondary);
  font-weight: 600;
}

.scope-select {
  width: 280px;
}

.slider {
  flex: 1;
  max-width: 320px;
}

.field-value {
  min-width: 56px;
  font-size: 13.5px;
  color: #d97706;
  font-weight: 700;
}

.start-btn {
  width: 100%;
  margin-top: 8px;
  font-weight: 600;
}

.match-card {
  text-align: center;
}

.match-card h3 {
  font-size: 19px;
  color: var(--text-primary);
  margin: 12px 0 6px;
}

.match-sub {
  font-size: 13.5px;
  color: var(--text-muted);
  margin: 0 0 20px;
}

.spin {
  animation: rot 1s linear infinite;
  color: #d97706;
}

@keyframes rot {
  to { transform: rotate(360deg); }
}

.countdown-ring {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 22px;
}

.cd-text {
  position: absolute;
  font-size: 26px;
  font-weight: 800;
  color: var(--text-primary);
}

.match-actions {
  display: flex;
  justify-content: center;
  gap: 14px;
}

.match-tip {
  margin-top: 16px;
  font-size: 12.5px;
  color: #e6a23c;
}

.dark .config-card,
.dark .match-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
}
</style>
