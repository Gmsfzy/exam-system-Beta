/**
 * 可缩放弹窗尺寸偏好（v7.22）
 *
 * 学习心得 / 学习笔记的编辑器原来固定在屏幕右侧（drawer），长表单挤在窄条里很别扭。
 * 改成居中弹窗后，宽高由用户自己拖右下角决定，并记在本机：下次打开还是自己调好的那一套。
 *
 * 用法：
 *   const { size, bodyStyle, startGrip, toggleFull, reset } = useDialogSize('insight_editor_size', { w: 880, h: 600 })
 *   <el-dialog :width="size.w + 'px'" :top="size.top + 'px'" :fullscreen="size.full">
 *     <div :style="bodyStyle">正文</div><span class="dlg-grip" @mousedown.stop="startGrip" />
 */
import { reactive, computed, onBeforeUnmount } from 'vue'

const MIN_W = 380
const MIN_H = 240

function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v))
}

export function useDialogSize(storageKey, def = {}) {
  const defW = def.w || 880
  const defH = def.h || 600
  const defTop = def.top ?? 56

  // 上限跟着视口走：换了小屏幕/缩了浏览器，不能还原出一个比屏幕还大的窗口
  const maxW = () => Math.max(MIN_W, window.innerWidth - 48)
  const maxH = (top) => Math.max(MIN_H, window.innerHeight - (top ?? defTop) - 110)

  function load() {
    const fallback = {
      w: clamp(defW, MIN_W, maxW()),
      h: clamp(defH, MIN_H, maxH(defTop)),
      top: defTop,
      full: false,
    }
    try {
      const s = JSON.parse(localStorage.getItem(storageKey) || '{}')
      const top = Number(s.top) || fallback.top
      return {
        w: clamp(Number(s.w) || fallback.w, MIN_W, maxW()),
        h: clamp(Number(s.h) || fallback.h, MIN_H, maxH(top)),
        top,
        // full 不持久化：刷新后弹回全屏会挡住页面，用户未必还记得是自己开的
        full: false,
      }
    } catch (e) {
      return fallback
    }
  }

  const size = reactive(load())

  function save() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ w: size.w, h: size.h, top: size.top }))
    } catch (e) { /* 隐私模式写不进去就算了，不影响当下使用 */ }
  }

  // 正文固定高度（而非 max-height）：拖拽手柄才能一直贴在窗口右下角
  const bodyStyle = computed(() => ({
    height: size.full ? 'calc(100vh - 168px)' : size.h + 'px',
    overflowY: 'auto',
    paddingRight: '6px',
  }))

  let grip = null
  function startGrip(e) {
    if (size.full) return
    grip = { x: e.clientX, y: e.clientY, w: size.w, h: size.h }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', stopGrip)
    e.preventDefault()
  }

  function onMove(e) {
    if (!grip) return
    size.w = clamp(grip.w + (e.clientX - grip.x), MIN_W, maxW())
    size.h = clamp(grip.h + (e.clientY - grip.y), MIN_H, maxH(size.top))
  }

  function stopGrip() {
    grip = null
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', stopGrip)
    save()
  }

  function toggleFull() {
    size.full = !size.full
  }

  function reset() {
    Object.assign(size, {
      w: clamp(defW, MIN_W, maxW()),
      h: clamp(defH, MIN_H, maxH(defTop)),
      top: defTop,
      full: false,
    })
    save()
  }

  onBeforeUnmount(stopGrip)

  return { size, bodyStyle, startGrip, toggleFull, reset }
}
