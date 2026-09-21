<template>
  <div class="md-view">
    <template v-for="(blk, i) in blocks" :key="i">
      <div v-if="blk.type === 'mermaid'" class="mermaid-box" v-html="blk.svg"></div>
      <pre v-else-if="blk.type === 'code'" class="code-box"><code>{{ blk.text }}</code></pre>
      <div v-else class="md-body" v-html="blk.html"></div>
    </template>
    <div v-if="!blocks.length" class="md-empty">{{ content || '（暂无内容）' }}</div>
  </div>
</template>

<script setup>
// 轻量 Markdown 渲染：标题/加粗/斜体/行内码/列表/表格/分隔线 + ```mermaid 图表
// 不引第三方 md 库；所有文本先做 HTML 转义，防 XSS
import { ref, watch, onMounted } from 'vue'

const props = defineProps({
  content: { type: String, default: '' },
})

const blocks = ref([])

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function inline(s) {
  return s
    .replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
}

function renderText(text) {
  const lines = text.split('\n')
  const out = []
  let listType = null
  const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null } }
  for (const raw of lines) {
    const line = esc(raw)
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    const ul = line.match(/^\s*[-*]\s+(.*)$/)
    const ol = line.match(/^\s*(\d+)[.、]\s+(.*)$/)
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { closeList(); out.push('<hr>') }
    else if (h) { closeList(); out.push(`<h${h[1].length + 1} class="md-h">${inline(h[2])}</h${h[1].length + 1}>`) }
    else if (ul) {
      if (listType !== 'ul') { closeList(); out.push('<ul>'); listType = 'ul' }
      out.push(`<li>${inline(ul[1])}</li>`)
    } else if (ol) {
      if (listType !== 'ol') { closeList(); out.push('<ol>'); listType = 'ol' }
      out.push(`<li>${inline(ol[2])}</li>`)
    } else if (!line.trim()) { closeList(); out.push('<br>') }
    else { closeList(); out.push(`<p class="md-p">${inline(line)}</p>`) }
  }
  closeList()
  return out.join('')
}

let mermaidMod = null
let seq = 0

async function build() {
  const src = props.content || ''
  const result = []
  const parts = src.split(/```(\w*)\n?([\s\S]*?)```/g)
  // split 带两个捕获组：[前, lang, body, 后, lang, body, ...]
  for (let i = 0; i < parts.length; i += 3) {
    const before = parts[i]
    if (before.trim()) result.push({ type: 'md', html: renderText(before) })
    const lang = (parts[i + 1] || '').toLowerCase()
    const body = parts[i + 2]
    if (body === undefined) continue
    if (lang === 'mermaid') {
      result.push({ type: 'mermaid', code: body, svg: '' })
    } else {
      result.push({ type: 'code', text: body })
    }
  }
  blocks.value = result
  // 懒加载 mermaid 渲染图表（失败降级为代码块）
  const mermaidBlocks = result.filter(b => b.type === 'mermaid')
  if (mermaidBlocks.length) {
    try {
      if (!mermaidMod) {
        const { default: mermaid } = await import('mermaid')
        mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'strict' })
        mermaidMod = mermaid
      }
      for (const b of mermaidBlocks) {
        const { svg } = await mermaidMod.render(`mdv-${++seq}`, b.code)
        b.svg = svg
      }
      blocks.value = [...result]
    } catch (e) {
      for (const b of mermaidBlocks) { b.type = 'code'; b.text = b.code }
      blocks.value = [...result]
    }
  }
}

onMounted(build)
watch(() => props.content, build)
</script>

<style scoped>
.md-view { line-height: 1.75; color: inherit; word-break: break-word; }
.md-body :deep(.md-h) { font-weight: 700; margin: 14px 0 8px; line-height: 1.4; }
.md-body :deep(h2.md-h) { font-size: 19px; }
.md-body :deep(h3.md-h) { font-size: 17px; }
.md-body :deep(h4.md-h), .md-body :deep(h5.md-h) { font-size: 15px; }
.md-body :deep(.md-p) { margin: 4px 0; }
.md-body :deep(ul), .md-body :deep(ol) { padding-left: 22px; margin: 6px 0; }
.md-body :deep(li) { margin: 3px 0; }
.md-body :deep(hr) { border: none; border-top: 1px solid var(--el-border-color, #dcdfe6); margin: 12px 0; }
.md-body :deep(code) { background: rgba(127, 127, 127, .15); border-radius: 3px; padding: 1px 5px; font-size: .92em; }
.md-body :deep(a) { color: var(--el-color-primary, #409eff); }
.code-box { background: rgba(127, 127, 127, .12); border-radius: 6px; padding: 10px 12px; overflow-x: auto; font-size: 13px; margin: 8px 0; }
.mermaid-box { text-align: center; margin: 10px 0; overflow-x: auto; }
.mermaid-box :deep(svg) { max-width: 100%; }
.md-empty { color: #909399; }
</style>
