<template>
  <div class="page-wrapper" v-loading="loading">
    <el-page-header @back="goBack" content="个人主页" class="back" />

    <template v-if="profile">
      <div class="profile-card">
        <el-avatar :size="64" class="avatar">{{ initial }}</el-avatar>
        <div class="info">
          <div class="name-line">
            <h2 class="name">{{ profile.user.username }}</h2>
            <el-tag v-if="profile.user.role === 'teacher'" size="small" type="warning">教师</el-tag>
            <el-tag v-else size="small" type="info">学生</el-tag>
            <template v-if="!isSelf && auth.token">
              <el-button
                size="small"
                :type="followStats.is_following ? 'info' : 'primary'"
                :plain="!!followStats.is_following"
                :loading="followPending"
                @click="toggleFollow"
              >{{ followStats.is_following ? '已关注' : '+ 关注' }}</el-button>
              <el-button
                size="small"
                plain
                @click="router.push({ path: '/community/messages', query: { peer: profile.user.id } })"
              >私信</el-button>
              <el-tag v-if="followStats.is_mutual" size="small" type="success" effect="plain">互关</el-tag>
            </template>
          </div>
          <p class="joined">
            加入于 {{ fmtDate(profile.user.created_at) }}
            <span v-if="isSelf" class="self-tag">这是你的主页</span>
            <span class="follow-nums">
              关注 {{ followStats.following_count }} · 粉丝 {{ followStats.fans_count }}
            </span>
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
          <el-tab-pane :label="`动态 (${momentTotal})`" name="moments">
            <div v-if="momentsLoading" v-loading="true" class="moments-loading" />
            <el-empty v-else-if="!moments.length" :image-size="60" description="还没有公开动态" />
            <div v-else class="moment-list">
              <MomentCard
                v-for="m in moments"
                :key="m.id"
                :moment="m"
                :current-user-id="auth.user?.id || null"
                :show-follow="false"
                @open="(x) => router.push(`/community/moment/${x.id}`)"
                @comment="(x) => router.push(`/community/moment/${x.id}`)"
                @repost="(x) => router.push(`/community/moment/${x.id}`)"
                @like="toggleMomentLike"
                @favorite="toggleMomentFavorite"
                @topic="(t) => router.push(`/community/topic/${t.id}`)"
              />
            </div>
            <el-pagination
              v-if="momentTotal > pageSize"
              class="pager"
              background
              layout="prev, pager, next"
              :current-page="page"
              :page-size="pageSize"
              :total="momentTotal"
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
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import MomentCard from '../components/MomentCard.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const profile = ref(null)
const tab = ref('posts')
const page = ref(1)
const pageSize = ref(20)
const moments = ref([])
const momentTotal = ref(0)
const momentsLoading = ref(false)
const followPending = ref(false)
const followStats = ref({
  following_count: 0,
  fans_count: 0,
  is_following: false,
  is_mutual: false,
})

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
    loadFollowStats()
  } finally {
    loading.value = false
  }
}

const loadFollowStats = async () => {
  try {
    const res = await request.get(`/api/community/users/${route.params.id}/follow-stats`)
    followStats.value = res.data || followStats.value
  } catch {
    // 未登录/接口异常时保留默认 0，不影响主页展示
  }
}

const loadMoments = async () => {
  momentsLoading.value = true
  try {
    const res = await request.get(`/api/community/users/${route.params.id}/moments`, {
      params: { page: page.value, per_page: pageSize.value },
    })
    const data = res.data || {}
    moments.value = data.items || []
    momentTotal.value = data.total || 0
  } catch (e) {
    console.error('加载用户动态失败:', e)
  } finally {
    momentsLoading.value = false
  }
}

const toggleFollow = async () => {
  if (followPending.value) return
  followPending.value = true
  try {
    const res = await request.post(`/api/learning/users/${route.params.id}/follow`)
    const following = !!res.data.following
    followStats.value.is_following = following
    followStats.value.fans_count = Math.max(0, (followStats.value.fans_count || 0) + (following ? 1 : -1))
    followStats.value.is_mutual = following && !!followStats.value.is_followed_by
    ElMessage.success(following ? '已关注' : '已取消关注')
  } catch (e) { /* 已提示 */ } finally {
    followPending.value = false
  }
}

const toggleMomentLike = async (m) => {
  try {
    const res = m.liked
      ? await request.delete(`/api/community/moments/${m.id}/like`)
      : await request.post(`/api/community/moments/${m.id}/like`)
    m.liked = res.data.liked
    m.like_count = res.data.like_count
  } catch (e) { /* 已提示 */ }
}

const toggleMomentFavorite = async (m) => {
  try {
    const res = m.favorited
      ? await request.delete(`/api/community/moments/${m.id}/favorite`)
      : await request.post(`/api/community/moments/${m.id}/favorite`)
    m.favorited = res.data.favorited
    m.favorite_count = res.data.favorite_count
  } catch (e) { /* 已提示 */ }
}

const onPage = (p) => {
  page.value = p
  if (tab.value === 'moments') loadMoments()
  else load()
}
const onTabChange = () => {
  page.value = 1
  if (tab.value === 'moments') loadMoments()
  else load()
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
.name-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.follow-nums { margin-left: 12px; color: var(--el-text-color-secondary, #909399); }
.moment-list { display: flex; flex-direction: column; gap: 12px; }
.moments-loading { height: 120px; }

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
