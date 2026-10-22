<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Memo /></el-icon> 评分量规库</h2>
      </div>
      <div class="header-actions">
        <el-button type="primary" size="small" :icon="Plus" @click="openCreate">新建量规</el-button>
        <el-button :icon="Refresh" size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert type="info" :closable="false" show-icon class="tip">
      量规是教师可复用的<b>多维度评分标准</b>（如「内容 60 / 语言 40」）。在批改作业时可关联量规、逐维度打分，
      并按量规合计「填入」整体建议分。<b>量规分仅作结构化拆解与建议，不改动官方总分、积分与错题口径。</b>
    </el-alert>

    <el-table :data="items" v-loading="loading" class="rb-table" empty-text="还没有量规，点上方「新建量规」开始">
      <el-table-column prop="title" label="量规" min-width="180">
        <template #default="{ row }">
          <div class="rb-title">{{ row.title }}</div>
          <div v-if="row.description" class="rb-desc">{{ row.description }}</div>
        </template>
      </el-table-column>
      <el-table-column label="维度" min-width="260">
        <template #default="{ row }">
          <el-tag v-for="(d, i) in row.dimensions" :key="i" size="small" effect="plain" class="dim-tag">
            {{ d.label }} · {{ d.max_score }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="建议满分" width="110" align="center">
        <template #default="{ row }"><b>{{ row.max_total }}</b></template>
      </el-table-column>
      <el-table-column label="引用作业" width="100" align="center">
        <template #default="{ row }">{{ row.homework_count ?? 0 }} 份</template>
      </el-table-column>
      <el-table-column label="操作" width="150" align="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialog" :title="form.id ? '编辑量规' : '新建量规'" width="680px" top="6vh">
      <el-form label-width="72px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" placeholder="如：议论文写作量规" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="2000" placeholder="量规用途说明（可选）" />
        </el-form-item>
        <el-form-item label="维度">
          <div class="dims">
            <div v-for="(d, i) in form.dimensions" :key="i" class="dim-card">
              <div class="dim-head">
                <el-input v-model="d.label" size="small" placeholder="维度名（如 内容）" style="width: 180px" maxlength="60" />
                <span class="lbl">满分</span>
                <el-input-number v-model="d.max_score" size="small" :min="0" :max="1000" :step="5" controls-position="right" style="width: 120px" />
                <el-button link type="danger" size="small" :icon="Delete" @click="form.dimensions.splice(i, 1)" />
              </div>
              <div class="levels">
                <div class="lv-title">描述语（可选，供打分参考）</div>
                <div v-for="(lv, j) in d.levels" :key="j" class="lv-row">
                  <el-input-number v-model="lv.score" size="small" :min="0" :max="d.max_score || 0" :step="1" controls-position="right" style="width: 110px" />
                  <el-input v-model="lv.desc" size="small" placeholder="该档描述（如 切题、论证充分）" style="flex: 1" maxlength="200" />
                  <el-button link type="danger" size="small" :icon="Delete" @click="d.levels.splice(j, 1)" />
                </div>
                <el-button link type="primary" size="small" :icon="Plus" @click="d.levels.push({ score: 0, desc: '' })">添加描述语</el-button>
              </div>
            </div>
            <el-button size="small" :icon="Plus" @click="addDim">添加维度</el-button>
            <span class="muted small" style="margin-left: 12px">合计建议满分：<b>{{ maxTotal }}</b></span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="dialog = false">取消</el-button>
        <el-button type="primary" size="small" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Memo, Refresh, Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'

const items = ref([])
const loading = ref(false)

const dialog = ref(false)
const saving = ref(false)
const form = ref({ id: null, title: '', description: '', dimensions: [] })

const maxTotal = computed(() =>
  form.value.dimensions.reduce((s, d) => s + (Number(d.max_score) || 0), 0))

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/homeworks/rubrics')
    items.value = res.data.items || []
  } finally {
    loading.value = false
  }
}

const blank = () => ({ id: null, title: '', description: '',
  dimensions: [{ label: '', max_score: 10, levels: [] }] })

const openCreate = () => { form.value = blank(); dialog.value = true }

const openEdit = (row) => {
  form.value = {
    id: row.id, title: row.title, description: row.description || '',
    dimensions: (row.dimensions || []).map(d => ({
      label: d.label, max_score: Number(d.max_score) || 0,
      levels: (d.levels || []).map(lv => ({ score: Number(lv.score) || 0, desc: lv.desc || '' }))
    }))
  }
  if (!form.value.dimensions.length) form.value.dimensions.push({ label: '', max_score: 10, levels: [] })
  dialog.value = true
}

const addDim = () => form.value.dimensions.push({ label: '', max_score: 10, levels: [] })

const save = async () => {
  if (!form.value.title.trim()) return ElMessage.warning('请填写量规标题')
  if (!form.value.dimensions.length) return ElMessage.warning('至少一个维度')
  for (const d of form.value.dimensions) {
    if (!String(d.label || '').trim()) return ElMessage.warning('维度名不能为空')
  }
  saving.value = true
  try {
    const payload = {
      title: form.value.title, description: form.value.description,
      dimensions: form.value.dimensions.map(d => ({
        label: d.label, max_score: Number(d.max_score) || 0,
        levels: (d.levels || []).filter(lv => String(lv.desc || '').trim() !== '' || lv.score != null)
          .map(lv => ({ score: Number(lv.score) || 0, desc: lv.desc || '' }))
      }))
    }
    if (form.value.id) await request.put(`/api/homeworks/rubrics/${form.value.id}`, payload)
    else await request.post('/api/homeworks/rubrics', payload)
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const remove = async (row) => {
  await ElMessageBox.confirm(
    `确认删除量规《${row.title}》？引用它的作业将解除关联（已录入的维度分保留供留档）。`, '提示', { type: 'warning' })
  await request.delete(`/api/homeworks/rubrics/${row.id}`)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.tip { margin-bottom: 14px; }
.rb-table { background: #fff; border-radius: 10px; }
.rb-title { font-weight: 600; color: #303133; }
.rb-desc { font-size: 12px; color: #909399; margin-top: 2px; }
.dim-tag { margin: 2px 4px 2px 0; font-size: 12px; }
.dims { width: 100%; }
.dim-card { border: 1px solid #ebeef5; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; background: #fafbff; }
.dim-head { display: flex; align-items: center; gap: 8px; }
.lbl { font-size: 13px; color: #606266; }
.levels { margin-top: 8px; padding-left: 4px; }
.lv-title { font-size: 12px; color: #909399; margin-bottom: 6px; }
.lv-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.muted { color: #909399; } .small { font-size: 12px; }
</style>
