<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>考试管理</h2>
        <p>管理您创建的所有考试</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="showCreateModal = true">
          <el-icon><Plus /></el-icon>
          创建考试
        </el-button>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
          <el-icon :size="24" color="white"><Document /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ exams.length }}</div>
          <div class="stat-label">考试总数</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%)">
          <el-icon :size="24" color="white"><Clock /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ draftCount }}</div>
          <div class="stat-label">草稿状态</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%)">
          <el-icon :size="24" color="white"><VideoPlay /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ publishedCount }}</div>
          <div class="stat-label">进行中</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)">
          <el-icon :size="24" color="white"><Check /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ endedCount }}</div>
          <div class="stat-label">已结束</div>
        </div>
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="statusFilter" placeholder="筛选状态" clearable>
        <el-option value="draft" label="草稿" />
        <el-option value="published" label="进行中" />
        <el-option value="ended" label="已结束" />
      </el-select>
      <el-input v-model="searchText" placeholder="搜索考试名称" prefix-icon="Search" />
    </div>

    <div class="exam-grid">
      <div
        v-for="exam in filteredExams"
        :key="exam.id"
        class="exam-card"
        :class="exam.status"
      >
        <div class="card-header">
          <span :class="['badge-status', exam.status]">{{ statusLabels[exam.status] }}</span>
          <el-dropdown @command="(action) => handleDropdownAction(action, exam)">
            <el-button text>
              <el-icon><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
              <el-dropdown-item command="smart">智能组卷</el-dropdown-item>
              <el-dropdown-item command="questions">管理题目</el-dropdown-item>
              <el-dropdown-item command="students">邀请学生</el-dropdown-item>
              <el-dropdown-item divided command="edit">编辑</el-dropdown-item>
              <el-dropdown-item command="delete" divided>删除考试</el-dropdown-item>
            </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <h3 class="exam-title">{{ exam.title }}</h3>
        <p class="exam-desc">{{ exam.description }}</p>
        <div class="exam-meta">
          <div class="meta-item">
            <el-icon :size="14"><Calendar /></el-icon>
            <span>{{ formatDate(exam.start_time) }}</span>
          </div>
          <div class="meta-item">
            <el-icon :size="14"><Clock /></el-icon>
            <span>{{ exam.duration }}分钟</span>
          </div>
        </div>
        <div class="card-footer">
          <el-button
            v-if="exam.status === 'draft' || exam.status === 'ended'"
            type="primary"
            @click="publishExam(exam.id)"
          >
            <el-icon><Star /></el-icon>{{ exam.status === 'ended' ? '重新发布' : '发布考试' }}
          </el-button>
          <el-button
            v-if="exam.status === 'published'"
            type="danger"
            @click="endExam(exam.id)"
          >
            <el-icon><Bell /></el-icon>结束考试
          </el-button>
          <el-button
            v-if="exam.status === 'ended'"
            type="success"
            @click="viewResults(exam.id)"
          >
            <el-icon><User /></el-icon>查看成绩
          </el-button>
        </div>
      </div>
    </div>

    <div v-if="filteredExams.length === 0" class="empty-state">
      <div class="empty-icon">
        <el-icon :size="64" color="#cbd5e1"><Document /></el-icon>
      </div>
      <h3>暂无考试</h3>
      <p>点击右上角按钮创建您的第一场考试</p>
    </div>

    <el-dialog v-model="showCreateModal" title="创建考试" width="600px" @closed="resetForm">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="考试名称" required>
          <el-input v-model="createForm.title" placeholder="请输入考试名称" />
        </el-form-item>
        <el-form-item label="考试描述">
          <el-input v-model="createForm.description" type="textarea" placeholder="请输入考试描述" />
        </el-form-item>
        <el-form-item label="开始时间" required>
          <el-date-picker
            v-model="createForm.start_time"
            type="datetime"
            placeholder="选择开始时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="结束时间" required>
          <el-date-picker
            v-model="createForm.end_time"
            type="datetime"
            placeholder="选择结束时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="考试时长" required>
          <el-input-number v-model="createForm.duration" :min="5" :max="480" />
          <span style="margin-left: 8px">分钟</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateModal = false">取消</el-button>
        <el-button type="primary" @click="createExam">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showSmartModal" title="智能组卷" width="800px">
      <el-form :model="smartForm" label-width="100px">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="选择专业">
              <el-select v-model="smartForm.major_id" placeholder="全部专业" clearable style="width: 100%">
                <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="题目来源">
              <el-select v-model="smartForm.source_filter" placeholder="全部来源" style="width: 100%">
                <el-option label="全部来源" value="all" />
                <el-option label="手动输入" value="manual" />
                <el-option label="AI生成" value="ai" />
                <el-option label="历年真题" value="past_exam" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="题目总数">
          <el-input-number v-model="smartForm.total_questions" :min="1" :max="50" />
          <span style="margin-left: 8px">道</span>
          <span style="margin-left: 16px; color: #94a3b8; font-size: 13px">不设置题型数量时使用</span>
        </el-form-item>
        <el-divider content-position="left">按题型分配</el-divider>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="单选题">
              <el-input-number v-model="smartForm.type_single_choice" :min="0" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="多选题">
              <el-input-number v-model="smartForm.type_multiple_choice" :min="0" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="填空题">
              <el-input-number v-model="smartForm.type_fill_blank" :min="0" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="判断题">
              <el-input-number v-model="smartForm.type_true_false" :min="0" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="问答题">
              <el-input-number v-model="smartForm.type_short_answer" :min="0" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="编程题">
              <el-input-number v-model="smartForm.type_programming" :min="0" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="应用题">
              <el-input-number v-model="smartForm.type_application" :min="0" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="计算题">
              <el-input-number v-model="smartForm.type_calculation" :min="0" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="题型小计">
              <div style="padding-top: 2px; color: #6366f1; font-weight: 600">
                {{ (smartForm.type_single_choice || 0) + (smartForm.type_multiple_choice || 0) + (smartForm.type_fill_blank || 0) + (smartForm.type_true_false || 0) + (smartForm.type_short_answer || 0) + (smartForm.type_programming || 0) + (smartForm.type_application || 0) + (smartForm.type_calculation || 0) }} 道
              </div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-divider content-position="left">难度分布（百分比）</el-divider>
        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="简单">
              <el-input-number v-model="smartForm.diff_easy" :min="0" :max="100" style="width: 100%" />
              <span style="margin-left: 8px">%</span>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="中等">
              <el-input-number v-model="smartForm.diff_medium" :min="0" :max="100" style="width: 100%" />
              <span style="margin-left: 8px">%</span>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="困难">
              <el-input-number v-model="smartForm.diff_hard" :min="0" :max="100" style="width: 100%" />
              <span style="margin-left: 8px">%</span>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="showSmartModal = false">取消</el-button>
        <el-button type="primary" @click="doSmartComposition">智能组卷</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showQuestionsModal" title="管理题目" width="900px" :close-on-click-modal="false">
      <div class="questions-modal">
        <div class="questions-section">
          <div class="section-header">
            <h4>已添加题目</h4>
            <div class="header-info">
              <span class="count-badge">{{ examQuestions.length }} 道</span>
              <span class="score-badge">总分 {{ totalScore }} 分</span>
            </div>
          </div>
          
          <div v-if="examQuestions.length === 0" class="empty-tip">
            <div class="empty-icon-wrap">
              <el-icon :size="48" color="#94a3b8"><Document /></el-icon>
            </div>
            <p>暂无题目，点击下方"添加题目"按钮从题库中选择</p>
          </div>

          <div v-else class="question-list">
            <div v-for="(q, index) in examQuestions" :key="q.id" class="question-item">
              <div class="question-main">
                <span class="question-order">{{ index + 1 }}</span>
                <div class="question-content-wrap">
                  <p class="question-text">{{ q.content }}</p>
                  <div class="question-meta">
                    <span :class="['type-tag', q.type]">{{ typeLabels[q.type] || q.type }}</span>
                    <span :class="['diff-tag', q.difficulty]">{{ diffLabels[q.difficulty] || q.difficulty }}</span>
                    <span class="score-tag">{{ q.score }}分</span>
                  </div>
                </div>
              </div>
              <div class="question-actions">
                <el-button size="small" text @click="editQuestionScore(index)">编辑分数</el-button>
                <el-button size="small" text type="danger" @click="removeExamQuestion(q.id)">移除</el-button>
              </div>
            </div>
          </div>
        </div>

        <el-divider content-position="left">从题库添加题目</el-divider>

        <div class="add-section">
          <div class="add-header">
            <h4>题库题目</h4>
            <span class="available-count">可添加 {{ availableQuestions.length }} 道</span>
          </div>
          
          <div class="search-bar">
            <el-input
              v-model="questionSearchText"
              placeholder="搜索题目内容..."
              prefix-icon="Search"
              clearable
              @input="searchAvailableQuestions"
              style="width: 100%"
            />
          </div>

          <div class="question-table-wrap">
            <el-table
              :data="availableQuestions"
              :row-key="(row) => row.id"
              border
              :height="250"
              size="small"
              @selection-change="handleQuestionSelection"
            >
              <el-table-column type="selection" width="40" />
              <el-table-column prop="content" label="题目" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">
                  <span>{{ row.content.substring(0, 60) }}{{ row.content.length > 60 ? '...' : '' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="type" label="题型" width="100">
                <template #default="{ row }">
                  <span :class="['type-tag', row.type]">{{ typeLabels[row.type] || row.type }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="difficulty" label="难度" width="80">
                <template #default="{ row }">
                  <span :class="['diff-tag', row.difficulty]">{{ diffLabels[row.difficulty] || row.difficulty }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="score" label="默认分数" width="80" />
            </el-table>
          </div>

          <div class="add-footer">
            <span class="selected-info">已选择 {{ addQuestionsForm.question_ids.length }} 道题目</span>
            <el-button type="primary" @click="addExamQuestions" :disabled="addQuestionsForm.question_ids.length === 0">
              <el-icon><Plus /></el-icon>
              添加选中的题目
            </el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showQuestionsModal = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showStudentsModal" title="邀请学生" width="900px" :close-on-click-modal="false">
      <div class="students-modal">
        <div class="students-section">
          <div class="section-header">
            <h4>已邀请学生</h4>
            <div class="header-info">
              <span class="count-badge">{{ examStudents.length }} 人</span>
              <span class="submit-count">已提交 {{ submittedCount }} 人</span>
            </div>
          </div>
          
          <div v-if="examStudents.length === 0" class="empty-tip">
            <div class="empty-icon-wrap">
              <el-icon :size="48" color="#94a3b8"><User /></el-icon>
            </div>
            <p>暂无邀请的学生，点击下方"邀请学生"按钮添加</p>
          </div>

          <div v-else class="student-list">
            <div v-for="s in examStudents" :key="s.id" class="student-item">
              <div class="student-main">
                <div class="student-avatar">
                  {{ s.username.charAt(0).toUpperCase() }}
                </div>
                <div class="student-info">
                  <span class="student-name">{{ s.username }}</span>
                  <span class="student-email">{{ s.email }}</span>
                </div>
              </div>
              <div class="student-status">
                <span :class="['submit-status', s.has_submitted ? 'submitted' : 'pending']">
                  {{ s.has_submitted ? '已提交' : '未提交' }}
                </span>
                <span v-if="s.score !== null" class="score-display">{{ s.score }}分</span>
              </div>
              <el-button size="small" text type="danger" @click="removeStudent(s.id)">移除</el-button>
            </div>
          </div>
        </div>

        <el-divider content-position="left">邀请学生</el-divider>

        <div class="invite-section">
          <div class="add-header">
            <h4>可选学生</h4>
            <span class="available-count">可邀请 {{ allStudents.length }} 人</span>
          </div>
          
          <div class="search-bar">
            <el-input
              v-model="studentSearchText"
              placeholder="搜索用户名或邮箱..."
              prefix-icon="Search"
              clearable
              @input="searchStudents"
              style="width: 100%"
            />
          </div>

          <div class="student-table-wrap">
            <el-table
              :data="filteredStudents"
              :row-key="(row) => row.id"
              border
              :height="250"
              size="small"
              @selection-change="handleStudentSelection"
            >
              <el-table-column type="selection" width="40" />
              <el-table-column prop="username" label="用户名" min-width="120" />
              <el-table-column prop="email" label="邮箱" min-width="200" show-overflow-tooltip />
            </el-table>
          </div>

          <div class="add-footer">
            <span class="selected-info">已选择 {{ selectedStudents.length }} 名学生</span>
            <el-button type="primary" @click="inviteStudents" :disabled="selectedStudents.length === 0">
              <el-icon><Plus /></el-icon>
              邀请选中的学生
            </el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="showStudentsModal = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, MoreFilled, Calendar, Clock, Document, Star, Bell, User, Delete } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()

const exams = ref([])
const majors = ref([])
const statusFilter = ref('')
const searchText = ref('')
const showCreateModal = ref(false)
const showSmartModal = ref(false)
const showQuestionsModal = ref(false)
const showStudentsModal = ref(false)
const currentExamId = ref(null)
const examQuestions = ref([])
const examStudents = ref([])
const allStudents = ref([])
const selectedStudents = ref([])
const addQuestionsForm = ref({ question_ids: [] })
const availableQuestions = ref([])
const allAvailableQuestions = ref([])
const questionSearchText = ref('')
const editingScoreIndex = ref(-1)
const editingScore = ref(10)
const studentSearchText = ref('')

const createForm = ref({
  title: '',
  description: '',
  start_time: null,
  end_time: null,
  duration: 60
})

const smartForm = ref({
  major_id: '',
  source_filter: 'all',
  total_questions: 10,
  type_single_choice: '',
  type_multiple_choice: '',
  type_fill_blank: '',
  type_true_false: '',
  type_short_answer: '',
  type_programming: '',
  type_application: '',
  type_calculation: '',
  diff_easy: 30,
  diff_medium: 50,
  diff_hard: 20
})

const statusLabels = {
  draft: '草稿',
  published: '进行中',
  ended: '已结束'
}

const typeLabels = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  fill_blank: '填空题',
  true_false: '判断题',
  short_answer: '问答题',
  programming: '编程题',
  application: '应用题',
  calculation: '计算题'
}

const diffLabels = {
  easy: '简单',
  medium: '中等',
  hard: '困难'
}

const totalScore = computed(() => {
  return examQuestions.value.reduce((sum, q) => sum + (q.score || 0), 0)
})

const submittedCount = computed(() => examStudents.value.filter(s => s.has_submitted).length)

const filteredStudents = computed(() => {
  const keyword = studentSearchText.value
  if (!keyword) {
    return allStudents.value
  }
  return allStudents.value.filter(s =>
    s.username.includes(keyword) || s.email.includes(keyword)
  )
})

const draftCount = computed(() => exams.value.filter(e => e.status === 'draft').length)
const publishedCount = computed(() => exams.value.filter(e => e.status === 'published').length)
const endedCount = computed(() => exams.value.filter(e => e.status === 'ended').length)

const filteredExams = computed(() => {
  let result = exams.value
  if (statusFilter.value) {
    result = result.filter(e => e.status === statusFilter.value)
  }
  if (searchText.value) {
    result = result.filter(e => e.title.includes(searchText.value))
  }
  return result
})

onMounted(async () => {
  await loadExams()
  await loadMajors()
})

const loadExams = async () => {
  try {
    const res = await request.get('/api/exams')
    exams.value = res.data
  } catch (e) {
    console.error('加载考试失败', e)
  }
}

const loadMajors = async () => {
  try {
    const res = await request.get('/api/majors')
    majors.value = res.data
  } catch (e) {
    console.error('加载专业失败', e)
  }
}

const createExam = async () => {
  if (!createForm.value.title) {
    ElMessage.warning('请输入考试名称')
    return
  }
  if (!createForm.value.start_time || !createForm.value.end_time) {
    ElMessage.warning('请选择时间')
    return
  }

  try {
    await request.post('/api/exams', {
      title: createForm.value.title,
      description: createForm.value.description,
      start_time: createForm.value.start_time.toISOString(),
      end_time: createForm.value.end_time.toISOString(),
      duration: createForm.value.duration
    })
    ElMessage.success('创建成功')
    showCreateModal.value = false
    resetForm()
    await loadExams()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '创建失败')
  }
}

const resetForm = () => {
  createForm.value = {
    title: '',
    description: '',
    start_time: '',
    end_time: '',
    duration: 60
  }
}

const publishExam = async (id) => {
  try {
    await request.post(`/api/exams/${id}/publish`)
    ElMessage.success('发布成功')
    await loadExams()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '发布失败')
  }
}

const endExam = async (id) => {
  await ElMessageBox.confirm('确定要结束这场考试吗？', '提示', { type: 'warning' })
  try {
    await request.post(`/api/exams/${id}/end`)
    ElMessage.success('结束成功')
    await loadExams()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '结束失败')
  }
}

const deleteExam = async (id, title) => {
  await ElMessageBox.confirm(
    `确定要删除考试「${title}」吗？此操作不可恢复，相关成绩数据也将被删除！`,
    '删除确认',
    { type: 'warning' }
  )
  try {
    await request.delete(`/api/exams/${id}`)
    ElMessage.success('删除成功')
    await loadExams()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '删除失败')
  }
}

const viewResults = (id) => {
  router.push(`/results/exam/${id}`)
}

const handleDropdownAction = (action, exam) => {
  switch (action) {
    case 'edit':
      router.push(`/exams/${exam.id}/edit`)
      break
    case 'smart':
      currentExamId.value = exam.id
      showSmartModal.value = true
      break
    case 'questions':
      currentExamId.value = exam.id
      loadExamQuestions()
      loadAvailableQuestions()
      showQuestionsModal.value = true
      break
    case 'students':
      currentExamId.value = exam.id
      loadExamStudents()
      loadAllStudents()
      showStudentsModal.value = true
      break
    case 'delete':
      deleteExam(exam.id, exam.title)
      break
  }
}

const loadExamQuestions = async () => {
  try {
    const res = await request.get(`/api/exams/${currentExamId.value}/questions`)
    examQuestions.value = res.data
  } catch (e) {
    console.error('加载题目失败', e)
  }
}

const loadAvailableQuestions = async () => {
  try {
    const res = await request.get('/api/questions')
    const existingIds = examQuestions.value.map(q => q.id)
    allAvailableQuestions.value = res.data.filter(q => !existingIds.includes(q.id)).map(q => ({
      ...q,
      label: `${q.content.substring(0, 40)}${q.content.length > 40 ? '...' : ''}`
    }))
    availableQuestions.value = allAvailableQuestions.value
  } catch (e) {
    console.error('加载题库失败', e)
  }
}

const searchAvailableQuestions = () => {
  const keyword = questionSearchText.value
  if (!keyword) {
    availableQuestions.value = allAvailableQuestions.value
  } else {
    availableQuestions.value = allAvailableQuestions.value.filter(q =>
      q.content.includes(keyword)
    )
  }
}

const handleQuestionSelection = (selectedItems) => {
  addQuestionsForm.value.question_ids = selectedItems.map(item => item.id)
}

const editQuestionScore = (index) => {
  editingScoreIndex.value = index
  editingScore.value = examQuestions.value[index].score || 10
  ElMessageBox.prompt('请输入题目分数', '编辑分数', {
    inputValue: editingScore.value.toString(),
    inputPattern: /^[1-9]\d*$/,
    inputErrorMessage: '请输入有效的正整数',
    confirmButtonText: '确定',
    cancelButtonText: '取消'
  }).then(({ value }) => {
    examQuestions.value[index].score = parseInt(value)
    ElMessage.success('分数已更新')
  }).catch(() => {})
}

const addExamQuestions = async () => {
  if (addQuestionsForm.value.question_ids.length === 0) {
    ElMessage.warning('请选择题目')
    return
  }
  try {
    await request.post(`/api/exams/${currentExamId.value}/add_questions`, {
      question_ids: addQuestionsForm.value.question_ids
    })
    ElMessage.success('添加成功')
    addQuestionsForm.value.question_ids = []
    await loadExamQuestions()
    await loadAvailableQuestions()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '添加失败')
  }
}

const removeExamQuestion = async (questionId) => {
  await ElMessageBox.confirm('确定要移除这道题目吗？', '提示', { type: 'warning' })
  try {
    await request.post(`/api/exams/${currentExamId.value}/remove_question/${questionId}`)
    ElMessage.success('移除成功')
    await loadExamQuestions()
    await loadAvailableQuestions()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '移除失败')
  }
}

const loadExamStudents = async () => {
  try {
    const res = await request.get(`/api/exams/${currentExamId.value}/students`)
    examStudents.value = res.data
  } catch (e) {
    console.error('加载学生列表失败', e)
  }
}

const loadAllStudents = async () => {
  try {
    const res = await request.get('/api/students')
    const existingIds = examStudents.value.map(s => s.id)
    allStudents.value = res.data.filter(s => !existingIds.includes(s.id))
    selectedStudents.value = []
  } catch (e) {
    console.error('加载所有学生失败', e)
  }
}

const inviteStudents = async () => {
  if (selectedStudents.value.length === 0) {
    ElMessage.warning('请选择学生')
    return
  }
  try {
    await request.post(`/api/exams/${currentExamId.value}/invite`, {
      student_ids: selectedStudents.value
    })
    ElMessage.success('邀请成功')
    selectedStudents.value = []
    await loadExamStudents()
    await loadAllStudents()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '邀请失败')
  }
}

const searchStudents = () => {}

const handleStudentSelection = (selectedItems) => {
  selectedStudents.value = selectedItems.map(item => item.id)
}

const removeStudent = async (studentId) => {
  await ElMessageBox.confirm('确定要移除该学生吗？', '提示', { type: 'warning' })
  try {
    await request.post(`/api/exams/${currentExamId.value}/remove_student/${studentId}`)
    ElMessage.success('移除成功')
    await loadExamStudents()
    await loadAllStudents()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '移除失败')
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

const doSmartComposition = async () => {
  if (!currentExamId.value) {
    ElMessage.warning('请选择考试')
    return
  }

  try {
    const res = await request.post(`/api/exams/${currentExamId.value}/smart_composition`, smartForm.value)
    ElMessage.success(res.data.message)
    showSmartModal.value = false
    await loadExams()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '组卷失败')
  }
}
</script>

<style scoped>
.page-wrapper {
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border-color);
}

.header-title h2 {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}

.header-title p {
  color: var(--text-muted);
  margin: 6px 0 0;
  font-size: 15px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.header-actions .el-button--primary {
  border-radius: 12px;
  padding: 0 28px;
  height: 44px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  font-weight: 600;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.35);
  transition: all 0.3s ease;
}

.header-actions .el-button--primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(102, 126, 234, 0.45);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 32px;
}

.stat-card {
  background: var(--bg-card);
  border-radius: 20px;
  padding: 28px;
  display: flex;
  align-items: center;
  gap: 20px;
  border: 1px solid var(--border-color);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.stat-card::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -50%;
  width: 100%;
  height: 100%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.05) 0%, transparent 70%);
  opacity: 0;
  transition: opacity 0.4s ease;
}

.stat-card:hover {
  transform: translateY(-6px) scale(1.02);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
  border-color: rgba(99, 102, 241, 0.15);
}

.stat-card:hover::before {
  opacity: 1;
}

.stat-icon {
  width: 64px;
  height: 64px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
  z-index: 1;
  transition: transform 0.3s ease;
}

.stat-card:hover .stat-icon {
  transform: scale(1.1);
}

.stat-info {
  flex: 1;
  position: relative;
  z-index: 1;
}

.stat-value {
  font-size: 36px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
  position: relative;
}

.stat-value::after {
  content: '';
  position: absolute;
  bottom: -4px;
  left: 0;
  width: 30px;
  height: 3px;
  background: var(--gradient-primary);
  border-radius: 2px;
  opacity: 0;
  transition: opacity 0.3s ease;
}

.stat-card:hover .stat-value::after {
  opacity: 1;
}

.stat-label {
  font-size: 14px;
  color: var(--text-muted);
  margin-top: 8px;
  font-weight: 500;
}

.filter-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 28px;
  padding: 16px 20px;
  background: var(--bg-card);
  border-radius: 12px;
  border: 1px solid var(--border-color);
}

.filter-bar .el-select {
  width: 180px;
}

.filter-bar .el-input {
  flex: 1;
  max-width: 320px;
}

.filter-bar :deep(.el-input__wrapper),
.filter-bar :deep(.el-select .el-input__wrapper) {
  border-radius: 10px;
  background: var(--bg-tertiary);
  border-color: transparent;
}

.filter-bar :deep(.el-input__wrapper):focus-within,
.filter-bar :deep(.el-select .el-input__wrapper):focus-within {
  border-color: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.exam-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 24px;
}

.exam-card {
  background: var(--bg-card);
  border-radius: 24px;
  padding: 32px;
  border: 1px solid var(--border-color);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.exam-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 6px;
  height: 100%;
  transition: width 0.3s ease;
}

.exam-card::after {
  content: '';
  position: absolute;
  top: -60px;
  right: -60px;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  opacity: 0;
  transition: opacity 0.4s ease;
}

.exam-card.draft::before { background: linear-gradient(180deg, #f59e0b 0%, #d97706 100%); }
.exam-card.published::before { background: linear-gradient(180deg, #10b981 0%, #059669 100%); }
.exam-card.ended::before { background: linear-gradient(180deg, #8b5cf6 0%, #7c3aed 100%); }

.exam-card.draft::after { background: radial-gradient(circle, rgba(245, 158, 11, 0.15) 0%, transparent 70%); }
.exam-card.published::after { background: radial-gradient(circle, rgba(16, 185, 129, 0.15) 0%, transparent 70%); }
.exam-card.ended::after { background: radial-gradient(circle, rgba(139, 92, 246, 0.15) 0%, transparent 70%); }

.exam-card:hover {
  transform: translateY(-8px) scale(1.01);
  box-shadow: 0 24px 50px rgba(0, 0, 0, 0.12);
  border-color: rgba(99, 102, 241, 0.15);
}

.exam-card:hover::after {
  opacity: 1;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.badge-status {
  padding: 6px 16px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  position: relative;
  overflow: hidden;
}

.badge-status::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.3) 0%, transparent 50%);
}

.badge-status.draft { 
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); 
  color: #d97706;
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.2);
}
.badge-status.published { 
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%); 
  color: #059669;
  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.2);
}
.badge-status.ended { 
  background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%); 
  color: #7c3aed;
  box-shadow: 0 2px 8px rgba(139, 92, 246, 0.2);
}

.exam-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 10px;
}

.exam-desc {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0 0 20px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.exam-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 20px;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-light);
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-radius: 10px;
}

.card-footer {
  border-top: 1px solid var(--border-color);
  padding-top: 20px;
}

.card-footer .el-button {
  border-radius: 10px;
  padding: 10px 24px;
  font-weight: 500;
  transition: all 0.3s ease;
}

.card-footer .el-button:hover {
  transform: translateY(-2px);
}

.empty-state {
  text-align: center;
  padding: 80px 20px;
  background: var(--bg-card);
  border-radius: 20px;
  border: 1px dashed var(--border-color);
}

.empty-icon {
  margin-bottom: 20px;
}

.empty-state h3 {
  font-size: 20px;
  color: var(--text-primary);
  margin: 0 0 10px;
}

.empty-state p {
  color: var(--text-muted);
  margin: 0;
  font-size: 15px;
}

.dark .page-wrapper {
  background: var(--bg-secondary);
}

.dark .page-header {
  border-bottom-color: var(--glass-border);
}

.dark .header-title h2 {
  color: var(--text-primary);
}

.dark .header-title p {
  color: var(--text-light);
}

.dark .stat-card {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-card);
  position: relative;
  overflow: hidden;
}

.dark .stat-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(99, 102, 241, 0.4), transparent);
}

.dark .stat-card:hover {
  border-color: var(--border-glow);
  box-shadow: var(--shadow-glow), var(--shadow-card);
  transform: translateY(-4px);
}

.dark .stat-value {
  color: var(--text-primary);
}

.dark .stat-label {
  color: var(--text-light);
}

.dark .stat-icon {
  background: rgba(99, 102, 241, 0.15);
}

.dark .filter-bar {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-card);
}

.dark .filter-bar :deep(.el-input__wrapper),
.dark .filter-bar :deep(.el-select .el-input__wrapper) {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
}

.dark .filter-bar :deep(.el-input__inner),
.dark .filter-bar :deep(.el-select .el-input__inner) {
  color: var(--text-primary);
}

.dark .filter-bar :deep(.el-input__placeholder),
.dark .filter-bar :deep(.el-select__placeholder) {
  color: var(--text-disabled);
}

.dark .filter-bar :deep(.el-select-dropdown) {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
}

.dark .filter-bar :deep(.el-option) {
  color: var(--text-secondary);
}

.dark .filter-bar :deep(.el-option:hover) {
  background: var(--bg-hover);
}

.dark .exam-card {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-card);
  position: relative;
  overflow: hidden;
}

.dark .exam-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(99, 102, 241, 0.2), transparent);
}

.dark .exam-card:hover {
  border-color: var(--border-glow);
  box-shadow: var(--shadow-glow), var(--shadow-card);
  transform: translateY(-4px);
}

.dark .exam-title {
  color: var(--text-primary);
}

.dark .exam-desc {
  color: var(--text-secondary);
}

.dark .meta-item {
  color: var(--text-secondary);
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--glass-border);
}

.dark .card-footer {
  border-top: 1px solid var(--glass-border);
  background: rgba(255,255,255,0.03);
}

.dark .badge-status.draft { 
  background: rgba(245, 158, 11, 0.15); 
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.25);
}

.dark .badge-status.published { 
  background: rgba(16, 185, 129, 0.15); 
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.dark .badge-status.ended { 
  background: rgba(139, 92, 246, 0.15); 
  color: #a78bfa;
  border: 1px solid rgba(139, 92, 246, 0.25);
}

.dark .badge-status::before {
  background: linear-gradient(180deg, rgba(255,255,255,0.15) 0%, transparent 50%);
}

.dark .empty-state {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px dashed var(--glass-border);
}

.dark .empty-state h3 {
  color: var(--text-primary);
}

.dark .empty-state p {
  color: var(--text-light);
}

.dark .empty-icon {
  color: var(--border-color);
}

.dark .el-dialog {
  background: var(--bg-card);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--glass-border);
  box-shadow: var(--shadow-xl);
}

.dark .el-dialog__header {
  border-bottom: 1px solid var(--glass-border);
  background: rgba(0, 0, 0, 0.1);
}

.dark .el-dialog__title {
  color: var(--text-primary);
}

.dark .el-form-item__label {
  color: var(--text-light);
}

.dark .el-input__wrapper {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
}

.dark .el-input__inner {
  color: var(--text-primary);
}

.dark .el-textarea__inner {
  background: var(--bg-input);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
}

.dark .el-date-picker {
  background: var(--bg-card);
}

.dark .el-input-number {
  background: var(--bg-input);
}

.dark .el-input-number__decrease,
.dark .el-input-number__increase {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
  color: var(--text-secondary);
}

.dark .el-dropdown-menu {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
}

.dark .el-dropdown-menu__item {
  color: var(--text-secondary);
}

.dark .el-dropdown-menu__item:hover {
  background: var(--bg-hover);
}

.dark .el-select .el-input__wrapper {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
}

.dark .el-select .el-input__inner {
  color: var(--text-primary) !important;
}

.dark .el-select .el-input__placeholder {
  color: var(--text-disabled) !important;
}

.dark .el-select-dropdown {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
}

.dark .el-select-dropdown__item {
  color: var(--text-secondary) !important;
}

.dark .el-select-dropdown__item:hover {
  background: var(--bg-hover) !important;
}

.dark .el-select-dropdown__item.selected {
  background: rgba(99, 102, 241, 0.2) !important;
  color: #818cf8 !important;
}

.dark .el-dialog__body {
  background: var(--bg-card);
}

.dark .el-dialog__footer {
  background: rgba(0, 0, 0, 0.1);
  border-top: 1px solid var(--glass-border);
}

.dark .el-button {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
  color: var(--text-secondary) !important;
}

.dark .el-button:hover {
  background: var(--bg-hover) !important;
}

.dark .el-button--primary {
  background: var(--gradient-primary) !important;
  border-color: transparent !important;
}

.questions-modal,
.students-modal {
  max-height: 650px;
  overflow-y: auto;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header h4 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.header-info {
  display: flex;
  gap: 12px;
}

.count-badge {
  padding: 4px 12px;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
}

.score-badge {
  padding: 4px 12px;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
}

.empty-tip {
  padding: 40px 24px;
  text-align: center;
  background: var(--bg-tertiary);
  border-radius: 12px;
  margin-bottom: 16px;
}

.empty-icon-wrap {
  margin-bottom: 12px;
}

.empty-tip p {
  color: var(--text-muted);
  font-size: 14px;
  margin: 0;
}

.question-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 20px;
}

.question-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: var(--bg-tertiary);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  transition: all 0.3s ease;
}

.question-item:hover {
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.08);
}

.question-main {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.question-order {
  width: 28px;
  height: 28px;
  background: var(--gradient-primary);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

.question-content-wrap {
  flex: 1;
  min-width: 0;
}

.question-text {
  font-size: 14px;
  color: var(--text-primary);
  margin: 0 0 8px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.question-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.type-tag {
  padding: 3px 10px;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.diff-tag {
  padding: 3px 10px;
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.score-tag {
  padding: 3px 10px;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.question-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.add-section {
  margin-top: 8px;
}

.add-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.add-header h4 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.available-count {
  font-size: 13px;
  color: var(--text-muted);
}

.search-bar {
  margin-bottom: 12px;
}

.question-table-wrap {
  margin-bottom: 12px;
}

.add-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.selected-info {
  font-size: 13px;
  color: var(--text-muted);
}

.student-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 20px;
}

.student-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: var(--bg-tertiary);
  border-radius: 12px;
  border: 1px solid var(--border-color);
  transition: all 0.3s ease;
}

.student-item:hover {
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.08);
}

.student-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.student-avatar {
  width: 36px;
  height: 36px;
  background: var(--gradient-primary);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.student-info {
  flex: 1;
  min-width: 0;
}

.student-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  display: block;
  margin-bottom: 2px;
}

.student-email {
  font-size: 13px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.student-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-right: 12px;
}

.submit-status {
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.submit-status.submitted {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.submit-status.pending {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.score-display {
  padding: 3px 10px;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}

.submit-count {
  padding: 4px 12px;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
}

.student-table-wrap {
  margin-bottom: 12px;
}

.dark .questions-modal,
.dark .students-modal {
  background: var(--bg-card);
}

.dark .questions-section h4,
.dark .students-section h4 {
  color: var(--text-primary);
}

.dark .add-section h4,
.dark .invite-section h4 {
  color: var(--text-primary);
}

.dark .empty-tip {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-light);
}

.dark .question-item {
  background: rgba(255, 255, 255, 0.04);
}

.dark .question-text {
  color: var(--text-primary);
}

.dark .student-item {
  background: rgba(255, 255, 255, 0.04);
}

.dark .student-name {
  color: var(--text-primary);
}

.dark .student-email {
  color: var(--text-secondary);
}

.dark .submit-status.submitted {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
}

.dark .submit-status.pending {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
}

.dark .el-table {
  background: var(--bg-tertiary);
}

.dark .el-table th {
  background: rgba(0, 0, 0, 0.2);
  color: var(--text-light);
  border-color: var(--glass-border);
}

.dark .el-table td {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border-color: var(--glass-border);
}

.dark .el-table tr:hover > td {
  background: var(--bg-hover);
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .exam-grid {
    grid-template-columns: 1fr;
  }
  .filter-bar {
    flex-wrap: wrap;
  }
}
</style>