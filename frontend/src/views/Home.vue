<template>
  <div class="home-page" :class="{ light: !isDark }">
    <!-- 全局背景：极光 + 噪点 -->
    <div class="bg-layer">
      <div class="aurora a1"></div>
      <div class="aurora a2"></div>
      <div class="aurora a3"></div>
      <div class="noise"></div>
    </div>

    <!-- 顶部导航 -->
    <nav class="navbar" :class="{ scrolled: isScrolled }">
      <div class="container nav-inner">
        <div class="navbar-brand" @click="scrollToTop">
          <div class="brand-logo"><el-icon :size="22"><School /></el-icon></div>
          <span class="brand-text">智汇学场</span>
        </div>
        <div class="navbar-links">
          <a href="#modules" class="nav-link" @click.prevent="scrollTo('modules')">五大模块</a>
          <a href="#ai" class="nav-link" @click.prevent="scrollTo('ai')">AI 引擎</a>
          <a href="#panorama" class="nav-link" @click.prevent="scrollTo('panorama')">全景能力</a>
          <a href="#voices" class="nav-link" @click.prevent="scrollTo('voices')">用户心声</a>
          <a href="#faq" class="nav-link" @click.prevent="scrollTo('faq')">常见问题</a>
        </div>
        <div class="navbar-actions">
          <button class="theme-toggle" @click="toggleTheme" :title="isDark ? '切换亮色' : '切换暗色'">
            <el-icon :size="17"><Moon v-if="isDark" /><Sunny v-else /></el-icon>
          </button>
          <router-link :to="loginLink" class="btn btn-ghost">登录</router-link>
          <router-link to="/register" class="btn btn-ghost">注册</router-link>
          <router-link to="/register" class="btn btn-primary btn-glow">免费试用</router-link>
        </div>
      </div>
    </nav>

    <!-- ══ Hero ══ -->
    <section class="hero" ref="heroRef">
      <div class="container hero-grid">
        <div class="hero-copy">
          <div class="hero-badge rise" style="--d:.05s">
            <span class="pulse-dot"></span>
            AI 驱动 · 五模块一体化学习平台
          </div>
          <h1 class="hero-title">
            <span class="line rise" style="--d:.12s">让每一次学习，</span>
            <span class="line rise" style="--d:.22s">都有<span class="grad-text">场域</span>可依</span>
          </h1>
          <p class="hero-sub rise" style="--d:.34s">
            在线考试夯实测评、作业练习闭环批改、答题竞赛点燃热情、征集悬赏众创题库、自主学习持续提升——
            五大场域环环相扣，AI 全程赋能。
          </p>
          <div class="hero-btns rise" style="--d:.44s">
            <router-link to="/register" class="btn btn-xl btn-primary btn-glow">
              立即开启 <el-icon :size="17"><ArrowRight /></el-icon>
            </router-link>
            <button class="btn btn-xl btn-glass" @click="showVideoModal = true">
              <el-icon :size="17"><VideoPlay /></el-icon> 观看演示
            </button>
          </div>
          <div class="hero-stats rise" style="--d:.54s">
            <div class="hstat">
              <div class="hstat-num"><em ref="s1">0</em><i>+</i></div>
              <div class="hstat-label">跨教师共享题库</div>
            </div>
            <div class="hstat-sep"></div>
            <div class="hstat">
              <div class="hstat-num"><em ref="s2">0</em></div>
              <div class="hstat-label">一体化功能模块</div>
            </div>
            <div class="hstat-sep"></div>
            <div class="hstat">
              <div class="hstat-num"><em ref="s3">0</em><i>种</i></div>
              <div class="hstat-label">考试题型支持</div>
            </div>
            <div class="hstat-sep"></div>
            <div class="hstat">
              <div class="hstat-num"><em ref="s4">0</em><i>s</i></div>
              <div class="hstat-label">AI 平均批改</div>
            </div>
          </div>
        </div>

        <!-- Hero 右侧：五模块轨道浮标 -->
        <div class="hero-orbit rise" style="--d:.3s">
          <div class="orbit-core">
            <el-icon :size="34"><School /></el-icon>
            <span>智汇学场</span>
          </div>
          <div
            v-for="(m, i) in modules" :key="m.key"
            class="orbit-chip" :class="'oc' + (i + 1)"
            :style="{ background: m.gradient }"
            @click="pickModule(i); scrollTo('modules')"
          >
            <el-icon :size="18"><component :is="m.icon" /></el-icon>
            <span>{{ m.short }}</span>
          </div>
        </div>
      </div>
      <div class="scroll-hint" @click="scrollTo('modules')">
        <span class="mouse"><span class="wheel"></span></span>
        <em>向下滚动</em>
      </div>
    </section>

    <!-- ══ 能力跑马灯 ══ -->
    <div class="ticker" aria-hidden="true">
      <div class="ticker-track">
        <template v-for="n in 2" :key="n">
          <span v-for="t in tickerItems" :key="t" class="tk-item">
            <i class="tk-dot"></i>{{ t }}
          </span>
        </template>
      </div>
    </div>

    <!-- ══ 五大模块 · 体验台 ══ -->
    <section class="section" id="modules" ref="modulesRef">
      <div class="container">
        <div class="sec-head reveal">
          <div class="sec-badge"><el-icon :size="13"><Grid /></el-icon> 五大场域</div>
          <h2 class="sec-title">一个平台，<span class="grad-text">五种玩法</span></h2>
          <p class="sec-sub">点击左侧模块，右侧即时预览该模块的真实工作界面</p>
        </div>

        <div class="showcase">
          <!-- 左：模块选择列 -->
          <div class="mod-rail">
            <div
              v-for="(m, i) in modules" :key="m.key"
              class="mod-tab" :class="{ on: active === i }"
              :style="{ '--mc': m.hex }"
              @click="pickModule(i)"
            >
              <div class="mod-tab-icon" :style="{ background: m.gradient }">
                <el-icon :size="20"><component :is="m.icon" /></el-icon>
              </div>
              <div class="mod-tab-body">
                <div class="mod-tab-title">{{ m.title }}</div>
                <div class="mod-tab-tag">{{ m.tagline }}</div>
              </div>
              <el-icon class="mod-tab-arrow" :size="16"><ArrowRight /></el-icon>
            </div>
          </div>

          <!-- 右：仿真界面预览 + 功能清单 -->
          <div class="mod-stage">
            <div class="mock-window" :key="active">
              <div class="mock-bar">
                <span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
                <span class="mock-url">{{ modules[active].mockUrl }}</span>
                <span class="mock-live"><i></i>LIVE PREVIEW</span>
              </div>

              <!-- 在线考试 -->
              <div v-if="active === 0" class="mock-body mb-exam">
                <div class="mb-title">考试仪表盘 <em>教师视角</em></div>
                <div class="exam-cards">
                  <div class="x-card" v-for="c in mockData.exams" :key="c.name">
                    <div class="x-head"><span class="x-dot" :style="{ background: c.color }"></span>{{ c.name }}</div>
                    <div class="x-bar"><i :style="{ width: c.pct + '%', background: c.color }"></i></div>
                    <div class="x-meta"><span>{{ c.done }}/{{ c.total }} 人已交卷</span><b :style="{ color: c.color }">{{ c.pct }}%</b></div>
                  </div>
                </div>
                <div class="x-foot">
                  <span class="x-chip">8 种题型</span><span class="x-chip">AI 智能组卷</span>
                  <span class="x-chip">切屏检测</span><span class="x-chip">成绩多维分析</span>
                </div>
              </div>

              <!-- 答题竞赛 -->
              <div v-else-if="active === 1" class="mock-body mb-pk">
                <div class="mb-title">1v1 实时对战 <em>赛季排位</em></div>
                <div class="pk-arena">
                  <div class="pk-side">
                    <div class="pk-ava" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">我</div>
                    <div class="pk-name">你</div>
                    <div class="pk-score" ref="pkA">7</div>
                  </div>
                  <div class="pk-mid"><span>VS</span><em>第 {{ pkQ }} / 10 题 · 剩 42s</em></div>
                  <div class="pk-side">
                    <div class="pk-ava" style="background:linear-gradient(135deg,#f59e0b,#ef4444)">对</div>
                    <div class="pk-name">对手</div>
                    <div class="pk-score" ref="pkB">6</div>
                  </div>
                </div>
                <div class="pk-question">下列哪项是 Python 的不可变类型？</div>
                <div class="pk-opts">
                  <span v-for="o in mockData.pkOpts" :key="o.t" :class="o.cls">{{ o.t }}</span>
                </div>
              </div>

              <!-- 征集悬赏 -->
              <div v-else-if="active === 2" class="mock-body mb-bounty">
                <div class="mb-title">悬赏广场 <em>众创题库</em></div>
                <div class="b-row" v-for="b in mockData.bounties" :key="b.title">
                  <div class="b-info">
                    <div class="b-title">{{ b.title }}</div>
                    <div class="b-meta">{{ b.meta }}</div>
                  </div>
                  <div class="b-reward">
                    <b>{{ b.reward }}</b><span>积分</span>
                    <em :class="b.cls">{{ b.state }}</em>
                  </div>
                </div>
                <div class="b-flow">发布悬赏 → 社区投稿 → 教师审核 → 采纳得积分</div>
              </div>

              <!-- 自主学习 -->
              <div v-else-if="active === 3" class="mock-body mb-learn">
                <div class="mb-title">学习计划 <em>时间轴视图</em></div>
                <div class="tl-plan">
                  <div class="tl-name">三角函数冲刺</div>
                  <div class="tl-band"><i class="time" style="width:62%"></i><i class="done" style="width:40%"></i></div>
                  <div class="tl-legend"><span>■ 时间进度 62%</span><span>■ 完成进度 40%</span><em>落后预警</em></div>
                </div>
                <div class="tl-tasks">
                  <div class="tl-task done"><i></i>掌握「诱导公式」并完成配套练习</div>
                  <div class="tl-task"><i></i>专项刷题 20 题</div>
                  <div class="tl-task overdue"><i></i>错题复盘笔记 <em>已逾期</em></div>
                </div>
                <div class="learn-chips">
                  <span class="x-chip">AI 拆计划</span><span class="x-chip">智能错题本</span>
                  <span class="x-chip">遗忘曲线复习</span><span class="x-chip">知识图谱路径</span>
                </div>
              </div>

              <!-- 作业练习 -->
              <div v-else class="mock-body mb-homework">
                <div class="mb-title">作业批改工作台 <em>教师视角</em></div>
                <div class="hw-list">
                  <div class="hw-row" v-for="h in mockData.homeworks" :key="h.name">
                    <div class="hw-info">
                      <div class="hw-name">{{ h.name }}</div>
                      <div class="hw-meta">{{ h.meta }}</div>
                    </div>
                    <div class="hw-bar"><i :style="{ width: h.pct + '%', background: h.color }"></i></div>
                    <div class="hw-state" :style="{ color: h.color, borderColor: h.color }">{{ h.state }}</div>
                  </div>
                </div>
                <div class="hw-flow">布置 → 作答 → AI 初评 → 教师复核 → 讲评订正</div>
                <div class="learn-chips">
                  <span class="x-chip">题集/开放双形态</span><span class="x-chip">匿名互评</span>
                  <span class="x-chip">评分量规</span><span class="x-chip">查重监测</span><span class="x-chip">优秀展示墙</span>
                </div>
              </div>
            </div>

            <!-- 模块详情 -->
            <div class="mod-detail">
              <div class="mod-desc">{{ modules[active].desc }}</div>
              <div class="mod-points">
                <div v-for="(p, idx) in modules[active].points" :key="idx" class="point" :style="{ '--d': idx * 0.07 + 's' }">
                  <el-icon :size="14" class="pt-check"><Check /></el-icon>{{ p }}
                </div>
              </div>
              <div class="mod-figures">
                <div class="fig" v-for="f in modules[active].figures" :key="f.label">
                  <b>{{ f.num }}</b><span>{{ f.label }}</span>
                </div>
              </div>
              <router-link :to="loginLink" class="btn btn-enter" :style="{ background: modules[active].gradient }">
                进入{{ modules[active].title }} <el-icon :size="15"><ArrowRight /></el-icon>
              </router-link>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ══ AI 引擎 ══ -->
    <section class="section" id="ai" ref="aiRef">
      <div class="container">
        <div class="sec-head reveal">
          <div class="sec-badge"><el-icon :size="13"><MagicStick /></el-icon> AI 引擎</div>
          <h2 class="sec-title">五大模块背后，<span class="grad-text">同一颗 AI 大脑</span></h2>
          <p class="sec-sub">从出题、批改到答疑与规划，AI 贯穿教与学的每个环节</p>
        </div>
        <div class="ai-grid reveal">
          <div v-for="(a, i) in aiPowers" :key="i" class="ai-card" :style="{ '--mc': a.hex }" @mousemove="followLight">
            <div class="ai-icon" :style="{ background: a.gradient }">
              <el-icon :size="24"><component :is="a.icon" /></el-icon>
            </div>
            <h3>{{ a.title }}</h3>
            <p>{{ a.desc }}</p>
            <div class="ai-mods">
              <span v-for="m in a.mods" :key="m" class="x-chip">{{ m }}</span>
            </div>
          </div>
        </div>

        <!-- AI 批改演示流 -->
        <div class="ai-demo reveal">
          <div class="demo-q">
            <div class="demo-label">学生主观题作答</div>
            <p>简述牛顿第二定律，并推导 F=ma 在非惯性系下的修正形式。</p>
            <em>「物体加速度与所受合外力成正比、与质量成反比……在非惯性系中需要引入惯性力进行修正。」</em>
          </div>
          <div class="demo-arrow"><i></i><el-icon :size="20"><MagicStick /></el-icon></div>
          <div class="demo-a">
            <div class="demo-label">AI 语义批改结果</div>
            <div class="score-ring">
              <svg viewBox="0 0 80 80">
                <circle class="bgc" cx="40" cy="40" r="34"></circle>
                <circle class="fgc" cx="40" cy="40" r="34"></circle>
              </svg>
              <div><b>92</b><span>/100</span></div>
            </div>
            <ul>
              <li class="ok">✓ 定律表述完整，比例关系准确</li>
              <li class="ok">✓ 惯性力修正概念正确</li>
              <li class="warn">△ 未区分平移与转动惯性系（-8 分）</li>
            </ul>
          </div>
        </div>
      </div>
    </section>

    <!-- ══ 全景能力 · 三角色 ══ -->
    <section class="section" id="panorama" ref="panoRef">
      <div class="container">
        <div class="sec-head reveal">
          <div class="sec-badge"><el-icon :size="13"><Compass /></el-icon> 全景能力</div>
          <h2 class="sec-title">同一平台，<span class="grad-text">三种角色</span></h2>
          <p class="sec-sub">无论你是组织考试的教师、闯关学习的学生，还是组建战队的队长，都有专属主场</p>
        </div>
        <div class="role-grid reveal">
          <div v-for="(r, i) in roles" :key="i" class="role-card" :style="{ '--mc': r.hex }">
            <div class="role-head">
              <div class="role-icon" :style="{ background: r.gradient }">
                <el-icon :size="22"><component :is="r.icon" /></el-icon>
              </div>
              <div>
                <h3>{{ r.title }}</h3>
                <span>{{ r.sub }}</span>
              </div>
            </div>
            <div class="role-items">
              <div v-for="it in r.items" :key="it" class="role-item"><i :style="{ background: r.hex }"></i>{{ it }}</div>
            </div>
          </div>
        </div>

        <!-- 题型与知识点矩阵 -->
        <div class="matrix reveal">
          <div class="mx-block">
            <h4><el-icon :size="15"><Document /></el-icon> 支持题型全覆盖</h4>
            <div class="mx-chips">
              <span v-for="t in qTypes" :key="t" class="mx-chip">{{ t }}</span>
            </div>
          </div>
          <div class="mx-block">
            <h4><el-icon :size="15"><DataAnalysis /></el-icon> 学情分析维度</h4>
            <div class="mx-chips">
              <span v-for="d in dimTags" :key="d" class="mx-chip alt">{{ d }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ══ 成长闭环 ══ -->
    <section class="section" id="workflow" ref="workflowRef">
      <div class="container">
        <div class="sec-head reveal">
          <div class="sec-badge"><el-icon :size="13"><Refresh /></el-icon> 成长闭环</div>
          <h2 class="sec-title">测评 → 巩固 → 攻克 → 竞技 → <span class="grad-text">共创</span></h2>
          <p class="sec-sub">五个模块环环相扣，你的每一步都有去处</p>
        </div>
        <div class="loop-steps reveal">
          <div v-for="(s, i) in steps" :key="i" class="loop-step" :style="{ '--d': i * 0.12 + 's' }">
            <div class="loop-num">0{{ i + 1 }}</div>
            <div class="loop-icon" :style="{ background: s.gradient }">
              <el-icon :size="22"><component :is="s.icon" /></el-icon>
            </div>
            <h3>{{ s.title }}</h3>
            <p>{{ s.desc }}</p>
            <span class="loop-mod" :style="{ color: s.hex, borderColor: s.hex + '55' }">{{ s.from }}</span>
            <div v-if="i < steps.length - 1" class="loop-arrow"><el-icon :size="18"><ArrowRight /></el-icon></div>
          </div>
        </div>
      </div>
    </section>

    <!-- ══ 用户心声 ══ -->
    <section class="section" id="voices" ref="voicesRef">
      <div class="container">
        <div class="sec-head reveal">
          <div class="sec-badge"><el-icon :size="13"><ChatDotRound /></el-icon> 用户心声</div>
          <h2 class="sec-title">他们在智汇学场，<span class="grad-text">学到了什么</span></h2>
          <p class="sec-sub">来自教师、学生与队长的真实使用姿势</p>
        </div>
        <div class="voice-grid reveal">
          <div v-for="(v, i) in voices" :key="i" class="voice-card" :class="{ wide: i === 0 }">
            <div class="voice-quote">“</div>
            <p>{{ v.text }}</p>
            <div class="voice-who">
              <span class="v-ava" :style="{ background: v.gradient }">{{ v.name.charAt(0) }}</span>
              <div>
                <b>{{ v.name }}</b>
                <em>{{ v.role }}</em>
              </div>
              <span class="v-tag" :style="{ color: v.hex, borderColor: v.hex + '55' }">{{ v.tag }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ══ 常见问题 ══ -->
    <section class="section" id="faq" ref="faqRef">
      <div class="container faq-wrap">
        <div class="sec-head reveal">
          <div class="sec-badge"><el-icon :size="13"><QuestionFilled /></el-icon> 常见问题</div>
          <h2 class="sec-title">答疑时间</h2>
          <p class="sec-sub">开始之前，这些答案也许能帮到你</p>
        </div>
        <div class="faq-list reveal">
          <div
            v-for="(f, i) in faqs" :key="i"
            class="faq-item" :class="{ open: faqOpen === i }"
            @click="faqOpen = faqOpen === i ? -1 : i"
          >
            <div class="faq-q">
              <span>{{ f.q }}</span>
              <el-icon class="faq-arrow" :size="16"><ArrowRight /></el-icon>
            </div>
            <div class="faq-a"><p>{{ f.a }}</p></div>
          </div>
        </div>
      </div>
    </section>

    <!-- ══ CTA ══ -->
    <section class="section cta-section" ref="ctaRef">
      <div class="container cta-box reveal">
        <h2>五种场域，<span class="grad-text">一个账号</span></h2>
        <p>注册即享全部功能，把学习交给智汇学场</p>
        <div class="cta-btns">
          <router-link to="/register" class="btn btn-xl btn-primary btn-glow">免费注册 <el-icon :size="17"><ArrowRight /></el-icon></router-link>
          <router-link :to="loginLink" class="btn btn-xl btn-glass">已有账号，登录</router-link>
        </div>
        <div class="cta-notes">
          <span><el-icon :size="13"><Check /></el-icon> 永久免费基础功能</span>
          <span><el-icon :size="13"><Check /></el-icon> 无需信用卡</span>
          <span><el-icon :size="13"><Check /></el-icon> 30 秒完成注册</span>
        </div>
      </div>
    </section>

    <!-- ══ Footer ══ -->
    <footer class="footer">
      <div class="container foot-grid">
        <div class="foot-brand">
          <div class="navbar-brand">
            <div class="brand-logo"><el-icon :size="20"><School /></el-icon></div>
            <span class="brand-text">智汇学场</span>
          </div>
          <p>融合考试、作业、竞赛、悬赏、自学的一体化智能学习平台。以 AI 赋能教与学，让每个进步都看得见。</p>
          <div class="foot-badges">
            <span class="x-chip">Flask 3.1</span><span class="x-chip">Vue 3</span>
            <span class="x-chip">WebSocket 实时对战</span><span class="x-chip">AI 大模型</span>
          </div>
        </div>
        <div class="foot-col" v-for="col in footCols" :key="col.title">
          <h4>{{ col.title }}</h4>
          <router-link v-for="l in col.links" :key="l.t" :to="l.to">{{ l.t }}</router-link>
        </div>
      </div>
      <div class="container foot-bottom">
        © 2026 智汇学场 · Smart Learning Arena —— 让每一次学习，都有场域可依
      </div>
    </footer>

    <VideoModal :show="showVideoModal" @close="showVideoModal = false" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, markRaw, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import {
  School, Moon, Sunny, ArrowRight, VideoPlay, MagicStick, Check, Grid, Refresh,
  Calendar, Trophy, Coin, Reading, EditPen, DataAnalysis, ChatDotRound, Compass,
  Document, QuestionFilled, User, Notebook
} from '@element-plus/icons-vue'
import VideoModal from '../components/VideoModal.vue'
import { useThemeStore } from '../stores/theme'

const route = useRoute()
const theme = useThemeStore()
const isDark = ref(true)
const isScrolled = ref(false)
const showVideoModal = ref(false)
const active = ref(0)
const faqOpen = ref(0)

// 带 redirect 参数时把登录链接透传下去，方便用户登录后跳回原路径
const loginLink = computed(() => {
  const r = route.query.redirect
  return (typeof r === 'string' && r.startsWith('/') && !r.startsWith('//')) ? `/login?redirect=${encodeURIComponent(r)}` : '/login'
})

const heroRef = ref(null); const modulesRef = ref(null); const aiRef = ref(null)
const panoRef = ref(null); const workflowRef = ref(null); const voicesRef = ref(null)
const faqRef = ref(null); const ctaRef = ref(null)
const s1 = ref(null); const s2 = ref(null); const s3 = ref(null); const s4 = ref(null)
const pkA = ref(null); const pkB = ref(null)
const pkQ = ref(4)

// ── 跑马灯词条 ──
const tickerItems = [
  'AI 智能组卷', '1v1 实时 PK', '遗忘曲线复习', '悬赏共创题库', '切屏检测防作弊',
  '知识图谱学习路径', '段位勋章体系', '主观题语义评分', '战队团队赛', '学习计划甘特视图',
  '8 种题型全覆盖', '积分排行榜', '错题自动沉淀', 'AI 苏格拉底式答疑', '赛季结算晋升',
]

// ── 五大模块数据（与登录后 Portal 渐变一致）──
const modules = [
  {
    key: 'exam', short: '考试', title: '在线考试', tagline: '智能组卷 · 自动批改',
    icon: markRaw(Calendar), hex: '#8b5cf6',
    gradient: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
    mockUrl: 'arena/exam/dashboard',
    desc: '覆盖「出题 → 组卷 → 考试 → 批改 → 分析」全流程。8 种题型自由组合，AI 按知识点难度智能组卷，客观题秒判、主观题语义评分，成绩支持班级/知识点/题目三维透视。',
    points: ['公共题库 · 跨教师共享', 'AI 智能组卷', '切屏检测防作弊', '主观题 AI 语义评分', '成绩多维分析'],
    figures: [{ num: '8 种', label: '题型支持' }, { num: '3 维', label: '成绩分析' }, { num: '秒级', label: '客观题判分' }],
  },
  {
    key: 'competition', short: '竞赛', title: '答题竞赛', tagline: '实时 PK · 排位冲段',
    icon: markRaw(Trophy), hex: '#f59e0b',
    gradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
    mockUrl: 'arena/competition/pk',
    desc: '以赛促学的实时竞技场。1v1 PK 毫秒级同步对战、限时积分赛全服排位、段位勋章与战队协作赛，AI 按水平智能匹配对手，让每次答题都心跳加速。',
    points: ['1v1 实时 PK 对战', '赛季积分排位', '段位勋章体系', '战队协作与团队赛', 'AI 智能匹配对手'],
    figures: [{ num: '1v1', label: '毫秒级对战' }, { num: '7 档', label: '段位体系' }, { num: '赛季', label: '周期性结算' }],
  },
  {
    key: 'bounty', short: '悬赏', title: '征集悬赏', tagline: '积分激励 · 众创题库',
    icon: markRaw(Coin), hex: '#ec4899',
    gradient: 'linear-gradient(135deg, #ec4899 0%, #db2777 100%)',
    mockUrl: 'arena/bounty/plaza',
    desc: '人人参与的题目共创市场。教师按缺口发布题目悬赏，学生投稿作答，审核采纳即赚竞技积分；优质投稿沉淀进公共题库，让题库在社区流转中持续生长。',
    points: ['悬赏发布 · 定价自由', '投稿与审核流转', '采纳即得积分', '积分可流通全模块', '众创题库沉淀'],
    figures: [{ num: '4 步', label: '悬赏流转' }, { num: '∞', label: '题库自生长' }, { num: '积分', label: '全模块流通' }],
  },
  {
    key: 'learning', short: '自学', title: '自主学习', tagline: '闭环提升 · AI 陪学',
    icon: markRaw(Reading), hex: '#06b6d4',
    gradient: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)',
    mockUrl: 'arena/learning/plan',
    desc: '从测到学的闭环提升引擎。错题自动沉淀并按遗忘曲线间隔复习，学习计划支持 AI 一键拆解与甘特追踪，专业学习路径以知识图谱呈现，遇到卡点随时唤起 AI 答疑。',
    points: ['智能错题本 · 间隔复习', 'AI 拆解学习计划', '甘特视图 · 时间轴', '知识图谱学习路径', 'AI 答疑 · 每日报告'],
    figures: [{ num: '5 轮', label: '间隔复习' }, { num: '1 句', label: '话拆出计划' }, { num: '24/7', label: 'AI 陪学' }],
  },
  {
    key: 'homework', short: '作业', title: '作业练习', tagline: '全链批改 · AI 讲评',
    icon: markRaw(Notebook), hex: '#10b981',
    gradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
    mockUrl: 'arena/homework/manage',
    desc: '贯穿「布置 → 作答 → 批改 → 订正 → 讲评」的作业全链路。题集式与开放式双形态，客观题自动判分、主观题 AI 初评加人工复核，支持匿名互评、评分量规、查重检测与过程监测；退回可订正重交，优秀作业上展示墙，成绩还能汇入课程成绩册。',
    points: ['题集式 / 开放式双形态', 'AI 批改建议 + 班级讲评', '匿名互评 · 评分量规', '查重检测 · 过程监测', '退回订正 · 优秀展示墙'],
    figures: [{ num: '2 形态', label: '题集/开放' }, { num: 'AI', label: '初评+讲评' }, { num: '全链', label: '布置到讲评' }],
  },
]

// ── 仿真窗口内的假数据 ──
const mockData = {
  exams: [
    { name: '期中高数模拟', color: '#8b5cf6', done: 42, total: 48, pct: 88 },
    { name: '线章阶段测验', color: '#06b6d4', done: 35, total: 48, pct: 73 },
    { name: '英语单元测 Unit 3', color: '#f59e0b', done: 20, total: 45, pct: 44 },
  ],
  pkOpts: [
    { t: 'A. list', cls: '' }, { t: 'B. tuple', cls: 'ok' },
    { t: 'C. dict', cls: 'bad' }, { t: 'D. set', cls: '' },
  ],
  bounties: [
    { title: '求「洛必达法则」计算题 3 道', meta: '高数 · 已收 7 份投稿', reward: 60, state: '采纳中', cls: 'ing' },
    { title: '补强「二叉树遍历」代码题', meta: '数据结构 · 已收 3 份投稿', reward: 80, state: '待审', cls: 'wait' },
    { title: '英语六级阅读长难句解析题', meta: '大学英语 · 已收 12 份投稿', reward: 45, state: '已结束', cls: 'end' },
  ],
  homeworks: [
    { name: '高数第一章 · 课后习题', meta: '题集式 · 已交 48 人待批 12', pct: 75, color: '#10b981', state: '批改中' },
    { name: '数据结构 · 链表编程题', meta: '开放式 · AI 已初评 30 份', pct: 62, color: '#8b5cf6', state: '待复核' },
    { name: '大学英语 · 作文 Unit 3', meta: '互评进行中 · 已收 20 份', pct: 40, color: '#f59e0b', state: '互评中' },
  ],
}

// ── AI 引擎 ──
const aiPowers = [
  { title: 'AI 智能出题', hex: '#8b5cf6', icon: markRaw(EditPen), gradient: 'linear-gradient(135deg,#6366f1,#8b5cf6)',
    desc: '按知识点、难度、题型描述需求，秒级生成整卷题目，自动查重去歧义。', mods: ['在线考试', '征集悬赏'] },
  { title: 'AI 语义批改', hex: '#06b6d4', icon: markRaw(DataAnalysis), gradient: 'linear-gradient(135deg,#06b6d4,#0891b2)',
    desc: '主观题不再逐字批改——AI 理解题意给分、标注失分点，教师复核一键确认；作业批改同样智能省时。', mods: ['在线考试', '作业练习', '自主学习'] },
  { title: 'AI 学习答疑', hex: '#10b981', icon: markRaw(ChatDotRound), gradient: 'linear-gradient(135deg,#10b981,#059669)',
    desc: '苏格拉底式引导对话，不直接给答案；错题可追问，卡点随时拆解。', mods: ['自主学习'] },
  { title: 'AI 路径规划', hex: '#f59e0b', icon: markRaw(Compass), gradient: 'linear-gradient(135deg,#f59e0b,#d97706)',
    desc: '一句话目标自动拆解成带截止日的学习计划，掌握度引擎动态推荐下一步。', mods: ['自主学习', '答题竞赛'] },
]

// ── 三角色全景 ──
const roles = [
  { title: '教师 · 教得省心', sub: '出题批改全托管', hex: '#8b5cf6', icon: markRaw(User),
    gradient: 'linear-gradient(135deg,#6366f1,#8b5cf6)',
    items: ['题库 / 章节 / 知识点三级管理', 'AI 一句话生成整卷试题', '作业布置 · AI 初评与讲评', '考试发布与切屏监考', '主观题 AI 初评 + 人工复核', '班级成绩知识点失分透视', '发布悬赏补齐题目缺口'] },
  { title: '学生 · 学得带劲', sub: '从测评到逆袭', hex: '#06b6d4', icon: markRaw(Reading),
    gradient: 'linear-gradient(135deg,#06b6d4,#0891b2)',
    items: ['参加考试并即时查看解析', '完成作业并订正重交', '错题本自动归集 + 间隔复习', 'AI 拆解学习计划并打卡', '自由刷题按知识点突破', '知识图谱指引学习路径', '答悬赏赚积分冲排行榜'] },
  { title: '战队队长 · 赛得热血', sub: '带队冲击赛季榜', hex: '#f59e0b', icon: markRaw(Trophy),
    gradient: 'linear-gradient(135deg,#f59e0b,#d97706)',
    items: ['创建 / 加入战队', '战队内部战绩贡献', '团队赛协同作战', '赛季段位晋升结算', '段位勋章墙收藏荣誉'] },
]

const qTypes = ['单选题', '多选题', '判断题', '填空题', '简答题', '论述题', '程序题', '组合题']
const dimTags = ['班级均分趋势', '知识点得分率', '题目区分度', '错题沉淀率', '学习活跃度', '复习完成度', '段位分布', '悬赏贡献度']

// ── 成长闭环 ──
const steps = [
  { title: '测评摸底', desc: '考试 / 刷题定位当前水平，暴露薄弱知识点', icon: markRaw(Calendar), hex: '#8b5cf6', from: '在线考试', gradient: 'linear-gradient(135deg,#6366f1,#8b5cf6)' },
  { title: '作业巩固', desc: '课后作业逐个巩固，AI 初评 + 教师反馈精准补齐', icon: markRaw(Notebook), hex: '#10b981', from: '作业练习', gradient: 'linear-gradient(135deg,#10b981,#059669)' },
  { title: '攻克提升', desc: '错题本间隔复习 + AI 学习计划逐个击破', icon: markRaw(Reading), hex: '#06b6d4', from: '自主学习', gradient: 'linear-gradient(135deg,#06b6d4,#0891b2)' },
  { title: '竞技检验', desc: 'PK 与排位赛实战检验，能力段位双晋升', icon: markRaw(Trophy), hex: '#f59e0b', from: '答题竞赛', gradient: 'linear-gradient(135deg,#f59e0b,#d97706)' },
  { title: '共创反哺', desc: '答悬赏、投稿题目赚积分，反哺社区题库', icon: markRaw(Coin), hex: '#ec4899', from: '征集悬赏', gradient: 'linear-gradient(135deg,#ec4899,#db2777)' },
]

// ── 用户心声 ──
const voices = [
  { name: '林老师', role: '高中数学教师 · 使用 8 个月', tag: '效率提升', hex: '#8b5cf6',
    gradient: 'linear-gradient(135deg,#6366f1,#8b5cf6)',
    text: '以前最头疼的就是出卷和批改主观题。现在 AI 按知识点组卷，交卷后客观题秒判、主观题 AI 先给一版分，我只要复核——每次月考我能省出大半天。成绩分析直接指出全班在「数形结合」上得分率最低，下节课讲什么一目了然。' },
  { name: '小陈', role: '大二学生 · 赛季段位「钻石」', tag: '错题本', hex: '#06b6d4',
    gradient: 'linear-gradient(135deg,#06b6d4,#0891b2)',
    text: '错题本是真香，错过的题按遗忘曲线推给我复习，期末前基本没有陌生题型。' },
  { name: 'Kira', role: '数据结构课代表', tag: '悬赏达人', hex: '#ec4899',
    gradient: 'linear-gradient(135deg,#ec4899,#db2777)',
    text: '给老师投稿了 11 道题，采纳 8 道，积分够我在 PK 商城横着走了。' },
  { name: '老张队长', role: '「极限挑战」战队队长', tag: '团队赛', hex: '#f59e0b',
    gradient: 'linear-gradient(135deg,#f59e0b,#d97706)',
    text: '赛季末团队赛全员刷贡献那晚，宿舍楼道都在喊，氛围拉满。' },
]

// ── FAQ ──
const faqs = [
  { q: '智汇学场和普通考试系统有什么不同？', a: '普通系统只管「考」，智汇学场把「考 → 学 → 赛 → 创」连成闭环：考试暴露的薄弱知识点自动流入错题本与学习计划，学完可以去 PK 和竞赛检验，还能通过悬赏投稿把你会的题沉淀给社区，积分在五个模块间流通。' },
  { q: 'AI 批改靠谱吗？会不会乱给分？', a: '客观题由系统精确判分；主观题采用 AI 语义评分，按得分点给分并标注失分原因，最终成绩支持教师一键复核调整。AI 是初评助手，打分权始终在教师手里。' },
  { q: '学生和教师账号有什么区别？', a: '教师账号拥有题库管理、组卷、考试发布、批改与成绩分析等教务能力；学生账号可以参加考试、错题复习、自由刷题、参与 PK/竞赛/悬赏。' },
  { q: 'PK 对战和竞赛是怎么匹配的？', a: '实时 PK 通过 WebSocket 毫秒级同步，AI 按答题水平与段位就近匹配；积分竞赛为限时全员同场，按得分与用时实时排行，赛季结束后按名次结算段位并发放勋章。' },
  { q: '悬赏积分能做什么？', a: '悬赏采纳所得积分为全模块通货：可用于排位赛结算奖励、排行榜荣誉展示，未来还会扩展更多权益。题目被采纳越多，说明你的输出质量越高，这本身就是学习能力的证明。' },
  { q: '使用时需要注意什么浏览器？', a: '推荐 Chrome / Edge 等现代浏览器。实时 PK 依赖 WebSocket 长连接，如在校园网受限环境可能自动降级为轮询模式，不影响基本使用。' },
]

const footCols = [
  { title: '模块', links: [{ t: '在线考试', to: '/login' }, { t: '作业练习', to: '/login' }, { t: '答题竞赛', to: '/login' }, { t: '征集悬赏', to: '/login' }, { t: '自主学习', to: '/login' }] },
  { title: '能力', links: [{ t: 'AI 智能出题', to: '/login' }, { t: 'AI 语义批改', to: '/login' }, { t: '知识图谱路径', to: '/login' }, { t: '段位勋章体系', to: '/login' }] },
  { title: '开始', links: [{ t: '注册新账号', to: '/register' }, { t: '登录', to: '/login' }, { t: '常见问题', to: '/home' }] },
]

// ── 交互逻辑 ──
function pickModule(i) { active.value = i }

function followLight(e) {
  const r = e.currentTarget.getBoundingClientRect()
  e.currentTarget.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100) + '%')
  e.currentTarget.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100) + '%')
}

const onScroll = () => { isScrolled.value = window.scrollY > 40 }
const scrollTo = (id) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
const scrollToTop = () => window.scrollTo({ top: 0, behavior: 'smooth' })

function toggleTheme() {
  isDark.value = !isDark.value
  // 单一真值：委托 theme store 同步 html.dark + localStorage，
  // 避免本页只改 localStorage 而 store/DOM 落后，导致进入内页后主题失步（表格深底等）
  theme.setTheme(isDark.value)
}

// 数字滚动
function countUp(el, end, dur = 1600) {
  if (!el || el.dataset.done) return
  el.dataset.done = '1'
  const t0 = performance.now()
  const tick = (now) => {
    const p = Math.min((now - t0) / dur, 1)
    const ease = 1 - Math.pow(1 - p, 3)
    el.textContent = Math.round(end * ease).toLocaleString()
    if (p < 1) requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

// PK 假分数跳动
let pkTimer = null
function startPkTick() {
  if (pkTimer) return
  let a = 7, b = 6, q = 4
  pkTimer = setInterval(() => {
    if (Math.random() > 0.5) a++; else b++
    q = Math.min(q + 1, 10)
    if (pkA.value) pkA.value.textContent = a
    if (pkB.value) pkB.value.textContent = b
    pkQ.value = q
    if (q >= 10) {
      clearInterval(pkTimer); pkTimer = null
      setTimeout(() => {
        if (pkA.value) pkA.value.textContent = '7'
        if (pkB.value) pkB.value.textContent = '6'
        pkQ.value = 4; startPkTick()
      }, 2200)
    }
  }, 1400)
}

// IntersectionObserver 统一驱动 reveal / 数字
let io = null
onMounted(() => {
  isDark.value = localStorage.getItem('theme') !== 'light'
  window.addEventListener('scroll', onScroll, { passive: true })

  io = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (!e.isIntersecting) return
      e.target.classList.add('in')
      if (e.target === heroRef.value) {
        countUp(s1.value, 10000); countUp(s2.value, 5); countUp(s3.value, 8); countUp(s4.value, 30)
      }
    })
  }, { threshold: 0.12 })

  nextTick(() => {
    document.querySelectorAll('.home-page .reveal').forEach(el => io.observe(el))
    if (heroRef.value) io.observe(heroRef.value)
  })
  // PK mock 首次进入即启动跳动
  startPkTick()
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  if (io) io.disconnect()
  if (pkTimer) clearInterval(pkTimer)
})
</script>

<style scoped>
/* ── 变量：暗色沉浸为默认，light 类切亮色 ── */
.home-page {
  --bg0: #070a1a;
  --card: rgba(255, 255, 255, 0.045);
  --card-strong: rgba(255, 255, 255, 0.08);
  --line: rgba(255, 255, 255, 0.09);
  --txt: #eef1ff;
  --txt2: #9aa3c7;
  --txt3: #667099;
  --accent: #8b5cf6;
  --accent2: #22d3ee;
  --glass: rgba(7, 10, 26, .72);
  --mock-shadow: 0 24px 60px rgba(0, 0, 0, .35);
  position: relative;
  min-height: 100vh;
  background: var(--bg0);
  color: var(--txt);
  font-family: 'Inter', -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  overflow-x: hidden;
}
.home-page.light {
  --bg0: #f4f6fb;
  --card: rgba(255, 255, 255, 0.72);
  --card-strong: #ffffff;
  --line: rgba(15, 23, 42, 0.09);
  --txt: #101832;
  --txt2: #4b5678;
  --txt3: #8a93b3;
  --glass: rgba(244, 246, 251, .82);
  --mock-shadow: 0 24px 50px rgba(15, 23, 42, .12);
}

.container { max-width: 1200px; margin: 0 auto; padding: 0 24px; }

/* ── 背景极光 ── */
.bg-layer { position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; background: linear-gradient(180deg, var(--bg0), transparent 30%, transparent 70%, var(--bg0)); }
.aurora { position: absolute; border-radius: 50%; filter: blur(110px); opacity: .5; animation: drift 26s ease-in-out infinite alternate; }
.a1 { width: 55vw; height: 55vw; left: -12vw; top: -18vw; background: radial-gradient(circle, rgba(139,92,246,.55), transparent 65%); }
.a2 { width: 48vw; height: 48vw; right: -14vw; top: 8vh; background: radial-gradient(circle, rgba(34,211,238,.4), transparent 65%); animation-delay: -8s; }
.a3 { width: 40vw; height: 40vw; left: 22vw; bottom: -22vw; background: radial-gradient(circle, rgba(236,72,153,.32), transparent 65%); animation-delay: -16s; }
@keyframes drift { from { transform: translate(0,0) scale(1); } to { transform: translate(6vw, -4vh) scale(1.15); } }
.noise { position: absolute; inset: 0; opacity: .28; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.04 0'/%3E%3C/filter%3E%3Crect width='120' height='120' filter='url(%23n)'/%3E%3C/svg%3E"); }
.light .aurora { opacity: .3; filter: blur(120px); }

/* ── 入场动画 ── */
.rise { opacity: 0; transform: translateY(26px); animation: rise .8s cubic-bezier(.2,.7,.2,1) forwards; animation-delay: var(--d, 0s); }
@keyframes rise { to { opacity: 1; transform: none; } }
.reveal { opacity: 0; transform: translateY(34px); transition: opacity .8s cubic-bezier(.2,.7,.2,1), transform .8s cubic-bezier(.2,.7,.2,1); }
.reveal.in { opacity: 1; transform: none; }

/* ── 渐变文字 / 按钮 ── */
.grad-text {
  background: linear-gradient(100deg, #a78bfa 0%, #22d3ee 50%, #f472b6 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  animation: shine 6s linear infinite;
}
@keyframes shine { to { background-position: -200% 0; } }

.btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 22px; border-radius: 12px; font-weight: 600; font-size: .92rem; text-decoration: none; border: 1px solid transparent; cursor: pointer; transition: all .25s ease; font-family: inherit; }
.btn-primary { background: linear-gradient(120deg, #7c3aed, #06b6d4); color: #fff; }
.btn-primary:hover { transform: translateY(-2px); filter: brightness(1.12); }
.btn-glow { box-shadow: 0 6px 24px rgba(124, 58, 237, .45); }
.btn-glow:hover { box-shadow: 0 10px 32px rgba(124, 58, 237, .6); }
.btn-ghost { color: var(--txt2); border-color: var(--line); background: transparent; }
.btn-ghost:hover { color: var(--txt); border-color: rgba(139,92,246,.6); background: rgba(139,92,246,.1); }
.btn-glass { background: var(--card); border-color: var(--line); color: var(--txt); backdrop-filter: blur(10px); }
.btn-glass:hover { background: var(--card-strong); transform: translateY(-2px); }
.btn-xl { padding: 15px 30px; font-size: 1rem; border-radius: 14px; }

/* ── 导航 ── */
.navbar { position: fixed; top: 0; left: 0; right: 0; z-index: 100; transition: all .35s ease; border-bottom: 1px solid transparent; }
.navbar.scrolled { background: var(--glass); backdrop-filter: blur(18px); border-bottom-color: var(--line); }
.nav-inner { display: flex; align-items: center; justify-content: space-between; height: 68px; }
.navbar-brand { display: flex; align-items: center; gap: 11px; cursor: pointer; }
.brand-logo { width: 38px; height: 38px; border-radius: 12px; background: linear-gradient(135deg, #6366f1, #06b6d4); display: flex; align-items: center; justify-content: center; color: #fff; box-shadow: 0 4px 16px rgba(99,102,241,.4); }
.brand-text { font-weight: 700; font-size: 1.18rem; background: linear-gradient(120deg, #c4b5fa, #67e8f9); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.light .brand-text { background: linear-gradient(120deg, #6d28d9, #0e7490); -webkit-background-clip: text; background-clip: text; }
.navbar-links { display: flex; gap: 28px; }
.nav-link { color: var(--txt2); text-decoration: none; font-size: .93rem; font-weight: 500; transition: color .2s; }
.nav-link:hover { color: var(--txt); }
.navbar-actions { display: flex; align-items: center; gap: 12px; }
.theme-toggle { width: 38px; height: 38px; border-radius: 50%; border: 1px solid var(--line); background: var(--card); color: var(--txt2); cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all .25s; }
.theme-toggle:hover { color: #fbbf24; border-color: rgba(251,191,36,.5); transform: rotate(30deg); }

/* ── Hero ── */
.hero { position: relative; z-index: 1; min-height: 100vh; display: flex; align-items: center; padding: 110px 0 80px; }
.hero-grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: 48px; align-items: center; }
.hero-badge { display: inline-flex; align-items: center; gap: 9px; padding: 7px 16px; border-radius: 99px; border: 1px solid rgba(139,92,246,.4); background: rgba(139,92,246,.12); color: #c4b5fd; font-size: .85rem; margin-bottom: 26px; }
.light .hero-badge { color: #6d28d9; }
.pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: #34d399; box-shadow: 0 0 0 0 rgba(52,211,153,.6); animation: pulse 2s infinite; }
@keyframes pulse { 70% { box-shadow: 0 0 0 9px rgba(52,211,153,0); } 100% { box-shadow: 0 0 0 0 rgba(52,211,153,0); } }
.hero-title { font-size: clamp(2.4rem, 4.6vw, 3.7rem); font-weight: 800; line-height: 1.18; margin: 0 0 22px; letter-spacing: .5px; }
.hero-title .line { display: block; }
.hero-sub { font-size: 1.08rem; line-height: 1.9; color: var(--txt2); max-width: 520px; margin: 0 0 36px; }
.hero-btns { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 52px; }
.hero-stats { display: flex; align-items: center; gap: 26px; flex-wrap: wrap; padding: 20px 26px; border-radius: 18px; border: 1px solid var(--line); background: var(--card); backdrop-filter: blur(14px); }
.hstat-num { font-size: 1.65rem; font-weight: 800; font-style: normal; }
.hstat-num em { font-style: normal; background: linear-gradient(120deg, #fff, #a5b4fc); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.light .hstat-num em { background: linear-gradient(120deg, #4f46e5, #0891b2); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.hstat-num i { font-style: normal; font-size: .95rem; color: var(--accent2); margin-left: 2px; }
.hstat-label { font-size: .8rem; color: var(--txt3); margin-top: 3px; }
.hstat-sep { width: 1px; height: 36px; background: var(--line); }

.hero-orbit { position: relative; width: 100%; aspect-ratio: 1; max-width: 440px; margin: 0 auto; }
.orbit-core { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); width: 130px; height: 130px; border-radius: 50%; background: radial-gradient(circle at 35% 30%, rgba(139,92,246,.35), rgba(13,18,48,.9)); border: 1px solid rgba(139,92,246,.45); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: #ddd6fe; font-weight: 700; font-size: .9rem; box-shadow: 0 0 60px rgba(139,92,246,.35); animation: breathe 5s ease-in-out infinite; }
.light .orbit-core { background: radial-gradient(circle at 35% 30%, rgba(139,92,246,.25), rgba(255,255,255,.92)); color: #4c1d95; }
@keyframes breathe { 50% { box-shadow: 0 0 90px rgba(34,211,238,.4); transform: translate(-50%, -50%) scale(1.04); } }
.orbit-core::before, .orbit-core::after { content: ''; position: absolute; inset: -34px; border-radius: 50%; border: 1px dashed rgba(255,255,255,.12); animation: spin 26s linear infinite; }
.orbit-core::after { inset: -74px; animation-duration: 44s; animation-direction: reverse; border-color: rgba(139,92,246,.18); }
.light .orbit-core::before, .light .orbit-core::after { border-color: rgba(76,29,149,.18); }
@keyframes spin { to { transform: rotate(360deg); } }
.orbit-chip { position: absolute; display: flex; align-items: center; gap: 7px; padding: 11px 18px; border-radius: 14px; color: #fff; font-weight: 600; font-size: .88rem; cursor: pointer; box-shadow: 0 10px 28px rgba(0,0,0,.35); transition: transform .25s ease, box-shadow .25s; animation: float 6s ease-in-out infinite; z-index: 2; }
.orbit-chip:hover { transform: scale(1.1); box-shadow: 0 14px 36px rgba(0,0,0,.5); }
.oc1 { left: 4%; top: 14%; }
.oc2 { right: 0; top: 32%; animation-delay: -1.5s; }
.oc3 { left: 10%; bottom: 14%; animation-delay: -3s; }
.oc4 { right: 6%; bottom: 30%; animation-delay: -4.5s; }
.oc5 { left: 38%; bottom: -1%; animation-delay: -6s; }
@keyframes float { 50% { transform: translateY(-12px); } }

.scroll-hint { position: absolute; left: 50%; bottom: 26px; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--txt3); font-size: .75rem; cursor: pointer; }
.mouse { width: 24px; height: 38px; border: 2px solid var(--txt3); border-radius: 14px; display: flex; justify-content: center; padding-top: 7px; box-sizing: border-box; }
.wheel { width: 3px; height: 8px; border-radius: 3px; background: var(--accent2); animation: wheel 1.6s infinite; }
@keyframes wheel { 50% { transform: translateY(10px); opacity: .2; } }
.scroll-hint em { font-style: normal; letter-spacing: 2px; }

/* ── 跑马灯 ── */
.ticker { position: relative; z-index: 1; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); background: rgba(139,92,246,.06); padding: 14px 0; overflow: hidden; -webkit-mask-image: linear-gradient(90deg, transparent, #000 12%, #000 88%, transparent); mask-image: linear-gradient(90deg, transparent, #000 12%, #000 88%, transparent); }
.ticker-track { display: flex; gap: 44px; width: max-content; animation: marquee 38s linear infinite; }
.ticker:hover .ticker-track { animation-play-state: paused; }
.tk-item { display: inline-flex; align-items: center; gap: 10px; color: var(--txt2); font-size: .88rem; white-space: nowrap; }
.tk-dot { width: 6px; height: 6px; border-radius: 50%; background: linear-gradient(120deg, #8b5cf6, #22d3ee); }
@keyframes marquee { to { transform: translateX(calc(-50% - 22px)); } }

/* ── Section 通用 ── */
.section { position: relative; z-index: 1; padding: 104px 0; scroll-margin-top: 60px; }
.sec-head { text-align: center; margin-bottom: 58px; }
.sec-badge { display: inline-flex; align-items: center; gap: 7px; padding: 6px 16px; border-radius: 99px; border: 1px solid var(--line); background: var(--card); color: var(--txt2); font-size: .82rem; margin-bottom: 18px; }
.sec-title { font-size: clamp(1.8rem, 3.4vw, 2.6rem); font-weight: 800; margin: 0 0 14px; }
.sec-sub { color: var(--txt2); font-size: 1.02rem; margin: 0; }

/* ── 模块体验台 ── */
.showcase { display: grid; grid-template-columns: 300px 1fr; gap: 30px; align-items: start; }
.mod-rail { display: flex; flex-direction: column; gap: 14px; position: sticky; top: 96px; }
.mod-tab { display: flex; align-items: center; gap: 13px; padding: 15px 16px; border-radius: 16px; border: 1px solid var(--line); background: var(--card); cursor: pointer; transition: all .3s cubic-bezier(.2,.7,.2,1); position: relative; overflow: hidden; backdrop-filter: blur(10px); }
.mod-tab::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--mc); opacity: 0; transition: opacity .3s; }
.mod-tab:hover { transform: translateX(5px); border-color: rgba(139,92,246,.4); }
.mod-tab.on { background: var(--card-strong); border-color: var(--mc); box-shadow: 0 8px 30px rgba(0,0,0,.25); transform: translateX(5px); }
.mod-tab.on::before { opacity: 1; }
.mod-tab-icon { width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.mod-tab-body { flex: 1; min-width: 0; }
.mod-tab-title { font-weight: 700; font-size: .98rem; }
.mod-tab-tag { font-size: .76rem; color: var(--txt3); margin-top: 2px; }
.mod-tab-arrow { color: var(--txt3); opacity: 0; transform: translateX(-6px); transition: all .3s; }
.mod-tab.on .mod-tab-arrow { opacity: 1; transform: none; color: var(--mc); }

.mod-stage { display: flex; flex-direction: column; gap: 24px; min-width: 0; }
.mock-window { border-radius: 18px; border: 1px solid var(--line); background: linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.02)); backdrop-filter: blur(16px); overflow: hidden; box-shadow: var(--mock-shadow); animation: mockIn .55s cubic-bezier(.2,.7,.2,1); }
.light .mock-window { background: rgba(255,255,255,.85); }
@keyframes mockIn { from { opacity: 0; transform: translateY(16px) scale(.985); } }
.mock-bar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,.03); }
.dot { width: 11px; height: 11px; border-radius: 50%; }
.dot.r { background: #f87171; } .dot.y { background: #fbbf24; } .dot.g { background: #34d399; }
.mock-url { margin-left: 10px; font-size: .76rem; color: var(--txt3); font-family: Consolas, monospace; background: rgba(255,255,255,.05); padding: 3px 12px; border-radius: 8px; }
.light .mock-url { background: rgba(15,23,42,.05); }
.mock-live { margin-left: auto; display: flex; align-items: center; gap: 6px; font-size: .68rem; letter-spacing: 1.5px; color: #34d399; }
.mock-live i { width: 7px; height: 7px; border-radius: 50%; background: #34d399; animation: pulse 1.8s infinite; }
.mock-body { padding: 22px 24px 24px; min-height: 320px; }
.mb-title { font-weight: 700; font-size: 1.02rem; margin-bottom: 16px; }
.mb-title em { font-style: normal; font-size: .72rem; color: var(--txt3); border: 1px solid var(--line); padding: 2px 9px; border-radius: 99px; margin-left: 10px; vertical-align: 2px; }
.x-chip { font-size: .76rem; color: var(--txt2); border: 1px solid var(--line); background: var(--card); padding: 4px 12px; border-radius: 99px; }

/* mock: 考试 */
.exam-cards { display: flex; flex-direction: column; gap: 12px; }
.x-card { border: 1px solid var(--line); border-radius: 12px; padding: 13px 16px; background: var(--card); }
.x-head { font-size: .88rem; font-weight: 600; display: flex; align-items: center; gap: 8px; margin-bottom: 9px; }
.x-dot { width: 8px; height: 8px; border-radius: 50%; }
.x-bar { height: 6px; border-radius: 3px; background: rgba(255,255,255,.08); overflow: hidden; }
.light .x-bar, .light .tl-band { background: rgba(15,23,42,.07); }
.x-bar i { display: block; height: 100%; border-radius: 3px; animation: grow 1.2s cubic-bezier(.2,.7,.2,1); transform-origin: left; }
@keyframes grow { from { transform: scaleX(0); } }
.x-meta { display: flex; justify-content: space-between; font-size: .76rem; color: var(--txt3); margin-top: 7px; }
.x-foot { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }

/* mock: PK */
.pk-arena { display: grid; grid-template-columns: 1fr auto 1fr; gap: 12px; align-items: center; padding: 14px; border-radius: 14px; border: 1px solid var(--line); background: var(--card); margin-bottom: 16px; }
.pk-side { text-align: center; }
.pk-ava { width: 52px; height: 52px; border-radius: 50%; margin: 0 auto 8px; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 700; }
.pk-name { font-size: .78rem; color: var(--txt3); }
.pk-score { font-size: 2rem; font-weight: 800; color: #fbbf24; text-shadow: 0 0 24px rgba(251,191,36,.5); transition: all .3s; }
.pk-mid { text-align: center; }
.pk-mid span { display: block; font-weight: 900; font-size: 1.35rem; background: linear-gradient(120deg, #f472b6, #fbbf24); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.pk-mid em { font-style: normal; font-size: .72rem; color: var(--txt3); }
.pk-question { font-size: .92rem; margin-bottom: 12px; }
.pk-opts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.pk-opts span { padding: 10px 14px; border-radius: 10px; border: 1px solid var(--line); background: var(--card); font-size: .85rem; color: var(--txt2); }
.pk-opts .ok { border-color: rgba(52,211,153,.6); background: rgba(52,211,153,.12); color: #34d399; animation: pop .4s; }
.pk-opts .bad { border-color: rgba(248,113,113,.5); background: rgba(248,113,113,.1); color: #f87171; animation: shake .4s; }
@keyframes pop { 50% { transform: scale(1.05); } }
@keyframes shake { 25% { transform: translateX(-4px); } 75% { transform: translateX(4px); } }

/* mock: 悬赏 */
.b-row { display: flex; align-items: center; gap: 14px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); margin-bottom: 10px; }
.b-info { flex: 1; min-width: 0; }
.b-title { font-size: .88rem; font-weight: 600; }
.b-meta { font-size: .74rem; color: var(--txt3); margin-top: 4px; }
.b-reward { text-align: right; white-space: nowrap; }
.b-reward b { color: #f472b6; font-size: 1.15rem; }
.b-reward span { font-size: .72rem; color: var(--txt3); margin-left: 2px; }
.b-reward em { display: block; font-style: normal; font-size: .7rem; margin-top: 3px; }
.b-reward .ing { color: #34d399; } .b-reward .wait { color: #fbbf24; } .b-reward .end { color: var(--txt3); }
.b-flow { margin-top: 14px; text-align: center; font-size: .8rem; color: var(--txt2); border: 1px dashed var(--line); border-radius: 10px; padding: 10px; }

/* mock: 自学 */
.tl-plan { border: 1px solid var(--line); border-radius: 12px; background: var(--card); padding: 14px 16px; margin-bottom: 12px; }
.tl-name { font-size: .88rem; font-weight: 600; margin-bottom: 10px; }
.tl-band { position: relative; height: 10px; border-radius: 5px; background: rgba(255,255,255,.08); overflow: hidden; }
.tl-band .time { position: absolute; inset: 0 auto 0 0; background: rgba(244,63,94,.35); animation: grow 1.2s cubic-bezier(.2,.7,.2,1); }
.tl-band .done { position: absolute; inset: 0 auto 0 0; height: 100%; border-radius: 5px; background: linear-gradient(90deg, #06b6d4, #8b5cf6); animation: grow 1.2s cubic-bezier(.2,.7,.2,1) .2s; }
.tl-legend { display: flex; gap: 14px; font-size: .72rem; color: var(--txt3); margin-top: 8px; }
.tl-legend span:first-child { color: #f87171; } .tl-legend span:nth-child(2) { color: #22d3ee; }
.tl-legend em { font-style: normal; margin-left: auto; color: #fbbf24; }
.tl-tasks { display: flex; flex-direction: column; gap: 8px; }
.tl-task { display: flex; align-items: center; gap: 10px; font-size: .85rem; color: var(--txt2); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; background: var(--card); }
.tl-task i { width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--txt3); flex-shrink: 0; box-sizing: border-box; }
.tl-task.done { color: var(--txt3); text-decoration: line-through; }
.tl-task.done i { background: #10b981; border-color: #10b981; position: relative; }
.tl-task.done i::after { content: '✓'; position: absolute; inset: 0; color: #fff; font-size: 10px; display: flex; align-items: center; justify-content: center; }
.tl-task.overdue { border-color: rgba(248,113,113,.4); }
.tl-task.overdue em { font-style: normal; margin-left: auto; font-size: .7rem; color: #f87171; background: rgba(248,113,113,.12); padding: 2px 8px; border-radius: 99px; }
.learn-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }

/* mock: 作业练习 */
.mb-homework .hw-list { display: flex; flex-direction: column; gap: 12px; }
.hw-row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 12px; border: 1px solid var(--line); border-radius: 12px; padding: 12px 16px; background: var(--card); }
.hw-info { min-width: 0; }
.hw-name { font-size: .9rem; font-weight: 600; color: var(--txt); }
.hw-meta { font-size: .74rem; color: var(--txt3); margin-top: 2px; }
.hw-bar { width: 110px; height: 8px; border-radius: 99px; background: var(--line); overflow: hidden; }
.hw-bar i { display: block; height: 100%; border-radius: 99px; }
.hw-state { font-size: .74rem; font-weight: 600; border: 1px solid; border-radius: 99px; padding: 3px 12px; white-space: nowrap; }
.hw-flow { margin-top: 14px; text-align: center; font-size: .8rem; color: var(--txt2); border: 1px dashed var(--line); border-radius: 10px; padding: 10px; }

/* 模块详情 */
.mod-detail { border-radius: 18px; border: 1px solid var(--line); background: var(--card); backdrop-filter: blur(14px); padding: 26px 28px; animation: mockIn .55s cubic-bezier(.2,.7,.2,1) .12s backwards; }
.mod-desc { color: var(--txt2); line-height: 1.85; font-size: .96rem; margin-bottom: 18px; }
.mod-points { display: grid; grid-template-columns: 1fr 1fr; gap: 11px; margin-bottom: 20px; }
.point { display: flex; align-items: center; gap: 8px; font-size: .89rem; color: var(--txt); opacity: 0; transform: translateY(10px); animation: rise .5s ease forwards; animation-delay: var(--d); }
.pt-check { color: #34d399; }
.mod-figures { display: flex; gap: 12px; margin-bottom: 22px; }
.fig { flex: 1; text-align: center; border: 1px dashed var(--line); border-radius: 12px; padding: 12px 8px; }
.fig b { display: block; font-size: 1.2rem; background: linear-gradient(120deg, #a78bfa, #22d3ee); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.fig span { font-size: .74rem; color: var(--txt3); }
.btn-enter { color: #fff; justify-content: center; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,.3); }
.btn-enter:hover { transform: translateY(-2px); filter: brightness(1.1); }

/* ── AI 引擎 ── */
.ai-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
.ai-card { position: relative; border: 1px solid var(--line); border-radius: 18px; background: var(--card); backdrop-filter: blur(12px); padding: 28px 24px; transition: transform .35s cubic-bezier(.2,.7,.2,1), border-color .35s, box-shadow .35s; overflow: hidden; }
.ai-card::before { content: ''; position: absolute; inset: 0; background: radial-gradient(240px circle at var(--mx, 50%) var(--my, 0%), rgba(139,92,246,.16), transparent 65%); opacity: 0; transition: opacity .35s; pointer-events: none; }
.ai-card:hover { transform: translateY(-8px); border-color: var(--mc); box-shadow: 0 18px 44px rgba(0,0,0,.28); }
.ai-card:hover::before { opacity: 1; }
.ai-icon { width: 52px; height: 52px; border-radius: 15px; display: flex; align-items: center; justify-content: center; color: #fff; margin-bottom: 18px; box-shadow: 0 8px 22px rgba(0,0,0,.3); }
.ai-card h3 { font-size: 1.06rem; margin: 0 0 10px; }
.ai-card p { font-size: .86rem; line-height: 1.75; color: var(--txt2); margin: 0 0 16px; }
.ai-mods { display: flex; gap: 7px; flex-wrap: wrap; }

/* AI 批改演示 */
.ai-demo { margin-top: 28px; display: grid; grid-template-columns: 1fr auto 1fr; gap: 18px; align-items: stretch; border: 1px solid var(--line); border-radius: 20px; background: var(--card); backdrop-filter: blur(12px); padding: 26px 28px; }
.demo-label { font-size: .76rem; color: var(--txt3); letter-spacing: 1px; margin-bottom: 12px; }
.demo-q p { font-size: .9rem; color: var(--txt); margin: 0 0 12px; }
.demo-q em { display: block; font-style: normal; font-size: .82rem; color: var(--txt2); border-left: 3px solid var(--accent); padding: 6px 12px; background: rgba(139,92,246,.08); border-radius: 0 10px 10px 0; line-height: 1.7; }
.demo-arrow { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; color: var(--accent2); }
.demo-arrow i { width: 2px; flex: 1; background: linear-gradient(180deg, transparent, var(--accent), transparent); position: relative; overflow: hidden; }
.demo-arrow i::after { content: ''; position: absolute; left: -2px; top: 0; width: 6px; height: 22px; border-radius: 3px; background: #22d3ee; filter: blur(2px); animation: flow 2.2s linear infinite; }
@keyframes flow { from { top: -22px; } to { top: 100%; } }
.score-ring { position: relative; width: 88px; margin: 0 auto 12px; }
.score-ring svg { width: 88px; height: 88px; transform: rotate(-90deg); }
.score-ring .bgc { fill: none; stroke: rgba(255,255,255,.08); stroke-width: 7; }
.light .score-ring .bgc { stroke: rgba(15,23,42,.07); }
.score-ring .fgc { fill: none; stroke: #22d3ee; stroke-width: 7; stroke-linecap: round; stroke-dasharray: 213.6; stroke-dashoffset: 213.6; animation: ring 1.4s cubic-bezier(.2,.7,.2,1) .3s forwards; }
@keyframes ring { to { stroke-dashoffset: 17; } }
.score-ring div { position: absolute; inset: 0; display: flex; align-items: baseline; justify-content: center; gap: 2px; }
.score-ring b { font-size: 1.5rem; color: #22d3ee; margin-top: 26px; }
.score-ring span { font-size: .74rem; color: var(--txt3); }
.demo-a ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
.demo-a li { font-size: .82rem; padding: 7px 12px; border-radius: 9px; }
.demo-a li.ok { background: rgba(52,211,153,.09); color: #6ee7b7; }
.demo-a li.warn { background: rgba(251,191,36,.09); color: #fcd34d; }
.light .demo-a li.ok { color: #047857; }
.light .demo-a li.warn { color: #b45309; }

/* ── 三角色全景 ── */
.role-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 28px; }
.role-card { border: 1px solid var(--line); border-radius: 18px; background: var(--card); backdrop-filter: blur(12px); padding: 26px 24px; transition: all .35s ease; }
.role-card:hover { transform: translateY(-6px); border-color: var(--mc); box-shadow: 0 18px 40px rgba(0,0,0,.25); }
.role-head { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
.role-icon { width: 48px; height: 48px; border-radius: 14px; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
.role-head h3 { margin: 0; font-size: 1.04rem; }
.role-head span { font-size: .78rem; color: var(--txt3); }
.role-items { display: flex; flex-direction: column; gap: 10px; }
.role-item { display: flex; align-items: center; gap: 10px; font-size: .85rem; color: var(--txt2); }
.role-item i { width: 6px; height: 6px; border-radius: 2px; flex-shrink: 0; transform: rotate(45deg); }

.matrix { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; border: 1px solid var(--line); border-radius: 18px; background: var(--card); backdrop-filter: blur(12px); padding: 26px 28px; }
.mx-block h4 { display: flex; align-items: center; gap: 8px; margin: 0 0 14px; font-size: .95rem; }
.mx-chips { display: flex; gap: 9px; flex-wrap: wrap; }
.mx-chip { font-size: .8rem; color: #c4b5fd; border: 1px solid rgba(139,92,246,.35); background: rgba(139,92,246,.1); padding: 5px 14px; border-radius: 99px; transition: all .25s; }
.mx-chip:hover { background: rgba(139,92,246,.25); transform: translateY(-2px); }
.light .mx-chip { color: #5b21b6; }
.mx-chip.alt { color: #67e8f9; border-color: rgba(34,211,238,.35); background: rgba(34,211,238,.08); }
.mx-chip.alt:hover { background: rgba(34,211,238,.2); }
.light .mx-chip.alt { color: #0e7490; }

/* ── 成长闭环 ── */
.loop-steps { display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; }
.loop-step { position: relative; text-align: center; padding: 34px 20px 28px; border-radius: 18px; border: 1px solid var(--line); background: var(--card); backdrop-filter: blur(12px); transition: all .35s ease; }
.loop-step:hover { transform: translateY(-6px); border-color: rgba(139,92,246,.45); box-shadow: 0 18px 44px rgba(0,0,0,.3); }
.loop-num { position: absolute; top: 14px; left: 18px; font-size: 1.5rem; font-weight: 900; color: transparent; -webkit-text-stroke: 1px var(--txt3); opacity: .5; }
.loop-icon { width: 58px; height: 58px; border-radius: 17px; margin: 0 auto 16px; display: flex; align-items: center; justify-content: center; color: #fff; box-shadow: 0 10px 26px rgba(0,0,0,.35); }
.loop-step h3 { font-size: 1.02rem; margin: 0 0 8px; }
.loop-step p { font-size: .83rem; color: var(--txt2); line-height: 1.7; margin: 0 0 14px; }
.loop-mod { display: inline-block; font-size: .72rem; border: 1px solid; padding: 3px 12px; border-radius: 99px; }
.loop-arrow { position: absolute; right: -16px; top: 50%; transform: translateY(-50%); width: 30px; height: 30px; border-radius: 50%; background: linear-gradient(120deg, #7c3aed, #06b6d4); display: flex; align-items: center; justify-content: center; color: #fff; z-index: 2; box-shadow: 0 4px 14px rgba(124,58,237,.5); }

/* ── 用户心声 ── */
.voice-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; grid-auto-rows: auto; }
.voice-card { position: relative; border: 1px solid var(--line); border-radius: 18px; background: var(--card); backdrop-filter: blur(12px); padding: 26px 24px 22px; transition: all .3s ease; display: flex; flex-direction: column; }
.voice-card:hover { transform: translateY(-5px); border-color: rgba(34,211,238,.4); box-shadow: 0 16px 36px rgba(0,0,0,.25); }
.voice-card.wide { grid-column: span 2; }
.voice-quote { position: absolute; top: 10px; right: 20px; font-size: 3rem; line-height: 1; font-family: Georgia, serif; background: linear-gradient(120deg, rgba(139,92,246,.5), rgba(34,211,238,.5)); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.voice-card p { font-size: .9rem; line-height: 1.85; color: var(--txt2); margin: 0 0 18px; flex: 1; }
.voice-card.wide p { font-size: .96rem; }
.voice-who { display: flex; align-items: center; gap: 11px; border-top: 1px dashed var(--line); padding-top: 15px; }
.v-ava { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 700; font-size: .95rem; flex-shrink: 0; }
.voice-who b { display: block; font-size: .88rem; }
.voice-who em { font-style: normal; font-size: .72rem; color: var(--txt3); }
.v-tag { margin-left: auto; font-size: .72rem; border: 1px solid; padding: 3px 10px; border-radius: 99px; white-space: nowrap; }

/* ── FAQ ── */
.faq-wrap { max-width: 860px; }
.faq-list { display: flex; flex-direction: column; gap: 12px; }
.faq-item { border: 1px solid var(--line); border-radius: 14px; background: var(--card); backdrop-filter: blur(10px); cursor: pointer; transition: all .3s ease; overflow: hidden; }
.faq-item:hover { border-color: rgba(139,92,246,.45); }
.faq-item.open { border-color: var(--accent); background: rgba(139,92,246,.07); }
.faq-q { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 17px 22px; font-weight: 600; font-size: .95rem; }
.faq-arrow { color: var(--txt3); transition: transform .3s ease; flex-shrink: 0; }
.faq-item.open .faq-arrow { transform: rotate(90deg); color: var(--accent); }
.faq-a { max-height: 0; transition: max-height .4s cubic-bezier(.2,.7,.2,1); }
.faq-item.open .faq-a { max-height: 240px; }
.faq-a p { margin: 0; padding: 0 22px 18px; font-size: .88rem; line-height: 1.85; color: var(--txt2); }

/* ── CTA ── */
.cta-section { padding: 90px 0 110px; }
.cta-box { text-align: center; border: 1px solid var(--line); border-radius: 28px; padding: 68px 40px 56px; background: radial-gradient(700px 300px at 50% 0%, rgba(139,92,246,.22), transparent), var(--card); backdrop-filter: blur(16px); }
.cta-box h2 { font-size: clamp(1.8rem, 3.4vw, 2.6rem); font-weight: 800; margin: 0 0 14px; }
.cta-box p { color: var(--txt2); font-size: 1.05rem; margin: 0 0 36px; }
.cta-btns { display: flex; justify-content: center; gap: 16px; flex-wrap: wrap; margin-bottom: 26px; }
.cta-notes { display: flex; justify-content: center; gap: 26px; flex-wrap: wrap; }
.cta-notes span { display: inline-flex; align-items: center; gap: 6px; font-size: .82rem; color: var(--txt3); }
.cta-notes .el-icon { color: #34d399; }

/* ── Footer ── */
.footer { position: relative; z-index: 1; border-top: 1px solid var(--line); padding: 52px 0 26px; }
.foot-grid { display: grid; grid-template-columns: 1.8fr 1fr 1fr 1fr; gap: 32px; margin-bottom: 40px; }
.foot-brand p { color: var(--txt3); font-size: .86rem; margin: 14px 0 16px; max-width: 300px; line-height: 1.8; }
.foot-badges { display: flex; gap: 8px; flex-wrap: wrap; }
.foot-col { display: flex; flex-direction: column; gap: 11px; }
.foot-col h4 { margin: 0 0 4px; font-size: .92rem; }
.foot-col a { color: var(--txt3); text-decoration: none; font-size: .85rem; transition: color .2s; width: fit-content; }
.foot-col a:hover { color: var(--accent2); }
.foot-bottom { border-top: 1px solid var(--line); padding-top: 22px; text-align: center; color: var(--txt3); font-size: .8rem; }

/* ── 响应式 ── */
@media (max-width: 1024px) {
  .hero-grid { grid-template-columns: 1fr; text-align: center; }
  .hero-sub { margin-left: auto; margin-right: auto; }
  .hero-btns, .hero-stats { justify-content: center; }
  .hero-orbit { max-width: 380px; margin-top: 20px; }
  .showcase { grid-template-columns: 1fr; }
  .mod-rail { position: static; flex-direction: row; overflow-x: auto; padding-bottom: 6px; }
  .mod-tab { min-width: 220px; }
  .ai-grid { grid-template-columns: 1fr 1fr; }
  .ai-demo { grid-template-columns: 1fr; }
  .demo-arrow { flex-direction: row; padding: 6px 0; }
  .demo-arrow i { width: 100%; height: 2px; flex: none; }
  .role-grid { grid-template-columns: 1fr; }
  .matrix { grid-template-columns: 1fr; }
  .loop-steps { grid-template-columns: 1fr 1fr; }
  .loop-arrow { display: none; }
  .voice-grid { grid-template-columns: 1fr; }
  .voice-card.wide { grid-column: span 1; }
  .foot-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 640px) {
  .navbar-links { display: none; }
  .section { padding: 72px 0; }
  .mod-points { grid-template-columns: 1fr; }
  .ai-grid, .loop-steps { grid-template-columns: 1fr; }
  .hero-stats { gap: 16px; }
  .hstat-sep { display: none; }
  .mock-body { padding: 16px; }
  .pk-opts { grid-template-columns: 1fr; }
  .mod-figures { flex-direction: column; }
  .cta-box { padding: 48px 22px 40px; }
}
</style>
