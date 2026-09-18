<template>
  <div class="replay">
    <div class="rp-players">
      <div v-for="p in players" :key="p.side" class="rp-row">
        <div class="rp-name">
          <span class="rp-dot" :style="{ background: p.color }"></span>
          <router-link v-if="p.user_id" class="rp-link" :to="'/rank/player/' + p.user_id">{{ p.name }}</router-link>
          <span v-else>{{ p.name }}</span>
        </div>
        <div class="rp-bar">
          <div class="rp-fill" :style="{ width: pct(p.side) + '%', background: p.color }"></div>
        </div>
        <div class="rp-score" :style="{ color: p.color }">{{ scoreAt(p.side) }}</div>
      </div>
    </div>

    <div class="rp-controls">
      <el-button size="small" circle @click="toggle">
        <el-icon><component :is="playing ? VideoPause : VideoPlay" /></el-icon>
      </el-button>
      <span class="rp-time">{{ Math.round(t) }}s / {{ maxT }}s</span>
      <el-select v-model="speed" size="small" class="rp-speed">
        <el-option :value="1" label="1x" />
        <el-option :value="2" label="2x" />
        <el-option :value="4" label="4x" />
        <el-option :value="8" label="8x" />
      </el-select>
    </div>
    <el-slider v-model="t" :max="maxT" :step="1" :show-tooltip="false" @input="pause" />

    <div class="rp-events">
      <div v-for="(e, i) in eventsUpTo" :key="i" class="re">
        <span class="re-dot" :style="{ background: colorOf(e.side) }"></span>
        <span class="re-name">{{ e.username }}</span>
        <el-tag size="small" :type="e.is_correct ? 'success' : 'info'" effect="plain">
          {{ tagText(e) }}
        </el-tag>
        <span class="re-score">{{ e.running_score }}</span>
        <span class="re-time">{{ e.t_sec }}s</span>
      </div>
      <div v-if="!eventsUpTo.length" class="re-empty">点击播放，观察双方逐题得分随时间爬升…</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted, watch } from 'vue'
import { VideoPlay, VideoPause } from '@element-plus/icons-vue'

const props = defineProps({
  timeline: { type: Array, default: () => [] },
  duration: { type: Number, default: 0 },
})

const SIDE_COLORS = { challenger: '#7db9f5', opponent: '#ff7a45', self: '#f0c14b' }
const t = ref(0)
const playing = ref(false)
const speed = ref(2)
let timer = null

const maxT = computed(() => {
  const m = props.timeline.reduce((x, e) => Math.max(x, e.t_sec || 0), 0)
  return Math.max(1, Math.ceil(m))
})

const players = computed(() => {
  const seen = {}
  const out = []
  for (const e of props.timeline) {
    if (!(e.side in seen)) {
      seen[e.side] = true
      out.push({ side: e.side, name: e.username, user_id: e.user_id, color: colorOf(e.side) })
    }
  }
  return out
})

function colorOf(side) {
  return SIDE_COLORS[side] || '#a8b4c4'
}

function tagText(e) {
  return e.is_correct ? `+${e.gained}` : '未得分'
}

function scoreAt(side) {
  let last = 0
  for (const e of props.timeline) {
    if (e.side === side && e.t_sec <= t.value) last = e.running_score
  }
  return round2(last)
}

const overallMax = computed(() => {
  const m = props.timeline.reduce((x, e) => Math.max(x, e.running_score || 0), 0)
  return m > 0 ? m : 1
})

function pct(side) {
  return Math.min(100, (scoreAt(side) / overallMax.value) * 100)
}

const eventsUpTo = computed(() =>
  props.timeline.filter((e) => e.t_sec <= t.value).slice().reverse())

const round2 = (n) => Math.round((n || 0) * 100) / 100

function pause() {
  playing.value = false
  if (timer) { clearInterval(timer); timer = null }
}

function toggle() {
  if (playing.value) { pause(); return }
  if (t.value >= maxT.value) t.value = 0
  playing.value = true
  timer = setInterval(() => {
    t.value = Math.min(maxT.value, t.value + 0.2 * speed.value)
    if (t.value >= maxT.value) pause()
  }, 200)
}

watch(() => props.timeline, () => { pause(); t.value = 0 })
onUnmounted(pause)
</script>

<style scoped>
.replay { padding: 4px 0; }
.rp-players { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
.rp-row { display: flex; align-items: center; gap: 12px; }
.rp-name { width: 120px; display: flex; align-items: center; gap: 6px; font-weight: 600; color: var(--text-primary); }
.rp-link { color: inherit; text-decoration: none; }
.rp-link:hover { text-decoration: underline; }
.rp-dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.rp-bar { flex: 1; height: 16px; border-radius: 8px; background: var(--bg-tertiary); overflow: hidden; }
.rp-fill { height: 100%; border-radius: 8px; transition: width 0.25s ease; }
.rp-score { width: 60px; text-align: right; font-weight: 800; font-size: 16px; }
.rp-controls { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
.rp-time { font-size: 13px; color: var(--text-muted); }
.rp-speed { width: 78px; margin-left: auto; }
.rp-events { margin-top: 14px; max-height: 240px; overflow-y: auto; }
.re { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-top: 1px solid var(--border-color); font-size: 13px; }
.re-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.re-name { font-weight: 600; color: var(--text-primary); }
.re-score { margin-left: auto; font-weight: 700; color: var(--text-primary); }
.re-time { color: var(--text-light); width: 44px; text-align: right; }
.re-empty { padding: 16px 0; text-align: center; color: var(--text-light); font-size: 13px; }
</style>
