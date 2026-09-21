<template>
  <div ref="host" class="code-editor" :style="{ height }"></div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as monaco from 'monaco-editor'
// Vite 原生 ?worker：仅 Python（Monarch 基础语言）走编辑器基座 worker 即可
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'

self.MonacoEnvironment = {
  getWorker() {
    return new editorWorker()
  },
}

const props = defineProps({
  modelValue: { type: String, default: '' },
  language: { type: String, default: 'python' },
  readonly: { type: Boolean, default: false },
  height: { type: String, default: '360px' },
})
const emit = defineEmits(['update:modelValue'])

const host = ref(null)
let editor = null
let silent = false

const theme = () =>
  (document.documentElement.classList.contains('dark') ? 'vs-dark' : 'vs')

onMounted(() => {
  editor = monaco.editor.create(host.value, {
    value: props.modelValue || '',
    language: props.language,
    theme: theme(),
    readOnly: props.readonly,
    minimap: { enabled: false },
    fontSize: 13,
    lineNumbers: 'on',
    scrollBeyondLastLine: false,
    automaticLayout: true,
    tabSize: 4,
    wordWrap: 'off',
    padding: { top: 8, bottom: 8 },
  })
  editor.onDidChangeModelContent(() => {
    if (silent) return
    emit('update:modelValue', editor.getValue())
  })
})

watch(
  () => props.modelValue,
  (val) => {
    if (!editor) return
    const cur = editor.getValue()
    if (val !== cur) {
      silent = true
      editor.setValue(val || '')
      silent = false
    }
  }
)

watch(
  () => props.readonly,
  (v) => editor && editor.updateOptions({ readOnly: !!v })
)

onBeforeUnmount(() => {
  if (editor) {
    editor.dispose()
    editor = null
  }
})
</script>

<style scoped>
.code-editor {
  width: 100%;
  border: 1px solid var(--border-color, #dcdfe6);
  border-radius: 10px;
  overflow: hidden;
}
</style>
