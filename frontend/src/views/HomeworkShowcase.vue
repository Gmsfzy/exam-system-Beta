<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Trophy /></el-icon> 优秀作业展示墙</h2>
        <span class="sub">教师提名、学生同意后公开的优秀作品（仅本作业名单内可见）</span>
      </div>
      <el-button :icon="Refresh" @click="reload">刷新</el-button>
    </div>

    <el-tabs v-model="tab">
      <!-- 展示墙 -->
      <el-tab-pane label="展示墙" name="wall">
        <el-skeleton v-if="loading" :rows="4" animated />
        <el-empty v-else-if="!items.length" description="还没有已公开的优秀作业" />
        <div v-else class="wall-grid">
          <el-card v-for="it in items" :key="it.sub_id" shadow="hover" class="work-card">
            <div class="work-top">
              <span class="work-author">{{ it.author }}</span>
              <el-tag v-if="it.is_mine" size="small" type="success" effect="plain">我的作品</el-tag>
              <el-tag v-else-if="it.showcase_anon" size="small" type="info" effect="plain">匿名</el-tag>
            </div>
            <div class="work-hw">{{ it.homework_title }}</div>
            <div class="work-score" v-if="it.total_score != null">
              <b>{{ it.total_score }}</b><span class="of">/{{ it.max_score }}</span>
            </div>
            <div class="work-excerpt">{{ it.excerpt || '（无正文摘要）' }}</div>
            <div class="work-comment" v-if="it.comment">教师点评：{{ it.comment }}</div>
            <div class="work-foot">
              <el-button size="small" text type="primary" @click="openDetail(it)">查看详情</el-button>
              <span class="muted small">{{ fmt(it.graded_at) }}</span>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- 待我确认（学生） -->
      <el-tab-pane v-if="isStudent" name="invite">
        <template #label>
          <el-badge :value="invites.length" :hidden="!invites.length" class="tab-badge">待我确认</el-badge>
        </template>
        <el-empty v-if="!invites.length" description="暂无待确认的展示邀请" />
        <div v-else class="invite-list">
          <el-card v-for="iv in invites" :key="iv.sub_id" shadow="never" class="invite-card">
            <div class="invite-head">
              <span class="work-hw">《{{ iv.homework_title }}》</span>
              <span class="work-score" v-if="iv.total_score != null">
                <b>{{ iv.total_score }}</b><span class="of">/{{ iv.max_score }}</span>
              </span>
            </div>
            <div class="work-excerpt">{{ iv.excerpt || '（无正文摘要）' }}</div>
            <div class="work-comment" v-if="iv.comment">教师点评：{{ iv.comment }}</div>
            <div class="invite-actions">
              <el-checkbox v-model="iv._anon">匿名展示（不显示我的名字）</el-checkbox>
              <div class="invite-btns">
                <el-button size="small" @click="decline(iv)">暂不展示</el-button>
                <el-button size="small" type="primary" :loading="iv._busy" @click="accept(iv)">同意展示</el-button>
              </div>
            </div>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="detailDialog" title="作品详情" width="640px">
      <div v-if="detail">
        <div class="dt-row"><span class="dt-k">作业</span>{{ detail.homework_title }}</div>
        <div class="dt-row"><span class="dt-k">作者</span>{{ detail.author }}</div>
        <div class="dt-row" v-if="detail.total_score != null">
          <span class="dt-k">得分</span>{{ detail.total_score }} / {{ detail.max_score }}
        </div>
        <div class="dt-row" v-if="detail.comment"><span class="dt-k">教师点评</span>{{ detail.comment }}</div>
        <div class="dt-row"><span class="dt-k">正文</span></div>
        <div class="dt-content">{{ detail.content || '（该作业为题集式，无正文内容）' }}</div>
        <div class="dt-row" v-if="detail.attachment">
          <span class="dt-k">附件</span>{{ detail.attachment.filename }}
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Trophy, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isStudent = computed(() => auth.user?.role !== 'teacher')

const tab = ref('wall')
const loading = ref(false)
const items = ref([])
const invites = ref([])
const detailDialog = ref(false)
const detail = ref(null)

const fmt = (v) => (v || '').slice(0, 16).replace('T', ' ')

const loadWall = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/homeworks/showcase')
    items.value = res.data.items || []
  } finally {
    loading.value = false
  }
}

const loadInvites = async () => {
  if (!isStudent.value) return
  const res = await request.get('/api/homeworks/showcase/invitations')
  invites.value = (res.data.items || []).map(it => ({ ...it, _anon: false, _busy: false }))
}

const reload = async () => { await loadWall(); await loadInvites() }

const openDetail = async (it) => {
  const res = await request.get(`/api/homeworks/showcase/${it.sub_id}`)
  detail.value = res.data
  detailDialog.value = true
}

const accept = async (iv) => {
  iv._busy = true
  try {
    await request.post(`/api/homeworks/showcase/${iv.sub_id}/consent`,
      { accept: true, anonymous: iv._anon })
    ElMessage.success('已同意展示，感谢分享！')
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '操作失败')
  } finally {
    iv._busy = false
  }
}

const decline = async (iv) => {
  try {
    await request.post(`/api/homeworks/showcase/${iv.sub_id}/consent`, { accept: false })
    ElMessage.info('已拒绝本次展示邀请')
    await reload()
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '操作失败')
  }
}

onMounted(reload)
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
.header-title h2 { margin: 0; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #e6a23c; }
.sub { font-size: 12px; color: #909399; }
.wall-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.work-card { border-radius: 12px; }
.work-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.work-author { font-weight: 600; color: #303133; }
.work-hw { font-size: 13px; color: #6366f1; margin-bottom: 6px; }
.work-score { font-size: 14px; color: #d97706; margin-bottom: 6px; }
.work-score b { font-size: 20px; }
.work-score .of { color: #909399; font-size: 13px; }
.work-excerpt { font-size: 13px; color: #4b5563; line-height: 1.5; margin-bottom: 6px;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.work-comment { font-size: 12px; color: #6b7280; background: #f9fafb; border-radius: 6px;
  padding: 6px 8px; margin-bottom: 8px; }
.work-foot { display: flex; justify-content: space-between; align-items: center; }
.muted { color: #909399; }
.small { font-size: 12px; }
.invite-list { display: flex; flex-direction: column; gap: 14px; max-width: 720px; }
.invite-card { border-radius: 10px; }
.invite-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.invite-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; }
.invite-btns { display: flex; gap: 8px; }
.dt-row { font-size: 14px; margin-bottom: 8px; color: #303133; }
.dt-k { display: inline-block; width: 72px; color: #909399; }
.dt-content { white-space: pre-wrap; background: #f9fafb; border-radius: 8px; padding: 12px;
  font-size: 13px; color: #4b5563; line-height: 1.6; margin-bottom: 10px; }
:deep(.tab-badge sup) { top: 2px; }
</style>
