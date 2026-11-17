<template>
  <div class="composer">
    <div class="avatar">{{ avatarChar }}</div>
    <div class="body">
      <el-input
        ref="contentRef"
        v-model="content"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        maxlength="500"
        show-word-limit
        resize="none"
        placeholder="分享此刻的想法… 可用 #话题# 或 @同学"
        @input="onInput"
      />

      <div v-if="suggestions.length" class="mention-bar">
        <span class="tip">@</span>
        <button
          v-for="u in suggestions"
          :key="u.id"
          type="button"
          class="mention-chip"
          @click="insertMention(u)"
        >{{ u.username }}<em v-if="u.role === 'teacher'">师</em></button>
      </div>

      <div v-if="isLong" class="long-wrap">
        <el-input
          v-model="longBody"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 12 }"
          maxlength="20000"
          show-word-limit
          resize="none"
          placeholder="展开写成长文（≤ 20000 字）"
        />
      </div>

      <div v-if="topics.length" class="topic-row">
        <el-tag
          v-for="(t, i) in topics"
          :key="t"
          closable
          size="small"
          effect="light"
          @close="topics.splice(i, 1)"
        >#{{ t }}</el-tag>
      </div>

      <div class="toolbar">
        <el-button text size="small" :type="isLong ? 'primary' : 'default'" @click="isLong = !isLong">
          {{ isLong ? '收起长文' : '写长文' }}
        </el-button>
        <div class="topic-add">
          <span class="hash">#</span>
          <el-input
            v-model="topicInput"
            size="small"
            maxlength="30"
            placeholder="添加话题"
            class="topic-input"
            @keyup.enter="addTopic"
          />
          <el-button size="small" text @click="addTopic">添加</el-button>
        </div>
        <el-select v-model="visibility" size="small" class="vis-select">
          <el-option value="public" label="公开" />
          <el-option value="followers" label="仅关注者" />
          <el-option value="private" label="仅自己" />
        </el-select>
        <el-switch v-model="isAnonymous" size="small" active-text="匿名" />
        <div class="spacer" />
        <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="publish">
          发布
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onBeforeUnmount, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const props = defineProps({
  initialTopics: { type: Array, default: () => [] },
})

const emit = defineEmits(['published'])
const auth = useAuthStore()

const content = ref('')
const longBody = ref('')
const isLong = ref(false)
const topicInput = ref('')
const topics = ref([])
const visibility = ref('public')
const isAnonymous = ref(false)
const submitting = ref(false)
const suggestions = ref([])
const contentRef = ref(null)

onMounted(() => {
  props.initialTopics.forEach((name) => {
    const t = String(name || '').trim().replace(/^#+|#+$/g, '')
    if (t && !topics.value.includes(t) && topics.value.length < 4) topics.value.push(t)
  })
})

let mentionTimer = null

const avatarChar = computed(() => (auth.user?.username || '我').slice(0, 1).toUpperCase())

const canSubmit = computed(() => {
  if (submitting.value) return false
  if (!content.value.trim() && !longBody.value.trim()) return false
  return content.value.length <= 500 && longBody.value.length <= 20000
})

const onInput = (val) => {
  clearTimeout(mentionTimer)
  const match = /@([A-Za-z0-9_\u4e00-\u9fa5-]{0,20})$/.exec(val || '')
  if (!match || !match[1]) {
    suggestions.value = []
    return
  }
  const q = match[1]
  mentionTimer = setTimeout(async () => {
    try {
      const res = await request.get('/api/community/users/autocomplete', { params: { q } })
      suggestions.value = (res.data || []).slice(0, 6)
    } catch {
      suggestions.value = []
    }
  }, 250)
}

const insertMention = (user) => {
  content.value = content.value.replace(
    /@([A-Za-z0-9_\u4e00-\u9fa5-]{0,20})$/,
    `@${user.username} `
  )
  suggestions.value = []
  contentRef.value?.focus()
}

const addTopic = () => {
  const name = (topicInput.value || '').trim().replace(/^#+|#+$/g, '')
  if (!name) return
  if (topics.value.length >= 4) {
    ElMessage.warning('最多 4 个话题')
    return
  }
  if (topics.value.includes(name)) {
    topicInput.value = ''
    return
  }
  topics.value.push(name)
  topicInput.value = ''
}

const reset = () => {
  content.value = ''
  longBody.value = ''
  isLong.value = false
  topics.value = []
  topicInput.value = ''
  visibility.value = 'public'
  isAnonymous.value = false
  suggestions.value = []
}

const publish = async () => {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const res = await request.post('/api/community/moments', {
      content: content.value.trim(),
      long_body: longBody.value.trim() || null,
      visibility: visibility.value,
      is_anonymous: isAnonymous.value,
      topics: topics.value,
    })
    ElMessage.success('发布成功')
    reset()
    emit('published', res.data)
  } catch (e) {
    // request.js 已提示具体错误
  } finally {
    submitting.value = false
  }
}

onBeforeUnmount(() => clearTimeout(mentionTimer))
</script>

<style scoped>
.composer {
  display: flex; gap: 12px;
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #ebeef5);
  border-radius: 14px;
  padding: 16px;
}
.avatar {
  width: 40px; height: 40px; flex: 0 0 40px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #14b8a6, #0ea5e9);
  color: #fff; font-weight: 700;
}
.body { flex: 1; min-width: 0; }
.mention-bar {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-top: 8px; padding: 8px 10px;
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 10px;
}
.mention-bar .tip { color: #14b8a6; font-weight: 700; font-size: 12px; }
.mention-chip {
  border: 1px solid rgba(20, 184, 166, .35);
  background: #fff; color: #0f766e;
  border-radius: 999px; padding: 2px 10px;
  font-size: 12px; cursor: pointer;
}
.mention-chip:hover { background: rgba(20, 184, 166, .1); }
.mention-chip em {
  font-style: normal; margin-left: 4px;
  background: #14b8a6; color: #fff; border-radius: 4px;
  padding: 0 3px; font-size: 10px;
}
.long-wrap { margin-top: 10px; }
.topic-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.toolbar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-top: 10px;
}
.topic-add { display: flex; align-items: center; gap: 2px; }
.hash { color: #14b8a6; font-weight: 700; }
.topic-input { width: 108px; }
.vis-select { width: 112px; }
.spacer { flex: 1; }
@media (max-width: 640px) {
  .composer { padding: 12px; gap: 8px; }
  .avatar { width: 32px; height: 32px; flex-basis: 32px; font-size: 13px; }
  .toolbar { gap: 6px; }
  .topic-input { width: 84px; }
}
</style>
