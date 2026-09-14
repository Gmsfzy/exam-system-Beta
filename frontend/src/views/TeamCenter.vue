<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><User /></el-icon> {{ isTeacher ? '战队管理' : '战队' }}</h2>
        <p><span class="sub-info">战队积分 = 队员当前赛季竞技积分之和</span></p>
      </div>
    </div>

    <!-- 我的战队 -->
    <div v-if="!isTeacher" class="section">
      <h3 class="section-title">我的战队</h3>
      <el-empty v-if="!myTeam" description="你还没有加入战队">
        <div class="empty-actions">
          <el-button type="primary" @click="createVisible = true">创建战队</el-button>
          <el-button @click="joinVisible = true">加入战队</el-button>
        </div>
      </el-empty>
      <div v-else class="my-team-card">
        <div class="team-head">
          <div>
            <div class="team-name">{{ myTeam.name }}</div>
            <div class="team-desc">{{ myTeam.description || '暂无简介' }}</div>
          </div>
          <div class="team-points">
            <span class="tp-value">{{ myTeam.points }}</span>
            <span class="tp-label">战队积分</span>
          </div>
        </div>
        <el-table :data="myTeam.members" stripe size="default">
          <el-table-column prop="username" label="成员" min-width="110">
            <template #default="{ row }">
              <span>{{ row.username }}</span>
              <el-tag v-if="row.role === 'captain'" size="small" type="warning" effect="plain" style="margin-left: 8px">队长</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="段位" width="90" align="center">
            <template #default="{ row }">
              <span class="tier-mini" :style="{ color: tierColor(row.tier) }">{{ row.tier }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="points" label="个人积分" width="100" align="center" />
          <el-table-column v-if="isMyTeamCaptain" label="操作" width="140" align="center">
            <template #default="{ row }">
              <el-button v-if="row.user_id !== myTeam.captain_id" size="small" text type="primary"
                         @click="transferTo(row)">转让队长</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="team-actions">
          <el-button v-if="!isMyTeamCaptain" size="small" type="danger" plain @click="leave">退出战队</el-button>
          <el-button v-else size="small" type="danger" plain @click="dissolve">解散战队</el-button>
        </div>
      </div>
    </div>

    <!-- 战队排行榜 -->
    <div class="section">
      <h3 class="section-title">战队排行榜</h3>
      <el-empty v-if="!teams.length" description="还没有战队，快创建第一个吧" />
      <el-table v-else :data="teams" stripe>
        <el-table-column prop="rank" label="名次" width="70" align="center" />
        <el-table-column prop="name" label="战队" min-width="140">
          <template #default="{ row }">
            <span>{{ row.name }}</span>
            <el-tag v-if="myTeam && row.id === myTeam.id" size="small" type="success" effect="plain" style="margin-left: 8px">我的战队</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="captain" label="队长" width="110" />
        <el-table-column prop="member_count" label="人数" width="70" align="center" />
        <el-table-column prop="points" label="战队积分" width="100" align="center">
          <template #default="{ row }">
            <span class="tp-cell">{{ row.points }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!isTeacher && !myTeam" label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="join(row)">加入</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 创建战队对话框 -->
    <el-dialog v-model="createVisible" title="创建战队" width="420">
      <el-form label-width="70px">
        <el-form-item label="战队名">
          <el-input v-model="createForm.name" maxlength="20" show-word-limit placeholder="不超过20个字" />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="战队口号（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="createTeam">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { User } from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isTeacher = computed(() => auth.user?.role === 'teacher')
const TIER_COLORS = {
  青铜: '#b08d57', 白银: '#a8b4c4', 黄金: '#f0c14b',
  铂金: '#7fd8d8', 钻石: '#7db9f5', 王者: '#ff7a45',
}

const myTeam = ref(null)
const teams = ref([])
const createVisible = ref(false)
const submitting = ref(false)
const createForm = ref({ name: '', description: '' })
let pollTimer = null

const isMyTeamCaptain = computed(() => myTeam.value && myTeam.value.captain_id === auth.user?.id)
const tierColor = (t) => TIER_COLORS[t] || 'inherit'

const load = async () => {
  const boardRes = await request.get('/api/teams')
  teams.value = boardRes.data
  if (!isTeacher.value) {
    const mine = await request.get('/api/teams/mine')
    myTeam.value = mine.data
  }
}

const createTeam = async () => {
  if (!createForm.value.name.trim()) {
    ElMessage.warning('请输入战队名')
    return
  }
  submitting.value = true
  try {
    const res = await request.post('/api/teams', createForm.value)
    myTeam.value = res.data
    createVisible.value = false
    createForm.value = { name: '', description: '' }
    ElMessage.success('战队创建成功')
    load()
  } finally {
    submitting.value = false
  }
}

const join = (team) => {
  ElMessageBox.confirm(`确定加入战队「${team.name}」？`, '加入战队', { type: 'info' })
    .then(async () => {
      const res = await request.post(`/api/teams/${team.id}/join`)
      myTeam.value = res.data
      ElMessage.success('加入成功')
      load()
    })
    .catch(() => {})
}

const leave = () => {
  ElMessageBox.confirm('确定退出当前战队？', '退出战队', { type: 'warning' })
    .then(async () => {
      await request.post(`/api/teams/${myTeam.value.id}/leave`)
      myTeam.value = null
      ElMessage.success('已退出战队')
      load()
    })
    .catch(() => {})
}

const transferTo = (member) => {
  ElMessageBox.confirm(`将队长转让给「${member.username}」？`, '转让队长', { type: 'warning' })
    .then(async () => {
      const res = await request.post(`/api/teams/${myTeam.value.id}/transfer`, { user_id: member.user_id })
      myTeam.value = res.data
      ElMessage.success('队长已转让')
      load()
    })
    .catch(() => {})
}

const dissolve = () => {
  ElMessageBox.confirm('解散后战队成员将全部移出，确定解散？', '解散战队', { type: 'warning' })
    .then(async () => {
      await request.delete(`/api/teams/${myTeam.value.id}`)
      myTeam.value = null
      ElMessage.success('战队已解散')
      load()
    })
    .catch(() => {})
}

onMounted(() => {
  load()
  pollTimer = setInterval(load, 30000)
})
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.page-wrapper {
  max-width: 860px;
  margin: 0 auto;
}

.page-header h2 {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon {
  color: #7db9f5;
}

.sub-info {
  font-size: 13.5px;
  color: var(--text-muted);
}

.section {
  margin-bottom: 28px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 12px 0;
}

.empty-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}

.my-team-card {
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 20px;
  background: var(--bg-secondary);
}

.team-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.team-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.team-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 4px;
}

.team-points {
  text-align: center;
}

.tp-value {
  display: block;
  font-size: 26px;
  font-weight: 800;
  color: #f0c14b;
}

.tp-label {
  font-size: 12px;
  color: var(--text-muted);
}

.tp-cell {
  font-weight: 700;
  color: #f0c14b;
}

.team-actions {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}

.tier-mini {
  font-weight: 700;
}
</style>
