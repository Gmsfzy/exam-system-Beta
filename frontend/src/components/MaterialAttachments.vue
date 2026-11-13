<template>
  <div v-if="items && items.length" class="att-wrap">
    <div class="att-head">
      <span class="att-title">📎 附件（{{ items.length }}）</span>
      <span class="att-tip">图片 / 视频 / PDF 就地预览，Office 与压缩包下载后用本地程序打开</span>
    </div>
    <div class="att-list">
      <div v-for="(a, i) in items" :key="i" class="att-item">
        <div class="att-row">
          <span class="att-ico">{{ ICONS[a.type] || '📄' }}</span>
          <a v-if="a.url && (a.type === 'link' || a.type === 'mindmap')" :href="a.url"
             target="_blank" rel="noopener" class="att-name">{{ a.name }}</a>
          <span v-else class="att-name">{{ a.name }}</span>
          <span class="att-size">{{ fmtSize(a.size) }}</span>
          <el-button v-if="openable(a)" size="small" text @click="toggle(a, i)">
            {{ opened[i] ? '收起' : '预览' }}
          </el-button>
          <el-button v-if="a.stored_name" size="small" text @click="download(a)">下载</el-button>
          <el-button size="small" text @click="copyLink(a)">复制链接</el-button>
        </div>
        <div v-if="opened[i]" class="att-body">
          <!-- 图片/视频/音频：直接给媒体元素，路径由后端拼好（UUID 名，与笔记插图同一口径） -->
          <img v-if="a.type === 'image'" :src="a.inline_url || a.url" :alt="a.name" class="att-media" />
          <video v-else-if="a.type === 'video'" :src="a.inline_url || a.url" controls
                 class="att-media att-video"></video>
          <!-- PDF：浏览器原生渲染，不必引 pdfjs（本站已有 pdfjs 但那是作业批注场景） -->
          <iframe v-else-if="a.type === 'pdf'" :src="a.inline_url || a.url" class="att-frame"></iframe>
          <!-- 纯文本/Markdown/mermaid 源：拉回来交给 MdView，公式与导图一并渲染 -->
          <div v-else-if="a.type === 'text'" v-loading="loading[i]" class="att-text">
            <MdView :content="texts[i] || ''" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
// 资料附件预览（v7.18 需求 h）：文档/表格/PPT/PDF/链接/视频/图片/思维导图
// 类型判定与 url 拼装都在后端 _attachments_out 里做好，这里只按 type 选渲染器。
import { reactive } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import MdView from './MdView.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
})

const ICONS = {
  doc: '📄', sheet: '📊', slide: '📽️', pdf: '📕', image: '🖼️', video: '🎬',
  archive: '🗜️', code: '💻', text: '📝', link: '🔗', mindmap: '🧠',
}

const opened = reactive({})
const texts = reactive({})
const loading = reactive({})

function fmtSize(n) {
  if (!n) return ''
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

function openable(a) {
  return ['image', 'video', 'pdf', 'text'].includes(a.type)
}

async function toggle(a, i) {
  opened[i] = !opened[i]
  if (!opened[i] || texts[i] !== undefined || a.type !== 'text') return
  // 文本类走受控下载接口取原文：私有资料的附件不该靠猜 UUID 直接拿 /uploads/
  loading[i] = true
  try {
    const { data } = await request.get(a.inline_url, { responseType: 'text', transformResponse: [(d) => d] })
    texts[i] = typeof data === 'string' ? data : JSON.stringify(data)
  } catch (e) {
    texts[i] = '（附件内容读取失败，可点下载保存本地）'
  } finally {
    loading[i] = false
  }
}

function download(a) {
  const url = a.download_url || a.inline_url || a.url
  if (!url) return
  const aEl = document.createElement('a')
  aEl.href = url
  aEl.download = a.name || ''
  document.body.appendChild(aEl)
  aEl.click()
  document.body.removeChild(aEl)
}

function copyLink(a) {
  const url = a.url || a.download_url
  if (!url) return ElMessage.warning('该附件没有可用链接')
  const full = url.startsWith('http') ? url : window.location.origin + url
  const done = () => ElMessage.success('链接已复制')
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(full).then(done)
  else done()
}
</script>

<style scoped>
.att-wrap { margin: 14px 0 6px; }
.att-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.att-title { font-weight: 600; font-size: 14px; }
.att-tip { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.att-list { display: flex; flex-direction: column; gap: 6px; }
.att-item { border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 8px; padding: 6px 10px; }
.att-row { display: flex; align-items: center; gap: 8px; }
.att-ico { font-size: 16px; }
.att-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--el-text-color-primary, #303133); }
.att-size { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.att-body { margin-top: 8px; }
.att-media { max-width: 100%; max-height: 420px; border-radius: 6px; display: block; }
.att-video { width: 100%; max-width: 720px; }
.att-frame { width: 100%; height: 520px; border: 0; border-radius: 6px; background: #f5f7fa; }
.att-text { background: rgba(127, 127, 127, .06); border-radius: 6px; padding: 8px 12px; max-height: 420px; overflow: auto; }
</style>
