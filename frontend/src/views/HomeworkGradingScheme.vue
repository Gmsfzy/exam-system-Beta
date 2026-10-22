<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Medal /></el-icon> 评分制设置</h2>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert type="info" :closable="false" show-icon class="tip">
      为每个作业选择评分呈现方式：<b>分数制</b>（原始数值分）/ <b>等级制</b>（按得分率映射优·良·中·差，可自定义阈值）/
      <b>评语制</b>（学生仅见评语、不见数值分）。<b>仅影响展示层，不改动判分、积分与错题口径。</b>已发布作业亦可随时调整。
    </el-alert>

    <el-table :data="rows" v-loading="loading" class="scheme-table" empty-text="你还没有布置作业">
      <el-table-column prop="title" label="作业" min-width="200">
        <template #default="{ row }">
          <div class="hw-title">{{ row.title }}</div>
          <div class="hw-meta">
            <span>{{ row.hw_type === 'open' ? '开放式' : '题集式' }}</span>
            <el-tag size="small" :type="statusTag(row.status)" effect="plain">{{ statusText(row.status) }}</el-tag>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="评分制" width="180">
        <template #default="{ row }">
          <el-select v-model="row.grade_mode" size="small" @change="row.dirty = true">
            <el-option label="分数制" value="numeric" />
            <el-option label="等级制" value="level" />
            <el-option label="评语制" value="comment" />
          </el-select>
        </template>
      </el-table-column>

      <el-table-column label="等级档位 / 预览" min-width="280">
        <template #default="{ row }">
          <template v-if="row.grade_mode === 'level'">
            <div class="scale-preview">
              <el-tag v-for="(it, i) in effectiveScale(row)" :key="i"
                      size="small" :type="levelTag(i)" effect="plain" class="scale-tag">
                {{ it.label }} ≥ {{ Math.round(it.min * 100) }}%
              </el-tag>
            </div>
            <el-button link type="primary" size="small" @click="openScaleEditor(row)">
              {{ (row.grade_scale && row.grade_scale.length) ? '编辑自定义档位' : '使用内置四档 · 自定义' }}
            </el-button>
          </template>
          <span v-else-if="row.grade_mode === 'comment'" class="muted small">学生端仅显示教师评语，不展示数值分</span>
          <span v-else class="muted small">按原始数值总分呈现（得分 / 满分）</span>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="140" align="right">
        <template #default="{ row }">
          <el-button type="primary" size="small" :disabled="!row.dirty" :loading="row.saving"
                     @click="save(row)">保存</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 等级阈值编辑器 -->
    <el-dialog v-model="scaleDialog" title="自定义等级档位" width="520px">
      <div class="muted small" style="margin-bottom: 10px">
        按得分率（0~1）从高到低匹配：得分落入「≥ 阈值」的最高档位。阈值填 0~1 的小数（0.9 即 90%）。留空一行删除即可。
      </div>
      <div v-for="(it, i) in editingScale" :key="i" class="scale-row">
        <el-input v-model="it.label" size="small" placeholder="档位名（如 优）" style="width: 150px" maxlength="12" />
        <span class="sep">≥ 得分率</span>
        <el-input-number v-model="it.min" size="small" :min="0" :max="1" :step="0.05" :precision="2"
                         controls-position="right" style="width: 130px" />
        <el-button link type="danger" size="small" :icon="Delete" @click="editingScale.splice(i, 1)" />
      </div>
      <el-button link type="primary" size="small" :icon="Plus" @click="editingScale.push({ label: '', min: 0 })">
        添加档位
      </el-button>

      <div v-if="previewList.length" class="preview-box">
        <div class="preview-title">换算预览（按得分率示例）</div>
        <div class="preview-items">
          <span v-for="(p, i) in previewList" :key="i" class="preview-item">
            {{ Math.round(p.ratio * 100) }}% → <b>{{ p.label }}</b>
          </span>
        </div>
      </div>

      <template #footer>
        <el-button size="small" @click="useBuiltin">恢复内置四档</el-button>
        <el-button size="small" @click="scaleDialog = false">取消</el-button>
        <el-button type="primary" size="small" @click="applyScale">应用</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Medal, Refresh, Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'

const BUILTIN = [{ label: '优', min: 0.9 }, { label: '良', min: 0.8 },
                 { label: '中', min: 0.6 }, { label: '差', min: 0.0 }]

const rows = ref([])
const loading = ref(false)

const scaleDialog = ref(false)
const editingScale = ref([])
let editingRow = null

const statusText = (s) => ({ draft: '草稿', published: '已发布', closed: '已关闭' }[s] || s)
const statusTag = (s) => ({ draft: 'info', published: 'success', closed: 'warning' }[s] || 'info')
const levelTag = (i) => ['success', '', 'warning', 'danger'][i % 4]

const load = async () => {
  loading.value = true
  try {
    const res = await request.get('/api/homeworks')
    rows.value = (res.data.items || []).map(h => ({
      id: h.id, title: h.title, hw_type: h.hw_type, status: h.status,
      grade_mode: h.grade_mode || 'numeric',
      grade_scale: Array.isArray(h.grade_scale) ? h.grade_scale.map(x => ({ label: x.label, min: Number(x.min) })) : [],
      dirty: false, saving: false
    }))
  } finally {
    loading.value = false
  }
}

// 生效档位：自定义优先（按 min 降序），否则内置四档
const effectiveScale = (row) => {
  const src = (row.grade_scale && row.grade_scale.length) ? row.grade_scale : BUILTIN
  return [...src].sort((a, b) => b.min - a.min)
}

// 换算预览：对若干示例得分率求档位
const levelFor = (scale, ratio) => {
  const s = [...scale].sort((a, b) => b.min - a.min)
  for (const it of s) if (ratio >= it.min) return it.label
  return s.length ? s[s.length - 1].label : ''
}
const previewList = computed(() => {
  const s = editingScale.value.filter(x => x.label && !Number.isNaN(Number(x.min)))
  if (!s.length) return []
  return [0.95, 0.85, 0.7, 0.55, 0.3].map(r => ({ ratio: r, label: levelFor(s, r) }))
})

const openScaleEditor = (row) => {
  editingRow = row
  editingScale.value = (row.grade_scale && row.grade_scale.length)
    ? row.grade_scale.map(x => ({ label: x.label, min: Number(x.min) }))
    : BUILTIN.map(x => ({ label: x.label, min: x.min }))
  scaleDialog.value = true
}
const useBuiltin = () => { editingScale.value = BUILTIN.map(x => ({ label: x.label, min: x.min })) }

const applyScale = () => {
  const cleaned = editingScale.value
    .filter(x => x.label && !Number.isNaN(Number(x.min)))
    .map(x => ({ label: String(x.label).slice(0, 12), min: Number(x.min) }))
  if (!cleaned.length) return ElMessage.warning('至少保留一个有效档位')
  if (editingRow) { editingRow.grade_scale = cleaned; editingRow.dirty = true }
  scaleDialog.value = false
}

const save = async (row) => {
  row.saving = true
  try {
    const payload = { grade_mode: row.grade_mode }
    payload.grade_scale = row.grade_mode === 'level' ? (row.grade_scale || []) : null
    const res = await request.put(`/api/homeworks/${row.id}`, payload)
    const hw = res.data.homework || {}
    row.grade_mode = hw.grade_mode || row.grade_mode
    row.grade_scale = Array.isArray(hw.grade_scale) ? hw.grade_scale.map(x => ({ label: x.label, min: Number(x.min) })) : []
    row.dirty = false
    ElMessage.success(res.data.message || '已保存')
  } finally {
    row.saving = false
  }
}

onMounted(load)
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.tip { margin-bottom: 14px; }
.scheme-table { background: #fff; border-radius: 10px; }
.hw-title { font-weight: 600; color: #303133; }
.hw-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #909399; margin-top: 3px; }
.scale-preview { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
.scale-tag { font-size: 12px; }
.muted { color: #909399; } .small { font-size: 12px; }
.scale-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sep { font-size: 13px; color: #606266; }
.preview-box { margin-top: 12px; padding: 10px 12px; background: #f8faff; border-radius: 8px; }
.preview-title { font-size: 12px; color: #606266; margin-bottom: 6px; }
.preview-items { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; color: #4b5563; }
.preview-items b { color: #4f46e5; }
</style>
