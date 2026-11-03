<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="goBack" content="我的收藏" class="back" />

    <div class="page-header">
      <div>
        <h2><el-icon :size="22" class="title-icon"><Star /></el-icon> 我的收藏</h2>
        <p class="sub-info">收藏的帖子会集中在这里，方便随时回看</p>
      </div>
      <el-button :icon="ChatDotRound" @click="router.push('/community')">回到论坛</el-button>
    </div>

    <el-empty v-if="!loading && !posts.length" description="还没有收藏任何帖子">
      <el-button type="primary" @click="router.push('/community')">去逛逛社区</el-button>
    </el-empty>

    <div class="post-grid" v-else>
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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Star, ChatDotRound } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()
const loading = ref(false)
const posts = ref([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/community/favorites', {
      params: { page: page.value, per_page: pageSize.value },
    })
    const data = res.data || {}
    posts.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    console.error('加载收藏失败:', e)
  } finally {
    loading.value = false
  }
}

const goBack = () => window.history.back()
const goDetail = (id) => router.push(`/community/${id}`)
const onPage = (p) => { page.value = p; load() }

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
