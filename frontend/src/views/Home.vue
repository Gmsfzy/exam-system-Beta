<template>
  <div class="home-page" :class="{ 'dark-mode': isDark }">
    <nav class="navbar" :class="{ 'scrolled': isScrolled }">
      <div class="container">
        <div class="navbar-brand" @click="scrollToTop">
          <div class="brand-logo">
            <el-icon :size="28"><School /></el-icon>
          </div>
          <span class="brand-text">智汇学场</span>
        </div>
        <div class="navbar-links">
          <a href="#modules" class="nav-link">四大模块</a>
          <a href="#features" class="nav-link">核心优势</a>
          <a href="#workflow" class="nav-link">使用流程</a>
          <a href="#about" class="nav-link">关于</a>
        </div>
        <div class="navbar-actions">
          <button class="theme-toggle" @click="toggleTheme" :title="isDark ? '切换亮色' : '切换暗色'">
            <el-icon :size="18"><Moon v-if="!isDark" /><Sunny v-else /></el-icon>
          </button>
          <router-link to="/login" class="btn btn-secondary">登录</router-link>
          <router-link to="/register" class="btn btn-outline">注册</router-link>
          <router-link to="/login" class="btn btn-primary">免费试用</router-link>
        </div>
      </div>
    </nav>

    <section class="hero-section">
      <div class="aurora-bg"></div>
      <div class="grid-pattern"></div>
      <div class="container">
        <div class="hero-content" ref="heroRef">
          <div class="hero-badge">
            <el-icon :size="14"><MagicStick /></el-icon>
            <span>AI 驱动 · 四模块一体化</span>
          </div>
          <h1 class="hero-title">
            智汇学场，<span class="gradient-text">让学习更多彩</span>
          </h1>
          <p class="hero-subtitle">
            融合在线考试、答题竞赛、悬赏征集、自主学习四大场域，以 AI 智能出题与批改赋能教学，为每一位学习者打造从测评到提升的完整闭环。
          </p>
          <div class="hero-buttons">
            <router-link to="/login" class="btn btn-large btn-primary">
              <span>开始使用</span>
              <el-icon :size="18"><ArrowRight /></el-icon>
            </router-link>
            <button class="btn btn-large btn-outline" @click="showVideoModal = true">
              <el-icon :size="18"><VideoPlay /></el-icon>
              <span>观看演示</span>
            </button>
          </div>
          <div class="hero-stats">
            <div class="stat-item">
              <div class="stat-value" ref="stat1Ref">10000+</div>
              <div class="stat-label">智能题库</div>
            </div>
            <div class="stat-divider"></div>
            <div class="stat-item">
              <div class="stat-value" ref="stat2Ref">4</div>
              <div class="stat-label">功能模块</div>
            </div>
            <div class="stat-divider"></div>
            <div class="stat-item">
              <div class="stat-value" ref="stat3Ref">98%</div>
              <div class="stat-label">AI 批改准确率</div>
            </div>
            <div class="stat-divider"></div>
            <div class="stat-item">
              <div class="stat-value" ref="stat4Ref">24/7</div>
              <div class="stat-label">在线服务</div>
            </div>
          </div>
        </div>
        <div class="hero-visual" ref="visualRef">
          <div class="visual-card card-1">
            <div class="card-icon">
              <el-icon :size="24"><Calendar /></el-icon>
            </div>
            <div class="card-content">
              <div class="card-title">在线考试</div>
              <div class="card-desc">智能组卷 · 自动批改</div>
            </div>
          </div>
          <div class="visual-card card-2">
            <div class="card-icon">
              <el-icon :size="24"><Trophy /></el-icon>
            </div>
            <div class="card-content">
              <div class="card-title">答题竞赛</div>
              <div class="card-desc">PK 排位 · 实时对战</div>
            </div>
          </div>
          <div class="visual-card card-3">
            <div class="card-icon">
              <el-icon :size="24"><Money /></el-icon>
            </div>
            <div class="card-content">
              <div class="card-title">征集悬赏</div>
              <div class="card-desc">积分激励 · 众创题目</div>
            </div>
          </div>
          <div class="visual-card card-4">
            <div class="card-icon">
              <el-icon :size="24"><Reading /></el-icon>
            </div>
            <div class="card-content">
              <div class="card-title">自主学习</div>
              <div class="card-desc">错题本 · 刷题计划</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="features-section" id="modules">
      <div class="container">
        <div class="section-header" ref="featuresHeader">
          <div class="section-badge">
            <el-icon :size="14"><Grid /></el-icon>
            <span>四大场域</span>
          </div>
          <h2 class="section-title">一个平台，四种玩法</h2>
          <p class="section-subtitle">从传统考试到 PK 对战，从悬赏征集到自主刷题，智汇学场为每位学习者准备了专属场域</p>
        </div>
        <div class="features-grid">
          <div class="feature-card" v-for="(feature, index) in features" :key="index" :ref="el => setFeatureRef(el, index)">
            <div class="feature-icon" :class="feature.color">
              <el-icon :size="28"><component :is="feature.icon" /></el-icon>
            </div>
            <h3 class="feature-title">{{ feature.title }}</h3>
            <p class="feature-desc">{{ feature.desc }}</p>
            <div class="feature-highlights">
              <div v-for="(highlight, idx) in feature.highlights" :key="idx" class="highlight-item">
                <el-icon :size="14"><Check /></el-icon>
                <span>{{ highlight }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="workflow-section" id="workflow">
      <div class="container">
        <div class="section-header" ref="workflowHeader">
          <div class="section-badge">
            <el-icon :size="14"><ArrowRight /></el-icon>
            <span>成长路径</span>
          </div>
          <h2 class="section-title">测评 → 学习 → 竞技，完整闭环</h2>
          <p class="section-subtitle">从注册到能力提升，四个模块环环相扣，让学习效果可见可衡量</p>
        </div>
        <div class="workflow-timeline">
          <div class="timeline-line"></div>
          <div class="workflow-steps">
            <div class="step-item" v-for="(step, index) in steps" :key="index" :ref="el => setStepRef(el, index)">
              <div class="step-number">{{ index + 1 }}</div>
              <div class="step-icon" :class="step.color">
                <el-icon :size="24"><component :is="step.icon" /></el-icon>
              </div>
              <h3 class="step-title">{{ step.title }}</h3>
              <p class="step-desc">{{ step.desc }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="stats-section">
      <div class="container">
        <div class="stats-grid" ref="statsRef">
          <div class="stat-card">
            <div class="stat-icon">
              <el-icon :size="32"><User /></el-icon>
            </div>
            <div class="stat-number">50,000+</div>
            <div class="stat-label">注册学习者</div>
          </div>
          <div class="stat-card">
            <div class="stat-icon">
              <el-icon :size="32"><Document /></el-icon>
            </div>
            <div class="stat-number">200,000+</div>
            <div class="stat-label">题目总数</div>
          </div>
          <div class="stat-card">
            <div class="stat-icon">
              <el-icon :size="32"><Trophy /></el-icon>
            </div>
            <div class="stat-number">10,000+</div>
            <div class="stat-label">竞赛场次</div>
          </div>
          <div class="stat-card">
            <div class="stat-icon">
              <el-icon :size="32"><Clock /></el-icon>
            </div>
            <div class="stat-number">30秒</div>
            <div class="stat-label">AI 平均批改</div>
          </div>
        </div>
      </div>
    </section>

    <section class="pricing-section" id="pricing">
      <div class="container">
        <div class="section-header" ref="pricingHeader">
          <div class="section-badge">
            <el-icon :size="14"><CreditCard /></el-icon>
            <span>定价方案</span>
          </div>
          <h2 class="section-title">灵活的价格选择</h2>
          <p class="section-subtitle">满足不同规模的教育机构需求</p>
        </div>
        <div class="pricing-cards">
          <div class="pricing-card" v-for="(plan, index) in pricingPlans" :key="index" :class="{ 'featured': plan.featured }" :ref="el => setPricingRef(el, index)">
            <div class="pricing-badge" v-if="plan.featured">
              <el-icon :size="12"><Star /></el-icon>
              <span>推荐</span>
            </div>
            <h3 class="pricing-name">{{ plan.name }}</h3>
            <div class="pricing-price">
              <span class="currency">¥</span>
              <span class="amount">{{ plan.price }}</span>
              <span class="period">/{{ plan.period }}</span>
            </div>
            <p class="pricing-desc">{{ plan.desc }}</p>
            <ul class="pricing-features">
              <li v-for="(feature, idx) in plan.features" :key="idx">
                <el-icon :size="14"><Check /></el-icon>
                <span>{{ feature }}</span>
              </li>
            </ul>
            <router-link to="/login" class="btn" :class="plan.featured ? 'btn-primary' : 'btn-outline'">
              {{ plan.cta }}
            </router-link>
          </div>
        </div>
      </div>
    </section>

    <section class="cta-section">
      <div class="container">
        <div class="cta-content" ref="ctaRef">
          <h2 class="cta-title">准备好开启智汇学场之旅了吗？</h2>
          <p class="cta-subtitle">四种场域，从测评到竞技到自学，即刻注册，免费体验全部功能</p>
          <div class="cta-buttons">
            <router-link to="/login" class="btn btn-large btn-primary">
              <span>免费注册</span>
              <el-icon :size="18"><ArrowRight /></el-icon>
            </router-link>
            <router-link to="/login" class="btn btn-large btn-outline">
              <el-icon :size="18"><Bell /></el-icon>
              <span>联系销售</span>
            </router-link>
          </div>
        </div>
      </div>
    </section>

    <footer class="footer" id="about">
      <div class="container">
        <div class="footer-content">
          <div class="footer-brand">
            <div class="brand-logo">
              <el-icon :size="28"><School /></el-icon>
            </div>
            <span class="brand-text">智汇学场</span>
            <p class="footer-tagline">融合考试、竞赛、悬赏、自学的一体化智能学习平台</p>
          </div>
          <div class="footer-links-section">
            <h4 class="footer-title">产品</h4>
            <ul class="footer-links">
              <li><router-link to="/login">在线考试</router-link></li>
              <li><router-link to="/login">答题竞赛</router-link></li>
              <li><router-link to="/login">征集悬赏</router-link></li>
              <li><router-link to="/login">自主学习</router-link></li>
            </ul>
          </div>
          <div class="footer-links-section">
            <h4 class="footer-title">模块导航</h4>
            <ul class="footer-links">
              <li><router-link to="/login">题库管理</router-link></li>
              <li><router-link to="/login">PK 排位</router-link></li>
              <li><router-link to="/login">战队中心</router-link></li>
              <li><router-link to="/login">错题本</router-link></li>
            </ul>
          </div>
          <div class="footer-links-section">
            <h4 class="footer-title">关于</h4>
            <ul class="footer-links">
              <li><router-link to="/login">帮助中心</router-link></li>
              <li><router-link to="/login">常见问题</router-link></li>
              <li><router-link to="/login">服务条款</router-link></li>
              <li><router-link to="/login">隐私政策</router-link></li>
            </ul>
          </div>
        </div>
        <div class="footer-bottom">
          <p class="copyright">© 2026 智汇学场 · Smart Learning Arena. All rights reserved.</p>
          <div class="social-links">
            <a href="#" class="social-link"><el-icon :size="18"><Share /></el-icon></a>
            <a href="#" class="social-link"><el-icon :size="18"><Link /></el-icon></a>
          </div>
        </div>
      </div>
    </footer>

    <VideoModal :show="showVideoModal" @close="showVideoModal = false" />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, markRaw } from 'vue'
import {
  School, Moon, Sunny, ArrowRight, VideoPlay, MagicStick, Check,
  TrendCharts, Grid, User, Document, Medal, Clock,
  CreditCard, Star, Bell, Share, Link, Calendar, Trophy, Money, Reading
} from '@element-plus/icons-vue'
import VideoModal from '../components/VideoModal.vue'

const isDark = ref(false)
const isScrolled = ref(false)
const showVideoModal = ref(false)

const heroRef = ref(null)
const visualRef = ref(null)
const featuresHeader = ref(null)
const workflowHeader = ref(null)
const statsRef = ref(null)
const pricingHeader = ref(null)
const ctaRef = ref(null)

const featureRefs = ref([])
const stepRefs = ref([])
const pricingRefs = ref([])

const setFeatureRef = (el, index) => {
  if (el) featureRefs.value[index] = el
}
const setStepRef = (el, index) => {
  if (el) stepRefs.value[index] = el
}
const setPricingRef = (el, index) => {
  if (el) pricingRefs.value[index] = el
}

const toggleTheme = () => {
  isDark.value = !isDark.value
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
  document.body.classList.toggle('dark-mode', isDark.value)
}

const scrollToTop = () => {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const features = [
  {
    icon: markRaw(Calendar),
    title: '在线考试',
    desc: '智能题库 + AI 组卷 + 自动批改的考试全流程，支持 8 种题型、防作弊切屏检测、实时成绩分析',
    color: 'gradient-purple',
    highlights: ['公共题库 · 跨教师共享', 'AI 智能组卷', '客观题即时批改', '主观题 AI 语义评分', '切屏检测防作弊']
  },
  {
    icon: markRaw(Trophy),
    title: '答题竞赛',
    desc: '实时 PK 对战 + 排位赛 + 战队系统，以赛促学，让学习充满竞技乐趣',
    color: 'gradient-orange',
    highlights: ['1v1 实时 PK', '积分赛排位', '段位勋章体系', '战队协作与 PK', 'AI 智能匹配']
  },
  {
    icon: markRaw(Money),
    title: '征集悬赏',
    desc: '发布悬赏征集优质题目，投稿被采纳即可赚取竞技积分，构建人人参与的众创题库',
    color: 'gradient-green',
    highlights: ['悬赏发布 · 积分激励', '题目征集与审核', '众创题库积累', '积分排行榜', '悬赏采纳奖励']
  },
  {
    icon: markRaw(Reading),
    title: '自主学习',
    desc: '错题本 + 自由刷题 + 学习计划 + AI 答疑，每一次练习都是进步',
    color: 'gradient-red',
    highlights: ['智能错题本', '自由刷题模式', '学习计划追踪', '每日学习报告', 'AI 智能答疑']
  }
]

const steps = [
  { icon: markRaw(School), title: '注册登录', desc: '教师和学生分别注册，创建专属账号', color: 'step-purple' },
  { icon: markRaw(Calendar), title: '测评摸底', desc: '在线考试或自由刷题，了解当前水平', color: 'step-blue' },
  { icon: markRaw(Reading), title: '错题攻克', desc: '错题本 + 学习计划，逐个击破薄弱点', color: 'step-green' },
  { icon: markRaw(Trophy), title: '竞技提升', desc: '参加 PK 或竞赛，在实战中检验学习效果', color: 'step-orange' }
]

const pricingPlans = [
  {
    name: '免费版',
    price: '0',
    period: '月',
    desc: '适合个人教师和小型班级',
    features: ['最多100道题目', '基础AI出题', '客观题自动批改', '3个考试场次/月', '社区支持'],
    cta: '开始使用',
    featured: false
  },
  {
    name: '专业版',
    price: '99',
    period: '月',
    desc: '适合学校和培训机构',
    features: ['无限题目', '高级AI出题', '主观题AI批改', '无限考试场次', '优先技术支持', '数据导出', 'API接口'],
    cta: '立即升级',
    featured: true
  },
  {
    name: '企业版',
    price: '定制',
    period: '',
    desc: '适合大型教育集团',
    features: ['全部专业版功能', '私有化部署', '定制开发', '专属客户经理', 'SLA保障', '安全审计', '培训服务'],
    cta: '联系销售',
    featured: false
  }
]

const animateValue = (obj, start, end, duration) => {
  let startTimestamp = null
  const step = (timestamp) => {
    if (!startTimestamp) startTimestamp = timestamp
    const progress = Math.min((timestamp - startTimestamp) / duration, 1)
    obj.innerHTML = (progress * (end - start) + start).toFixed(end % 1 !== 0 ? 1 : 0) + (obj.dataset.suffix || '')
    if (progress < 1) {
      window.requestAnimationFrame(step)
    }
  }
  window.requestAnimationFrame(step)
}

const animateNumbers = () => {
  const stat1 = document.querySelector('.stat-value:nth-child(1)')
  const stat2 = document.querySelector('.stat-value:nth-child(3)')
  const stat3 = document.querySelector('.stat-value:nth-child(5)')
  const stat4 = document.querySelector('.stat-value:nth-child(7)')
  
  if (stat1 && stat1.dataset.animated !== 'true') {
    stat1.dataset.suffix = '+'; animateValue(stat1, 0, 10000, 2000); stat1.dataset.animated = 'true'
  }
  if (stat2 && stat2.dataset.animated !== 'true') {
    stat2.dataset.suffix = ''; animateValue(stat2, 0, 4, 2000); stat2.dataset.animated = 'true'
  }
  if (stat3 && stat3.dataset.animated !== 'true') {
    stat3.dataset.suffix = '%'; animateValue(stat3, 0, 98, 2000); stat3.dataset.animated = 'true'
  }
  if (stat4 && stat4.dataset.animated !== 'true') {
    stat4.dataset.suffix = '/7'; animateValue(stat4, 0, 24, 2000); stat4.dataset.animated = 'true'
  }
}

const observerCallback = (entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('reveal')
      if (entry.target.classList.contains('hero-content')) {
        setTimeout(animateNumbers, 500)
      }
    }
  })
}

let observer = null

onMounted(() => {
  const savedTheme = localStorage.getItem('theme')
  if (savedTheme === 'dark') {
    isDark.value = true
    document.body.classList.add('dark-mode')
  }

  window.addEventListener('scroll', () => {
    isScrolled.value = window.scrollY > 50
  })

  observer = new IntersectionObserver(observerCallback, {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
  })

  const elements = [
    heroRef.value,
    visualRef.value,
    featuresHeader.value,
    ...featureRefs.value,
    workflowHeader.value,
    ...stepRefs.value,
    statsRef.value,
    pricingHeader.value,
    ...pricingRefs.value,
    ctaRef.value
  ].filter(Boolean)

  elements.forEach(el => observer.observe(el))
})

onUnmounted(() => {
  if (observer) {
    observer.disconnect()
  }
  window.removeEventListener('scroll', () => {
    isScrolled.value = window.scrollY > 50
  })
})
</script>

<style scoped>
:root {
  --primary-color: #8b5cf6;
  --primary-light: #a78bfa;
  --primary-dark: #7c3aed;
  --secondary-color: #06b6d4;
  --accent-color: #f43f5e;
  --text-primary: #1e293b;
  --text-secondary: #64748b;
  --text-muted: #94a3b8;
  --bg-primary: #ffffff;
  --bg-secondary: #f8fafc;
  --bg-tertiary: #f1f5f9;
  --card-bg: rgba(255, 255, 255, 0.8);
  --card-border: rgba(226, 232, 240, 0.6);
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
  --shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 24px;
}

.dark-mode {
  --text-primary: #f1f5f9;
  --text-secondary: #cbd5e1;
  --text-muted: #64748b;
  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --bg-tertiary: #334155;
  --card-bg: rgba(30, 41, 59, 0.8);
  --card-border: rgba(71, 85, 105, 0.4);
}

.home-page {
  min-height: 100vh;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  transition: background 0.3s ease;
}

.container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 24px;
}

.navbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(226, 232, 240, 0.5);
  transition: all 0.3s ease;
}

.navbar.scrolled {
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
}

.dark-mode .navbar {
  background: rgba(15, 23, 42, 0.7);
  border-bottom-color: rgba(71, 85, 105, 0.3);
}

.dark-mode .navbar.scrolled {
  background: rgba(15, 23, 42, 0.95);
}

.navbar .container {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 72px;
}

.navbar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
}

.brand-logo {
  width: 40px;
  height: 40px;
  background: linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.brand-text {
  font-weight: 700;
  font-size: 1.3rem;
  background: linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.navbar-links {
  display: flex;
  gap: 32px;
}

.nav-link {
  text-decoration: none;
  color: var(--text-secondary);
  font-weight: 500;
  font-size: 0.95rem;
  transition: color 0.2s ease;
}

.nav-link:hover {
  color: var(--primary-color);
}

.navbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.theme-toggle {
  width: 40px;
  height: 40px;
  border: none;
  background: var(--bg-tertiary);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.2s ease;
}

.theme-toggle:hover {
  background: var(--primary-color);
  color: white;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 10px;
  font-weight: 600;
  font-size: 0.9rem;
  text-decoration: none;
  border: 2px solid transparent;
  cursor: pointer;
  transition: all 0.25s ease;
}

.btn-primary {
  background: linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%);
  color: white;
  box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4);
}

.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(139, 92, 246, 0.5);
}

.btn-secondary {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.btn-secondary:hover {
  background: var(--card-border);
}

.btn-outline {
  background: transparent;
  color: var(--primary-color);
  border-color: var(--primary-color);
}

.btn-outline:hover {
  background: var(--primary-color);
  color: white;
}

.btn-large {
  padding: 14px 32px;
  font-size: 1rem;
}

.hero-section {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  overflow: hidden;
  padding-top: 72px;
}

.aurora-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
}

.aurora-bg::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  right: -50%;
  bottom: -50%;
  background: radial-gradient(circle at 30% 20%, rgba(139, 92, 246, 0.15) 0%, transparent 50%),
              radial-gradient(circle at 70% 80%, rgba(6, 182, 212, 0.15) 0%, transparent 50%),
              radial-gradient(circle at 50% 50%, rgba(244, 63, 94, 0.08) 0%, transparent 50%);
  animation: auroraMove 20s infinite ease-in-out;
}

@keyframes auroraMove {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  25% { transform: translate(5%, -5%) rotate(1deg); }
  50% { transform: translate(0, 5%) rotate(0deg); }
  75% { transform: translate(-5%, 0) rotate(-1deg); }
}

.grid-pattern {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-image: 
    linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
  background-size: 60px 60px;
}

.hero-section .container {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 60px;
  align-items: center;
}

.hero-content {
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.8s ease, transform 0.8s ease;
}

.hero-content.reveal {
  opacity: 1;
  transform: translateY(0);
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  background: rgba(139, 92, 246, 0.15);
  border: 1px solid rgba(139, 92, 246, 0.3);
  border-radius: 20px;
  color: #a78bfa;
  font-size: 0.85rem;
  font-weight: 500;
  margin-bottom: 24px;
}

.hero-title {
  font-size: 3.5rem;
  font-weight: 800;
  line-height: 1.1;
  margin-bottom: 20px;
  color: white;
}

.gradient-text {
  background: linear-gradient(135deg, #a78bfa 0%, #22d3ee 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: gradientShift 4s ease infinite;
  background-size: 200% 200%;
}

@keyframes gradientShift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

.hero-subtitle {
  font-size: 1.15rem;
  color: rgba(255, 255, 255, 0.7);
  line-height: 1.8;
  margin-bottom: 40px;
  max-width: 500px;
}

.hero-buttons {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 60px;
}

.hero-stats {
  display: flex;
  align-items: center;
  gap: 32px;
  flex-wrap: wrap;
  padding: 24px;
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-value {
  font-size: 2rem;
  font-weight: 700;
  color: white;
  margin-bottom: 4px;
}

.stat-label {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
}

.stat-divider {
  width: 1px;
  height: 40px;
  background: rgba(255, 255, 255, 0.1);
}

.hero-visual {
  position: relative;
  height: 500px;
  opacity: 0;
  transform: translateX(30px);
  transition: opacity 0.8s ease 0.2s, transform 0.8s ease 0.2s;
}

.hero-visual.reveal {
  opacity: 1;
  transform: translateX(0);
}

.visual-card {
  position: absolute;
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  padding: 20px;
  display: flex;
  gap: 16px;
  transition: all 0.3s ease;
}

.visual-card:hover {
  transform: translateY(-5px) scale(1.02);
  background: rgba(255, 255, 255, 0.12);
}

.card-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.card-1 .card-icon { background: linear-gradient(135deg, #8b5cf6, #a78bfa); }
.card-2 .card-icon { background: linear-gradient(135deg, #10b981, #34d399); }
.card-3 .card-icon { background: linear-gradient(135deg, #f59e0b, #fbbf24); }
.card-4 .card-icon { background: linear-gradient(135deg, #ef4444, #f87171); }

.card-content {
  display: flex;
  flex-direction: column;
}

.card-title {
  font-weight: 600;
  color: white;
  margin-bottom: 4px;
}

.card-desc {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
}

.card-1 { top: 20px; left: 0; animation: floatCard 6s ease-in-out infinite; }
.card-2 { top: 80px; right: 20px; animation: floatCard 6s ease-in-out infinite 1.5s; }
.card-3 { bottom: 80px; left: 40px; animation: floatCard 6s ease-in-out infinite 3s; }
.card-4 { bottom: 20px; right: 0; animation: floatCard 6s ease-in-out infinite 4.5s; }

@keyframes floatCard {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

.features-section {
  padding: 100px 24px;
  background: var(--bg-primary);
}

.section-header {
  text-align: center;
  margin-bottom: 60px;
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}

.section-header.reveal {
  opacity: 1;
  transform: translateY(0);
}

.section-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px;
  background: rgba(139, 92, 246, 0.1);
  border-radius: 20px;
  color: var(--primary-color);
  font-size: 0.85rem;
  font-weight: 500;
  margin-bottom: 16px;
}

.section-title {
  font-size: 2.5rem;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.section-subtitle {
  font-size: 1.1rem;
  color: var(--text-secondary);
  max-width: 500px;
  margin: 0 auto;
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 24px;
}

.feature-card {
  background: var(--card-bg);
  backdrop-filter: blur(12px);
  border: 1px solid var(--card-border);
  border-radius: 20px;
  padding: 40px 32px;
  transition: all 0.3s ease;
  opacity: 0;
  transform: translateY(30px);
}

.feature-card.reveal {
  opacity: 1;
  transform: translateY(0);
}

.feature-card:nth-child(2) { transition-delay: 0.1s; }
.feature-card:nth-child(3) { transition-delay: 0.2s; }
.feature-card:nth-child(4) { transition-delay: 0.3s; }

.feature-card:hover {
  transform: translateY(-8px);
  box-shadow: var(--shadow-xl);
}

.feature-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24px;
  color: white;
}

.gradient-purple { background: linear-gradient(135deg, #8b5cf6, #a78bfa); }
.gradient-green { background: linear-gradient(135deg, #10b981, #34d399); }
.gradient-orange { background: linear-gradient(135deg, #f59e0b, #fbbf24); }
.gradient-red { background: linear-gradient(135deg, #ef4444, #f87171); }

.feature-title {
  font-size: 1.3rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
}

.feature-desc {
  font-size: 0.95rem;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 20px;
}

.feature-highlights {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.highlight-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.highlight-item .el-icon {
  color: #10b981;
}

.workflow-section {
  padding: 100px 24px;
  background: var(--bg-secondary);
}

.workflow-timeline {
  position: relative;
  max-width: 900px;
  margin: 0 auto;
}

.timeline-line {
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--primary-color), transparent);
  transform: translateY(-50%);
}

.workflow-steps {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
}

.step-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 24px;
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}

.step-item.reveal {
  opacity: 1;
  transform: translateY(0);
}

.step-item:nth-child(2) { transition-delay: 0.1s; }
.step-item:nth-child(3) { transition-delay: 0.2s; }
.step-item:nth-child(4) { transition-delay: 0.3s; }

.step-number {
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  width: 24px;
  height: 24px;
  background: var(--bg-primary);
  border: 3px solid var(--primary-color);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--primary-color);
}

.step-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
  color: white;
}

.step-purple { background: linear-gradient(135deg, #8b5cf6, #a78bfa); }
.step-blue { background: linear-gradient(135deg, #3b82f6, #60a5fa); }
.step-green { background: linear-gradient(135deg, #10b981, #34d399); }
.step-orange { background: linear-gradient(135deg, #f59e0b, #fbbf24); }

.step-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.step-desc {
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.stats-section {
  padding: 80px 24px;
  background: linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 32px;
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}

.stats-grid.reveal {
  opacity: 1;
  transform: translateY(0);
}

.stat-card {
  text-align: center;
  padding: 32px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.stat-icon {
  width: 48px;
  height: 48px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
  color: white;
}

.stat-number {
  font-size: 2.5rem;
  font-weight: 700;
  color: white;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 0.95rem;
  color: rgba(255, 255, 255, 0.8);
}

.pricing-section {
  padding: 100px 24px;
  background: var(--bg-primary);
}

.pricing-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 24px;
  max-width: 1100px;
  margin: 0 auto;
}

.pricing-card {
  background: var(--card-bg);
  backdrop-filter: blur(12px);
  border: 1px solid var(--card-border);
  border-radius: 20px;
  padding: 40px 32px;
  position: relative;
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}

.pricing-card.reveal {
  opacity: 1;
  transform: translateY(0);
}

.pricing-card:nth-child(2) { transition-delay: 0.15s; }
.pricing-card:nth-child(3) { transition-delay: 0.3s; }

.pricing-card.featured {
  border-color: var(--primary-color);
  box-shadow: 0 10px 40px rgba(139, 92, 246, 0.2);
  transform: scale(1.02);
}

.pricing-badge {
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 16px;
  background: linear-gradient(135deg, #8b5cf6, #a78bfa);
  border-radius: 20px;
  color: white;
  font-size: 0.8rem;
  font-weight: 600;
}

.pricing-name {
  font-size: 1.2rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.pricing-price {
  margin-bottom: 8px;
}

.currency {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
}

.amount {
  font-size: 3rem;
  font-weight: 700;
  color: var(--text-primary);
}

.period {
  font-size: 1rem;
  color: var(--text-muted);
}

.pricing-desc {
  font-size: 0.95rem;
  color: var(--text-secondary);
  margin-bottom: 24px;
}

.pricing-features {
  list-style: none;
  padding: 0;
  margin: 0 0 32px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pricing-features li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.95rem;
  color: var(--text-secondary);
}

.pricing-features .el-icon {
  color: #10b981;
}

.pricing-card .btn {
  width: 100%;
  justify-content: center;
}

.cta-section {
  padding: 100px 24px;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
  position: relative;
  overflow: hidden;
}

.cta-section::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  right: -50%;
  bottom: -50%;
  background: radial-gradient(circle at 50% 50%, rgba(139, 92, 246, 0.1) 0%, transparent 50%);
}

.cta-content {
  position: relative;
  z-index: 1;
  text-align: center;
  opacity: 0;
  transform: translateY(30px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}

.cta-content.reveal {
  opacity: 1;
  transform: translateY(0);
}

.cta-title {
  font-size: 2.5rem;
  font-weight: 700;
  color: white;
  margin-bottom: 16px;
}

.cta-subtitle {
  font-size: 1.15rem;
  color: rgba(255, 255, 255, 0.7);
  margin-bottom: 40px;
}

.cta-buttons {
  display: flex;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
}

.footer {
  padding: 60px 24px 30px;
  background: var(--bg-secondary);
}

.footer-content {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 40px;
  margin-bottom: 40px;
}

.footer-brand {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.footer-tagline {
  font-size: 0.9rem;
  color: var(--text-muted);
}

.footer-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}

.footer-links {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.footer-links li a {
  text-decoration: none;
  font-size: 0.9rem;
  color: var(--text-secondary);
  transition: color 0.2s ease;
}

.footer-links li a:hover {
  color: var(--primary-color);
}

.footer-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 24px;
  border-top: 1px solid var(--card-border);
}

.copyright {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.social-links {
  display: flex;
  gap: 16px;
}

.social-link {
  width: 36px;
  height: 36px;
  background: var(--bg-tertiary);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  text-decoration: none;
  transition: all 0.2s ease;
}

.social-link:hover {
  background: var(--primary-color);
  color: white;
}

@media (max-width: 1024px) {
  .hero-section .container {
    grid-template-columns: 1fr;
    gap: 40px;
    text-align: center;
  }
  
  .hero-visual {
    height: 350px;
  }
  
  .hero-stats {
    justify-content: center;
  }
  
  .hero-title {
    font-size: 2.8rem;
  }
}

@media (max-width: 768px) {
  .navbar-links {
    display: none;
  }
  
  .hero-title {
    font-size: 2.2rem;
  }
  
  .hero-subtitle {
    font-size: 1rem;
  }
  
  .section-title {
    font-size: 1.8rem;
  }
  
  .workflow-steps {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .timeline-line {
    display: none;
  }
  
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .cta-title {
    font-size: 1.8rem;
  }
  
  .footer-bottom {
    flex-direction: column;
    gap: 16px;
  }
}

@media (max-width: 480px) {
  .hero-stats {
    flex-direction: column;
    gap: 16px;
  }
  
  .stat-divider {
    display: none;
  }
  
  .workflow-steps {
    grid-template-columns: 1fr;
  }
  
  .stats-grid {
    grid-template-columns: 1fr;
  }
  
  .pricing-card.featured {
    transform: none;
  }
}
</style>
