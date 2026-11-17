<template>
  <article
    class="moment-card"
    :class="{ 'is-hidden': moment.hidden && !moment.can_view_content }"
    @click="$emit('open', moment)"
  >
    <div class="m-head">
      <button
        type="button"
        class="avatar"
        :class="{ anon: moment.is_anonymous }"
        :disabled="!canOpenProfile"
        @click.stop="openProfile"
      >{{ avatarChar }}</button>
      <div class="who">
        <div class="name-line">
          <button type="button" class="name name-button" :disabled="!canOpenProfile" @click.stop="openProfile">
            {{ moment.display_anon || moment.display_username || '未知用户' }}
          </button>
          <el-tag v-if="moment.is_anonymous" size="small" type="info" effect="plain">匿名</el-tag>
          <el-tag v-else-if="moment.repost_type" size="small" type="success" effect="plain">
            {{ moment.repost_type === 'quote' ? '引用' : '转发' }}
          </el-tag>
          <el-tag v-if="moment.visibility && moment.visibility !== 'public'" size="small" type="warning" effect="plain">
            {{ moment.visibility_label }}
          </el-tag>
        </div>
        <div class="meta">
          <span>{{ fmtTime(moment.created_at) }}</span>
          <span v-if="moment.repost_of_id && moment.repost_type === 'repost'"> · 转发了动态</span>
        </div>
      </div>
      <el-button
        v-if="showFollow && !moment.is_author && !moment.is_anonymous && currentUserId"
        size="small"
        :type="moment.author_followed ? 'info' : 'primary'"
        :plain="!!moment.author_followed"
        class="follow-btn"
        @click.stop="$emit('follow', moment)"
      >{{ moment.author_followed ? '已关注' : '+ 关注' }}</el-button>
    </div>

    <div class="m-body">
      <p v-if="moment.content" class="content">{{ moment.content }}</p>
      <div v-if="moment.is_long && !compact && moment.long_body" class="long-content">{{ moment.long_body }}</div>
      <p v-else-if="moment.is_long" class="long-hint">
        <el-icon><Document /></el-icon>
        长文动态 · 点击查看全文
      </p>

      <div
        v-if="moment.repost_snapshot"
        class="snapshot"
        @click.stop="openSnapshot"
      >
        <div class="snap-author">@{{ moment.repost_snapshot.display_username || '未知用户' }}</div>
        <div class="snap-content">{{ moment.repost_snapshot.content || '（图片/空内容）' }}</div>
      </div>

      <div v-if="moment.topics && moment.topics.length" class="topics">
        <button
          v-for="t in moment.topics"
          :key="t.id"
          type="button"
          class="topic-chip"
          @click.stop="$emit('topic', t)"
        >#{{ t.name }}</button>
      </div>
    </div>

    <div class="m-actions" @click.stop>
      <button type="button" class="act" :class="{ active: moment.liked }" @click="$emit('like', moment)">
        <el-icon><Pointer /></el-icon><span>{{ moment.like_count || 0 }}</span>
      </button>
      <button type="button" class="act" @click="$emit('comment', moment)">
        <el-icon><ChatDotRound /></el-icon><span>{{ moment.comment_count || 0 }}</span>
      </button>
      <button type="button" class="act" :disabled="repostDisabled" :title="repostTitle" @click="$emit('repost', moment)">
        <el-icon><Share /></el-icon><span>{{ moment.repost_count || 0 }}</span>
      </button>
      <button type="button" class="act" :class="{ active: moment.favorited }" @click="$emit('favorite', moment)">
        <el-icon><Star /></el-icon><span>{{ moment.favorite_count || 0 }}</span>
      </button>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ChatDotRound, Document, Pointer, Share, Star } from '@element-plus/icons-vue'

const router = useRouter()

const props = defineProps({
  moment: { type: Object, required: true },
  currentUserId: { type: Number, default: null },
  showFollow: { type: Boolean, default: true },
  compact: { type: Boolean, default: true },
})

const emit = defineEmits(['open', 'like', 'comment', 'repost', 'favorite', 'follow', 'topic'])

const canOpenProfile = computed(() => !props.moment.is_anonymous && !!props.moment.author_id)
const repostDisabled = computed(() => !!props.moment.repost_type
  || !!props.moment.is_anonymous
  || (!!props.moment.visibility && props.moment.visibility !== 'public'))
const repostTitle = computed(() => {
  if (props.moment.repost_type) return '转发或引用动态不能再次转发'
  if (props.moment.is_anonymous) return '匿名动态不能转发'
  if (props.moment.visibility && props.moment.visibility !== 'public') return '仅公开动态可以转发'
  return '转发'
})

const avatarChar = computed(() => {
  const name = props.moment.display_username || props.moment.display_anon || '?'
  return name.slice(0, 1).toUpperCase()
})

const fmtTime = (s) => {
  if (!s) return ''
  const d = new Date(s)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)} 天前`
  return s.slice(0, 16).replace('T', ' ')
}

const openSnapshot = () => {
  if (props.moment.repost_snapshot?.id) emit('open', { id: props.moment.repost_snapshot.id })
}

const openProfile = () => {
  if (canOpenProfile.value) router.push(`/community/users/${props.moment.author_id}`)
}
</script>

<style scoped>
.moment-card {
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #ebeef5);
  border-radius: 14px;
  padding: 16px 18px 10px;
  cursor: pointer;
  transition: border-color .2s, box-shadow .2s, transform .2s;
}
.moment-card:hover {
  border-color: rgba(20, 184, 166, .55);
  box-shadow: 0 6px 20px rgba(20, 184, 166, .10);
}
.moment-card.is-hidden { opacity: .72; }
.m-head { display: flex; align-items: flex-start; gap: 10px; }
.avatar {
  width: 40px; height: 40px; flex: 0 0 40px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #14b8a6, #0ea5e9);
  color: #fff; font-weight: 700; font-size: 16px;
  border: none; padding: 0; cursor: pointer;
}
.avatar:disabled, .name-button:disabled { cursor: default; }
.avatar.anon { background: linear-gradient(135deg, #94a3b8, #cbd5e1); }
.who { flex: 1; min-width: 0; }
.name-line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.name { font-weight: 600; font-size: 15px; color: var(--el-text-color-primary); }
.name-button { border: none; background: none; padding: 0; cursor: pointer; }
.name-button:not(:disabled):hover { color: #0d9488; }
.meta { font-size: 12px; color: var(--el-text-color-secondary); margin-top: 2px; }
.follow-btn { margin-left: auto; }
.m-body { margin: 10px 0 6px; padding-left: 50px; }
.content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 15px;
  line-height: 1.65;
  color: var(--el-text-color-primary);
}
.long-content {
  margin-top: 10px;
  color: var(--el-text-color-regular);
  font-size: 15px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}
.long-hint {
  display: inline-flex; align-items: center; gap: 4px;
  margin: 8px 0 0; font-size: 13px; color: #14b8a6;
}
.snapshot {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--el-fill-color-light, #f5f7fa);
  border: 1px solid var(--el-border-color-lighter, #f0f2f5);
  transition: background .2s;
}
.snapshot:hover { background: var(--el-fill-color, #eef1f6); }
.snap-author { font-size: 13px; color: #0d9488; font-weight: 600; }
.snap-content {
  margin-top: 4px; font-size: 14px; line-height: 1.55;
  color: var(--el-text-color-regular);
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
  white-space: pre-wrap; word-break: break-word;
}
.topics { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.topic-chip {
  border: none; cursor: pointer;
  background: rgba(20, 184, 166, .10);
  color: #0f766e;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  transition: background .2s;
}
.topic-chip:hover { background: rgba(20, 184, 166, .2); }
.m-actions {
  display: flex; align-items: center; gap: 6px;
  margin-left: 50px; padding: 8px 0 4px;
  border-top: 1px solid var(--el-border-color-lighter, #f2f3f5);
}
.act {
  display: inline-flex; align-items: center; gap: 5px;
  background: none; border: none; cursor: pointer;
  color: var(--el-text-color-secondary);
  font-size: 13px; padding: 5px 12px; border-radius: 8px;
  transition: background .18s, color .18s;
}
.act:hover { background: rgba(20, 184, 166, .08); color: #0d9488; }
.act:disabled { opacity: .45; cursor: not-allowed; background: none; color: var(--el-text-color-secondary); }
.act.active { color: #f43f5e; }
.act.active:nth-child(4) { color: #eab308; }
@media (max-width: 640px) {
  .m-body { padding-left: 0; }
  .m-actions { margin-left: 0; justify-content: space-between; }
  .moment-card { padding: 14px 14px 8px; }
}
</style>
