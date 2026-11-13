<template>
  <div class="uh-page" v-loading="loading">
    <template v-if="profile">
      <div class="uh-card">
        <div class="uh-avatar">{{ (profile.username || '?')[0].toUpperCase() }}</div>
        <div class="uh-info">
          <h2>{{ profile.username }}
            <el-tag size="small" :type="profile.role === 'teacher' ? 'success' : 'info'">
              {{ profile.role === 'teacher' ? '教师' : '学生' }}</el-tag>
            <el-tag v-if="profile.is_mutual" size="small" type="warning" effect="plain">互相关注</el-tag>
          </h2>
          <div class="uh-stats">
            <span>公开资料 {{ profile.materials?.length || 0 }} 篇</span>
            <span v-if="insights.length">公开心得 {{ insights.length }} 篇</span>
            <span v-if="certs.length">公开证书 {{ certs.length }} 份</span>
            <span>关注 {{ profile.following_count }}</span>
            <span>粉丝 {{ profile.fans_count }}</span>
          </div>
        </div>
        <div class="uh-ops" v-if="profile.user_id !== myId">
          <el-button :type="profile.is_following ? 'default' : 'primary'" @click="toggleFollow">
            {{ profile.is_following ? '取消关注' : '+ 关注' }}
          </el-button>
        </div>
        <div class="uh-ops" v-else>
          <el-button text @click="$router.push('/learning/materials')">管理我的资料 →</el-button>
        </div>
      </div>

      <h3 class="uh-section">TA 的资料</h3>
      <el-empty v-if="!profile.materials?.length" description="还没有公开资料" />
      <div class="uh-grid">
        <div v-for="m in profile.materials" :key="m.id" class="uh-card-item">
          <div class="uh-m-title" @click="openView(m)">
            {{ m.title }}
            <el-tag size="small" effect="plain">{{ KINDS[m.kind] || m.kind }}</el-tag>
          </div>
          <div class="uh-m-excerpt" @click="openView(m)">{{ m.excerpt || '（无正文）' }}</div>
          <div class="uh-m-meta">
            <el-tag v-if="!m.is_public && m.owner_id === myId" size="small" type="info" effect="plain">私有</el-tag>
            <span>👁 {{ m.views }}</span><span>❤ {{ m.fav_count }}</span>
            <span>{{ (m.updated_at || '').slice(0, 10) }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- v7.19 公开证书：只展示广场那一套脱敏字段（后端 square 接口带 owner 筛选），
         编号、核验意见、佐证附件一律不在主页出现；点开不做详情抽屉是因为完整视图只给本人 -->
    <template v-if="insights.length">
      <h3 class="uh-section">TA 的学习心得</h3>
      <div class="uh-grid">
        <div v-for="i in insights" :key="'i' + i.id" class="uh-card-item">
          <div class="uh-m-title" @click="openInsight(i)">
            {{ i.title }}
            <el-tag size="small" effect="plain">{{ i.period_label }}</el-tag>
          </div>
          <div class="uh-i-text" @click="openInsight(i)">{{ firstText(i) }}</div>
          <div class="uh-m-meta">
            <span>{{ i.period_text }}</span>
            <span>👁 {{ i.views }}</span>
            <span>{{ (i.updated_at || '').slice(0, 10) }}</span>
            <span v-if="i.share_post_id" class="uh-link" @click="goPost(i)">🔗 社区帖</span>
          </div>
        </div>
      </div>
    </template>

    <template v-if="certs.length">
      <h3 class="uh-section">TA 的公开证书</h3>
      <div class="uh-cert-grid">
        <div v-for="c in certs" :key="'c' + c.kind + c.id" class="uh-cert" :class="'k-' + c.kind">
          <div class="uc-ribbon" v-if="c.verify_label">{{ c.verify_label }}</div>
          <div class="uc-title">{{ c.title }}</div>
          <div class="uc-sub">{{ c.subtitle || c.category_label }}</div>
          <div class="uc-meta">
            <el-tag size="small" effect="plain">{{ KINDS_CERT[c.kind] || c.kind }}</el-tag>
            <span>👁 {{ c.views }}</span>
            <span>{{ (c.earned_at || '').slice(0, 10) }}</span>
          </div>
        </div>
      </div>
      <div class="uh-cert-hint">
        证书只展示荣誉信息，完整票面请本人到
        <el-link type="primary" :underline="false" @click="$router.push('/learning/certificates')">我的证书</el-link>
        查看或打印
      </div>
    </template>

    <!-- 心得阅读：他人只能读到已公开的，正文走详情接口（会计一次浏览） -->
    <el-dialog v-model="insVisible" :title="viewInsight?.title" width="760px" top="6vh">
      <div v-if="viewInsight" class="ui-head">
        <el-tag size="small" effect="plain">{{ viewInsight.period_label }}</el-tag>
        <span class="ui-period">{{ viewInsight.period_text }}</span>
        <el-tag v-for="t in viewInsight.tags" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
      </div>
      <el-scrollbar max-height="60vh">
        <div v-for="(label, key) in SECTIONS" :key="key" class="ui-sec">
          <h4>{{ label }}</h4>
          <MdView v-if="viewInsight?.[key]" :content="viewInsight[key]" />
          <p v-else class="ui-empty">这一栏没有写</p>
        </div>
      </el-scrollbar>
    </el-dialog>

    <el-dialog v-model="viewVisible" :title="viewMat?.title" width="760px" top="6vh">
      <el-scrollbar max-height="62vh">
        <MdView :content="viewMat?.content || ''" />
      </el-scrollbar>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import MdView from '../components/MdView.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const myId = auth.user?.id
const KINDS = { video_script: '视频脚本', mindmap: '思维导图', lesson_plan: '教案', lecture: '讲解稿', summary: '总结要点', quiz: '自测题组', manual: '手写' }
const KINDS_CERT = { system: '系统结业', module: '跨模块', social: '社会第三方' }
const SECTIONS = { gains: '学习感悟与收获', summary: '我的心得与总结', reflection: '反思创造' }

const loading = ref(false)
const profile = ref(null)
const insights = ref([])
const certs = ref([])
async function load() {
  loading.value = true
  try {
    const { data } = await request.get(`/api/learning/users/${route.params.uid}/profile`)
    profile.value = data
    loadShared()
  } catch (e) { /* 拦截器提示 */ } finally { loading.value = false }
}

// 公开心得与公开证书是两块旁路展示，任一边失败都不该把主页开天窗，故各自吞异常
async function loadShared() {
  const uid = route.params.uid
  try {
    const { data } = await request.get(`/api/learning/insights/user/${uid}`)
    insights.value = data.items || []
  } catch (e) { insights.value = [] }
  try {
    const { data } = await request.get('/api/learning/certificates/square', { params: { owner: uid, size: 24 } })
    certs.value = data.items || []
  } catch (e) { certs.value = [] }
}

function firstText(i) {
  const p = i.previews || {}
  return p.gains || p.summary || p.reflection || '（正文为空）'
}

const insVisible = ref(false)
const viewInsight = ref(null)
async function openInsight(i) {
  try {
    const { data } = await request.get(`/api/learning/insights/${i.id}`)
    viewInsight.value = data.insight || data
    insVisible.value = true
    i.views = (i.views || 0) + 1
  } catch (e) { /* 拦截器提示 */ }
}
function goPost(i) {
  if (i.share_post_id) router.push(`/community/${i.share_post_id}`)
}

async function toggleFollow() {
  try {
    const { data } = await request.post(`/api/learning/users/${profile.value.user_id}/follow`)
    ElMessage.success(data.message)
    load()
  } catch (e) { /* 拦截器提示 */ }
}

const viewVisible = ref(false)
const viewMat = ref(null)
async function openView(m) {
  try {
    const { data } = await request.get(`/api/learning/materials/${m.id}`)
    viewMat.value = data.material
    viewVisible.value = true
  } catch (e) { /* 拦截器提示 */ }
}

onMounted(load)
watch(() => route.params.uid, load)
</script>

<style scoped>
.uh-page { padding: 4px; }
.uh-card { display: flex; align-items: center; gap: 16px; background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 12px; padding: 20px; }
.uh-avatar { width: 58px; height: 58px; border-radius: 50%; background: linear-gradient(135deg, #409eff, #79bbff); color: #fff; font-size: 26px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.uh-info { flex: 1; }
.uh-info h2 { margin: 0 0 6px; display: flex; align-items: center; gap: 8px; }
.uh-stats { color: #909399; font-size: 13px; display: flex; gap: 14px; }
.uh-section { margin: 18px 0 10px; }
.uh-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.uh-card-item { background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 10px; padding: 14px; display: flex; flex-direction: column; gap: 6px; }
.uh-m-title { font-weight: 600; cursor: pointer; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.uh-m-title:hover { color: var(--el-color-primary, #409eff); }
.uh-m-excerpt { color: #606266; font-size: 13px; cursor: pointer; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.uh-m-meta { color: #909399; font-size: 12px; display: flex; gap: 10px; align-items: center; }
.uh-i-text { color: #606266; font-size: 13px; cursor: pointer; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.uh-link { color: var(--el-color-primary, #409eff); cursor: pointer; }
.uh-cert-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.uh-cert { position: relative; border-radius: 10px; padding: 14px; border: 1px solid #e5e7eb; background: linear-gradient(160deg, #fafafa, #f3f4f6); overflow: hidden; }
.uh-cert.k-system { background: linear-gradient(160deg, #fffbeb, #fef3c7); border-color: #fcd34d; }
.uh-cert.k-module { background: linear-gradient(160deg, #eef2ff, #e0e7ff); border-color: #a5b4fc; }
.uh-cert.k-social { background: linear-gradient(160deg, #f0fdf4, #dcfce7); border-color: #86efac; }
.uc-ribbon { position: absolute; top: 8px; right: -22px; font-size: 11px; color: #fff; background: #059669; padding: 1px 24px; transform: rotate(38deg); }
.uc-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; padding-right: 34px; }
.uc-sub { color: #606266; font-size: 12px; min-height: 18px; }
.uc-meta { color: #909399; font-size: 12px; display: flex; gap: 8px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
.uh-cert-hint { color: #909399; font-size: 12px; margin-top: 8px; }
.ui-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.ui-period { color: #909399; font-size: 12px; }
.ui-sec { margin-bottom: 14px; }
.ui-sec h4 { margin: 0 0 6px; color: var(--el-color-primary, #409eff); font-size: 14px; }
.ui-empty { color: #c0c4cc; font-size: 13px; margin: 0; }
</style>
