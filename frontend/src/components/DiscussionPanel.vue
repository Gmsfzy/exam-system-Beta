<template>
  <div class="disc-panel">
    <div class="disc-head">
      <el-icon><ChatDotRound /></el-icon>
      <span>赛后讨论区</span>
      <span class="disc-count" v-if="threads.length">共 {{ totalCount }} 条</span>
    </div>

    <div class="disc-editor">
      <el-input v-model="draft" type="textarea" :rows="2" maxlength="500" show-word-limit
                :placeholder="replyTo ? '回复 @' + replyTo.username : '友善讨论，理性交流（最多 500 字）'" />
      <div class="disc-editor-actions">
        <el-button v-if="replyTo" size="small" text @click="replyTo = null">取消回复</el-button>
        <el-button type="primary" size="small" :loading="posting" @click="submit">
          {{ replyTo ? '回复' : '发布' }}
        </el-button>
      </div>
    </div>

    <el-empty v-if="!threads.length" description="还没有讨论，来抢沙发吧" :image-size="70" />
    <div v-else class="disc-threads">
      <div v-for="t in threads" :key="t.id" class="disc-item">
        <div class="disc-item-main">
          <router-link class="disc-user" :to="'/rank/player/' + t.user_id">{{ t.username }}</router-link>
          <span class="disc-time">{{ fmtTime(t.created_at) }}</span>
          <button class="disc-act" @click="startReply(t)">回复</button>
          <button class="disc-act danger" v-if="t.can_delete" @click="remove(t)">删除</button>
        </div>
        <div class="disc-content" v-text="t.content"></div>
        <div v-if="t.replies && t.replies.length" class="disc-replies">
          <div v-for="r in t.replies" :key="r.id" class="disc-item reply">
            <div class="disc-item-main">
              <router-link class="disc-user" :to="'/rank/player/' + r.user_id">{{ r.username }}</router-link>
              <span class="disc-reply-to">回复 @{{ t.username }}</span>
              <span class="disc-time">{{ fmtTime(r.created_at) }}</span>
              <button class="disc-act" @click="startReply(t)">回复</button>
              <button class="disc-act danger" v-if="r.can_delete" @click="remove(r)">删除</button>
            </div>
            <div class="disc-content" v-text="r.content"></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound } from '@element-plus/icons-vue'
import request from '../utils/request'
import { getSocket, authToken } from '../utils/socket'

const props = defineProps({ competitionId: { type: [Number, String], required: true } })
const threads = ref([])
const draft = ref('')
const replyTo = ref(null)
const posting = ref(false)
let socket = null
let pollTimer = null

const totalCount = computed(() =>
  threads.value.reduce((n, t) => n + 1 + ((t.replies && t.replies.length) || 0), 0))

const fmtTime = (iso) => iso
  ? new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  : ''

const load = async () => {
  try {
    const res = await request.get(`/api/competitions/${props.competitionId}/discussions`)
    threads.value = res.data || []
  } catch (e) { /* 静默：轮询兜底 */ }
}

const startReply = (t) => { replyTo.value = t }

const submit = async () => {
  const content = draft.value.trim()
  if (!content) { ElMessage.warning('内容不能为空'); return }
  posting.value = true
  try {
    const body = { content }
    if (replyTo.value) body.parent_id = replyTo.value.id
    await request.post(`/api/competitions/${props.competitionId}/discussions`, body)
    draft.value = ''
    replyTo.value = null
    await load()
  } catch (e) { /* 拦截器已提示 */ } finally {
    posting.value = false
  }
}

const remove = async (p) => {
  try {
    await request.delete(`/api/competitions/${props.competitionId}/discussions/${p.id}`)
    await load()
  } catch (e) { /* ignore */ }
}

const onNew = (payload) => {
  if (!payload || payload.competition_id !== Number(props.competitionId)) return
  load()
}

const setupSocket = () => {
  try {
    socket = getSocket()
    socket.emit('join_competition', { competition_id: Number(props.competitionId), token: authToken() })
    socket.on('discussion_new', onNew)
  } catch (e) { /* 降级为轮询 */ }
}

onMounted(() => {
  load()
  setupSocket()
  pollTimer = setInterval(load, 20000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (socket) socket.off('discussion_new', onNew)
})
</script>

<style scoped>
.disc-panel {
  margin-top: 20px;
  padding: 20px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
}
.disc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 14px;
}
.disc-count {
  margin-left: auto;
  font-size: 12px;
  font-weight: 400;
  color: var(--text-light);
}
.disc-editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.disc-threads { margin-top: 12px; }
.disc-item {
  padding: 12px 0;
  border-top: 1px solid var(--border-color);
}
.disc-item:first-child { border-top: none; }
.disc-item.reply {
  padding: 8px 0 0 0;
  border-top: none;
}
.disc-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.disc-user {
  font-weight: 700;
  color: #d97706;
  text-decoration: none;
}
.disc-user:hover { text-decoration: underline; }
.disc-reply-to { font-size: 12px; color: var(--text-muted); }
.disc-time { font-size: 12px; color: var(--text-light); }
.disc-act {
  margin-left: auto;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-muted);
}
.disc-act.danger { margin-left: 8px; color: #f56c6c; }
.disc-act:hover { color: var(--text-primary); }
.disc-content {
  margin-top: 6px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-primary);
  word-break: break-word;
  white-space: pre-wrap;
}
.disc-replies {
  margin-top: 6px;
  padding-left: 16px;
  border-left: 2px solid var(--border-color);
}
.dark .disc-panel {
  background: var(--glass-bg);
  border-color: var(--glass-border);
}
</style>
