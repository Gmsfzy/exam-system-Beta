<template>
  <div class="page-wrapper" v-loading="loading">
    <template v-if="comp">
      <div class="page-header">
        <div class="header-title">
          <h2>
            <el-icon :size="24" class="trophy"><Trophy /></el-icon>
            {{ comp.title }}
            <el-tag :type="statusTag(comp.status)" effect="dark" size="small">{{ statusLabel(comp.status) }}</el-tag>
            <el-tag size="small" type="primary" effect="plain">数据赛</el-tag>
            <el-tag v-if="config.metric_label" size="small" type="warning" effect="plain">指标：{{ config.metric_label }}</el-tag>
            <el-tag v-if="comp.prize_points" size="small" type="danger" effect="plain">冠军 {{ comp.prize_points }} 积分</el-tag>
          </h2>
          <p><span class="sub-info">截止：{{ fmtTime(comp.end_time) }} · {{ comp.participant_count }} 人参与 · 每日限 {{ config.daily_limit || 5 }} 次提交<template v-if="comp.description"> · {{ comp.description }}</template></span></p>
        </div>
        <div class="header-actions">
          <el-button :icon="Back" @click="$router.push('/competitions')">返回广场</el-button>
          <el-button v-if="canJoin" type="primary" @click="join">报名参赛</el-button>
        </div>
      </div>

      <el-alert v-if="!joined && comp.status !== 'ended'" type="info" :closable="false" show-icon class="join-tip"
                title="报名后即可下载数据、在线编写运行并提交预测，平台按隐藏答案自动评分（公榜实时、私榜结束公布）。" />

      <el-row :gutter="18" class="body-row">
        <el-col :span="16">
          <!-- 在线编写运行 -->
          <div class="panel">
            <h3>🧪 在线工作台</h3>
            <p class="tip">约定：读取 <code>train.csv</code> 等公开数据，把预测写回 <code>submission.csv</code>（<code>df.to_csv('submission.csv', index=False)</code>），仅可用 numpy / pandas。</p>
            <CodeEditor v-model="code" height="340px" :readonly="!joined || comp.status === 'ended'" />
            <div class="run-bar">
              <el-button type="primary" :loading="running" :disabled="!joined || comp.status === 'ended'" @click="runCode">▶ 运行</el-button>
              <el-button type="success" :disabled="!lastRun || !lastRun.has_submission || comp.status !== 'ongoing'" @click="submitFromRun">用运行结果提交</el-button>
              <el-button :disabled="comp.status !== 'ongoing'" @click="$refs.subFile.click()">上传 prediction.csv 提交</el-button>
              <input ref="subFile" type="file" accept=".csv" style="display:none" @change="onPickSubmission" />
            </div>
            <div v-if="runResult" class="console">
              <div class="console-head">
                <el-tag size="small" :type="runResult.status === 'ok' ? 'success' : (runResult.status === 'rejected' ? 'danger' : 'warning')">
                  {{ runStatusText }}
                </el-tag>
                <span v-if="runResult.exit_code !== null && runResult.exit_code !== undefined" class="codelab">退出码 {{ runResult.exit_code }}</span>
              </div>
              <pre v-if="runResult.stdout" class="out">{{ runResult.stdout }}</pre>
              <pre v-if="runResult.stderr" class="err">{{ runResult.stderr }}</pre>
              <div v-if="runResult.error" class="err">{{ runResult.error }}</div>
              <div v-if="runResult.has_submission" class="prod">
                <b>产出 submission.csv 预览：</b>
                <pre class="out">{{ runResult.submission_preview }}</pre>
              </div>
            </div>
          </div>

          <!-- 我的提交 -->
          <div class="panel">
            <h3>📈 我的提交</h3>
            <el-empty v-if="!mySubs.length" description="还没有提交记录" :image-size="50" />
            <el-table v-else :data="mySubs" size="small" max-height="320">
              <el-table-column label="#" width="52"><template #default="{ row }">v{{ row.version }}</template></el-table-column>
              <el-table-column prop="kind" label="来源" width="80"><template #default="{ row }">{{ row.kind === 'notebook' ? '在线' : '文件' }}</template></el-table-column>
              <el-table-column label="公榜分" width="100"><template #default="{ row }">{{ row.public_score != null ? row.public_score : '—' }}</template></el-table-column>
              <el-table-column label="状态" width="90"><template #default="{ row }">
                <el-tag size="small" :type="row.status === 'scored' ? 'success' : (row.status === 'error' ? 'danger' : 'info')">{{ row.status }}</el-tag>
              </template></el-table-column>
              <el-table-column prop="created_at" label="时间" min-width="140"><template #default="{ row }">{{ fmtTime(row.created_at) }}</template></el-table-column>
              <el-table-column label="备注" min-width="120"><template #default="{ row }"><span class="err-inline">{{ row.error_msg }}</span></template></el-table-column>
            </el-table>
          </div>
        </el-col>

        <el-col :span="8">
          <!-- 数据集 -->
          <div class="panel">
            <h3>📁 数据集</h3>
            <el-empty v-if="!files.length" description="教师尚未上传数据" :image-size="50" />
            <div v-for="f in files" :key="f.id" class="res-item">
              <div class="res-info">
                <span class="res-title">{{ f.filename }}</span>
                <span class="ann-meta">{{ roleLabel(f.role) }} · {{ fmtSize(f.size) }}</span>
              </div>
              <el-button size="small" text type="primary" :disabled="!f.is_downloadable || (!isTeacher && !joined)" @click="downloadFile(f)">下载</el-button>
            </div>
          </div>

          <!-- 公榜 -->
          <div class="panel">
            <h3>🏅 公开排行榜</h3>
            <el-empty v-if="!board.length" description="暂无排名" :image-size="50" />
            <el-table v-else :data="board" size="small" max-height="320">
              <el-table-column prop="rank" label="#" width="46" />
              <el-table-column prop="username" label="选手" show-overflow-tooltip />
              <el-table-column label="公榜分" width="90"><template #default="{ row }">{{ row.public_score }}</template></el-table-column>
            </el-table>
          </div>
        </el-col>
      </el-row>
    </template>

    <el-empty v-else-if="!loading" description="竞赛不存在或未对你开放">
      <el-button type="primary" @click="$router.push('/competitions')">返回竞赛广场</el-button>
    </el-empty>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import { Trophy, Back } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import CodeEditor from '../components/CodeEditor.vue'

const route = useRoute()
const auth = useAuthStore()
const compId = route.params.compId

const loading = ref(true)
const comp = ref(null)
const config = reactive({})
const files = ref([])
const mySubs = ref([])
const board = ref([])
const code = ref("# 读取训练集，训练你的模型，再把测试预测写入 submission.csv\nimport pandas as pd\n\ndf = pd.read_csv('train.csv')\nprint(df.head())\n")
const running = ref(false)
const runResult = ref(null)
const lastRun = ref(null)

const isTeacher = computed(() => auth.user?.role === 'teacher')
const joined = computed(() => !!comp.value?.my_status)
const canJoin = computed(() => !isTeacher.value && !joined.value && ['published', 'ongoing'].includes(comp.value?.status))

const statusLabel = (s) => ({ published: '未开始', ongoing: '进行中', ended: '已结束' }[s] || s)
const statusTag = (s) => ({ published: 'primary', ongoing: 'success', ended: 'danger' }[s] || 'info')
const roleLabel = (r) => ({ train: '训练集', test: '测试集', sample: '样例', gold: '隐藏答案' }[r] || r)
const fmtTime = (iso) => iso ? new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
const fmtSize = (n) => !n ? '0B' : (n < 1048576 ? (n / 1024).toFixed(1) + 'KB' : (n / 1048576).toFixed(1) + 'MB')
const runStatusText = computed(() => {
  const r = runResult.value
  if (!r) return ''
  if (r.timed_out) return '运行超时'
  return { ok: '运行成功', rejected: '代码被拒绝', error: '运行错误' }[r.status] || r.status
})

const load = async () => {
  loading.value = true
  try {
    if (isTeacher.value) {
      comp.value = (await request.get(`/api/competitions/${compId}`)).data
    } else {
      const res = await request.get('/api/competitions/lobby')
      comp.value = (res.data || []).find(c => String(c.id) === String(compId)) || null
    }
    if (!comp.value) return
    const [cfg, ds, subs, lb] = await Promise.all([
      request.get(`/api/ds/competitions/${compId}/config`).catch(() => ({ data: { config: {} } })),
      request.get(`/api/ds/competitions/${compId}/datasets`).catch(() => ({ data: { items: [] } })),
      isTeacher.value ? Promise.resolve({ data: { items: [] } })
                      : request.get(`/api/ds/competitions/${compId}/my-submissions`).catch(() => ({ data: { items: [] } })),
      request.get(`/api/ds/competitions/${compId}/leaderboard?scope=public`).catch(() => ({ data: { items: [] } })),
    ])
    Object.assign(config, cfg.data.config || {})
    files.value = ds.data.items || []
    mySubs.value = subs.data.items || []
    board.value = lb.data.items || []
  } catch (e) {
    comp.value = null
  } finally {
    loading.value = false
  }
}

const join = async () => {
  await request.post(`/api/competitions/${compId}/join`)
  ElMessage.success('报名成功，即可运行与提交')
  load()
}

const runCode = async () => {
  running.value = true
  try {
    const res = await request.post(`/api/ds/competitions/${compId}/notebook/run`, { code: code.value })
    runResult.value = res.data
    if (res.data.status === 'ok' && res.data.has_submission) {
      lastRun.value = res.data
      lastRun.value.run_id = res.data.run_id
    } else {
      lastRun.value = null
    }
  } finally {
    running.value = false
  }
}

const submitFromRun = async () => {
  if (!lastRun.value?.run_id) return ElMessage.warning('请先运行并产出 submission.csv')
  const res = await request.post(`/api/ds/competitions/${compId}/submit`, { from_run_id: lastRun.value.run_id })
  afterSubmit(res)
}

const onPickSubmission = async (e) => {
  const f = e.target.files?.[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  const res = await request.post(`/api/ds/competitions/${compId}/submit`, fd)
  afterSubmit(res)
  e.target.value = ''
}

const afterSubmit = (res) => {
  const sub = res.data.submission
  if (sub && sub.status === 'scored') {
    ElMessage.success(`提交成功，公榜分 ${sub.public_score}`)
  } else {
    ElMessage.warning(res.data.message || '提交未通过评分')
  }
  load()
}

const downloadFile = async (f) => {
  const res = await request.get(`/api/ds/files/${f.id}/download`, { responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(res.data)
  link.download = f.filename
  link.click()
  URL.revokeObjectURL(link.href)
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { max-width: 1240px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; flex-wrap: wrap; gap: 12px; }
.header-title h2 { font-size: 22px; font-weight: 700; color: var(--text-primary); margin: 0 0 8px 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.trophy { color: #d97706; }
.header-title p { font-size: 13.5px; color: var(--text-muted); margin: 0; }
.sub-info { color: var(--text-muted); }
.join-tip { margin-bottom: 16px; }
.panel { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 14px; padding: 18px 20px; margin-bottom: 16px; }
.panel h3 { font-size: 15.5px; font-weight: 700; color: var(--text-primary); margin: 0 0 14px; }
.tip { font-size: 12.5px; color: var(--text-muted); margin: 0 0 10px; }
.tip code { background: rgba(0,0,0,.06); padding: 1px 5px; border-radius: 4px; }
.run-bar { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.console { margin-top: 14px; border: 1px solid var(--border-color); border-radius: 10px; padding: 12px 14px; background: rgba(0,0,0,.02); }
.console-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.codelab { font-size: 12px; color: var(--text-muted); }
.console pre { margin: 0; max-height: 220px; overflow: auto; font-family: Consolas, Menlo, monospace; font-size: 12.5px; white-space: pre-wrap; word-break: break-all; }
.console .out { color: var(--text-primary); }
.console .err { color: #dc2626; }
.prod { margin-top: 10px; }
.res-item { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border-color); }
.res-item:last-child { border-bottom: none; }
.res-info { min-width: 0; }
.res-title { display: block; font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.ann-meta { font-size: 12px; color: var(--text-muted); }
.err-inline { color: #dc2626; font-size: 12px; }
</style>
