import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { ElMessage } from 'element-plus'

// 角色级路由保护（v4.11.1 前端权限护栏）
// - meta.public:           未登录可访问（登录/注册/欢迎页）
// - meta.requiresTeacher:  仅教师可访问（题库/考试管理/批改/AI治理/系统设置等）
// - meta.requiresStudent:  仅学生可访问（我的考试）
// - 未标 meta 的路由：登录后教师学生均可访问（页面内按 role 自行分支）
// 守卫层只做「堵 URL 直进」+提示，资源级权限仍由后端 RBAC（utils/permissions.py）兜底
const routes = [
  // ── 公开页（无需登录）──
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/register', name: 'Register', component: () => import('../views/Register.vue'), meta: { public: true } },
  { path: '/home', name: 'Home', component: () => import('../views/Home.vue'), meta: { public: true } },
  { path: '/portal', name: 'Portal', component: () => import('../views/Portal.vue') },

  // ── 主应用（Layout 嵌套）──
  {
    path: '/',
    component: () => import('../views/Layout.vue'),
    // 动态 redirect：有 token 直奔 Portal，无 token 回 Home，避免「/ -> /portal -> /home」双跳
    redirect: () => {
      try {
        return localStorage.getItem('token') ? '/portal' : '/home'
      } catch (e) {
        return '/home'
      }
    },
    children: [
      // ── 在线考试模块 ──
      { path: 'questions', name: 'Questions', component: () => import('../views/QuestionList.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'majors', name: 'Majors', component: () => import('../views/MajorList.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'majors/:id', name: 'MajorDetail', component: () => import('../views/MajorDetail.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'chapters/:id', name: 'ChapterList', component: () => import('../views/ChapterList.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'ai-generate', name: 'AiGenerate', component: () => import('../views/AiGenerate.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'exams', name: 'ExamDashboard', component: () => import('../views/ExamDashboard.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'exams/:id/edit', name: 'EditExam', component: () => import('../views/EditExam.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'exams/:id/monitor', name: 'ExamMonitor', component: () => import('../views/ExamMonitor.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'exams/:id/item-analysis', name: 'ExamItemAnalysis', component: () => import('../views/ExamItemAnalysis.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'exams/:id/plagiarism', name: 'PlagiarismCheck', component: () => import('../views/PlagiarismCheck.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'student', name: 'StudentDashboard', component: () => import('../views/StudentDashboard.vue'), meta: { module: 'exam', requiresStudent: true } },
      { path: 'results', name: 'ResultList', component: () => import('../views/ResultList.vue'), meta: { module: 'exam' } },
      { path: 'results/exam/:examId', name: 'ExamResults', component: () => import('../views/ExamResults.vue'), meta: { module: 'exam' } },
      { path: 'results/analysis', name: 'ResultAnalysis', component: () => import('../views/ResultAnalysis.vue'), meta: { module: 'exam', requiresTeacher: true } },
      { path: 'profile', name: 'UserProfile', component: () => import('../views/UserProfile.vue'), meta: { module: 'exam' } },
      { path: 'settings', name: 'SystemSettings', component: () => import('../views/SystemSettings.vue'), meta: { module: 'exam', requiresTeacher: true } },

      // ── 答题竞赛模块 ──
      { path: 'competitions', name: 'CompetitionHome', component: () => import('../views/CompetitionHome.vue'), meta: { module: 'competition' } },
      { path: 'competitions/pk', name: 'PkLobby', component: () => import('../views/PkLobby.vue'), meta: { module: 'competition' } },
      { path: 'competitions/pk/quick', name: 'QuickPk', component: () => import('../views/QuickPk.vue'), meta: { module: 'competition' } },
      { path: 'competitions/series', name: 'SeriesView', component: () => import('../views/SeriesView.vue'), meta: { module: 'competition' } },
      { path: 'competitions/:compId/leaderboard', name: 'CompetitionLeaderboard', component: () => import('../views/CompetitionLeaderboard.vue'), meta: { module: 'competition' } },
      { path: 'competitions/:compId/project', name: 'CompetitionProject', component: () => import('../views/CompetitionProject.vue'), meta: { module: 'competition' } },
      { path: 'competitions/:compId/ds', name: 'DsCompetition', component: () => import('../views/DsCompetition.vue'), meta: { module: 'competition' } },
      { path: 'competitions/:compId/ds-manage', name: 'DsManage', component: () => import('../views/DsManage.vue'), meta: { module: 'competition', requiresTeacher: true } },
      { path: 'competitions/pk/:battleId/replay', name: 'BattleReplay', component: () => import('../views/BattleReplay.vue'), meta: { module: 'competition' } },
      { path: 'competitions/certificates', name: 'CompetitionCertificates', component: () => import('../views/CompetitionCertificates.vue'), meta: { module: 'competition' } },
      { path: 'competitions/certificates/:id', name: 'CompetitionCertificateDetail', component: () => import('../views/CompetitionCertificates.vue'), meta: { module: 'competition' } },
      { path: 'rank', name: 'RankCenter', component: () => import('../views/RankCenter.vue'), meta: { module: 'competition' } },
      { path: 'rank/player/:userId', name: 'PublicProfile', component: () => import('../views/PublicProfile.vue'), meta: { module: 'competition' } },
      { path: 'teams', name: 'TeamCenter', component: () => import('../views/TeamCenter.vue'), meta: { module: 'competition' } },
      { path: 'study-profile', name: 'StudyProfile', component: () => import('../views/StudyProfile.vue'), meta: { module: 'competition' } },

      // ── 征集悬赏模块 ──
      { path: 'bounties', name: 'BountyPlaza', component: () => import('../views/BountyPlaza.vue'), meta: { module: 'bounty' } },
      { path: 'bounties/publish', name: 'BountyPublish', component: () => import('../views/BountyPublish.vue'), meta: { module: 'bounty' } },
      { path: 'bounties/mine', name: 'BountyMine', component: () => import('../views/BountyMine.vue'), meta: { module: 'bounty' } },
      { path: 'bounties/wallet', name: 'BountyWallet', component: () => import('../views/BountyWallet.vue'), meta: { module: 'bounty' } },
      { path: 'bounties/leaderboard', name: 'BountyLeaderboard', component: () => import('../views/BountyLeaderboard.vue'), meta: { module: 'bounty' } },
      { path: 'bounties/:id', name: 'BountyDetail', component: () => import('../views/BountyDetail.vue'), meta: { module: 'bounty' } },

      // ── 自主学习模块 ──
      { path: 'learning', name: 'LearningHome', component: () => import('../views/LearningHome.vue'), meta: { module: 'learning' } },
      { path: 'learning/today', name: 'TodayStudy', component: () => import('../views/TodayStudy.vue'), meta: { module: 'learning' } },
      { path: 'learning/my-knowledge', name: 'MyKnowledge', component: () => import('../views/MyKnowledge.vue'), meta: { module: 'learning' } },
      { path: 'learning/certificates', name: 'Certificates', component: () => import('../views/CertificateView.vue'), meta: { module: 'learning' } },
      { path: 'learning/certificates/:id', name: 'CertificateDetail', component: () => import('../views/CertificateView.vue'), meta: { module: 'learning' } },
      { path: 'learning/paths', name: 'MajorPaths', component: () => import('../views/MajorPathsView.vue'), meta: { module: 'learning' } },
      { path: 'learning/paths/:id', name: 'PathDetail', component: () => import('../views/PathDetailView.vue'), meta: { module: 'learning' } },
      { path: 'learning/node/:nodeId', name: 'NodeLearn', component: () => import('../views/NodeLearnView.vue'), meta: { module: 'learning' } },
      { path: 'learning/graph', name: 'KnowledgeGraph', component: () => import('../views/KnowledgeGraphView.vue'), meta: { module: 'learning' } },
      { path: 'learning/wrong', name: 'WrongNotebook', component: () => import('../views/WrongNotebook.vue'), meta: { module: 'learning' } },
      { path: 'learning/notes', name: 'StudyNotes', component: () => import('../views/StudyNotes.vue'), meta: { module: 'learning' } },
      { path: 'learning/practice', name: 'PracticeList', component: () => import('../views/PracticeList.vue'), meta: { module: 'learning' } },
      { path: 'learning/practice/:sessionId', name: 'PracticeDetail', component: () => import('../views/PracticeDetail.vue'), meta: { module: 'learning' } },
      { path: 'learning/plan', name: 'StudyPlan', component: () => import('../views/StudyPlan.vue'), meta: { module: 'learning' } },
      { path: 'learning/report', name: 'StudyReport', component: () => import('../views/StudyReport.vue'), meta: { module: 'learning' } },
      { path: 'learning/materials', name: 'MaterialLibrary', component: () => import('../views/MaterialLibrary.vue'), meta: { module: 'learning' } },
      { path: 'learning/explore', name: 'ExploreSquare', component: () => import('../views/ExploreSquare.vue'), meta: { module: 'learning' } },
      { path: 'learning/user/:uid', name: 'LearningUserHome', component: () => import('../views/UserHome.vue'), meta: { module: 'learning' } },
      { path: 'learning/ai-governance', name: 'AiGovernance', component: () => import('../views/AiGovernance.vue'), meta: { module: 'learning', requiresTeacher: true } },

      // ── 作业练习模块（v5.0）──
      { path: 'homeworks/manage', name: 'HomeworkManage', component: () => import('../views/HomeworkManage.vue'), meta: { module: 'homework', requiresTeacher: true } },
      { path: 'homeworks/:id/grade', name: 'HomeworkGrade', component: () => import('../views/HomeworkGrade.vue'), meta: { module: 'homework', requiresTeacher: true } },
      { path: 'homeworks/my', name: 'HomeworkStudent', component: () => import('../views/HomeworkStudent.vue'), meta: { module: 'homework', requiresStudent: true } },
      { path: 'homeworks/peer-reviews', name: 'PeerReviewCenter', component: () => import('../views/PeerReviewCenter.vue'), meta: { module: 'homework', requiresStudent: true } },
      { path: 'homeworks/:id/take', name: 'HomeworkTake', component: () => import('../views/HomeworkTake.vue'), meta: { module: 'homework', requiresStudent: true } },
    ]
  },

  // ── 全屏答题/批改页（不套 Layout）──
  { path: '/pk/take/:battleId', name: 'PkTake', component: () => import('../views/PkTake.vue') },
  { path: '/competition/take/:compId', name: 'CompetitionTake', component: () => import('../views/CompetitionTake.vue') },
  { path: '/exam/take/:examId', name: 'ExamTake', component: () => import('../views/ExamTake.vue') },
  { path: '/results/:id', name: 'ResultDetail', component: () => import('../views/ResultDetail.vue') },
  { path: '/grading/:examId/:studentId', name: 'Grading', component: () => import('../views/GradingPage.vue'), meta: { requiresTeacher: true } },

  // ── 404 兜底（vue-router 4 的 catch-all 路由）──
  // 注：必须放在路由表末尾；pathMatch(.*)* 匹配所有未命中的路径
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('../views/NotFound.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  const role = auth.user?.role
  const isTeacher = role === 'teacher'
  const isStudent = role === 'student'

  // 1) 公开页：直接放行
  if (to.meta.public) {
    // 已登录用户访问登录/注册页：跳 Portal 避免重复登录
    if (auth.token && (to.path === '/login' || to.path === '/register')) {
      return next('/portal')
    }
    return next()
  }

  // 2) 未登录访问受保护页：回 Home，并带 redirect 参数供登录后跳回
  if (!auth.token) {
    return next({ path: '/home', query: { redirect: to.fullPath } })
  }

  // 3) 角色级保护：教师专属 / 学生专属
  if (to.meta.requiresTeacher && !isTeacher) {
    ElMessage.warning('该页面仅教师可访问')
    return next('/portal')
  }
  if (to.meta.requiresStudent && !isStudent) {
    ElMessage.warning('该页面仅学生可访问')
    return next('/portal')
  }

  // 4) 其他登录后路由：放行
  next()
})

export default router
