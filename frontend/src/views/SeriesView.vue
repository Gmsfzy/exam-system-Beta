<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Trophy /></el-icon> 多轮系列赛</h2>
        <p>把若干场竞赛归为一个赛季系列，按总积分或最佳 N 场结算总冠军</p>
      </div>
      <el-button v-if="isTeacher" type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>创建系列赛
      </el-button>
    </div>

    <div v-if="loading" class="loading-box"><el-skeleton :rows="4" animated /></div>
    <el-empty v-else-if="!seriesList.length" description="还没有系列赛{{ isTeacher ? '，点击右上角创建' : '' }}" />

    <div v-else class="series-grid">
      <div v-for="s in seriesList" :key="s.id" class="series-card"
           :class="{ active: current && current.id === s.id }" @click="selectSeries(s)">
        <div class="sc-top">
          <span class="sc-title">{{ s.title }}</span>
          <el-tag v-if="s.ongoing" size="small" type="success" effect="dark">进行中</el-tag>
        </div>
        <div class="sc-meta">
          <span class="m-item">{{ s.round_count }} 轮</span>
          <span class="m-item">· {{ s.scoring_mode === 'best_n' ? (s.best_n > 0 ? `最佳 ${s.best_n} 场` : '全部场次') : '总积分' }}</span>
          <span v-if="!isTeacher && s.my_rank" class="m-item rank">我的排名 第{{ s.my_rank }}</span>
          <span v-if="isTeacher && s.participant_count != null" class="m-item">{{ s.participant_count }} 人参与</span>
        </div>
        <div class="sc-desc">{{ s.description || '暂无描述' }}</div>
      </div>
    </div>

    <!-- 详情 -->
    <div v-if="current" class="detail-card">
      <div class="detail-head">
        <h3>{{ current.title }}</h3>
        <div class="detail-actions" v-if="isTeacher">
          <el-button size="small" @click="openBind">关联竞赛</el-button>
          <el-button size="small" type="danger" text @click="removeSeries">删除系列赛</el-button>
        </div>
      </div>

      <div class="rounds-line" v-if="rounds.length">
        <el-tag v-for="r in rounds" :key="r.competition_id" size="small" effect="plain" class="round-tag">
          第{{ r.series_round }}轮 · {{ r.title }}
        </el-tag>
      </div>
      <el-empty v-else description="尚未关联任何竞赛轮次" :image-size="70" />

      <div v-if="standings.length" class="standings">
        <div class="st-title">总冠军排行</div>
        <el-table :data="standings" stripe size="small">
          <el-table-column label="名次" width="70" align="center">
            <template #default="{ row }">
              <span :class="['rk', row.rank <= 3 ? 'rk-' + row.rank : '']">{{ row.rank }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="username" label="选手" min-width="120" />
          <el-table-column prop="total" label="系列总分" width="100" align="center" />
          <el-table-column v-for="r in rounds" :key="r.competition_id" :label="`第${r.round}轮`" width="90" align="center">
            <template #default="{ row }">
              <span v-if="row.rounds[r.competition_id]">
                {{ row.rounds[r.competition_id].points }}<span class="sub-rank">（第{{ row.rounds[r.competition_id].rank }}）</span>
              </span>
              <span v-else class="absent">—</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 创建对话框 -->
    <el-dialog v-model="createVisible" title="创建系列赛" width="520px">
      <el-form :model="createForm" label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="createForm.title" placeholder="例如：秋季挑战赛·三连胜" maxlength="100" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="系列赛说明（可选）" />
        </el-form-item>
        <el-form-item label="结算模式">
          <el-radio-group v-model="createForm.scoring_mode">
            <el-radio-button label="best_n">最佳 N 场</el-radio-button>
            <el-radio-button label="sum">总积分</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="createForm.scoring_mode === 'best_n'" label="取最佳">
          <el-input-number v-model="createForm.best_n" :min="0" :max="20" />
          <span class="form-tip">0 表示统计全部场次之和</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="saveSeries">创建</el-button>
      </template>
    </el-dialog>

    <!-- 关联竞赛对话框 -->
    <el-dialog v-model="bindVisible" title="关联竞赛到系列赛" width="520px">
      <el-form label-width="90px">
        <el-form-item label="选择竞赛">
          <el-select v-model="bindForm.competition_id" placeholder="选择要并入本系列的竞赛" filterable style="width: 100%">
            <el-option v-for="c in myCompetitions" :key="c.id" :label="`${c.title}（${c.status}）`" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="轮次序号">
          <el-input-number v-model="bindForm.series_round" :min="0" :max="50" />
          <span class="form-tip">0 表示自动排到下一轮</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!bindForm.competition_id" @click="doBind">关联</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import { Trophy, Plus } from '@element-plus/icons-vue'

const auth = useAuthStore()
const isTeacher = ref(auth.user?.role === 'teacher')

const loading = ref(true)
const seriesList = ref([])
const current = ref(null)
const rounds = ref([])
const standings = ref([])

const createVisible = ref(false)
const createForm = ref({ title: '', description: '', scoring_mode: 'best_n', best_n: 1 })
const bindVisible = ref(false)
const bindForm = ref({ competition_id: null, series_round: 0 })
const myCompetitions = ref([])

const loadList = async () => {
  loading.value = true
  try {
    const url = isTeacher.value ? '/api/series' : '/api/series/available'
    const res = await request.get(url)
    seriesList.value = res.data || []
    if (seriesList.value.length && !current.value) {
      selectSeries(seriesList.value[0])
    }
  } finally {
    loading.value = false
  }
}

const selectSeries = async (s) => {
  current.value = s
  rounds.value = []
  standings.value = []
  try {
    const [detail, st] = await Promise.all([
      request.get(`/api/series/${s.id}`),
      request.get(`/api/series/${s.id}/standings`),
    ])
    rounds.value = detail.data.rounds || []
    standings.value = st.data.standings || []
  } catch (e) { /* ignore */ }
}

const openCreate = () => {
  createForm.value = { title: '', description: '', scoring_mode: 'best_n', best_n: 1 }
  createVisible.value = true
}

const saveSeries = async () => {
  const f = createForm.value
  if (!f.title.trim()) return ElMessage.warning('请填写系列赛标题')
  await request.post('/api/series', {
    title: f.title, description: f.description,
    scoring_mode: f.scoring_mode, best_n: f.best_n,
  })
  ElMessage.success('创建成功')
  createVisible.value = false
  loadList()
}

const openBind = async () => {
  if (!current.value) return
  bindForm.value = { competition_id: null, series_round: 0 }
  const res = await request.get('/api/competitions')
  myCompetitions.value = res.data || []
  bindVisible.value = true
}

const doBind = async () => {
  const { competition_id, series_round } = bindForm.value
  await request.post(`/api/series/${current.value.id}/competitions`, {
    competition_id, series_round,
  })
  ElMessage.success('已关联')
  bindVisible.value = false
  await selectSeries(current.value)
  loadList()
}

const removeSeries = () => {
  ElMessageBox.confirm(`确定删除系列赛「${current.value.title}」？关联的竞赛不会被删除。`, '删除系列赛', { type: 'warning' })
    .then(async () => {
      await request.delete(`/api/series/${current.value.id}`)
      ElMessage.success('已删除')
      current.value = null
      loadList()
    }).catch(() => {})
}

onMounted(loadList)
</script>

<style scoped>
.page-wrapper {
  max-width: 1040px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}

.header-title h2 {
  font-size: 26px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  color: #d97706;
}

.header-title p {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

.loading-box {
  padding: 20px;
}

.series-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.series-card {
  padding: 18px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.series-card:hover {
  border-color: rgba(245, 158, 11, 0.5);
  transform: translateY(-2px);
}

.series-card.active {
  border-color: #d97706;
  box-shadow: 0 6px 18px rgba(217, 119, 6, 0.18);
}

.sc-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.sc-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.sc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.m-item.rank {
  color: #d97706;
  font-weight: 600;
}

.sc-desc {
  font-size: 12.5px;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.detail-card {
  padding: 22px 24px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
}

.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.detail-head h3 {
  margin: 0;
  font-size: 18px;
  color: var(--text-primary);
}

.rounds-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 18px;
}

.round-tag {
  font-size: 12px;
}

.st-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 10px;
}

.rk {
  font-weight: 700;
}

.rk-1 { color: #f0c14b; }
.rk-2 { color: #a8b4c4; }
.rk-3 { color: #b08d57; }

.sub-rank {
  font-size: 11.5px;
  color: var(--text-muted);
}

.absent {
  color: var(--text-light);
}

.form-tip {
  font-size: 12px;
  color: var(--text-light);
  margin-left: 8px;
}

.dark .series-card,
.dark .detail-card {
  background: var(--glass-bg);
  border-color: var(--glass-border);
}
</style>
