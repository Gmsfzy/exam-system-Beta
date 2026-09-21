<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2>竞赛管理</h2>
        <p>创建限时积分赛或作品赛，发布需教师交叉审核，查看实时排行</p>
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

    <!-- v4.5 待审核赛事（教师互审） -->
    <div v-if="pendingList.length" class="pending-panel">
      <h3>🔍 待审核赛事（{{ pendingList.length }}）</h3>
      <div v-for="p in pendingList" :key="p.id" class="pending-row">
        <div class="p-info">
          <span class="p-title">{{ p.title }}</span>
          <span class="p-meta">创建人 {{ p.creator }} · {{ p.question_count }} 题 · {{ fmtTime(p.start_time) }} 开放<template v-if="p.prize_points"> · 奖金 {{ p.prize_points }} 积分</template></span>
        </div>
        <span class="p-ops">
          <el-button size="small" type="success" @click="reviewComp(p, 'approve')">通过</el-button>
          <el-button size="small" type="danger" plain @click="reviewComp(p, 'reject')">驳回</el-button>
        </span>
      </div>
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
            <el-tag v-if="comp.competition_type === 'project'" size="small" type="warning" effect="plain">作品赛</el-tag>
            <el-tag v-if="comp.competition_type === 'ds'" size="small" type="primary" effect="plain">数据赛</el-tag>
            <el-tag v-if="comp.prize_points" size="small" type="danger" effect="plain">冠军 {{ comp.prize_points }} 积分</el-tag>
            <el-tag v-if="comp.access_mode === 'restricted'" size="small" type="warning" effect="plain">受限</el-tag>
          </div>
          <p class="comp-desc">{{ comp.description || '暂无描述' }}</p>
          <p v-if="comp.status === 'rejected' && comp.review_reason" class="comp-desc" style="color: #f56c6c">驳回原因：{{ comp.review_reason }}</p>
          <div class="comp-meta">
            <span class="meta-tag"><el-icon :size="14"><Calendar /></el-icon>{{ fmtTime(comp.start_time) }} ~ {{ fmtTime(comp.end_time) }}</span>
            <span class="meta-tag"><el-icon :size="14"><Clock /></el-icon>{{ comp.duration }}分钟</span>
            <span class="meta-tag"><el-icon :size="14"><List /></el-icon>{{ comp.question_count }}题</span>
            <span class="meta-tag"><el-icon :size="14"><Star /></el-icon>总分{{ comp.total_score }}</span>
            <span class="meta-tag"><el-icon :size="14"><User /></el-icon>{{ comp.participant_count }}人参与</span>
          </div>
        </div>
        <div class="comp-actions">
          <el-button v-if="['draft', 'rejected'].includes(comp.status)" size="small" @click="openEdit(comp)">编辑</el-button>
          <el-button v-if="['draft', 'rejected'].includes(comp.status) && comp.competition_type === 'timed'" size="small" type="primary" @click="openQuestions(comp)">选题</el-button>
          <el-button v-if="['draft', 'rejected'].includes(comp.status) && comp.competition_type === 'timed' && comp.question_count > 0" size="small" @click="openManageQuestions(comp)">题目管理</el-button>
          <el-button v-if="['draft', 'rejected'].includes(comp.status)" size="small" type="success" @click="publish(comp)">发布</el-button>
          <el-button v-if="comp.status === 'ongoing'" size="small" type="warning" @click="endCompetition(comp)">结束</el-button>
          <el-button size="small" @click="viewLeaderboard(comp)">排行榜</el-button>
          <el-button v-if="comp.status !== 'draft'" size="small" @click="openExtras(comp)">公告/资料</el-button>
          <el-button v-if="comp.competition_type === 'project' && ['published', 'ongoing', 'ended'].includes(comp.status)" size="small" @click="openWorks(comp)">作品评审</el-button>
          <el-button v-if="comp.competition_type === 'ds' && comp.status !== 'draft'" size="small" type="primary" plain @click="openDsManage(comp)">数据赛工作台</el-button>
          <el-button v-if="comp.status === 'ended' && comp.frozen_points > 0" size="small" type="warning" plain @click="settle(comp)">结算奖金</el-button>
          <el-button v-if="comp.status === 'ended' && comp.question_count > 0" size="small" plain @click="archive(comp)">归档题库</el-button>
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
        <el-form-item label="竞赛类型">
          <el-select v-model="editForm.compType" :disabled="!!editForm.id" style="width: 240px">
            <el-option value="timed" label="限时积分赛" />
            <el-option value="project" label="作品提交赛（人工评审）" />
            <el-option value="ds" label="数据科学赛（在线运行·自动评分）" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editForm.compType === 'timed'" label="答题时长" required>
          <el-input-number v-model="editForm.duration" :min="1" :max="180" />
          <span class="form-tip">每人限时（分钟）</span>
        </el-form-item>
        <el-form-item label="冠军奖金">
          <el-input-number v-model="editForm.prizePoints" :min="0" :max="100000" :step="50" />
          <span class="form-tip">积分托管：发布时从你的赏金钱包冻结，结算发给冠军，驳回/流标退回；0 = 纯荣誉赛</span>
        </el-form-item>
        <el-form-item v-if="editForm.compType === 'timed'" label="抽题数">
          <el-input-number v-model="editForm.drawCount" :min="0" :max="200" />
          <span class="form-tip">每人随机抽题数，0 = 答全部题目（防作弊）</span>
        </el-form-item>
        <el-form-item v-if="editForm.compType === 'timed'" label="PK对战">
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
        <el-form-item v-if="editForm.compType === 'timed'" label="计分规则">
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
          <el-option v-for="t in QUESTION_TYPE_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
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
    <!-- v4.5 公告与资料包 -->
    <el-dialog v-model="extrasVisible" :title="`公告与资料 - ${extrasComp?.title || ''}`" width="720px" top="6vh">
      <el-tabs>
        <el-tab-pane label="赛事公告">
          <div class="ann-create">
            <el-input v-model="annForm.title" placeholder="公告标题" style="width: 200px" maxlength="100" />
            <el-input v-model="annForm.content" placeholder="公告内容（发布后向全体参赛者推送通知）" style="flex: 1" maxlength="5000" />
            <el-button type="primary" :loading="annSaving" @click="saveAnnouncement">发布</el-button>
          </div>
          <el-empty v-if="!announcements.length" description="暂无公告" :image-size="60" />
          <div v-for="a in announcements" :key="a.id" class="ann-item">
            <div class="ann-head"><b>{{ a.title }}</b><span class="ann-meta">{{ a.author }} · {{ (a.created_at || '').slice(0, 16) }}</span>
              <el-button size="small" text type="danger" @click="delAnnouncement(a)">删除</el-button></div>
            <div class="ann-content">{{ a.content }}</div>
          </div>
        </el-tab-pane>
        <el-tab-pane label="资料包">
          <div class="ann-create">
            <input ref="resFileInput" type="file" @change="onResFilePick" style="display:none" />
            <el-button @click="$refs.resFileInput.click()">📎 选择文件上传（≤50MB）</el-button>
            <span v-if="resFileName" class="form-tip">{{ resFileName }}</span>
          </div>
          <el-table :data="resources" size="small">
            <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
            <el-table-column prop="filename" label="文件" min-width="150" show-overflow-tooltip />
            <el-table-column label="大小" width="90"><template #default="{ row }">{{ fmtSize(row.size) }}</template></el-table-column>
            <el-table-column label="操作" width="140" align="center">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="downloadResource(row)">下载</el-button>
                <el-button size="small" text type="danger" @click="delResource(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <!-- v4.5 作品评审（project 型） -->
    <el-dialog v-model="worksVisible" :title="`作品评审 - ${worksComp?.title || ''}`" width="760px" top="6vh">
      <el-empty v-if="!works.length" description="还没有学生提交作品" :image-size="60" />
      <el-table v-else :data="works" size="small" max-height="440">
        <el-table-column prop="username" label="选手" width="110" />
        <el-table-column label="作品" min-width="200">
          <template #default="{ row }">
            <a v-if="row.stored_name || row.filename" class="dl-link" @click="downloadWork(row)">📎 {{ row.filename || '文件' }}（v{{ row.version }}）</a>
            <div class="work-desc">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="130"><template #default="{ row }">{{ fmtTime(row.submitted_at) }}<div class="form-tip">更新 {{ fmtTime(row.updated_at) }}</div></template></el-table-column>
        <el-table-column label="评分" width="150" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.score != null" type="success">{{ row.score }} 分</el-tag>
            <el-button v-else size="small" type="primary" @click="scoreWork(row)">评分</el-button>
            <el-button v-if="row.score != null" size="small" text @click="scoreWork(row)">重评</el-button>
          </template>
        </el-table-column>
      </el-table>
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

const statusLabel = (s) => ({ draft: '草稿', reviewing: '待审核', rejected: '被驳回', published: '已发布', ongoing: '进行中', ended: '已结束' }[s] || s)
const statusTag = (s) => ({ draft: 'info', reviewing: 'warning', rejected: 'danger', published: 'primary', ongoing: 'success', ended: 'danger' }[s] || 'info')
// v4.6.1 枚举收敛：题型/难度单一来源 frontend/src/utils/enums.js（简称统一为全称）
import { typeLabel, difficultyLabel, QUESTION_TYPE_OPTIONS } from '../utils/enums'
const diffLabel = difficultyLabel

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
  loadPending()
}

// ── v4.5 审核门禁：待审核列表 ──
const pendingList = ref([])
const loadPending = async () => {
  try {
    const res = await request.get('/api/competitions/pending')
    pendingList.value = res.data.items || []
  } catch (e) { /* 非教师接口 403，忽略 */ }
}

const reviewComp = async (p, action) => {
  if (action === 'approve') {
    try {
      await ElMessageBox.confirm(`确认通过「${p.title}」的发布审核？通过后立即对全体学生开放`, '审核通过')
    } catch (e) { return }
    const res = await request.post(`/api/competitions/${p.id}/review`, { action })
    ElMessage.success(res.data.message || '已通过')
  } else {
    try {
      const { value } = await ElMessageBox.prompt(`驳回「${p.title}」，请填写理由（将通知创建者）`, '审核驳回', { inputPattern: /\S+/, inputErrorMessage: '请填写驳回理由' })
      const res = await request.post(`/api/competitions/${p.id}/review`, { action, reason: value })
      ElMessage.success(res.data.message || '已驳回')
    } catch (e) { return }
  }
  loadCompetitions()
}

const openCreate = () => {
  editForm.value = { id: null, title: '', description: '', timeRange: [], duration: 10, baseRatio: 0.7, speedRatio: 0.3, drawCount: 0, allowPk: true, accessMode: 'public', inviteCode: '', remindBefore: 0, compType: 'timed', prizePoints: 0 }
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
    compType: detail.competition_type || 'timed',
    prizePoints: detail.prize_points ?? 0,
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
    duration: (f.compType === 'project' || f.compType === 'ds') ? 0 : f.duration,
    competition_type: f.compType || 'timed',
    prize_points: f.prizePoints || 0,
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

const openDsManage = (comp) => {
  router.push(`/competitions/${comp.id}/ds-manage`)
}

const publish = (comp) => {
  ElMessageBox.confirm(
    comp.competition_type !== 'timed'
      ? '发布后需其他教师审核（本系统仅你一名教师时自动通过），确认提交？'
      : `发布后题目将锁定，共 ${comp.question_count} 题。确认发布？`,
    '发布竞赛', { type: 'warning' }
  ).then(async () => {
    const res = await request.post(`/api/competitions/${comp.id}/publish`)
    ElMessage.success(res.data.message || '发布成功')
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

// ── v4.5 公告与资料包 ──
const fmtSize = (n) => !n ? '-' : (n > 1048576 ? (n / 1048576).toFixed(1) + 'MB' : Math.max(1, Math.round(n / 1024)) + 'KB')
const downloadBlob = async (url, filename) => {
  const res = await request.get(url, { responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(res.data)
  link.download = filename || 'download'
  link.click()
  URL.revokeObjectURL(link.href)
}

const extrasVisible = ref(false)
const extrasComp = ref(null)
const announcements = ref([])
const annForm = ref({ title: '', content: '' })
const annSaving = ref(false)
const resources = ref([])
const resFileName = ref('')
let resPickedFile = null

const openExtras = async (comp) => {
  extrasComp.value = comp
  annForm.value = { title: '', content: '' }
  extrasVisible.value = true
  loadAnnouncements()
  loadResources()
}
const loadAnnouncements = async () => {
  const res = await request.get(`/api/competitions/${extrasComp.value.id}/announcements`)
  announcements.value = res.data.items || []
}
const loadResources = async () => {
  const res = await request.get(`/api/competitions/${extrasComp.value.id}/resources`)
  resources.value = res.data.items || []
}
const saveAnnouncement = async () => {
  if (!annForm.value.title?.trim() || !annForm.value.content?.trim()) return ElMessage.warning('请填写公告标题与内容')
  annSaving.value = true
  try {
    await request.post(`/api/competitions/${extrasComp.value.id}/announcements`, annForm.value)
    ElMessage.success('已发布并通知全体参赛者')
    annForm.value = { title: '', content: '' }
    loadAnnouncements()
  } finally { annSaving.value = false }
}
const delAnnouncement = async (a) => {
  await request.delete(`/api/competitions/${extrasComp.value.id}/announcements/${a.id}`)
  ElMessage.success('已删除')
  loadAnnouncements()
}
const onResFilePick = (e) => {
  const file = e.target.files?.[0]
  if (!file) return
  resPickedFile = file
  resFileName.value = file.name
  const fd = new FormData()
  fd.append('file', file)
  request.post(`/api/competitions/${extrasComp.value.id}/resources`, fd).then(() => {
    ElMessage.success('上传成功')
    resFileName.value = ''
    resPickedFile = null
    e.target.value = ''
    loadResources()
  }).catch(() => { e.target.value = '' })
}
const delResource = async (r) => {
  await request.delete(`/api/competitions/${extrasComp.value.id}/resources/${r.id}`)
  ElMessage.success('已删除')
  loadResources()
}
const downloadResource = (r) => downloadBlob(`/api/competition-resources/${r.id}/download`, r.filename)

// ── v4.5 作品评审与结算 ──
const worksVisible = ref(false)
const worksComp = ref(null)
const works = ref([])
const openWorks = async (comp) => {
  worksComp.value = comp
  worksVisible.value = true
  const res = await request.get(`/api/competitions/${comp.id}/works`)
  works.value = res.data.items || []
}
const scoreWork = async (row) => {
  try {
    const { value } = await ElMessageBox.prompt(
      `给 ${row.username} 的作品评分（0-100，同分取最早提交者夺冠）`, '作品评分',
      { inputPattern: /^(\d{1,2}|100)(\.\d)?$/ , inputErrorMessage: '请输入 0-100 的数字',
        inputPlaceholder: '分数，如 85' }
    )
    const note = await ElMessageBox.prompt('评语（可选，将通知选手）', '作品评语', { inputPattern: /[\s\S]*/, inputValue: '' }).catch(() => ({ value: '' }))
    await request.post(`/api/competition-works/${row.id}/score`, { score: parseFloat(value), note: note.value || '' })
    ElMessage.success('已评分并通知选手')
    openWorks(worksComp.value)
  } catch (e) { /* 取消 */ }
}
const downloadWork = (row) => downloadBlob(`/api/competition-works/${row.id}/download`, row.filename || 'work')

const settle = (comp) => {
  ElMessageBox.confirm(
    `将托管的 ${comp.frozen_points} 积分发给冠军（作品赛取最高分，同分取最早提交；无有效作品则流标退回你的钱包）。确认结算？`,
    '结算奖金', { type: 'warning' }
  ).then(async () => {
    const res = await request.post(`/api/competitions/${comp.id}/settle`)
    ElMessage.success(res.data.message || '结算完成')
    loadCompetitions()
  }).catch(() => {})
}

const archive = (comp) => {
  ElMessageBox.confirm('把本场赛题正式加入公共题库，供全体学生练习。确认归档？', '归档题库', { type: 'warning' })
    .then(async () => {
      const res = await request.post(`/api/competitions/${comp.id}/archive`)
      ElMessage.success(res.data.message || '已归档')
    }).catch(() => {})
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
.pending-panel {
  background: #fffbeb;
  border: 1px solid #f3d19e;
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 14px;
}
.pending-panel h3 { margin: 0 0 8px; font-size: 15px; }
.pending-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px dashed #f0dcb2;
  flex-wrap: wrap;
}
.p-info { display: flex; flex-direction: column; gap: 2px; }
.p-title { font-weight: 600; }
.p-meta { color: #909399; font-size: 12px; }
.ann-create { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }
.ann-item { border-bottom: 1px solid #ebeef5; padding: 8px 0; }
.ann-head { display: flex; align-items: center; gap: 10px; }
.ann-head .el-button { margin-left: auto; }
.ann-meta { color: #909399; font-size: 12px; }
.ann-content { color: #606266; font-size: 13px; white-space: pre-wrap; margin-top: 4px; }
.dl-link { color: #409eff; cursor: pointer; font-size: 13px; }
.work-desc { color: #909399; font-size: 12px; margin-top: 2px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
</style>
