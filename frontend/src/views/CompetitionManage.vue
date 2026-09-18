<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>竞赛管理</h2>
        <p>创建限时积分赛，选题发布，查看实时排行</p>
      </div>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>
        创建竞赛
      </el-button>
      <el-button type="warning" plain @click="router.push('/competitions/series')">
        <el-icon><Connection /></el-icon>
        系列赛
      </el-button>
    </div>

    <div v-if="loading" class="loading-box">
      <el-skeleton :rows="4" animated />
    </div>

    <el-empty v-else-if="!competitions.length" description="还没有创建竞赛，点击右上角创建" />

    <div v-else class="comp-list">
      <div v-for="comp in competitions" :key="comp.id" class="comp-card">
        <div class="comp-main">
          <div class="comp-title-row">
            <h3 class="comp-title">{{ comp.title }}</h3>
            <el-tag :type="statusTag(comp.status)" effect="dark" size="small">
              {{ statusLabel(comp.status) }}
            </el-tag>
            <el-tag v-if="comp.access_mode === 'restricted'" size="small" type="warning" effect="plain">受限</el-tag>
          </div>
          <p class="comp-desc">{{ comp.description || '暂无描述' }}</p>
          <div class="comp-meta">
            <span class="meta-tag"><el-icon :size="14"><Calendar /></el-icon>{{ fmtTime(comp.start_time) }} ~ {{ fmtTime(comp.end_time) }}</span>
            <span class="meta-tag"><el-icon :size="14"><Clock /></el-icon>{{ comp.duration }}分钟</span>
            <span class="meta-tag"><el-icon :size="14"><List /></el-icon>{{ comp.question_count }}题</span>
            <span class="meta-tag"><el-icon :size="14"><Star /></el-icon>总分{{ comp.total_score }}</span>
            <span class="meta-tag"><el-icon :size="14"><User /></el-icon>{{ comp.participant_count }}人参与</span>
          </div>
        </div>
        <div class="comp-actions">
          <el-button v-if="comp.status === 'draft'" size="small" @click="openEdit(comp)">编辑</el-button>
          <el-button v-if="comp.status === 'draft'" size="small" type="primary" @click="openQuestions(comp)">选题</el-button>
          <el-button v-if="comp.status === 'draft' && comp.question_count > 0" size="small" @click="openManageQuestions(comp)">题目管理</el-button>
          <el-button v-if="comp.status === 'draft'" size="small" type="success" @click="publish(comp)">发布</el-button>
          <el-button v-if="comp.status === 'ongoing'" size="small" type="warning" @click="endCompetition(comp)">结束</el-button>
          <el-button size="small" @click="viewLeaderboard(comp)">排行榜</el-button>
          <el-button v-if="comp.status === 'ended' || comp.status === 'ongoing'" size="small" type="warning" plain @click="openIntegrity(comp)">公平审查</el-button>
          <el-button v-if="comp.status !== 'ongoing'" size="small" type="danger" text @click="remove(comp)">删除</el-button>
        </div>
      </div>
    </div>

    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="editVisible" :title="editForm.id ? '编辑竞赛' : '创建竞赛'" width="560px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="竞赛标题" required>
          <el-input v-model="editForm.title" placeholder="例如：Python基础挑战赛" maxlength="100" />
        </el-form-item>
        <el-form-item label="竞赛描述">
          <el-input v-model="editForm.description" type="textarea" :rows="2" placeholder="竞赛说明（可选）" />
        </el-form-item>
        <el-form-item label="开放窗口" required>
          <el-date-picker v-model="editForm.timeRange" type="datetimerange"
            start-placeholder="开始时间" end-placeholder="结束时间" value-format="YYYY-MM-DDTHH:mm:ss" />
        </el-form-item>
        <el-form-item label="答题时长" required>
          <el-input-number v-model="editForm.duration" :min="1" :max="180" />
          <span class="form-tip">每人限时（分钟）</span>
        </el-form-item>
        <el-form-item label="抽题数">
          <el-input-number v-model="editForm.drawCount" :min="0" :max="200" />
          <span class="form-tip">每人随机抽题数，0 = 答全部题目（防作弊）</span>
        </el-form-item>
        <el-form-item label="PK对战">
          <el-switch v-model="editForm.allowPk" />
          <span class="form-tip">允许学生基于本题库发起1v1对战</span>
        </el-form-item>
        <el-form-item label="访问权限">
          <el-radio-group v-model="editForm.accessMode">
            <el-radio value="public">公开</el-radio>
            <el-radio value="restricted">受限（邀请码）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="editForm.accessMode === 'restricted'" label="邀请码">
          <template v-if="editForm.inviteCode">
            <el-input v-model="editForm.inviteCode" readonly style="width: 140px" />
            <el-button size="small" @click="copyCode">复制</el-button>
            <el-button size="small" :disabled="!editForm.id" @click="resetCode">重置邀请码</el-button>
          </template>
          <span v-else class="form-tip">保存后自动生成邀请码（或在此指定）</span>
          <el-input v-if="!editForm.inviteCode" v-model="editForm.inviteCode" placeholder="自定义邀请码（可留空）" style="width: 200px; margin-left: 8px" maxlength="16" />
        </el-form-item>
        <el-form-item label="开赛提醒">
          <el-input-number v-model="editForm.remindBefore" :min="0" :max="1440" :step="5" />
          <span class="form-tip">开赛前 N 分钟向已报名选手推送提醒，0 = 关闭</span>
        </el-form-item>
        <el-form-item label="计分规则">
          <div class="rule-row">
            <span>基础分</span>
            <el-input-number v-model="editForm.baseRatio" :min="0" :max="1" :step="0.1" />
            <span>速度分</span>
            <el-input-number v-model="editForm.speedRatio" :min="0" :max="1" :step="0.1" />
          </div>
          <div class="form-tip">得分 = 题分 × 基础比 + 题分 × 速度比 × 剩余时间比，答错得0分</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCompetition">保存</el-button>
      </template>
    </el-dialog>

    <!-- 选题对话框 -->
    <el-dialog v-model="questionVisible" title="选择竞赛题目（仅客观题）" width="760px">
      <div class="question-filter">
        <el-select v-model="qFilter.type" placeholder="题型" clearable style="width: 160px" @change="loadQuestionPool">
          <el-option label="单选题" value="single_choice" />
          <el-option label="多选题" value="multiple_choice" />
          <el-option label="判断题" value="true_false" />
          <el-option label="填空题" value="fill_blank" />
        </el-select>
        <span class="form-tip">已选 {{ selectedQuestions.length }} 题</span>
      </div>
      <el-table ref="questionTableRef" :data="questionPool" max-height="380"
        @selection-change="val => selectedQuestions = val">
        <el-table-column type="selection" width="44" />
        <el-table-column prop="content" label="题干" show-overflow-tooltip />
        <el-table-column prop="type" label="题型" width="90">
          <template #default="{ row }">{{ typeLabel(row.type) }}</template>
        </el-table-column>
        <el-table-column prop="difficulty" label="难度" width="80">
          <template #default="{ row }">{{ diffLabel(row.difficulty) }}</template>
        </el-table-column>
        <el-table-column prop="course_name" label="课程" width="120" show-overflow-tooltip />
      </el-table>
      <div class="score-row">
        <span>每题分值：</span>
        <el-input-number v-model="questionScore" :min="0.5" :max="100" :step="0.5" />
      </div>
      <template #footer>
        <el-button @click="questionVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!selectedQuestions.length" @click="addQuestions">添加</el-button>
      </template>
    </el-dialog>

    <!-- 题目管理对话框 -->
    <el-dialog v-model="manageVisible" :title="`题目管理 - ${manageComp?.title || ''}`" width="720px">
      <el-table :data="manageQuestions" max-height="400">
        <el-table-column prop="order" label="序号" width="60" />
        <el-table-column prop="content" label="题干" show-overflow-tooltip />
        <el-table-column prop="q_type" label="题型" width="90">
          <template #default="{ row }">{{ typeLabel(row.q_type) }}</template>
        </el-table-column>
        <el-table-column prop="score" label="分值" width="70" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" type="danger" text @click="removeQuestion(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="manageVisible = false">关闭</el-button>
      </template>
    </el-dialog>
    <!-- 公平性审查对话框 -->
    <el-dialog v-model="integrityVisible" :title="`公平性审查 - ${integrityComp?.title || ''}`" width="820px">
      <el-alert v-if="integrityLoading" type="info" :closable="false" title="分析中..." />
      <template v-else>
        <div class="integ-tip">系统根据正确率、用时与跨场异常自动标记可疑选手，可一键施加/解除竞技受限。</div>
        <el-table :data="integrityRows" max-height="420" size="small">
          <el-table-column prop="username" label="选手" min-width="100" />
          <el-table-column label="名次" width="60" align="center">
            <template #default="{ row }">{{ row.rank ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="正确率" width="80" align="center">
            <template #default="{ row }">{{ Math.round(row.accuracy * 100) }}%</template>
          </el-table-column>
          <el-table-column label="均用时" width="80" align="center">
            <template #default="{ row }">{{ row.avg_time }}s</template>
          </el-table-column>
          <el-table-column label="异常标记" min-width="200">
            <template #default="{ row }">
              <el-tag v-if="!row.suspicious" size="small" type="success" effect="plain">正常</el-tag>
              <span v-else class="susp-reasons">{{ row.reasons.join('；') }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" align="center">
            <template #default="{ row }">
              <el-button v-if="!row.sanctioned" size="small" type="danger" text @click="doSanction(row)">标记受限</el-button>
              <el-button v-else size="small" type="success" text @click="undoSanction(row)">解除受限</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="integrityVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { Calendar, Clock, List, Star, User, Plus, Connection } from '@element-plus/icons-vue'

const router = useRouter()
const competitions = ref([])
const loading = ref(true)

const editVisible = ref(false)
const editForm = ref({})
const questionVisible = ref(false)
const questionPool = ref([])
const selectedQuestions = ref([])
const questionScore = ref(2)
const qFilter = ref({ type: '' })
let currentComp = null

const manageVisible = ref(false)
const manageComp = ref(null)
const manageQuestions = ref([])

const integrityVisible = ref(false)
const integrityLoading = ref(false)
const integrityComp = ref(null)
const integrityRows = ref([])

const statusLabel = (s) => ({ draft: '草稿', published: '已发布', ongoing: '进行中', ended: '已结束' }[s] || s)
const statusTag = (s) => ({ draft: 'info', published: 'primary', ongoing: 'success', ended: 'danger' }[s] || 'info')
const typeLabel = (t) => ({ single_choice: '单选', multiple_choice: '多选', true_false: '判断', fill_blank: '填空' }[t] || t)
const diffLabel = (d) => ({ easy: '简单', medium: '中等', hard: '困难' }[d] || d)

const fmtTime = (iso) => {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const loadCompetitions = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/competitions')
    competitions.value = res.data
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editForm.value = { id: null, title: '', description: '', timeRange: [], duration: 10, baseRatio: 0.7, speedRatio: 0.3, drawCount: 0, allowPk: true, accessMode: 'public', inviteCode: '', remindBefore: 0 }
  editVisible.value = true
}

const openEdit = async (comp) => {
  let detail = comp
  try {
    const res = await request.get(`/api/competitions/${comp.id}`)
    detail = { ...comp, ...res.data }
  } catch (e) { /* 降级用列表数据 */ }
  editForm.value = {
    id: comp.id,
    title: detail.title,
    description: detail.description || '',
    timeRange: [detail.start_time, detail.end_time],
    duration: detail.duration,
    baseRatio: detail.scoring_rule.base_ratio ?? 0.7,
    speedRatio: detail.scoring_rule.speed_ratio ?? 0.3,
    drawCount: detail.draw_count ?? 0,
    allowPk: detail.allow_pk ?? true,
    accessMode: detail.access_mode || 'public',
    inviteCode: detail.invite_code || '',
    remindBefore: detail.remind_before ?? 0,
  }
  editVisible.value = true
}

const saveCompetition = async () => {
  const f = editForm.value
  if (!f.title?.trim()) return ElMessage.warning('请填写竞赛标题')
  if (!f.timeRange || f.timeRange.length !== 2) return ElMessage.warning('请选择开放窗口')
  const payload = {
    title: f.title,
    description: f.description,
    start_time: f.timeRange[0],
    end_time: f.timeRange[1],
    duration: f.duration,
    draw_count: f.drawCount,
    allow_pk: f.allowPk,
    access_mode: f.accessMode,
    remind_before: f.remindBefore,
    scoring_rule: { base_ratio: f.baseRatio, speed_ratio: f.speedRatio },
  }
  if (f.accessMode === 'restricted' && f.inviteCode) payload.invite_code = f.inviteCode
  if (f.id) {
    await request.put(`/api/competitions/${f.id}`, payload)
    ElMessage.success('更新成功')
  } else {
    await request.post('/api/competitions', payload)
    ElMessage.success('创建成功，请添加题目后发布')
  }
  editVisible.value = false
  loadCompetitions()
}

const openQuestions = async (comp) => {
  currentComp = comp
  questionVisible.value = true
  loadQuestionPool()
}

const loadQuestionPool = async () => {
  const params = qFilter.value.type ? { type: qFilter.value.type } : {}
  const res = await request.get('/api/questions', { params })
  questionPool.value = res.data
}

const addQuestions = async () => {
  const res = await request.post(`/api/competitions/${currentComp.id}/questions`, {
    question_ids: selectedQuestions.value.map(q => q.id),
    score: questionScore.value,
  })
  ElMessage.success(res.data.message || '添加成功')
  questionVisible.value = false
  loadCompetitions()
}

const openManageQuestions = async (comp) => {
  manageComp.value = comp
  manageVisible.value = true
  try {
    const res = await request.get(`/api/competitions/${comp.id}`)
    manageQuestions.value = res.data.questions || []
  } catch (e) { /* ignore */ }
}

const removeQuestion = async (q) => {
  try {
    await ElMessageBox.confirm(`确定移除该题目？`, '移除题目', { type: 'warning' })
    await request.delete(`/api/competitions/${manageComp.value.id}/questions/${q.id}`)
    ElMessage.success('已移除')
    // 刷新题目列表
    const res = await request.get(`/api/competitions/${manageComp.value.id}`)
    manageQuestions.value = res.data.questions || []
    loadCompetitions()
  } catch (e) { /* 用户取消 */ }
}

const publish = (comp) => {
  ElMessageBox.confirm(
    `发布后题目将锁定，共 ${comp.question_count} 题。确认发布？`,
    '发布竞赛', { type: 'warning' }
  ).then(async () => {
    await request.post(`/api/competitions/${comp.id}/publish`)
    ElMessage.success('发布成功')
    loadCompetitions()
  }).catch(() => {})
}

const endCompetition = (comp) => {
  ElMessageBox.confirm('结束后学生将无法继续答题，确认结束？', '结束竞赛', { type: 'warning' })
    .then(async () => {
      await request.post(`/api/competitions/${comp.id}/end`)
      ElMessage.success('已结束')
      loadCompetitions()
    }).catch(() => {})
}

const remove = (comp) => {
  ElMessageBox.confirm(`确定删除竞赛「${comp.title}」？`, '删除竞赛', { type: 'warning' })
    .then(async () => {
      await request.delete(`/api/competitions/${comp.id}`)
      ElMessage.success('删除成功')
      loadCompetitions()
    }).catch(() => {})
}

const viewLeaderboard = (comp) => {
  router.push(`/competitions/${comp.id}/leaderboard`)
}

const copyCode = async () => {
  try {
    await navigator.clipboard.writeText(editForm.value.inviteCode)
    ElMessage.success('邀请码已复制')
  } catch (e) {
    ElMessage.warning('复制失败，请手动选择')
  }
}

const resetCode = async () => {
  if (!editForm.value.id) return ElMessage.warning('请先保存竞赛')
  const res = await request.post(`/api/competitions/${editForm.value.id}/invite/reset`)
  editForm.value.inviteCode = res.data.invite_code
  ElMessage.success('邀请码已重置')
}

const openIntegrity = async (comp) => {
  integrityComp.value = comp
  integrityRows.value = []
  integrityVisible.value = true
  integrityLoading.value = true
  try {
    const res = await request.get(`/api/competitions/${comp.id}/integrity`)
    integrityRows.value = res.data.participants || []
  } finally {
    integrityLoading.value = false
  }
}

const doSanction = async (row) => {
  try {
    const { value } = await ElMessageBox.prompt(
      `将选手「${row.username}」标记为竞技受限（成绩不计入排行），请填写原因：`,
      '标记受限', { confirmButtonText: '确定', cancelButtonText: '取消', inputPlaceholder: '例如：反应时异常 / 跨场正确率异常' }
    )
    await request.post(`/api/competitions/${integrityComp.value.id}/participants/${row.user_id}/sanction`, { reason: value || '异常行为' })
    ElMessage.success('已标记受限')
    openIntegrity(integrityComp.value)
  } catch (e) { /* 取消 */ }
}

const undoSanction = async (row) => {
  await request.post(`/api/competitions/${integrityComp.value.id}/participants/${row.user_id}/sanction`, { revoke: true })
  ElMessage.success('已解除受限')
  openIntegrity(integrityComp.value)
}

onMounted(loadCompetitions)
</script>

<style scoped>
.page-wrapper {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 28px;
}

.header-title h2 {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
}

.header-title p {
  font-size: 15px;
  color: var(--text-muted);
  margin: 0;
}

.loading-box {
  padding: 20px;
}

.comp-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.comp-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 22px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  transition: all 0.3s ease;
}

.comp-card:hover {
  border-color: rgba(245, 158, 11, 0.45);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
}

.comp-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.comp-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.comp-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0 0 10px;
}

.comp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}

.meta-tag {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  color: var(--text-secondary);
}

.comp-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px;
  flex-shrink: 0;
}

.question-filter {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
}

.rule-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rule-row span {
  font-size: 13px;
  color: var(--text-secondary);
}

.form-tip {
  font-size: 12px;
  color: var(--text-light);
  margin-left: 8px;
}

.score-row {
  display: flex;
  align-items: center;
  margin-top: 14px;
  font-size: 14px;
  color: var(--text-secondary);
}

.dark .comp-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
}

.integ-tip {
  font-size: 12.5px;
  color: var(--text-muted);
  margin-bottom: 12px;
}

.susp-reasons {
  font-size: 12px;
  color: #f56c6c;
}

@media (max-width: 768px) {
  .comp-card {
    flex-direction: column;
    align-items: stretch;
  }

  .comp-actions {
    justify-content: flex-start;
  }
}
</style>
