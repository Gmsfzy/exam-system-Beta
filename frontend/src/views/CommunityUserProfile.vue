<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="goBack" content="个人主页" class="back" />

    <template v-if="profile">
      <div class="profile-card">
        <el-avatar :size="64" class="avatar">{{ initial }}</el-avatar>
        <div class="info">
          <h2 class="name">
            {{ profile.user.username }}
            <el-tag v-if="profile.user.role === 'teacher'" size="small" type="warning">教师</el-tag>
            <el-tag v-else size="small" type="info">学生</el-tag>
          </h2>
          <p class="joined">
            加入于 {{ fmtDate(profile.user.created_at) }}
            <span v-if="isSelf" class="self-tag">这是你的主页</span>
          </p>
        </div>
      </div>

      <div class="stats">
        <div class="stat">
          <span class="num">{{ profile.stats.post_count }}</span>
          <span class="label">发帖</span>
        </div>
        <div class="stat">
          <span class="num">{{ profile.stats.comment_count }}</span>
          <span class="label">评论</span>
        </div>
        <div class="stat">
          <span class="num">{{ profile.stats.resolved_count }}</span>
          <span class="label">已解决</span>
        </div>
        <div class="stat">
          <span class="num">{{ profile.stats.accepted_count }}</span>
          <span class="label">被采纳</span>
        </div>
        <div class="stat">
          <span class="num">{{ profile.stats.like_received }}</span>
          <span class="label">获赞</span>
        </div>
        <div class="stat">
          <span class="num">{{ profile.stats.points }}</span>
          <span class="label">社区积分</span>
        </div>
        <div class="stat">
          <span class="num">{{ profile.stats.level_name }}</span>
          <span class="label">Lv.{{ profile.stats.level }}</span>
        </div>
        <div class="stat">
          <span class="num">{{ profile.stats.rank }}</span>
          <span class="label">积分排名</span>
        </div>
      </div>

      <div class="section">
        <el-tabs v-model="tab" @tab-change="onTabChange">
          <el-tab-pane :label="`帖子 (${profile.posts.total})`" name="posts">
            <el-empty v-if="!profile.posts.items.length" :image-size="60" description="还没有公开帖子" />
            <div
              v-for="p in profile.posts.items"
              :key="p.id"
              class="post-item"
              @click="router.push(`/community/${p.id}`)"
            >
              <div class="item-top">
                <el-tag size="small" effect="light">{{ catName(p.category) }}</el-tag>
                <el-tag v-if="p.is_anonymous" size="small" type="info" effect="plain">匿名</el-tag>
                <el-tag v-if="p.is_resolved" size="small" type="success" effect="dark">已解决</el-tag>
              </div>
              <h4 class="item-title">{{ p.title }}</h4>
              <div class="item-meta">
                <span>{{ fmtDate(p.created_at) }}</span>
                <span class="spacer"></span>
                <span>赞 {{ p.like_count || 0 }}</span>
                <span>评论 {{ p.comment_count || 0 }}</span>
              </div>
            </div>
            <el-pagination
              v-if="profile.posts.total > pageSize"
              class="pager"
              background
              layout="prev, pager, next"
              :current-page="page"
              :page-size="pageSize"
              :total="profile.posts.total"
              @current-change="onPage"
            />
          </el-tab-pane>

          <el-tab-pane :label="`评论 (${profile.comments.total})`" name="comments">
            <el-empty v-if="!profile.comments.items.length" :image-size="60" description="还没有公开评论" />
            <div v-for="c in profile.comments.items" :key="c.id" class="comment-item">
              <p class="comment-body">{{ c.content }}</p>
              <div class="item-meta">
                <span v-if="c.post_id" class="post-link" @click="router.push(`/community/${c.post_id}`)">
                  来自帖子：{{ c.post_title || '#' + c.post_id }}
                </span>
                <span v-if="c.is_accepted" class="accepted">最佳答案</span>
                <span class="spacer"></span>
                <span>{{ fmtDate(c.created_at) }}</span>
              </div>
            </div>
            <el-pagination
              v-if="profile.comments.total > pageSize"
              class="pager"
              background
              layout="prev, pager, next"
              :current-page="page"
              :page-size="pageSize"
              :total="profile.comments.total"
              @current-change="onPage"
            />
          </el-tab-pane>
        </el-tabs>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const profile = ref(null)
const tab = ref('posts')
const page = ref(1)
const pageSize = ref(20)

const isSelf = computed(() => auth.user?.id === profile.value?.user?.id)
const initial = computed(() => (profile.value?.user?.username || '?').slice(0, 1).toUpperCase())

const CAT_LABELS = {
  discussion: '错题讨论', solution: '解法分享', help: '求助答疑',
  experience: '经验交流', resource: '资源下载', other: '其他',
}
const catName = (k) => CAT_LABELS[k] || k

const fmtDate = (s) => {
  if (!s) return ''
  try {
    return new Date(s).toISOString().slice(0, 10)
  } catch {
    return s
  }
}

const goBack = () => window.history.back()

const load = async () => {
  loading.value = true
  try {
    const res = await request.get(`/api/community/users/${route.params.id}`, {
      params: { page: page.value, per_page: pageSize.value },
    })
    profile.value = res.data || null
  } finally {
    loading.value = false
  }
}

const onPage = (p) => {
  page.value = p
  load()
}
const onTabChange = () => {
  page.value = 1
  load()
}

onMounted(load)
</script>

<style scoped>
.back { margin-bottom: 12px; }

.profile-card {
  display: flex;
  align-items: center;
  gap: 18px;
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 16px;
}
.avatar { background: #14b8a6; font-size: 26px; font-weight: 600; }
.name { margin: 0 0 6px; display: flex; align-items: center; gap: 8px; font-size: 22px; }
.joined { margin: 0; font-size: 13px; color: var(--el-text-color-secondary, #909399); }
.self-tag { margin-left: 10px; color: #14b8a6; }

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.stat {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 10px;
  padding: 14px;
  text-align: center;
}
.stat .num { display: block; font-size: 22px; font-weight: 600; color: #14b8a6; }
.stat .label { font-size: 12px; color: var(--el-text-color-secondary, #909399); }

.section {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px;
  padding: 20px 24px;
}

.post-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--el-border-color-lighter, #ebeef5);
  cursor: pointer;
}
.post-item:hover .item-title { color: #14b8a6; }
.post-item:last-child { border-bottom: none; }
.item-top { display: flex; gap: 6px; margin-bottom: 6px; }
.item-title { margin: 0 0 6px; font-size: 15px; }
.item-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  align-items: center;
}
.item-meta .spacer { flex: 1; }
.item-meta .post-link { cursor: pointer; color: #14b8a6; }
.item-meta .accepted { color: #67c23a; font-weight: 500; }

.comment-item { padding: 12px 0; border-bottom: 1px solid var(--el-border-color-lighter, #ebeef5); }
.comment-item:last-child { border-bottom: none; }
.comment-body { margin: 0 0 8px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }

.pager { margin-top: 16px; justify-content: center; }
</style>
