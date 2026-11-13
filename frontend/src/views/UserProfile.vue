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

      <div class="form-card">
        <h3>学习报告隐私</h3>
        <p class="hint">开启后，其他用户可在你的主页查看你的学习报告</p>
        <el-form label-width="100px" class="profile-form">
          <el-form-item label="学习报告公开">
            <el-switch v-model="form.is_study_report_public" @change="toggleReportPublic" />
          </el-form-item>
        </el-form>
        <el-button type="primary" plain @click="viewStudyReport">查看 TA 的学习报告</el-button>
      </div>

      <div class="form-card">
        <h3>钱包与积分</h3>
        <p class="hint">竞赛、PK 对战、悬赏领取都需要积分，可在钱包页充值</p>
        <div style="display:flex; gap:10px;">
          <el-button type="warning" :icon="Wallet" @click="$router.push('/bounties/wallet')">打开积分钱包 / 充值</el-button>
        </div>
      </div>

      <div class="form-card">
        <h3>我的关注</h3>
        <el-radio-group v-model="followTab" size="small" @change="loadFollows">
          <el-radio-button label="following">我关注的 ({{ followCounts.following }})</el-radio-button>
          <el-radio-button label="fans">粉丝 ({{ followCounts.fans }})</el-radio-button>
          <el-radio-button label="mutual">互关 ({{ followCounts.mutual }})</el-radio-button>
        </el-radio-group>
        <el-empty v-if="!followList.length && !followLoading" description="暂无数据" style="padding:20px" />
        <div v-else-if="followList.length" class="follow-list">
          <div v-for="u in followList" :key="u.id" class="follow-item">
            <span class="follow-name">{{ u.username }}</span>
            <el-tag size="small" :type="u.role === 'teacher' ? 'success' : 'info'">
              {{ u.role === 'teacher' ? '教师' : '学生' }}
            </el-tag>
          </div>
        </div>
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
import { useRouter } from 'vue-router'
import request from '../utils/request'
import { ElMessage } from 'element-plus'
import { User, Wallet } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const userInfo = ref({ username: '', role: '', email: '', id: null, is_study_report_public: false })
const form = ref({ username: '', role: '', email: '', is_study_report_public: false })
const passwordForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const saving = ref(false)

// v7.7 关注关系
const followTab = ref('following')
const followList = ref([])
const followLoading = ref(false)
const followCounts = ref({ following: 0, fans: 0, mutual: 0 })

const loadFollows = async () => {
  if (!userInfo.value.id) return
  followLoading.value = true
  try {
    const { data } = await request.get(`/api/learning/users/${userInfo.value.id}/follows`, {
      params: { type: followTab.value }
    })
    followList.value = data.items || []
  } catch (e) { followList.value = [] }
  followLoading.value = false
}

const loadFollowCounts = async () => {
  if (!userInfo.value.id) return
  try {
    for (const t of ['following', 'fans', 'mutual']) {
      const { data } = await request.get(`/api/learning/users/${userInfo.value.id}/follows`, { params: { type: t } })
      followCounts.value[t] = (data.items || []).length
    }
  } catch (e) {}
}

const fetchUserInfo = async () => {
  const res = await request.get('/api/user/me')
  userInfo.value = res.data
  form.value = { ...res.data }
}

// 学习报告公开开关：变更即持久化（PUT /api/user/me）
const toggleReportPublic = async (val) => {
  try {
    await request.put('/api/user/me', { is_study_report_public: val })
    userInfo.value.is_study_report_public = val
    ElMessage.success(val ? '已公开学习报告' : '已设为仅自己可见')
  } catch (e) {
    // 失败回滚开关状态
    form.value.is_study_report_public = !val
  }
}

const viewStudyReport = () => {
  if (userInfo.value.id) router.push(`/learning/report/${userInfo.value.id}`)
}

const saveProfile = async () => {
  saving.value = true
  try {
    // 先保存基本信息（邮箱）
    const basicChanged = form.value.email !== (userInfo.value.email || '')
    if (basicChanged) {
      await request.put('/api/user/me', { email: form.value.email })
    }

    // 再处理密码修改
    if (passwordForm.value.newPassword) {
      if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
        ElMessage.error('两次输入的密码不一致')
        return
      }
      if (!passwordForm.value.oldPassword) {
        ElMessage.error('请填写旧密码')
        return
      }
      await request.post('/api/auth/change-password', {
        old_password: passwordForm.value.oldPassword,
        new_password: passwordForm.value.newPassword,
      })
      // 改密成功后清掉 token 并跳转到登录页，强制重新登录（后端已吊销旧 token）
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      ElMessage.success('密码已修改，请重新登录')
      passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
      setTimeout(() => window.location.href = '/home', 1200)
      return
    }

    ElMessage.success('保存成功')
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
  } catch (e) {
    console.error(e)
    // 错误拦截器已弹 message
  } finally {
    saving.value = false
  }
}

const resetForm = () => {
  form.value = { ...userInfo.value }
  passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
}

onMounted(async () => {
  await fetchUserInfo()
  await Promise.all([loadFollows(), loadFollowCounts()])
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

.hint { color: #909399; font-size: 13px; margin: 0 0 14px; }

.follow-list {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.follow-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: var(--bg-tertiary, #f5f7fa);
  border-radius: 8px;
}

.follow-name { font-weight: 500; }
</style>