<template>
  <div class="wrong-notebook">
    <div class="page-header">
      <h1>错题本</h1>
      <p class="subtitle">自动收录考试/竞赛/练习答错的题目，重做直到掌握</p>
    </div>

    <!-- 筛选 -->
    <div class="filter-bar">
      <el-select v-model="filterMastered" placeholder="全部状态" clearable style="width:140px">
        <el-option label="待攻克" value="false" />
        <el-option label="已掌握" value="true" />
      </el-select>
      <el-select v-model="filterSource" placeholder="全部来源" clearable style="width:140px">
        <el-option label="考试" value="exam" />
        <el-option label="竞赛" value="competition" />
        <el-option label="练习" value="practice" />
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
        <el-tag v-if="rec.question_type" size="small">{{ typeLabel(rec.question_type) }}</el-tag>
        <el-tag v-if="rec.is_mastered" type="success" size="small">已掌握</el-tag>
        <el-tag v-else type="danger" size="small">待攻克</el-tag>
        <span class="wrong-count">错 {{ rec.wrong_count }} 次</span>
      </div>

      <div class="question-content" v-html="renderContent(rec.question_content)"></div>

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
          <span class="answer-text">{{ rec.correct_answer }}</span>
        </div>
      </div>

      <div v-if="rec.knowledge" class="knowledge-row">
        <el-tag v-for="k in rec.knowledge.split(',').filter(Boolean)" :key="k" size="small" type="info">{{ k.trim() }}</el-tag>
      </div>

      <div class="wrong-footer">
        <span class="time-info">上次答错：{{ rec.last_wrong_at }}</span>
        <div class="actions">
          <el-button size="small" @click="toggleMastered(rec)">
            {{ rec.is_mastered ? '取消掌握' : '标记已掌握' }}
          </el-button>
          <el-button size="small" type="primary" @click="askAI(rec)">AI 答疑</el-button>
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

      <div v-if="aiLoading" class="ai-loading">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <span>AI 正在分析...</span>
      </div>
      <div v-else class="ai-result">
        <div v-if="aiResult" class="ai-answer">{{ aiResult }}</div>
        <div v-else class="ai-empty">暂无解析</div>
      </div>

      <template #footer>
        <el-button @click="aiDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import request from '../utils/request'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'

const router = useRouter()

const records = ref([])
const total = ref(0)
const page = ref(1)
const perPage = 20
const loading = ref(false)
const filterMastered = ref('')
const filterSource = ref('')

const unmastered = computed(() => records.value.filter(r => !r.is_mastered).length)
const mastered = computed(() => records.value.filter(r => r.is_mastered).length)

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, per_page: perPage }
    if (filterMastered.value !== '') params.is_mastered = filterMastered.value
    if (filterSource.value) params.source_type = filterSource.value
    const res = await request.get('/api/learning/wrong-records', { params })
    records.value = res.data.items
    total.value = res.data.total
  } catch (e) { /* 无数据时静默 */ }
  loading.value = false
}

function refresh() { page.value = 1; load() }

function sourceLabel(t) { return { exam: '考试', competition: '竞赛', practice: '练习' }[t] || t }
function sourceTagType(t) { return { exam: '', competition: 'warning', practice: 'success' }[t] || '' }
function typeLabel(t) {
  return { single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题', fill_blank: '填空题', essay: '简答题' }[t] || t
}
function optionLabel(i) { return String.fromCharCode(65 + i) }
function isCorrectOption(rec, i) {
  const a = (rec.correct_answer || '').toUpperCase().trim()
  return a.includes(optionLabel(i))
}
function isWrongOption(rec, i) {
  const a = (rec.wrong_answer || '').toUpperCase().trim()
  return a.includes(optionLabel(i))
}
function renderContent(text) { return text || '' }

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

// AI 答疑
const aiDialogVisible = ref(false)
const aiLoading = ref(false)
const aiResult = ref('')
const aiCurrent = ref(null)
const userDoubt = ref('')

async function askAI(rec) {
  aiCurrent.value = rec
  aiResult.value = ''
  userDoubt.value = ''
  aiDialogVisible.value = true
  aiLoading.value = true
  try {
    const res = await request.post('/api/learning/ask', {
      question_id: rec.question_id,
      student_answer: rec.wrong_answer || '',
      doubt: rec.question_content,  // 让 AI 看完整题目
    })
    aiResult.value = res.data.analysis || res.data.question_content
  } catch (e) {
    aiResult.value = 'AI 服务暂不可用，请稍后重试'
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

.knowledge-row { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }

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
</style>
