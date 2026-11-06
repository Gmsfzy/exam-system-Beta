<template>
  <div class="nb-cell" :class="{ 'is-markdown': cell.cell_type === 'markdown' }">
    <!-- 工具条 -->
    <div class="nb-cell-bar">
      <span class="nb-cell-tag">{{ cell.cell_type === 'code' ? 'In[' + (cell.exec_count || '') + ']' : 'MD' }}</span>
      <template v-if="cell.cell_type === 'code'">
        <el-button size="small" type="primary" :icon="CaretRight"
                   :loading="running" @click="$emit('run', cell)">运行</el-button>
        <el-button v-if="answerMode" size="small" type="warning" plain
                   @click="$emit('use-answer', cell.source)">用作作答</el-button>
      </template>
      <el-button v-else size="small" @click="mdPreview = !mdPreview">{{ mdPreview ? '编辑' : '预览' }}</el-button>
      <span class="nb-cell-spacer"></span>
      <el-button size="small" text :icon="Top" :disabled="index === 0" @click="$emit('move-up', cell)" title="上移" />
      <el-button size="small" text :icon="Bottom" :disabled="index === total - 1" @click="$emit('move-down', cell)" title="下移" />
      <el-button size="small" text type="danger" :icon="Delete" @click="$emit('delete', cell)" title="删除单元" />
    </div>

    <!-- 输入区 -->
    <div class="nb-cell-input">
      <CodeEditor v-if="cell.cell_type === 'code'" v-model="cell.source" language="python" height="180px" />
      <el-input v-else-if="!mdPreview" v-model="cell.source" type="textarea" :autosize="{ minRows: 3, maxRows: 16 }"
                placeholder="支持 Markdown + LaTeX 公式（$...$ / $$...$$）" />
      <RichContent v-else :content="cell.source" class="nb-md-preview" />
    </div>

    <!-- 输出区（仅代码单元） -->
    <div v-if="cell.cell_type === 'code' && (cell.outputs || []).length" class="nb-cell-outputs">
      <template v-for="(o, i) in cell.outputs" :key="i">
        <pre v-if="o.output_type === 'stream'" class="nb-out nb-out-stream" :class="{ 'is-stderr': o.name === 'stderr' }">{{ o.text }}</pre>
        <pre v-else-if="o.output_type === 'error'" class="nb-out nb-out-error">{{ o.traceback }}</pre>
        <img v-else-if="o.output_type === 'image'" class="nb-out-image" :src="'data:' + (o.mime || 'image/png') + ';base64,' + o.data" alt="输出图" />
        <div v-else-if="o.output_type === 'html'" class="nb-out nb-out-html" v-html="sanitizeHtml(o.html)"></div>
        <pre v-else-if="o.output_type === 'text'" class="nb-out nb-out-result">{{ o.text }}</pre>
      </template>
      <div v-if="cell.last_run_at" class="nb-out-time">最近运行：{{ fmtTime(cell.last_run_at) }}</div>
    </div>
  </div>
</template>

<script setup>
// Notebook 单元组件（v6.6）：code 单元 = Monaco + 富输出；markdown 单元 = 编辑/预览切换
// 富输出渲染口径与后端 api_cell_run 的 outputs 结构一一对应：
//   stream(stdout/stderr) / error(traceback) / image(base64) / html(DataFrame 等 _repr_html_) / text(repr)
// html 输出源自 kernel 内库生成的表格标记，仍经 DOMPurify 净化后注入（与 RichContent 同一防 XSS 口径）。
import { ref } from 'vue'
import DOMPurify from 'dompurify'
import { CaretRight, Top, Bottom, Delete } from '@element-plus/icons-vue'
import CodeEditor from './CodeEditor.vue'
import RichContent from './RichContent.vue'

defineProps({
  cell: { type: Object, required: true },
  running: { type: Boolean, default: false },
  index: { type: Number, default: 0 },
  total: { type: Number, default: 1 },
  // v6.7 六模块接入：嵌入式作答模式下每个代码单元附「用作作答」按钮
  answerMode: { type: Boolean, default: false },
})
defineEmits(['run', 'delete', 'move-up', 'move-down', 'use-answer'])

const mdPreview = ref(false)

function sanitizeHtml(html) {
  return DOMPurify.sanitize(html || '', {
    ADD_TAGS: ['table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'caption', 'col', 'colgroup', 'span', 'div', 'style'],
    ADD_ATTR: ['class', 'style', 'colspan', 'rowspan', 'align'],
  })
}

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleString()
  } catch (e) {
    return iso
  }
}
</script>

<style scoped>
.nb-cell {
  border: 1px solid var(--border-color, #dcdfe6);
  border-radius: 10px;
  margin-bottom: 14px;
  background: var(--el-bg-color, #fff);
  overflow: hidden;
}
.nb-cell-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-color, #ebeef5);
  background: rgba(127, 127, 127, 0.05);
}
.nb-cell-spacer { flex: 1; }
.nb-cell-tag {
  font-family: Consolas, Menlo, monospace;
  font-size: 12px;
  color: var(--el-color-primary, #409eff);
  min-width: 48px;
}
.nb-cell.is-markdown .nb-cell-tag { color: var(--el-color-success, #67c23a); }
.nb-cell-input :deep(.code-editor) { border: none; border-radius: 0; }
.nb-cell-outputs { border-top: 1px dashed var(--border-color, #dcdfe6); padding: 8px 10px; }
.nb-out {
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(127, 127, 127, 0.08);
  font-family: Consolas, Menlo, monospace;
  font-size: 12.5px;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-x: auto;
}
.nb-out-stream.is-stderr { background: rgba(230, 162, 60, 0.12); color: var(--el-color-warning, #b8860b); }
.nb-out-error { background: rgba(245, 108, 108, 0.12); color: var(--el-color-danger, #c0341d); }
.nb-out-result { background: rgba(64, 158, 255, 0.08); }
.nb-out-html :deep(table) { border-collapse: collapse; margin: 4px 0; }
.nb-out-html :deep(th), .nb-out-html :deep(td) { border: 1px solid var(--border-color, #d0d0d0); padding: 4px 10px; font-size: 12.5px; }
.nb-out-image { max-width: 640px; display: block; margin: 4px 0 8px; border-radius: 6px; border: 1px solid var(--border-color, #ebeef5); }
.nb-out-time { font-size: 12px; color: #909399; }
.nb-md-preview { padding: 10px 14px; min-height: 60px; }
</style>
