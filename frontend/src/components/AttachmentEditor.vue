<template>
  <div class="att-edit">
    <div class="ae-tools">
      <el-button size="small" :loading="uploading" @click="pickFile">📄 上传文件</el-button>
      <input ref="fileInput" type="file" class="ae-hidden"
             accept=".pdf,.doc,.docx,.txt,.md,.ppt,.pptx,.xls,.xlsx,.csv,.zip,.rar,.7z,.png,.jpg,.jpeg,.gif,.webp,.mp4,.webm,.py,.java,.c,.cpp,.js,.ts,.css,.sql"
             @change="onPicked" />
      <el-button size="small" @click="showLink = !showLink">🔗 添加链接</el-button>
      <span class="ae-count">{{ list.length }} / {{ MAX }}</span>
    </div>
    <div class="ae-tip">
      Word / Excel / PPT / PDF / 图片 / 视频 / 代码均可上传，单文件 ≤ 50MB；
      思维导图用 <code>```mermaid mindmap```</code> 写进正文，或挂 XMind 导出的图片/PDF。
    </div>

    <div v-if="showLink" class="ae-link">
      <el-select v-model="link.type" size="small" class="ae-lt">
        <el-option v-for="(label, t) in LINK_TYPE_LABELS" :key="t" :value="t" :label="label" />
      </el-select>
      <el-input v-model="link.name" size="small" class="ae-ln" placeholder="名称（留空取链接本身）" />
      <el-input v-model="link.url" size="small" class="ae-lu" placeholder="https://…" />
      <el-button size="small" type="primary" @click="addLink">添加</el-button>
    </div>

    <div v-if="list.length" class="ae-list">
      <div v-for="(a, i) in list" :key="i" class="ae-row">
        <span class="ae-ico">{{ ICONS[a.type] || '📎' }}</span>
        <span class="ae-name" :title="a.name">{{ a.name }}</span>
        <el-tag size="small" effect="plain">{{ a.stored_name ? (a.ext || '文件') : (LINK_TYPE_LABELS[a.type] || '链接') }}</el-tag>
        <span v-if="a.size" class="ae-size">{{ fmtSize(a.size) }}</span>
        <el-button size="small" text type="danger" @click="remove(i)">移除</el-button>
      </div>
    </div>
    <div v-else class="ae-empty">暂无附件</div>
  </div>
</template>

<script setup>
// 资料附件编辑器（v7.18 需求 h）：文件走 /api/learning/attachments 落盘拿 stored_name，
// 链接只存 url + 展示类型。这里攒的是「待保存」列表，随资料 PUT/POST 一起提交，
// 真正的合法性校验（后缀白名单、目录穿越、http(s) 前缀、条数上限）在后端
// _normalize_attachments 做，前端只做体验层拦截。
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

// 与后端 _MATERIAL_ATT_MAX 同值：后端是静默截断前 20 条，前端提前挡住免得用户白传
const MAX = 20

const list = computed(() => props.modelValue || [])

const ICONS = {
  doc: '📄', sheet: '📊', slide: '📽️', pdf: '📕', image: '🖼️', video: '🎬',
  archive: '🗜️', code: '💻', text: '📝', link: '🔗', mindmap: '🧠',
}
// 外链可选展示形态（与后端 _ATT_LINK_TYPES 同集）：key 是提交值，value 是下拉显示
const LINK_TYPE_LABELS = { link: '网页', video: '视频', image: '图片', mindmap: '导图' }

const fileInput = ref(null)
const uploading = ref(false)
const showLink = ref(false)
const link = reactive({ type: 'link', url: '', name: '' })

function fmtSize(n) {
  if (!n) return ''
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

function commit(next) {
  emit('update:modelValue', next)
}

function pickFile() {
  if (list.value.length >= MAX) return ElMessage.warning(`最多 ${MAX} 个附件`)
  fileInput.value && fileInput.value.click()
}

async function onPicked(ev) {
  const file = ev.target.files && ev.target.files[0]
  ev.target.value = ''          // 先清空，允许移除后重新选同一个文件
  if (!file) return
  if (list.value.length >= MAX) return ElMessage.warning(`最多 ${MAX} 个附件`)
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const { data } = await request.post('/api/learning/attachments', fd, { timeout: 60000 })
    // type 只为立刻显示图标而粗判，落库后以后端按后缀归一化的 type 为准
    commit([...list.value, {
      name: data.name || file.name, ext: data.ext || '', stored_name: data.stored_name,
      size: data.size || file.size || 0, url: '', type: extType(data.ext),
    }])
    ElMessage.success(`附件「${file.name}」已上传，保存资料后生效`)
  } catch (e) {
    /* 拦截器已提示（类型不支持 / 超 50MB / 登录态失效） */
  } finally {
    uploading.value = false
  }
}

// 后缀 → 图标类型（展示用兜底表，判定口径与后端 _ATT_TYPE_BY_EXT 一致）
const EXT_TYPE = {
  doc: 'doc', docx: 'doc', xls: 'sheet', xlsx: 'sheet', csv: 'sheet',
  ppt: 'slide', pptx: 'slide', pdf: 'pdf', png: 'image', jpg: 'image',
  jpeg: 'image', gif: 'image', webp: 'image', mp4: 'video', webm: 'video',
  zip: 'archive', rar: 'archive', '7z': 'archive', md: 'text', txt: 'text',
}

function extType(ext) {
  return EXT_TYPE[(ext || '').replace(/^\./, '').toLowerCase()] || 'code'
}

function addLink() {
  const url = (link.url || '').trim()
  if (!/^https?:\/\//i.test(url)) return ElMessage.warning('请填写 http(s) 开头的完整链接')
  if (list.value.length >= MAX) return ElMessage.warning(`最多 ${MAX} 个附件`)
  commit([...list.value, {
    name: (link.name || '').trim() || url.replace(/^https?:\/\//, '').slice(0, 60),
    type: link.type, ext: '', url, size: 0, stored_name: '',
  }])
  link.url = ''
  link.name = ''
  showLink.value = false
  ElMessage.success('链接已加入，保存资料后生效')
}

function remove(i) {
  const next = [...list.value]
  next.splice(i, 1)
  commit(next)
}
</script>

<style scoped>
.att-edit { width: 100%; }
.ae-tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ae-hidden { display: none; }
.ae-count { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.ae-tip { margin-top: 4px; font-size: 12px; line-height: 1.6; color: var(--el-text-color-secondary, #909399); }
.ae-link { display: flex; align-items: center; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.ae-lt { width: 100px; }
.ae-ln { width: 160px; }
.ae-lu { flex: 1; min-width: 200px; }
.ae-list { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.ae-row { display: flex; align-items: center; gap: 8px; padding: 2px 6px; border: 1px solid var(--el-border-color-lighter, #ebeef5); border-radius: 6px; }
.ae-ico { font-size: 15px; }
.ae-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ae-size { font-size: 12px; color: var(--el-text-color-secondary, #909399); }
.ae-empty { margin-top: 6px; font-size: 12px; color: var(--el-text-color-placeholder, #a8abb2); }
</style>
