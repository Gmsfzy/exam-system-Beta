<template>
  <div class="login-wrapper">
    <div class="bg-shapes">
      <div class="shape shape-1"></div>
      <div class="shape shape-2"></div>
      <div class="shape shape-3"></div>
      <div class="shape shape-4"></div>
    </div>

    <div class="login-container">
      <div class="welcome-section animate-fade-in">
        <div class="welcome-content">
          <div class="logo-icon">
            <el-icon :size="48" color="#fff"><School /></el-icon>
          </div>
          <h1 class="welcome-title">智汇学场</h1>
          <p class="welcome-subtitle">融合考试、竞赛、悬赏、自学的一体化智能学习平台</p>
          <div class="feature-list">
            <div class="feature-item">
              <el-icon><Check /></el-icon>
              <span>在线考试 · 智能组卷</span>
            </div>
            <div class="feature-item">
              <el-icon><Check /></el-icon>
              <span>答题竞赛 · PK 排位</span>
            </div>
            <div class="feature-item">
              <el-icon><Check /></el-icon>
              <span>悬赏征集 · 积分激励</span>
            </div>
            <div class="feature-item">
              <el-icon><Check /></el-icon>
              <span>自主学习 · 错题本</span>
            </div>
          </div>
        </div>
      </div>

      <div class="form-section animate-slide-up">
        <div class="glass-card">
          <div class="back-btn-container">
            <router-link to="/home" class="back-btn">
              <el-icon><ArrowLeft /></el-icon>
              <span>返回首页</span>
            </router-link>
          </div>
          <div class="form-header">
            <h2>创建账户</h2>
            <p>注册成为我们的用户</p>
          </div>

          <el-form :model="form" class="login-form" @keyup.enter="handleRegister">
            <el-form-item>
              <div class="input-label">用户名</div>
              <el-input
                v-model="form.username"
                placeholder="请输入用户名"
                size="large"
                :prefix-icon="User"
                class="custom-input"
              />
            </el-form-item>

            <el-form-item>
              <div class="input-label">邮箱（选填）</div>
              <el-input
                v-model="form.email"
                placeholder="请输入邮箱"
                size="large"
                :prefix-icon="Message"
                class="custom-input"
              />
            </el-form-item>

            <el-form-item>
              <div class="input-label">密码</div>
              <el-input
                v-model="form.password"
                type="password"
                placeholder="请输入密码"
                size="large"
                :prefix-icon="Lock"
                show-password
                class="custom-input"
              />
            </el-form-item>

            <el-form-item>
              <div class="input-label">确认密码</div>
              <el-input
                v-model="form.confirmPassword"
                type="password"
                placeholder="请再次输入密码"
                size="large"
                :prefix-icon="Lock"
                show-password
                class="custom-input"
              />
            </el-form-item>

            <el-form-item>
              <div class="input-label">角色选择</div>
              <div class="role-selector">
                <el-radio-group v-model="form.role">
                  <el-radio-button value="teacher">
                    <el-icon :size="16"><School /></el-icon>
                    教师
                  </el-radio-button>
                  <el-radio-button value="student">
                    <el-icon :size="16"><User /></el-icon>
                    学生
                  </el-radio-button>
                </el-radio-group>
              </div>
            </el-form-item>

            <div class="form-options">
              <el-checkbox v-model="form.agree">我已阅读并同意服务条款</el-checkbox>
            </div>

            <el-form-item>
              <el-button
                type="primary"
                size="large"
                @click="handleRegister"
                :loading="loading"
                class="login-btn"
              >
                <el-icon class="mr-2"><Plus /></el-icon>
                立即注册
              </el-button>
            </el-form-item>
          </el-form>

          <div class="register-footer">
            <span>已有账户？</span>
            <router-link to="/login" class="register-link">立即登录</router-link>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus'
import { User, Lock, ArrowRight, ArrowLeft, School, Check, Message, Plus } from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({ 
  username: '', 
  email: '', 
  password: '', 
  confirmPassword: '',
  role: 'student',
  agree: false 
})

const handleRegister = async () => {
  if (!form.username) {
    ElMessage.warning('请输入用户名')
    return
  }
  if (!form.password) {
    ElMessage.warning('请输入密码')
    return
  }
  if (form.password !== form.confirmPassword) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  if (!form.agree) {
    ElMessage.warning('请同意服务条款')
    return
  }
  
  loading.value = true
  try {
    await auth.register(form.username, form.password, form.email, form.role)
    ElMessage.success('注册成功！')
    router.push('/')
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 40%, #f093fb 70%, #f5576c 100%);
  position: relative;
  overflow: hidden;
  transition: background 0.5s ease;
}

.bg-shapes {
  position: absolute;
  inset: 0;
  overflow: hidden;
  z-index: 0;
}
.shape {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.4;
  animation: float 12s ease-in-out infinite;
}
.shape-1 {
  width: 500px; height: 500px;
  background: rgba(255,255,255,0.25);
  top: -150px; left: -150px;
  animation-delay: 0s;
}
.shape-2 {
  width: 400px; height: 400px;
  background: rgba(255,255,255,0.18);
  bottom: -100px; right: -100px;
  animation-delay: 3s;
}
.shape-3 {
  width: 280px; height: 280px;
  background: rgba(255,255,255,0.12);
  top: 40%; left: 20%;
  animation-delay: 6s;
}
.shape-4 {
  width: 350px; height: 350px;
  background: rgba(255,255,255,0.15);
  bottom: 30%; right: 15%;
  animation-delay: 9s;
}

@keyframes float {
  0%, 100% { 
    transform: translateY(0) translateX(0) rotate(0deg) scale(1); 
    opacity: 0.4;
  }
  25% { 
    transform: translateY(-40px) translateX(20px) rotate(3deg) scale(1.05); 
    opacity: 0.5;
  }
  50% { 
    transform: translateY(-20px) translateX(-10px) rotate(-3deg) scale(0.95); 
    opacity: 0.35;
  }
  75% { 
    transform: translateY(-60px) translateX(30px) rotate(2deg) scale(1.02); 
    opacity: 0.45;
  }
}

.login-container {
  display: flex;
  gap: 40px;
  align-items: center;
}

.welcome-section {
  flex: 1;
  color: white;
}
.welcome-content {
  padding: 40px;
}
.logo-icon {
  width: 80px;
  height: 80px;
  background: rgba(255,255,255,0.2);
  backdrop-filter: blur(10px);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 30px;
  border: 1px solid rgba(255,255,255,0.3);
}
.welcome-title {
  font-size: 42px;
  font-weight: 700;
  margin-bottom: 12px;
  text-shadow: 0 2px 10px rgba(0,0,0,0.1);
}
.welcome-subtitle {
  font-size: 18px;
  opacity: 0.9;
  margin-bottom: 40px;
  font-weight: 300;
}
.feature-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 15px;
  opacity: 0.9;
}
.feature-item .el-icon {
  width: 28px;
  height: 28px;
  background: rgba(255,255,255,0.2);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.form-section {
  width: 440px;
}
.glass-card {
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(24px);
  border-radius: 32px;
  padding: 48px;
  box-shadow: 
    0 25px 50px rgba(0,0,0,0.15),
    0 0 0 1px rgba(255,255,255,0.3),
    inset 0 1px 0 rgba(255,255,255,0.8);
  border: 1px solid rgba(255,255,255,0.4);
  position: relative;
  overflow: hidden;
}
.glass-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 25%, #f093fb 50%, #f5576c 75%, #667eea 100%);
  background-size: 200% 100%;
  animation: gradientSlide 4s linear infinite;
}

@keyframes gradientSlide {
  0% { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}
.back-btn-container {
  display: flex;
  justify-content: flex-start;
  margin-bottom: 8px;
}
.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  color: #64748b;
  text-decoration: none;
  font-size: 14px;
  border-radius: 12px;
  transition: all 0.3s ease;
}
.back-btn:hover {
  color: #334155;
  background: rgba(0,0,0,0.05);
}
.back-btn .el-icon {
  font-size: 16px;
}
.form-header {
  text-align: center;
  margin-bottom: 32px;
}
.form-header h2 {
  font-size: 28px;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 8px;
}
.form-header p {
  color: #64748b;
  font-size: 15px;
}

.input-label {
  font-size: 14px;
  font-weight: 500;
  color: #334155;
  margin-bottom: 6px;
}
.custom-input :deep(.el-input__wrapper) {
  border-radius: 12px;
  padding: 8px 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  transition: all 0.3s;
}
.custom-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 2px 8px rgba(59,130,246,0.15);
}
.custom-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 3px rgba(59,130,246,0.2);
}

.role-selector {
  display: flex;
  gap: 8px;
}

.form-options {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  margin-bottom: 24px;
  font-size: 14px;
}

.login-btn {
  width: 100%;
  border-radius: 16px;
  height: 52px;
  font-size: 16px;
  font-weight: 600;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  box-shadow: 0 4px 15px rgba(102,126,234,0.35);
}
.login-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.2) 0%, transparent 50%);
}
.login-btn:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 30px rgba(102,126,234,0.5);
}
.login-btn:active {
  transform: translateY(-1px);
}

.register-footer {
  text-align: center;
  margin-top: 20px;
  font-size: 14px;
  color: #64748b;
}
.register-link {
  color: #667eea;
  font-weight: 600;
  text-decoration: none;
  margin-left: 6px;
  transition: color 0.3s;
}
.register-link:hover {
  color: #764ba2;
}

.animate-fade-in {
  animation: fadeIn 0.8s ease-out;
}
.animate-slide-up {
  animation: slideUp 0.6s ease-out 0.2s both;
}
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(30px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 768px) {
  .login-container {
    flex-direction: column;
  }
  .welcome-section {
    display: none;
  }
  .form-section {
    width: 100%;
    max-width: 420px;
  }
}

.dark .login-wrapper {
  background: linear-gradient(135deg, #020617 0%, #0f172a 25%, #1e1b4b 50%, #0f172a 75%, #020617 100%);
}

.dark .shape {
  opacity: 0.25;
}

.dark .shape-1 {
  background: rgba(99, 102, 241, 0.4);
}

.dark .shape-2 {
  background: rgba(139, 92, 246, 0.35);
}

.dark .shape-3 {
  background: rgba(236, 72, 153, 0.25);
}

.dark .shape-4 {
  background: rgba(59, 130, 246, 0.25);
}

.dark .logo-icon {
  background: rgba(99, 102, 241, 0.25);
  border-color: rgba(99, 102, 241, 0.4);
}

.dark .feature-item .el-icon {
  background: rgba(99, 102, 241, 0.2);
}

.dark .glass-card {
  background: rgba(15, 23, 42, 0.92);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-color: rgba(148, 163, 184, 0.18);
  box-shadow: 
    0 25px 50px rgba(0,0,0,0.5),
    0 0 0 1px rgba(255,255,255,0.04),
    inset 0 1px 0 rgba(255,255,255,0.06);
}

.dark .glass-card::before {
  background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 25%, #d946ef 50%, #ec4899 75%, #6366f1 100%);
}

.dark .form-header h2 {
  color: var(--text-primary);
}

.dark .form-header p {
  color: var(--text-muted);
}

.dark .input-label {
  color: var(--text-secondary);
}

.dark .custom-input :deep(.el-input__wrapper) {
  background: rgba(30, 41, 59, 0.9);
  border-color: rgba(148, 163, 184, 0.25);
}

.dark .custom-input :deep(.el-input__wrapper:hover) {
  border-color: rgba(148, 163, 184, 0.4);
}

.dark .custom-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.3);
  border-color: #6366f1;
}

.dark .custom-input :deep(.el-input__placeholder) {
  color: rgba(148, 163, 184, 0.6);
}

.dark .custom-input :deep(.el-input__inner) {
  color: var(--text-primary);
}

.dark .el-radio-button__inner {
  background: rgba(30, 41, 59, 0.7);
  border-color: rgba(148, 163, 184, 0.25);
  color: var(--text-secondary);
}

.dark .el-radio-button__inner:hover {
  background: rgba(30, 41, 59, 0.9);
}

.dark .el-radio-button__original-radio:checked + .el-radio-button__inner {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border-color: #6366f1;
  color: white;
}

.dark .el-checkbox__label {
  color: var(--text-secondary);
}

.dark .el-checkbox__inner {
  border-color: rgba(148, 163, 184, 0.35);
  background: rgba(30, 41, 59, 0.7);
}

.dark .el-checkbox__input.is-checked .el-checkbox__inner {
  background: #6366f1;
  border-color: #6366f1;
}

.dark .login-btn {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  box-shadow: 0 4px 15px rgba(99, 102, 241, 0.45);
}

.dark .login-btn:hover {
  box-shadow: 0 12px 30px rgba(99, 102, 241, 0.55);
}

.dark .register-footer {
  color: var(--text-secondary);
}

.dark .register-link {
  color: #818cf8;
}

.dark .register-link:hover {
  color: #a5b4fc;
}

.dark .back-btn {
  color: #94a3b8;
}

.dark .back-btn:hover {
  color: #e2e8f0;
  background: rgba(255, 255, 255, 0.08);
}
</style>