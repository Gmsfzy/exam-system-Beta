<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Tickets /></el-icon> 课程成绩册</h2>
        <span class="sub">按课程把作业与考试成绩加权汇总，只读视图、不改判分与积分</span>
      </div>
      <div class="head-tools">
        <el-select v-model="courseId" filterable placeholder="选择课程" style="width: 220px" @change="onCourseChange">
          <el-option v-for="cs in courses" :key="cs.id" :label="cs.name" :value="cs.id" />
        </el-select>
        <el-button :icon="Refresh" :disabled="!courseId" @click="reload">刷新</el-button>
      </div>
    </div>

    <el-empty v-if="!courses.length" description="暂无课程，请先在题库管理中创建课程" />
    <el-alert v-else-if="!courseId" type="info" :closable="false" show-icon title="请选择一门课程" />

    <!-- 教师：权重方案 + 成绩册 -->
    <el-tabs v-else-if="isTeacher" v-model="tab">
      <el-tab-pane label="成绩册" name="book">
        <el-skeleton v-if="loading" :rows="5" animated />
        <template v-else>
          <el-empty v-if="!groups.length" description="尚未配置计分组件，请先在「权重方案」添加" />
          <div v-for="g in groups" :key="g.teacher_id" class="group">
            <div class="group-head">
              <span class="g-title">计分组件：作业 {{ g.homework_count }} · 考试 {{ g.exam_count }}</span>
              <span class="muted small">共 {{ g.rows.length }} 名学生</span>
            </div>
            <el-table :data="g.rows" border stripe size="small">
              <el-table-column prop="student_name" label="学生" min-width="120" fixed />
              <el-table-column v-for="s in g.schemes" :key="s.id" :label="schemeLabel(s)" min-width="110" align="center">
                <template #default="{ row }">
                  <span :class="rateClass(compOf(row, s.id)?.rate)">{{ fmtRate(compOf(row, s.id)?.rate) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="加权总评" min-width="120" align="center" fixed="right">
                <template #default="{ row }">
                  <b :class="totalClass(row.total)">{{ fmtRate(row.total) }}</b>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="权重方案" name="scheme">
        <div class="toolbar">
          <el-button type="primary" :icon="Plus" @click="openScheme()">新增计分组件</el-button>
          <span class="muted small">权重按 Σ 归一，未必要凑满 100；聚合口径：平均(仅已完成)/全部(未交计0)/最优(取最高)</span>
        </div>
        <el-table :data="schemes" border stripe size="small" class="mt10">
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.component_type === 'exam' ? 'warning' : 'success'" effect="plain">
                {{ row.component_type === 'exam' ? '考试' : '作业' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column prop="weight" label="权重" width="90" align="center" />
          <el-table-column label="聚合口径" width="120" align="center">
            <template #default="{ row }">{{ AGG_LABEL[row.aggregate] || row.aggregate }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150" align="center">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="openScheme(row)">编辑</el-button>
              <el-button size="small" text type="danger" @click="delScheme(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!schemes.length" description="暂无计分组件" />
      </el-tab-pane>
    </el-tabs>

    <!-- 学生：本人各教师成绩册 -->
    <div v-else class="student-wrap">
      <el-skeleton v-if="loading" :rows="4" animated />
      <el-empty v-else-if="!myBooks.length" description="该课程暂无你的成绩记录" />
      <el-card v-for="(bk, i) in myBooks" :key="i" shadow="never" class="mybook">
        <div class="group-head">
          <span class="g-title">任课：{{ bk.teacher_name }}</span>
          <span class="total-badge" :class="totalClass(bk.total)">总评 {{ fmtRate(bk.total) }}</span>
        </div>
        <el-table :data="bk.components" border size="small">
          <el-table-column label="类型" width="90">
            <template #default="{ row }">{{ row.component_type === 'exam' ? '考试' : '作业' }}</template>
          </el-table-column>
          <el-table-column prop="name" label="组件" min-width="140" />
          <el-table-column label="权重" width="80" align="center">
            <template #default="{ row }">{{ row.weight }}</template>
          </el-table-column>
          <el-table-column label="聚合" width="90" align="center">
            <template #default="{ row }">{{ AGG_LABEL[row.aggregate] || row.aggregate }}</template>
          </el-table-column>
          <el-table-column label="得分率" width="110" align="center">
            <template #default="{ row }"><span :class="rateClass(row.rate)">{{ fmtRate(row.rate) }}</span></template>
          </el-table-column>
        </el-table>
      </el-card>
    </div>

    <!-- 方案编辑对话框 -->
    <el-dialog v-model="schemeDialog" :title="schemeForm.id ? '编辑计分组件' : '新增计分组件'" width="480px">
      <el-form :model="schemeForm" label-width="88px">
        <el-form-item label="类型" required>
          <el-radio-group v-model="schemeForm.component_type">
            <el-radio-button value="homework">作业</el-radio-button>
            <el-radio-button value="exam">考试</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="schemeForm.name" maxlength="100" placeholder="如：平时作业 / 期中 / 期末" />
        </el-form-item>
        <el-form-item label="权重" required>
          <el-input-number v-model="schemeForm.weight" :min="0" :max="100" :step="5" controls-position="right" style="width: 160px" />
        </el-form-item>
        <el-form-item label="聚合口径">
          <el-select v-model="schemeForm.aggregate" style="width: 200px">
            <el-option label="平均（仅已完成）" value="mean" />
            <el-option label="全部（未交计 0）" value="all" />
            <el-option label="最优（取最高）" value="best" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="schemeDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveScheme">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { Tickets, Refresh, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isTeacher = computed(() => auth.user?.role === 'teacher')
const AGG_LABEL = { mean: '平均', all: '全部', best: '最优' }

const tab = ref('book')
const courses = ref([])
const courseId = ref(null)
const loading = ref(false)
const groups = ref([])
const schemes = ref([])
const myBooks = ref([])

const schemeDialog = ref(false)
const saving = ref(false)
const schemeForm = reactive({ id: null, component_type: 'homework', name: '', weight: 20, aggregate: 'mean' })

const fmtRate = (v) => (v == null ? '—' : `${v}`)
const schemeLabel = (s) => `${s.name || (s.component_type === 'exam' ? '考试' : '作业')}(${s.weight}%)`
const compOf = (row, sid) => (row.components || []).find((x) => x.scheme_id === sid)
const rateClass = (v) => (v == null ? 'muted' : v >= 60 ? 'ok' : 'bad')
const totalClass = (v) => (v == null ? 'muted' : v >= 60 ? 'total-ok' : 'total-bad')

const loadCourses = async () => {
  const res = await request.get('/api/courses')
  courses.value = res.data || []
  if (!courseId.value && courses.value.length) courseId.value = courses.value[0].id
}

const loadTeacher = async () => {
  loading.value = true
  try {
    const [b, s] = await Promise.all([
      request.get(`/api/courses/${courseId.value}/gradebook`),
      request.get(`/api/courses/${courseId.value}/gradebook/schemes`),
    ])
    groups.value = b.data.groups || []
    schemes.value = s.data.schemes || []
  } finally {
    loading.value = false
  }
}

const loadStudent = async () => {
  loading.value = true
  try {
    const res = await request.get(`/api/courses/${courseId.value}/gradebook/me`)
    myBooks.value = res.data.gradebooks || []
  } finally {
    loading.value = false
  }
}

const reload = async () => {
  if (!courseId.value) return
  if (isTeacher.value) await loadTeacher()
  else await loadStudent()
}

const onCourseChange = () => reload()

const openScheme = (row) => {
  if (row) Object.assign(schemeForm, { id: row.id, component_type: row.component_type, name: row.name, weight: row.weight, aggregate: row.aggregate })
  else Object.assign(schemeForm, { id: null, component_type: 'homework', name: '', weight: 20, aggregate: 'mean' })
  schemeDialog.value = true
}

const saveScheme = async () => {
  saving.value = true
  const payload = { component_type: schemeForm.component_type, name: schemeForm.name, weight: schemeForm.weight, aggregate: schemeForm.aggregate }
  try {
    if (schemeForm.id) await request.put(`/api/gradebook/schemes/${schemeForm.id}`, payload)
    else await request.post(`/api/courses/${courseId.value}/gradebook/schemes`, payload)
    ElMessage.success('已保存')
    schemeDialog.value = false
    await loadTeacher()
  } catch (e) {
    ElMessage.error(e.response?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

const delScheme = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除计分组件「${row.name || schemeLabel(row)}」？`, '提示', { type: 'warning' })
  } catch { return }
  await request.delete(`/api/gradebook/schemes/${row.id}`)
  ElMessage.success('已删除')
  await loadTeacher()
}

onMounted(async () => {
  await loadCourses()
  await reload()
})
</script>

<style scoped>
.page-wrapper { padding: 4px; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; flex-wrap: wrap; gap: 12px; }
.header-title h2 { margin: 0; display: flex; align-items: center; gap: 8px; }
.header-title .sub { color: #909399; font-size: 13px; }
.title-icon { color: #6366f1; }
.head-tools { display: flex; gap: 8px; }
.group { margin-bottom: 20px; }
.group-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.g-title { font-weight: 600; }
.toolbar { margin-bottom: 8px; }
.mt10 { margin-top: 10px; }
.muted { color: #909399; }
.small { font-size: 12px; }
.ok { color: #67c23a; }
.bad { color: #f56c6c; }
.total-ok { color: #67c23a; font-size: 15px; }
.total-bad { color: #f56c6c; font-size: 15px; }
.mybook { margin-bottom: 16px; }
.total-badge { font-weight: 700; font-size: 15px; padding: 2px 10px; border-radius: 6px; background: #f4f4f5; }
</style>
