<template>
  <div class="page-wrapper">
    <div class="profile-header">
      <div class="avatar-section">
        <div class="avatar">
          <el-icon :size="48" color="white"><User /></el-icon>
        </div>
        <h2>{{ userInfo.username }}</h2>
        <p class="role">{{ userInfo.role === 'teacher' ? '教师' : '学生' }}</p>
      </div>
    </div>

    <div class="profile-content">
      <div class="form-card">
        <h3>基本信息</h3>
        <el-form :model="form" label-width="100px" class="profile-form">
          <el-form-item label="用户名">
            <el-input v-model="form.username" disabled />
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input v-model="form.email" />
          </el-form-item>
          <el-form-item label="角色">
            <el-input :value="form.role === 'teacher' ? '教师' : '学生'" disabled />
          </el-form-item>
        </el-form>
      </div>

      <div class="form-card">
        <h3>修改密码</h3>
        <el-form :model="passwordForm" label-width="100px" class="profile-form">
          <el-form-item label="旧密码">
            <el-input v-model="passwordForm.oldPassword" type="password" placeholder="请输入旧密码" />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="passwordForm.newPassword" type="password" placeholder="请输入新密码" />
          </el-form-item>
          <el-form-item label="确认密码">
            <el-input v-model="passwordForm.confirmPassword" type="password" placeholder="请确认新密码" />
          </el-form-item>
        </el-form>
      </div>

      <div class="action-buttons">
        <el-button type="primary" @click="saveProfile" :loading="saving">保存修改</el-button>
        <el-button @click="resetForm">重置</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import request from '../utils/request'
import { ElMessage } from 'element-plus'
import { User } from '@element-plus/icons-vue'

const userInfo = ref({ username: '', role: '', email: '' })
const form = ref({ username: '', role: '', email: '' })
const passwordForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const saving = ref(false)

const fetchUserInfo = async () => {
  const res = await request.get('/api/user/me')
  userInfo.value = res.data
  form.value = { ...res.data }
}

const saveProfile = async () => {
  saving.value = true
  try {
    if (passwordForm.value.newPassword) {
      if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
        ElMessage.error('两次输入的密码不一致')
        return
      }
    }
    
    ElMessage.success('保存成功')
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } catch (e) {
    console.error(e)
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const resetForm = () => {
  form.value = { ...userInfo.value }
  passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
}

onMounted(() => {
  fetchUserInfo()
})
</script>

<style scoped>
.page-wrapper {
  max-width: 600px;
  margin: 0 auto;
  padding: 24px;
}

.profile-header {
  text-align: center;
  padding: 40px 0;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 16px;
  margin-bottom: 24px;
}

.avatar-section {
  color: white;
}

.avatar {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
}

.avatar-section h2 {
  margin: 0 0 8px;
  font-size: 24px;
}

.role {
  margin: 0;
  opacity: 0.8;
}

.profile-content {
  background: var(--el-bg-color-page);
  border-radius: 16px;
  padding: 24px;
  border: 1px solid var(--el-border-color);
}

.form-card {
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--el-border-color);
}

.form-card:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.form-card h3 {
  margin: 0 0 20px;
  font-size: 16px;
  font-weight: 600;
}

.profile-form {
  max-width: 400px;
}

.action-buttons {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 24px;
}
</style>