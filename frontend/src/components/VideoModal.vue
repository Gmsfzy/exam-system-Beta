<template>
  <el-dialog
    v-model="visible"
    width="800px"
    :close-on-click-modal="false"
    :show-close="false"
    class="video-modal"
  >
    <div class="video-container">
      <div class="video-player" ref="playerRef">
        <canvas ref="canvasRef" class="video-canvas"></canvas>
        <div class="video-overlay" v-if="!isPlaying">
          <button class="play-button" @click="togglePlay">
            <el-icon :size="44"><VideoPlay /></el-icon>
          </button>
        </div>
        <button class="close-btn" @click="close">
          <el-icon :size="18"><Close /></el-icon>
        </button>
        <div class="brand-mark">智汇学场 · Smart Learning Arena</div>
      </div>
      <div class="video-controls">
        <div class="controls-left">
          <button class="control-btn" @click="togglePlay">
            <el-icon :size="18"><VideoPause v-if="isPlaying" /><VideoPlay v-else /></el-icon>
          </button>
          <button class="control-btn" @click="prevSlide" title="上一段">
            <el-icon :size="18"><ArrowLeftBold /></el-icon>
          </button>
          <button class="control-btn" @click="nextSlide" title="下一段">
            <el-icon :size="18"><ArrowRightBold /></el-icon>
          </button>
          <span class="time-display">{{ formatTime(currentTime) }} / {{ formatTime(totalDuration) }}</span>
        </div>
        <div class="controls-center">
          <div class="chapter-dots">
            <span v-for="(s, i) in slides" :key="i"
                  class="dot" :class="{ active: i === currentSlide }"
                  :title="s.name" @click="jumpTo(i)"></span>
          </div>
          <div class="progress-bar" @click="seek">
            <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
            <div class="progress-dot" :style="{ left: progressPercent + '%' }"></div>
          </div>
        </div>
        <div class="controls-right">
          <button class="control-btn" @click="toggleFullscreen" title="全屏">
            <el-icon :size="18"><FullScreen /></el-icon>
          </button>
        </div>
      </div>
    </div>
    <template #footer>
      <div class="video-footer">
        <h4>智汇学场 · Smart Learning Arena</h4>
        <p>AI 驱动，融合考试 · 作业 · 竞赛 · 悬赏 · 自学的一体化智能学习平台</p>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  VideoPlay, VideoPause, ArrowLeftBold, ArrowRightBold, FullScreen, Close,
} from '@element-plus/icons-vue'

const props = defineProps({ show: { type: Boolean, default: false } })
const emit = defineEmits(['close'])

const visible = computed({
  get: () => props.show,
  set: (val) => { if (!val) emit('close', false) },
})

const W = 800
const H = 450
const canvasRef = ref(null)
const playerRef = ref(null)
const isPlaying = ref(false)
const currentSlide = ref(0)
const currentTime = ref(0)
const isFullscreen = ref(false)
const animationDuration = 620

// ── 演示时间线：开场品牌 → 系统亮点 → 四大模块 → 闭环总结 ──
const slides = [
  {
    name: '品牌开场', scene: 'brand', dur: 4600,
    gradient: ['#0f172a', '#312e81', '#4f46e5'],
  },
  {
    name: '系统亮点', scene: 'highlight', dur: 6200,
    gradient: ['#1e1b4b', '#4f46e5', '#0891b2'],
  },
  {
    name: '在线考试', scene: 'exam', dur: 5600,
    title: '在线考试', desc: '公共题库 · AI 组卷 · 智能批改 · 防作弊',
    features: ['公共题库跨师共享', 'AI 智能组卷', '主客观题 AI 语义评分', '切屏检测防作弊', '邀请码一键加入'],
    gradient: ['#6366f1', '#8b5cf6', '#d946ef'],
  },
  {
    name: '答题竞赛', scene: 'competition', dur: 5600,
    title: '答题竞赛', desc: '实时 PK · 段位排位 · 赛季证书 · 邀请门禁',
    features: ['1v1 实时 PK', '段位积分青铜→王者', '赛季分等级证书', '邀请码门禁赛', '系列赛 + 对战回放'],
    gradient: ['#f59e0b', '#f97316', '#ef4444'],
  },
  {
    name: '征集悬赏', scene: 'bounty', dur: 5600,
    title: '征集悬赏', desc: '积分激励 · 众创题库 · 采纳即奖',
    features: ['悬赏发布激励投稿', '题目征集与审核', '众创题库持续积累', '积分排行榜', '采纳即获积分'],
    gradient: ['#22c55e', '#10b981', '#06b6d4'],
  },
  {
    name: '自主学习', scene: 'study', dur: 5600,
    title: '自主学习', desc: '错题本 · 刷题计划 · 学习报告 · AI 答疑',
    features: ['智能错题本自动收录', '自由刷题模式', '学习计划进度追踪', '每日学习报告', 'AI 智能答疑'],
    gradient: ['#ec4899', '#f43f5e', '#ef4444'],
  },
  {
    name: '作业练习', scene: 'homework', dur: 5600,
    title: '作业练习', desc: '题集/开放 · AI 讲评 · 互评量规 · 订正展示',
    features: ['题集式 / 开放式双形态', 'AI 初评 + 班级讲评', '匿名互评与评分量规', '查重监测预警', '退回订正 · 展示墙'],
    gradient: ['#0f766e', '#14b8a6', '#06b6d4'],
  },
  {
    name: '闭环总结', scene: 'summary', dur: 5200,
    gradient: ['#0f172a', '#4f46e5', '#06b6d4'],
  },
]

const starts = (() => {
  let acc = 0
  return slides.map(s => { const v = acc; acc += s.dur; return v })
})()
const totalDuration = computed(() => starts[starts.length - 1] + slides[slides.length - 1].dur)
const progressPercent = computed(() => (currentTime.value / totalDuration.value) * 100)

const HIGHLIGHTS = [
  { emoji: '🧩', title: '五位一体', sub: '考试·作业·竞赛·悬赏·自学' },
  { emoji: '🤖', title: 'AI 全流程', sub: '组卷·批改·答疑·推荐' },
  { emoji: '⚔️', title: '实时竞技', sub: '1v1 PK·段位排位' },
  { emoji: '🏅', title: '赛季证书', sub: '金银铜·分档颁发' },
  { emoji: '🔐', title: '邀请门禁', sub: '班级化竞赛·凭码入场' },
  { emoji: '🔄', title: '错题闭环', sub: '自动收录·智能攻克' },
]

let animationFrameId = null
let lastTimestamp = 0

function formatTime(ms) {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, '0')}`
}

// ========== 缓动与绘制工具 ==========
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v))
const easeOut = t => 1 - Math.pow(1 - clamp(t), 3)
const easeIn = t => Math.pow(clamp(t), 3)

function drawGradient(ctx, colors, w, h, t) {
  const g = ctx.createLinearGradient(0, 0, w, h)
  colors.forEach((c, i) => g.addColorStop(i / (colors.length - 1), c))
  ctx.fillStyle = g
  ctx.fillRect(0, 0, w, h)
}

function drawOrbs(ctx, w, h, t) {
  // 背景漂浮光斑（连续动画，不随切片重置）
  const orbs = [
    { r: 140, c: 'rgba(255,255,255,0.10)', x: 0.18, y: 0.25, s: 0.00022 },
    { r: 90, c: 'rgba(255,255,255,0.08)', x: 0.82, y: 0.7, s: -0.0003 },
    { r: 60, c: 'rgba(255,255,255,0.10)', x: 0.66, y: 0.2, s: 0.0004 },
  ]
  orbs.forEach(o => {
    const cx = o.x * w + Math.sin(t * o.s) * 40
    const cy = o.y * h + Math.cos(t * o.s * 1.3) * 30
    ctx.beginPath()
    ctx.arc(cx, cy, o.r, 0, Math.PI * 2)
    ctx.fillStyle = o.c
    ctx.fill()
  })
}

function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

function setShadow(ctx, color, blur, ox, oy) {
  ctx.shadowColor = color || 'rgba(0,0,0,0.25)'
  ctx.shadowBlur = blur || 12
  ctx.shadowOffsetX = ox || 0
  ctx.shadowOffsetY = oy || 4
}
function clearShadow(ctx) {
  ctx.shadowColor = 'transparent'
  ctx.shadowBlur = 0
  ctx.shadowOffsetX = 0
  ctx.shadowOffsetY = 0
}

function drawGlassCard(ctx, x, y, w, h, r, opts) {
  opts = opts || {}
  const fill = opts.fill || 'rgba(255,255,255,0.95)'
  ctx.save()
  setShadow(ctx, opts.shadowColor || 'rgba(0,0,0,0.25)', opts.shadowBlur == null ? 18 : opts.shadowBlur, 0, opts.shadowY == null ? 6 : opts.shadowY)
  roundRect(ctx, x, y, w, h, r)
  ctx.fillStyle = fill
  ctx.fill()
  clearShadow(ctx)
  if (opts.stroke) { ctx.strokeStyle = opts.stroke; ctx.lineWidth = 1; ctx.stroke() }
  const hl = ctx.createLinearGradient(x, y, x, y + Math.min(h * 0.5, 40))
  hl.addColorStop(0, 'rgba(255,255,255,0.5)')
  hl.addColorStop(1, 'rgba(255,255,255,0)')
  roundRect(ctx, x, y, w, h, r)
  ctx.fillStyle = hl
  ctx.fill()
  ctx.restore()
}

function drawGradientBar(ctx, x, y, w, h, r, colors, shadowColor) {
  ctx.save()
  if (shadowColor) setShadow(ctx, shadowColor, 8, 0, 2)
  const g = ctx.createLinearGradient(x, y, x + w, y)
  colors.forEach((c, i) => g.addColorStop(i / (colors.length - 1), c))
  roundRect(ctx, x, y, w, h, r)
  ctx.fillStyle = g
  ctx.fill()
  clearShadow(ctx)
  ctx.restore()
}

function drawGradientCircle(ctx, cx, cy, radius, colors, shadowColor) {
  ctx.save()
  if (shadowColor) setShadow(ctx, shadowColor, 14, 0, 3)
  const g = ctx.createRadialGradient(cx - radius * 0.3, cy - radius * 0.3, radius * 0.1, cx, cy, radius)
  colors.forEach((c, i) => g.addColorStop(i / (colors.length - 1), c))
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.fillStyle = g
  ctx.fill()
  clearShadow(ctx)
  ctx.restore()
}

function drawGlowRing(ctx, cx, cy, radius, colors, lineWidth) {
  ctx.save()
  setShadow(ctx, colors[colors.length - 1], 12, 0, 0)
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.strokeStyle = colors[0]
  ctx.lineWidth = lineWidth || 2
  ctx.stroke()
  clearShadow(ctx)
  ctx.restore()
}

function drawGradText(ctx, text, x, y, size, weight, colors, align, baseline) {
  ctx.save()
  ctx.font = `${weight || 700} ${size}px -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif`
  ctx.textAlign = align || 'left'
  ctx.textBaseline = baseline || 'top'
  const m = ctx.measureText(text)
  const sx = align === 'center' ? x - m.width / 2 : align === 'right' ? x - m.width : x
  const g = ctx.createLinearGradient(sx, y, sx + m.width, y)
  colors.forEach((c, i) => g.addColorStop(i / (colors.length - 1), c))
  ctx.fillStyle = g
  ctx.fillText(text, x, y)
  ctx.restore()
}

function drawText(ctx, text, x, y, size, weight, opacity, color, align, baseline) {
  ctx.save()
  ctx.globalAlpha = opacity == null ? 1 : opacity
  ctx.fillStyle = color || '#fff'
  ctx.font = `${weight || 400} ${size}px -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif`
  ctx.textAlign = align || 'center'
  ctx.textBaseline = baseline || 'middle'
  ctx.fillText(text, x, y)
  ctx.restore()
}

// ========== 场景 0：品牌开场 ==========
function drawBrandScene(ctx, w, h, p, t) {
  const cx = w / 2
  const cy = h / 2 - 18
  const e = easeOut(p * 1.6)

  // 旋转环
  ctx.save()
  ctx.globalAlpha = 0.5 * clamp(p * 2)
  const ringR = 150
  ctx.translate(cx, cy)
  ctx.rotate(t * 0.0003)
  ctx.strokeStyle = 'rgba(255,255,255,0.25)'
  ctx.lineWidth = 2
  ctx.setLineDash([4, 10])
  ctx.beginPath()
  ctx.arc(0, 0, ringR, 0, Math.PI * 2)
  ctx.stroke()
  ctx.restore()

  // 五模块光点（均匀环排）
  const mods = [
    { emoji: '📝', a: -Math.PI / 2, c: ['#a5b4fc', '#6366f1'] },
    { emoji: '🏆', a: -Math.PI / 2 + 2 * Math.PI / 5, c: ['#fdba74', '#f97316'] },
    { emoji: '💰', a: -Math.PI / 2 + 4 * Math.PI / 5, c: ['#6ee7b7', '#10b981'] },
    { emoji: '📚', a: -Math.PI / 2 + 6 * Math.PI / 5, c: ['#f9a8d4', '#ec4899'] },
    { emoji: '📒', a: -Math.PI / 2 + 8 * Math.PI / 5, c: ['#5eead4', '#14b8a6'] },
  ]
  mods.forEach((m, i) => {
    const appear = easeOut((p - 0.25 - i * 0.08) * 4)
    if (appear <= 0) return
    const ang = m.a + t * 0.0003
    const mx = cx + ringR * Math.cos(ang)
    const my = cy + ringR * Math.sin(ang)
    ctx.save()
    ctx.globalAlpha = appear
    drawGradientCircle(ctx, mx, my, 20 * appear, m.c.concat(m.c[m.c.length - 1]), m.c[1] + '88')
    ctx.fillStyle = '#fff'
    ctx.font = '18px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(m.emoji, mx, my + 1)
    ctx.restore()
  })

  // 中心标题
  ctx.save()
  ctx.globalAlpha = e
  ctx.translate(cx, cy)
  ctx.scale(0.85 + 0.15 * e, 0.85 + 0.15 * e)
  drawGradText(ctx, '智汇学场', 0, -18, 44, 800, ['#ffffff', '#e0e7ff', '#a5f3fc'], 'center', 'middle')
  ctx.restore()
  drawText(ctx, 'Smart Learning Arena', cx, cy + 24, 15, 600, e, 'rgba(224,231,255,0.9)')
  const sub = easeOut((p - 0.35) * 2.2)
  drawText(ctx, 'AI 驱动 · 一体化智能学习平台', cx, cy + 56, 16, 500, sub, 'rgba(255,255,255,0.92)')
  drawText(ctx, '考试 · 作业 · 竞赛 · 悬赏 · 自学  五大场域环环相扣', cx, cy + 82, 12.5, 400, sub, 'rgba(226,232,240,0.75)')
}

// ========== 场景 1：系统亮点 ==========
function drawHighlightScene(ctx, w, h, p) {
  drawText(ctx, '系统亮点', w / 2, 40, 26, 800, easeOut(p * 3), '#ffffff')
  drawText(ctx, 'Why 智汇学场 · 六大核心能力', w / 2, 66, 13, 400, easeOut(p * 3), 'rgba(224,231,255,0.85)')

  const cols = 3, rows = 2
  const gx = 46, gy = 96
  const cw = (w - gx * 2 - 20 * (cols - 1)) / cols
  const ch = 148
  HIGHLIGHTS.forEach((it, i) => {
    const cxi = i % cols, cyi = Math.floor(i / cols)
    const x = gx + cxi * (cw + 20)
    const y = gy + cyi * (ch + 22)
    const appear = easeOut((p - 0.12 - i * 0.09) * 5)
    if (appear <= 0) return
    ctx.save()
    ctx.globalAlpha = appear
    const dy = (1 - appear) * 18
    drawGlassCard(ctx, x, y + dy, cw, ch, 16, { fill: 'rgba(255,255,255,0.94)', shadowColor: 'rgba(49,46,129,0.4)', shadowBlur: 16, shadowY: 6 })
    drawGradientCircle(ctx, x + 34, y + dy + 42, 22, ['#c7d2fe', '#818cf8', '#6366f1'], 'rgba(99,102,241,0.4)')
    ctx.font = '22px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(it.emoji, x + 34, y + dy + 43)
    drawText(ctx, it.title, x + 12, y + dy + 92, 17, 800, appear, '#1e293b', 'left', 'alphabetic')
    drawText(ctx, it.sub, x + 12, y + dy + 118, 12, 400, appear, '#64748b', 'left', 'alphabetic')
    ctx.restore()
  })
}

// ========== 场景 2：在线考试 ==========
function drawExamScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade
  const cardX = 40 + slide * 20, cardY = 54, cardW = 340, cardH = 300
  drawGlassCard(ctx, cardX, cardY, cardW, cardH, 16, { shadowColor: 'rgba(79,70,229,0.35)' })
  ctx.fillStyle = '#f1f5f9'
  roundRect(ctx, cardX, cardY, cardW, 40, 16); ctx.fill()
  roundRect(ctx, cardX, cardY + 24, cardW, 16, 0); ctx.fill()
  ctx.strokeStyle = 'rgba(148,163,184,0.25)'; ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(cardX + 14, cardY + 40); ctx.lineTo(cardX + cardW - 14, cardY + 40); ctx.stroke()
  drawGradText(ctx, '📝 高等数学 · 期中考试', cardX + 14, cardY + 12, 13, 600, ['#4f46e5', '#8b5cf6'])
  ctx.save()
  setShadow(ctx, 'rgba(220,38,38,0.4)', 6, 0, 0)
  ctx.fillStyle = '#dc2626'; ctx.font = '700 12px monospace'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle'
  ctx.fillText('42:38', cardX + cardW - 14, cardY + 20); clearShadow(ctx); ctx.restore()

  ctx.fillStyle = '#334155'; ctx.font = '600 13px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'
  ctx.fillText('1. 设 f(x) = x² - 2x + 1，求 f(3)：', cardX + 14, cardY + 66)
  const opts = [{ l: 'A', t: '2', s: false }, { l: 'B', t: '4', s: true }, { l: 'C', t: '6', s: false }, { l: 'D', t: '8', s: false }]
  opts.forEach((o, i) => {
    const oy = cardY + 86 + i * 28
    if (o.s) drawGradientBar(ctx, cardX + 14, oy, 312, 22, 6, ['#ede9fe', '#ddd6fe', '#c4b5fd'], 'rgba(139,92,246,0.35)')
    else { roundRect(ctx, cardX + 14, oy, 312, 22, 6); ctx.fillStyle = '#f8fafc'; ctx.fill(); ctx.strokeStyle = '#e2e8f0'; ctx.stroke() }
    ctx.fillStyle = o.s ? '#6d28d9' : '#64748b'; ctx.font = '700 12px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
    ctx.fillText(o.l + '.', cardX + 22, oy + 11)
    ctx.fillStyle = o.s ? '#6d28d9' : '#475569'; ctx.font = '500 12px sans-serif'; ctx.fillText(o.t, cardX + 44, oy + 11)
  })
  const statusY = cardY + 208
  ctx.save(); setShadow(ctx, 'rgba(180,83,9,0.2)', 8, 0, 2)
  roundRect(ctx, cardX + 14, statusY, 312, 76, 10); ctx.fillStyle = '#fef3c7'; ctx.fill(); clearShadow(ctx); ctx.restore()
  ctx.fillStyle = '#b45309'; ctx.font = '700 12px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top'
  ctx.fillText('✅ AI 自动批改', cardX + 24, statusY + 12)
  ctx.fillStyle = '#92400e'; ctx.font = '400 11px sans-serif'
  ctx.fillText('答案：B（正确） · 解析：f(3)=9-6+1=4', cardX + 24, statusY + 32)
  ctx.fillText('语义评分：主观题按要点智能给分', cardX + 24, statusY + 50)
  ctx.save(); setShadow(ctx, 'rgba(220,38,38,0.45)', 6, 0, 0)
  ctx.fillStyle = '#dc2626'; ctx.font = '700 11px sans-serif'; ctx.textAlign = 'right'; ctx.textBaseline = 'top'
  ctx.fillText('⚠ 切屏 2 次', cardX + cardW - 14, statusY + 12); clearShadow(ctx); ctx.restore()

  const floatX = 420 - slide * 10
  drawGlassCard(ctx, floatX, cardY + 16, 140, 52, 10, { shadowColor: 'rgba(99,102,241,0.35)', shadowBlur: 14, shadowY: 5 })
  ctx.fillStyle = '#475569'; ctx.font = '400 10px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top'
  ctx.fillText('📚 公共题库', floatX + 10, cardY + 26)
  drawGradText(ctx, '1,236 题', floatX + 10, cardY + 42, 15, 700, ['#6366f1', '#8b5cf6'])
  drawGlassCard(ctx, floatX, cardY + 78, 140, 52, 10, { shadowColor: 'rgba(99,102,241,0.35)', shadowBlur: 14, shadowY: 5 })
  ctx.fillStyle = '#475569'; ctx.font = '400 10px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top'
  ctx.fillText('🎯 AI 智能组卷', floatX + 10, cardY + 88)
  drawGradText(ctx, '5 秒生成', floatX + 10, cardY + 104, 15, 700, ['#06b6d4', '#6366f1'])
  ctx.restore()
}

// ========== 场景 3：答题竞赛 ==========
function drawCompetitionScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade
  const lx = 40 + slide * 20, ly = 54
  drawGlassCard(ctx, lx, ly, 300, 250, 14, { shadowColor: 'rgba(249,115,22,0.3)' })
  drawGradText(ctx, '🏆 实时排行榜', lx + 14, ly + 14, 14, 700, ['#ea580c', '#f97316', '#ef4444'])
  const players = [
    { r: 1, n: '智汇王者', s: 2850 }, { r: 2, n: '学霸小李', s: 2610, self: true },
    { r: 3, n: '努力王', s: 2480 }, { r: 4, n: '进击的小明', s: 2320 }, { r: 5, n: '稳稳上分', s: 2150 },
  ]
  const bars = [
    ['#fde68a', '#facc15', '#f59e0b'], ['#cbd5e1', '#e2e8f0', '#f1f5f9'],
    ['#fbbf24', '#d97706', '#92400e'], ['#fed7aa', '#fb923c', '#f97316'], ['#fed7aa', '#fdba74', '#fb923c'],
  ]
  players.forEach((p, i) => {
    const py = ly + 46 + i * 34
    drawGradientBar(ctx, lx + 14, py, Math.min(258, 220 * (p.s / 2850)), 24, 6, bars[i], i === 0 ? 'rgba(245,158,11,0.3)' : null)
    ctx.fillStyle = i === 0 ? '#713f12' : '#334155'; ctx.font = '700 11px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
    ctx.fillText(p.r + ' ' + p.n + (p.self ? ' (我)' : ''), lx + 22, py + 12)
    ctx.fillStyle = '#1e293b'; ctx.font = '700 11px monospace'; ctx.textAlign = 'right'; ctx.fillText(p.s, lx + 288, py + 12)
  })

  const px = 360 - slide * 10, py = 78
  drawGlassCard(ctx, px, py, 170, 120, 14, { shadowColor: 'rgba(249,115,22,0.3)', shadowY: 4 })
  drawGradText(ctx, '⚔ 1v1 实时 PK', px + 25, py + 12, 11, 700, ['#ea580c', '#f97316'])
  drawGradientCircle(ctx, px + 42, py + 62, 22, ['#60a5fa', '#3b82f6', '#1d4ed8'], 'rgba(59,130,246,0.4)')
  ctx.fillStyle = '#fff'; ctx.font = '700 14px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('A', px + 42, py + 62)
  drawGradientCircle(ctx, px + 128, py + 62, 22, ['#fca5a5', '#ef4444', '#b91c1c'], 'rgba(239,68,68,0.4)')
  ctx.fillStyle = '#fff'; ctx.fillText('B', px + 128, py + 62)
  ctx.save(); setShadow(ctx, 'rgba(249,115,22,0.45)', 8, 0, 0)
  drawGradText(ctx, 'VS', px + 85, py + 52, 20, 800, ['#ea580c', '#f97316', '#ef4444'], 'center', 'alphabetic')
  clearShadow(ctx); ctx.restore()
  ctx.fillStyle = '#1e293b'; ctx.font = '600 10px sans-serif'; ctx.textBaseline = 'top'
  ctx.textAlign = 'center'; ctx.fillText('青铜 III', px + 42, py + 88); ctx.fillText('白银 I', px + 128, py + 88)

  // 段位阶梯
  const tiers = [['青铜', '#b08d57'], ['白银', '#a8b4c4'], ['黄金', '#f0c14b'], ['铂金', '#7fd8d8'], ['钻石', '#7db9f5'], ['王者', '#ff7a45']]
  const by = py + 132
  tiers.forEach((t, i) => {
    const tx = 360 + i * 29
    ctx.save(); setShadow(ctx, 'rgba(0,0,0,0.18)', 6, 0, 2)
    drawGradientCircle(ctx, tx + 10, by + 10, 11, [t[1], t[1]], t[1] + '77'); clearShadow(ctx); ctx.restore()
    ctx.fillStyle = '#fff'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(['🥉', '🥈', '🥇', '💎', '💠', '👑'][i], tx + 10, by + 11)
  })

  // 新增亮点角标：赛季证书 / 邀请门禁 / 系列赛（排在左侧排行榜卡片下方）
  const chips = [['🏅 赛季证书', '#b45309'], ['🔐 邀请门禁', '#4338ca'], ['🔁 系列赛回放', '#be185d']]
  chips.forEach((c, i) => {
    const bx = 40 + i * 100, bby = 314
    ctx.save(); setShadow(ctx, c[1] + '55', 6, 0, 2)
    roundRect(ctx, bx, bby, 92, 26, 13); ctx.fillStyle = 'rgba(255,255,255,0.95)'; ctx.fill(); clearShadow(ctx); ctx.restore()
    ctx.fillStyle = c[1]; ctx.font = '700 11px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(c[0], bx + 46, bby + 13)
  })
  ctx.restore()
}

// ========== 场景 4：征集悬赏 ==========
function drawBountyScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade
  const bx = 40 + slide * 20, by = 54
  const bounties = [
    { t: 'Python 面向对象编程', p: 500, s: '进行中', c: '#22c55e', g: ['#22c55e', '#10b981'] },
    { t: '数据结构：链表与树', p: 800, s: '热门', c: '#ef4444', g: ['#fb7185', '#ef4444', '#b91c1c'] },
    { t: '机器学习基础概念', p: 1200, s: '新发布', c: '#3b82f6', g: ['#60a5fa', '#3b82f6', '#1d4ed8'] },
  ]
  bounties.forEach((b, i) => {
    const cy = by + i * 82
    drawGlassCard(ctx, bx, cy, 310, 72, 14, { shadowColor: b.c + '66', shadowBlur: 14 })
    ctx.save(); setShadow(ctx, b.c + '88', 10, 0, 2)
    drawGradText(ctx, String(b.p), bx + 214, cy + 8, 28, 800, b.g, 'left', 'alphabetic'); clearShadow(ctx); ctx.restore()
    ctx.fillStyle = b.c; ctx.font = '600 10px sans-serif'; ctx.textAlign = 'right'; ctx.textBaseline = 'top'
    ctx.fillText('积分', bx + 294, cy + 42)
    ctx.fillStyle = '#0f172a'; ctx.font = '700 14px sans-serif'; ctx.textAlign = 'left'
    ctx.fillText('📌 ' + b.t, bx + 16, cy + 16)
    ctx.save(); setShadow(ctx, b.c + '88', 6, 0, 1)
    drawGradientBar(ctx, bx + 16, cy + 42, 60, 20, 4, [b.c, b.c], null); clearShadow(ctx); ctx.restore()
    ctx.fillStyle = '#fff'; ctx.font = '600 10px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(b.s, bx + 46, cy + 52)
    ctx.fillStyle = '#64748b'; ctx.font = '400 11px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top'
    ctx.fillText('优质题目被采纳即获积分', bx + 86, cy + 46)
  })
  const fx = 370 - slide * 10, fy = 130
  drawGlassCard(ctx, fx - 10, fy - 30, 170, 150, 12, { shadowColor: 'rgba(16,185,129,0.3)', fill: 'rgba(255,255,255,0.9)' })
  drawGradText(ctx, '🔄 征集审核流程', fx + 12, fy - 20, 12, 700, ['#047857', '#10b981'], 'center')
  const flow = [
    { l: '发布', x: fx + 20, y: fy + 24, c: ['#4ade80', '#22c55e', '#15803d'] },
    { l: '投稿', x: fx + 75, y: fy + 24, c: ['#67e8f9', '#06b6d4', '#0e7490'] },
    { l: '采纳', x: fx + 130, y: fy + 24, c: ['#fcd34d', '#f59e0b', '#b45309'] },
  ]
  ctx.strokeStyle = 'rgba(16,185,129,0.5)'; ctx.lineWidth = 2
  ctx.beginPath(); ctx.moveTo(fx + 36, fy + 24); ctx.lineTo(fx + 59, fy + 24); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(fx + 91, fy + 24); ctx.lineTo(fx + 114, fy + 24); ctx.stroke()
  flow.forEach(n => {
    drawGradientCircle(ctx, n.x, n.y, 16, n.c, n.c[n.c.length - 1] + '99')
    ctx.fillStyle = '#fff'; ctx.font = '700 11px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(n.l, n.x, n.y)
  })
  ctx.fillStyle = '#047857'; ctx.font = '500 10px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'top'
  ctx.fillText('人人参与 · 众创题库', fx + 75, fy + 52)
  ctx.fillText('今日新增 128 题', fx + 75, fy + 74)
  ctx.fillText('累计采纳 3,456 题', fx + 75, fy + 92)
  ctx.restore()
}

// ========== 场景 5：自主学习 ==========
function drawStudyScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade
  const wx = 40 + slide * 20, wy = 54
  drawGlassCard(ctx, wx, wy, 280, 250, 14, { shadowColor: 'rgba(219,39,119,0.3)', shadowY: 5 })
  drawGradText(ctx, '📖 我的错题本', wx + 14, wy + 12, 13, 700, ['#db2777', '#ec4899'])
  ctx.fillStyle = '#64748b'; ctx.font = '500 10px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top'
  ctx.fillText('待攻克 7 · 已掌握 18', wx + 150, wy + 16)
  const wrongs = [
    { q: 'TCP 三次握手的第二次报文？', m: false }, { q: '数据库索引的底层数据结构？', m: false },
    { q: '进程与线程的本质区别？', m: true }, { q: 'HTTP 304 状态码含义？', m: false },
  ]
  wrongs.forEach((w2, i) => {
    const qy = wy + 40 + i * 42
    ctx.save(); setShadow(ctx, w2.m ? 'rgba(22,163,74,0.2)' : 'rgba(220,38,38,0.25)', 6, 0, 1)
    roundRect(ctx, wx + 14, qy, 252, 34, 8); ctx.fillStyle = w2.m ? '#dcfce7' : '#fef2f2'; ctx.fill()
    ctx.strokeStyle = w2.m ? '#86efac' : '#fecaca'; ctx.stroke(); clearShadow(ctx); ctx.restore()
    drawGradientBar(ctx, wx + 20, qy + 8, 42, 18, 4,
      w2.m ? ['#4ade80', '#22c55e', '#15803d'] : ['#fca5a5', '#ef4444', '#b91c1c'], w2.m ? null : 'rgba(239,68,68,0.4)')
    ctx.fillStyle = '#fff'; ctx.font = '700 9px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(w2.m ? '✓ 掌握' : '✗ 待攻', wx + 41, qy + 17)
    ctx.fillStyle = '#334155'; ctx.font = '400 11px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top'
    ctx.fillText(w2.q, wx + 70, qy + 11)
  })

  const rx = 340 - slide * 10, ry = 64, rad = 52
  const cx = rx + rad + 10, cy = ry + rad + 10
  drawGlassCard(ctx, rx, ry, (rad + 10) * 2, (rad + 10) * 2, 14, { shadowColor: 'rgba(219,39,119,0.25)', shadowBlur: 12 })
  const labels = ['基础', '进阶', '算法', '系统', '网络']
  const values = [0.8, 0.65, 0.45, 0.72, 0.55]
  ctx.strokeStyle = 'rgba(148,163,184,0.4)'; ctx.lineWidth = 1
  for (let ring = 1; ring <= 4; ring++) {
    ctx.beginPath(); const r = (rad * ring) / 4
    for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / 5; const px = cx + r * Math.cos(a), py = cy + r * Math.sin(a); i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py) }
    ctx.closePath(); ctx.stroke()
  }
  ctx.strokeStyle = 'rgba(148,163,184,0.3)'
  for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / 5; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + rad * Math.cos(a), cy + rad * Math.sin(a)); ctx.stroke() }
  ctx.save(); setShadow(ctx, 'rgba(236,72,153,0.4)', 8, 0, 0)
  const dg = ctx.createRadialGradient(cx, cy, rad * 0.2, cx, cy, rad)
  dg.addColorStop(0, 'rgba(236,72,153,0.15)'); dg.addColorStop(1, 'rgba(236,72,153,0.5)')
  ctx.fillStyle = dg; ctx.beginPath()
  for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / 5; const r = rad * values[i]; const px = cx + r * Math.cos(a), py = cy + r * Math.sin(a); i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py) }
  ctx.closePath(); ctx.fill(); ctx.strokeStyle = '#ec4899'; ctx.lineWidth = 2; ctx.stroke(); clearShadow(ctx); ctx.restore()
  for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / 5; const r = rad * values[i]; ctx.beginPath(); ctx.arc(cx + r * Math.cos(a), cy + r * Math.sin(a), 3, 0, Math.PI * 2); ctx.fillStyle = '#ec4899'; ctx.fill() }
  ctx.fillStyle = '#475569'; ctx.font = '600 10px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  labels.forEach((lb, i) => { const a = -Math.PI / 2 + i * 2 * Math.PI / 5; ctx.fillText(lb, cx + (rad + 12) * Math.cos(a), cy + (rad + 12) * Math.sin(a)) })

  const bx2 = rx, by2 = ry + (rad + 10) * 2 + 12
  drawGlassCard(ctx, bx2, by2, (rad + 10) * 2, 66, 14, { shadowColor: 'rgba(236,72,153,0.25)', shadowBlur: 12 })
  ctx.save(); setShadow(ctx, 'rgba(0,0,0,0.12)', 4, 0, 1)
  roundRect(ctx, bx2 + 10, by2 + 10, 108, 20, 6); ctx.fillStyle = '#e2e8f0'; ctx.fill(); clearShadow(ctx); ctx.restore()
  ctx.fillStyle = '#374151'; ctx.font = '400 10px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
  ctx.fillText('什么是哈希冲突？', bx2 + 16, by2 + 20)
  ctx.save(); setShadow(ctx, 'rgba(219,39,119,0.25)', 5, 0, 2)
  drawGradientBar(ctx, bx2 + 40, by2 + 34, 130, 26, 6, ['#fce7f3', '#fbcfe8'], null); clearShadow(ctx); ctx.restore()
  ctx.fillStyle = '#be185d'; ctx.font = '400 9.5px sans-serif'; ctx.textBaseline = 'middle'
  ctx.fillText('同一地址的映射…链地址法解决', bx2 + 48, by2 + 47)
  drawGradientCircle(ctx, bx2 + 28, by2 + 47, 9, ['#f9a8d4', '#ec4899', '#be185d'], 'rgba(236,72,153,0.5)')
  ctx.fillStyle = '#fff'; ctx.font = '700 9px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('AI', bx2 + 28, by2 + 48)
  ctx.restore()
}

// ========== 场景 5.5：作业练习 ==========
function drawHomeworkScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade
  const lx = 40 + slide * 20, ly = 54
  drawGlassCard(ctx, lx, ly, 330, 300, 16, { shadowColor: 'rgba(20,184,166,0.35)' })
  drawGradText(ctx, '📒 作业批改工作台', lx + 16, ly + 14, 15, 700, ['#0f766e', '#14b8a6'])
  ctx.fillStyle = '#64748b'; ctx.font = '500 11px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top'
  ctx.fillText('已交 48 · 待批改 12 · AI 已初评 30', lx + 16, ly + 40)
  const rows = [
    { n: '高数第一章 · 课后习题', s: '批改中', c: '#10b981', p: 0.75 },
    { n: '数据结构 · 链表编程题', s: '待复核', c: '#8b5cf6', p: 0.62 },
    { n: '大学英语 · 作文 Unit3', s: '互评中', c: '#f59e0b', p: 0.40 },
    { n: '线性代数 · 证明题', s: '已批改', c: '#06b6d4', p: 1.0 },
  ]
  rows.forEach((r, i) => {
    const ry = ly + 64 + i * 44
    ctx.fillStyle = '#334155'; ctx.font = '600 12px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
    ctx.fillText(r.n, lx + 16, ry + 6)
    roundRect(ctx, lx + 16, ry + 22, 200, 8, 4); ctx.fillStyle = '#e2e8f0'; ctx.fill()
    drawGradientBar(ctx, lx + 16, ry + 22, 200 * r.p, 8, 4, [r.c, r.c], null)
    ctx.save(); setShadow(ctx, r.c + '55', 5, 0, 1)
    roundRect(ctx, lx + 232, ry - 6, 84, 24, 12); ctx.fillStyle = r.c; ctx.fill(); clearShadow(ctx); ctx.restore()
    ctx.fillStyle = '#fff'; ctx.font = '700 11px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(r.s, lx + 274, ry + 6)
  })

  const rx = 396 - slide * 10, ry2 = 70
  drawGlassCard(ctx, rx, ry2, 300, 210, 14, { shadowColor: 'rgba(20,184,166,0.3)', shadowY: 5 })
  drawGradText(ctx, '🤖 AI 智能讲评', rx + 16, ry2 + 14, 13, 700, ['#0f766e', '#14b8a6'])
  const ccx = rx + 64, ccy = ry2 + 100, cr = 36
  ctx.strokeStyle = 'rgba(148,163,184,0.35)'; ctx.lineWidth = 9
  ctx.beginPath(); ctx.arc(ccx, ccy, cr, 0, Math.PI * 2); ctx.stroke()
  ctx.save(); setShadow(ctx, 'rgba(20,184,166,0.5)', 8, 0, 0)
  ctx.strokeStyle = '#14b8a6'; ctx.lineCap = 'round'
  ctx.beginPath(); ctx.arc(ccx, ccy, cr, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * 0.82); ctx.stroke(); clearShadow(ctx); ctx.restore()
  ctx.fillStyle = '#0f766e'; ctx.font = '800 18px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText('82%', ccx, ccy)
  ctx.fillStyle = '#64748b'; ctx.font = '500 10px sans-serif'; ctx.fillText('班级得分率', ccx, ccy + cr + 14)
  ctx.fillStyle = '#334155'; ctx.font = '600 12px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top'
  ctx.fillText('AI 讲评要点', rx + 132, ry2 + 40)
  ctx.font = '500 11px sans-serif'; ctx.fillStyle = '#475569'
  ctx.fillText('· 多数同学漏写定义域', rx + 132, ry2 + 66)
  ctx.fillText('· 步骤分按量规拆解', rx + 132, ry2 + 88)
  ctx.fillText('· 一键退回订正重交', rx + 132, ry2 + 110)

  const chips = ['题集/开放', '匿名互评', '评分量规', '展示墙']
  chips.forEach((t, i) => {
    const bx = rx + 8 + i * 74, bby = ry2 + 160
    ctx.save(); setShadow(ctx, 'rgba(20,184,166,0.4)', 5, 0, 1)
    roundRect(ctx, bx, bby, 68, 24, 12); ctx.fillStyle = 'rgba(20,184,166,0.12)'; ctx.fill(); clearShadow(ctx); ctx.restore()
    ctx.fillStyle = '#0f766e'; ctx.font = '600 10px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(t, bx + 34, bby + 12)
  })
  ctx.restore()
}

// ========== 场景 6：闭环总结 ==========
function drawSummaryScene(ctx, w, h, progress, t) {
  const fade = Math.min(progress * 1.5, 1)
  ctx.save()
  ctx.globalAlpha = fade
  const cx = w / 2, cy = h / 2 - 26, bigR = 130
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(t * 0.0002)
  ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 2; ctx.setLineDash([6, 6])
  ctx.beginPath(); ctx.arc(0, 0, bigR, 0, Math.PI * 2); ctx.stroke(); ctx.restore()

  const nodes = [
    { label: '在线考试', a: -Math.PI / 2, c: ['#a5b4fc', '#6366f1', '#4338ca'], e: '📝' },
    { label: '答题竞赛', a: -Math.PI / 2 + 2 * Math.PI / 5, c: ['#fdba74', '#f97316', '#c2410c'], e: '🏆' },
    { label: '征集悬赏', a: -Math.PI / 2 + 4 * Math.PI / 5, c: ['#6ee7b7', '#10b981', '#047857'], e: '💰' },
    { label: '自主学习', a: -Math.PI / 2 + 6 * Math.PI / 5, c: ['#f9a8d4', '#ec4899', '#be185d'], e: '📚' },
    { label: '作业练习', a: -Math.PI / 2 + 8 * Math.PI / 5, c: ['#5eead4', '#14b8a6', '#0f766e'], e: '📒' },
  ]
  nodes.forEach((n, i) => {
    const ap = easeOut((progress - 0.1 - i * 0.08) * 4)
    if (ap <= 0) return
    const ang = n.a + t * 0.0002
    const nx = cx + bigR * Math.cos(ang), ny = cy + bigR * Math.sin(ang)
    ctx.save(); ctx.globalAlpha = fade * ap
    drawGlowRing(ctx, nx, ny, 34 * ap, [n.c[2], 'transparent'], 2)
    drawGradientCircle(ctx, nx, ny, 28 * ap, n.c, n.c[2] + '99')
    ctx.fillStyle = '#fff'; ctx.font = '19px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(n.e, nx, ny + 1)
    ctx.font = '700 12px sans-serif'; ctx.fillText(n.label, nx, ny + 50)
    ctx.restore()
  })
  ctx.save(); setShadow(ctx, 'rgba(99,102,241,0.5)', 24, 0, 0)
  const cg = ctx.createRadialGradient(cx, cy - 10, 5, cx, cy, 58)
  cg.addColorStop(0, 'rgba(255,255,255,0.92)'); cg.addColorStop(0.4, 'rgba(99,102,241,0.85)'); cg.addColorStop(1, 'rgba(6,182,212,0.7)')
  ctx.beginPath(); ctx.arc(cx, cy, 58, 0, Math.PI * 2); ctx.fillStyle = cg; ctx.fill(); clearShadow(ctx); ctx.restore()
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#fff'
  ctx.font = '800 17px sans-serif'; ctx.shadowColor = 'rgba(0,0,0,0.2)'; ctx.shadowBlur = 4
  ctx.fillText('智汇学场', cx, cy - 6); ctx.shadowBlur = 0
  ctx.font = '500 10.5px sans-serif'; ctx.fillStyle = 'rgba(255,255,255,0.92)'
  ctx.fillText('AI 驱动 · 五模块闭环', cx, cy + 14)
  drawText(ctx, '从测评、作业到竞技，从众创到自学 · 一站式成长', cx, h - 40, 14, 600, easeOut((progress - 0.4) * 2.5), 'rgba(255,255,255,0.95)')
  ctx.restore()
}

// ========== 底部字幕带（仅模块切片） ==========
function drawCaptionBand(ctx, slide, slideTime, w, h) {
  if (!slide.features) return
  const mask = ctx.createLinearGradient(0, h - 120, 0, h)
  mask.addColorStop(0, 'rgba(0,0,0,0)'); mask.addColorStop(1, 'rgba(0,0,0,0.55)')
  ctx.fillStyle = mask; ctx.fillRect(0, h - 120, w, 120)

  const titleOp = clamp((slideTime - animationDuration * 0.3) / animationDuration)
  const descOp = clamp((slideTime - animationDuration * 0.5) / animationDuration)
  ctx.save()
  ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'
  ctx.globalAlpha = titleOp; ctx.fillStyle = '#fff'
  ctx.font = "800 26px -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif"
  ctx.fillText(slide.title, 30, h - 92)
  ctx.globalAlpha = descOp; ctx.fillStyle = 'rgba(255,255,255,0.85)'
  ctx.font = "400 13px -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif"
  ctx.fillText(slide.desc, 30, h - 70)
  ctx.restore()

  // feature 标签（横排右下，逐个淡入）
  ctx.save()
  ctx.font = "500 12px -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif"
  const widths = slide.features.map(f => ctx.measureText(f).width + 26)
  const total = widths.reduce((a, b) => a + b + 8, -8)
  let tx = w - total - 20
  slide.features.forEach((f, i) => {
    const op = clamp((slideTime - animationDuration * 0.7 - i * 90) / animationDuration)
    ctx.globalAlpha = op
    const tw = widths[i]
    roundRect(ctx, tx, h - 42, tw, 24, 12); ctx.fillStyle = 'rgba(255,255,255,0.22)'; ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 1; ctx.stroke()
    ctx.fillStyle = '#fff'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'
    ctx.fillText('✓ ' + f, tx + 10, h - 29)
    tx += tw + 8
  })
  ctx.restore()
}

// ========== 主绘制 ==========
function drawFrame(t) {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const dpr = Math.max(1, window.devicePixelRatio || 1)
  if (canvas.width !== W * dpr) {
    canvas.width = W * dpr; canvas.height = H * dpr
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, W, H)

  const idx = currentSlide.value
  const slide = slides[idx]
  const slideTime = currentTime.value - starts[idx]
  const p = clamp(slideTime / slide.dur)

  // 切片间交叉淡入
  drawGradient(ctx, slide.gradient, W, H, t)
  drawOrbs(ctx, W, H, t)

  if (slide.scene === 'brand') drawBrandScene(ctx, W, H, p, t)
  else if (slide.scene === 'highlight') drawHighlightScene(ctx, W, H, p)
  else if (slide.scene === 'exam') drawExamScene(ctx, W, H, Math.min(slideTime / animationDuration, 1))
  else if (slide.scene === 'competition') drawCompetitionScene(ctx, W, H, Math.min(slideTime / animationDuration, 1))
  else if (slide.scene === 'bounty') drawBountyScene(ctx, W, H, Math.min(slideTime / animationDuration, 1))
  else if (slide.scene === 'study') drawStudyScene(ctx, W, H, Math.min(slideTime / animationDuration, 1))
  else if (slide.scene === 'homework') drawHomeworkScene(ctx, W, H, Math.min(slideTime / animationDuration, 1))
  else if (slide.scene === 'summary') drawSummaryScene(ctx, W, H, p, t)

  drawCaptionBand(ctx, slide, slideTime, W, H)

  // 章节指示点（右上角）
  ctx.save()
  const dotsY = 20
  const dotW = 20, gap = 6
  const totalW = slides.length * dotW + (slides.length - 1) * gap
  let dx = W - totalW - 16
  slides.forEach((s, i) => {
    ctx.globalAlpha = i === idx ? 1 : 0.35
    ctx.fillStyle = i === idx ? '#ffffff' : 'rgba(255,255,255,0.7)'
    roundRect(ctx, dx, dotsY, dotW, 4, 2); ctx.fill()
    dx += dotW + gap
  })
  ctx.restore()
}

function slideIndexAt(ms) {
  let idx = 0
  for (let i = 0; i < starts.length; i++) {
    if (ms >= starts[i]) idx = i
  }
  return idx
}

function updateTime(timestamp) {
  if (!lastTimestamp) lastTimestamp = timestamp
  const delta = timestamp - lastTimestamp
  lastTimestamp = timestamp
  if (isPlaying.value) {
    currentTime.value += delta
    if (currentTime.value >= totalDuration.value) currentTime.value = 0
    currentSlide.value = slideIndexAt(currentTime.value)
  }
  drawFrame(timestamp)
  animationFrameId = requestAnimationFrame(updateTime)
}

function togglePlay() {
  isPlaying.value = !isPlaying.value
  if (isPlaying.value && currentTime.value >= totalDuration.value) {
    currentTime.value = 0; currentSlide.value = 0
  }
}
function jumpTo(i) {
  currentSlide.value = i
  currentTime.value = starts[i] + 1
}
function prevSlide() {
  const inSlide = currentTime.value - starts[currentSlide.value]
  if (inSlide > 700 || currentSlide.value === 0) jumpTo(currentSlide.value)
  else jumpTo(currentSlide.value - 1)
}
function nextSlide() {
  jumpTo(Math.min(currentSlide.value + 1, slides.length - 1))
}
function seek(event) {
  const bar = event.currentTarget
  const rect = bar.getBoundingClientRect()
  const pct = clamp((event.clientX - rect.left) / rect.width)
  currentTime.value = pct * totalDuration.value
  currentSlide.value = slideIndexAt(currentTime.value)
}
function toggleFullscreen() {
  const el = playerRef.value ? playerRef.value.parentElement : null
  if (!el) return
  if (!document.fullscreenElement) { el.requestFullscreen && el.requestFullscreen(); isFullscreen.value = true }
  else { document.exitFullscreen(); isFullscreen.value = false }
}
function close() {
  isPlaying.value = false
  currentTime.value = 0
  currentSlide.value = 0
  emit('close', false)
}

watch(() => props.show, (val) => {
  if (val) {
    currentTime.value = 0
    currentSlide.value = 0
    setTimeout(() => { isPlaying.value = true }, 300)
  } else {
    isPlaying.value = false
  }
})

onMounted(() => { animationFrameId = requestAnimationFrame(updateTime) })
onUnmounted(() => { if (animationFrameId) cancelAnimationFrame(animationFrameId) })
</script>

<style scoped>
.video-modal { border-radius: 16px; overflow: hidden; }
.video-modal :deep(.el-dialog__body) { padding: 0; }
.video-modal :deep(.el-dialog__footer) {
  padding: 18px 24px; background: rgba(0, 0, 0, 0.02);
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}
.video-container { background: #0f172a; border-radius: 12px; overflow: hidden; }
.video-player { position: relative; width: 100%; height: 450px; }
.video-canvas { width: 100%; height: 100%; display: block; }
.brand-mark {
  position: absolute; left: 14px; top: 12px; z-index: 5;
  font-size: 11px; letter-spacing: 1px; color: rgba(255, 255, 255, 0.55);
  font-weight: 600; pointer-events: none;
}
.video-overlay {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  background: rgba(0, 0, 0, 0.4); backdrop-filter: blur(5px); z-index: 8;
}
.play-button {
  width: 80px; height: 80px; border-radius: 50%;
  background: rgba(99, 102, 241, 0.9); border: none; color: white;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
  transition: all 0.3s ease;
}
.play-button:hover { transform: scale(1.1); background: rgba(99, 102, 241, 1); }
.close-btn {
  position: absolute; top: 12px; right: 12px; width: 36px; height: 36px; border-radius: 50%;
  background: rgba(0, 0, 0, 0.5); border: none; color: white;
  display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 20;
  transition: all 0.3s ease;
}
.close-btn:hover { background: rgba(0, 0, 0, 0.8); transform: scale(1.08); }
.video-controls {
  display: flex; align-items: center; gap: 16px; padding: 12px 20px;
  background: rgba(0, 0, 0, 0.85);
}
.controls-left { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.control-btn {
  width: 34px; height: 34px; border-radius: 50%; background: transparent; border: none;
  color: rgba(255, 255, 255, 0.85); display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: all 0.2s ease;
}
.control-btn:hover { background: rgba(255, 255, 255, 0.12); color: white; }
.time-display { color: rgba(255, 255, 255, 0.7); font-size: 12.5px; margin-left: 6px; white-space: nowrap; }
.controls-center { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.chapter-dots { display: flex; align-items: center; gap: 8px; }
.chapter-dots .dot {
  width: 7px; height: 7px; border-radius: 50%; background: rgba(255, 255, 255, 0.3);
  cursor: pointer; transition: all 0.25s ease;
}
.chapter-dots .dot:hover { background: rgba(255, 255, 255, 0.7); }
.chapter-dots .dot.active { background: #a5b4fc; transform: scale(1.35); }
.progress-bar {
  position: relative; width: 100%; height: 4px; background: rgba(255, 255, 255, 0.2);
  border-radius: 2px; cursor: pointer;
}
.progress-fill { position: absolute; top: 0; left: 0; height: 100%; background: #6366f1; border-radius: 2px; transition: width 0.1s linear; }
.progress-dot {
  position: absolute; top: 50%; width: 12px; height: 12px; background: white; border-radius: 50%;
  transform: translate(-50%, -50%); box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3); opacity: 0; transition: opacity 0.2s;
}
.progress-bar:hover .progress-dot { opacity: 1; }
.controls-right { display: flex; align-items: center; flex-shrink: 0; }
.video-footer { text-align: center; }
.video-footer h4 { margin: 0 0 6px; font-size: 16px; font-weight: 600; color: #1e293b; }
.video-footer p { margin: 0; font-size: 13px; color: #64748b; }

@media (max-width: 768px) {
  .video-player { height: 340px; }
  .time-display { display: none; }
}
.dark .video-modal :deep(.el-dialog__footer) {
  background: rgba(30, 41, 59, 0.5); border-top-color: rgba(148, 163, 184, 0.15);
}
.dark .video-footer h4 { color: var(--text-primary); }
.dark .video-footer p { color: var(--text-secondary); }
</style>
