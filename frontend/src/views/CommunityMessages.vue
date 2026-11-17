<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div>
        <h2><el-icon :size="22" class="title-icon"><ChatLineSquare /></el-icon> 私信</h2>
        <p class="sub-info">与同学、老师一对一交流；非互关时对方回复前 1 条/分钟，最多 10 条/天</p>
      </div>
      <el-button :icon="ChatDotRound" @click="router.push('/community')">回到社区</el-button>
    </div>

    <div class="msg-shell" :class="{ 'chat-open': !!current }">
      <aside class="conv-pane" :aria-hidden="!!current">
        <div class="conv-head">
          <span>会话</span>
          <el-tag v-if="unreadTotal" size="small" type="danger" effect="dark">{{ unreadTotal }} 未读</el-tag>
        </div>

        <div v-if="loading" v-loading="true" class="conv-loading" />
        <el-empty v-else-if="!conversations.length" :image-size="64" description="还没有私信">
          <span class="hint">在同学主页点击「私信」即可开始</span>
        </el-empty>

        <div v-else class="conv-list">
          <button
            v-for="c in conversations"
            :key="c.id"
            type="button"
            class="conv-item"
            :class="{ active: current && current.id === c.id }"
            @click="selectConversation(c)"
          >
            <div class="avatar">{{ (c.peer?.username || '?').slice(0, 1).toUpperCase() }}</div>
            <div class="conv-main">
              <div class="conv-line">
                <span class="conv-name">{{ c.peer?.username || '未知用户' }}</span>
                <span class="conv-time">{{ fmtTime(c.last_message_at) }}</span>
              </div>
              <div class="conv-line">
                <span class="conv-preview">{{ c.last_preview || '还没有消息' }}</span>
                <el-badge v-if="c.unread" :value="c.unread" class="conv-badge" />
              </div>
            </div>
          </button>
        </div>
      </aside>

      <section v-if="current" class="chat-pane">
        <header class="chat-head">
          <el-button text :icon="ArrowLeft" class="mobile-back" @click="closeChat">返回</el-button>
          <div class="chat-peer">
            <b>{{ current.peer?.username || '未知用户' }}</b>
            <el-tag v-if="current.peer?.role === 'teacher'" size="small" type="warning" effect="plain">教师</el-tag>
            <el-tag v-if="current.is_mutual" size="small" type="success" effect="plain">互关</el-tag>
            <el-tag v-if="current.is_blocked_me" size="small" type="info" effect="plain">对方已拉黑你</el-tag>
          </div>
          <div class="chat-actions">
            <el-button
              v-if="!current.is_blocked_me"
              size="small"
              :type="current.is_blocked_by_me ? 'info' : 'danger'"
              plain
              @click="toggleBlock"
            >{{ current.is_blocked_by_me ? '解除拉黑' : '拉黑' }}</el-button>
            <el-button size="small" text type="danger" @click="hideConversation">删除会话</el-button>
          </div>
        </header>

        <div ref="messagesEl" class="messages" v-loading="messagesLoading">
          <div v-if="hasMore" class="older">
            <el-button link size="small" :loading="loadingOlder" @click="loadOlder">加载更早消息</el-button>
          </div>
          <div
            v-for="m in messages"
            :key="m.id"
            class="bubble-row"
            :class="{ mine: m.sender_id === currentUserId }"
          >
            <div class="bubble">
              <template v-if="m.recalled">［消息已撤回］</template>
              <template v-else-if="m.content_type === 'image'">
                <a :href="m.image_url" target="_blank" rel="noopener">［图片］</a>
              </template>
              <template v-else>{{ m.content }}</template>
            </div>
            <div class="bubble-meta">
              <span>{{ fmtTime(m.created_at) }}</span>
              <button
                v-if="m.sender_id !== currentUserId && !m.recalled"
                type="button"
                class="report-link"
                @click="reportMessage(m)"
              >举报</button>
            </div>
          </div>
          <el-empty v-if="!messages.length && !messagesLoading" :image-size="56" description="还没有消息，打个招呼吧" />
        </div>

        <div class="composer">
          <el-alert
            v-if="current.is_blocked"
            type="warning"
            :closable="false"
            show-icon
            :title="current.is_blocked_by_me ? '你已拉黑对方，解除后才能继续发送' : '对方已拉黑你，暂时无法发送私信'"
            class="block-alert"
          />
          <el-input
            v-model="draft"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            maxlength="2000"
            show-word-limit
            resize="none"
            :disabled="current.is_blocked"
            placeholder="输入私信内容，Enter 发送，Shift + Enter 换行"
            @keydown.enter.exact.prevent="send"
          />
          <div class="composer-actions">
            <span class="rate-hint" v-if="!current.is_mutual">非互关：对方回复前 1 条/分钟，最多 10 条/天</span>
            <div class="spacer" />
            <el-button type="primary" :loading="sending" :disabled="current.is_blocked || !draft.trim()" @click="send">
              发送
            </el-button>
          </div>
        </div>
      </section>

      <section v-else class="chat-pane chat-empty">
        <el-icon :size="40"><ChatLineSquare /></el-icon>
        <p>选择一个会话开始聊天</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ChatDotRound, ChatLineSquare } from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const currentUserId = computed(() => auth.user?.id || null)
const conversations = ref([])
const unreadTotal = ref(0)
const current = ref(null)
const messages = ref([])
const draft = ref('')
const loading = ref(false)
const messagesLoading = ref(false)
const loadingOlder = ref(false)
const sending = ref(false)
const hasMore = ref(false)
const nextCursor = ref(null)
const messagesEl = ref(null)

let pollTimer = null

const fmtTime = (s) => {
  if (!s) return ''
  const d = new Date(s)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return s.slice(5, 16).replace('T', ' ')
}

const loadConversations = async (keepCurrent = true, silent = false) => {
  if (!silent) loading.value = true
  try {
    const res = await request.get('/api/community/dm/conversations')
    const data = res.data || {}
    conversations.value = data.items || []
    unreadTotal.value = data.unread_total || 0
    if (keepCurrent && current.value) {
      const fresh = conversations.value.find((c) => c.id === current.value.id)
      if (fresh) current.value = fresh
    }
  } catch (e) {
    console.error('加载会话失败:', e)
  } finally {
    if (!silent) loading.value = false
  }
}

const scrollBottom = async () => {
  await nextTick()
  const el = messagesEl.value
  if (el) el.scrollTop = el.scrollHeight
}

const loadMessages = async (reset = true) => {
  if (!current.value) return
  messagesLoading.value = reset
  try {
    const params = { limit: 30 }
    if (!reset && nextCursor.value) params.before_id = nextCursor.value
    const res = await request.get(`/api/community/dm/conversations/${current.value.id}/messages`, { params })
    const data = res.data || {}
    messages.value = reset ? (data.items || []) : [...(data.items || []), ...messages.value]
    hasMore.value = !!data.has_more
    nextCursor.value = data.next_cursor || null
    if (reset) await scrollBottom()
  } catch (e) {
    console.error('加载消息失败:', e)
  } finally {
    messagesLoading.value = false
  }
}

const selectConversation = async (conv) => {
  current.value = conv
  messages.value = []
  hasMore.value = false
  nextCursor.value = null
  await loadMessages(true)
  await markRead(conv.id)
  await loadConversations(false, true)
}

const markRead = async (convId) => {
  try {
    await request.put(`/api/community/dm/conversations/${convId}/read`)
  } catch { /* 忽略 */ }
}

const closeChat = () => {
  current.value = null
  messages.value = []
}

const loadOlder = async () => {
  if (loadingOlder.value) return
  loadingOlder.value = true
  try {
    await loadMessages(false)
  } finally {
    loadingOlder.value = false
  }
}

const send = async () => {
  if (sending.value) return
  const content = draft.value.trim()
  if (!content || !current.value || current.value.is_blocked) return
  sending.value = true
  try {
    const res = await request.post(
      `/api/community/dm/conversations/${current.value.id}/messages`,
      { content },
    )
    messages.value.push(res.data)
    draft.value = ''
    await scrollBottom()
    loadConversations(false, true)
  } catch (e) {
    // request.js 已提示（含 429 频控文案）
  } finally {
    sending.value = false
  }
}

const reportMessage = async (m) => {
  try {
    const { value } = await ElMessageBox.prompt('请填写举报理由（≤ 200 字）', '举报私信', {
      confirmButtonText: '提交举报',
      cancelButtonText: '取消',
      inputPlaceholder: '如：辱骂、骚扰、广告…',
      inputValidator: (v) => (!!v && v.trim().length <= 200) || '理由必填且 ≤ 200 字',
    })
    await request.post('/api/community/reports', {
      target_type: 'dm_message', target_id: m.id, reason: value.trim(),
    })
    ElMessage.success('举报已提交，教师会尽快处理')
  } catch (e) {
    // 取消或接口错误
  }
}

const toggleBlock = async () => {
  if (!current.value) return
  const willBlock = !current.value.is_blocked_by_me
  try {
    if (willBlock) {
      await ElMessageBox.confirm('拉黑后双方将无法互发私信，确定继续吗？', '拉黑', { type: 'warning' })
      await request.post(`/api/community/users/${current.value.peer.id}/block`)
    } else {
      await request.delete(`/api/community/users/${current.value.peer.id}/block`)
    }
    current.value.is_blocked_by_me = willBlock
    current.value.is_blocked = willBlock || current.value.is_blocked_me
    ElMessage.success(willBlock ? '已拉黑' : '已解除拉黑')
    loadConversations(false, true)
  } catch (e) {
    // 取消或接口错误
  }
}

const hideConversation = async () => {
  if (!current.value) return
  try {
    await ElMessageBox.confirm('删除后会话会从你的列表隐藏，对方仍保留聊天记录。', '删除会话', { type: 'warning' })
    await request.delete(`/api/community/dm/conversations/${current.value.id}`)
    ElMessage.success('已删除')
    closeChat()
    loadConversations(false, true)
  } catch (e) {
    // 取消或接口错误
  }
}

const openPeerFromQuery = async () => {
  const peerId = Number(route.query.peer)
  if (!peerId) return
  try {
    const res = await request.post('/api/community/dm/conversations', { peer_id: peerId })
    const conv = res.data?.conversation
    if (conv) {
      await loadConversations(false, true)
      const fresh = conversations.value.find((c) => c.id === conv.id) || conv
      selectConversation(fresh)
    }
    router.replace({ path: '/community/messages' })
  } catch (e) {
    console.error('发起会话失败:', e)
  }
}

onMounted(async () => {
  await loadConversations(false, false)
  await openPeerFromQuery()
  if (!current.value && conversations.value.length) selectConversation(conversations.value[0])
  pollTimer = setInterval(() => {
    if (!sending.value) loadConversations(true, true)
  }, 30000)
})

onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.header-title h2, .page-header h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.title-icon { color: #14b8a6; }
.sub-info { color: var(--el-text-color-secondary, #909399); font-size: 13px; margin: 0; }

.msg-shell {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 0;
  height: calc(100vh - 210px);
  min-height: 460px;
  border: 1px solid var(--el-border-color-light, #ebeef5);
  border-radius: 16px;
  overflow: hidden;
  background: var(--el-bg-color, #fff);
  color: var(--el-text-color-primary, #303133);
}
.conv-pane { border-right: 1px solid var(--el-border-color-lighter, #f0f2f5); display: flex; flex-direction: column; min-height: 0; }
.conv-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; font-weight: 600; font-size: 14px;
  border-bottom: 1px solid var(--el-border-color-lighter, #f0f2f5);
}
.conv-loading { height: 160px; }
.conv-list { flex: 1; overflow-y: auto; }
.conv-item {
  width: 100%; display: flex; gap: 10px; align-items: flex-start;
  padding: 12px 14px; border: none; background: none; cursor: pointer;
  color: var(--el-text-color-primary, #303133);
  text-align: left; transition: background .16s;
}
.conv-item:hover { background: rgba(20, 184, 166, .06); }
.conv-item.active { background: rgba(20, 184, 166, .12); }
.avatar {
  width: 38px; height: 38px; flex: 0 0 38px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #14b8a6, #0ea5e9);
  color: #fff; font-weight: 700;
}
.conv-main { flex: 1; min-width: 0; }
.conv-line { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.conv-name { font-size: 14px; font-weight: 600; }
.conv-time { font-size: 11px; color: var(--el-text-color-secondary); flex: 0 0 auto; }
.conv-preview {
  font-size: 12px; color: var(--el-text-color-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.conv-badge { flex: 0 0 auto; }

.chat-pane { display: flex; flex-direction: column; min-height: 0; }
.chat-empty {
  align-items: center; justify-content: center;
  color: var(--el-text-color-secondary); gap: 8px;
}
.chat-head {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; border-bottom: 1px solid var(--el-border-color-lighter, #f0f2f5);
}
.chat-peer { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; }
.chat-actions { display: flex; align-items: center; gap: 6px; }
.mobile-back { display: none; }
.messages { flex: 1; overflow-y: auto; padding: 16px; background: var(--el-fill-color-light, #fafbfc); }
.older { text-align: center; margin-bottom: 8px; }
.bubble-row { display: flex; flex-direction: column; align-items: flex-start; margin-bottom: 12px; }
.bubble-row.mine { align-items: flex-end; }
.bubble {
  max-width: 68%;
  padding: 9px 13px;
  border-radius: 12px;
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-lighter, #f0f2f5);
  color: var(--el-text-color-primary, #303133);
  font-size: 14px; line-height: 1.55;
  white-space: pre-wrap; word-break: break-word;
}
.bubble-row.mine .bubble {
  background: #14b8a6; color: #fff; border-color: #14b8a6;
}
.bubble-meta { display: flex; gap: 8px; margin-top: 3px; font-size: 11px; color: var(--el-text-color-secondary); }
.report-link {
  border: none; background: none; cursor: pointer;
  color: #94a3b8; font-size: 11px; padding: 0;
}
.report-link:hover { color: #f43f5e; }
.composer { border-top: 1px solid var(--el-border-color-lighter, #f0f2f5); padding: 12px 16px 14px; }
.block-alert { margin-bottom: 8px; }
.composer-actions { display: flex; align-items: center; margin-top: 8px; gap: 8px; }
.composer-actions .spacer { flex: 1; }
.rate-hint { font-size: 11px; color: var(--el-text-color-placeholder); }
.hint { font-size: 12px; color: var(--el-text-color-placeholder); }

@media (max-width: 760px) {
  .msg-shell { grid-template-columns: 1fr; height: calc(100vh - 190px); }
  .conv-pane { border-right: none; }
  .chat-pane { display: none; }
  .msg-shell.chat-open .conv-pane { display: none; }
  .msg-shell.chat-open .chat-pane { display: flex; }
  .mobile-back { display: inline-flex; }
  .bubble { max-width: 82%; }
}
</style>
