<template>
  <div class="page-wrapper">
    <div class="settings-header">
      <h2>系统设置</h2>
      <p>配置系统相关参数</p>
    </div>

    <div class="settings-content">
      <div class="setting-card">
        <h3>主题设置</h3>
        <div class="theme-options">
          <div 
            v-for="theme in themes" 
            :key="theme.value"
            class="theme-item"
            :class="{ active: currentTheme === theme.value }"
            @click="setTheme(theme.value)"
          >
            <div class="theme-preview" :style="{ background: theme.preview }"></div>
            <span>{{ theme.label }}</span>
          </div>
        </div>
      </div>

      <div class="setting-card">
        <h3>AI出题设置</h3>
        <el-form :model="aiSettings" label-width="150px" class="settings-form">
          <el-form-item label="默认生成数量">
            <el-input-number v-model="aiSettings.defaultCount" :min="1" :max="20" />
          </el-form-item>
          <el-form-item label="自动创建专业">
            <el-switch v-model="aiSettings.autoCreateMajor" />
          </el-form-item>
          <el-form-item label="自动创建课程">
            <el-switch v-model="aiSettings.autoCreateCourse" />
          </el-form-item>
        </el-form>
      </div>

      <div class="setting-card">
        <h3>考试设置</h3>
        <el-form :model="examSettings" label-width="150px" class="settings-form">
          <el-form-item label="默认考试时长(分钟)">
            <el-input-number v-model="examSettings.defaultDuration" :min="10" :max="300" />
          </el-form-item>
          <el-form-item label="允许提前交卷">
            <el-switch v-model="examSettings.allowEarlySubmit" />
          </el-form-item>
          <el-form-item label="自动批改">
            <el-switch v-model="examSettings.autoGrade" />
          </el-form-item>
        </el-form>
      </div>

      <div class="action-buttons">
        <el-button type="primary" @click="saveSettings" :loading="saving">保存设置</el-button>
        <el-button @click="resetSettings">恢复默认</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'

const themes = [
  { value: 'light', label: '亮色模式', preview: 'linear-gradient(135deg, #ffffff 0%, #f8fafc 100%)' },
  { value: 'dark', label: '暗色模式', preview: 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)' },
  { value: 'auto', label: '跟随系统', preview: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' }
]

const currentTheme = ref('dark')
const saving = ref(false)

const aiSettings = ref({
  defaultCount: 5,
  autoCreateMajor: true,
  autoCreateCourse: true
})

const examSettings = ref({
  defaultDuration: 60,
  allowEarlySubmit: true,
  autoGrade: true
})

const setTheme = (theme) => {
  currentTheme.value = theme
  localStorage.setItem('theme', theme)
  if (theme === 'dark') {
    document.documentElement.classList.add('dark')
  } else if (theme === 'light') {
    document.documentElement.classList.remove('dark')
  }
  ElMessage.success(`已切换到${themes.find(t => t.value === theme)?.label}`)
}

const saveSettings = async () => {
  saving.value = true
  try {
    const settings = {
      theme: currentTheme.value,
      ai: aiSettings.value,
      exam: examSettings.value
    }
    localStorage.setItem('systemSettings', JSON.stringify(settings))
    ElMessage.success('设置保存成功')
  } catch (e) {
    console.error(e)
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const resetSettings = () => {
  currentTheme.value = 'dark'
  aiSettings.value = {
    defaultCount: 5,
    autoCreateMajor: true,
    autoCreateCourse: true
  }
  examSettings.value = {
    defaultDuration: 60,
    allowEarlySubmit: true,
    autoGrade: true
  }
  ElMessage.info('已恢复默认设置')
}

const loadSettings = () => {
  const saved = localStorage.getItem('systemSettings')
  if (saved) {
    try {
      const settings = JSON.parse(saved)
      currentTheme.value = settings.theme || 'dark'
      aiSettings.value = { ...aiSettings.value, ...settings.ai }
      examSettings.value = { ...examSettings.value, ...settings.exam }
    } catch (e) {
      console.error('Failed to load settings:', e)
    }
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<style scoped>
.page-wrapper {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px;
}

.settings-header {
  margin-bottom: 24px;
}

.settings-header h2 {
  margin: 0 0 8px;
  font-size: 24px;
}

.settings-header p {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.settings-content {
  background: var(--el-bg-color-page);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid var(--el-border-color);
}

.setting-card {
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--el-border-color);
}

.setting-card:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.setting-card h3 {
  margin: 0 0 20px;
  font-size: 16px;
  font-weight: 600;
}

.theme-options {
  display: flex;
  gap: 20px;
}

.theme-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s;
  border: 2px solid transparent;
}

.theme-item:hover {
  background: var(--el-bg-color-page);
}

.theme-item.active {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.1);
}

.theme-preview {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.settings-form {
  max-width: 500px;
}

.action-buttons {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}
</style>