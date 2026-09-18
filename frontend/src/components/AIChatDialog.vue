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
          <el-button class="header-close" text circle @click="open = false">
            <el-icon :size="16"><Close /></el-icon>
          </el-button>
        </div>

        <div ref="bodyRef" class="chat-body">
          <div
            v-for="(m, i) in messages" :key="i"
            class="msg-row" :class="m.role === 'user' ? 'from-user' : 'from-ai'"
          >
            <div v-if="m.role === 'assistant'" class="msg-avatar">
              <el-icon :size="13"><MagicStick /></el-icon>
            </div>
            <div class="msg-bubble" :class="{ 'is-error': m.error }">{{ m.content }}</div>
          </div>

          <div v-if="loading" class="msg-row from-ai">
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
import { ChatDotRound, MagicStick, Close, Promotion } from '@element-plus/icons-vue'
import request from '../utils/request'

const props = defineProps({
  // 页面背景摘要，注入 system 提示词，让 AI 建议更贴合当前页面
  context: { type: String, default: '' },
  // 欢迎语下的快捷提问
  suggestions: { type: Array, default: () => [] },
  title: { type: String, default: 'AI 学习助手' },
})

const WELCOME = '你好，我是你的 AI 学习助手。可以问我知识点讲解、错题分析、复习规划等问题，我会结合你当前的学习情况给出建议。'

const open = ref(false)
const draft = ref('')
const loading = ref(false)
const messages = ref([{ role: 'assistant', content: WELCOME, welcome: true }])
const bodyRef = ref(null)
const inputRef = ref(null)

const subText = computed(() => (props.context ? '已了解当前页面情况' : '随时为你解答学习问题'))

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

// 仅把真实对话（排除欢迎语/错误提示）发给后端，服务端无状态
const historyPayload = () =>
  messages.value
    .filter(m => !m.welcome && !m.error)
    .map(m => ({ role: m.role, content: m.content }))

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
    const res = await request.post('/api/learning/ai-chat', {
      messages: historyPayload(),
      context: props.context,
    })
    messages.value.push({ role: 'assistant', content: res.data.reply || '（AI 未返回内容）' })
  } catch (e) {
    const msg = e?.response?.data?.message || 'AI 服务暂时不可用，请稍后再试'
    messages.value.push({ role: 'assistant', content: msg, error: true })
  }
  loading.value = false
  scrollBottom()
}

// 清空对话重新开始：关闭再打开即重置
watch(open, (v) => {
  if (v) {
    messages.value = [{ role: 'assistant', content: WELCOME, welcome: true }]
    scrollBottom()
    nextTick(() => inputRef.value?.focus())
  }
})
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
