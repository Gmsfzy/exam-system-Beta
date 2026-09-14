<template>
  <span ref="container" class="katex-renderer"></span>
</template>

<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({
  formula: {
    type: String,
    required: true
  },
  displayMode: {
    type: Boolean,
    default: false
  }
})

const container = ref(null)

const renderFormula = () => {
  if (!container.value || !props.formula) return
  
  try {
    const text = props.formula.replace(/\\\(/g, '').replace(/\\\)/g, '').replace(/\$\$/g, '').replace(/\$/g, '')
    katex.render(text, container.value, {
      displayMode: props.displayMode,
      throwOnError: false,
      strict: false
    })
  } catch (e) {
    container.value.textContent = props.formula
  }
}

onMounted(() => {
  nextTick(renderFormula)
})

watch(() => props.formula, () => {
  nextTick(renderFormula)
})
</script>

<style scoped>
.katex-renderer {
  font-size: 1em;
  line-height: 1.5;
}
</style>