<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>AI智能出题</h2>
        <p>基于AI自动生成高质量试题，支持多种题型和难度</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="generateQuestions" :loading="isGenerating">
          <el-icon><Star /></el-icon>
          生成题目
        </el-button>
      </div>
    </div>

    <div class="form-container">
      <el-card class="form-card" shadow="hover">
        <el-form :model="form" label-width="120px" class="generate-form">
          <div class="form-row">
            <el-form-item label="专业名称" required>
              <el-input
                v-model="form.major_name"
                placeholder="输入专业名称，如：计算机科学与技术"
                class="input-lg"
              />
              <div class="input-tip">输入新专业会自动创建</div>
            </el-form-item>
          </div>

          <div class="form-row">
            <el-form-item label="课程名称">
              <el-input
                v-model="form.course_name"
                placeholder="输入课程名称（可选），如：高等数学"
                class="input-lg"
              />
              <div class="input-tip">输入新课程会自动创建</div>
            </el-form-item>
          </div>

          <div class="form-row">
            <el-form-item label="题目类型" required>
              <el-select v-model="form.type" placeholder="请选择题型" class="input-lg">
                <el-option
                  v-for="t in questionTypes"
                  :key="t.value"
                  :label="t.label"
                  :value="t.value"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="难度等级" required>
              <el-select v-model="form.difficulty" placeholder="请选择难度" class="input-lg">
                <el-option
                  v-for="d in difficulties"
                  :key="d.value"
                  :label="d.label"
                  :value="d.value"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="生成数量" required>
              <el-input-number
                v-model="form.count"
                :min="1"
                :max="20"
                class="input-lg"
              />
            </el-form-item>
          </div>

          <div class="form-row">
            <el-form-item label="出题描述">
              <el-input
                v-model="form.description"
                type="textarea"
                placeholder="输入出题描述，如：围绕数据结构中链表的基本操作，包括创建、插入、删除、遍历等知识点"
                :rows="4"
                class="input-lg"
              />
              <div class="input-tip">详细描述将帮助 AI 生成更准确的题目，包括知识点范围、考察重点等</div>
            </el-form-item>
          </div>

          <div class="form-row">
            <el-form-item label="出题方式">
              <el-radio-group v-model="form.question_mode" class="question-mode-group">
                <el-radio-button label="ai">
                  <el-icon><MagicStick /></el-icon>
                  AI生成题目
                </el-radio-button>
                <el-radio-button label="past">
                  <el-icon><Notebook /></el-icon>
                  历年真题
                </el-radio-button>
              </el-radio-group>
              <div class="input-tip">选择AI生成新题目或根据历年真题风格生成</div>
            </el-form-item>
          </div>

          <div class="form-row">
            <el-form-item>
              <div class="info-card">
                <div class="info-icon">
                  <el-icon :size="24" color="#667eea"><InfoFilled /></el-icon>
                </div>
                <div class="info-content">
                  <h4>AI出题说明</h4>
                  <ul>
                    <li>支持单选题、多选题、填空题、判断题、问答题、编程题、应用题、计算题</li>
                    <li>题目将根据专业名称自动匹配相关知识点</li>
                    <li>生成的题目会自动保存到题库中</li>
                  </ul>
                </div>
              </div>
            </el-form-item>
          </div>
        </el-form>
      </el-card>
    </div>

    <div v-if="history.length > 0" class="history-section">
      <h3 class="section-title">
        <el-icon><Clock /></el-icon>
        生成历史
      </h3>
      <el-table :data="history" border class="history-table">
        <el-table-column prop="time" label="时间" width="180" />
        <el-table-column prop="major" label="专业" />
        <el-table-column prop="type" label="题型" />
        <el-table-column prop="count" label="数量" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <span :class="['status-tag', row.status]">{{ row.status === 'success' ? '成功' : '失败' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Star, InfoFilled, Clock, MagicStick, Notebook } from '@element-plus/icons-vue'
import request from '../utils/request'

const form = ref({
  major_name: '',
  course_name: '',
  type: '',
  difficulty: '',
  count: 5,
  description: '',
  question_mode: 'ai'
})

const questionTypes = ref([])
const difficulties = ref([])
const isGenerating = ref(false)
const history = ref([])

onMounted(async () => {
  try {
    const typesRes = await request.get('/api/question-types')
    questionTypes.value = typesRes.data
    const diffRes = await request.get('/api/difficulties')
    difficulties.value = diffRes.data
  } catch (e) {
    console.error('加载选项失败', e)
  }
})

const generateQuestions = async () => {
  if (!form.value.major_name) {
    ElMessage.warning('请输入专业名称')
    return
  }
  if (!form.value.type) {
    ElMessage.warning('请选择题目类型')
    return
  }
  if (!form.value.difficulty) {
    ElMessage.warning('请选择难度等级')
    return
  }

  isGenerating.value = true
  const startTime = new Date()
  
  try {
    const res = await request.post('/api/ai/generate', {
      major_name: form.value.major_name,
      course_name: form.value.course_name,
      type: form.value.type,
      difficulty: form.value.difficulty,
      count: form.value.count,
      description: form.value.description,
      question_mode: form.value.question_mode
    })
    
    ElMessage.success(res.data.message)
    history.value.unshift({
      time: startTime.toLocaleString(),
      major: form.value.major_name,
      type: questionTypes.value.find(t => t.value === form.value.type)?.label || form.value.type,
      count: form.value.count,
      status: 'success'
    })
  } catch (e) {
    const msg = e.response?.data?.message || '生成失败'
    ElMessage.error(msg)
    history.value.unshift({
      time: startTime.toLocaleString(),
      major: form.value.major_name,
      type: questionTypes.value.find(t => t.value === form.value.type)?.label || form.value.type,
      count: form.value.count,
      status: 'failed'
    })
  } finally {
    isGenerating.value = false
  }
}
</script>

<style scoped>
.page-wrapper {
  max-width: 1000px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.header-title h2 {
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
  margin: 0;
}

.header-title p {
  color: #94a3b8;
  margin: 6px 0 0;
}

.form-container {
  margin-bottom: 32px;
}

.form-card {
  border-radius: 16px;
}

.generate-form {
  padding: 8px 0;
}

.form-row {
  margin-bottom: 20px;
}

.form-row:last-child {
  margin-bottom: 0;
}

.input-lg {
  width: 100%;
}

.input-tip {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 6px;
}

.info-card {
  display: flex;
  gap: 16px;
  padding: 20px;
  background: linear-gradient(135deg, #f0f9ff 0%, #fef3c7 100%);
  border-radius: 12px;
}

.info-icon {
  flex-shrink: 0;
}

.info-content h4 {
  margin: 0 0 10px;
  color: #334155;
  font-size: 15px;
}

.info-content ul {
  margin: 0;
  padding-left: 20px;
  font-size: 14px;
  color: #64748b;
  line-height: 1.8;
}

.history-section {
  background: white;
  border-radius: 16px;
  padding: 24px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 20px;
}

.history-table {
  border-radius: 12px;
}

.status-tag {
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
}

.status-tag.success {
  background: #dcfce7;
  color: #16a34a;
}

.status-tag.failed {
  background: #fee2e2;
  color: #dc2626;
}

/* 暗色模式 */
.dark .page-wrapper {
  background: var(--bg-secondary);
}

.dark .header-title h2 {
  color: var(--text-primary);
}

.dark .header-title p {
  color: var(--text-light);
}

.dark .form-card {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-color: var(--glass-border);
  box-shadow: var(--shadow-card);
}

.dark .el-form-item__label {
  color: var(--text-light);
}

.dark .el-input__wrapper {
  background: var(--bg-input);
  border-color: var(--border-color);
}

.dark .el-input__inner {
  color: var(--text-primary);
}

.dark :deep(.el-select__wrapper) {
  background: var(--bg-input) !important;
  background-image: none !important;
  border-color: var(--border-color) !important;
}

.dark :deep(.el-select__wrapper:hover) {
  border-color: rgba(99, 102, 241, 0.4) !important;
}

.dark :deep(.el-select__wrapper.is-focus) {
  border-color: #6366f1 !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2) !important;
}

.dark :deep(.el-select__inner) {
  color: var(--text-primary) !important;
  background: transparent !important;
}

.dark :deep(.el-select__placeholder) {
  color: var(--text-disabled) !important;
}

.dark :deep(.el-select__suffix-inner) {
  color: var(--text-light) !important;
}

.dark :deep(.el-select-dropdown) {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
}

.dark :deep(.el-select-dropdown__list) {
  background: transparent !important;
}

.dark :deep(.el-select-dropdown__item) {
  color: var(--text-secondary) !important;
  background: transparent !important;
}

.dark :deep(.el-select-dropdown__item:hover) {
  background: rgba(99, 102, 241, 0.15) !important;
}

.dark :deep(.el-select-dropdown__item.selected) {
  background: rgba(99, 102, 241, 0.25) !important;
  color: #a5b4fc !important;
}

.dark :deep(.el-input-number) {
  background: var(--bg-input) !important;
}

.dark :deep(.el-input-number .el-input__wrapper) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
}

.dark :deep(.el-input-number .el-input__inner) {
  color: var(--text-primary) !important;
  background: transparent !important;
}

.dark :deep(.el-input-number__decrease),
.dark :deep(.el-input-number__increase) {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
  color: var(--text-secondary) !important;
}

.dark :deep(.el-input-number__decrease:hover),
.dark :deep(.el-input-number__increase:hover) {
  background: var(--bg-hover) !important;
}

.dark .info-card {
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.dark .info-content h4 {
  color: var(--text-primary);
}

.dark .info-content ul {
  color: var(--text-secondary);
}

.dark .input-tip {
  color: var(--text-disabled);
}

.dark .history-section {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-card);
}

.dark .section-title {
  color: var(--text-primary);
}

.dark .el-table {
  background: transparent;
}

.dark .el-table th {
  background: var(--bg-secondary);
  color: var(--text-light);
  border-bottom-color: var(--glass-border);
}

.dark .el-table td {
  color: var(--text-secondary);
  border-bottom-color: var(--glass-border);
}

.dark .el-table tr:hover>td {
  background: var(--bg-hover);
}

.dark .el-table--border {
  border: 1px solid var(--glass-border);
}

.dark .el-table--border .el-table__cell {
  border-right: 1px solid var(--glass-border);
}

.dark .status-tag.success {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.dark .status-tag.failed {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.25);
}

.dark :deep(.el-select .el-input__wrapper),
.dark :deep(.el-select .el-input__wrapper.is-focus),
.dark :deep(.el-select .el-input__wrapper.is-hover) {
  background: #1e293b !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
  box-shadow: none !important;
}

.dark :deep(.el-select .el-input__inner),
.dark :deep(.el-select__selected-item),
.dark :deep(.el-select__selection-text) {
  color: #f1f5f9 !important;
}

.dark :deep(.el-select .el-input__placeholder),
.dark :deep(.el-select__placeholder) {
  color: #64748b !important;
}

.dark :deep(.el-select .el-input__suffix-inner) {
  color: #94a3b8 !important;
}

.dark :deep(.el-select-dropdown) {
  background: #1e293b !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
}

.dark :deep(.el-select-dropdown__item) {
  color: #f1f5f9 !important;
}

.dark :deep(.el-select-dropdown__item:hover) {
  background: rgba(255, 255, 255, 0.08) !important;
}

.dark :deep(.el-select-dropdown__item.selected) {
  background: rgba(99, 102, 241, 0.25) !important;
  color: #a5b4fc !important;
}

.dark :deep(.el-select .el-input__wrapper) {
  background: rgba(30, 41, 59, 0.95) !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
}

.dark :deep(.el-select .el-input__wrapper:hover) {
  border-color: rgba(99, 102, 241, 0.4) !important;
}

.dark :deep(.el-select .el-input__wrapper.is-focus) {
  border-color: #6366f1 !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2) !important;
}

.dark :deep(.el-input-number .el-input__wrapper) {
  background: rgba(30, 41, 59, 0.95) !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
}

.dark :deep(.el-input-number .el-input__wrapper:hover) {
  border-color: rgba(99, 102, 241, 0.4) !important;
}

.dark :deep(.el-input-number .el-input__wrapper.is-focus) {
  border-color: #6366f1 !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2) !important;
}

.dark :deep(.el-input .el-input__wrapper) {
  background: rgba(30, 41, 59, 0.95) !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
}

.dark :deep(.el-input .el-input__wrapper:hover) {
  border-color: rgba(99, 102, 241, 0.4) !important;
}

.dark :deep(.el-input .el-input__wrapper.is-focus) {
  border-color: #6366f1 !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2) !important;
}

.dark :deep(.el-select .el-input__suffix-inner button) {
  background: transparent !important;
  border: none !important;
  color: #94a3b8 !important;
}

.dark :deep(.el-select .el-input__suffix-inner button:hover) {
  background: rgba(255, 255, 255, 0.08) !important;
  color: #f1f5f9 !important;
}

.dark :deep(.el-select .el-input__wrapper) {
  background: rgba(30, 41, 59, 0.95) !important;
}

.dark :deep(.el-select .el-input__wrapper) * {
  background: transparent !important;
}

.dark :deep(.el-select-dropdown) {
  background: rgba(30, 41, 59, 0.98) !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
}

.dark :deep(.el-select-dropdown__list) {
  background: transparent !important;
}

.dark :deep(.el-select-dropdown__item) {
  background: transparent !important;
}

.dark :deep(.el-select-dropdown__item:hover) {
  background: rgba(99, 102, 241, 0.15) !important;
}

.dark :deep(.el-select-dropdown__item.selected) {
  background: rgba(99, 102, 241, 0.25) !important;
}

.dark :deep(.el-textarea__inner) {
  background: rgba(30, 41, 59, 0.95) !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
  color: #f1f5f9 !important;
}

.dark :deep(.el-textarea__inner:hover) {
  border-color: rgba(99, 102, 241, 0.4) !important;
}

.dark :deep(.el-textarea__inner:focus) {
  border-color: #6366f1 !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2) !important;
}

.dark :deep(.el-radio-button) {
  background: rgba(30, 41, 59, 0.95) !important;
  border-color: rgba(148, 163, 184, 0.3) !important;
  color: #94a3b8 !important;
}

.dark :deep(.el-radio-button:hover) {
  background: rgba(51, 65, 85, 0.95) !important;
  border-color: rgba(99, 102, 241, 0.4) !important;
}

.dark :deep(.el-radio-button.is-active) {
  background: rgba(99, 102, 241, 0.25) !important;
  border-color: #6366f1 !important;
  color: #a5b4fc !important;
}

.dark :deep(.el-radio-button__inner) {
  background: transparent !important;
  border-color: transparent !important;
  color: inherit !important;
}

.dark :deep(.el-radio-button__inner:hover) {
  background: rgba(255, 255, 255, 0.08) !important;
}

.dark :deep(.el-radio-button.is-active .el-radio-button__inner) {
  background: rgba(99, 102, 241, 0.2) !important;
  color: #a5b4fc !important;
}
</style>