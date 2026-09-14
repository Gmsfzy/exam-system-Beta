<template>
  <div class="portal-wrapper">
    <header class="portal-header">
      <div class="header-brand">
        <div class="brand-icon">
          <el-icon :size="26"><School /></el-icon>
        </div>
        <span class="brand-text">智汇学场</span>
      </div>
      <div class="header-actions">
        <el-button
          text
          circle
          class="theme-toggle"
          :title="theme.isDark ? '切换到亮色模式' : '切换到暗色模式'"
          @click="theme.toggleTheme"
        >
          <el-icon :size="20"><Sunny v-if="theme.isDark" /><Moon v-else /></el-icon>
        </el-button>
        <div class="user-chip">
          <el-avatar :size="34" class="user-avatar">
            {{ auth.user?.username?.charAt(0)?.toUpperCase() }}
          </el-avatar>
          <span class="user-name">{{ auth.user?.username }}</span>
        </div>
        <el-button text class="logout-btn" @click="handleLogout">
          <el-icon :size="18"><SwitchButton /></el-icon>
          <span class="logout-text">退出</span>
        </el-button>
      </div>
    </header>

    <main class="portal-main">
      <div class="portal-hero">
        <h1 class="hero-title">{{ greeting }}，{{ auth.user?.username }}</h1>
        <p class="hero-subtitle">请选择一个功能模块开始使用</p>
      </div>

      <div class="portal-grid">
        <div
          v-for="mod in modules"
          :key="mod.key"
          class="portal-card"
          :class="{ disabled: mod.disabled }"
          @click="handleModuleClick(mod)"
        >
          <div v-if="mod.disabled" class="coming-badge">敬请期待</div>
          <div class="card-icon" :style="{ background: mod.gradient }">
            <el-icon :size="34" color="white">
              <component :is="mod.icon" />
            </el-icon>
          </div>
          <h3 class="card-title">{{ mod.title }}</h3>
          <p class="card-desc">{{ mod.desc }}</p>
          <div class="card-enter">
            <span>进入模块</span>
            <el-icon :size="16"><ArrowRight /></el-icon>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useThemeStore } from '../stores/theme'
import { ElMessage } from 'element-plus'
import {
  Calendar, VideoPlay, Trophy, Money, Reading,
  School, Sunny, Moon, SwitchButton, ArrowRight
} from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuthStore()
const theme = useThemeStore()
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

const teacherModules = [
  {
    key: 'exam',
    title: '在线考试',
    desc: '题库管理、组卷发布、考试执行与成绩分析',
    icon: Calendar,
    gradient: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
    path: '/exams'
  },
  {
    key: 'competition',
    title: '答题竞赛',
    desc: '组织限时积分赛，实时排行激烈角逐',
    icon: Trophy,
    gradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
    path: '/competitions'
  },
  {
    key: 'bounty',
    title: '征集悬赏',
    desc: '发布题目/答案悬赏，审核投稿共建题库',
    icon: Money,
    gradient: 'linear-gradient(135deg, #ec4899 0%, #db2777 100%)',
    path: '/bounties'
  },
  {
    key: 'learning',
    title: '自我学习',
    desc: '错题本 · 自由刷题 · 学习计划 · AI 答疑',
    icon: Reading,
    gradient: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)',
    path: '/learning'
  }
]

const studentModules = [
  {
    key: 'exam',
    title: '在线考试',
    desc: '参加老师发布的考试，查询历史成绩',
    icon: VideoPlay,
    gradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
    path: '/student'
  },
  {
    key: 'competition',
    title: '答题竞赛',
    desc: '参与竞赛挑战，冲击排行榜',
    icon: Trophy,
    gradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
    path: '/competitions'
  },
  {
    key: 'bounty',
    title: '征集悬赏',
    desc: '投稿题目和答案，被采纳赢取竞技积分',
    icon: Money,
    gradient: 'linear-gradient(135deg, #ec4899 0%, #db2777 100%)',
    path: '/bounties'
  },
  {
    key: 'learning',
    title: '自我学习',
    desc: '错题回顾 · 自由刷题 · 学习计划 · AI 答疑',
    icon: Reading,
    gradient: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)',
    path: '/learning'
  }
]

const modules = computed(() => {
  return auth.user?.role === 'teacher' ? teacherModules : studentModules
})

const handleModuleClick = (mod) => {
  if (mod.disabled) {
    ElMessage.info('该模块正在开发中，敬请期待')
    return
  }
  router.push(mod.path)
}

const handleLogout = () => {
  auth.logout()
  ElMessage.success('已安全退出')
  router.push('/home')
}
</script>

<style scoped>
.portal-wrapper {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
}

.portal-header {
  height: 76px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 40px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
}

.header-brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-icon {
  width: 46px;
  height: 46px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
}

.brand-text {
  font-size: 21px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 18px;
}

.theme-toggle {
  transition: all 0.3s ease;
  padding: 10px;
}

.theme-toggle:hover {
  background: var(--bg-tertiary);
  transform: rotate(180deg);
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 14px 6px 6px;
  border-radius: 20px;
  background: var(--bg-tertiary);
}

.user-avatar {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  font-weight: 600;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
}

.logout-btn {
  color: var(--text-muted);
  padding: 10px;
}

.logout-btn:hover {
  color: #ef4444;
  background: var(--bg-tertiary);
}

.portal-main {
  flex: 1;
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
  padding: 56px 32px;
}

.portal-hero {
  text-align: center;
  margin-bottom: 56px;
}

.hero-title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 12px 0;
}

.hero-subtitle {
  font-size: 16px;
  color: var(--text-muted);
  margin: 0;
}

.portal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 28px;
}

.portal-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 32px 28px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.portal-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.portal-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.14);
  border-color: rgba(99, 102, 241, 0.45);
}

.portal-card:hover::after {
  opacity: 1;
}

.portal-card.disabled {
  opacity: 0.6;
}

.portal-card.disabled:hover {
  transform: none;
  border-color: var(--border-color);
  box-shadow: none;
}

.coming-badge {
  position: absolute;
  top: 14px;
  right: -30px;
  transform: rotate(38deg);
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: white;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 36px;
  letter-spacing: 1px;
}

.card-icon {
  width: 66px;
  height: 66px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.25);
}

.card-title {
  font-size: 19px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px 0;
}

.card-desc {
  font-size: 13.5px;
  color: var(--text-muted);
  margin: 0 0 20px;
  line-height: 1.6;
}

.card-enter {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: auto;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-light);
  transition: all 0.3s ease;
}

.portal-card:hover .card-enter {
  color: #6366f1;
  gap: 10px;
}

.dark .portal-wrapper {
  background: var(--bg-secondary);
}

.dark .portal-header {
  background: var(--glass-bg);
  backdrop-filter: blur(16px);
  border-bottom-color: var(--glass-border);
}

.dark .portal-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
  backdrop-filter: blur(12px);
}

.dark .portal-card:hover {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
}

@media (max-width: 768px) {
  .portal-header {
    padding: 0 16px;
  }

  .portal-main {
    padding: 32px 16px;
  }

  .portal-grid {
    grid-template-columns: 1fr;
    gap: 18px;
  }

  .hero-title {
    font-size: 24px;
  }

  .brand-text {
    font-size: 17px;
  }

  .user-name,
  .logout-text {
    display: none;
  }
}
</style>
