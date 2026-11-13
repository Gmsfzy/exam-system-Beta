<template>
  <div class="wrong-notebook">
    <div class="page-header">
      <h1>错题本</h1>
      <p class="subtitle">自动收录考试/竞赛/练习答错的题目，重做直到掌握</p>
    </div>

    <!-- 筛选 -->
    <div class="filter-bar">
      <el-input
        v-model="searchKey"
        placeholder="搜索题干 / 知识点"
        clearable
        style="width:220px"
        :prefix-icon="Search"
        @keyup.enter="refresh"
        @clear="refresh"
      />
      <el-select v-model="filterMastered" placeholder="全部状态" clearable style="width:140px">
        <el-option label="待攻克" value="false" />
        <el-option label="已掌握" value="true" />
      </el-select>
      <el-select v-model="filterSource" placeholder="全部来源" clearable style="width:140px">
        <el-option label="考试" value="exam" />
        <el-option label="竞赛" value="competition" />
        <el-option label="练习" value="practice" />
        <el-option label="作业" value="homework" />
      </el-select>
      <el-button type="primary" @click="refresh">刷新</el-button>
      <el-button @click="startPractice">重做错题练习</el-button>
    </div>

    <!-- 汇总 -->
    <div class="stats">
      <span>共 <b>{{ total }}</b> 题</span>
      <span>待攻克 <b class="danger">{{ unmastered }}</b></span>
      <span>已掌握 <b class="success">{{ mastered }}</b></span>
    </div>

    <!-- 列表 -->
    <el-empty v-if="!loading && records.length === 0" description="还没有错题，继续加油！" />

    <div v-for="rec in records" :key="rec.id" class="wrong-card">
      <div class="wrong-header">
        <el-tag :type="sourceTagType(rec.source_type)" size="small">
          {{ sourceLabel(rec.source_type) }}
        </el-tag>
        <router-link v-if="rec.source_type === 'homework' && rec.source_id"
                     :to="`/homeworks/${rec.source_id}/take`" class="source-link">
          《{{ rec.source_title || '查看原作业' }}》
        </router-link>
        <el-tag v-if="rec.question_type" size="small">{{ typeLabel(rec.question_type) }}</el-tag>
        <el-tag v-if="rec.is_mastered" type="success" size="small">已掌握</el-tag>
        <el-tag v-else type="danger" size="small">待攻克</el-tag>
        <span class="wrong-count">错 {{ rec.wrong_count }} 次</span>
      </div>

      <div class="question-content"><RichContent :content="rec.question_content || ''" /></div>

      <!-- 选项（客观题） -->
      <div v-if="rec.options && rec.question_type !== 'fill_blank' && rec.question_type !== 'essay'" class="options">
        <div v-for="(opt, i) in rec.options" :key="i"
             :class="['option-item', { correct: rec.correct_answer && isCorrectOption(rec, i), wrong: rec.wrong_answer && isWrongOption(rec, i) }]">
          <span class="option-label">{{ optionLabel(i) }}</span>
          <span class="option-text">{{ opt }}</span>
        </div>
      </div>

      <!-- 主观题/填空 -->
      <div v-else class="text-answers">
        <div class="answer-row wrong">
          <span class="answer-label">你的作答：</span>
          <span class="answer-text">{{ rec.wrong_answer || '（空）' }}</span>
        </div>
        <div class="answer-row correct">
          <span class="answer-label">正确答案：</span>
          <span v-if="rec.answer_hidden" class="answer-text answer-hidden-tip">暂不可见（该来源仍可重答，截止/批改完成后开放）</span>
          <span v-else class="answer-text">{{ rec.correct_answer }}</span>
        </div>
      </div>

      <div v-if="rec.knowledge" class="knowledge-row">
        <el-tag v-for="k in rec.knowledge.split(',').filter(Boolean)" :key="k" size="small" type="info">{{ k.trim() }}</el-tag>
      </div>

      <!-- 逐题 AI 归因结果 -->
      <div v-if="rec.ai_analysis" class="ai-analysis-box">
        <div class="ai-analysis-head">
          <el-icon :size="14"><MagicStick /></el-icon>
          <span>AI 错因归因</span>
          <span v-if="rec.ai_analyzed_at" class="ai-analysis-time">{{ rec.ai_analyzed_at }}</span>
        </div>
        <div class="ai-analysis-text">{{ rec.ai_analysis }}</div>
      </div>

      <div class="wrong-footer">
        <span class="time-info">上次答错：{{ rec.last_wrong_at }}</span>
        <div class="actions">
          <el-button size="small" @click="toggleMastered(rec)">
            {{ rec.is_mastered ? '取消掌握' : '标记已掌握' }}
          </el-button>
          <el-button size="small" :loading="analyzingId === rec.id" :disabled="!!rec.answer_hidden"
                       :title="rec.answer_hidden ? '该来源仍可重答，归因暂不开放' : ''"
                       @click="analyzeWrong(rec)">
            {{ rec.ai_analysis ? '重新归因' : 'AI 归因' }}
          </el-button>
          <el-button size="small" type="primary" @click="openAsk(rec)">AI 答疑</el-button>
          <el-button
            size="small"
            type="success"
            plain
            :loading="askingCommunityId === rec.id"
            @click="askCommunity(rec)"
          >社区求助</el-button>
          <el-button size="small" type="danger" @click="removeRecord(rec)">移除</el-button>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > perPage" class="pagination">
      <el-pagination
        v-model:current-page="page"
        :page-size="perPage"
        :total="total"
        layout="prev, pager, next"
        @current-change="load"
      />
    </div>

    <!-- AI 答疑弹窗 -->
    <el-dialog v-model="aiDialogVisible" :title="aiCurrent ? 'AI 答疑 - ' + (aiCurrent.question_content || '').slice(0, 30) : 'AI 答疑'" width="600px" top="8vh">
      <div v-if="aiCurrent" class="ai-question">
        <div class="ai-q-label">你的错误作答：</div>
        <div class="ai-q-text">{{ aiCurrent.wrong_answer || '（空）' }}</div>
        <div class="ai-q-label" style="margin-top:8px">正确答案：</div>
        <div class="ai-q-text">{{ aiCurrent.correct_answer }}</div>
      </div>

      <!-- v7.20：不再一打开就自动请求——先给人把疑问写清楚的机会，留空也照样能问。
           以前是「弹窗一开就烧一次额度，而你想说的话没地方说」。 -->
      <div class="ai-doubt">
        <el-input v-model="userDoubt" type="textarea" :rows="2" maxlength="500" show-word-limit
                  placeholder="卡在哪一步？写下来 AI 会针对这点回答（可留空）" />
        <el-button size="small" type="primary" :loading="aiLoading" @click="askAI(false)">获取解析</el-button>
      </div>

      <div v-if="aiLoading" class="ai-loading">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <span>AI 正在分析...</span>
      </div>
      <div v-else class="ai-result">
        <div v-if="aiCached" class="ai-cached">{{ aiCached }}</div>
        <div v-if="aiResult" class="ai-answer">{{ aiResult }}</div>
        <div v-else class="ai-empty">还没有解析，写下你的疑问再点「获取解析」</div>
      </div>

      <template #footer>
        <el-button v-if="aiResult" size="small" :loading="aiLoading" @click="askAI(true)">重新生成</el-button>
        <el-button @click="aiDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- AI 学习助手 -->
    <AIChatDialog :context="aiContext" :suggestions="aiSuggestions" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import request from '../utils/request'
import { errTip } from '../utils/errs'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Search, MagicStick } from '@element-plus/icons-vue'
import AIChatDialog from '../components/AIChatDialog.vue'
import RichContent from '../components/RichContent.vue'

const router = useRouter()

const records = ref([])
const total = ref(0)
const page = ref(1)
const perPage = 20
const loading = ref(false)
const searchKey = ref('')
const filterMastered = ref('')
const filterSource = ref('')

const unmastered = computed(() => records.value.filter(r => !r.is_mastered).length)
const mastered = computed(() => records.value.filter(r => r.is_mastered).length)

// ── AI 助手上下文：附上当前页错题的薄弱知识点分布 ──
const aiContext = computed(() => {
  const kn = {}
  records.value.forEach(r => {
    if (!r.is_mastered && r.knowledge) {
      String(r.knowledge).split(/[,，]/).forEach(k => {
        const key = k.trim()
        if (key) kn[key] = (kn[key] || 0) + 1
      })
    }
  })
  const topK = Object.entries(kn).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, c]) => `${k}(${c}题)`).join('、')
  return `学生在「错题本」页查看错题，共 ${total.value} 道错题，当前页未掌握 ${unmastered.value} 道、已掌握 ${mastered.value} 道` +
    (topK ? `，未掌握题目涉及的高频知识点：${topK}` : '') +
    '。希望 AI 帮忙分析错因、总结薄弱点并给出补救建议。'
})
const aiSuggestions = [
  '帮我分析这些错题的常见错因',
  '我的薄弱知识点怎么针对性补强？',
  '错题本应该怎么高效复盘？',
]

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, per_page: perPage }
    if (searchKey.value.trim()) params.q = searchKey.value.trim()
    if (filterMastered.value !== '') params.is_mastered = filterMastered.value
    if (filterSource.value) params.source_type = filterSource.value
    const res = await request.get('/api/learning/wrong-records', { params })
    records.value = res.data.items
    total.value = res.data.total
  } catch (e) { /* 无数据时静默 */ }
  loading.value = false
}

function refresh() { page.value = 1; load() }

function sourceLabel(t) { return { exam: '考试', competition: '竞赛', practice: '练习', homework: '作业' }[t] || t }
function sourceTagType(t) { return { exam: '', competition: 'warning', practice: 'success', homework: 'info' }[t] || '' }
// v4.6.1 枚举收敛：题型中文名单一来源 frontend/src/utils/enums.js
import { typeLabel } from '../utils/enums'
function optionLabel(i) { return String.fromCharCode(65 + i) }
function isCorrectOption(rec, i) {
  const a = (rec.correct_answer || '').toUpperCase().trim()
  return a.includes(optionLabel(i))
}
function isWrongOption(rec, i) {
  const a = (rec.wrong_answer || '').toUpperCase().trim()
  return a.includes(optionLabel(i))
}

const askingCommunityId = ref(0)

async function askCommunity(rec) {
  askingCommunityId.value = rec.id
  try {
    const res = await request.post('/api/community/ask-from-wrong-record', {
      wrong_record_id: rec.id,
    })
    const post = res.data || {}
    ElMessage.success('已发布社区求助帖')
    if (post.id) router.push(`/community/${post.id}`)
  } catch (e) {
    // request 拦截器已提示
  } finally {
    askingCommunityId.value = 0
  }
}

async function toggleMastered(rec) {
  try {
    await request.post(`/api/learning/wrong-records/${rec.id}/master`, { mastered: !rec.is_mastered })
    rec.is_mastered = !rec.is_mastered
    rec.mastered_at = new Date().toISOString()
  } catch (e) { /* ignore */ }
}

async function removeRecord(rec) {
  await ElMessageBox.confirm('确定从错题本移除？', '确认')
  try {
    await request.delete(`/api/learning/wrong-records/${rec.id}`)
    ElMessage.success('已移除')
    load()
  } catch (e) { /* ignore */ }
}

function startPractice() {
  const unmasteredList = records.value.filter(r => !r.is_mastered)
  if (unmasteredList.length === 0) {
    ElMessage.info('没有待攻克的错题，先去自由刷题吧')
    return
  }
  router.push('/learning/practice')
}

// AI 逐题归因（结果持久化到错题记录，重做前可反复回看）
const analyzingId = ref(0)

async function analyzeWrong(rec) {
  analyzingId.value = rec.id
  try {
    const res = await request.post(`/api/learning/wrong-records/${rec.id}/analyze`)
    rec.ai_analysis = res.data.analysis
    rec.ai_analyzed_at = res.data.ai_analyzed_at
    if (res.data.source === 'rule') {
      ElMessage.info('AI 服务暂不可用，已生成规则化建议')
    } else {
      ElMessage.success('错因归因已生成')
    }
  } catch (e) { /* 拦截器已提示 */ }
  analyzingId.value = 0
}

// AI 答疑
const aiDialogVisible = ref(false)
const aiLoading = ref(false)
const aiResult = ref('')
const aiCurrent = ref(null)
const userDoubt = ref('')
const aiCached = ref('')

function openAsk(rec) {
  aiCurrent.value = rec
  aiResult.value = ''
  aiCached.value = ''
  userDoubt.value = ''
  aiDialogVisible.value = true
}

async function askAI(refresh) {
  const rec = aiCurrent.value
  if (!rec || aiLoading.value) return
  aiLoading.value = true
  aiResult.value = ''
  aiCached.value = ''
  try {
    const res = await request.post('/api/learning/ask', {
      question_id: rec.question_id,
      student_answer: rec.wrong_answer || '',
      // v7.20：doubt 现在真的会进 prompt。此前后端收下这个字段就丢掉，而前端又把题面塞进
      // doubt 想「让 AI 看到完整题目」——两头各白做一半，写不写疑问结果都一样。
      doubt: userDoubt.value.trim(),
      refresh: !!refresh,
    })
    // 不再拿 question_content 兜底：那正是旧版「没解析就把题面当解析显示」的源头，
    // 看着像 AI 答了，其实一个字都没答
    aiResult.value = res.data.analysis || 'AI 这次没给出可用解析，可点下方「重新生成」再试一次'
    if (res.data.cached) aiCached.value = res.data.message || '已回用七天内同样的提问'
  } catch (e) {
    // 不写死「AI 服务暂不可用」：额度用完是 429、后端没重启是 404，文案得对得上
    aiResult.value = errTip(e)
  }
  aiLoading.value = false
}

onMounted(load)
</script>

<style scoped>
.wrong-notebook { padding: 20px; max-width: 960px; }
.page-header { margin-bottom: 20px; }
.page-header h1 { font-size: 22px; margin: 0 0 4px; color: var(--text-primary); }
.subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }

.filter-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }

.stats { font-size: 13px; color: var(--text-muted); margin-bottom: 14px; }
.stats span { margin-right: 20px; }
.stats b { color: var(--text-primary); }
.stats b.danger { color: #ef4444; }
.stats b.success { color: #10b981; }

.wrong-card {
  background: var(--bg-card); border: 1px solid var(--border-color);
  border-radius: 12px; padding: 18px 20px; margin-bottom: 14px;
}
.wrong-header { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
.wrong-count { font-size: 12px; color: var(--text-muted); margin-left: auto; }

.source-link {
  font-size: 13px; color: var(--primary-color, #409eff); text-decoration: none;
  max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.source-link:hover { text-decoration: underline; }

.question-content { font-size: 15px; line-height: 1.7; color: var(--text-primary); margin-bottom: 14px; white-space: pre-wrap; }

.options { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
.option-item {
  display: flex; align-items: flex-start; gap: 10px; padding: 10px 14px;
  background: var(--bg-tertiary); border-radius: 8px; font-size: 14px;
}
.option-item.correct { background: rgba(16,185,129,0.1); border-left: 3px solid #10b981; }
.option-item.wrong { background: rgba(239,68,68,0.1); border-left: 3px solid #ef4444; }
.option-label { font-weight: 600; color: var(--text-muted); min-width: 18px; }

.text-answers { display: flex; flex-direction: column; gap: 8px; margin-bottom: 14px; }
.answer-row { font-size: 14px; padding: 8px 12px; border-radius: 8px; }
.answer-row.wrong { background: rgba(239,68,68,0.08); }
.answer-row.correct { background: rgba(16,185,129,0.08); }
.answer-label { color: var(--text-muted); margin-right: 6px; }
.answer-text { color: var(--text-primary); }
.answer-hidden-tip { color: var(--text-secondary); font-style: italic; }

.knowledge-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }

.ai-analysis-box {
  background: rgba(6, 182, 212, 0.06); border: 1px solid rgba(6, 182, 212, 0.25);
  border-radius: 10px; padding: 10px 14px; margin-bottom: 12px;
}
.ai-analysis-head {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; font-weight: 600; color: #0891b2; margin-bottom: 6px;
}
.ai-analysis-time { margin-left: auto; font-weight: 400; color: var(--text-muted); }
.ai-analysis-text { font-size: 13px; line-height: 1.7; color: var(--text-primary); white-space: pre-wrap; }

.wrong-footer { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.time-info { font-size: 12px; color: var(--text-muted); }
.actions { display: flex; gap: 8px; }

.pagination { display: flex; justify-content: center; margin-top: 20px; }

/* AI 答疑 */
.ai-question {
  background: var(--bg-tertiary); border-radius: 10px;
  padding: 14px 16px; margin-bottom: 14px; font-size: 13px;
}
.ai-q-label { color: var(--text-muted); font-size: 12px; margin-bottom: 4px; }
.ai-q-text { color: var(--text-primary); white-space: pre-wrap; line-height: 1.5; }
.ai-loading { display: flex; gap: 10px; align-items: center; justify-content: center; padding: 30px; color: var(--text-muted); font-size: 13px; }
.ai-result { font-size: 14px; line-height: 1.7; color: var(--text-primary); white-space: pre-wrap; }
.ai-empty { color: var(--text-muted); text-align: center; padding: 20px; }
.ai-doubt { display: flex; gap: 10px; align-items: flex-start; margin-bottom: 12px; }
.ai-doubt :deep(.el-textarea) { flex: 1; }
.ai-cached {
  background: var(--bg-tertiary); border-radius: 8px; padding: 8px 12px;
  margin-bottom: 10px; font-size: 12px; color: var(--text-muted);
}
</style>
