<template>
  <div class="ai-chat-root">
    <!-- 浮动入口按钮 -->
    <button v-if="!open" class="chat-fab" title="AI 学习助手" @click="open = true">
      <el-icon :size="26"><ChatDotRound /></el-icon>
      <span class="fab-dot"></span>
    </button>

    <!-- 对话面板 -->
    <transition name="chat-pop">
      <div v-if="open" class="chat-panel">
        <div class="chat-header">
          <div class="header-avatar">
            <el-icon :size="20"><MagicStick /></el-icon>
          </div>
          <div class="header-text">
            <span class="header-title">{{ title }}</span>
            <span class="header-sub">{{ subText }}</span>
          </div>
          <el-button class="header-btn" text circle title="历史会话" @click="toggleHistory">
            <el-icon :size="16"><Clock /></el-icon>
          </el-button>
          <el-button class="header-btn" text circle title="新建会话" @click="newConversation">
            <el-icon :size="16"><Plus /></el-icon>
          </el-button>
          <el-button class="header-close" text circle @click="open = false">
            <el-icon :size="16"><Close /></el-icon>
          </el-button>
        </div>

        <!-- 历史会话面板 -->
        <div v-if="showHistory" class="history-panel">
          <div class="history-head">
            <span>历史会话</span>
            <el-button size="small" text @click="showHistory = false">收起</el-button>
          </div>
          <div class="history-list">
            <div v-if="!conversations.length" class="history-empty">暂无历史会话</div>
            <div
              v-for="c in conversations" :key="c.id"
              class="history-item" :class="{ active: c.id === conversationId }"
              @click="openConversation(c.id)"
            >
              <div class="history-info">
                <span class="history-title">{{ c.title }}</span>
                <span class="history-meta">{{ c.message_count }} 条 · {{ fmtTime(c.updated_at) }}</span>
              </div>
              <el-button class="history-del" text circle size="small" @click.stop="removeConversation(c.id)">
                <el-icon :size="13"><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>

        <div ref="bodyRef" class="chat-body">
          <div
            v-for="(m, i) in messages" :key="i"
            class="msg-row" :class="m.role === 'user' ? 'from-user' : 'from-ai'"
          >
            <div v-if="m.role === 'assistant'" class="msg-avatar">
              <el-icon :size="13"><MagicStick /></el-icon>
            </div>
            <div class="msg-bubble" :class="{ 'is-error': m.error, 'is-degraded': m.degraded, 'is-streaming': m.streaming }">{{ m.content }}</div>
          </div>

          <div v-if="loading && !streamingMsg" class="msg-row from-ai">
            <div class="msg-avatar">
              <el-icon :size="13"><MagicStick /></el-icon>
            </div>
            <div class="msg-bubble typing">
              <span></span><span></span><span></span>
            </div>
          </div>

          <div v-if="messages.length <= 1 && suggestions.length" class="quick-chips">
            <button
              v-for="s in suggestions" :key="s"
              class="chip" :disabled="loading" @click="send(s)"
            >{{ s }}</button>
          </div>
        </div>

        <div class="chat-input">
          <textarea
            ref="inputRef"
            v-model="draft"
            :rows="1"
            placeholder="输入你的问题，Enter 发送 / Shift+Enter 换行"
            @keydown.enter.exact.prevent="onEnter"
            @input="autoGrow"
          ></textarea>
          <button class="send-btn" :disabled="loading || !draft.trim()" @click="send()">
            <el-icon :size="17"><Promotion /></el-icon>
          </button>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { ChatDotRound, MagicStick, Close, Promotion, Clock, Plus, Delete } from '@element-plus/icons-vue'
import request from '../utils/request'

const props = defineProps({
  // 页面背景摘要，注入 system 提示词，让 AI 建议更贴合当前页面
  context: { type: String, default: '' },
  // 欢迎语下的快捷提问
  suggestions: { type: Array, default: () => [] },
  title: { type: String, default: 'AI 学习助手' },
})

const WELCOME = '你好，我是你的 AI 学习助手。可以问我知识点讲解、错题分析、复习规划等问题，对话会自动保存，下次回来继续聊。'

const open = ref(false)
const draft = ref('')
const loading = ref(false)
const messages = ref([{ role: 'assistant', content: WELCOME, welcome: true }])
const bodyRef = ref(null)
const inputRef = ref(null)

// 会话持久化状态
const conversationId = ref(null)
const conversations = ref([])
const showHistory = ref(false)
// 当前正在流式接收的助手消息（逐 token 追加）
const streamingMsg = ref(null)

const subText = computed(() => {
  if (conversationId.value) return '对话已保存 · 可随时回看'
  return props.context ? '已了解当前页面情况' : '随时为你解答学习问题'
})

const fmtTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const scrollBottom = async () => {
  await nextTick()
  if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight
}

const autoGrow = () => {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 88) + 'px'
}

const onEnter = () => {
  if (!loading.value && draft.value.trim()) send()
}

// ── 历史会话管理 ──
const loadConversations = async () => {
  try {
    const res = await request.get('/api/learning/ai-conversations')
    conversations.value = res.data.items || []
  } catch (e) { /* 静默 */ }
}

const toggleHistory = () => {
  showHistory.value = !showHistory.value
  if (showHistory.value) loadConversations()
}

const newConversation = () => {
  conversationId.value = null
  showHistory.value = false
  messages.value = [{ role: 'assistant', content: WELCOME, welcome: true }]
}

const openConversation = async (cid) => {
  try {
    const res = await request.get(`/api/learning/ai-conversations/${cid}/messages`)
    conversationId.value = cid
    messages.value = [
      { role: 'assistant', content: WELCOME, welcome: true },
      ...(res.data.items || []).map(m => ({
        role: m.role, content: m.content, degraded: m.degraded,
      })),
    ]
    showHistory.value = false
    scrollBottom()
  } catch (e) { /* 拦截器已提示 */ }
}

const removeConversation = async (cid) => {
  try {
    await request.delete(`/api/learning/ai-conversations/${cid}`)
    if (cid === conversationId.value) newConversation()
    loadConversations()
  } catch (e) { /* ignore */ }
}

// ── 发送：优先 SSE 流式，异常时回退到非流式接口 ──
const send = async (preset) => {
  const text = (preset !== undefined ? preset : draft.value).trim()
  if (!text || loading.value) return
  if (preset === undefined) {
    draft.value = ''
    const el = inputRef.value
    if (el) el.style.height = 'auto'
  }

  messages.value.push({ role: 'user', content: text })
  loading.value = true
  scrollBottom()
  try {
    await streamChat(text)
  } catch (e) {
    // 流式失败（含降级）：清掉半截流式气泡，回退非流式端点
    if (streamingMsg.value) {
      messages.value = messages.value.filter(m => m !== streamingMsg.value)
      streamingMsg.value = null
    }
    try {
      const history = messages.value
        .filter(m => !m.welcome && !m.error)
        .map(m => ({ role: m.role, content: m.content }))
      const res = await request.post('/api/learning/ai-chat', {
        messages: [...history, { role: 'user', content: text }].slice(-12),
        context: props.context,
      })
      messages.value.push({ role: 'assistant', content: res.data.reply || '（AI 未返回内容）' })
    } catch (e2) {
      const msg = e2?.response?.data?.message || 'AI 服务暂时不可用，请稍后再试'
      messages.value.push({ role: 'assistant', content: msg, error: true })
    }
  }
  loading.value = false
  scrollBottom()
}

const streamChat = async (text) => {
  const base = import.meta.env.VITE_API_BASE_URL || ''
  const headers = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('token')
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${base}/api/learning/ai-chat/stream`, {
    method: 'POST',
    headers,
    credentials: 'include',
    body: JSON.stringify({ conversation_id: conversationId.value, message: text, context: props.context }),
  })
  if (!resp.ok || !resp.body) throw new Error(`stream http ${resp.status}`)

  const aiMsg = { role: 'assistant', content: '', streaming: true }
  messages.value.push(aiMsg)
  streamingMsg.value = aiMsg

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const line of block.split('\n')) {
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (!payload || payload === '[DONE]') continue
        try {
          const evt = JSON.parse(payload)
          if (evt.conversation_id) conversationId.value = evt.conversation_id
          if (evt.delta) { aiMsg.content += evt.delta; scrollBottom() }
          if (evt.done) aiMsg.degraded = !!evt.degraded
        } catch (e) { /* 非 JSON 块忽略 */ }
      }
    }
  }
  aiMsg.streaming = false
  streamingMsg.value = null
  if (!aiMsg.content) throw new Error('empty stream')
}

// 打开面板：保留当前会话；若从未聊过则重置欢迎语
const onOpen = () => {
  if (!conversationId.value && !messages.value.some(m => !m.welcome)) {
    messages.value = [{ role: 'assistant', content: WELCOME, welcome: true }]
  }
  scrollBottom()
  nextTick(() => inputRef.value?.focus())
}

watch(open, (v) => { if (v) onOpen() })
</script>

<style scoped>
.chat-fab {
  position: fixed;
  right: 28px;
  bottom: 28px;
  width: 56px;
  height: 56px;
  border: none;
  border-radius: 50%;
  background: linear-gradient(135deg, #06b6d4, #3b82f6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 2500;
  box-shadow: 0 8px 24px rgba(6, 182, 212, 0.45);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.chat-fab:hover {
  transform: translateY(-3px) scale(1.05);
  box-shadow: 0 14px 32px rgba(6, 182, 212, 0.55);
}

.fab-dot {
  position: absolute;
  top: 6px;
  right: 7px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #f59e0b;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.85);
}

.chat-panel {
  position: fixed;
  right: 28px;
  bottom: 28px;
  width: 380px;
  max-width: calc(100vw - 40px);
  height: 560px;
  max-height: calc(100vh - 60px);
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  box-shadow: 0 24px 56px rgba(2, 8, 23, 0.22);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 2600;
}

.chat-pop-enter-active,
.chat-pop-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.chat-pop-enter-from,
.chat-pop-leave-to {
  opacity: 0;
  transform: translateY(14px) scale(0.97);
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 14px;
  background: linear-gradient(135deg, #06b6d4, #3b82f6);
  color: #fff;
  flex-shrink: 0;
}

.header-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.25);
}

.header-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.header-title {
  font-size: 14px;
  font-weight: 600;
}

.header-sub {
  font-size: 11px;
  opacity: 0.85;
}

.header-close {
  color: #fff;
}

.header-btn {
  color: #fff;
}

.history-panel {
  position: absolute;
  top: 60px;
  left: 12px;
  right: 12px;
  max-height: 60%;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 14px 32px rgba(2, 8, 23, 0.25);
  z-index: 5;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.history-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-color);
}

.history-list {
  overflow-y: auto;
  padding: 6px;
}

.history-empty {
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  padding: 18px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.history-item:hover {
  background: rgba(6, 182, 212, 0.08);
}

.history-item.active {
  background: rgba(6, 182, 212, 0.14);
}

.history-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.history-title {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.history-del {
  color: var(--text-muted);
  flex-shrink: 0;
}

.history-del:hover {
  color: #ef4444;
}

.msg-bubble.is-degraded {
  border: 1px dashed rgba(245, 158, 11, 0.6);
  background: rgba(245, 158, 11, 0.08);
}

.msg-bubble.is-streaming::after {
  content: '▍';
  color: #06b6d4;
  animation: blink 1s infinite;
}

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.msg-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}

.msg-row.from-user {
  justify-content: flex-end;
}

.msg-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  flex-shrink: 0;
  background: linear-gradient(135deg, rgba(6, 182, 212, 0.18), rgba(59, 130, 246, 0.18));
  color: #06b6d4;
  display: flex;
  align-items: center;
  justify-content: center;
}

.msg-bubble {
  max-width: 78%;
  padding: 9px 12px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.from-ai .msg-bubble {
  background: var(--bg-page, rgba(148, 163, 184, 0.12));
  color: var(--text-primary);
  border-top-left-radius: 4px;
}

.from-user .msg-bubble {
  background: linear-gradient(135deg, #06b6d4, #3b82f6);
  color: #fff;
  border-top-right-radius: 4px;
  box-shadow: 0 4px 12px rgba(6, 182, 212, 0.3);
}

.msg-bubble.is-error {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border: 1px solid rgba(239, 68, 68, 0.25);
}

.typing span {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #06b6d4;
  margin-right: 4px;
  animation: blink 1.2s infinite ease-in-out;
}

.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; margin-right: 0; }

@keyframes blink {
  0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-2px); }
}

.quick-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-left: 30px;
}

.chip {
  border: 1px solid rgba(6, 182, 212, 0.4);
  background: rgba(6, 182, 212, 0.06);
  color: #0891b2;
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.chip:hover:not(:disabled) {
  background: rgba(6, 182, 212, 0.14);
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(6, 182, 212, 0.2);
}

.chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chat-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--border-color);
  flex-shrink: 0;
}

.chat-input textarea {
  flex: 1;
  resize: none;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  line-height: 1.5;
  padding: 8px 10px;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.chat-input textarea:focus {
  border-color: rgba(6, 182, 212, 0.6);
  box-shadow: 0 0 0 3px rgba(6, 182, 212, 0.12);
}

.send-btn {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #06b6d4, #3b82f6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: transform 0.18s ease, box-shadow 0.18s ease, opacity 0.18s ease;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(6, 182, 212, 0.4);
}

.send-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
