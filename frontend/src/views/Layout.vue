<template>
  <div class="layout-wrapper">
    <aside class="sidebar" :class="{ collapsed: isCollapsed }">
      <div class="sidebar-header">
        <div class="brand" @click="goPortal">
          <div class="brand-icon">
            <el-icon :size="28"><School /></el-icon>
          </div>
          <span v-if="!isCollapsed" class="brand-text">考试系统</span>
        </div>
        <el-button
          class="collapse-btn"
          text
          @click="isCollapsed = !isCollapsed"
        >
          <el-icon :size="18"><Fold v-if="!isCollapsed" /><Expand v-else /></el-icon>
        </el-button>
      </div>

      <div class="sidebar-menu">
        <div class="module-switch" @click="goPortal">
          <div class="menu-icon">
            <el-icon :size="20"><Grid /></el-icon>
          </div>
          <span v-if="!isCollapsed" class="menu-text">切换模块</span>
          <div v-if="isCollapsed" class="menu-tooltip">切换模块</div>
        </div>
        <div v-if="!isCollapsed" class="module-divider"></div>
        <div
          v-for="item in menuItems"
          :key="item.path"
          class="menu-item"
          :class="{ active: $route.path === item.path }"
          @click="$router.push(item.path)"
        >
          <div class="menu-icon">
            <el-icon :size="20">
              <component :is="item.icon" />
            </el-icon>
          </div>
          <span v-if="!isCollapsed" class="menu-text">{{ item.label }}</span>
          <div v-if="!isCollapsed && item.badge" class="menu-badge">{{ item.badge }}</div>
          <div v-if="isCollapsed" class="menu-tooltip">{{ item.label }}</div>
        </div>
      </div>

      <div class="sidebar-footer">
        <div class="user-card">
          <el-avatar :size="36" class="user-avatar">
            {{ auth.user?.username?.charAt(0)?.toUpperCase() }}
          </el-avatar>
          <div v-if="!isCollapsed" class="user-info">
            <div class="user-name">{{ auth.user?.username }}</div>
            <div class="user-role">{{ auth.user?.role === 'teacher' ? '教师' : '学生' }}</div>
          </div>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <header class="top-header">
        <div class="breadcrumb" @click="goPortal">
          <el-icon :size="16" class="breadcrumb-icon"><HomeFilled /></el-icon>
          <span class="breadcrumb-text">{{ currentPageName }}</span>
        </div>
        <div class="header-actions">
          <el-dropdown trigger="click" class="action-item" @command="handleNotificationCommand">
            <div class="notification-btn">
              <el-icon :size="20"><Bell /></el-icon>
              <span v-if="unreadCount" class="notification-badge">{{ unreadCount }}</span>
            </div>
            <template #dropdown>
              <el-dropdown-menu style="width: 340px; padding: 0;">
                <div class="notification-header">
                  <span class="notification-title">通知消息</span>
                  <span class="notification-clear" @click.stop="markAllAsRead">全部已读</span>
                  <span class="notification-clear ml-2" @click.stop="clearAllNotifications">清空全部</span>
                </div>
                <div v-if="notifications.length" class="notification-list">
                  <div 
                    v-for="item in notifications" 
                    :key="item.id" 
                    class="notification-item"
                    :class="{ read: item.read }"
                    @click="handleNotificationClick(item)"
                  >
                    <div :class="['notification-icon', item.type]">
                      <el-icon :size="16"><Check v-if="item.type === 'success'" /><Warning v-else-if="item.type === 'warning'" /><InfoFilled v-else /></el-icon>
                    </div>
                    <div class="notification-content">
                      <div class="notification-title">{{ item.title }}</div>
                      <div v-if="item.content" class="notification-desc">{{ item.content }}</div>
                      <div class="notification-time">{{ item.time_ago }}</div>
                    </div>
                    <div class="notification-delete" @click.stop="deleteNotification(item)">
                      <el-icon :size="14"><Close /></el-icon>
                    </div>
                  </div>
                </div>
                <div v-else class="notification-empty">
                  <el-icon :size="32" class="empty-bell"><Bell /></el-icon>
                  <p>暂无通知消息</p>
                </div>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button 
            text 
            circle 
            class="theme-toggle"
            :title="theme.isDark ? '切换到亮色模式' : '切换到暗色模式'"
            @click="theme.toggleTheme"
          >
            <el-icon :size="20"><Sunny v-if="theme.isDark" /><Moon v-else /></el-icon>
          </el-button>
          <el-dropdown @command="handleCommand">
            <div class="user-dropdown">
              <el-avatar :size="32" class="avatar-gradient">
                {{ auth.user?.username?.charAt(0)?.toUpperCase() }}
              </el-avatar>
              <span v-if="!isMobile" class="dropdown-name">{{ auth.user?.username }}</span>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">
                  <el-icon><User /></el-icon>个人资料
                </el-dropdown-item>
                <el-dropdown-item command="settings">
                  <el-icon><Setting /></el-icon>系统设置
                </el-dropdown-item>
                <el-dropdown-item divided command="logout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <div class="page-content">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useThemeStore } from '../stores/theme'
import { ElMessage, ElNotification } from 'element-plus'
import { getSocket, joinUserRoom, leaveUserRoom } from '../utils/socket'
import {
  Document, Collection, HomeFilled, Bell, User, Setting,
  SwitchButton, ArrowDown, School, Fold, Expand, Grid,
  Star, Calendar, VideoPlay, TrendCharts, Medal, Trophy, Lightning,
  Sunny, Moon, Check, Warning, InfoFilled,
  Money, EditPen, Tickets, Close, Reading
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const theme = useThemeStore()
const isCollapsed = ref(false)
const isMobile = ref(false)

const checkMobile = () => {
  isMobile.value = window.innerWidth < 768
  if (isMobile.value) {
    isCollapsed.value = true
  }
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})

const notifications = ref([])
const notificationPolling = ref(null)

// 通知接口已改为 JWT 鉴权（身份取自 token，不再信任 user_id 参数）
const authFetch = (url, options = {}) => {
  const token = localStorage.getItem('token')
  return fetch(url, {
    ...options,
    credentials: 'include',
    headers: {
      ...(options.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  })
}

const unreadCount = computed(() => {
  return notifications.value.filter(n => !n.read).length
})

const fetchNotifications = async () => {
  if (!auth.user) return

  try {
    const response = await authFetch('/api/notifications')
    const data = await response.json()
    notifications.value = data.notifications || []
  } catch (error) {
    console.error('获取通知失败:', error)
  }
}

const markAsRead = async (notificationId) => {
  try {
    await authFetch(`/api/notifications/${notificationId}/read`, {
      method: 'PUT'
    })
    const notification = notifications.value.find(n => n.id === notificationId)
    if (notification) {
      notification.read = true
    }
  } catch (error) {
    console.error('标记已读失败:', error)
  }
}

const markAllAsRead = async () => {
  if (!auth.user) return

  try {
    await authFetch('/api/notifications/read_all', {
      method: 'PUT',
    })
    notifications.value.forEach(n => n.read = true)
    ElMessage.success('所有通知已标记为已读')
  } catch (error) {
    console.error('标记全部已读失败:', error)
  }
}

const clearAllNotifications = async () => {
  if (!auth.user) return

  try {
    await authFetch('/api/notifications/clear_all', {
      method: 'DELETE'
    })
    notifications.value = []
    ElMessage.success('已清空所有通知')
  } catch (error) {
    console.error('清空通知失败:', error)
  }
}

const deleteNotification = async (notification) => {
  try {
    await authFetch(`/api/notifications/${notification.id}`, {
      method: 'DELETE'
    })
    notifications.value = notifications.value.filter(n => n.id !== notification.id)
  } catch (error) {
    console.error('删除通知失败:', error)
  }
}

const handleNotificationClick = async (notification) => {
  await markAsRead(notification.id)
  
  if (notification.related_type === 'exam') {
    router.push(`/exams/${notification.related_id}`)
  } else if (notification.related_type === 'result') {
    router.push('/results')
  }
}

const handleNotificationCommand = () => {}

const startNotificationPolling = () => {
  if (notificationPolling.value) {
    clearInterval(notificationPolling.value)
  }
  notificationPolling.value = setInterval(() => {
    fetchNotifications()
  }, 30000)
}

const stopNotificationPolling = () => {
  if (notificationPolling.value) {
    clearInterval(notificationPolling.value)
    notificationPolling.value = null
  }
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
  if (auth.user) {
    fetchNotifications()
    startNotificationPolling()
    setupRealtimeProfile()
  }
})

// ── 个人实时推送：段位/积分/勋章变化 toast（Socket.IO 不可用时静默，仅影响提示）──
const setupRealtimeProfile = () => {
  try {
    joinUserRoom(auth.user.id, auth.token)
    const socket = getSocket()
    socket.on('profile_update', (data) => {
      if (data.tier_changed) {
        ElNotification({
          title: '段位变化',
          message: `段位 ${data.old_tier} → ${data.tier}（${data.points} 分）`,
          type: data.points > (data.old_points ?? 0) ? 'success' : 'info',
        })
      } else {
        ElMessage.info(`竞技积分 +${data.gained}，当前 ${data.points} 分`)
      }
    })
    socket.on('badge_granted', (badge) => {
      ElNotification({
        title: `获得勋章：${badge.name}`,
        message: badge.description,
        type: 'success',
      })
    })
  } catch (e) {
    console.warn('实时推送连接失败，已降级:', e)
  }
}

const teardownRealtimeProfile = () => {
  if (!auth.user) return
  try {
    const socket = getSocket()
    socket.off('profile_update')
    socket.off('badge_granted')
    leaveUserRoom(auth.user.id)
  } catch (e) { /* 忽略 */ }
}

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
  stopNotificationPolling()
  teardownRealtimeProfile()
})

const iconMap = {
  Document, Collection, HomeFilled, Bell, User, Setting,
  SwitchButton, ArrowDown, School, Fold, Expand, Grid,
  Star, Calendar, VideoPlay, TrendCharts, Medal, Trophy, Lightning,
  Money, EditPen, Tickets, Reading
}

// 按模块分组的菜单：与路由 meta.module 对应，新增模块只需在此加分组
const moduleMenus = {
  exam: {
    teacher: [
      { path: '/questions', label: '题库管理', icon: iconMap.Document },
      { path: '/majors', label: '专业管理', icon: iconMap.Collection },
      { path: '/ai-generate', label: 'AI出题', icon: iconMap.Star },
      { path: '/exams', label: '考试管理', icon: iconMap.Calendar },
      { path: '/results', label: '成绩管理', icon: iconMap.TrendCharts },
      { path: '/results/analysis', label: '成绩分析', icon: iconMap.Medal },
    ],
    student: [
      { path: '/student', label: '我的考试', icon: iconMap.VideoPlay },
      { path: '/results', label: '成绩查询', icon: iconMap.Medal },
    ]
  },
  competition: {
    teacher: [
      { path: '/competitions', label: '竞赛管理', icon: iconMap.Trophy },
      { path: '/teams', label: '战队管理', icon: iconMap.User },
      { path: '/study-profile', label: '学情画像', icon: iconMap.TrendCharts },
    ],
    student: [
      { path: '/competitions', label: '竞赛广场', icon: iconMap.Trophy },
      { path: '/competitions/pk', label: 'PK对战', icon: iconMap.Lightning },
      { path: '/rank', label: '我的段位', icon: iconMap.Medal },
      { path: '/teams', label: '战队', icon: iconMap.User },
      { path: '/study-profile', label: '学情画像', icon: iconMap.TrendCharts },
    ]
  },
  bounty: {
    teacher: [
      { path: '/bounties', label: '悬赏大厅', icon: iconMap.Money },
      { path: '/bounties/publish', label: '发布悬赏', icon: iconMap.EditPen },
      { path: '/bounties/mine', label: '我的悬赏', icon: iconMap.Tickets },
    ],
    student: [
      { path: '/bounties', label: '悬赏大厅', icon: iconMap.Money },
      { path: '/bounties/publish', label: '发布悬赏', icon: iconMap.EditPen },
      { path: '/bounties/mine', label: '我的悬赏', icon: iconMap.Tickets },
    ]
  },
  learning: {
    teacher: [
      { path: '/learning', label: '学习首页', icon: iconMap.Reading },
      { path: '/learning/wrong', label: '错题本', icon: iconMap.Document },
      { path: '/learning/practice', label: '自由刷题', icon: iconMap.EditPen },
      { path: '/learning/plan', label: '学习计划', icon: iconMap.Star },
      { path: '/learning/report', label: '学习报告', icon: iconMap.TrendCharts },
    ],
    student: [
      { path: '/learning', label: '学习首页', icon: iconMap.Reading },
      { path: '/learning/wrong', label: '错题本', icon: iconMap.Document },
      { path: '/learning/practice', label: '自由刷题', icon: iconMap.EditPen },
      { path: '/learning/plan', label: '学习计划', icon: iconMap.Star },
      { path: '/learning/report', label: '学习报告', icon: iconMap.TrendCharts },
    ]
  }
}

const currentModule = computed(() => route.meta?.module || 'exam')

const menuItems = computed(() => {
  const role = auth.user?.role === 'teacher' ? 'teacher' : 'student'
  return moduleMenus[currentModule.value]?.[role] || []
})

const currentPageName = computed(() => {
  const items = menuItems.value
  if (!Array.isArray(items)) return '首页'
  const item = items.find(i => i.path === route.path)
  return item?.label || '首页'
})

const handleCommand = (cmd) => {
  if (cmd === 'logout') {
    auth.logout()
    ElMessage.success('已安全退出')
    router.push('/home')
  } else if (cmd === 'profile') {
    router.push('/profile')
  } else if (cmd === 'settings') {
    router.push('/settings')
  }
}

const goPortal = () => {
  router.push('/portal')
}
</script>

<style scoped>
.layout-wrapper {
  display: flex;
  height: 100vh;
  background: var(--bg-secondary);
}

.sidebar {
  width: 260px;
  background: var(--bg-sidebar);
  display: flex;
  flex-direction: column;
  transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  z-index: 100;
  box-shadow: 4px 0 20px rgba(0, 0, 0, 0.1);
}

.sidebar.collapsed {
  width: 72px;
}

.sidebar-header {
  padding: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  cursor: pointer;
}

.brand-icon {
  width: 48px;
  height: 48px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
  box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
}

.brand-text {
  color: white;
  font-size: 22px;
  font-weight: 700;
  white-space: nowrap;
  letter-spacing: 0.5px;
}

.collapse-btn {
  color: rgba(255, 255, 255, 0.5);
  padding: 10px;
  border-radius: 10px;
  transition: all 0.2s ease;
}

.collapse-btn:hover {
  color: white;
  background: rgba(255, 255, 255, 0.1);
}

.sidebar-menu {
  flex: 1;
  padding: 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.module-switch {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  color: rgba(255, 255, 255, 0.85);
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2) 0%, rgba(139, 92, 246, 0.2) 100%);
  border: 1px solid rgba(99, 102, 241, 0.3);
  position: relative;
  overflow: hidden;
}

.module-switch:hover {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.35) 0%, rgba(139, 92, 246, 0.35) 100%);
  color: white;
  transform: translateX(4px);
}

.module-divider {
  height: 1px;
  margin: 6px 4px 10px;
  background: linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, 0.12) 20%, rgba(255, 255, 255, 0.12) 80%, transparent 100%);
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  color: rgba(255, 255, 255, 0.6);
  position: relative;
  overflow: hidden;
}

.menu-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  width: 3px;
  height: 100%;
  background: linear-gradient(180deg, #6366f1 0%, #8b5cf6 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.menu-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: white;
  transform: translateX(4px);
}

.menu-item.active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.25) 0%, rgba(139, 92, 246, 0.25) 100%);
  color: white;
  box-shadow: 0 4px 20px rgba(99, 102, 241, 0.3);
}

.menu-item.active::before {
  opacity: 1;
}

.menu-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.menu-text {
  font-size: 15px;
  font-weight: 500;
  white-space: nowrap;
}

.menu-badge {
  margin-left: auto;
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: white;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 12px;
}

.menu-tooltip {
  position: absolute;
  left: 100%;
  top: 50%;
  transform: translateY(-50%);
  margin-left: 12px;
  padding: 8px 16px;
  background: #1e293b;
  color: white;
  font-size: 13px;
  font-weight: 500;
  border-radius: 10px;
  white-space: nowrap;
  opacity: 0;
  visibility: hidden;
  transition: all 0.25s ease;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
  pointer-events: none;
  z-index: 1000;
}

.menu-tooltip::before {
  content: '';
  position: absolute;
  right: 100%;
  top: 50%;
  transform: translateY(-50%);
  border: 6px solid transparent;
  border-right-color: #1e293b;
}

.menu-item:hover .menu-tooltip {
  opacity: 1;
  visibility: visible;
  margin-left: 16px;
}

.sidebar-footer {
  padding: 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.user-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.04);
  transition: all 0.3s ease;
}

.user-card:hover {
  background: rgba(255, 255, 255, 0.08);
}

.user-avatar {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  font-weight: 600;
  flex-shrink: 0;
}

.user-info {
  overflow: hidden;
}

.user-name {
  color: white;
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
}

.user-role {
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
  margin-top: 3px;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.top-header {
  height: 72px;
  background: var(--bg-card);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
  z-index: 50;
  border-bottom: 1px solid var(--border-color);
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  padding: 10px 16px;
  border-radius: 10px;
  transition: all 0.25s ease;
}

.breadcrumb:hover {
  background: var(--bg-tertiary);
}

.breadcrumb-icon {
  color: var(--text-light);
}

.breadcrumb-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 18px;
}

.action-item {
  cursor: pointer;
}

.notification-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  border-radius: 12px;
  background: var(--bg-tertiary);
  color: var(--text-muted);
  position: relative;
  transition: all 0.3s ease;
}

.notification-btn:hover {
  background: var(--bg-secondary);
  color: var(--text-primary);
  transform: translateY(-2px);
}

.notification-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: white;
  font-size: 11px;
  font-weight: 600;
  min-width: 20px;
  height: 20px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 6px;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.4);
}

.theme-toggle {
  transition: all 0.3s ease;
  padding: 10px;
}

.theme-toggle:hover {
  background: var(--bg-tertiary);
  transform: rotate(180deg);
}

.user-dropdown {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  padding: 8px 14px;
  border-radius: 12px;
  transition: all 0.25s ease;
}

.user-dropdown:hover {
  background: var(--bg-tertiary);
}

.avatar-gradient {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  font-weight: 600;
}

.dropdown-name {
  font-size: 15px;
  font-weight: 500;
  color: var(--text-secondary);
}

.notification-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px;
  border-bottom: 1px solid var(--border-color);
}

.notification-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.notification-clear {
  font-size: 13px;
  color: var(--text-light);
  cursor: pointer;
  transition: color 0.2s ease;
}

.notification-clear:hover {
  color: #667eea;
}

.notification-list {
  padding: 8px;
  max-height: 320px;
  overflow-y: auto;
}

.notification-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.notification-item:hover {
  background: var(--bg-tertiary);
}

.notification-delete {
  flex-shrink: 0;
  margin-left: auto;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  opacity: 0;
  transition: all 0.2s ease;
}

.notification-item:hover .notification-delete {
  opacity: 1;
}

.notification-delete:hover {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.notification-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.notification-icon.success {
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
  color: #16a34a;
}

.notification-icon.warning {
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #d97706;
}

.notification-icon.info {
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  color: #2563eb;
}

.notification-content {
  flex: 1;
  min-width: 0;
}

.notification-content .notification-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.notification-desc {
  font-size: 13px;
  color: var(--text-light);
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.notification-time {
  font-size: 12px;
  color: var(--text-light);
}

.notification-item.read {
  opacity: 0.65;
}

.notification-item.read .notification-content .notification-title {
  font-weight: 400;
}

.notification-empty {
  padding: 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-light);
}

.empty-bell {
  margin-bottom: 14px;
}

.notification-empty p {
  font-size: 14px;
  margin: 0;
}

.page-content {
  flex: 1;
  padding: 28px 32px;
  overflow-y: auto;
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}

.dark .layout-wrapper {
  background: var(--bg-secondary);
  position: relative;
}

.dark .layout-wrapper::before {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: 
    radial-gradient(ellipse at top left, rgba(99, 102, 241, 0.08) 0%, transparent 50%),
    radial-gradient(ellipse at bottom right, rgba(139, 92, 246, 0.06) 0%, transparent 50%);
  pointer-events: none;
  z-index: 0;
}

.dark .sidebar {
  background: var(--bg-sidebar);
  border-right: 1px solid var(--glass-border);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  position: relative;
}

.dark .sidebar::before {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 1px;
  background: linear-gradient(180deg, 
    transparent 0%, 
    rgba(99, 102, 241, 0.2) 30%, 
    rgba(99, 102, 241, 0.2) 70%, 
    transparent 100%);
}

.dark .sidebar-header {
  border-bottom: 1px solid var(--glass-border);
  background: rgba(15, 23, 42, 0.5);
}

.dark .sidebar-footer {
  border-top: 1px solid var(--glass-border);
  background: rgba(15, 23, 42, 0.5);
}

.dark .menu-item {
  position: relative;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.dark .menu-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--gradient-primary);
  opacity: 0;
  transition: opacity 0.3s ease;
  border-radius: 0 4px 4px 0;
}

.dark .menu-item:hover {
  background: rgba(99, 102, 241, 0.08);
  color: #a5b4fc;
}

.dark .menu-item:hover::before {
  opacity: 0.5;
}

.dark .menu-item.active::before {
  opacity: 1;
}

.dark .menu-item.active {
  background: linear-gradient(90deg, rgba(99, 102, 241, 0.15) 0%, rgba(99, 102, 241, 0.02) 100%);
  box-shadow: inset 0 0 30px rgba(99, 102, 241, 0.05);
}

.dark .user-card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--glass-border);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.dark .main-content {
  background: transparent;
  position: relative;
  z-index: 1;
}

.dark .top-header {
  background: var(--glass-bg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--glass-border);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.dark .breadcrumb-text {
  color: var(--text-primary);
}

.dark .breadcrumb-icon {
  color: var(--text-light);
}

.dark .dropdown-name {
  color: var(--text-secondary);
}

.dark .user-dropdown:hover {
  background: var(--glass-bg-strong);
}

.dark .page-content {
  background: transparent;
}

.dark .theme-toggle:hover {
  background: var(--glass-bg-strong);
}

.dark .collapse-btn {
  color: rgba(255, 255, 255, 0.5);
}

.dark .collapse-btn:hover {
  color: white;
  background: rgba(255, 255, 255, 0.1);
}

.dark .notification-header {
  background: var(--bg-card);
  border-bottom-color: var(--border-color);
}

.dark .notification-title {
  color: var(--text-primary);
}

.dark .notification-clear {
  color: var(--text-light);
}

.dark .notification-list {
  background: var(--bg-card);
}

.dark .notification-item:hover {
  background: var(--bg-tertiary);
}

.dark .notification-content .notification-title {
  color: var(--text-secondary);
}

.dark .notification-time {
  color: var(--text-light);
}

.dark .el-dropdown-menu {
  background: var(--bg-card);
  border-color: var(--border-color);
}

.dark .el-dropdown-item {
  color: var(--text-secondary);
}

.dark .el-dropdown-item:hover {
  background: var(--bg-tertiary);
}

.dark .menu-tooltip {
  background: #334155;
  border: 1px solid #475569;
}

.dark .menu-tooltip::before {
  border-right-color: #334155;
}

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    height: 100vh;
    z-index: 1000;
    transform: translateX(0);
    transition: transform 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .sidebar.collapsed {
    transform: translateX(-100%);
  }

  .sidebar-header {
    padding: 16px;
  }

  .brand-icon {
    width: 40px;
    height: 40px;
  }

  .brand-text {
    font-size: 18px;
  }

  .sidebar-menu {
    padding: 16px 8px;
  }

  .menu-item {
    padding: 12px 16px;
    border-radius: 10px;
  }

  .sidebar-footer {
    padding: 16px;
  }

  .user-card {
    padding: 10px 12px;
    border-radius: 12px;
  }

  .top-header {
    padding: 0 16px;
    height: 64px;
  }

  .breadcrumb-text {
    font-size: 16px;
  }

  .header-actions {
    gap: 8px;
  }

  .notification-btn {
    width: 40px;
    height: 40px;
  }

  .page-content {
    padding: 16px;
  }

  .mobile-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 900;
    display: none;
  }

  .sidebar:not(.collapsed) + .mobile-overlay {
    display: block;
  }
}
</style>