<template>
  <div class="page-wrapper" v-loading="loading">
    <div class="page-header" v-if="comp">
      <div class="header-title">
        <h2>
          <el-icon :size="24" class="trophy"><Trophy /></el-icon>
          {{ comp.title }}
          <el-tag :type="statusTag(comp.status)" effect="dark" size="small">{{ statusLabel(comp.status) }}</el-tag>
          <el-tag size="small" type="primary" effect="plain">数据赛管理</el-tag>
        </h2>
        <p><span class="sub-info">开放：{{ fmtTime(comp.start_time) }} ~ {{ fmtTime(comp.end_time) }} · {{ comp.participant_count }} 人参与</span></p>
      </div>
      <div class="header-actions">
        <el-button :icon="Back" @click="$router.push('/competitions')">竞赛管理</el-button>
      </div>
    </div>

    <el-row :gutter="18" class="body-row">
      <el-col :span="12">
        <!-- 评分配置 -->
        <div class="panel">
          <h3>⚙️ 评分配置</h3>
          <el-form label-width="96px" :disabled="!editable">
            <el-form-item label="评分指标">
              <el-select v-model="form.metric" style="width: 200px">
                <el-option v-for="m in METRICS" :key="m.value" :label="`${m.label}（${m.value}）`" :value="m.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="主键列">
              <el-input v-model="form.id_column" placeholder="如 id / passengerId" style="width: 200px" maxlength="50" />
            </el-form-item>
            <el-form-item label="目标列">
              <el-input v-model="form.target_column" placeholder="如 label / survived" style="width: 200px" maxlength="50" />
            </el-form-item>
            <el-form-item label="公榜比例">
              <el-input-number v-model="form.public_ratio" :min="0.1" :max="0.9" :step="0.1" :precision="2" />
              <span class="form-tip">实时公开榜所占隐藏答案比例，其余结算时才可见</span>
            </el-form-item>
            <el-form-item label="每日限次">
              <el-input-number v-model="form.daily_limit" :min="1" :max="100" />
            </el-form-item>
            <template v-if="form.metric === 'custom'">
              <el-form-item label="越大越好">
                <el-switch v-model="form.higher_is_better" />
              </el-form-item>
              <el-form-item label="评分脚本">
                <CodeEditor v-model="form.scorer_code" height="240px" />
              </el-form-item>
              <div class="scorer-tip">约定定义 <code>def score(gold, pred): return float</code>；gold/pred 为 pandas DataFrame，仅可用 numpy / pandas。</div>
            </template>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="!editable" type="info" :closable="false" show-icon
                    title="竞赛已开始（进行中/已结束），评分配置已锁定以保证公平。" />
        </div>

        <!-- 数据集 -->
        <div class="panel">
          <h3>📁 数据集</h3>
          <div class="upload-row">
            <span>上传 CSV：</span>
            <el-select v-model="uploadRole" style="width: 120px">
              <el-option value="train" label="训练集" />
              <el-option value="test" label="测试集" />
              <el-option value="sample" label="样例" />
              <el-option value="gold" label="隐藏答案" />
            </el-select>
            <input ref="dataFile" type="file" accept=".csv" style="display:none" @change="onUpload" />
            <el-button type="primary" plain @click="$refs.dataFile.click()">选择并上传</el-button>
          </div>
          <el-table :data="files" size="small" max-height="280">
            <el-table-column label="角色" width="96"><template #default="{ row }">
              <el-tag size="small" :type="row.role === 'gold' ? 'danger' : 'info'">{{ roleLabel(row.role) }}</el-tag>
            </template></el-table-column>
            <el-table-column prop="filename" label="文件" show-overflow-tooltip />
            <el-table-column label="大小" width="86"><template #default="{ row }">{{ fmtSize(row.size) }}</template></el-table-column>
            <el-table-column label="操作" width="80" align="center">
              <template #default="{ row }"><el-button size="small" text type="danger" @click="delFile(row)">删除</el-button></template>
            </el-table-column>
          </el-table>
          <p class="form-tip gold-tip">隐藏答案（gold）仅评分器可读，任何下载请求都会被拒绝；含 <b>目标列真值</b>，列名需与「目标列」一致。</p>
        </div>
      </el-col>

      <el-col :span="12">
        <!-- 排行榜 -->
        <div class="panel">
          <h3>🏅 排行榜
            <el-button size="small" text type="primary" style="float:right" @click="loadBoards">刷新</el-button>
            <el-button size="small" text type="warning" style="float:right;margin-right:8px" @click="rescore">重跑评分</el-button>
          </h3>
          <el-radio-group v-model="scope" size="small" class="scope-switch">
            <el-radio-button value="public">公榜</el-radio-button>
            <el-radio-button value="private" :disabled="comp.status !== 'ended'">私榜</el-radio-button>
          </el-radio-group>
          <el-alert v-if="scope === 'private' && comp.status !== 'ended'" type="info" :closable="false" :title="'私榜仅竞赛结束后可见'" />
          <el-empty v-else-if="!board.length" description="暂无提交排名" :image-size="50" />
          <el-table v-else :data="board" size="small" max-height="360">
            <el-table-column prop="rank" label="#" width="46" />
            <el-table-column prop="username" label="选手" show-overflow-tooltip />
            <el-table-column :label="scope === 'private' ? '私榜分' : '公榜分'" width="100">
              <template #default="{ row }">{{ row[scope === 'private' ? 'private_score' : 'public_score'] }}</template>
            </el-table-column>
            <el-table-column label="提交" width="70" align="center"><template #default="{ row }">#{{ row.submission_id }}</template></el-table-column>
          </el-table>
          <p v-if="board.length" class="form-tip">每位选手取该榜最优一次；方向：{{ higherText }}。结算按私榜分决冠军。</p>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { Trophy, Back } from '@element-plus/icons-vue'
import CodeEditor from '../components/CodeEditor.vue'

const route = useRoute()
const compId = route.params.compId

const METRICS = [
  { value: 'accuracy', label: '准确率' },
  { value: 'f1_macro', label: '宏平均F1' },
  { value: 'rmse', label: 'RMSE' },
  { value: 'mae', label: 'MAE' },
  { value: 'auc', label: 'AUC（二分类）' },
  { value: 'custom', label: '自定义 scorer' },
]
const HIGHER = { accuracy: true, f1_macro: true, auc: true, rmse: false, mae: false }

const loading = ref(true)
const saving = ref(false)
const comp = ref(null)
const files = ref([])
const board = ref([])
const scope = ref('public')
const uploadRole = ref('train')
const dataFile = ref(null)
const form = reactive({ metric: 'accuracy', id_column: 'id', target_column: 'label', public_ratio: 0.3, daily_limit: 5, higher_is_better: true, scorer_code: '' })

const editable = computed(() => ['draft', 'rejected', 'published'].includes(comp.value?.status))
const statusLabel = (s) => ({ draft: '草稿', reviewing: '待审核', rejected: '被驳回', published: '未开始', ongoing: '进行中', ended: '已结束' }[s] || s)
const statusTag = (s) => ({ published: 'primary', ongoing: 'success', ended: 'danger' }[s] || 'info')
const roleLabel = (r) => ({ train: '训练集', test: '测试集', sample: '样例', gold: '隐藏答案' }[r] || r)
const fmtTime = (iso) => iso ? new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
const fmtSize = (n) => !n ? '0B' : (n < 1048576 ? (n / 1024).toFixed(1) + 'KB' : (n / 1048576).toFixed(1) + 'MB')
const higherText = computed(() => {
  const h = form.metric === 'custom' ? form.higher_is_better : HIGHER[form.metric]
  return h ? '越大越好' : '越小越好'
})

const load = async () => {
  loading.value = true
  try {
    comp.value = (await request.get(`/api/competitions/${compId}`)).data
    const cfg = (await request.get(`/api/ds/competitions/${compId}/config`)).data.config || {}
    if (cfg.metric) {
      form.metric = cfg.metric
      form.id_column = cfg.id_column || 'id'
      form.target_column = cfg.target_column || 'label'
      form.public_ratio = cfg.public_ratio ?? 0.3
      form.daily_limit = cfg.daily_limit ?? 5
      if (cfg.higher_is_better != null) form.higher_is_better = cfg.higher_is_better
    }
    files.value = (await request.get(`/api/ds/competitions/${compId}/datasets`)).data.items || []
    await loadBoards()
  } catch (e) {
    comp.value = null
  } finally {
    loading.value = false
  }
}

const loadBoards = async () => {
  try {
    const res = await request.get(`/api/ds/competitions/${compId}/leaderboard?scope=${scope.value}`)
    board.value = res.data.items || []
  } catch (e) { board.value = [] }
}

const saveConfig = async () => {
  saving.value = true
  try {
    await request.post(`/api/ds/competitions/${compId}/config`, { ...form })
    ElMessage.success('配置已保存')
    load()
  } finally { saving.value = false }
}

const onUpload = async (e) => {
  const f = e.target.files?.[0]
  if (!f) return
  const fd = new FormData()
  fd.append('file', f)
  fd.append('role', uploadRole.value)
  await request.post(`/api/ds/competitions/${compId}/datasets`, fd)
  ElMessage.success('上传成功')
  e.target.value = ''
  load()
}

const delFile = async (row) => {
  try {
    await ElMessageBox.confirm(`删除「${row.filename}」？`, '删除文件', { type: 'warning' })
  } catch (e) { return }
  await request.delete(`/api/ds/files/${row.id}`)
  ElMessage.success('已删除')
  load()
}

const rescore = async () => {
  try {
    await ElMessageBox.confirm('将按当前配置重新评分全部提交，确认？', '重跑评分', { type: 'warning' })
  } catch (e) { return }
  const res = await request.post(`/api/ds/competitions/${compId}/rescore`)
  ElMessage.success(res.data.message || '已重跑')
  load()
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { max-width: 1240px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; flex-wrap: wrap; gap: 12px; }
.header-title h2 { font-size: 22px; font-weight: 700; color: var(--text-primary); margin: 0 0 8px 0; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.trophy { color: #d97706; }
.header-title p { font-size: 13.5px; color: var(--text-muted); margin: 0; }
.panel { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 14px; padding: 18px 20px; margin-bottom: 16px; }
.panel h3 { font-size: 15.5px; font-weight: 700; color: var(--text-primary); margin: 0 0 14px; }
.form-tip { font-size: 12px; color: var(--text-muted); margin-left: 10px; }
.gold-tip { margin-left: 0; margin-top: 8px; }
.scorer-tip { font-size: 12px; color: var(--text-muted); margin: -6px 0 10px 96px; }
.scorer-tip code, .gold-tip b { }
.upload-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-size: 13.5px; }
.scope-switch { margin-bottom: 10px; }
</style>
