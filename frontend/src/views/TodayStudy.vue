<template>
  <div class="today-study">
    <div class="page-header">
      <div>
        <h1 class="page-title">今日学习</h1>
        <p class="page-subtitle">{{ data.date }} · 每天一小步，闭环一大步</p>
      </div>
      <div class="streak-badge" :class="{ hot: data.streak_days >= 7 }">
        <span class="flame">🔥</span>
        <span>连续打卡 <b>{{ data.streak_days }}</b> 天</span>
      </div>
    </div>

    <!-- 打卡日历条 -->
    <div class="panel week-strip">
      <div v-for="d in weekCells" :key="d.date" class="day-cell" :class="{ checked: d.checked, today: d.isToday }">
        <span class="day-week">{{ d.weekLabel }}</span>
        <span class="day-mark">{{ d.checked ? '✓' : '·' }}</span>
        <span class="day-min">{{ d.checked ? (d.info.minutes || 0) + '分' : '' }}</span>
      </div>
    </div>

    <div class="grid-2">
      <!-- 每日任务（自建 + AI 建议） -->
      <div class="panel">
        <div class="panel-head">
          <h3>每日任务</h3>
          <el-button size="small" type="primary" plain :loading="suggestLoading" @click="openSuggest">
            <el-icon><MagicStick /></el-icon>&nbsp;AI 学习建议
          </el-button>
        </div>

        <div class="task-add-row">
          <el-input v-model="newTaskTitle" size="small" placeholder="添加一条今日任务，回车确认" maxlength="200"
                    clearable @keyup.enter="addTask" :loading="addingTask">
            <template #append>
              <el-button size="small" :disabled="!newTaskTitle.trim()" @click="addTask">添加</el-button>
            </template>
          </el-input>
        </div>

        <div v-if="data.daily_tasks.length" class="task-list">
          <div v-for="t in data.daily_tasks" :key="t.id" class="task-item" :class="{ done: t.status === 'done' }">
            <el-checkbox :model-value="t.status === 'done'" @change="toggleTask(t)" />
            <span class="task-title">{{ t.title }}</span>
            <el-tag v-if="t.source === 'ai'" size="small" type="warning" effect="plain">AI</el-tag>
            <el-icon class="task-del" @click="removeTask(t)"><Delete /></el-icon>
          </div>
        </div>
        <el-empty v-else :image-size="52" description="还没有任务，自己建一条或让 AI 帮你出建议" />
      </div>

      <!-- 计划待办 -->
      <div class="panel">
        <div class="panel-head">
          <h3>计划待办</h3>
          <el-button size="small" text type="primary" @click="$router.push('/learning/plan')">全部计划 →</el-button>
        </div>
        <div v-if="data.todo_tasks.length" class="task-list">
          <div v-for="t in data.todo_tasks" :key="t.task_id" class="task-item plan-item">
            <el-tag size="small" :type="taskTypeColor(t.task_type)" effect="plain">{{ taskTypeLabel(t.task_type) }}</el-tag>
            <div class="plan-task-main">
              <span class="task-title">{{ t.title }}</span>
              <span class="task-sub">{{ t.plan_title }}{{ t.estimated_minutes ? ` · 约 ${t.estimated_minutes} 分钟` : '' }}</span>
              <el-progress v-if="t.task_type === 'practice' && t.question_count"
                           :percentage="Math.min(100, Math.round(t.progress_count / t.question_count * 100))"
                           :stroke-width="5" :show-text="false" style="margin-top: 4px" />
            </div>
            <el-button size="small" @click="goTask(t)">去完成</el-button>
          </div>
        </div>
        <el-empty v-else :image-size="52" description="暂无未完成的计划任务" />
      </div>
    </div>

    <!-- 继续学习路径 CTA -->
    <div v-if="data.next_node" class="panel next-node-cta" @click="$router.push(`/learning/node/${data.next_node.node_id}`)">
      <div class="cta-icon"><el-icon :size="22" color="white"><Reading /></el-icon></div>
      <div class="cta-main">
        <span class="cta-title">继续学习：{{ data.next_node.title }}</span>
        <span class="cta-sub">路径「{{ data.next_node.path_title }}」· 第 {{ data.next_node.order_num }} 站</span>
      </div>
      <el-button type="primary">进入学习 →</el-button>
    </div>

    <!-- 间隔复习 -->
    <div class="panel">
      <div class="panel-head">
        <h3>到期复习 <el-tag v-if="data.due_review_count" type="danger" size="small" round>{{ data.due_review_count }} 道</el-tag></h3>
        <el-button v-if="!review.active" size="small" type="warning" plain :disabled="!data.due_review_count" @click="startReview">
          开始复习
        </el-button>
      </div>

      <!-- 复习前：概览 -->
      <template v-if="!review.active">
        <div v-if="data.due_reviews.length" class="review-preview">
          <div v-for="r in data.due_reviews.slice(0, 4)" :key="r.review_id" class="review-prev-item">
            <el-tag size="small" :type="r.source_type === 'wrong' ? 'danger' : 'warning'" effect="plain">
              {{ r.source_type === 'wrong' ? '错题' : '遗忘' }}
            </el-tag>
            <span class="review-prev-text">{{ clip(r.question_content) }}</span>
          </div>
          <p v-if="data.due_review_count > 4" class="review-prev-more">…共 {{ data.due_review_count }} 道到期，点击「开始复习」逐张攻克</p>
        </div>
        <el-empty v-else :image-size="52" description="今日没有到期复习，去刷题积累吧" />
      </template>

      <!-- 复习中：卡片流 -->
      <div v-else-if="review.current" class="review-card">
        <div class="rc-head">
          <span class="rc-progress">第 {{ review.doneCount + 1 }} / {{ review.doneCount + review.queue.length }} 张</span>
          <el-tag size="small">{{ typeLabel(review.current.question?.type) }}</el-tag>
          <el-tag size="small" :type="review.current.source_type === 'wrong' ? 'danger' : 'warning'" effect="plain">
            {{ review.current.source_type === 'wrong' ? '错题重看' : '防遗忘' }}
          </el-tag>
        </div>
        <div class="rc-content">{{ review.current.question?.content }}</div>

        <!-- 答案未揭晓 -->
        <template v-if="!review.result">
          <div v-if="isChoiceType(review.current.question?.type)" class="rc-options">
            <div v-for="(opt, i) in (review.current.question?.options || [])" :key="i"
                 :class="['rc-option', { selected: isOptionSelected(i) }]" @click="selectOption(i)">
              <span class="opt-label">{{ optionLabel(i) }}</span>
              <span class="opt-text">{{ opt }}</span>
            </div>
          </div>
          <div v-else-if="review.current.question?.type === 'true_false'" class="rc-options">
            <div v-for="lab in ['A', 'B']" :key="lab" :class="['rc-option', { selected: review.answer === lab }]" @click="review.answer = lab">
              <span class="opt-label">{{ lab }}</span><span class="opt-text">{{ lab === 'A' ? '正确' : '错误' }}</span>
            </div>
          </div>
          <div v-else class="rc-text">
            <el-input v-model="review.answer" type="textarea" :rows="3" placeholder="写下你的答案（主观题将进入自评）" />
          </div>
          <div class="rc-actions">
            <el-button v-if="review.current.question?.type === 'essay'" @click="review.result = 'self'">回忆好了，开始自评</el-button>
            <el-button v-else type="primary" :disabled="!review.answer.trim()" :loading="review.submitting" @click="submitReview()">提交答案</el-button>
            <el-button text @click="quitReview">结束复习</el-button>
          </div>
        </template>

        <!-- 自评模式（主观题） -->
        <template v-else-if="review.result === 'self'">
          <div class="rc-answer">请对照自己刚才的答案与记忆，诚实自评；提交后会揭晓参考答案与解析。</div>
          <div class="rc-actions">
            <el-button type="success" :loading="review.submitting" @click="submitReview(true)">记住了，答对了</el-button>
            <el-button type="danger" plain :loading="review.submitting" @click="submitReview(false)">没答对</el-button>
          </div>
        </template>

        <!-- 判分结果 -->
        <template v-else>
          <div class="rc-result" :class="review.result.is_correct ? 'ok' : 'no'">
            <span class="rc-result-icon">{{ review.result.is_correct ? '✓' : '✗' }}</span>
            <div>
              <div v-if="!review.result.is_correct"><b>正确答案：</b>{{ review.result.correct_answer }}</div>
              <div v-if="review.result.analysis" class="rc-analysis"><b>解析：</b>{{ review.result.analysis }}</div>
              <div class="rc-next-plan">
                {{ review.result.status === 'retired' ? '🎉 该题已退休，无需再复习'
                   : `下次复习：${review.result.next_interval_days} 天后` }}
              </div>
            </div>
          </div>
          <div class="rc-actions">
            <el-button type="primary" :disabled="!review.queue.length" @click="nextCard">
              {{ review.queue.length ? '下一张 →' : '已完成今日复习 🎉' }}
            </el-button>
            <el-button text @click="quitReview">结束复习</el-button>
          </div>
        </template>
      </div>
    </div>

    <!-- AI 学习建议弹窗 -->
    <el-dialog v-model="suggestVisible" title="AI 学习建议" width="520px">
      <p v-if="suggest.source === 'ai'" class="suggest-tip">以下建议由 AI 根据你当前学习状态生成，勾选后加入今日任务：</p>
      <p v-else class="suggest-tip">AI 服务暂不可用，以下为根据学习状态自动整理的建议：</p>
      <el-checkbox-group v-model="suggest.picked">
        <div v-for="(s, i) in suggest.list" :key="i" class="suggest-item">
          <el-checkbox :value="s">{{ s }}</el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="suggestVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!suggest.picked.length" :loading="adoptLoading" @click="adoptSuggestions">
          采纳 {{ suggest.picked.length }} 条
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const router = useRouter()

const data = ref({
  date: '', streak_days: 0, checked_in_today: false, today_minutes: 0,
  week_days: {}, todo_tasks: [], daily_tasks: [], due_reviews: [],
  due_review_count: 0, next_node: null, active_plans: 0,
})

// ── 打卡日历条：以接口 date 为终点排 7 格 ─────────────────────
const WEEK_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const weekCells = computed(() => {
  const end = data.value.date ? new Date(data.value.date + 'T00:00:00') : new Date()
  const cells = []
  for (let i = 6; i >= 0; i--) {
    const d = new Date(end); d.setDate(end.getDate() - i)
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    const info = data.value.week_days[iso] || {}
    cells.push({ date: iso, weekLabel: WEEK_CN[d.getDay()], checked: !!data.value.week_days[iso], info, isToday: i === 0 })
  }
  return cells
})

async function load() {
  try {
    const res = await request.get('/api/learning/today')
    data.value = res.data
  } catch (e) { /* 拦截器已提示 */ }
}
onMounted(load)

// ── 每日任务：自建 + AI 建议采纳 ─────────────────────────────
const newTaskTitle = ref('')
const addingTask = ref(false)

async function addTask() {
  const title = newTaskTitle.value.trim()
  if (!title) return
  addingTask.value = true
  try {
    await request.post('/api/learning/daily-tasks', { title })
    newTaskTitle.value = ''
    await load()
  } catch (e) { /* ignore */ }
  addingTask.value = false
}

async function toggleTask(t) {
  try {
    await request.post(`/api/learning/daily-tasks/${t.id}/toggle`)
    await load()
  } catch (e) { /* ignore */ }
}

async function removeTask(t) {
  try {
    await request.delete(`/api/learning/daily-tasks/${t.id}`)
    await load()
  } catch (e) { /* ignore */ }
}

const suggestVisible = ref(false)
const suggestLoading = ref(false)
const adoptLoading = ref(false)
const suggest = reactive({ list: [], picked: [], source: 'ai', basis: '' })

async function openSuggest() {
  suggestLoading.value = true
  try {
    const res = await request.post('/api/learning/daily-tasks/ai-suggest')
    suggest.list = res.data.suggestions || []
    suggest.picked = [...suggest.list]
    suggest.source = res.data.source
    suggest.basis = res.data.basis || ''
    suggestVisible.value = true
  } catch (e) { /* ignore */ }
  suggestLoading.value = false
}

async function adoptSuggestions() {
  adoptLoading.value = true
  try {
    const res = await request.post('/api/learning/daily-tasks/batch', { items: suggest.picked })
    ElMessage.success(`已采纳 ${res.data.added} 条建议`)
    suggestVisible.value = false
    await load()
  } catch (e) { /* ignore */ }
  adoptLoading.value = false
}

// ── 计划待办跳转 ─────────────────────────────────────────────
function taskTypeLabel(t) {
  return { knowledge_point: '知识点', practice: '刷题', resource: '资源', custom: '自定义' }[t] || t
}
function taskTypeColor(t) {
  return { knowledge_point: 'primary', practice: 'success', resource: 'warning', custom: 'info' }[t] || 'info'
}
function goTask(t) {
  if (t.task_type === 'practice') router.push('/learning/practice')
  else router.push('/learning/plan')
}

// ── 间隔复习卡片流 ───────────────────────────────────────────
const review = reactive({
  active: false, queue: [], doneCount: 0, current: null,
  answer: '', submitting: false, result: null,
})

function clip(text, n = 46) {
  if (!text) return '（题目已删除）'
  return text.length > n ? text.slice(0, n) + '…' : text
}
function isChoiceType(t) { return ['single_choice', 'multiple_choice'].includes(t) }
function typeLabel(t) {
  return { single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题', fill_blank: '填空题', essay: '简答题' }[t] || t || ''
}
function optionLabel(i) { return String.fromCharCode(65 + i) }
function isOptionSelected(i) {
  return (review.answer || '').includes(optionLabel(i))
}
function selectOption(i) {
  const label = optionLabel(i)
  if (review.current.question?.type === 'single_choice') {
    review.answer = label
  } else {
    const set = new Set((review.answer || '').split('').filter(Boolean))
    set.has(label) ? set.delete(label) : set.add(label)
    review.answer = Array.from(set).sort().join('')
  }
}

async function startReview() {
  try {
    const res = await request.get('/api/learning/reviews/due')
    review.queue = res.data.items || []
    if (!review.queue.length) { ElMessage.info('到期复习已完成'); await load(); return }
    review.active = true
    review.doneCount = 0
    nextCard()
  } catch (e) { /* ignore */ }
}

function nextCard() {
  review.current = review.queue.shift() || null
  review.answer = ''
  review.result = null
  if (!review.current) {
    ElMessage.success('复习队列已完成！')
    quitReview()
  }
}

async function submitReview(selfCorrect) {
  if (!review.current) return
  review.submitting = true
  try {
    const payload = { review_id: review.current.review_id, student_answer: review.answer.trim() }
    if (selfCorrect !== undefined) payload.self_correct = selfCorrect
    const res = await request.post('/api/learning/reviews/answer', payload)
    review.doneCount += 1
    review.result = res.data
  } catch (e) { /* ignore */ }
  review.submitting = false
}

async function quitReview() {
  review.active = false
  review.current = null
  review.queue = []
  review.result = null
  await load()
}
</script>

<style scoped>
.today-study { padding: 20px; max-width: 1100px; }

.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }

.streak-badge {
  display: flex; align-items: center; gap: 6px;
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 999px; padding: 8px 16px; font-size: 14px; color: var(--text-primary);
}
.streak-badge.hot { border-color: rgba(245, 158, 11, 0.5); }
.streak-badge .flame { font-size: 17px; }
.streak-badge b { color: #f59e0b; }

.panel {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 14px; padding: 18px 20px; margin-bottom: 16px;
}
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.panel-head h3 { margin: 0; font-size: 16px; color: var(--text-primary); display: flex; align-items: center; gap: 8px; }

/* 打卡日历条 */
.week-strip { display: flex; gap: 8px; padding: 14px 16px; }
.day-cell {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 3px;
  padding: 8px 4px; border-radius: 10px; background: var(--bg-tertiary); min-width: 0;
}
.day-cell.checked { background: rgba(16, 185, 129, 0.12); }
.day-cell.today { outline: 2px solid var(--primary-color, #6366f1); outline-offset: -2px; }
.day-week { font-size: 11px; color: var(--text-muted); }
.day-mark { font-size: 16px; font-weight: 700; color: var(--text-primary); line-height: 1.1; }
.day-cell.checked .day-mark { color: #10b981; }
.day-min { font-size: 10px; color: var(--text-muted); height: 14px; }

.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

/* 任务列表 */
.task-add-row { margin-bottom: 10px; }
.task-list { display: flex; flex-direction: column; gap: 4px; }
.task-item {
  display: flex; align-items: center; gap: 10px; padding: 9px 10px;
  border-radius: 9px; transition: background 0.2s;
}
.task-item:hover { background: var(--bg-tertiary); }
.task-item.done .task-title { text-decoration: line-through; color: var(--text-muted); }
.task-title { flex: 1; font-size: 14px; color: var(--text-primary); word-break: break-all; }
.task-del { color: var(--text-muted); cursor: pointer; opacity: 0; transition: opacity 0.2s; }
.task-item:hover .task-del { opacity: 1; }
.task-del:hover { color: #ef4444; }
.plan-item { align-items: flex-start; }
.plan-task-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.task-sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

/* 继续学习 CTA */
.next-node-cta { display: flex; align-items: center; gap: 14px; cursor: pointer; transition: border-color 0.2s; }
.next-node-cta:hover { border-color: var(--primary-color, #6366f1); }
.cta-icon {
  width: 46px; height: 46px; border-radius: 12px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #06b6d4 0%, #0891b2 100%);
}
.cta-main { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.cta-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.cta-sub { font-size: 12px; color: var(--text-muted); }

/* 复习 */
.review-preview { display: flex; flex-direction: column; gap: 8px; }
.review-prev-item { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-primary); }
.review-prev-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); }
.review-prev-more { margin: 4px 0 0; font-size: 12px; color: var(--text-muted); }

.review-card { max-width: 640px; }
.rc-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.rc-progress { font-size: 13px; color: var(--text-muted); }
.rc-content { font-size: 15px; line-height: 1.7; color: var(--text-primary); margin-bottom: 16px; white-space: pre-wrap; }
.rc-options { display: flex; flex-direction: column; gap: 8px; }
.rc-option {
  display: flex; gap: 10px; padding: 10px 14px; border: 1px solid var(--border-color);
  border-radius: 9px; cursor: pointer; transition: all 0.2s; font-size: 14px;
}
.rc-option:hover { border-color: var(--primary-color, #6366f1); }
.rc-option.selected { background: var(--primary-bg, rgba(99, 102, 241, 0.08)); border-color: var(--primary-color, #6366f1); }
.opt-label { font-weight: 600; color: var(--text-muted); }
.rc-actions { display: flex; gap: 10px; margin-top: 16px; }
.rc-answer { font-size: 14px; line-height: 1.7; color: var(--text-primary); background: var(--bg-tertiary); border-radius: 9px; padding: 12px 14px; }
.rc-analysis { font-size: 13px; color: var(--text-muted); margin-top: 6px; }
.rc-result { display: flex; gap: 12px; padding: 12px 14px; border-radius: 9px; font-size: 14px; line-height: 1.6; }
.rc-result.ok { background: rgba(16, 185, 129, 0.1); color: #10b981; }
.rc-result.no { background: rgba(239, 68, 68, 0.08); color: var(--text-primary); }
.rc-result-icon { font-size: 20px; font-weight: 700; }
.rc-next-plan { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

/* AI 建议 */
.suggest-tip { font-size: 13px; color: var(--text-muted); margin: 0 0 10px; }
.suggest-item { padding: 6px 4px; border-radius: 8px; }
.suggest-item:hover { background: var(--bg-tertiary); }

@media (max-width: 900px) {
  .grid-2 { grid-template-columns: 1fr; }
}
</style>
