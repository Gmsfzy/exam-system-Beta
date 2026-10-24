<template>
  <div class="ann-root">
    <!-- 工具栏：仅教师批改（非只读）可见 -->
    <div v-if="!readonly" class="ann-toolbar">
      <div class="tool-group">
        <el-tooltip v-for="t in TOOLS" :key="t.key" :content="t.label" placement="top">
          <el-button size="small" :type="tool === t.key ? 'primary' : 'default'"
                     :class="{ 'is-active': tool === t.key }" @click="pickTool(t.key)">
            <span class="tool-ico">{{ t.ico }}</span>
          </el-button>
        </el-tooltip>
      </div>
      <div class="tool-group">
        <input type="color" v-model="color" class="color-pick" title="颜色" />
        <el-select v-model="width" size="small" style="width: 84px" title="线宽">
          <el-option v-for="w in [2, 3, 5, 8, 12]" :key="w" :label="`线宽 ${w}`" :value="w" />
        </el-select>
      </div>
      <div class="tool-group">
        <el-button size="small" :disabled="!shapes.length" @click="undo">撤销</el-button>
        <el-button size="small" :disabled="!shapes.length" @click="clearAll">清空</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="save">保存批注</el-button>
      </div>
    </div>
    <div v-else class="ann-readonly-tip">教师批注（只读回放）</div>

    <div v-loading="loading" class="ann-pages">
      <div v-for="(pg, i) in pages" :key="i" class="ann-page">
        <img :src="pg.url" class="ann-img" draggable="false" alt="" />
        <svg class="ann-svg" :viewBox="`0 0 ${pg.vbW} ${pg.vbH}`" preserveAspectRatio="none"
             @pointerdown="onDown($event, i)" @pointermove="onMove($event, i)" @pointerup="onUp($event, i)">
          <defs>
            <marker :id="'arw-' + uid" markerWidth="10" markerHeight="10" refX="7" refY="3.5"
                    orient="auto" markerUnits="strokeWidth">
              <path d="M0,0 L8,3.5 L0,7 Z" :fill="currentColor" />
            </marker>
          </defs>
          <template v-for="s in shapesOf(i)" :key="s.id">
            <polyline v-if="s.type === 'pen'" :points="poly(s, pg)" fill="none"
                      :stroke="s.color" :stroke-width="s.width" stroke-linecap="round" stroke-linejoin="round" />
            <polyline v-else-if="s.type === 'highlight'" :points="poly(s, pg)" fill="none"
                      :stroke="s.color" :stroke-width="Math.max(s.width * 3, 12)" stroke-opacity="0.3"
                      stroke-linecap="round" stroke-linejoin="round" />
            <line v-else-if="s.type === 'line'" :x1="pt(s, pg, 0, 0)" :y1="pt(s, pg, 0, 1)"
                  :x2="pt(s, pg, 1, 0)" :y2="pt(s, pg, 1, 1)" :stroke="s.color" :stroke-width="s.width" stroke-linecap="round" />
            <line v-else-if="s.type === 'arrow'" :x1="pt(s, pg, 0, 0)" :y1="pt(s, pg, 0, 1)"
                  :x2="pt(s, pg, 1, 0)" :y2="pt(s, pg, 1, 1)" :stroke="s.color" :stroke-width="s.width"
                  stroke-linecap="round" :marker-end="`url(#arw-${uid})`" />
            <rect v-else-if="s.type === 'rect'" :x="box(s, pg).x" :y="box(s, pg).y"
                  :width="box(s, pg).w" :height="box(s, pg).h" fill="none" :stroke="s.color" :stroke-width="s.width" />
            <ellipse v-else-if="s.type === 'ellipse'" :cx="box(s, pg).x + box(s, pg).w / 2"
                     :cy="box(s, pg).y + box(s, pg).h / 2" :rx="box(s, pg).w / 2" :ry="box(s, pg).h / 2"
                     fill="none" :stroke="s.color" :stroke-width="s.width" />
            <text v-else-if="s.type === 'text'" :x="(s.x || 0) * pg.vbW" :y="(s.y || 0) * pg.vbH"
                  :fill="s.color" :font-size="Math.max(s.width * 6, 18)" font-weight="600">{{ s.text }}</text>
          </template>
          <!-- 正在绘制的预览 -->
          <template v-if="current && current.page === i">
            <polyline v-if="current.type === 'pen' || current.type === 'highlight'" :points="poly(current, pg)"
                      :fill="'none'" :stroke="current.color"
                      :stroke-width="current.type === 'highlight' ? Math.max(current.width * 3, 12) : current.width"
                      :stroke-opacity="current.type === 'highlight' ? 0.3 : 1" stroke-linecap="round" stroke-linejoin="round" />
            <line v-else :x1="pt(current, pg, 0, 0)" :y1="pt(current, pg, 0, 1)"
                  :x2="pt(current, pg, 1, 0)" :y2="pt(current, pg, 1, 1)" :stroke="current.color"
                  :stroke-width="current.width" stroke-linecap="round" />
            <rect v-if="current.type === 'rect'" :x="box(current, pg).x" :y="box(current, pg).y"
                  :width="box(current, pg).w" :height="box(current, pg).h" fill="none" :stroke="current.color" :stroke-width="current.width" />
            <ellipse v-else-if="current.type === 'ellipse'" :cx="box(current, pg).x + box(current, pg).w / 2"
                     :cy="box(current, pg).y + box(current, pg).h / 2" :rx="box(current, pg).w / 2" :ry="box(current, pg).h / 2"
                     fill="none" :stroke="current.color" :stroke-width="current.width" />
          </template>
        </svg>
      </div>
      <el-empty v-if="!loading && !pages.length" description="无可批注的图片 / PDF 附件" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import request from '../utils/request'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

const props = defineProps({
  hwId: { type: [Number, String], required: true },
  subId: { type: [Number, String], required: true },
  attachment: { type: Object, default: null },   // {filename, ext, size}
  readonly: { type: Boolean, default: false },
})

const TOOLS = [
  { key: 'pen', label: '画笔', ico: '✎' },
  { key: 'highlight', label: '高亮', ico: '▨' },
  { key: 'line', label: '直线', ico: '╱' },
  { key: 'arrow', label: '箭头', ico: '➤' },
  { key: 'rect', label: '矩形', ico: '▭' },
  { key: 'ellipse', label: '椭圆', ico: '◯' },
  { key: 'text', label: '文字', ico: 'T' },
]
const TWO_POINT = new Set(['line', 'arrow', 'rect', 'ellipse'])
const uid = 'a' + Math.random().toString(36).slice(2, 8)

const loading = ref(false)
const saving = ref(false)
const pages = ref([])          // [{url, vbW, vbH}]
const shapes = ref([])         // [{id,type,page,points|x,y,color,width,text}]
const tool = ref('pen')
const color = ref('#ef4444')
const width = ref(3)
const current = ref(null)      // 正在绘制的图形
const currentColor = computed(() => color.value)

const inlineUrl = () => `/api/homeworks/${props.hwId}/attachment?submission_id=${props.subId}&inline=1`
const isImage = (ext) => ['.png', '.jpg', '.jpeg', '.gif', '.webp'].includes((ext || '').toLowerCase())
const isPdf = (ext) => (ext || '').toLowerCase() === '.pdf'

const pickTool = (k) => { tool.value = k }
const shapesOf = (page) => shapes.value.filter(s => (s.page || 0) === page)

// 坐标：归一化(0~1) × viewBox 尺寸
const pt = (s, pg, idx, axis) => {
  const p = (s.points && s.points[idx]) || [0, 0]
  return axis === 0 ? p[0] * pg.vbW : p[1] * pg.vbH
}
const poly = (s, pg) => (s.points || []).map(p => `${(p[0] * pg.vbW).toFixed(1)},${(p[1] * pg.vbH).toFixed(1)}`).join(' ')
const box = (s, pg) => {
  const a = (s.points && s.points[0]) || [0, 0]
  const b = (s.points && s.points[1]) || a
  const x = Math.min(a[0], b[0]) * pg.vbW, y = Math.min(a[1], b[1]) * pg.vbH
  const w = Math.abs(a[0] - b[0]) * pg.vbW, h = Math.abs(a[1] - b[1]) * pg.vbH
  return { x, y, w, h }
}

const norm = (e) => {
  const r = e.currentTarget.getBoundingClientRect()
  const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
  const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))
  return [Math.round(x * 1e4) / 1e4, Math.round(y * 1e4) / 1e4]
}

const onDown = async (e, page) => {
  if (props.readonly) return
  e.preventDefault()
  const [x, y] = norm(e)
  if (tool.value === 'text') {
    try {
      const { value } = await ElMessageBox.prompt('输入批注文字', '文字批注', {
        confirmButtonText: '添加', cancelButtonText: '取消', inputValidator: v => (v && v.trim() ? true : '不能为空'),
      })
      shapes.value.push({ id: Date.now() + '' + Math.floor(Math.random() * 99), type: 'text',
        page, x, y, color: color.value, width: width.value, text: value.trim() })
    } catch (_) { /* 取消 */ }
    return
  }
  current.value = { id: Date.now() + '' + Math.floor(Math.random() * 99), type: tool.value,
    page, color: color.value, width: width.value, points: [[x, y], [x, y]] }
}
const onMove = (e, page) => {
  if (!current.value || current.value.page !== page) return
  const [x, y] = norm(e)
  if (TWO_POINT.has(current.value.type)) {
    current.value.points[1] = [x, y]
  } else { // pen / highlight：追加点
    current.value.points.push([x, y])
  }
}
const onUp = () => {
  if (!current.value) return
  const s = current.value
  if (TWO_POINT.has(s.type)) {
    // 起终点几乎重合则丢弃
    const [a, b] = s.points
    if (Math.abs(a[0] - b[0]) < 0.005 && Math.abs(a[1] - b[1]) < 0.005) { current.value = null; return }
  } else if (s.points.length < 2) { current.value = null; return }
  shapes.value.push(s)
  current.value = null
}

const undo = () => { shapes.value.pop() }
const clearAll = () => { shapes.value = [] }

const loadShapes = async () => {
  try {
    const res = await request.get(`/api/homeworks/${props.hwId}/annotation`,
      { params: { submission_id: props.subId } })
    shapes.value = (res.data.shapes || []).map((s, i) => ({ ...s, id: s.id || ('ld' + i) }))
  } catch (_) { shapes.value = [] }
}

const save = async () => {
  saving.value = true
  try {
    const payload = shapes.value.map(s => {
      const o = { id: s.id, type: s.type, page: s.page || 0, color: s.color, width: s.width }
      if (s.points) o.points = s.points
      if (s.x != null) { o.x = s.x; o.y = s.y }
      if (s.type === 'text') o.text = s.text
      return o
    })
    const res = await request.post(`/api/homeworks/${props.hwId}/annotation`,
      { submission_id: props.subId, shapes: payload })
    shapes.value = (res.data.shapes || []).map((s, i) => ({ ...s, id: s.id || ('sv' + i) }))
    ElMessage.success('批注已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const loadImagePage = (url) => new Promise((resolve) => {
  const img = new Image()
  img.onload = () => resolve({ url, vbW: img.naturalWidth || 800, vbH: img.naturalHeight || 600 })
  img.onerror = () => resolve({ url, vbW: 800, vbH: 600 })
  img.src = url
})

const renderPdf = async () => {
  const res = await request.get(`/api/homeworks/${props.hwId}/attachment`,
    { params: { submission_id: props.subId, inline: 1 }, responseType: 'arraybuffer' })
  const doc = await pdfjsLib.getDocument({ data: new Uint8Array(res.data) }).promise
  const out = []
  for (let p = 1; p <= doc.numPages; p++) {
    const page = await doc.getPage(p)
    const vp = page.getViewport({ scale: 2 })
    const canvas = document.createElement('canvas')
    canvas.width = vp.width; canvas.height = vp.height
    const ctx = canvas.getContext('2d')
    await page.render({ canvasContext: ctx, viewport: vp }).promise
    out.push({ url: canvas.toDataURL('image/png'), vbW: vp.width, vbH: vp.height })
  }
  pages.value = out
}

const initPages = async () => {
  const ext = props.attachment?.ext
  if (isImage(ext)) {
    pages.value = [await loadImagePage(inlineUrl())]
  } else if (isPdf(ext)) {
    await renderPdf()
  } else {
    pages.value = []
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await initPages()
    await loadShapes()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.ann-root { display: flex; flex-direction: column; gap: 10px; }
.ann-toolbar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  padding: 8px 10px; background: #f8fafc; border-radius: 8px; }
.tool-group { display: flex; gap: 6px; align-items: center; }
.tool-ico { font-size: 15px; line-height: 1; }
.color-pick { width: 30px; height: 26px; border: none; background: none; cursor: pointer; padding: 0; }
.ann-readonly-tip { font-size: 12px; color: #909399; }
.ann-pages { max-height: 60vh; overflow: auto; display: flex; flex-direction: column; gap: 14px;
  background: #f1f5f9; border-radius: 8px; padding: 12px; }
.ann-page { position: relative; width: 100%; line-height: 0; }
.ann-img { width: 100%; height: auto; border-radius: 4px; user-select: none; }
.ann-svg { position: absolute; inset: 0; width: 100%; height: 100%;
  touch-action: none; cursor: crosshair; }
.ann-readonly .ann-svg { cursor: default; }
</style>
