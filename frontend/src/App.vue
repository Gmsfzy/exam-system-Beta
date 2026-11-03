<template>
  <el-config-provider>
    <router-view />
  </el-config-provider>
</template>

<script setup>
// 主题切换由 stores/theme.js 通过 html.dark class + style.css 自定义变量实现;
// el-config-provider 无 theme prop(旧 Element UI 写法),已移除以消除 console 警告。
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
</style>
