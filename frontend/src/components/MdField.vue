<template>
  <div class="md-field">
    <div class="mf-bar">
      <button v-for="t in TOOLS" :key="t.key" type="button" class="mf-btn"
              :title="t.title" @click="apply(t)">{{ t.label }}</button>
      <span v-if="previewable" class="mf-spacer"></span>
      <el-button v-if="previewable" link size="small" @click="showPreview = !showPreview">
        {{ showPreview ? '收起预览' : '预览效果' }}
      </el-button>
    </div>
    <el-input ref="inputRef" :model-value="modelValue"
              type="textarea" :autosize="{ minRows, maxRows }" :maxlength="maxlength" :placeholder="placeholder"
              @update:model-value="v => emit('update:modelValue', v)" />
    <div v-if="previewable && showPreview" class="mf-preview">
      <MdView :content="modelValue || '（暂无内容）'" />
    </div>
  </div>
</template>

<script setup>
// v7.24 文档字段编辑器：Markdown 工具栏 + 实时预览
// 覆盖需求里的富文本（粗体/标题/列表/表格/引用）、数学公式、化学式(mhchem)、
// 代码片段、流程图与思维导图（后端统一按 mermaid 围栏渲染），以及附件由外层组件负责。
import { ref } from 'vue'
import MdView from './MdView.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  minRows: { type: Number, default: 6 },
  maxRows: { type: Number, default: 14 },
  maxlength: { type: Number, default: 20000 },
  placeholder: { type: String, default: '支持 Markdown；工具栏可插入公式、化学式、代码、流程图与思维导图' },
  previewable: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue'])

const inputRef = ref(null)
const showPreview = ref(false)

const TOOLS = [
  { key: 'bold', label: 'B', title: '加粗 **文本**', wrap: ['**', '**'], sample: '加粗文本' },
  { key: 'italic', label: 'I', title: '斜体 *文本*', wrap: ['*', '*'], sample: '斜体文本' },
  { key: 'code', label: '</>', title: '行内代码 `code`', wrap: ['`', '`'], sample: 'code' },
  { key: 'h2', label: 'H2', title: '二级标题', prefix: '## ' },
  { key: 'list', label: '•', title: '项目列表', prefix: '- ' },
  { key: 'quote', label: '❝', title: '引用', prefix: '> ' },
  { key: 'table', label: '▦', title: '插入表格', block: '\n| 列 1 | 列 2 |\n| --- | --- |\n| 内容 | 内容 |\n' },
  { key: 'math', label: '∑', title: '行内数学公式 $...$', wrap: ['$', '$'], sample: 'E = mc^2' },
  { key: 'mathblock', label: '∑块', title: '块级数学公式 $$...$$', block: '\n$$\n\\int_0^1 x^2\\,dx = \\frac{1}{3}\n$$\n' },
  { key: 'chem', label: '⚗', title: '化学式 $\\ce{...}$', wrap: ['$\\ce{', '}$'], sample: 'H2SO4' },
  { key: 'codeblock', label: '{ }', title: '代码块', block: '\n```python\nprint("hello")\n```\n' },
  { key: 'flow', label: '流程', title: '流程图（mermaid）', block: '\n```mermaid\ngraph TD\n  A[开始] --> B{判断}\n  B -->|是| C[执行]\n  B -->|否| D[结束]\n```\n' },
  { key: 'mind', label: '导图', title: '思维导图（mermaid mindmap）', block: '\n```mermaid\nmindmap\n  root((主题))\n    分支一\n      要点\n    分支二\n      要点\n```\n' },
]

function apply(tool) {
  const el = inputRef.value && inputRef.value.textarea
  const text = props.modelValue || ''
  const start = el ? el.selectionStart : text.length
  const end = el ? el.selectionEnd : text.length
  const selected = text.slice(start, end)
  let insert, caret

  if (tool.wrap) {
    const body = selected || tool.sample || ''
    insert = tool.wrap[0] + body + tool.wrap[1]
    caret = start + tool.wrap[0].length + body.length
  } else if (tool.prefix) {
    const lines = (selected || '列表项').split('\n')
    insert = lines.map(l => tool.prefix + l).join('\n')
    caret = start + insert.length
  } else {
    insert = tool.block || ''
    caret = start + insert.length
  }

  emit('update:modelValue', text.slice(0, start) + insert + text.slice(end))
  requestAnimationFrame(() => {
    if (!el) return
    el.focus()
    el.setSelectionRange(caret, caret)
  })
}
</script>

<style scoped>
.md-field { width: 100%; }
.mf-bar { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; }
.mf-btn {
  min-width: 28px; height: 24px; padding: 0 6px; cursor: pointer;
  border: 1px solid var(--el-border-color, #dcdfe6); border-radius: 4px;
  background: var(--el-bg-color, #fff); color: var(--el-text-color-regular, #606266);
  font-size: 12px; line-height: 1;
}
.mf-btn:hover { color: var(--el-color-primary, #409eff); border-color: var(--el-color-primary, #409eff); }
.mf-spacer { flex: 1; }
.mf-preview {
  margin-top: 8px; padding: 10px 12px; max-height: 360px; overflow: auto;
  border: 1px dashed var(--el-border-color, #dcdfe6); border-radius: 8px;
  background: var(--el-fill-color-lighter, #fafafa);
}
</style>
