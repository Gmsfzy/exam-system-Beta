<template>
  <div class="md-view" :style="fontStyle" ref="rootEl">
    <div class="md-body" v-html="html"></div>
    <div v-if="!html" class="md-empty">{{ content || '（暂无内容）' }}</div>
  </div>
</template>

<script setup>
// 文档级富文本渲染（v7.18 重写）：Markdown + LaTeX 公式 + 代码高亮 + mermaid 思维导图（可缩放）
//
// 为什么要换掉原来那套手写解析：
// 1) 手写解析把 ```markdown 围栏当纯代码显示——AI 教案模板要求「板书设计用代码块」，
//    于是整段教案在预览里退化成源码（2026-11-13 用户截图即此），现在递归渲染成文档；
// 2) 手写解析没有公式：数学/物理/化学式与线性代数矩阵（\begin{bmatrix}）只能看到 LaTeX
//    源码，现在走 KaTeX（与全站统一的 RichContent 同一套抽取与净化口径）；
// 3) 手写解析没有代码高亮，思维导图渲染后不能放大缩小，长导图在小窗里根本看不清。
//
// 安全：markdown-it(允许 HTML) → KaTeX → DOMPurify 白名单净化，与 RichContent 一致；
// mermaid 用 securityLevel:'strict'，产出的 SVG 只由 mermaid 生成、不接受用户 HTML。
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({
  content: { type: String, default: '' },
  // 字号倍率（查看窗口右上角 A-/A+ 传进来，1 为原始大小）
  fontScale: { type: Number, default: 1 },
})

const rootEl = ref(null)
const html = ref('')
const fontStyle = computed(() => ({ fontSize: (props.fontScale || 1) + 'em' }))

const md = new MarkdownIt({ html: true, linkify: true, breaks: true, typographer: false })

const PURIFY_CONFIG = {
  USE_PROFILES: { html: true, svg: true, svgFilters: true, mathMl: true },
  ADD_TAGS: ['iframe', 'video', 'audio', 'source', 'track', 'img', 'table', 'thead',
             'tbody', 'tfoot', 'tr', 'td', 'th', 'caption', 'col', 'colgroup',
             'sup', 'sub', 'span', 'div', 'figure', 'figcaption'],
  ADD_ATTR: ['target', 'rel', 'src', 'srcset', 'alt', 'title', 'width', 'height',
             'controls', 'autoplay', 'loop', 'muted', 'poster', 'preload',
             'frameborder', 'allow', 'allowfullscreen', 'referrerpolicy',
             'colspan', 'rowspan', 'align', 'loading', 'decoding', 'style', 'class', 'id'],
  ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|data:image\/|\/(?!\/))/i,
}

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

// ── 数学：$$..$$ / $..$ / \[..\] / \(..\) 先抽成哨兵占位，渲染后回填 KaTeX ──
// 哨兵用私用区 \uE000：正常文本不出现，且不会被 markdown-it 规范化掉（U+0000 会被 strip）
const SENT = '\uE000'
function extractMath(text) {
  const store = []
  const put = (tex, display) => SENT + store.push({ tex, display }) + SENT
  let out = String(text == null ? '' : text)
  out = out.replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => put(t, true))
  out = out.replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => put(t, true))
  out = out.replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => put(t, false))
  // 行内 $...$ 避开货币：要求内部不以空白起止
  out = out.replace(/\$([^\s$](?:.*?[^\s$])?)\$/g, (_, t) => put(t, false))
  return { text: out, store }
}

function renderMath(store) {
  return (out) => store.reduce((acc, m, i) => {
    let one
    try {
      one = katex.renderToString(m.tex, {
        displayMode: m.display, throwOnError: false, output: 'html', strict: false,
      })
    } catch (e) {
      one = `<code>${escapeHtml(m.tex)}</code>`   // 公式写坏不炸整篇，原样回落到代码
    }
    // 函数式替换：KaTeX 输出里的 $ 与 $& 会被 String.replace 当模式解析
    return acc.replace(SENT + (i + 1) + SENT, () => one)
  }, out)
}

function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// ── 代码高亮：不引第三方高亮器（体积与离线），只做注释/字符串/数字/关键字四类着色 ──
// 输入已 HTML 转义，只在转义文本外面包 <span>，不会拼出可执行内容
const KW = ('function def return if else elif for while do break continue import from as class '
  + 'extends new this super try catch finally throw async await yield static public private '
  + 'protected void int long float double bool boolean char string str var let const null nil '
  + 'true false undefined self print SELECT FROM WHERE GROUP ORDER BY JOIN LEFT RIGHT INNER '
  + 'OUTER ON INSERT UPDATE DELETE CREATE TABLE DROP AS AND OR NOT NULL LIMIT').split(' ')
// 注释符号按语言分：把 CSS 的 #id、JS 里的 -- 误判成注释会整行变灰
const HASH_CMT = ['py', 'python', 'sh', 'bash', 'zsh', 'yaml', 'yml', 'rb', 'ruby', 'ini', 'toml']
const DASH_CMT = ['sql', 'lua', 'haskell', 'hs']
// 用正则字面量的 .source 拼接，避免在字符串里再套一层反斜杠转义
const STR_SRC = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/.source
const BLOCK_CMT_SRC = /\/\*[\s\S]*?\*\//.source
const LINE_CMT_SRC = /\/\/[^\n]*/.source

function tokRe(lang) {
  const cmts = [BLOCK_CMT_SRC, LINE_CMT_SRC]
  if (HASH_CMT.includes(lang)) cmts.push(/#[^\n]*/.source)
  if (DASH_CMT.includes(lang)) cmts.push(/--[^\n]*/.source)
  // 捕获组顺位：1 注释 / 2 字符串 / 3 关键字 / 4 数字，与下面回调一致
  return new RegExp('(' + cmts.join('|') + ')|(' + STR_SRC + ')'
    + '|\\b(' + KW.join('|') + ')\\b|\\b(\\d+(?:\\.\\d+)?)\\b', 'gi')
}

function highlight(code, lang) {
  const esc = escapeHtml(code)
  return esc.replace(tokRe(lang), (m, cmt, str, kw, num) => {
    if (str) return `<span class="tk-str">${str}</span>`
    if (cmt) return `<span class="tk-cmt">${cmt}</span>`
    if (kw) return `<span class="tk-kw">${kw}</span>`
    if (num) return `<span class="tk-num">${num}</span>`
    return m
  })
}

// mermaid 源码不进 HTML（防净化丢内容），按 id 存在进程内映射里，挂载后取回渲染
const mmStore = new Map()
let mmSeq = 0

md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  const info = (token.info || '').trim().toLowerCase()
  const body = token.content
  if (info === 'mermaid') {
    const id = `mm-${++mmSeq}`
    mmStore.set(id, body)
    return `<div class="mm-holder" data-mm="${id}"></div>`
  }
  // 教案「板书设计」这类嵌套 markdown：递归渲染成文档，而不是把源码摊给用户看
  if (info === 'markdown' || info === 'md') {
    try {
      return `<div class="md-nested">${md.render(body)}</div>`
    } catch (e) {
      return `<pre class="code-box"><code>${escapeHtml(body)}</code></pre>`
    }
  }
  const label = info ? `<span class="code-lang">${escapeHtml(info)}</span>` : ''
  // 用 span 不用 button：DOMPurify 对 button 的 type 属性未必放行，这里只想要个可点元素
  const copy = '<span class="code-copy" data-copy="1">复制</span>'
  return `<div class="code-wrap">${label}${copy}<pre class="code-box">`
    + `<code class="lang-${escapeHtml(info || 'text')}">${highlight(body, info)}</code></pre></div>`
}

function build() {
  const raw = props.content || ''
  mmStore.clear()
  if (!raw.trim()) { html.value = ''; return }
  let out
  try {
    const { text, store } = extractMath(raw)
    out = renderMath(store)(md.render(text))
  } catch (e) {
    out = `<p>${escapeHtml(raw)}</p>`      // 解析异常绝不丢内容，回落转义纯文本
  }
  html.value = DOMPurify.sanitize(out, PURIFY_CONFIG)
}

// ── mermaid 挂载：渲染 SVG + 缩放/平移控件 ──
let mermaidMod = null
const bound = new Set()      // 已绑过事件的图表 id，避免重复挂载时叠加监听

async function mountMermaid() {
  const root = rootEl.value
  if (!root) return
  const holders = [...root.querySelectorAll('.mm-holder')]
  if (!holders.length) return
  try {
    if (!mermaidMod) {
      const { default: mermaid } = await import('mermaid')
      mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'strict' })
      mermaidMod = mermaid
    }
  } catch (e) {
    for (const h of holders) fallback(h)
    return
  }
  for (const h of holders) {
    const key = h.getAttribute('data-mm')
    const code = mmStore.get(key) || ''
    if (!code) { fallback(h); continue }
    let svg
    try {
      ;({ svg } = await mermaidMod.render(`mmr-${key}`, code))
    } catch (e) {
      fallback(h, code)                      // 语法错误/渲染失败：退回源码，别留空白
      continue
    }
    h.innerHTML = toolbarHtml() + `<div class="mm-canvas"><div class="mm-inner">${svg}</div></div>`
    h.classList.add('mm-box')
    if (!bound.has(key)) { bound.add(key); bindZoom(h) }
  }
}

function toolbarHtml() {
  return '<div class="mm-bar">'
    + '<span class="mm-btn" data-act="out" title="缩小">－</span>'
    + '<span class="mm-btn" data-act="in" title="放大">＋</span>'
    + '<span class="mm-btn" data-act="fit" title="适应宽度">适宽</span>'
    + '<span class="mm-btn" data-act="reset" title="复位">1∶1</span>'
    + '<span class="mm-zoom">100%</span>'
    + '<span class="mm-tip">滚轮缩放 · 按住拖动平移</span></div>'
}

function fallback(holder, code) {
  holder.classList.add('mm-fail')
  holder.innerHTML = `<pre class="code-box"><code>${escapeHtml(code || '')}</code></pre>`
}

function bindZoom(box) {
  const canvas = box.querySelector('.mm-canvas')
  const inner = box.querySelector('.mm-inner')
  const label = box.querySelector('.mm-zoom')
  const st = { scale: 1 }
  const apply = () => {
    inner.style.transform = `scale(${st.scale})`
    inner.style.transformOrigin = 'top center'
    if (label) label.textContent = Math.round(st.scale * 100) + '%'
  }
  const set = (v) => { st.scale = Math.min(4, Math.max(0.3, v)); apply() }
  box.querySelector('.mm-bar').addEventListener('click', (e) => {
    const act = e.target.getAttribute('data-act')
    if (!act) return
    if (act === 'in') set(st.scale * 1.2)
    else if (act === 'out') set(st.scale / 1.2)
    else if (act === 'reset') set(1)
    else if (act === 'fit') {
      const svg = inner.querySelector('svg')
      const w = svg && (svg.getBoundingClientRect().width / st.scale)
      if (w && canvas.clientWidth) set(canvas.clientWidth / w)
    }
  })
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault()
    set(st.scale * (e.deltaY < 0 ? 1.12 : 1 / 1.12))
  }, { passive: false })
  // 放大后按住左键拖动改 scrollLeft/Top：比再套一层 transform 位移更不容易跑飞
  let drag = null
  const onMove = (e) => {
    if (!drag) return
    canvas.scrollLeft = drag.l - (e.clientX - drag.x)
    canvas.scrollTop = drag.t - (e.clientY - drag.y)
  }
  const onUp = () => { drag = null; canvas.classList.remove('grabbing') }
  canvas.addEventListener('mousedown', (e) => {
    drag = { x: e.clientX, y: e.clientY, l: canvas.scrollLeft, t: canvas.scrollTop }
    canvas.classList.add('grabbing')
  })
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  box._teardown = () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  apply()
}

// 复制按钮：事件委托，避免每次重建 HTML 都要重新绑一批监听
function onBodyClick(e) {
  const btn = e.target.closest && e.target.closest('.code-copy')
  if (!btn) return
  const pre = btn.parentElement && btn.parentElement.querySelector('code')
  if (!pre) return
  const text = pre.innerText
  const done = () => { btn.textContent = '已复制'; setTimeout(() => { btn.textContent = '复制' }, 1500) }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(() => legacyCopy(text, done))
  } else {
    legacyCopy(text, done)
  }
}

function legacyCopy(text, done) {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try { document.execCommand('copy'); done() } catch (e) { /* 复制失败不影响阅读 */ }
  document.body.removeChild(ta)
}

onMounted(async () => {
  build()
  await nextTick()
  await mountMermaid()
  rootEl.value && rootEl.value.addEventListener('click', onBodyClick)
})
onBeforeUnmount(() => {
  rootEl.value && rootEl.value.removeEventListener('click', onBodyClick)
  // 关窗口也要解绑：拖动监听挂在 window 上，不解就会随每次开合累积
  rootEl.value && rootEl.value.querySelectorAll('.mm-box').forEach((b) => {
    b._teardown && b._teardown()
  })
})
watch(() => props.content, async () => {
  // 换文档：旧的窗口级拖动监听要先解掉，否则每次切换都多留一对 handler
  rootEl.value && rootEl.value.querySelectorAll('.mm-box').forEach((b) => {
    b._teardown && b._teardown()
  })
  bound.clear()
  build()
  await nextTick()
  await mountMermaid()
})
</script>

<style scoped>
/* v-html 里的内容不带 scoped 属性，所有针对生成结构的样式都必须走 :deep() */
.md-view { line-height: 1.75; color: inherit; word-break: break-word; }
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3), .md-body :deep(h4) {
  font-weight: 700; margin: 16px 0 8px; line-height: 1.4;
}
.md-body :deep(h1) { font-size: 1.45em; }
.md-body :deep(h2) { font-size: 1.25em; }
.md-body :deep(h3) { font-size: 1.1em; }
.md-body :deep(h4) { font-size: 1em; }
.md-body :deep(p) { margin: 6px 0; }
.md-body :deep(ul), .md-body :deep(ol) { padding-left: 24px; margin: 6px 0; }
.md-body :deep(li) { margin: 3px 0; }
.md-body :deep(blockquote) {
  margin: 8px 0; padding: 6px 12px; border-left: 3px solid var(--el-border-color, #dcdfe6);
  background: rgba(127, 127, 127, .08); color: var(--el-text-color-regular, #606266);
}
.md-body :deep(hr) { border: none; border-top: 1px solid var(--el-border-color, #dcdfe6); margin: 12px 0; }
.md-body :deep(a) { color: var(--el-color-primary, #409eff); }
.md-body :deep(img), .md-body :deep(video) { max-width: 100%; height: auto; border-radius: 6px; }
.md-body :deep(.md-nested) {
  display: block; margin: 8px 0; padding: 10px 14px;
  border: 1px dashed var(--el-border-color, #dcdfe6); border-radius: 8px;
  background: rgba(127, 127, 127, .05);
}
.md-body :deep(table) { border-collapse: collapse; margin: 8px 0; width: 100%; font-size: .95em; }
.md-body :deep(th), .md-body :deep(td) {
  border: 1px solid var(--el-border-color, #dcdfe6); padding: 5px 9px;
  text-align: left; vertical-align: top;
}
.md-body :deep(th) { background: rgba(127, 127, 127, .12); font-weight: 600; }
.md-body :deep(code) { background: rgba(127, 127, 127, .15); border-radius: 3px; padding: 1px 5px; font-size: .92em; }
.md-body :deep(.katex-display) { margin: 10px 0; overflow-x: auto; }
.md-body :deep(.code-wrap) { position: relative; margin: 10px 0; }
.md-body :deep(.code-lang) {
  position: absolute; top: 6px; left: 10px; font-size: 11px; letter-spacing: .5px;
  color: var(--el-text-color-secondary, #909399); text-transform: uppercase;
}
.md-body :deep(.code-copy) {
  position: absolute; top: 4px; right: 8px; font-size: 11px; cursor: pointer;
  border: 1px solid var(--el-border-color, #dcdfe6); border-radius: 4px; padding: 1px 6px;
  background: var(--el-bg-color, #fff); color: var(--el-text-color-regular, #606266);
  user-select: none;
}
.md-body :deep(.code-box) {
  background: rgba(127, 127, 127, .12); border-radius: 6px; padding: 24px 12px 10px;
  overflow-x: auto; font-size: 13px; margin: 0; line-height: 1.6;
}
.md-body :deep(.code-box code) { background: none; padding: 0; font-size: inherit; }
.md-body :deep(.tk-str) { color: #2f8f46; }
.md-body :deep(.tk-cmt) { color: #8a8f98; font-style: italic; }
.md-body :deep(.tk-kw) { color: #b1358e; font-weight: 600; }
.md-body :deep(.tk-num) { color: #1f6fd0; }
.md-body :deep(.mm-box) { display: block; margin: 12px 0; }
.md-body :deep(.mm-bar) { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.md-body :deep(.mm-btn) {
  cursor: pointer; border: 1px solid var(--el-border-color, #dcdfe6); border-radius: 4px;
  padding: 2px 9px; font-size: 12px; background: var(--el-bg-color, #fff);
  color: var(--el-text-color-regular, #606266); user-select: none;
}
.md-body :deep(.mm-btn:hover) {
  border-color: var(--el-color-primary, #409eff); color: var(--el-color-primary, #409eff);
}
.md-body :deep(.mm-zoom) { font-size: 12px; color: var(--el-text-color-secondary, #909399); min-width: 40px; }
.md-body :deep(.mm-tip) { font-size: 11px; color: var(--el-text-color-placeholder, #a8abb2); }
.md-body :deep(.mm-canvas) {
  overflow: auto; max-height: 480px; border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 8px; background: var(--el-bg-color, #fff); cursor: grab;
}
.md-body :deep(.mm-canvas.grabbing) { cursor: grabbing; }
.md-body :deep(.mm-inner) {
  transition: transform .12s ease; width: max-content; min-width: 100%;
  padding: 8px; text-align: center;
}
.md-body :deep(.mm-inner svg) { max-width: none; }
.md-body :deep(.mm-fail .code-box) { padding-top: 10px; }
.md-empty { color: #909399; }
</style>
