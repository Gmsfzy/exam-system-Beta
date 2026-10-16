<template>
  <div class="notfound-wrapper">
    <div class="error-card">
      <p class="error-code">404</p>
      <p class="error-title">页面不存在</p>
      <p class="error-msg">您访问的页面不存在或已被移除</p>
      <el-button type="primary" class="error-btn" @click="goHome">
        <el-icon style="margin-right: 6px;"><HomeFilled /></el-icon>
        返回首页
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { HomeFilled } from '@element-plus/icons-vue'

const router = useRouter()
const goHome = () => {
  // 有 token 回 Portal，无 token 回 Home
  router.push(localStorage.getItem('token') ? '/portal' : '/home')
}
</script>

<style scoped>
.notfound-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-secondary, #f3f4f6);
  font-family: -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
}
.error-card {
  background: var(--bg-card, #fff);
  border-radius: 16px;
  padding: 3rem 4rem;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.08);
  text-align: center;
  max-width: 90vw;
}
.error-code {
  font-size: 4rem;
  font-weight: 700;
  color: #667eea;
  margin: 0;
  line-height: 1.1;
}
.error-title {
  font-size: 1.25rem;
  color: var(--text-primary, #1f2937);
  margin: 0.5rem 0 1rem;
}
.error-msg {
  color: var(--text-regular, #6b7280);
  margin: 0 0 2rem;
}
.error-btn {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border: none;
  padding: 0.7rem 1.8rem;
  border-radius: 8px;
  font-size: 0.95rem;
}
</style>
