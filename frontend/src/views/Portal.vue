<template>
  <div class="portal-wrapper">
    <!-- 背景装饰：极光光斑 + 极淡网格（仅增强景深，不拦截交互） -->
    <div class="bg-decor" aria-hidden="true">
      <span class="aurora aurora-a"></span>
      <span class="aurora aurora-b"></span>
      <span class="aurora aurora-c"></span>
      <span class="grid-overlay"></span>
    </div>
    <header class="portal-header">
      <div class="header-brand">
        <div class="brand-icon">
          <el-icon :size="26"><School /></el-icon>
        </div>
        <span class="brand-text">为学空间</span>
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
        <div class="hero-eyebrow">为学空间 · 一站式学练赛</div>
        <h1 class="hero-title">{{ greeting }}，<span class="hero-name">{{ auth.user?.username }}</span></h1>
        <p class="hero-subtitle">选择一个模块，即刻开始</p>
        <div class="hero-rule"></div>
      </div>

      <div class="portal-grid">
        <div
          v-for="(mod, i) in modules"
          :key="mod.key"
          class="portal-card"
          :class="{ disabled: mod.disabled }"
          :style="{ '--accent': accentOf(mod.gradient), '--accent-soft': softOf(mod.gradient, 0.16), '--accent-glow': softOf(mod.gradient, 0.5), '--grad': mod.gradient, '--i': i }"
          tabindex="0"
          @click="handleModuleClick(mod)"
          @keydown.enter="handleModuleClick(mod)"
        >
          <el-icon class="card-watermark" :size="128"><component :is="mod.icon" /></el-icon>
          <div v-if="mod.disabled" class="coming-badge">敬请期待</div>
          <div class="card-icon">
            <el-icon :size="30">
              <component :is="mod.icon" />
            </el-icon>
          </div>
          <h3 class="card-title">{{ mod.title }}</h3>
          <p class="card-desc">{{ mod.desc }}</p>
          <div class="card-enter">
            <span>进入模块</span>
            <el-icon class="enter-arrow" :size="16"><ArrowRight /></el-icon>
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
  School, Sunny, Moon, SwitchButton, ArrowRight, Notebook,
  ChatDotRound
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
  },
  {
    key: 'homework',
    title: '作业练习',
    desc: '发布题集/开放作业，自动判分与人工批改',
    icon: Notebook,
    gradient: 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)',
    path: '/homeworks/manage'
  },
  {
    key: 'community',
    title: '社区中心',
    desc: '发帖讨论、匿名求助，联动题目/作业/考试',
    icon: ChatDotRound,
    gradient: 'linear-gradient(135deg, #14b8a6 0%, #0d9488 100%)',
    path: '/community'
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
  },
  {
    key: 'homework',
    title: '作业练习',
    desc: '接收老师发布的作业，按时作答与提交',
    icon: Notebook,
    gradient: 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)',
    path: '/homeworks/my'
  },
  {
    key: 'community',
    title: '社区中心',
    desc: '交流答疑、分享经验，讨论联动题目和作业',
    icon: ChatDotRound,
    gradient: 'linear-gradient(135deg, #14b8a6 0%, #0d9488 100%)',
    path: '/community'
  }
]

const modules = computed(() => {
  return auth.user?.role === 'teacher' ? teacherModules : studentModules
})

// Aurora 卡片：从模块自身渐变里取主色，驱动图标着色与悬停霓虹，避免逐条硬编码
const accentOf = (grad) => (grad.match(/#[0-9a-fA-F]{6}/) || ['#6366f1'])[0]
const softOf = (grad, a) => {
  const h = accentOf(grad).slice(1)
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${a})`
}

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
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  overflow: hidden;
}

/* ── 背景装饰：极光光斑 + 极淡网格 ── */
.bg-decor {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
}
.aurora {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.3;
}
.aurora-a {
  width: 520px; height: 520px;
  top: -160px; left: -120px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.6), transparent 70%);
  animation: drift 18s ease-in-out infinite;
}
.aurora-b {
  width: 460px; height: 460px;
  top: 8%; right: -150px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.55), transparent 70%);
  animation: drift 22s ease-in-out infinite reverse;
}
.aurora-c {
  width: 520px; height: 520px;
  bottom: -220px; left: 28%;
  background: radial-gradient(circle, rgba(6, 182, 212, 0.5), transparent 70%);
  animation: drift 26s ease-in-out infinite;
}
.grid-overlay {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.06) 1px, transparent 1px);
  background-size: 44px 44px;
  -webkit-mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, #000 40%, transparent 100%);
  mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, #000 40%, transparent 100%);
}
@keyframes drift {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(40px, 30px) scale(1.08); }
  66% { transform: translate(-30px, 20px) scale(0.95); }
}

.portal-header {
  position: sticky;
  top: 0;
  z-index: 2;
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
  position: relative;
  z-index: 1;
  flex: 1;
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  padding: 48px 32px 64px;
}

.portal-hero {
  position: relative;
  text-align: center;
  margin-bottom: 48px;
}

.hero-eyebrow {
  display: inline-block;
  font-size: 12.5px;
  letter-spacing: 2px;
  font-weight: 600;
  color: var(--text-muted);
  padding: 6px 16px;
  border: 1px solid var(--border-color);
  border-radius: 9999px;
  background: rgba(99, 102, 241, 0.06);
  margin-bottom: 20px;
}

.hero-title {
  font-size: clamp(34px, 5vw, 50px);
  font-weight: 800;
  color: var(--text-primary);
  margin: 0 0 12px 0;
  letter-spacing: -0.5px;
  line-height: 1.12;
}

.hero-name {
  background: var(--gradient-primary);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtitle {
  font-size: 16px;
  color: var(--text-muted);
  margin: 0;
}

.hero-rule {
  width: 64px;
  height: 4px;
  border-radius: 2px;
  margin: 22px auto 0;
  background: var(--gradient-primary);
  opacity: 0.85;
}

.portal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 26px;
}

.portal-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-height: 236px;
  padding: 28px 26px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 22px;
  cursor: pointer;
  overflow: hidden;
  transition: transform 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.35s ease, border-color 0.35s ease;
  animation: cardIn 0.55s cubic-bezier(0.22, 0.61, 0.36, 1) both;
  animation-delay: calc(var(--i, 0) * 70ms);
}

@keyframes cardIn {
  from { opacity: 0; transform: translateY(22px) scale(0.98); }
  to { opacity: 1; transform: none; }
}

/* 右下角淡色大图标水印，增层次 */
.card-watermark {
  position: absolute;
  right: -18px;
  bottom: -24px;
  color: var(--accent);
  opacity: 0.07;
  pointer-events: none;
  z-index: 0;
  transition: opacity 0.35s ease, transform 0.35s ease;
}

.portal-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--grad);
  opacity: 0;
  transition: opacity 0.3s ease;
  z-index: 1;
}

.portal-card:hover {
  transform: translateY(-8px);
  border-color: var(--accent);
  box-shadow: 0 18px 44px var(--accent-glow), 0 0 0 1px var(--accent-soft);
}

.portal-card:hover::after { opacity: 1; }

.portal-card:hover .card-watermark {
  opacity: 0.12;
  transform: translate(-4px, -4px) rotate(-6deg);
}

.portal-card:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.portal-card.disabled {
  opacity: 0.6;
}

.portal-card.disabled:hover {
  transform: none;
  border-color: var(--border-color);
  box-shadow: none;
}

.portal-card.disabled:hover::after { opacity: 0; }

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
  z-index: 2;
}

.card-icon {
  position: relative;
  z-index: 1;
  width: 62px;
  height: 62px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 18px;
  background: var(--accent-soft);
  color: var(--accent);
  transition: background 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              color 0.35s ease, transform 0.35s ease, box-shadow 0.35s ease;
}

.portal-card:hover .card-icon {
  background: var(--grad);
  color: #fff;
  transform: scale(1.06) rotate(-3deg);
  box-shadow: 0 10px 24px var(--accent-glow);
}

.card-title {
  position: relative;
  z-index: 1;
  font-size: 19px;
  font-weight: 650;
  color: var(--text-primary);
  margin: 0 0 8px 0;
}

.card-desc {
  position: relative;
  z-index: 1;
  font-size: 13.5px;
  color: var(--text-muted);
  margin: 0 0 14px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-enter {
  position: relative;
  z-index: 1;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 14px;
  border-top: 1px solid var(--border-color);
  font-size: 13px;
  font-weight: 600;
  color: var(--text-light);
  transition: color 0.3s ease, border-color 0.3s ease;
}

.enter-arrow {
  transition: transform 0.3s ease;
}

.portal-card:hover .card-enter {
  color: var(--accent);
  border-top-color: var(--accent-soft);
}

.portal-card:hover .enter-arrow {
  transform: translateX(4px);
}

.dark .portal-wrapper {
  background: var(--bg-secondary);
}

.dark .aurora {
  opacity: 0.55;
}

.dark .portal-header {
  background: var(--glass-bg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom-color: var(--glass-border);
}

.dark .hero-eyebrow {
  background: rgba(99, 102, 241, 0.1);
  border-color: var(--glass-border);
}

.dark .portal-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.dark .portal-card:hover {
  box-shadow: 0 18px 48px var(--accent-glow), inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

/* 玻璃卡上的分隔线用半透明白，避免 glass-border 过淡看不出 footer */
.dark .card-enter {
  border-top-color: rgba(255, 255, 255, 0.08);
}

@media (max-width: 768px) {
  .portal-header {
    padding: 0 16px;
  }

  .portal-main {
    padding: 32px 16px 48px;
  }

  .portal-grid {
    grid-template-columns: 1fr;
    gap: 18px;
  }

  .portal-card {
    min-height: 0;
  }

  .hero-title {
    font-size: 28px;
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
