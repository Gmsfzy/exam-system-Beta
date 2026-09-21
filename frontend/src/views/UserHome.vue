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

    <el-dialog v-model="viewVisible" :title="viewMat?.title" width="760px" top="6vh">
      <el-scrollbar max-height="62vh">
        <MdView :content="viewMat?.content || ''" />
      </el-scrollbar>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import MdView from '../components/MdView.vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const myId = auth.user?.id
const KINDS = { video_script: '视频脚本', mindmap: '思维导图', lecture: '讲解稿', summary: '总结要点', quiz: '自测题组', manual: '手写' }

const loading = ref(false)
const profile = ref(null)
async function load() {
  loading.value = true
  try {
    const { data } = await request.get(`/api/learning/users/${route.params.uid}/profile`)
    profile.value = data
  } catch (e) { /* 拦截器提示 */ } finally { loading.value = false }
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
</style>
