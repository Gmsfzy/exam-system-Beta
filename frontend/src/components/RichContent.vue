<template>
  <div class="rich-content" v-html="sanitized"></div>
</template>

<script setup>
// 全站统一的「富内容」安全渲染组件：Markdown + LaTeX 公式 + 图文/动图/原始 HTML
// 设计：题干可能同时含列表/表格、数学公式、以及教师直接粘贴的 <img>/<video>/<iframe>。
// 安全模型 = markdown-it(允许 HTML) → KaTeX 渲染数学 → DOMPurify 净化白名单。
// ⚠️ 任何展示「用户/教师可控富文本」的地方都应走本组件，禁止再裸用 v-html（防存储型 XSS）。
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({
  content: { type: String, default: '' },
})

// markdown-it：开启 html（允许粘贴原始标签）、linkify（裸链接转超链）、breaks（软换行→<br>）
const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true,
  typographer: false,
})

// DOMPurify 净化配置：放开富媒体与表格/公式样式，剥离脚本与事件处理器
const PURIFY_CONFIG = {
  USE_PROFILES: { html: true, svg: true, svgFilters: true, mathMl: true },
  ADD_TAGS: ['iframe', 'video', 'audio', 'source', 'track', 'img', 'table', 'thead',
             'tbody', 'tfoot', 'tr', 'td', 'th', 'caption', 'col', 'colgroup',
             'sup', 'sub', 'span', 'div', 'figure', 'figcaption'],
  ADD_ATTR: ['target', 'rel', 'src', 'srcset', 'alt', 'title', 'width', 'height',
             'controls', 'autoplay', 'loop', 'muted', 'poster', 'preload',
             'frameborder', 'allow', 'allowfullscreen', 'referrerpolicy',
             'colspan', 'rowspan', 'align', 'loading', 'decoding', 'style', 'class', 'id'],
  // 放行 http(s)/mailto/tel、「data:image/*」内联图片，以及站内相对路径（/uploads/...）。
  // 笔记/资料插图与链接常写为 `/uploads/xxx.png`，不给放行会被剔掉 src 变成碎图；
  // 但必须排除协议相对写法 `//host/...`（等价于站外跳板），故用 (?!/) 卡住第二个斜杠。
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|data:image\/|\/(?!\/))/i,
}

// 一次性钩子：外链安全化 + iframe 收敛 + KaTeX class 保留
let hooked = false
function ensureHook() {
  if (hooked) return
  hooked = true
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (node.tagName === 'A' && node.getAttribute('target') === '_blank') {
      node.setAttribute('rel', 'noopener noreferrer')
    }
    if (node.tagName === 'IFRAME') {
      node.setAttribute('frameborder', '0')
      node.setAttribute('referrerpolicy', 'no-referrer')
      node.setAttribute('allowfullscreen', '')
    }
  })
}
ensureHook()

// 数学预处理：把 $$..$$ / $..$ / \[..\] / \(..\) 抽出为占位符，避免被 Markdown 破坏，
// 渲染后再用 KaTeX 还原。哨兵用私用区字符 \uE000（正常文本不出现，且不会被 markdown-it 规范化删除；
// 切勿用 \u0000——markdown-it 会主动 strip U+0000，导致占位符被破坏无法回填）。
const SENT = '\uE000'
function extractMath(text) {
  const store = []
  const put = (tex, display) => SENT + store.push({ tex, display }) + SENT
  let out = String(text == null ? '' : text)
  // 块级：$$...$$ 与 \[...\]
  out = out.replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => put(t, true))
  out = out.replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => put(t, true))
  // 行内：\(...\)
  out = out.replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => put(t, false))
  // 行内：$...$（避开货币：要求紧邻非空白，且内部不含空白起止）
  out = out.replace(/\$([^\s$](?:.*?[^\s$])?)\$/g, (_, t) => put(t, false))
  return { text: out, store }
}

function renderMath(store) {
  return (html) => store.reduce((acc, m, i) => {
    let rendered
    try {
      rendered = katex.renderToString(m.tex, {
        displayMode: m.display,
        throwOnError: false,
        output: 'html',
        strict: false,
      })
    } catch (e) {
      rendered = `<code>${escapeHtml(m.tex)}</code>`
    }
    // 函数式替换：避免 KaTeX 输出中的 $ 被 String.replace 当特殊模式（$&/$'/$1）解析
    return acc.replace(SENT + (i + 1) + SENT, () => rendered)
  }, html)
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// 小容量结果缓存：同一题干字符串反复渲染（列表/翻页）时避免重复 md+katex+净化开销
const cache = new Map()
const CACHE_MAX = 300

const sanitized = computed(() => {
  const raw = props.content || ''
  if (!raw.trim()) return ''
  if (cache.has(raw)) return cache.get(raw)
  let html
  try {
    const { text, store } = extractMath(raw)
    html = md.render(text)
    html = renderMath(store)(html)
  } catch (e) {
    html = escapeHtml(raw) // 解析异常降级为纯文本转义，绝不丢内容也不裸渲染
  }
  const clean = DOMPurify.sanitize(html, PURIFY_CONFIG)
  if (cache.size >= CACHE_MAX) cache.clear()
  cache.set(raw, clean)
  return clean
})
</script>

<style scoped>
.rich-content { word-break: break-word; line-height: 1.7; }
.rich-content :deep(p) { margin: 6px 0; }
.rich-content :deep(img), .rich-content :deep(video) { max-width: 100%; height: auto; border-radius: 6px; }
.rich-content :deep(table) { border-collapse: collapse; margin: 8px 0; width: 100%; }
.rich-content :deep(th), .rich-content :deep(td) { border: 1px solid var(--border-color, #d0d0d0); padding: 6px 10px; }
.rich-content :deep(pre) { background: rgba(127, 127, 127, .12); border-radius: 6px; padding: 10px 12px; overflow-x: auto; }
.rich-content :deep(code) { background: rgba(127, 127, 127, .15); border-radius: 3px; padding: 1px 5px; }
.rich-content :deep(iframe) { max-width: 100%; border: 0; }
.rich-content :deep(a) { color: var(--el-color-primary, #409eff); }
.rich-content :deep(.katex-display) { margin: 10px 0; overflow-x: auto; }
</style>
