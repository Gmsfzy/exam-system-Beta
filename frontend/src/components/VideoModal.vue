<template>
  <el-dialog
    v-model="visible"
    width="800px"
    :close-on-click-modal="false"
    :show-close="false"
    class="video-modal"
  >
    <div class="video-container">
      <div class="video-player">
        <canvas ref="canvasRef" class="video-canvas"></canvas>
        <div class="video-overlay" v-if="!isPlaying">
          <button class="play-button" @click="togglePlay">
            <FontAwesomeIcon icon="fa-solid fa-play" size="5x" />
          </button>
        </div>
        <button class="close-btn" @click="close">
        <FontAwesomeIcon icon="fa-solid fa-xmark" size="lg" />
      </button>
      </div>
      <div class="video-controls">
        <div class="controls-left">
          <button class="control-btn" @click="togglePlay">
            <FontAwesomeIcon icon="fa-solid fa-pause" v-if="isPlaying" size="lg" />
            <FontAwesomeIcon icon="fa-solid fa-play" v-else size="lg" />
          </button>
          <button class="control-btn" @click="prevSlide" title="上一段">
            <FontAwesomeIcon icon="fa-solid fa-backward-step" size="lg" />
          </button>
          <button class="control-btn" @click="nextSlide" title="下一段">
            <FontAwesomeIcon icon="fa-solid fa-forward-step" size="lg" />
          </button>
          <span class="time-display">{{ formatTime(currentTime) }} / {{ formatTime(totalDuration) }}</span>
        </div>
        <div class="controls-center">
          <div class="progress-bar" @click="seek">
            <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
            <div class="progress-dot" :style="{ left: progressPercent + '%' }"></div>
          </div>
        </div>
        <div class="controls-right">
          <div class="volume-control">
            <FontAwesomeIcon icon="fa-solid fa-volume-high" size="sm" class="volume-icon" />
            <input type="range" min="0" max="100" v-model="volume" class="volume-slider" />
          </div>
          <button class="control-btn" @click="toggleFullscreen" title="全屏">
            <FontAwesomeIcon icon="fa-solid fa-expand" v-if="!isFullscreen" size="lg" />
            <FontAwesomeIcon icon="fa-solid fa-compress" v-else size="lg" />
          </button>
        </div>
      </div>
    </div>
    <template #footer>
      <div class="video-footer">
        <h4>智汇学场 · Smart Learning Arena</h4>
        <p>融合考试、竞赛、悬赏、自学的一体化智能学习平台</p>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close'])

const visible = computed({
  get: () => props.show,
  set: (val) => emit('close', val)
})

const canvasRef = ref(null)
const isPlaying = ref(false)
const currentSlide = ref(0)
const currentTime = ref(0)
const volume = ref(100)
const isFullscreen = ref(false)
const slideDuration = 5000
const animationDuration = 600

// 5 张幻灯片：4 模块 + 1 张总结闭环
const slides = [
  {
    title: '在线考试',
    desc: '公共题库 · AI 组卷 · 智能批改 · 防作弊',
    features: ['公共题库跨教师共享', 'AI 智能组卷（难度/知识点）', '主客观题 AI 语义评分', '切屏检测防作弊', '邀请码一键加入'],
    gradient: ['#6366f1', '#8b5cf6', '#d946ef'],
    scene: 'exam'
  },
  {
    title: '答题竞赛',
    desc: '实时 PK · 积分排位 · 段位勋章 · 战队协作',
    features: ['1v1 实时 PK 对战', '积分赛积分排位', '段位勋章体系（青铜→王者）', '战队协作与 PK', 'AI 智能匹配对手'],
    gradient: ['#f59e0b', '#f97316', '#ef4444'],
    scene: 'competition'
  },
  {
    title: '征集悬赏',
    desc: '积分激励 · 众创题库 · 人人参与',
    features: ['悬赏发布激励投稿', '题目征集与审核', '众创题库持续积累', '积分排行榜', '采纳即获积分奖励'],
    gradient: ['#22c55e', '#10b981', '#06b6d4'],
    scene: 'bounty'
  },
  {
    title: '自主学习',
    desc: '错题本 · 刷题计划 · 学习报告 · AI 答疑',
    features: ['智能错题本自动收录', '自由刷题模式', '学习计划进度追踪', '每日学习报告', 'AI 智能答疑'],
    gradient: ['#ec4899', '#f43f5e', '#ef4444'],
    scene: 'study'
  },
  {
    title: '智汇学场',
    desc: '四模块联动，从测评到竞技到自学的完整闭环',
    features: ['四模块一体化', 'AI 驱动全流程', '学习效果可见', '教师·学生双视角'],
    gradient: ['#0f172a', '#4f46e5', '#06b6d4'],
    scene: 'summary'
  }
]

const totalDuration = computed(() => slides.length * slideDuration)

const progressPercent = computed(() => {
  return (currentTime.value / totalDuration.value) * 100
})

let animationFrameId = null
let lastTimestamp = 0

function formatTime(ms) {
  const seconds = Math.floor(ms / 1000)
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

// ========== 基础绘制工具 ==========

function drawGradient(ctx, colors, width, height) {
  const gradient = ctx.createLinearGradient(0, 0, width, height)
  colors.forEach((color, i) => {
    gradient.addColorStop(i / (colors.length - 1), color)
  })
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, width, height)
}

function drawOverlay(ctx, width, height, opacity) {
  ctx.save()
  ctx.fillStyle = `rgba(0, 0, 0, ${opacity || 0.25})`
  ctx.fillRect(0, 0, width, height)
  ctx.restore()
}

function drawText(ctx, text, x, y, fontSize, fontWeight, opacity, maxWidth, color) {
  ctx.save()
  ctx.globalAlpha = opacity == null ? 1 : opacity
  ctx.fillStyle = color || '#ffffff'
  ctx.font = `${fontWeight || 400} ${fontSize}px -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  if (maxWidth) {
    const chars = text.split('')
    let line = ''
    let currentY = y
    const lineHeight = fontSize * 1.35
    for (let ch of chars) {
      const test = line + ch
      if (ctx.measureText(test).width > maxWidth && line) {
        ctx.fillText(line, x, currentY)
        line = ch
        currentY += lineHeight
      } else {
        line = test
      }
    }
    ctx.fillText(line, x, currentY)
  } else {
    ctx.fillText(text, x, y)
  }
  ctx.restore()
}

function drawRoundedRect(ctx, x, y, width, height, radius, fill, stroke) {
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.lineTo(x + width - radius, y)
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius)
  ctx.lineTo(x + width, y + height - radius)
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height)
  ctx.lineTo(x + radius, y + height)
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius)
  ctx.lineTo(x, y + radius)
  ctx.quadraticCurveTo(x, y, x + radius, y)
  ctx.closePath()
  if (fill) { ctx.fillStyle = fill; ctx.fill() }
  if (stroke) { ctx.strokeStyle = stroke; ctx.stroke() }
}

// ========== 阴影 / 渐变增强工具 ==========

function setShadow(ctx, color, blur, offsetX, offsetY) {
  ctx.shadowColor = color || 'rgba(0,0,0,0.25)'
  ctx.shadowBlur = blur || 12
  ctx.shadowOffsetX = offsetX || 0
  ctx.shadowOffsetY = offsetY || 4
}

function clearShadow(ctx) {
  ctx.shadowColor = 'transparent'
  ctx.shadowBlur = 0
  ctx.shadowOffsetX = 0
  ctx.shadowOffsetY = 0
}

// 带阴影的卡片（白色玻璃质感）
function drawGlassCard(ctx, x, y, w, h, r, opts) {
  opts = opts || {}
  const fill = opts.fill || 'rgba(255,255,255,0.95)'
  const stroke = opts.stroke || 'rgba(255,255,255,1)'
  const shadowBlur = opts.shadowBlur == null ? 18 : opts.shadowBlur
  const shadowColor = opts.shadowColor || 'rgba(0,0,0,0.25)'
  const shadowY = opts.shadowY == null ? 6 : opts.shadowY

  ctx.save()
  setShadow(ctx, shadowColor, shadowBlur, 0, shadowY)
  drawRoundedRect(ctx, x, y, w, h, r, fill, stroke)
  clearShadow(ctx)

  // 顶部高光渐变（让卡片有立体感）
  const hl = ctx.createLinearGradient(x, y, x, y + Math.min(h * 0.5, 40))
  hl.addColorStop(0, 'rgba(255,255,255,0.55)')
  hl.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = hl
  drawRoundedRect(ctx, x, y, w, h, r, hl)
  ctx.restore()
}

// 水平渐变矩形（如排行榜条、按钮）
function drawGradientBar(ctx, x, y, w, h, r, colors, shadowColor) {
  ctx.save()
  if (shadowColor) setShadow(ctx, shadowColor, 8, 0, 2)
  const g = ctx.createLinearGradient(x, y, x + w, y)
  colors.forEach((c, i) => g.addColorStop(i / (colors.length - 1), c))
  drawRoundedRect(ctx, x, y, w, h, r)
  ctx.fillStyle = g
  ctx.fill()
  clearShadow(ctx)
  // 顶部微高光
  const hl = ctx.createLinearGradient(x, y, x, y + h * 0.5)
  hl.addColorStop(0, 'rgba(255,255,255,0.3)')
  hl.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = hl
  drawRoundedRect(ctx, x, y, w, h, r)
  ctx.fill()
  ctx.restore()
}

// 径向渐变圆（如 PK 头像、模块节点）
function drawGradientCircle(ctx, cx, cy, radius, colors, shadowColor) {
  ctx.save()
  if (shadowColor) setShadow(ctx, shadowColor, 14, 0, 3)
  const g = ctx.createRadialGradient(
    cx - radius * 0.3, cy - radius * 0.3, radius * 0.1,
    cx, cy, radius
  )
  colors.forEach((c, i) => g.addColorStop(i / (colors.length - 1), c))
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.fillStyle = g
  ctx.fill()
  clearShadow(ctx)
  ctx.restore()
}

// 渐变描边圆（外发光环）
function drawGlowRing(ctx, cx, cy, radius, colors, lineWidth) {
  ctx.save()
  setShadow(ctx, colors[colors.length - 1], 12, 0, 0)
  const g = ctx.createRadialGradient(cx, cy, radius * 0.6, cx, cy, radius)
  colors.forEach((c, i) => g.addColorStop(i / (colors.length - 1), c))
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.strokeStyle = g
  ctx.lineWidth = lineWidth || 2
  ctx.stroke()
  clearShadow(ctx)
  ctx.restore()
}

// 渐变文字
function drawGradientText(ctx, text, x, y, fontSize, fontWeight, colors, align) {
  ctx.save()
  ctx.font = `${fontWeight || 400} ${fontSize}px -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif`
  ctx.textAlign = align || 'left'
  ctx.textBaseline = 'top'
  const metrics = ctx.measureText(text)
  const g = ctx.createLinearGradient(x, y, x + metrics.width, y)
  colors.forEach((c, i) => g.addColorStop(i / (colors.length - 1), c))
  ctx.fillStyle = g
  ctx.fillText(text, x, y)
  ctx.restore()
}

function drawFeatureTag(ctx, text, x, y, opacity) {
  ctx.save()
  ctx.globalAlpha = opacity
  const padding = { x: 10, y: 4 }
  const fontSize = 12
  // 临时设置字体量宽
  ctx.font = `500 ${fontSize}px -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif`
  const metrics = ctx.measureText(text)
  const width = metrics.width + padding.x * 2 + 14
  const height = fontSize + padding.y * 2 + 4
  const round = height / 2
  ctx.fillStyle = 'rgba(255, 255, 255, 0.18)'
  drawRoundedRect(ctx, x - width / 2, y - height / 2, width, height, round)
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  ctx.font = `500 ${fontSize}px -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif`
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText('✓', x - width / 2 + padding.x, y)
  ctx.fillText(text, x - width / 2 + padding.x + 12, y)
  ctx.restore()
}

// ========== 场景 1：在线考试（模拟试卷预览 + 倒计时 + AI 批改角标） ==========

function drawExamScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade

  // 左侧：模拟试卷卡片（玻璃质感 + 投影）
  const cardX = 40 + slide * 20
  const cardY = 60
  const cardW = 340
  const cardH = 320
  drawGlassCard(ctx, cardX, cardY, cardW, cardH, 16, { shadowColor: 'rgba(79, 70, 229, 0.35)' })

  // 卡片顶栏（带底部分隔线）
  ctx.fillStyle = '#f1f5f9'
  drawRoundedRect(ctx, cardX, cardY, cardW, 40, 16, '#f1f5f9')
  drawRoundedRect(ctx, cardX, cardY + 24, cardW, 16, 0, '#f1f5f9')
  // 底部描边分隔
  ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(cardX + 14, cardY + 40)
  ctx.lineTo(cardX + cardW - 14, cardY + 40)
  ctx.stroke()

  // 标题用渐变色
  drawGradientText(ctx, '📝 高等数学 · 期中考试', cardX + 14, cardY + 10, 13, 600, ['#4f46e5', '#8b5cf6'])
  // 倒计时（红色带微阴影）
  ctx.save()
  setShadow(ctx, 'rgba(220,38,38,0.4)', 6, 0, 0)
  ctx.fillStyle = '#dc2626'
  ctx.font = '700 12px monospace'
  ctx.textAlign = 'right'
  ctx.textBaseline = 'middle'
  ctx.fillText('42:38', cardX + cardW - 14, cardY + 20)
  clearShadow(ctx)
  ctx.restore()

  // 题干
  ctx.fillStyle = '#334155'
  ctx.font = '600 13px sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'alphabetic'
  ctx.fillText('1. 设 f(x) = x² - 2x + 1，求 f(3) 的值：', cardX + 14, cardY + 66)

  // 选项框（选中项用渐变填充 + 阴影）
  const opts = [
    { label: 'A', text: '2', selected: false },
    { label: 'B', text: '4', selected: true },
    { label: 'C', text: '6', selected: false },
    { label: 'D', text: '8', selected: false }
  ]
  opts.forEach((o, i) => {
    const oy = cardY + 88 + i * 30
    if (o.selected) {
      drawGradientBar(ctx, cardX + 14, oy, 312, 24, 6, ['#ede9fe', '#ddd6fe', '#c4b5fd'], 'rgba(139,92,246,0.35)')
    } else {
      drawRoundedRect(ctx, cardX + 14, oy, 312, 24, 6, '#f8fafc', '#e2e8f0')
    }
    ctx.fillStyle = o.selected ? '#6d28d9' : '#64748b'
    ctx.font = '700 12px sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(o.label + '.', cardX + 22, oy + 12)
    ctx.fillStyle = o.selected ? '#6d28d9' : '#475569'
    ctx.font = '500 12px sans-serif'
    ctx.fillText(o.text, cardX + 44, oy + 12)
  })

  // 底部状态栏（带底部阴影投影）
  const statusY = cardY + 240
  ctx.save()
  setShadow(ctx, 'rgba(180,83,9,0.2)', 8, 0, 2)
  drawRoundedRect(ctx, cardX + 14, statusY, 312, 60, 10, '#fef3c7')
  clearShadow(ctx)
  ctx.restore()
  // 顶部细描边
  ctx.strokeStyle = 'rgba(251,191,36,0.5)'
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(cardX + 20, statusY)
  ctx.lineTo(cardX + cardW - 20, statusY)
  ctx.stroke()

  ctx.fillStyle = '#b45309'
  ctx.font = '700 12px sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.fillText('✅ AI 自动批改', cardX + 24, statusY + 10)
  ctx.fillStyle = '#92400e'
  ctx.font = '400 11px sans-serif'
  ctx.fillText('答案：B（正确） · 解析：f(3)=9-6+1=4', cardX + 24, statusY + 30)

  // 切屏计数（红色警示文字带阴影）
  ctx.save()
  setShadow(ctx, 'rgba(220,38,38,0.45)', 6, 0, 0)
  ctx.fillStyle = '#dc2626'
  ctx.font = '700 11px sans-serif'
  ctx.textAlign = 'right'
  ctx.textBaseline = 'top'
  ctx.fillText('⚠ 切屏 2 次', cardX + cardW - 14, statusY + 10)
  clearShadow(ctx)
  ctx.restore()

  // 右侧浮动小卡片（玻璃卡 + 紫色投影）
  const floatX = 420 - slide * 10
  drawGlassCard(ctx, floatX, cardY + 20, 140, 50, 10, { shadowColor: 'rgba(99,102,241,0.35)', shadowBlur: 14, shadowY: 5 })
  ctx.fillStyle = '#475569'
  ctx.font = '400 10px sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.fillText('📚 公共题库', floatX + 10, cardY + 32)
  drawGradientText(ctx, '1,236 题', floatX + 10, cardY + 46, 14, 700, ['#6366f1', '#8b5cf6'])

  drawGlassCard(ctx, floatX, cardY + 80, 140, 50, 10, { shadowColor: 'rgba(99,102,241,0.35)', shadowBlur: 14, shadowY: 5 })
  ctx.fillStyle = '#475569'
  ctx.font = '400 10px sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.fillText('🎯 AI 智能组卷', floatX + 10, cardY + 92)
  drawGradientText(ctx, '5 秒', floatX + 10, cardY + 106, 14, 700, ['#06b6d4', '#6366f1'])

  ctx.restore()
}

// ========== 场景 2：答题竞赛（排行榜 + PK VS） ==========

function drawCompetitionScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade

  // 左侧：排行榜（玻璃卡 + 橙色投影）
  const lx = 40 + slide * 20
  const ly = 70
  drawGlassCard(ctx, lx, ly, 300, 260, 14, { shadowColor: 'rgba(249,115,22,0.3)' })
  drawGradientText(ctx, '🏆 实时排行榜', lx + 14, ly + 14, 14, 700, ['#ea580c', '#f97316', '#ef4444'])

  const players = [
    { rank: 1, name: '智汇王者', score: 2850, self: false },
    { rank: 2, name: '学霸小李', score: 2610, self: true },
    { rank: 3, name: '努力王', score: 2480, self: false },
    { rank: 4, name: '进击的小明', score: 2320, self: false },
    { rank: 5, name: '稳稳上分', score: 2150, self: false }
  ]
  const barGradientSets = [
    ['#fde68a', '#facc15', '#f59e0b'],          // 金
    ['#cbd5e1', '#e2e8f0', '#f1f5f9'],          // 银
    ['#fbbf24', '#d97706', '#92400e'],          // 铜
    ['#fed7aa', '#fb923c', '#f97316'],
    ['#fed7aa', '#fdba74', '#fb923c']
  ]
  players.forEach((p, i) => {
    const py = ly + 50 + i * 36
    const barW = 220 * (p.score / 2850)
    // 外层槽
    drawRoundedRect(ctx, lx + 14, py, 262, 26, 6, p.self ? '#fecaca' : '#f1f5f9')
    // 渐变实条
    drawGradientBar(ctx, lx + 14, py, Math.min(barW, 258), 26, 6, barGradientSets[i], i === 0 ? 'rgba(245,158,11,0.3)' : null)
    ctx.fillStyle = i === 0 ? '#713f12' : '#334155'
    ctx.font = '700 12px sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(p.rank + ' ' + p.name + (p.self ? ' (我)' : ''), lx + 24, py + 13)
    ctx.fillStyle = '#1e293b'
    ctx.font = '700 12px monospace'
    ctx.textAlign = 'right'
    ctx.fillText(p.score, lx + 290, py + 13)
  })

  // 右侧：PK VS（玻璃卡 + 橙色投影）
  const px = 360 - slide * 10
  const py = 90
  drawGlassCard(ctx, px, py, 170, 120, 14, { shadowColor: 'rgba(249,115,22,0.3)', shadowY: 4 })
  drawGradientText(ctx, '⚔ 1v1 实时 PK', px + 25, py + 12, 11, 700, ['#ea580c', '#f97316'])

  // 玩家 1（径向渐变圆 + 投影）
  drawGradientCircle(ctx, px + 42, py + 62, 22, ['#60a5fa', '#3b82f6', '#1d4ed8'], 'rgba(59,130,246,0.4)')
  ctx.fillStyle = '#fff'
  ctx.font = '700 14px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('A', px + 42, py + 62)
  ctx.fillStyle = '#1e293b'
  ctx.font = '600 10px sans-serif'
  ctx.textBaseline = 'top'
  ctx.fillText('青铜 III', px + 42, py + 88)

  // VS（带阴影描边渐变字）
  ctx.save()
  setShadow(ctx, 'rgba(249,115,22,0.45)', 8, 0, 0)
  drawGradientText(ctx, 'VS', px + 74, py + 52, 20, 800, ['#ea580c', '#f97316', '#ef4444'], 'center')
  clearShadow(ctx)
  ctx.restore()

  // 玩家 2
  drawGradientCircle(ctx, px + 128, py + 62, 22, ['#fca5a5', '#ef4444', '#b91c1c'], 'rgba(239,68,68,0.4)')
  ctx.fillStyle = '#fff'
  ctx.font = '700 14px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('B', px + 128, py + 62)
  ctx.fillStyle = '#1e293b'
  ctx.font = '600 10px sans-serif'
  ctx.textBaseline = 'top'
  ctx.fillText('白银 I', px + 128, py + 88)

  // 段位徽章（带投影）
  const bx = 360 - slide * 10
  const by = py + 140
  const badges = ['🥉 青铜', '🥈 白银', '🥇 黄金', '💎 铂金', '👑 王者']
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  badges.forEach((b, i) => {
    const bx2 = bx + (i % 3) * 58
    const by2 = by + Math.floor(i / 3) * 28
    ctx.save()
    setShadow(ctx, 'rgba(0,0,0,0.15)', 6, 0, 2)
    drawRoundedRect(ctx, bx2, by2, 54, 22, 6, 'rgba(255,255,255,0.92)')
    clearShadow(ctx)
    ctx.restore()
    ctx.fillStyle = '#374151'
    ctx.font = '600 10px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(b, bx2 + 27, by2 + 11)
  })

  ctx.restore()
}

// ========== 场景 3：征集悬赏（悬赏列表 + 审核流程图） ==========

function drawBountyScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade

  // 左侧：悬赏列表（玻璃卡 + 绿/红/蓝主题投影）
  const bx = 40 + slide * 20
  const by = 70
  const bounties = [
    { title: 'Python 面向对象编程', points: 500, status: '进行中', color: '#22c55e', grad: ['#22c55e', '#10b981'] },
    { title: '数据结构：链表与树', points: 800, status: '热门', color: '#ef4444', grad: ['#fb7185', '#ef4444', '#b91c1c'] },
    { title: '机器学习基础概念', points: 1200, status: '新发布', color: '#3b82f6', grad: ['#60a5fa', '#3b82f6', '#1d4ed8'] }
  ]
  bounties.forEach((b, i) => {
    const cy = by + i * 88
    drawGlassCard(ctx, bx, cy, 310, 76, 14, { shadowColor: b.color + '66', shadowBlur: 14 })
    // 积分大数字（径向渐变填充 + 柔和阴影）
    ctx.save()
    setShadow(ctx, b.color + '88', 10, 0, 2)
    drawGradientText(ctx, String(b.points), bx + 220, cy + 8, 30, 800, b.grad, 'left')
    clearShadow(ctx)
    ctx.restore()
    ctx.fillStyle = b.color
    ctx.font = '600 10px sans-serif'
    ctx.textAlign = 'right'
    ctx.textBaseline = 'top'
    ctx.fillText('积分', bx + 300, cy + 46)
    // 标题
    ctx.fillStyle = '#0f172a'
    ctx.font = '700 14px sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText('📌 ' + b.title, bx + 16, cy + 18)
    // 状态标签（带投影）
    ctx.save()
    setShadow(ctx, b.color + '88', 6, 0, 1)
    drawGradientBar(ctx, bx + 16, cy + 44, 62, 20, 4, [b.color, b.color, b.color], null)
    clearShadow(ctx)
    ctx.restore()
    ctx.fillStyle = '#fff'
    ctx.font = '600 10px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(b.status, bx + 47, cy + 54)
    // 小描述
    ctx.fillStyle = '#64748b'
    ctx.font = '400 11px sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'top'
    ctx.fillText('征集优质题目，被采纳即获积分奖励', bx + 90, cy + 56)
  })

  // 右侧：审核流程图（玻璃卡）
  const fx = 370 - slide * 10
  const fy = 140
  drawGlassCard(ctx, fx - 10, fy - 30, 170, 110, 12, { shadowColor: 'rgba(16,185,129,0.3)', fill: 'rgba(255,255,255,0.9)' })
  drawGradientText(ctx, '🔄 征集审核流程', fx, fy - 22, 12, 700, ['#047857', '#10b981'], 'center')

  const flowNodes = [
    { label: '发布', x: fx + 20, y: fy + 20, colors: ['#4ade80', '#22c55e', '#15803d'] },
    { label: '投稿', x: fx + 75, y: fy + 20, colors: ['#67e8f9', '#06b6d4', '#0e7490'] },
    { label: '采纳', x: fx + 130, y: fy + 20, colors: ['#fcd34d', '#f59e0b', '#b45309'] }
  ]
  flowNodes.forEach(n => {
    drawGradientCircle(ctx, n.x, n.y, 16, n.colors, n.colors[n.colors.length - 1] + '99')
    ctx.fillStyle = '#fff'
    ctx.font = '700 11px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(n.label, n.x, n.y)
  })
  // 箭头（带装饰圆点）
  ctx.strokeStyle = 'rgba(16,185,129,0.5)'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(fx + 36, fy + 20)
  ctx.lineTo(fx + 58, fy + 20)
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(fx + 91, fy + 20)
  ctx.lineTo(fx + 113, fy + 20)
  ctx.stroke()

  // 底部统计卡片
  drawRoundedRect(ctx, fx - 10, fy + 56, 170, 40, 8, 'rgba(255,255,255,0.85)')
  ctx.fillStyle = '#047857'
  ctx.font = '400 10px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText('今日新增 128 题 · 累计采纳 3,456 题', fx + 75, fy + 76)

  ctx.restore()
}

// ========== 场景 4：自主学习（错题本 + 雷达图 + AI 气泡） ==========

function drawStudyScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  const slide = Math.max(0, (progress - 0.3) / 0.7)
  ctx.save()
  ctx.globalAlpha = fade

  // 左侧：错题本（玻璃卡 + 粉色投影）
  const wx = 40 + slide * 20
  const wy = 70
  drawGlassCard(ctx, wx, wy, 280, 260, 14, { shadowColor: 'rgba(219,39,119,0.3)', shadowY: 5 })
  drawGradientText(ctx, '📖 我的错题本', wx + 14, wy + 12, 13, 700, ['#db2777', '#ec4899'], 'left')
  ctx.fillStyle = '#64748b'
  ctx.font = '500 10px sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.fillText('待攻克 7 · 已掌握 18', wx + 140, wy + 16)

  const wrongs = [
    { q: 'TCP 三次握手的第二次报文？', mastered: false },
    { q: '数据库索引的底层数据结构？', mastered: false },
    { q: '进程与线程的本质区别？', mastered: true },
    { q: 'HTTP 304 状态码含义？', mastered: false }
  ]
  wrongs.forEach((w2, i) => {
    const qy = wy + 44 + i * 44
    ctx.save()
    setShadow(ctx, w2.mastered ? 'rgba(22,163,74,0.2)' : 'rgba(220,38,38,0.25)', 6, 0, 1)
    drawRoundedRect(ctx, wx + 14, qy, 252, 36, 8, w2.mastered ? '#dcfce7' : '#fef2f2', w2.mastered ? '#86efac' : '#fecaca')
    clearShadow(ctx)
    ctx.restore()
    // 左侧状态 pill
    drawGradientBar(ctx, wx + 20, qy + 9, 44, 18, 4,
      w2.mastered ? ['#4ade80', '#22c55e', '#15803d'] : ['#fca5a5', '#ef4444', '#b91c1c'],
      w2.mastered ? null : 'rgba(239,68,68,0.4)')
    ctx.fillStyle = '#fff'
    ctx.font = '700 9px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(w2.mastered ? '✓ 已掌' : '✗ 待攻', wx + 42, qy + 18)
    ctx.fillStyle = '#334155'
    ctx.font = '400 11px sans-serif'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'top'
    ctx.fillText(w2.q, wx + 74, qy + 10)
  })

  // 右侧上方：五维雷达图（玻璃卡 + 粉色投影）
  const rx = 340 - slide * 10
  const ry = 80
  const rad = 55
  const cx = rx + rad + 10
  const cy = ry + rad + 10
  drawGlassCard(ctx, rx, ry, (rad + 10) * 2, (rad + 10) * 2, 14, { shadowColor: 'rgba(219,39,119,0.25)', shadowBlur: 12 })

  const labels = ['基础', '进阶', '算法', '系统', '网络']
  const values = [0.8, 0.65, 0.45, 0.72, 0.55]
  ctx.strokeStyle = 'rgba(148,163,184,0.4)'
  ctx.lineWidth = 1
  // 雷达网格
  for (let ring = 1; ring <= 4; ring++) {
    ctx.beginPath()
    const r = (rad * ring) / 4
    for (let i = 0; i < 5; i++) {
      const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / 5
      const px = cx + r * Math.cos(angle)
      const py = cy + r * Math.sin(angle)
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
    }
    ctx.closePath()
    ctx.stroke()
  }
  // 轴线
  ctx.strokeStyle = 'rgba(148,163,184,0.3)'
  for (let i = 0; i < 5; i++) {
    const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / 5
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(cx + rad * Math.cos(angle), cy + rad * Math.sin(angle))
    ctx.stroke()
  }
  // 数据区域（渐变填充 + 投影）
  ctx.save()
  setShadow(ctx, 'rgba(236,72,153,0.4)', 8, 0, 0)
  const dataGrad = ctx.createRadialGradient(cx, cy, rad * 0.2, cx, cy, rad)
  dataGrad.addColorStop(0, 'rgba(236,72,153,0.15)')
  dataGrad.addColorStop(1, 'rgba(236,72,153,0.5)')
  ctx.fillStyle = dataGrad
  ctx.beginPath()
  for (let i = 0; i < 5; i++) {
    const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / 5
    const r = rad * values[i]
    const px = cx + r * Math.cos(angle)
    const py = cy + r * Math.sin(angle)
    if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
  }
  ctx.closePath()
  ctx.fill()
  // 顶点描边
  ctx.strokeStyle = '#ec4899'
  ctx.lineWidth = 2
  ctx.stroke()
  clearShadow(ctx)
  ctx.restore()
  // 顶点圆点
  for (let i = 0; i < 5; i++) {
    const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / 5
    const r = rad * values[i]
    const px = cx + r * Math.cos(angle)
    const py = cy + r * Math.sin(angle)
    ctx.beginPath()
    ctx.arc(px, py, 3, 0, Math.PI * 2)
    ctx.fillStyle = '#ec4899'
    ctx.fill()
  }
  // 标签
  ctx.fillStyle = '#475569'
  ctx.font = '600 10px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  labels.forEach((lb, i) => {
    const angle = (-Math.PI / 2) + (i * 2 * Math.PI) / 5
    const lx = cx + (rad + 14) * Math.cos(angle)
    const ly = cy + (rad + 14) * Math.sin(angle)
    ctx.fillText(lb, lx, ly)
  })

  // 右侧下方：AI 答疑气泡（玻璃卡）
  const bx2 = 340 - slide * 10
  const by2 = ry + (rad + 10) * 2 + 12
  drawGlassCard(ctx, bx2, by2, 170, 70, 14, { shadowColor: 'rgba(236,72,153,0.25)', shadowBlur: 12 })
  // 用户气泡（带投影）
  ctx.save()
  setShadow(ctx, 'rgba(0,0,0,0.12)', 4, 0, 1)
  drawRoundedRect(ctx, bx2 + 10, by2 + 10, 100, 20, 6, '#e2e8f0')
  clearShadow(ctx)
  ctx.restore()
  ctx.fillStyle = '#374151'
  ctx.font = '400 10px sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText('什么是哈希冲突？', bx2 + 16, by2 + 20)
  // AI 气泡（粉色渐变 + 投影）
  ctx.save()
  setShadow(ctx, 'rgba(219,39,119,0.25)', 5, 0, 2)
  drawGradientBar(ctx, bx2 + 40, by2 + 36, 122, 28, 6, ['#fce7f3', '#fbcfe8', '#f9a8d4'], null)
  clearShadow(ctx)
  ctx.restore()
  ctx.fillStyle = '#be185d'
  ctx.font = '400 10px sans-serif'
  ctx.fillText('两种哈希到同一地址的…', bx2 + 48, by2 + 46)
  ctx.fillText('解决方法有链地址法等', bx2 + 48, by2 + 58)
  // AI 头像（渐变圆 + 外发光）
  drawGradientCircle(ctx, bx2 + 30, by2 + 50, 9, ['#f9a8d4', '#ec4899', '#be185d'], 'rgba(236,72,153,0.5)')
  ctx.fillStyle = '#fff'
  ctx.font = '700 10px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('AI', bx2 + 30, by2 + 50 + 1)

  ctx.restore()
}

// ========== 场景 5：总结闭环 ==========

function drawSummaryScene(ctx, w, h, progress) {
  const fade = Math.min(progress * 1.5, 1)
  ctx.save()
  ctx.globalAlpha = fade

  const cx = w / 2
  const cy = h / 2 - 20
  const bigR = 140

  // 背景发光圈（外晕）
  ctx.save()
  setShadow(ctx, 'rgba(99,102,241,0.3)', 30, 0, 0)
  ctx.beginPath()
  ctx.arc(cx, cy, bigR + 8, 0, Math.PI * 2)
  ctx.strokeStyle = 'rgba(255,255,255,0.1)'
  ctx.lineWidth = 1
  ctx.stroke()
  clearShadow(ctx)
  ctx.restore()

  // 内圈（渐变虚线）
  ctx.save()
  setShadow(ctx, 'rgba(6,182,212,0.25)', 14, 0, 0)
  ctx.strokeStyle = 'rgba(255,255,255,0.35)'
  ctx.lineWidth = 2
  ctx.setLineDash([6, 6])
  ctx.beginPath()
  ctx.arc(cx, cy, bigR, 0, Math.PI * 2)
  ctx.stroke()
  ctx.setLineDash([])
  clearShadow(ctx)
  ctx.restore()

  // 四个模块节点（环形，每个带径向渐变 + 外发光环）
  const nodes = [
    { label: '在线考试', angle: -Math.PI / 2, colors: ['#a5b4fc', '#6366f1', '#4338ca'], emoji: '📝' },
    { label: '答题竞赛', angle: 0, colors: ['#fdba74', '#f97316', '#c2410c'], emoji: '🏆' },
    { label: '征集悬赏', angle: Math.PI / 2, colors: ['#6ee7b7', '#10b981', '#047857'], emoji: '💰' },
    { label: '自主学习', angle: Math.PI, colors: ['#f9a8d4', '#ec4899', '#be185d'], emoji: '📚' }
  ]

  nodes.forEach(n => {
    const nx = cx + bigR * Math.cos(n.angle)
    const ny = cy + bigR * Math.sin(n.angle)
    // 外发光环
    drawGlowRing(ctx, nx, ny, 36, [n.colors[n.colors.length - 1], 'transparent'], 2)
    // 渐变圆
    drawGradientCircle(ctx, nx, ny, 30, n.colors, n.colors[n.colors.length - 1] + '99')
    ctx.fillStyle = '#fff'
    ctx.font = '20px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(n.emoji, nx, ny + 1)
    // 标签
    ctx.fillStyle = '#fff'
    ctx.font = '700 13px sans-serif'
    ctx.fillText(n.label, nx, ny + 56)
  })

  // 中心圆（径向渐变 + 光晕）
  ctx.save()
  setShadow(ctx, 'rgba(99,102,241,0.5)', 24, 0, 0)
  const centerGrad = ctx.createRadialGradient(cx, cy - 10, 5, cx, cy, 60)
  centerGrad.addColorStop(0, 'rgba(255,255,255,0.9)')
  centerGrad.addColorStop(0.4, 'rgba(99,102,241,0.85)')
  centerGrad.addColorStop(1, 'rgba(6,182,212,0.7)')
  ctx.beginPath()
  ctx.arc(cx, cy, 60, 0, Math.PI * 2)
  ctx.fillStyle = centerGrad
  ctx.fill()
  clearShadow(ctx)
  ctx.restore()

  // 中心文字
  ctx.save()
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = '#fff'
  ctx.font = '800 18px sans-serif'
  ctx.shadowColor = 'rgba(0,0,0,0.2)'
  ctx.shadowBlur = 4
  ctx.fillText('智汇学场', cx, cy - 6)
  ctx.font = '500 11px sans-serif'
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  ctx.fillText('AI 驱动 · 四模块闭环', cx, cy + 16)
  ctx.restore()
}

// ========== 主绘制 ==========

function drawFrame() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const { width, height } = canvas

  const slide = slides[currentSlide.value]
  const slideTime = currentTime.value % slideDuration

  drawGradient(ctx, slide.gradient, width, height)

  // 场景淡入进度
  const fadeIn = Math.min(slideTime / animationDuration, 1)

  // 先画场景
  ctx.save()
  if (slide.scene === 'exam') drawExamScene(ctx, width, height, fadeIn)
  else if (slide.scene === 'competition') drawCompetitionScene(ctx, width, height, fadeIn)
  else if (slide.scene === 'bounty') drawBountyScene(ctx, width, height, fadeIn)
  else if (slide.scene === 'study') drawStudyScene(ctx, width, height, fadeIn)
  else if (slide.scene === 'summary') drawSummaryScene(ctx, width, height, fadeIn)
  ctx.restore()

  // 底部渐变遮罩（让底部文字更清晰）
  const maskGrad = ctx.createLinearGradient(0, height - 120, 0, height)
  maskGrad.addColorStop(0, 'rgba(0,0,0,0)')
  maskGrad.addColorStop(1, 'rgba(0,0,0,0.55)')
  ctx.fillStyle = maskGrad
  ctx.fillRect(0, height - 120, width, 120)

  // 右下角：标题 + 描述 + feature tags（延迟淡入）
  const titleOp = Math.max(0, Math.min((slideTime - animationDuration * 0.4) / animationDuration, 1))
  const descOp = Math.max(0, Math.min((slideTime - animationDuration * 0.55) / animationDuration, 1))
  const tagOp = Math.max(0, Math.min((slideTime - animationDuration * 0.7) / animationDuration, 1))

  // 标题（左下对齐）
  ctx.textAlign = 'left'
  ctx.textBaseline = 'bottom'
  drawText(ctx, slide.title, 30, height - 96, 26, 800, titleOp, null, '#ffffff')
  drawText(ctx, slide.desc, 30, height - 72, 13, 400, descOp, 520, 'rgba(255,255,255,0.85)')

  // Feature tags（横排，右对齐）
  const totalTagWidth = slide.features.reduce((sum, f) => {
    ctx.font = '500 12px sans-serif'
    return sum + ctx.measureText(f).width + 40
  }, 0)
  let tx = width - totalTagWidth - 20
  slide.features.forEach((f, i) => {
    const tagDelay = i * 60
    const op = Math.max(0, Math.min((slideTime - animationDuration * 0.7 - tagDelay) / animationDuration, 1))
    ctx.globalAlpha = op
    ctx.fillStyle = 'rgba(255,255,255,0.22)'
    ctx.strokeStyle = 'rgba(255,255,255,0.35)'
    ctx.lineWidth = 1
    ctx.font = '500 12px sans-serif'
    const tw = ctx.measureText(f).width + 26
    drawRoundedRect(ctx, tx, height - 42, tw, 24, 12, 'rgba(255,255,255,0.22)')
    ctx.fillStyle = '#ffffff'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText('✓ ' + f, tx + 10, height - 30)
    tx += tw + 8
  })

  // 幻灯片编号指示（右上角）
  ctx.globalAlpha = Math.min(slideTime / 300, 1)
  ctx.fillStyle = 'rgba(255,255,255,0.3)'
  ctx.font = '600 11px sans-serif'
  ctx.textAlign = 'right'
  ctx.textBaseline = 'top'
  ctx.fillText((currentSlide.value + 1) + ' / ' + slides.length, width - 14, 14)
  ctx.globalAlpha = 1
}

function updateTime(timestamp) {
  if (!lastTimestamp) lastTimestamp = timestamp
  const delta = timestamp - lastTimestamp
  lastTimestamp = timestamp

  if (isPlaying.value) {
    currentTime.value += delta
    if (currentTime.value >= totalDuration.value) {
      currentTime.value = 0
    }
    currentSlide.value = Math.min(Math.floor(currentTime.value / slideDuration), slides.length - 1)
  }

  drawFrame()
  animationFrameId = requestAnimationFrame(updateTime)
}

function togglePlay() {
  isPlaying.value = !isPlaying.value
  if (isPlaying.value && currentTime.value >= totalDuration.value) {
    currentTime.value = 0
    currentSlide.value = 0
  }
}

function prevSlide() {
  currentSlide.value = (currentSlide.value - 1 + slides.length) % slides.length
  currentTime.value = currentSlide.value * slideDuration
}

function nextSlide() {
  currentSlide.value = (currentSlide.value + 1) % slides.length
  currentTime.value = currentSlide.value * slideDuration
}

function seek(event) {
  const progressBar = event.currentTarget
  const rect = progressBar.getBoundingClientRect()
  const percent = (event.clientX - rect.left) / rect.width
  currentTime.value = percent * totalDuration.value
  currentSlide.value = Math.min(Math.floor(currentTime.value / slideDuration), slides.length - 1)
}

function toggleFullscreen() {
  const container = document.querySelector('.video-modal')
  if (!document.fullscreenElement) {
    container.requestFullscreen()
    isFullscreen.value = true
  } else {
    document.exitFullscreen()
    isFullscreen.value = false
  }
}

function close() {
  isPlaying.value = false
  currentTime.value = 0
  currentSlide.value = 0
  emit('close', false)
}

watch(() => props.show, (newVal) => {
  if (newVal) {
    const canvas = canvasRef.value
    if (canvas) {
      canvas.width = 800
      canvas.height = 450
    }
    setTimeout(() => {
      isPlaying.value = true
    }, 500)
  }
})

onMounted(() => {
  if (props.show) {
    const canvas = canvasRef.value
    if (canvas) {
      canvas.width = 800
      canvas.height = 450
    }
  }
  animationFrameId = requestAnimationFrame(updateTime)
})

onUnmounted(() => {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId)
  }
})
</script>

<style scoped>
.video-modal {
  border-radius: 16px;
  overflow: hidden;
}

.video-modal :deep(.el-dialog__body) {
  padding: 0;
}

.video-modal :deep(.el-dialog__footer) {
  padding: 20px 24px;
  background: rgba(0, 0, 0, 0.02);
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

.video-container {
  background: #0f172a;
  border-radius: 12px;
  overflow: hidden;
}

.video-player {
  position: relative;
  width: 100%;
  height: 450px;
}

.video-canvas {
  width: 100%;
  height: 100%;
}

.video-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(5px);
}

.play-button {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: rgba(99, 102, 241, 0.9);
  border: none;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.3s ease;
}

.play-button:hover {
  transform: scale(1.1);
  background: rgba(99, 102, 241, 1);
}

.close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  border: none;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 20;
  transition: all 0.3s ease;
}

.close-btn:hover {
  background: rgba(0, 0, 0, 0.8);
  transform: scale(1.1);
}

.video-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 24px;
  background: rgba(0, 0, 0, 0.8);
}

.controls-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.control-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s ease;
}

.control-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}

.time-display {
  color: rgba(255, 255, 255, 0.7);
  font-size: 13px;
  margin-left: 4px;
}

.controls-center {
  flex: 1;
  display: flex;
  align-items: center;
}

.progress-bar {
  position: relative;
  width: 100%;
  height: 4px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
  cursor: pointer;
}

.progress-bar:hover .progress-fill {
  background: #8b5cf6;
}

.progress-fill {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  background: #6366f1;
  border-radius: 2px;
  transition: width 0.1s ease;
}

.progress-dot {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  background: white;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  transition: left 0.1s ease;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
  opacity: 0;
}

.progress-bar:hover .progress-dot {
  opacity: 1;
}

.controls-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.volume-control {
  display: flex;
  align-items: center;
  gap: 6px;
}

.volume-icon {
  color: rgba(255, 255, 255, 0.7);
}

.volume-slider {
  width: 60px;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 2px;
  cursor: pointer;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  background: white;
  border-radius: 50%;
  cursor: pointer;
}

.play-pause-icon {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.8);
}

.fullscreen-icon {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.8);
}

.video-footer {
  text-align: center;
}

.video-footer h4 {
  margin: 0 0 8px;
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}

.video-footer p {
  margin: 0;
  font-size: 14px;
  color: #64748b;
}

@media (max-width: 768px) {
  .video-player {
    height: 350px;
  }
  
  .controls-right {
    display: none;
  }
}

.dark .video-modal :deep(.el-dialog__footer) {
  background: rgba(30, 41, 59, 0.5);
  border-top-color: rgba(148, 163, 184, 0.15);
}

.dark .video-footer h4 {
  color: var(--text-primary);
}

.dark .video-footer p {
  color: var(--text-secondary);
}
</style>