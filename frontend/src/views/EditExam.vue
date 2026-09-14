<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>编辑考试</h2>
        <p>修改考试的基本信息</p>
      </div>
      <div class="header-actions">
        <el-button @click="goBack">
          <el-icon><ArrowLeft /></el-icon>返回
        </el-button>
      </div>
    </div>

    <el-form :model="editForm" label-width="100px" class="edit-form">
      <el-form-item label="考试名称" required>
        <el-input v-model="editForm.title" placeholder="请输入考试名称" />
      </el-form-item>
      <el-form-item label="考试描述">
        <el-input v-model="editForm.description" type="textarea" placeholder="请输入考试描述" />
      </el-form-item>
      <el-form-item label="开始时间" required>
        <el-date-picker
          v-model="editForm.start_time"
          type="datetime"
          placeholder="选择开始时间"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="结束时间" required>
        <el-date-picker
          v-model="editForm.end_time"
          type="datetime"
          placeholder="选择结束时间"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="考试时长" required>
        <el-input-number v-model="editForm.duration" :min="5" :max="480" />
        <span style="margin-left: 8px">分钟</span>
      </el-form-item>

      <el-divider>邀请设置</el-divider>
      <el-form-item>
        <el-checkbox
          v-model="inviteFlags.generate_code"
          @change="onInviteChange('code')"
        >
          生成邀请码 <el-tag v-if="invitationData.code" size="small" type="success">已生成</el-tag>
        </el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-checkbox
          v-model="inviteFlags.generate_url"
          @change="onInviteChange('url')"
        >
          生成邀请链接 <el-tag v-if="invitationData.url" size="small" type="success">已生成</el-tag>
        </el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-checkbox
          v-model="inviteFlags.generate_qr"
          @change="onInviteChange('qr')"
        >
          生成QR码 <el-tag v-if="invitationData.url" size="small" type="info">需有邀请链接</el-tag>
        </el-checkbox>
      </el-form-item>

      <el-card v-if="invitationData.code" class="invite-card" shadow="never">
        <template #header>
          <div class="card-header">
            <el-icon><Key /></el-icon>
            <span>邀请码</span>
          </div>
        </template>
        <div class="invite-content">
          <span class="code-text">{{ invitationData.code }}</span>
          <el-button size="small" type="primary" @click="copyToClipboard(invitationData.code)">
            <el-icon><DocumentCopy /></el-icon>复制
          </el-button>
        </div>
        <p class="invite-hint">学生可在考试页面输入此邀请码加入考试</p>
      </el-card>

      <el-card v-if="invitationData.url" class="invite-card" shadow="never">
        <template #header>
          <div class="card-header">
            <el-icon><Link /></el-icon>
            <span>邀请链接</span>
          </div>
        </template>
        <div class="invite-content">
          <el-input :value="invitationData.url" readonly class="url-input" />
          <el-button size="small" type="primary" @click="copyToClipboard(invitationData.url)">
            <el-icon><DocumentCopy /></el-icon>复制
          </el-button>
        </div>
        <p class="invite-hint">学生点击此链接可直接加入考试</p>
      </el-card>

      <el-card v-if="invitationData.qr" class="invite-card" shadow="never">
        <template #header>
          <div class="card-header">
            <el-icon><Grid /></el-icon>
            <span>QR码</span>
          </div>
        </template>
        <div class="invite-content qr-content">
          <img :src="'data:image/png;base64,' + invitationData.qr" alt="QR码" class="qr-image" />
        </div>
        <p class="invite-hint">学生扫描此二维码可直接加入考试</p>
      </el-card>

      <el-form-item>
        <el-button type="primary" @click="saveExam">保存修改</el-button>
        <el-button @click="goBack">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Key, Link, Grid, DocumentCopy } from '@element-plus/icons-vue'
import request from '../utils/request'

const route = useRoute()
const router = useRouter()

const editForm = ref({
  title: '',
  description: '',
  start_time: null,
  end_time: null,
  duration: 60
})

const inviteFlags = reactive({
  generate_code: false,
  generate_url: false,
  generate_qr: false
})

const invitationData = reactive({
  code: '',
  url: '',
  qr: ''
})

onMounted(async () => {
  await loadExam()
})

const loadExam = async () => {
  const examId = route.params.id
  try {
    const res = await request.get(`/api/exams/${examId}`)
    const exam = res.data
    editForm.value = {
      title: exam.title,
      description: exam.description || '',
      start_time: exam.start_time ? new Date(exam.start_time) : '',
      end_time: exam.end_time ? new Date(exam.end_time) : '',
      duration: exam.duration
    }
    if (exam.invitation_code) {
      invitationData.code = exam.invitation_code
    }
    if (exam.invitation_url) {
      invitationData.url = exam.invitation_url
    }
  } catch (e) {
    ElMessage.error('加载考试信息失败')
    console.error(e)
  }
}

const onInviteChange = async (type) => {
  try {
    const res = await request.post(`/api/exams/${route.params.id}/generate_invitation`, {
      generate_code: inviteFlags.generate_code,
      generate_url: inviteFlags.generate_url,
      generate_qr: inviteFlags.generate_qr
    })
    const data = res.data
    if (data.success) {
      if (data.invitation_code) {
        invitationData.code = data.invitation_code
      }
      if (data.invitation_url) {
        invitationData.url = data.invitation_url
      }
      if (data.qr_code_data) {
        invitationData.qr = data.qr_code_data
      }
      if (inviteFlags.generate_code || inviteFlags.generate_url || inviteFlags.generate_qr) {
        ElMessage.success('生成成功')
      }
    }
  } catch (e) {
    if (e.message !== undefined) {}
    if (type === 'code' && !inviteFlags.generate_code) {
      invitationData.code = ''
    }
    if (type === 'url' && !inviteFlags.generate_url) {
      invitationData.url = ''
    }
    if (type === 'qr' && !inviteFlags.generate_qr) {
      invitationData.qr = ''
    }
  }

  if (type === 'code' && !inviteFlags.generate_code) {
    invitationData.code = ''
  }
  if (type === 'url' && !inviteFlags.generate_url) {
    invitationData.url = ''
  }
  if (type === 'qr' && !inviteFlags.generate_qr) {
    invitationData.qr = ''
  }
}

const copyToClipboard = (text) => {
  if (!text) return
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

const saveExam = async () => {
  if (!editForm.value.title) {
    ElMessage.warning('请输入考试名称')
    return
  }
  if (!editForm.value.start_time || !editForm.value.end_time) {
    ElMessage.warning('请选择时间')
    return
  }

  try {
    await request.put(`/api/exams/${route.params.id}`, {
      title: editForm.value.title,
      description: editForm.value.description,
      start_time: editForm.value.start_time.toISOString(),
      end_time: editForm.value.end_time.toISOString(),
      duration: editForm.value.duration
    })
    ElMessage.success('修改成功')
    router.push('/exams')
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '修改失败')
  }
}

const goBack = () => {
  router.push('/exams')
}
</script>

<style scoped>
.page-wrapper {
  max-width: 800px;
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

.edit-form {
  background: white;
  padding: 24px;
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}

.edit-form .el-form-item {
  margin-bottom: 20px;
}

.invite-card {
  margin-bottom: 16px;
  border-radius: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.invite-content {
  display: flex;
  align-items: center;
  gap: 12px;
}

.code-text {
  font-family: monospace;
  font-size: 18px;
  letter-spacing: 2px;
  color: #409eff;
  font-weight: 600;
}

.url-input {
  flex: 1;
}

.qr-content {
  justify-content: center;
}

.qr-image {
  width: 180px;
  height: 180px;
}

.invite-hint {
  color: #94a3b8;
  font-size: 12px;
  margin: 12px 0 0;
}

.dark .page-wrapper {
  background: transparent;
}

.dark .header-title h2 {
  color: var(--text-primary);
}

.dark .header-title p {
  color: var(--text-light);
}

.dark .edit-form {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: var(--shadow-card);
  border: 1px solid var(--glass-border);
}

.dark .edit-form :deep(.el-form-item__label) {
  color: var(--text-light);
}

.dark .edit-form :deep(.el-input__wrapper) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
}

.dark .edit-form :deep(.el-input__inner) {
  color: var(--text-primary) !important;
}

.dark .edit-form :deep(.el-input__placeholder) {
  color: var(--text-disabled) !important;
}

.dark .edit-form :deep(.el-textarea__inner) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
  color: var(--text-primary) !important;
}

.dark .edit-form :deep(.el-textarea__placeholder) {
  color: var(--text-disabled) !important;
}

.dark .edit-form :deep(.el-date-editor) {
  background: var(--bg-input) !important;
}

.dark .edit-form :deep(.el-date-editor .el-input__wrapper) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
}

.dark .edit-form :deep(.el-input-number) {
  background: var(--bg-input) !important;
}

.dark .edit-form :deep(.el-input-number__decrease),
.dark .edit-form :deep(.el-input-number__increase) {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
}

.dark .edit-form :deep(.el-input-number__decrease:hover),
.dark .edit-form :deep(.el-input-number__increase:hover) {
  background: var(--bg-hover) !important;
}

.dark .edit-form :deep(.el-input-number__decrease i),
.dark .edit-form :deep(.el-input-number__increase i) {
  color: var(--text-light) !important;
}

.dark .edit-form :deep(.el-input-number__inner) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
  color: var(--text-primary) !important;
}

.dark .edit-form :deep(.el-button) {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
  color: var(--text-secondary) !important;
}

.dark .edit-form :deep(.el-button--primary) {
  background: var(--gradient-primary) !important;
  border-color: transparent !important;
}

.dark .header-actions .el-button {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
  color: var(--text-secondary) !important;
}

.dark .header-actions .el-button:hover {
  background: var(--bg-hover) !important;
}

.dark .invite-card :deep(.el-card) {
  background: var(--bg-card);
  border: 1px solid var(--glass-border);
}

.dark .invite-card :deep(.el-card__body) {
  background: transparent;
}

.dark .code-text {
  color: var(--accent-primary);
}

.dark .invite-hint {
  color: var(--text-disabled);
}
</style>