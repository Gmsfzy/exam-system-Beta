import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue') },
  { path: '/register', name: 'Register', component: () => import('../views/Register.vue') },
  { path: '/home', name: 'Home', component: () => import('../views/Home.vue') },
  { path: '/portal', name: 'Portal', component: () => import('../views/Portal.vue') },
  {
    path: '/',
    component: () => import('../views/Layout.vue'),
    redirect: '/portal',
    children: [
      { path: 'questions', name: 'Questions', component: () => import('../views/QuestionList.vue'), meta: { module: 'exam' } },
      { path: 'majors', name: 'Majors', component: () => import('../views/MajorList.vue'), meta: { module: 'exam' } },
      { path: 'majors/:id', name: 'MajorDetail', component: () => import('../views/MajorDetail.vue'), meta: { module: 'exam' } },
      { path: 'chapters/:id', name: 'ChapterList', component: () => import('../views/ChapterList.vue'), meta: { module: 'exam' } },
      { path: 'ai-generate', name: 'AiGenerate', component: () => import('../views/AiGenerate.vue'), meta: { module: 'exam' } },
      { path: 'exams', name: 'ExamDashboard', component: () => import('../views/ExamDashboard.vue'), meta: { module: 'exam' } },
      { path: 'exams/:id/edit', name: 'EditExam', component: () => import('../views/EditExam.vue'), meta: { module: 'exam' } },
      { path: 'student', name: 'StudentDashboard', component: () => import('../views/StudentDashboard.vue'), meta: { module: 'exam' } },
      { path: 'results', name: 'ResultList', component: () => import('../views/ResultList.vue'), meta: { module: 'exam' } },
      { path: 'results/exam/:examId', name: 'ExamResults', component: () => import('../views/ExamResults.vue'), meta: { module: 'exam' } },
      { path: 'results/analysis', name: 'ResultAnalysis', component: () => import('../views/ResultAnalysis.vue'), meta: { module: 'exam' } },
      { path: 'profile', name: 'UserProfile', component: () => import('../views/UserProfile.vue'), meta: { module: 'exam' } },
      { path: 'settings', name: 'SystemSettings', component: () => import('../views/SystemSettings.vue'), meta: { module: 'exam' } },
      { path: 'competitions', name: 'CompetitionHome', component: () => import('../views/CompetitionHome.vue'), meta: { module: 'competition' } },
      { path: 'competitions/pk', name: 'PkLobby', component: () => import('../views/PkLobby.vue'), meta: { module: 'competition' } },
      { path: 'competitions/:compId/leaderboard', name: 'CompetitionLeaderboard', component: () => import('../views/CompetitionLeaderboard.vue'), meta: { module: 'competition' } },
      { path: 'rank', name: 'RankCenter', component: () => import('../views/RankCenter.vue'), meta: { module: 'competition' } },
      { path: 'teams', name: 'TeamCenter', component: () => import('../views/TeamCenter.vue'), meta: { module: 'competition' } },
      { path: 'study-profile', name: 'StudyProfile', component: () => import('../views/StudyProfile.vue'), meta: { module: 'competition' } },
      { path: 'bounties', name: 'BountyPlaza', component: () => import('../views/BountyPlaza.vue'), meta: { module: 'bounty' } },
      { path: 'bounties/publish', name: 'BountyPublish', component: () => import('../views/BountyPublish.vue'), meta: { module: 'bounty' } },
      { path: 'bounties/mine', name: 'BountyMine', component: () => import('../views/BountyMine.vue'), meta: { module: 'bounty' } },
      { path: 'bounties/:id', name: 'BountyDetail', component: () => import('../views/BountyDetail.vue'), meta: { module: 'bounty' } },
      { path: 'learning', name: 'LearningHome', component: () => import('../views/LearningHome.vue'), meta: { module: 'learning' } },
      { path: 'learning/wrong', name: 'WrongNotebook', component: () => import('../views/WrongNotebook.vue'), meta: { module: 'learning' } },
      { path: 'learning/practice', name: 'PracticeList', component: () => import('../views/PracticeList.vue'), meta: { module: 'learning' } },
      { path: 'learning/practice/:sessionId', name: 'PracticeDetail', component: () => import('../views/PracticeDetail.vue'), meta: { module: 'learning' } },
      { path: 'learning/plan', name: 'StudyPlan', component: () => import('../views/StudyPlan.vue'), meta: { module: 'learning' } },
      { path: 'learning/report', name: 'StudyReport', component: () => import('../views/StudyReport.vue'), meta: { module: 'learning' } },
    ]
  },
  { path: '/pk/take/:battleId', name: 'PkTake', component: () => import('../views/PkTake.vue') },
  { path: '/competition/take/:compId', name: 'CompetitionTake', component: () => import('../views/CompetitionTake.vue') },
  { path: '/exam/take/:examId', name: 'ExamTake', component: () => import('../views/ExamTake.vue') },
  { path: '/results/exam/:examId', name: 'ExamResults', component: () => import('../views/ExamResults.vue') },
  { path: '/results/:id', name: 'ResultDetail', component: () => import('../views/ResultDetail.vue') },
  { path: '/grading/:examId/:studentId', name: 'Grading', component: () => import('../views/GradingPage.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  const publicPaths = ['/login', '/home', '/register']
  if (!publicPaths.includes(to.path) && !auth.token) {
    next('/home')
  } else {
    next()
  }
})

export default router