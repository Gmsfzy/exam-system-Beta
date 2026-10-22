<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><EditPen /></el-icon> {{ hw.title || '作业批改' }}</h2>
        <el-tag size="small" effect="plain" style="margin-left: 10px">
          {{ hw.hw_type === 'open' ? '开放式' : '题集式' }}
        </el-tag>
      </div>
      <div class="header-actions">
        <el-button :icon="ChatDotRound" @click="discDialog = true">讨论区</el-button>
        <el-button :icon="UserFilled" @click="openPeer">互评管理</el-button>
        <el-button :icon="DocumentCopy" type="warning" plain @click="openPlagiarism">查重</el-button>
        <el-button :icon="MagicStick" type="primary" plain @click="openClassReview">班级 AI 讲评</el-button>
        <el-button :icon="Back" @click="$router.push('/homeworks/manage')">返回</el-button>
      </div>
    </div>

    <div class="summary">
      名单 {{ studentCount }} 人 · 已提交 {{ items.length }} 份
      <el-tag v-if="blindGrade" size="small" type="info" effect="plain" style="margin-left: 8px">匿名批改中</el-tag>
      <span v-if="notSubmitted.length" class="not-sub">· 未提交：{{ notSubmitted.map(n => n.username).join('、') }}</span>
    </div>

    <el-empty v-if="!items.length" description="还没有学生提交" />
    <el-table v-else :data="items" stripe @row-click="openGrade">
      <el-table-column prop="username" label="学生" width="140" />
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="70" align="center">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column label="得分" width="130" align="center">
        <template #default="{ row }">
          <span v-if="row.status === 'graded' || row.status === 'returned'">{{ row.total_score }} / {{ row.max_score ?? '—' }}<span v-if="row.status === 'returned' && row.revision_round" class="muted small">（订正 {{ row.revision_round }}）</span></span>
          <span v-else class="muted">待批改</span>
        </template>
      </el-table-column>
      <el-table-column label="迟交" width="70" align="center">
        <template #default="{ row }"><el-tag v-if="row.is_late" size="small" type="warning">迟交</el-tag></template>
      </el-table-column>
      <el-table-column label="提交时间" width="160">
        <template #default="{ row }">{{ (row.submitted_at || '').slice(0, 16) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" align="center">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click.stop="openGrade(row)">批改</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 批改抽屉 -->
    <el-drawer v-model="drawer" :title="`批改：${current?.username || ''}`" size="660px">
      <div v-if="loading" class="center">加载中…</div>
      <div v-else-if="grade">
        <div v-if="grade.blind" class="muted small" style="margin-bottom: 8px">
          匿名批改中：学生身份已隐藏，全部批完后自动恢复
        </div>
        <!-- 开放式：正文 + 附件 + 整体给分 -->
        <template v-if="grade.homework.hw_type === 'open'">
          <div class="label">学生提交内容</div>
          <pre class="content-box">{{ grade.submission.content || '（无正文）' }}</pre>
          <div v-if="grade.submission.attachment" class="attach">
            附件：<a :href="attachUrl(grade.submission.id)" target="_blank">{{ grade.submission.attachment.filename }}</a>
          </div>
          <div class="score-row" style="margin-top: 12px">
            <span>总分 / 满分</span>
            <el-input-number v-model="openScore" :min="0" :max="1000" :step="1" size="small" controls-position="right" />
            <el-input-number v-model="openMax" :min="1" :max="1000" size="small" controls-position="right" />
          </div>
        </template>

        <!-- 题集式：逐题 -->
        <div v-else>
          <div v-for="row in rows" :key="row.id" class="answer-block" :class="{ pending: row.needs_manual }">
            <div class="q-head">
              <span class="q-type">{{ typeName(row.type) }}</span>
              <span class="q-content">{{ row.content }}</span>
              <el-tag v-if="row.needs_manual" size="small" type="warning">待批</el-tag>
              <el-tag v-else-if="row.oj_verdict" size="small" :type="row.oj_verdict === 'AC' ? 'success' : 'danger'">OJ: {{ row.oj_verdict }}</el-tag>
              <el-tag v-else size="small" :type="row.is_correct ? 'success' : 'info'">{{ row.is_correct ? '正确' : '自动判分' }}</el-tag>
            </div>
            <pre class="stu-ans">{{ row.answer || '（未作答）' }}</pre>
            <div v-if="row.reference" class="ref">参考答案：{{ row.reference }}</div>
            <div class="score-row">
              <span>得分 / {{ row.max_score }}</span>
              <el-input-number v-model="row.manual_score" :min="0" :max="row.max_score" size="small"
                               controls-position="right" placeholder="人工分" />
              <el-input v-model="row.comment" size="small" placeholder="评语" style="flex: 1" />
              <el-button v-if="row.needs_manual" size="small" :loading="batchLoading"
                         @click="batchGrade(row)">批量给该题</el-button>
            </div>
          </div>
        </div>

        <!-- v5.15 评分量规 Rubric：逐维度打分（仅结构化拆解/建议，不改官方总分） -->
        <div v-if="grade.rubric" class="rubric-block">
          <div class="rubric-head">
            <span class="label" style="margin: 0">评分量规：{{ grade.rubric.title }}</span>
            <span class="rubric-sum">合计 <b>{{ rubricSum }}</b> / {{ grade.rubric.max_total }}</span>
            <el-button v-if="grade.homework.hw_type === 'open'" size="small" type="primary" plain
                       :disabled="!rubricTouched" @click="openScore = rubricSum">按量规合计填入建议分</el-button>
          </div>
          <div class="muted small rubric-tip">量规分仅供结构化拆解与建议，不影响官方总分与积分。</div>
          <div v-for="(dim, i) in grade.rubric.dimensions" :key="i" class="rubric-dim">
            <div class="rubric-dim-head">
              <span class="rubric-dim-label">{{ dim.label }}</span>
              <el-input-number v-model="rubricScores[i]" :min="0" :max="dim.max_score"
                               :step="1" size="small" controls-position="right" placeholder="0" />
              <span class="muted small">/ {{ dim.max_score }}</span>
            </div>
            <div v-if="dim.levels && dim.levels.length" class="rubric-levels">
              <span v-for="(lv, li) in dim.levels" :key="li" class="rubric-level">
                <b>{{ lv.score }}</b> {{ lv.desc }}
              </span>
            </div>
          </div>
        </div>

        <div class="label" style="margin-top: 14px">整体评语</div>
        <el-input v-model="overall" type="textarea" :rows="2" />

        <!-- v5.3 单份 AI 讲评 -->
        <div class="ai-review-head">
          <span class="label" style="margin: 0">AI 个性化讲评</span>
          <el-button size="small" :icon="MagicStick" :loading="personalLoading"
                     :disabled="grade.submission.status !== 'graded'"
                     @click="generatePersonalReview">
            {{ personalReview ? '重新生成' : '生成讲评' }}
          </el-button>
        </div>
        <AiReviewContent v-if="personalReview" :content="personalReview.content"
                         kind="submission" :degraded="personalReview.degraded"
                         class="personal-review" />
        <div v-else class="muted small">
          {{ grade.submission.status === 'graded'
            ? '可生成针对该学生的个性化讲评（不替代教师评语）'
            : '批改完成后可生成个性化讲评' }}
        </div>

        <!-- v5.5 同学互评（匿名） / v5.9 深度互评 -->
        <div v-if="grade.peer_review" class="peer-block">
          <div class="label" style="margin: 0">同学互评（匿名，仅作参考）</div>
          <div class="peer-line">
            均分 <b>{{ grade.peer_review.avg_score ?? '—' }}</b> / 100 · 共 {{ grade.peer_review.count }} 份
            <span v-if="grade.peer_review.accepted_count">
              · 采纳 {{ grade.peer_review.accepted_count }} 份，采纳均分
              <b>{{ grade.peer_review.accepted_avg_score ?? '—' }}</b>
            </span>
            <span v-if="grade.peer_review.rejected_count">
              · 已驳回 {{ grade.peer_review.rejected_count }} 份
            </span>
          </div>
          <div v-if="grade.peer_review.weighted_contribution != null" class="peer-weight-line">
            互评加权分 <b>+{{ grade.peer_review.weighted_contribution }}</b>
            （权重 {{ Math.round((grade.peer_review.weight || 0) * 100) }}%）
            · 总分视图 <b>{{ grade.peer_review.final_view_score }}</b>
            <span class="muted small">（不改写官方总分）</span>
          </div>
          <div v-for="(c, i) in grade.peer_review.comments" :key="i" class="peer-item">
            <span class="peer-score">{{ c.score }} 分</span>
            <el-tag v-if="c.audit_status === 'accepted'" size="small" type="success" effect="plain">
              已采纳
            </el-tag>
            <el-tag v-else-if="c.audit_status === 'rejected'" size="small" type="danger" effect="plain">
              已驳回
            </el-tag>
            {{ c.comment || '（无评语）' }}
          </div>
        </div>
      </div>
      <template #footer>
        <el-button v-if="grade && grade.homework.hw_type !== 'open'" :loading="aiLoading" @click="askAi">AI 建议</el-button>
        <el-button v-if="canReturn" :loading="returning" type="warning" plain @click="returnDialog = true">退回订正</el-button>
        <el-button type="primary" :loading="saving" @click="submitGrade">保存批改</el-button>
      </template>
    </el-drawer>

    <!-- v5.17 退回订正 -->
    <el-dialog v-model="returnDialog" title="退回订正" width="460px">
      <div class="muted small" style="margin-bottom: 8px">
        退回后该提交转为「待订正」，学生可见上次得分与本意见，并可重新提交（订正轮次 +1）。基础分/质量积分不重复发放。
      </div>
      <el-input v-model="returnReason" type="textarea" :rows="3" :maxlength="2000" show-word-limit
                placeholder="请填写退回原因 / 订正要求（将展示给学生）" />
      <template #footer>
        <el-button @click="returnDialog = false">取消</el-button>
        <el-button type="warning" :loading="returning" @click="returnRevision">确认退回</el-button>
      </template>
    </el-dialog>

    <!-- 班级 AI 讲评 -->
    <el-dialog v-model="classDialog" title="班级 AI 讲评" width="780px" top="6vh">
      <div v-if="classLoading" class="center">正在分析班级作答数据…</div>
      <template v-else-if="classReview">
        <div class="class-stats">
          <span>提交 <b>{{ classStats.submitted }}</b> / {{ classStats.total_students }} 人</span>
          <span v-if="classStats.avg_score != null">平均 <b>{{ classStats.avg_score }}</b> / {{ classStats.max_score }}</span>
          <span v-if="classStats.avg_ratio != null">平均得分率 <b>{{ Math.round(classStats.avg_ratio * 100) }}%</b></span>
          <span>已批改 {{ classStats.graded }} 份</span>
          <el-tag v-if="classReview.published" type="success" size="small">已发布给学生</el-tag>
          <el-tag v-else type="info" size="small">仅教师可见</el-tag>
        </div>
        <div v-if="classStats.weak_questions?.length" class="weak-list">
          <div class="weak-title">薄弱题目（平均得分率 &lt; 60%）</div>
          <div v-for="q in classStats.weak_questions" :key="q.question_id" class="weak-item">
            <span class="weak-q">{{ q.content }}</span>
            <span class="weak-ratio">{{ Math.round((q.avg_ratio || 0) * 100) }}%</span>
          </div>
        </div>
        <AiReviewContent :content="classReview.content" kind="class"
                         :degraded="classReview.degraded" />
      </template>
      <el-empty v-else description="还没有生成班级讲评，点击下方按钮开始分析" />
      <template #footer>
        <el-button :loading="classLoading" :icon="MagicStick" @click="generateClassReview">
          {{ classReview ? '重新生成' : '生成讲评' }}
        </el-button>
        <el-button v-if="classReview" :type="classReview.published ? 'warning' : 'success'"
                   :loading="publishing" @click="togglePublish">
          {{ classReview.published ? '撤回发布' : '发布给学生' }}
        </el-button>
        <el-button @click="classDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- v5.4 讨论区 -->
    <el-drawer v-model="discDialog" title="作业讨论区" size="560px">
      <HomeworkDiscussion :homework-id="hwId" can-moderate />
    </el-drawer>

    <!-- v5.5 生生互评管理 -->
    <el-dialog v-model="peerDialog" title="生生互评管理" width="920px" top="5vh">
      <div class="peer-settings">
        <div class="setting-item">
          <span class="label">互评截止时间</span>
          <el-date-picker v-model="peerDeadline" type="datetime" clearable
                          value-format="YYYY-MM-DDTHH:mm:ss" placeholder="不设截止"
                          style="width: 200px" size="small" />
        </div>
        <div class="setting-item">
          <span class="label">互评分权重</span>
          <el-input-number v-model="peerWeightPercent" :min="0" :max="100" :step="5"
                           size="small" />
          <span class="muted small">%（0=仅参考，不计入总分视图）</span>
        </div>
        <el-button type="primary" size="small" :loading="peerSaving" @click="savePeerSettings">
          保存设置
        </el-button>
      </div>
      <div class="peer-toolbar">
        <span class="label" style="margin: 0">每份作业分配互评人数</span>
        <el-input-number v-model="peerPer" :min="1" :max="5" size="small" />
        <el-button type="primary" size="small" :loading="peerDistributing" @click="distributePeer">
          生成 / 重新分配
        </el-button>
        <span class="muted small">重新分配会清空未完成的任务，已提交的互评保留</span>
      </div>
      <div v-if="peerSummary" class="peer-stats">
        <span>互评任务 <b>{{ peerSummary.total }}</b></span>
        <span>已完成 <b>{{ peerSummary.submitted }}</b></span>
        <span>完成率 <b>{{ peerSummary.completion_rate }}%</b></span>
        <span>已采纳 <b>{{ peerSummary.accepted }}</b></span>
        <span>已驳回 <b>{{ peerSummary.rejected }}</b></span>
        <span>待审核 <b>{{ peerSummary.pending_audit }}</b></span>
        <span v-if="peerSummary.deadline">截止 {{ fmt(peerSummary.deadline) }}</span>
      </div>
      <el-table :data="peerSummary?.per_submission || []" size="small" max-height="240" stripe>
        <el-table-column prop="username" label="学生" width="130" />
        <el-table-column label="互评进度" width="100">
          <template #default="{ row }">{{ row.submitted_count }} / {{ row.review_count }}</template>
        </el-table-column>
        <el-table-column label="互评均分" width="100">
          <template #default="{ row }">{{ row.avg_score ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="采纳均分" width="100">
          <template #default="{ row }">{{ row.accepted_avg_score ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="互评加权分" width="110">
          <template #default="{ row }">{{ row.peer_weighted_score ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="提交状态" width="90">
          <template #default="{ row }">{{ statusText(row.submission_status) }}</template>
        </el-table-column>
      </el-table>
      <div class="label" style="margin-top: 14px">评审人进度</div>
      <el-table :data="peerSummary?.reviewers || []" size="small" max-height="180" stripe>
        <el-table-column prop="username" label="学生" width="130" />
        <el-table-column prop="assigned" label="分配" width="70" />
        <el-table-column prop="submitted" label="完成" width="70" />
        <el-table-column prop="pending" label="待完成" width="80" />
        <el-table-column prop="accepted" label="被采纳" width="80" />
        <el-table-column prop="rejected" label="被驳回" />
      </el-table>

      <div class="label" style="margin-top: 14px">互评审核（采纳后计入加权分）</div>
      <el-table :data="peerSummary?.reviews || []" size="small" max-height="240" stripe>
        <el-table-column prop="student_name" label="被评学生" width="120" />
        <el-table-column prop="reviewer_name" label="评审人" width="120" />
        <el-table-column label="维度分" min-width="200">
          <template #default="{ row }">
            <span class="muted small">{{ dimsText(row.scores) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="加权总分" width="95">
          <template #default="{ row }">{{ row.score ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="审核" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="auditTag(row.audit_status)">
              {{ auditText(row.audit_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="success" size="small" :disabled="row.audit_status === 'accepted'"
                       @click="auditPeer(row, 'accept')">采纳</el-button>
            <el-button link type="danger" size="small" :disabled="row.audit_status === 'rejected'"
                       @click="auditPeer(row, 'reject')">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="peerDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- v5.6 作业反抄袭 -->
    <el-dialog v-model="plagDialog" title="作业查重（相似对）" width="720px" top="6vh">
      <div class="plag-toolbar">
        <span class="hint">阈值</span>
        <el-input-number v-model="plagThreshold" :min="0.1" :max="1" :step="0.05" :precision="2" size="small" controls-position="right" style="width: 120px" />
        <el-button size="small" type="primary" :loading="plagLoading" @click="loadPlagiarism">重新检测</el-button>
        <span class="hint">扫描 {{ plagResult.scanned || 0 }} 份，高相似对 {{ plagResult.pair_count || 0 }}</span>
      </div>
      <el-empty v-if="!plagLoading && plagResult.pair_count === 0" description="未发现高相似提交对" />
      <div v-else class="plag-items">
        <div v-for="(item, idx) in plagResult.items" :key="idx" class="plag-item">
          <div class="plag-item-head">
            <el-tag size="small" type="warning">{{ item.hw_type === 'open' ? '开放式正文' : item.question_content }}</el-tag>
          </div>
          <div v-for="(p, pi) in item.pairs" :key="pi" class="plag-pair">
            <span class="plag-user">{{ p.a.username }}</span>
            <el-icon><Right /></el-icon>
            <span class="plag-user">{{ p.b.username }}</span>
            <el-progress :percentage="Math.round(p.similarity * 100)" :stroke-width="10" style="width: 180px; margin: 0 10px" :color="'#f56c6c'" />
            <el-tag size="small" :type="p.similarity >= 0.9 ? 'danger' : 'warning'">{{ (p.similarity * 100).toFixed(1) }}%</el-tag>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="plagDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { EditPen, Back, MagicStick, ChatDotRound, UserFilled, DocumentCopy, Right } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import AiReviewContent from '../components/AiReviewContent.vue'
import HomeworkDiscussion from '../components/HomeworkDiscussion.vue'

const route = useRoute()
const hwId = route.params.id
const hw = ref({})
const items = ref([])
const notSubmitted = ref([])
const studentCount = ref(0)
const drawer = ref(false)
const loading = ref(false)
const saving = ref(false)
const aiLoading = ref(false)
const batchLoading = ref(false)
const blindGrade = ref(false)
const grade = ref(null)
const rows = ref([])          // 题集式：答案与题面合并视图
const current = ref(null)
const overall = ref('')
const openScore = ref(0)
const openMax = ref(100)
// v5.15 评分量规：逐维度得分（按维度索引），仅建议/拆解，不改官方总分
const rubricScores = ref({})
// v5.3 AI 讲评
const classDialog = ref(false)
const classLoading = ref(false)
const classReview = ref(null)
const publishing = ref(false)
const personalReview = ref(null)
const personalLoading = ref(false)
const classStats = computed(() => classReview.value?.stats || {})
// v5.4 讨论区 / v5.5 生生互评
const discDialog = ref(false)
const peerDialog = ref(false)
const peerDistributing = ref(false)
const peerPer = ref(2)
const peerSummary = ref(null)
const peerDeadline = ref(null)
const peerWeightPercent = ref(0)
const peerSaving = ref(false)
// v5.6 反抄袭
const plagDialog = ref(false)
const plagLoading = ref(false)
const plagThreshold = ref(0.7)
const plagResult = ref({ scanned: 0, pair_count: 0, items: [] })

const fmt = (v) => (v || '').slice(0, 16).replace('T', ' ')
const statusText = (s) => ({ submitted: '待批改', graded: '已批改', returned: '待订正' }[s] || s)
const auditText = (s) => ({ accepted: '已采纳', rejected: '已驳回' }[s] || '待审核')
const auditTag = (s) => ({ accepted: 'success', rejected: 'danger' }[s] || 'info')
const dimsText = (scores) => {
  if (!scores || !Object.keys(scores).length) return '—'
  const labels = { accuracy: '准确', completeness: '完整', standard: '规范', innovation: '创造' }
  return Object.entries(scores).map(([k, v]) => `${labels[k] || k} ${v}`).join(' · ')
}
const statusTag = (s) => ({ submitted: 'warning', graded: 'success', returned: 'info' }[s] || 'info')
// v5.17 退回订正：仅已批改且作业开启订正重做时可退回
const returnDialog = ref(false)
const returnReason = ref('')
const returning = ref(false)
const canReturn = computed(() => !!grade.value
  && grade.value.submission?.status === 'graded' && !!hw.value.allow_revision)
const rubricSum = computed(() => Object.values(rubricScores.value)
  .reduce((s, v) => s + (Number(v) || 0), 0))
const rubricTouched = computed(() => Object.values(rubricScores.value).some(v => Number(v) > 0))
const typeName = (t) => ({ single_choice: '单选', multiple_choice: '多选', true_false: '判断',
  fill_blank: '填空', programming: '编程', short_answer: '简答', essay: '论述' }[t] || t)

const load = async () => {
  const [detail, subs] = await Promise.all([
    request.get(`/api/homeworks/${hwId}`),
    request.get(`/api/homeworks/${hwId}/submissions`)
  ])
  hw.value = detail.data
  items.value = subs.data.items || []
  notSubmitted.value = subs.data.not_submitted || []
  studentCount.value = subs.data.student_count || 0
  blindGrade.value = !!subs.data.blind
}

const openGrade = async (row) => {
  current.value = row
  drawer.value = true
  loading.value = true
  grade.value = null
  rows.value = []
  personalReview.value = null
  try {
    const res = await request.get(`/api/homeworks/${hwId}/grade/${row.id}`)
    grade.value = res.data
    overall.value = res.data.submission.comment || ''
    openScore.value = res.data.submission.total_score || 0
    openMax.value = res.data.submission.max_score || 100
    personalReview.value = res.data.ai_review || null
    // v5.15 回填量规维度分快照 [{index,label,score}] -> {index:score}
    const rs = {}
    ;(res.data.submission.rubric_scores || []).forEach(x => {
      if (x && x.index != null) rs[x.index] = x.score
    })
    rubricScores.value = rs
    // 题面元数据（content/type/answer）在 questions 里，按 question_id 合并到逐题行
    const qmap = {}
    ;(res.data.questions || []).forEach(q => { qmap[q.question_id] = q })
    rows.value = (res.data.answers || []).map(a => ({
      id: a.id, question_id: a.question_id, type: qmap[a.question_id]?.type,
      content: qmap[a.question_id]?.content || '', reference: qmap[a.question_id]?.answer || '',
      max_score: a.max_score ?? qmap[a.question_id]?.score ?? 100,
      answer: a.answer, is_correct: a.is_correct, oj_verdict: a.oj_verdict,
      needs_manual: a.needs_manual_grade, auto_score: a.auto_score,
      manual_score: a.manual_score, comment: a.comment || ''
    }))
  } finally {
    loading.value = false
  }
}

const attachUrl = (subId) => `/api/homeworks/${hwId}/attachment?submission_id=${subId}`

const askAi = async () => {
  aiLoading.value = true
  try {
    const res = await request.post(`/api/homeworks/${hwId}/grade/${current.value.id}/ai_suggest`)
    const sg = res.data.suggestions || []
    sg.forEach(s => {
      const r = rows.value.find(x => x.id === s.answer_id)
      if (r && r.needs_manual) { r.manual_score = s.score; if (!r.comment) r.comment = s.comment }
    })
    ElMessage.success(sg.length ? `AI 已给出 ${sg.length} 题建议` : '无待批题目')
  } finally {
    aiLoading.value = false
  }
}

const batchGrade = async (row) => {
  if (row.manual_score == null || row.manual_score === '') {
    return ElMessage.warning('请先给该题填写分数')
  }
  try {
    await ElMessageBox.confirm(
      `把该题 ${row.manual_score} 分${row.comment ? '及评语' : ''}批量套用到本作业所有待批此题的提交？`,
      '同题批量给分', { type: 'warning' })
  } catch { return }
  batchLoading.value = true
  try {
    const body = { question_id: row.question_id, score: row.manual_score }
    if (row.comment) body.comment = row.comment
    const res = await request.post(`/api/homeworks/${hwId}/grade/batch`, body)
    ElMessage.success(res.data.message || '批量给分完成')
    drawer.value = false
    load()
  } finally {
    batchLoading.value = false
  }
}

const openClassReview = async () => {
  classDialog.value = true
  if (classReview.value) return
  classLoading.value = true
  try {
    const res = await request.get(`/api/homeworks/${hwId}/ai_review`)
    classReview.value = res.data.review || null
  } finally {
    classLoading.value = false
  }
}

const generateClassReview = async () => {
  classLoading.value = true
  try {
    const res = await request.post(`/api/homeworks/${hwId}/ai_review`)
    classReview.value = res.data.review
    ElMessage.success(res.data.message || '班级讲评已生成')
  } finally {
    classLoading.value = false
  }
}

const togglePublish = async () => {
  publishing.value = true
  try {
    const res = await request.post(`/api/homeworks/${hwId}/ai_review/publish`,
      { published: !classReview.value.published })
    classReview.value = res.data.review
    ElMessage.success(res.data.message)
  } finally {
    publishing.value = false
  }
}

const generatePersonalReview = async () => {
  personalLoading.value = true
  try {
    const res = await request.post(
      `/api/homeworks/${hwId}/grade/${current.value.id}/ai_review`)
    personalReview.value = res.data.review
    ElMessage.success(res.data.message || '个性化讲评已生成')
  } finally {
    personalLoading.value = false
  }
}

const applyPeerSettings = () => {
  peerDeadline.value = peerSummary.value?.deadline || null
  peerWeightPercent.value = Math.round((peerSummary.value?.weight || 0) * 100)
}

const openPeer = async () => {
  peerDialog.value = true
  const res = await request.get(`/api/homeworks/${hwId}/peer_reviews`)
  peerSummary.value = res.data
  applyPeerSettings()
}

const savePeerSettings = async () => {
  peerSaving.value = true
  try {
    const res = await request.put(`/api/homeworks/${hwId}/peer_reviews/settings`, {
      deadline: peerDeadline.value || null,
      weight: (peerWeightPercent.value || 0) / 100
    })
    peerSummary.value = res.data.summary
    applyPeerSettings()
    ElMessage.success(res.data.message)
  } finally {
    peerSaving.value = false
  }
}

const auditPeer = async (row, action) => {
  let comment = ''
  if (action === 'reject') {
    const r = await ElMessageBox.prompt('请填写驳回原因（将通知评审人）', '驳回互评', {
      inputType: 'textarea', confirmButtonText: '确认驳回', cancelButtonText: '取消',
      inputPlaceholder: '如：评分明显偏离标准，请说明原因'
    }).catch(() => null)
    if (!r) return
    comment = r.value || ''
  } else {
    const ok = await ElMessageBox.confirm('采纳后该互评分将按权重计入「互评加权分」，是否继续？',
      '采纳互评', { type: 'warning', confirmButtonText: '采纳' }).catch(() => false)
    if (!ok) return
  }
  const res = await request.post(
    `/api/homeworks/${hwId}/peer_reviews/${row.id}/audit`, { action, comment })
  peerSummary.value = res.data.summary
  applyPeerSettings()
  ElMessage.success(res.data.message)
}

const distributePeer = async () => {
  peerDistributing.value = true
  try {
    const res = await request.post(`/api/homeworks/${hwId}/peer_reviews/distribute`,
      { per_submission: peerPer.value })
    peerSummary.value = res.data.summary
    ElMessage.success(res.data.message)
  } finally {
    peerDistributing.value = false
  }
}

const openPlagiarism = async () => {
  plagDialog.value = true
  await loadPlagiarism()
}

const loadPlagiarism = async () => {
  plagLoading.value = true
  try {
    const res = await request.get(`/api/homeworks/${hwId}/plagiarism`,
      { params: { threshold: plagThreshold.value } })
    plagResult.value = res.data
  } finally {
    plagLoading.value = false
  }
}

// v5.17 退回订正：将当前已批提交退回供学生重做（账务不二次发分）
const returnRevision = async () => {
  returning.value = true
  try {
    const res = await request.post(
      `/api/homeworks/${hwId}/grade/${current.value.id}/return`,
      { reason: returnReason.value || '' })
    ElMessage.success(res.data.message || '已退回订正')
    returnDialog.value = false
    returnReason.value = ''
    drawer.value = false
    load()
  } finally {
    returning.value = false
  }
}

const submitGrade = async () => {
  saving.value = true
  try {
    let payload
    if (grade.value.homework.hw_type === 'open') {
      payload = { comment: overall.value, score: openScore.value, max_score: openMax.value }
    } else {
      payload = {
        comment: overall.value,
        answers: rows.value
          .filter(r => r.needs_manual && (r.manual_score != null || r.comment))
          .map(r => ({ answer_id: r.id, score: r.manual_score, comment: r.comment }))
      }
    }
    // v5.15 关联量规时随批改提交逐维度快照（后端仅落库不改总分）
    if (grade.value.rubric) {
      payload.rubric_scores = grade.value.rubric.dimensions
        .map((d, i) => ({ index: i, label: d.label, score: Number(rubricScores.value[i]) || 0 }))
    }
    const res = await request.post(`/api/homeworks/${hwId}/grade/${current.value.id}`, payload)
    ElMessage.success(res.data.message || '已保存')
    drawer.value = false
    load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.summary { margin-bottom: 12px; color: #606266; font-size: 14px; }
.not-sub { color: #f56c6c; }
.muted { color: #909399; }
.center { text-align: center; padding: 40px; color: #909399; }
.answer-block { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; margin-bottom: 12px; }
.answer-block.pending { border-color: #e6a23c; }
.q-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.q-type { font-size: 12px; color: #909399; }
.q-content { flex: 1; font-weight: 500; }
.stu-ans { background: #f5f7fa; padding: 8px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; margin: 0 0 8px; max-height: 160px; overflow: auto; }
.ref { font-size: 12px; color: #67c23a; margin-bottom: 6px; }
.score-row { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #606266; }
.content-box { background: #f5f7fa; padding: 12px; border-radius: 4px; white-space: pre-wrap; max-height: 240px; overflow: auto; }
.label { font-weight: 500; margin-bottom: 6px; }
.attach { margin: 8px 0; }
.muted { color: #909399; }
.small { font-size: 12px; line-height: 1.6; }
.ai-review-head {
  display: flex; align-items: center; justify-content: space-between;
  margin: 16px 0 8px; padding-top: 14px; border-top: 1px dashed #ebeef5;
}
.personal-review { margin-top: 8px; }
.peer-block { margin-top: 16px; padding-top: 14px; border-top: 1px dashed #ebeef5; }
.peer-line { font-size: 13px; color: #606266; margin: 4px 0 8px; }
.peer-line b { color: #f59e0b; font-size: 16px; }
.peer-item { font-size: 13px; color: #4b5563; background: #fffbeb; border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; line-height: 1.5; }
.peer-score { color: #d97706; font-weight: 600; margin-right: 6px; }
.peer-settings { display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 10px 14px; margin-bottom: 10px; border-radius: 10px; border: 1px dashed #dbeafe;
  background: #f8faff; }
.setting-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #4b5563; }
.peer-weight-line { font-size: 13px; color: #4f46e5; background: #eef2ff;
  border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }
.peer-weight-line b { color: #4338ca; }
.peer-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.peer-stats {
  display: flex; flex-wrap: wrap; gap: 16px; align-items: center;
  padding: 10px 14px; margin-bottom: 12px; border-radius: 10px; font-size: 13px; color: #606266;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.08), rgba(139, 92, 246, 0.05));
}
.peer-stats b { color: #d97706; font-size: 15px; }
.class-stats {
  display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
  padding: 10px 14px; margin-bottom: 12px; border-radius: 10px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(139, 92, 246, 0.05));
  color: #606266; font-size: 13px;
}
.class-stats b { color: #4f46e5; font-size: 15px; }
.weak-list {
  margin-bottom: 14px; padding: 10px 14px; border-radius: 10px;
  background: rgba(245, 108, 108, 0.05); border: 1px solid rgba(245, 108, 108, 0.14);
}
.weak-title { font-size: 13px; font-weight: 600; color: #b91c1c; margin-bottom: 8px; }
.weak-item { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; padding: 4px 0; color: #606266; }
.weak-q { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.weak-ratio { flex-shrink: 0; font-weight: 600; color: #f56c6c; }
.plag-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.plag-items { display: flex; flex-direction: column; gap: 14px; }
.plag-item { padding: 12px 14px; border-radius: 10px; background: rgba(245, 108, 108, 0.04); border: 1px solid rgba(245, 108, 108, 0.14); }
.plag-item-head { margin-bottom: 8px; }
.plag-pair { display: flex; align-items: center; gap: 6px; padding: 4px 0; font-size: 13px; }
.plag-user { font-weight: 600; color: #303133; min-width: 70px; }
:deep(.el-table__row) { cursor: pointer; }
.rubric-block { margin-top: 16px; padding: 12px 14px; border-radius: 10px;
  border: 1px solid #e0e7ff; background: #f8faff; }
.rubric-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.rubric-sum { font-size: 13px; color: #4f46e5; }
.rubric-sum b { font-size: 16px; color: #4338ca; }
.rubric-tip { margin: 4px 0 10px; }
.rubric-dim { padding: 8px 0; border-top: 1px dashed #e5e7eb; }
.rubric-dim-head { display: flex; align-items: center; gap: 10px; }
.rubric-dim-label { font-weight: 500; color: #374151; min-width: 72px; }
.rubric-levels { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 6px; padding-left: 4px; }
.rubric-level { font-size: 12px; color: #6b7280; }
.rubric-level b { color: #6366f1; margin-right: 4px; }
</style>
