<template>
  <div class="page-wrapper" v-loading="loading">
    <template v-if="comp">
      <div class="page-header">
        <div class="header-title">
          <h2>
            <el-icon :size="24" class="trophy"><Trophy /></el-icon>
            {{ comp.title }}
            <el-tag :type="statusTag(comp.status)" effect="dark" size="small">{{ statusLabel(comp.status) }}</el-tag>
            <el-tag size="small" type="warning" effect="plain">作品赛</el-tag>
            <el-tag v-if="comp.prize_points" size="small" type="danger" effect="plain">冠军 {{ comp.prize_points }} 积分</el-tag>
          </h2>
          <p><span class="sub-info">提交截止：{{ fmtTime(comp.end_time) }} · {{ comp.participant_count }} 人已参与<template v-if="comp.description"> · {{ comp.description }}</template></span></p>
        </div>
        <div class="header-actions">
          <el-button :icon="Back" @click="$router.push('/competitions')">返回广场</el-button>
          <el-button v-if="!isTeacher && !comp.my_status && comp.status !== 'ended'" type="primary" @click="join">报名参赛</el-button>
        </div>
      </div>

      <el-alert v-if="!isTeacher && !comp.my_status" type="info" :closable="false" show-icon class="join-tip"
                title="报名后即可提交作品，截止前可反复重交（自动升版），由教师人工评审。" />

      <el-row :gutter="18" class="body-row">
        <el-col :span="15">
          <!-- 我的作品 -->
          <div class="panel">
            <h3>📦 我的作品</h3>
            <template v-if="myWork">
              <div class="work-card">
                <div class="work-head">
                  <span class="ver">第 {{ myWork.version }} 版</span>
                  <el-tag v-if="myWork.score != null" size="small" type="success">{{ myWork.score }} 分</el-tag>
                  <el-tag v-else size="small" type="info" effect="plain">待评审</el-tag>
                  <a v-if="myWork.filename" class="dl-link" @click="downloadMyWork">📎 {{ myWork.filename }}（{{ fmtSize(myWork.size) }}）</a>
                </div>
                <div class="work-desc">{{ myWork.description }}</div>
                <div class="work-meta">提交 {{ fmtTime(myWork.submitted_at) }} · 更新 {{ fmtTime(myWork.updated_at) }}</div>
                <div v-if="myWork.review_note" class="work-note">教师评语：{{ myWork.review_note }}</div>
              </div>
            </template>
            <el-empty v-else :image-size="60" description="还没有提交作品" />

            <el-form v-if="!isTeacher && comp.my_status && comp.status !== 'ended'" class="submit-form">
              <el-form-item label="作品说明" required>
                <el-input v-model="form.description" type="textarea" :rows="4" maxlength="5000" show-word-limit
                          placeholder="介绍你的作品思路、实现要点、运行方式（必填）" />
              </el-form-item>
              <el-form-item label="作品文件">
                <input ref="fileInput" type="file" @change="onPickFile" style="display:none" />
                <el-button @click="$refs.fileInput.click()">📎 选择文件（≤50MB，可选项）</el-button>
                <span v-if="form.fileName" class="file-name">{{ form.fileName }}</span>
              </el-form-item>
              <el-button type="primary" :loading="submitting" @click="submitWork">
                {{ myWork ? `重新提交（升为第 ${myWork.version + 1} 版）` : '提交作品' }}
              </el-button>
            </el-form>
          </div>
        </el-col>

        <el-col :span="9">
          <!-- 赛事公告 -->
          <div class="panel">
            <h3>📢 赛事公告</h3>
            <el-empty v-if="!announcements.length" description="暂无公告" :image-size="50" />
            <div v-for="a in announcements" :key="a.id" class="ann-item">
              <div class="ann-head"><b>{{ a.title }}</b><span class="ann-meta">{{ a.author }} · {{ (a.created_at || '').slice(5, 16) }}</span></div>
              <div class="ann-content">{{ a.content }}</div>
            </div>
          </div>

          <!-- 资料包 -->
          <div class="panel">
            <h3>📁 赛题资料包</h3>
            <el-empty v-if="!resources.length" description="暂无资料" :image-size="50" />
            <div v-for="r in resources" :key="r.id" class="res-item">
              <div class="res-info">
                <span class="res-title">{{ r.title }}</span>
                <span class="ann-meta">{{ r.filename }} · {{ fmtSize(r.size) }}</span>
              </div>
              <el-button size="small" text type="primary" :disabled="!isTeacher && !comp.my_status"
                         @click="downloadResource(r)">下载</el-button>
            </div>
            <p v-if="resources.length && !isTeacher && !comp.my_status" class="res-tip">报名后可下载资料</p>
          </div>
        </el-col>
      </el-row>
    </template>

    <el-empty v-else-if="!loading" description="竞赛不存在或未对你开放" >
      <el-button type="primary" @click="$router.push('/competitions')">返回竞赛广场</el-button>
    </el-empty>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import { Trophy, Back } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const compId = route.params.compId

const loading = ref(true)
const comp = ref(null)
const announcements = ref([])
const resources = ref([])
const myWork = ref(null)

const form = reactive({ description: '', file: null, fileName: '' })
const submitting = ref(false)
const fileInput = ref(null)

// 教师可预览（公告/资料 GET 端点对教师开放，不可报名/提交）
const isTeacher = computed(() => auth.user?.role === 'teacher')

const statusLabel = (s) => ({ published: '未开始', ongoing: '进行中', ended: '已结束' }[s] || s)
const statusTag = (s) => ({ published: 'primary', ongoing: 'success', ended: 'danger' }[s] || 'info')

const fmtTime = (iso) => iso ? new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
const fmtSize = (n) => {
  if (!n) return '0B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + 'KB'
  return (n / 1024 / 1024).toFixed(1) + 'MB'
}

const load = async () => {
  loading.value = true
  try {
    // 学生详情接口不开放，复用广场列表定位本场
    if (isTeacher.value) {
      const res = await request.get(`/api/competitions/${compId}`)
      comp.value = res.data
    } else {
      const res = await request.get('/api/competitions/lobby')
      comp.value = (res.data || []).find(c => String(c.id) === String(compId)) || null
      if (comp.value && comp.value.competition_type === 'ds') {
        // 误入：数据科学赛跳转到专用工作台
        router.replace(`/competitions/${compId}/ds`)
        return
      }
      if (comp.value && comp.value.competition_type !== 'project') {
        // 误入：限时赛跳回答题页
        router.replace(`/competition/take/${compId}`)
        return
      }
    }
    if (!comp.value) return
    const [ann, rs, wk] = await Promise.all([
      request.get(`/api/competitions/${compId}/announcements`),
      request.get(`/api/competitions/${compId}/resources`),
      isTeacher.value ? Promise.resolve({ data: { work: null } })
                      : request.get(`/api/competitions/${compId}/work`).catch(() => ({ data: { work: null } })),
    ])
    announcements.value = ann.data.items || []
    resources.value = rs.data.items || []
    myWork.value = wk.data.work || null
    if (myWork.value) form.description = myWork.value.description || ''
  } catch (e) {
    comp.value = null
  } finally {
    loading.value = false
  }
}

const join = async () => {
  await request.post(`/api/competitions/${compId}/join`)
  ElMessage.success('报名成功，即可提交作品')
  load()
}

const onPickFile = (e) => {
  const f = e.target.files?.[0]
  if (!f) return
  if (f.size > 50 * 1024 * 1024) {
    ElMessage.warning('文件超过 50MB 限制')
    e.target.value = ''
    return
  }
  form.file = f
  form.fileName = f.name
}

const submitWork = async () => {
  if (!form.description.trim()) return ElMessage.warning('请填写作品说明')
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('description', form.description)
    if (form.file) fd.append('file', form.file)
    const res = await request.post(`/api/competitions/${compId}/work`, fd)
    myWork.value = res.data.work
    ElMessage.success(res.data.message || '提交成功')
    form.file = null
    form.fileName = ''
    if (fileInput.value) fileInput.value.value = ''
  } finally {
    submitting.value = false
  }
}

const downloadBlob = async (url, filename) => {
  const res = await request.get(url, { responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(res.data)
  link.download = filename || 'download'
  link.click()
  URL.revokeObjectURL(link.href)
}

const downloadResource = (r) => downloadBlob(`/api/competition-resources/${r.id}/download`, r.filename)
const downloadMyWork = () => myWork.value && downloadBlob(`/api/competition-works/${myWork.value.id}/download`, myWork.value.filename)

onMounted(load)
</script>

<style scoped>
.page-wrapper { max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; flex-wrap: wrap; gap: 12px; }
.header-title h2 { font-size: 22px; font-weight: 700; color: var(--text-primary); margin: 0 0 8px 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.trophy { color: #d97706; }
.header-title p { font-size: 13.5px; color: var(--text-muted); margin: 0; }
.sub-info { color: var(--text-muted); }
.join-tip { margin-bottom: 16px; }
.panel { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 14px; padding: 18px 20px; margin-bottom: 16px; }
.panel h3 { font-size: 15.5px; font-weight: 700; color: var(--text-primary); margin: 0 0 14px; }
.work-card { border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; margin-bottom: 16px; }
.work-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ver { font-weight: 700; color: var(--text-primary); font-size: 14px; }
.dl-link { color: var(--el-color-primary, #409eff); cursor: pointer; font-size: 13px; }
.work-desc { margin-top: 8px; font-size: 13.5px; color: var(--text-secondary); white-space: pre-wrap; }
.work-meta { margin-top: 6px; font-size: 12px; color: var(--text-muted); }
.work-note { margin-top: 8px; padding: 8px 10px; border-radius: 8px; background: rgba(16, 185, 129, 0.1); color: #059669; font-size: 13px; }
.submit-form { border-top: 1px dashed var(--border-color); padding-top: 16px; }
.file-name { margin-left: 12px; font-size: 12.5px; color: var(--text-secondary); }
.ann-item { padding: 10px 0; border-bottom: 1px solid var(--border-color); }
.ann-item:last-child { border-bottom: none; }
.ann-head { display: flex; justify-content: space-between; gap: 8px; font-size: 13.5px; color: var(--text-primary); }
.ann-meta { font-size: 12px; color: var(--text-muted); white-space: nowrap; }
.ann-content { margin-top: 4px; font-size: 13px; color: var(--text-secondary); white-space: pre-wrap; }
.res-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
.res-item:last-child { border-bottom: none; }
.res-info { min-width: 0; }
.res-title { display: block; font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.res-info .ann-meta { display: block; }
.res-tip { margin: 8px 0 0; font-size: 12px; color: var(--text-muted); }
</style>
