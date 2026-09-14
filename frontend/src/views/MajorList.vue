<template>
  <div class="page-wrapper">
    <!-- 统计栏 -->
    <div class="stats-row">
      <div class="stat-card" style="--stat-color: #667eea; --stat-glow: rgba(102, 126, 234, 0.08)">
        <div class="stat-icon" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
          <el-icon :size="24" color="white"><Collection /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ majors.length }}</div>
          <div class="stat-label">专业总数</div>
        </div>
      </div>
      <div class="stat-card" style="--stat-color: #11998e; --stat-glow: rgba(17, 153, 142, 0.08)">
        <div class="stat-icon" style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%)">
          <el-icon :size="24" color="white"><Document /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ totalQuestions }}</div>
          <div class="stat-label">题目总数</div>
        </div>
      </div>
    </div>

    <!-- 操作栏 -->
    <div class="action-bar">
      <div class="search-box">
        <el-icon :size="16" class="search-icon"><Search /></el-icon>
        <el-input v-model="searchKeyword" placeholder="搜索专业名称..." clearable class="search-input" />
      </div>
      <el-button type="primary" class="add-btn" @click="dialogVisible = true">
        <el-icon><Plus /></el-icon>
        <span>添加专业</span>
      </el-button>
    </div>

    <!-- 专业卡片网格 -->
    <div v-if="filteredMajors.length" class="major-grid">
      <div
        v-for="major in filteredMajors"
        :key="major.id"
        class="major-card"
        :style="{ '--card-color': getMajorColor(major.name) }"
        @click="viewMajorDetail(major.id)"
      >
        <div class="card-bg-pattern"></div>
        <div class="card-content">
          <div class="card-top">
            <div class="major-icon">
              <el-icon :size="28" color="white"><Collection /></el-icon>
            </div>
            <el-dropdown @command="cmd => handleAction(cmd, major)">
              <el-icon class="more-icon"><More /></el-icon>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit"><el-icon><Edit /></el-icon>编辑</el-dropdown-item>
                  <el-dropdown-item command="delete" divided><el-icon><Delete /></el-icon>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <h3 class="major-name">{{ major.name }}</h3>
          <p class="major-desc">{{ major.description || '暂无描述' }}</p>

          <div class="major-meta">
            <div class="meta-item">
              <el-icon :size="14"><Document /></el-icon>
              <span>{{ getQuestionCount(major.id) }} 道题目</span>
            </div>
            <div class="meta-item">
              <el-icon :size="14"><Calendar /></el-icon>
              <span>{{ formatDate(major.created_at) }}</span>
            </div>
          </div>

          <div class="card-progress">
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: getProgress(major.id) + '%' }"></div>
            </div>
            <span class="progress-text">题库覆盖率 {{ getProgress(major.id) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-state">
      <el-icon :size="64" class="empty-icon"><Collection /></el-icon>
      <h3>暂无专业</h3>
      <p>点击右上角添加按钮创建第一个专业</p>
    </div>

    <!-- 添加/编辑弹窗 -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑专业' : '添加专业'" width="500px" class="major-dialog">
      <el-form :model="form" label-width="80px">
        <el-form-item label="专业名称">
          <el-input v-model="form.name" placeholder="请输入专业名称" />
        </el-form-item>
        <el-form-item label="专业描述">
          <el-input v-model="form.description" type="textarea" rows="3" placeholder="请输入专业描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveMajor" :loading="saving">
          {{ isEdit ? '保存修改' : '确认添加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import request from '../utils/request'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Collection, Document, Calendar, More, Edit, Delete } from '@element-plus/icons-vue'

const router = useRouter()
const majors = ref([])
const questions = ref([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const saving = ref(false)
const searchKeyword = ref('')

const form = ref({ id: null, name: '', description: '' })

const filteredMajors = computed(() => {
  if (!searchKeyword.value) return majors.value
  return majors.value.filter(m => m.name.includes(searchKeyword.value))
})

const totalQuestions = computed(() => questions.value.length)

const majorColors = [
  '#667eea', '#11998e', '#f093fb', '#4facfe',
  '#fa709a', '#fee140', '#30cfd0', '#a8edea'
]

const getMajorColor = (name) => {
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return majorColors[Math.abs(hash) % majorColors.length]
}

const getQuestionCount = (majorId) => {
  return questions.value.filter(q => q.major_id === majorId).length
}

const getProgress = (majorId) => {
  if (!questions.value.length) return 0
  const count = getQuestionCount(majorId)
  return Math.min(Math.round((count / Math.max(questions.value.length, 1)) * 100), 100)
}

const formatDate = (date) => {
  if (!date) return '未知'
  return new Date(date).toLocaleDateString('zh-CN')
}

const fetchMajors = async () => {
  const res = await request.get('/api/majors')
  majors.value = res.data
}

const fetchQuestions = async () => {
  const res = await request.get('/api/questions')
  questions.value = res.data
}

const viewMajorDetail = (majorId) => {
  router.push(`/majors/${majorId}`)
}

const handleAction = (cmd, major) => {
  if (cmd === 'edit') {
    isEdit.value = true
    form.value = { ...major }
    dialogVisible.value = true
  } else if (cmd === 'delete') {
    deleteMajor(major.id)
  }
}

const saveMajor = async () => {
  if (!form.value.name.trim()) {
    ElMessage.warning('请输入专业名称')
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await request.put(`/api/majors/${form.value.id}`, form.value)
      ElMessage.success('更新成功')
    } else {
      await request.post('/api/majors', form.value)
      ElMessage.success('添加成功')
    }
    dialogVisible.value = false
    fetchMajors()
  } catch (e) {
    console.error(e)
  } finally {
    saving.value = false
  }
}

const deleteMajor = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该专业吗？相关题目将变为无专业归属', '提示', { type: 'warning' })
    await request.delete(`/api/majors/${id}`)
    ElMessage.success('删除成功')
    fetchMajors()
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}

onMounted(() => {
  fetchMajors()
  fetchQuestions()
})
</script>

<style scoped>
.page-wrapper {
  max-width: 1400px;
  margin: 0 auto;
}

/* 统计卡片 */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 28px;
}
.stat-card {
  background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
  border-radius: 20px;
  padding: 28px;
  display: flex;
  align-items: center;
  gap: 20px;
  box-shadow: 
    0 4px 6px -1px rgba(0, 0, 0, 0.05),
    0 2px 4px -2px rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.8);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}
.stat-card::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -30%;
  width: 100px;
  height: 100px;
  background: var(--stat-glow, rgba(102, 126, 234, 0.05));
  border-radius: 50%;
  filter: blur(20px);
}
.stat-card:hover {
  transform: translateY(-4px);
  box-shadow: 
    0 10px 25px -5px rgba(0, 0, 0, 0.08),
    0 4px 10px -4px rgba(0, 0, 0, 0.05);
}
.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}
.stat-icon::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.4) 0%, transparent 50%);
}
.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1;
  position: relative;
}
.stat-value::after {
  content: '';
  position: absolute;
  bottom: -4px;
  left: 0;
  width: 30px;
  height: 3px;
  background: var(--stat-color, #667eea);
  border-radius: 2px;
}
.stat-label {
  font-size: 14px;
  color: #64748b;
  margin-top: 10px;
  font-weight: 500;
}

/* 操作栏 */
.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
  gap: 20px;
}
.search-box {
  position: relative;
  flex: 1;
  max-width: 360px;
}
.search-icon {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
  z-index: 2;
  transition: all 0.3s;
}
.search-box:focus-within .search-icon {
  color: #667eea;
  transform: translateY(-50%) scale(1.1);
}
.search-input :deep(.el-input__wrapper) {
  padding-left: 44px;
  border-radius: 16px;
  background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid rgba(148, 163, 184, 0.2);
  box-shadow: 
    0 1px 2px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.search-input :deep(.el-input__wrapper):hover {
  border-color: rgba(102, 126, 234, 0.3);
  box-shadow: 
    0 2px 8px rgba(0, 0, 0, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
}
.search-input :deep(.el-input__wrapper):focus-within {
  border-color: #667eea;
  box-shadow: 
    0 0 0 3px rgba(102, 126, 234, 0.1),
    0 4px 12px rgba(102, 126, 234, 0.15);
}
.search-input :deep(.el-input__inner) {
  font-size: 14px;
  color: #334155;
}
.add-btn {
  border-radius: 16px;
  padding: 0 28px;
  height: 44px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  font-weight: 600;
  font-size: 14px;
  box-shadow: 
    0 4px 15px rgba(102, 126, 234, 0.35),
    0 2px 4px rgba(118, 75, 162, 0.2);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}
.add-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.2) 0%, transparent 50%);
}
.add-btn:hover {
  transform: translateY(-2px);
  box-shadow: 
    0 8px 25px rgba(102, 126, 234, 0.45),
    0 4px 10px rgba(118, 75, 162, 0.3);
}
.add-btn:active {
  transform: translateY(0);
  box-shadow: 
    0 2px 8px rgba(102, 126, 234, 0.3);
}

/* 专业卡片 */
.major-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 24px;
}
.major-card {
  background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 
    0 4px 6px -1px rgba(0, 0, 0, 0.05),
    0 2px 4px -2px rgba(0, 0, 0, 0.05);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.8);
}
.major-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(145deg, rgba(255,255,255,0.9) 0%, rgba(248,250,252,0.95) 100%);
  z-index: 0;
}
.major-card:hover {
  transform: translateY(-6px) scale(1.02);
  box-shadow: 
    0 20px 40px -10px rgba(0, 0, 0, 0.12),
    0 8px 20px -8px rgba(0, 0, 0, 0.08);
}
.card-bg-pattern {
  position: absolute;
  top: -40px;
  left: -40px;
  right: -40px;
  height: 180px;
  background: linear-gradient(135deg, var(--card-color) 0%, transparent 60%);
  opacity: 0.08;
  border-radius: 50%;
  filter: blur(20px);
  transition: all 0.4s;
}
.major-card:hover .card-bg-pattern {
  opacity: 0.12;
  transform: scale(1.1);
}
.card-content {
  padding: 28px;
  position: relative;
  z-index: 1;
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.major-icon {
  width: 60px;
  height: 60px;
  border-radius: 20px;
  background: linear-gradient(135deg, var(--card-color) 0%, color-mix(in srgb, var(--card-color) 70%, white) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 
    0 8px 25px rgba(var(--card-color), 0.25),
    0 4px 8px rgba(0, 0, 0, 0.08);
  transition: all 0.3s;
  position: relative;
  overflow: hidden;
}
.major-icon::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.4) 0%, transparent 50%);
}
.major-card:hover .major-icon {
  transform: scale(1.1);
  box-shadow: 
    0 12px 35px rgba(var(--card-color), 0.35),
    0 6px 12px rgba(0, 0, 0, 0.1);
}
.more-icon {
  color: #94a3b8;
  cursor: pointer;
  padding: 8px;
  border-radius: 12px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  background: rgba(148, 163, 184, 0.1);
}
.more-icon:hover {
  background: rgba(148, 163, 184, 0.2);
  color: #64748b;
  transform: rotate(90deg);
}
.major-name {
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 10px;
  position: relative;
  display: inline-block;
}
.major-name::after {
  content: '';
  position: absolute;
  bottom: -4px;
  left: 0;
  width: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--card-color) 0%, transparent 100%);
  border-radius: 2px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.major-card:hover .major-name::after {
  width: 60%;
}
.major-desc {
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
  margin-bottom: 22px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 44px;
  padding: 12px 14px;
  background: rgba(148, 163, 184, 0.06);
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.1);
}
.major-meta {
  display: flex;
  gap: 20px;
  margin-bottom: 22px;
  padding: 14px 16px;
  background: linear-gradient(135deg, rgba(241, 245, 249, 0.8) 0%, rgba(226, 232, 240, 0.6) 100%);
  border-radius: 14px;
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}
.meta-item el-icon {
  color: var(--card-color);
}
.card-progress {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  background: rgba(248, 250, 252, 0.8);
  border-radius: 14px;
  border: 1px solid rgba(226, 232, 240, 0.6);
}
.progress-bar {
  flex: 1;
  height: 8px;
  background: rgba(148, 163, 184, 0.15);
  border-radius: 4px;
  overflow: visible;
  position: relative;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--card-color) 0%, color-mix(in srgb, var(--card-color) 80%, white) 100%);
  border-radius: 4px;
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  box-shadow: 0 2px 8px rgba(var(--card-color), 0.3);
}
.progress-fill::after {
  content: '';
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 12px;
  height: 12px;
  background: white;
  border-radius: 50%;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
  opacity: 0;
  transition: opacity 0.3s;
}
.major-card:hover .progress-fill::after {
  opacity: 1;
}
.progress-text {
  font-size: 13px;
  color: var(--card-color);
  white-space: nowrap;
  font-weight: 600;
  padding: 4px 10px;
  background: rgba(var(--card-color), 0.08);
  border-radius: 8px;
}

/* 空状态 */
.empty-state {
  text-align: center;
  padding: 80px 20px;
  color: #94a3b8;
}

/* 暗色模式样式 */
.dark .page-wrapper {
  background: var(--bg-secondary);
}
.dark .page-title {
  color: var(--text-primary);
}
.dark .page-subtitle {
  color: var(--text-light);
}
.dark .stats-row {
  background: transparent;
}
.dark .stat-card {
  background: var(--gradient-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: var(--shadow-card);
  border: 1px solid var(--glass-border);
}
.dark .stat-value {
  color: var(--text-primary);
}
.dark .stat-label {
  color: var(--text-light);
}
.dark .stat-icon {
  background: rgba(99, 102, 241, 0.2);
  color: var(--primary-500);
}
.dark .stat-card::before {
  opacity: 0.35;
}
.dark .search-box {
  background: transparent;
}
.dark .search-icon {
  color: var(--text-light);
}
.dark .search-box:focus-within .search-icon {
  color: var(--primary-500);
}
.dark .search-input :deep(.el-input__wrapper) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
  box-shadow: 0 1px 2px rgba(0,0,0,0.3) !important;
}
.dark .search-input :deep(.el-input__inner) {
  color: var(--text-primary) !important;
}
.dark .search-input :deep(.el-input__placeholder) {
  color: var(--text-disabled) !important;
}
.dark .search-input :deep(.el-input__wrapper):focus-within {
  border-color: var(--primary-500) !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2), 0 4px 12px rgba(99, 102, 241, 0.15) !important;
}
.dark .major-card {
  background: var(--bg-card) !important;
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: var(--shadow-card);
  border: 1px solid var(--glass-border);
}
.dark .major-card::before {
  background: var(--bg-card);
}
.dark .card-bg-pattern {
  opacity: 0.3;
}
.dark .card-bg-pattern::after {
  background: var(--bg-tertiary);
}
.dark .major-name {
  color: var(--text-primary);
}
.dark .major-desc {
  color: var(--text-secondary);
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.2);
}
.dark .major-meta {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--glass-border);
}
.dark .meta-item {
  color: var(--text-secondary);
}
.dark .card-progress {
  background: rgba(255, 255, 255, 0.04);
  border-color: var(--glass-border);
}
.dark .progress-bar {
  background: rgba(255, 255, 255, 0.08);
}
.dark .progress-fill::after {
  background: var(--bg-secondary);
}
.dark .progress-text {
  background: rgba(99, 102, 241, 0.15);
}
.dark .more-icon {
  color: var(--text-light);
  background: rgba(100, 116, 139, 0.15);
}
.dark .more-icon:hover {
  background: rgba(100, 116, 139, 0.25);
  color: var(--text-secondary);
}
.dark .empty-state {
  color: var(--text-light);
}
.dark .empty-state h3 {
  color: var(--text-primary);
}
.dark .progress-text {
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.15);
}
.dark .meta-icon {
  color: #64748b;
}
.dark .more-icon {
  color: #64748b;
  background: rgba(100, 116, 139, 0.1);
}
.dark .more-icon:hover {
  background: rgba(255,255,255,0.1);
  color: #94a3b8;
}
.dark .progress-bar {
  background: rgba(255,255,255,0.1);
}
.dark .progress-fill {
  background: linear-gradient(90deg, #667eea, #764ba2);
}
.dark .progress-text {
  color: #94a3b8;
}
.dark .empty-state {
  background: transparent;
}
.dark .empty-state h3 {
  color: #f1f5f9;
}
.dark .empty-state p {
  color: #94a3b8;
}
.dark .empty-icon {
  color: #334155;
}
.dark .major-dialog :deep(.el-dialog) {
  background: #1e293b !important;
}
.dark .major-dialog :deep(.el-dialog__header) {
  border-bottom-color: rgba(255,255,255,0.1);
}
.dark .major-dialog :deep(.el-dialog__title) {
  color: #f1f5f9;
}
.dark .major-dialog :deep(.el-form-item__label) {
  color: #94a3b8;
}
.dark .major-dialog :deep(.el-input__wrapper) {
  background: #334155;
  border-color: rgba(255,255,255,0.1);
}
.dark .major-dialog :deep(.el-input__inner) {
  color: #f1f5f9;
}
.dark .major-dialog :deep(.el-textarea__inner) {
  background: #334155;
  border-color: rgba(255,255,255,0.1);
  color: #f1f5f9;
}
.dark .el-dropdown-menu {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
}
.dark .el-dropdown-menu__item {
  color: var(--text-secondary) !important;
}
.dark .el-dropdown-menu__item:hover {
  background: var(--bg-hover) !important;
}
.empty-state h3 {
  font-size: 20px;
  color: #475569;
  margin: 16px 0 8px;
}
.empty-state p {
  font-size: 14px;
}
.empty-icon {
  color: #cbd5e1;
}

/* 弹窗 */
.major-dialog :deep(.el-dialog__header) {
  padding: 20px 24px;
  border-bottom: 1px solid #f1f5f9;
}
.major-dialog :deep(.el-dialog__body) {
  padding: 24px;
}
.major-dialog :deep(.el-input__wrapper),
.major-dialog :deep(.el-textarea__inner) {
  border-radius: 10px;
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .major-grid {
    grid-template-columns: 1fr;
  }
}
</style>