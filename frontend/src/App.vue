<template>
  <el-config-provider :theme="themeConfig">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import { computed } from 'vue'
import { useThemeStore } from './stores/theme'

const themeStore = useThemeStore()

const themeConfig = computed(() => ({
  name: themeStore.isDark ? 'dark' : 'light',
  cssVars: themeStore.isDark ? {
    '--el-bg-color': '#1e293b',
    '--el-bg-color-page': '#0f172a',
    '--el-bg-color-secondary': '#334155',
    '--el-bg-color-tertiary': '#1e293b',
    '--el-text-color-primary': '#ffffff',
    '--el-text-color-regular': '#f1f5f9',
    '--el-text-color-secondary': '#cbd5e1',
    '--el-text-color-placeholder': '#64748b',
    '--el-border-color': 'rgba(148, 163, 184, 0.2)',
    '--el-input-bg-color': '#1e293b',
    '--el-input-border-color': 'rgba(148, 163, 184, 0.3)',
    '--el-input-text-color': '#f1f5f9',
    '--el-input-placeholder-color': '#64748b',
    '--el-select-dropdown-bg-color': '#1e293b',
    '--el-select-dropdown-text-color': '#f1f5f9',
    '--el-select-option-hover-bg-color': 'rgba(99, 102, 241, 0.15)',
    '--el-select-option-selected-bg-color': 'rgba(99, 102, 241, 0.25)',
    '--el-table-row-hover-bg-color': 'rgba(99, 102, 241, 0.18)',
    '--el-radio-button-bg-color': '#1e293b',
    '--el-radio-button-text-color': '#94a3b8',
    '--el-radio-button-active-bg-color': 'rgba(99, 102, 241, 0.25)',
    '--el-radio-button-active-text-color': '#a5b4fc',
    '--el-radio-button-border-color': 'rgba(148, 163, 184, 0.3)',
    '--el-textarea-bg-color': '#1e293b',
    '--el-textarea-border-color': 'rgba(148, 163, 184, 0.3)',
    '--el-textarea-text-color': '#f1f5f9',
    '--el-textarea-placeholder-color': '#64748b',
  } : {}
}))
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
</style>
