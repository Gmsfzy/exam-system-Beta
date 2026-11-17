<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="goBack" content="我的收藏" class="back" />

    <div class="page-header">
      <div>
        <h2><el-icon :size="22" class="title-icon"><Star /></el-icon> 我的收藏</h2>
        <p class="sub-info">收藏的帖子与动态会集中在这里，方便随时回看</p>
      </div>
      <el-button :icon="ChatDotRound" @click="router.push('/community')">回到社区</el-button>
    </div>

    <el-tabs v-model="kind" class="kind-tabs" @tab-change="onKindChange">
      <el-tab-pane label="帖子" name="post" />
      <el-tab-pane label="动态" name="moment" />
    </el-tabs>

    <el-empty v-if="!loading && kind === 'post' && !posts.length" description="还没有收藏任何帖子">
      <el-button type="primary" @click="router.push('/community/forum')">去论坛逛逛</el-button>
    </el-empty>
    <el-empty v-else-if="!loading && kind === 'moment' && !moments.length" description="还没有收藏任何动态">
      <el-button type="primary" @click="router.push('/community')">去动态广场看看</el-button>
    </el-empty>

    <div v-else-if="kind === 'moment'" class="moment-list">
      <MomentCard
        v-for="m in moments"
        :key="m.id"
        :moment="m"
        :current-user-id="currentUserId"
        :show-follow="false"
        @open="openMoment"
        @comment="openMoment"
        @repost="openMoment"
        @like="toggleMomentLike"
        @favorite="unfavoriteMoment"
        @topic="(t) => router.push(`/community/topic/${t.id}`)"
      />
    </div>

    <div v-else class="post-grid">
      <div v-for="p in posts" :key="p.id" class="post-card" @click="goDetail(p.id)">
        <div class="card-top">
          <el-tag size="small" effect="light">{{ p.category_label || p.category }}</el-tag>
          <el-tag v-if="p.is_resolved" size="small" type="success" effect="plain">已解决</el-tag>
          <el-tag v-if="p.hidden" size="small" type="info" effect="plain">已折叠</el-tag>
        </div>
        <h3 class="card-title">{{ p.title }}</h3>
        <p class="card-summary">{{ p.content }}</p>
        <div class="card-meta">
          <span>{{ p.display_anon || p.display_username || '匿名用户' }}</span>
          <span class="spacer"></span>
          <span><el-icon><Star /></el-icon> {{ p.like_count || 0 }}</span>
          <span><el-icon><ChatDotRound /></el-icon> {{ p.comment_count || 0 }}</span>
          <el-button
            size="small"
            text
            type="warning"
            @click.stop="unfavorite(p)"
          >取消收藏</el-button>
        </div>
      </div>
    </div>

    <el-pagination
      v-if="total > pageSize"
      class="pager"
      background
      layout="prev, pager, next, total"
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      @current-change="onPage"
    />
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Star, ChatDotRound } from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import MomentCard from '../components/MomentCard.vue'

const router = useRouter()
const auth = useAuthStore()
const currentUserId = computed(() => auth.user?.id || null)
const kind = ref('post')
const loading = ref(false)
const posts = ref([])
const moments = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const load = async () => {
  loading.value = true
  try {
    if (kind.value === 'moment') {
      const res = await request.get('/api/community/moments/favorites', {
        params: { page: page.value, per_page: pageSize.value },
      })
      const data = res.data || {}
      moments.value = data.items || []
      total.value = data.total || 0
    } else {
      const res = await request.get('/api/community/favorites', {
        params: { page: page.value, per_page: pageSize.value },
      })
      const data = res.data || {}
      posts.value = data.items || []
      total.value = data.total || 0
    }
  } catch (e) {
    console.error('加载收藏失败:', e)
  } finally {
    loading.value = false
  }
}

const goBack = () => window.history.back()
const goDetail = (id) => router.push(`/community/${id}`)
const onPage = (p) => { page.value = p; load() }

const onKindChange = () => {
  page.value = 1
  total.value = 0
  load()
}

const openMoment = (m) => router.push(`/community/moment/${m.id}`)

const toggleMomentLike = async (m) => {
  try {
    const res = m.liked
      ? await request.delete(`/api/community/moments/${m.id}/like`)
      : await request.post(`/api/community/moments/${m.id}/like`)
    m.liked = res.data.liked
    m.like_count = res.data.like_count
  } catch (e) { /* 已提示 */ }
}

const unfavoriteMoment = async (m) => {
  try {
    await request.delete(`/api/community/moments/${m.id}/favorite`)
    moments.value = moments.value.filter((x) => x.id !== m.id)
    total.value = Math.max(0, total.value - 1)
    ElMessage.success('已取消收藏')
  } catch (e) {
    console.error('取消收藏失败:', e)
  }
}

const unfavorite = async (p) => {
  try {
    await request.delete(`/api/community/posts/${p.id}/favorite`)
    posts.value = posts.value.filter((x) => x.id !== p.id)
    total.value = Math.max(0, total.value - 1)
    ElMessage.success('已取消收藏')
  } catch (e) {
    console.error('取消收藏失败:', e)
  }
}

onMounted(load)
</script>

<style scoped>
.back { margin-bottom: 12px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; gap: 16px; flex-wrap: wrap; }
.page-header h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.sub-info { color: var(--el-text-color-secondary, #909399); font-size: 13px; margin: 0; }
.title-icon { color: #14b8a6; }
.kind-tabs { margin-bottom: 14px; }
.moment-list { display: flex; flex-direction: column; gap: 12px; }
.post-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.post-card { background: var(--el-bg-color, #fff); border: 1px solid var(--el-border-color-light, #e4e7ed); border-radius: 12px; padding: 18px; cursor: pointer; transition: all .25s; display: flex; flex-direction: column; gap: 10px; }
.post-card:hover { transform: translateY(-3px); box-shadow: 0 8px 24px rgba(20,184,166,.12); border-color: #14b8a6; }
.card-top { display: flex; gap: 6px; align-items: center; }
.card-title { font-size: 16px; font-weight: 600; line-height: 1.4; margin: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-summary { font-size: 13px; color: var(--el-text-color-secondary, #909399); margin: 0; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; min-height: 42px; line-height: 1.6; }
.card-meta { display: flex; gap: 10px; align-items: center; font-size: 12px; color: var(--el-text-color-secondary, #909399); border-top: 1px dashed var(--el-border-color-lighter, #ebeef5); padding-top: 10px; margin-top: auto; }
.card-meta .spacer { flex: 1; }
.pager { margin-top: 24px; justify-content: center; }
</style>
