<template>
  <div class="repo-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">学习规划仓</h1>
        <p class="page-subtitle">全量专业与课程随取随用：挑素材、选模板，一键生成自己的学习路径</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openCreate()">
          <el-icon style="margin-right: 4px"><Plus /></el-icon>新建模板
        </el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- ── 专业课程库 ───────────────────────────────────── -->
      <el-tab-pane label="专业课程库" name="catalog">
        <div class="stat-row">
          <div v-for="s in catalogStats" :key="s.label" class="stat-chip">
            <span class="stat-num">{{ s.value }}</span>
            <span class="stat-label">{{ s.label }}</span>
          </div>
          <el-input
            v-model="catalogKw" placeholder="搜索课程名称" clearable
            style="width: 220px; margin-left: auto" @change="loadCatalog"
          />
        </div>

        <div v-loading="catalogLoading">
          <el-empty v-if="!catalog.majors.length" description="暂无课程数据" />
          <el-collapse v-else v-model="openMajors">
            <el-collapse-item v-for="m in catalog.majors" :key="m.id" :name="String(m.id)">
              <template #title>
                <span class="major-name">{{ m.name }}</span>
                <el-tag size="small" effect="plain">{{ m.department_name || '未分系' }}</el-tag>
                <el-tag size="small" type="info">{{ m.courses_count }} 门课程</el-tag>
              </template>
              <div class="course-grid">
                <div v-for="c in m.courses" :key="c.id" class="course-card">
                  <div class="cc-top">
                    <span class="cc-name">{{ c.name }}</span>
                    <el-tag v-if="c.credit" size="small" effect="plain">{{ c.credit }} 学分</el-tag>
                  </div>
                  <p class="cc-desc">{{ c.description || '暂无课程简介' }}</p>
                  <div class="cc-meta">
                    <span>{{ c.chapters_count }} 章节</span>
                    <span>{{ c.knowledge_points_count }} 知识点</span>
                  </div>
                  <div class="cc-actions">
                    <el-button size="small" type="primary" plain
                      @click="openCreate({
                        major_id: m.id,
                        items: [{ item_type: 'course', course_id: c.id, title: c.name, estimated_minutes: 120 }]
                      })">用此课程建模板</el-button>
                    <el-button size="small" text @click="openCreate({ major_id: m.id })">
                      新建该专业模板
                    </el-button>
                  </div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-tab-pane>

      <!-- ── 模板库 / 我的模板 ────────────────────────────── -->
      <el-tab-pane v-for="tab in listTabs" :key="tab.name" :label="tab.label" :name="tab.name">
        <div class="filter-row">
          <el-input
            v-model="filters.q" placeholder="搜索模板标题/简介" clearable
            style="width: 240px" @change="loadTemplates"
          />
          <el-select v-model="filters.major_id" placeholder="全部专业" clearable
            style="width: 180px" @change="loadTemplates">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
          <el-select v-model="filters.type" placeholder="全部类型" clearable
            style="width: 150px" @change="loadTemplates">
            <el-option label="结构化" value="structured" />
            <el-option label="非结构化" value="unstructured" />
          </el-select>
          <span class="filter-count">共 {{ listTotal }} 个模板</span>
        </div>

        <div v-loading="listLoading">
          <el-empty v-if="!listLoading && !currentList.length" :description="tab.name === 'mine' ? '你还没有创建模板' : '还没有公开模板'" />
          <div v-else class="tpl-grid">
            <div v-for="t in currentList" :key="t.id" class="tpl-card">
              <div class="tc-top">
                <span class="tc-title">{{ t.title }}</span>
                <el-tag size="small" :type="t.visibility === 'public' ? 'success' : 'info'">
                  {{ t.visibility === 'public' ? '公开' : '私有' }}
                </el-tag>
              </div>
              <p class="tc-desc">{{ t.description || '暂无简介' }}</p>
              <div class="tc-tags">
                <el-tag size="small" effect="plain">
                  {{ t.template_type === 'structured' ? '结构化' : '非结构化' }}
                </el-tag>
                <el-tag v-if="t.major_name" size="small" effect="plain">{{ t.major_name }}</el-tag>
                <el-tag size="small" type="warning" effect="plain">{{ diffLabel(t.difficulty) }}</el-tag>
              </div>
              <div class="tc-meta">
                <span>{{ t.items_count }} 个条目</span>
                <span>约 {{ formatMinutes(t.total_minutes) }}</span>
                <span v-if="t.target_hours">目标 {{ t.target_hours }} 学时</span>
              </div>
              <div class="tc-footer">
                <span class="tc-owner">
                  {{ t.is_mine ? '我的模板' : '来自 ' + (t.owner_name || '-') }} · 被使用 {{ t.use_count }} 次
                </span>
                <div class="tc-ops">
                  <el-button size="small" text @click="viewTemplate(t)">详情</el-button>
                  <template v-if="t.is_mine">
                    <el-button size="small" text type="primary" @click="openEdit(t)">编辑</el-button>
                    <el-button size="small" text type="danger" @click="removeTemplate(t)">删除</el-button>
                  </template>
                  <el-button size="small" type="primary" @click="askUse(t)">使用</el-button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ── 模板详情抽屉 ────────────────────────────────────── -->
    <el-drawer v-model="detailDlg" :title="detail?.title || '模板详情'" size="520px">
      <template v-if="detail">
        <p class="detail-desc">{{ detail.description || '暂无简介' }}</p>
        <div class="detail-meta">
          <el-tag size="small" effect="plain">{{ detail.major_name || '未关联专业' }}</el-tag>
          <el-tag size="small" effect="plain">{{ detail.template_type === 'structured' ? '结构化' : '非结构化' }}</el-tag>
          <el-tag size="small" type="warning" effect="plain">{{ diffLabel(detail.difficulty) }}</el-tag>
          <span>{{ detail.items_count }} 个条目</span>
          <span>约 {{ formatMinutes(detail.total_minutes) }}</span>
        </div>
        <div class="detail-items">
          <div v-for="(it, i) in detail.items" :key="it.id" class="detail-item">
            <span class="di-order">{{ i + 1 }}</span>
            <div class="di-body">
              <div class="di-title-row">
                <span class="di-title">{{ it.title }}</span>
                <el-tag size="small" :type="typeTag(it.item_type)">{{ typeLabel(it.item_type) }}</el-tag>
                <el-tag v-if="!it.required" size="small" type="info">选修</el-tag>
              </div>
              <div class="di-meta">
                <span>约 {{ it.estimated_minutes || 60 }} 分钟</span>
                <el-link v-if="it.url" type="primary" :href="it.url" target="_blank" rel="noopener">打开外链</el-link>
                <el-link v-if="it.file_url" type="primary" :href="it.file_url" target="_blank" rel="noopener">下载附件</el-link>
              </div>
              <p v-if="it.content" class="di-content">{{ it.content }}</p>
            </div>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button @click="detailDlg = false">关闭</el-button>
        <el-button type="primary" @click="detail && askUse(detail)">使用此模板</el-button>
      </template>
    </el-drawer>

    <!-- ── 使用模板（生成个人路径）────────────────────────── -->
    <el-dialog v-model="useDlg" title="使用模板生成学习路径" width="460px">
      <el-form label-width="90px">
        <el-form-item label="所属专业" required>
          <el-select v-model="useMajorId" placeholder="选择专业" filterable style="width: 100%">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="路径标题">
          <el-input v-model="useTitle" maxlength="100" placeholder="留空则沿用模板标题" />
        </el-form-item>
      </el-form>
      <p class="form-hint">生成的是你自己的独立路径草稿，可在「专业路径」里继续调整节点。</p>
      <template #footer>
        <el-button @click="useDlg = false">取消</el-button>
        <el-button type="primary" :loading="using" @click="doUse">生成路径</el-button>
      </template>
    </el-dialog>

    <!-- ── 模板编辑器 ─────────────────────────────────────── -->
    <el-dialog v-model="editor.visible" :title="editor.id ? '编辑模板' : '新建模板'" width="860px" top="6vh">
      <el-form :model="editor.form" label-width="90px">
        <div class="form-grid">
          <el-form-item label="模板标题" required>
            <el-input v-model="editor.form.title" maxlength="100" placeholder="如：数据结构期末冲刺路线" />
          </el-form-item>
          <el-form-item label="所属专业">
            <el-select v-model="editor.form.major_id" placeholder="可不选（跨专业通用）" clearable style="width: 100%">
              <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="模板类型">
            <el-radio-group v-model="editor.form.template_type">
              <el-radio-button value="structured">结构化</el-radio-button>
              <el-radio-button value="unstructured">非结构化</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="可见性">
            <el-radio-group v-model="editor.form.visibility">
              <el-radio-button value="private">私有</el-radio-button>
              <el-radio-button value="public">公开</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="难度">
            <el-select v-model="editor.form.difficulty" style="width: 100%">
              <el-option label="简单" value="easy" />
              <el-option label="中等" value="medium" />
              <el-option label="困难" value="hard" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标学时">
            <el-input-number v-model="editor.form.target_hours" :min="1" :max="999" />
          </el-form-item>
        </div>
        <el-form-item label="模板简介">
          <el-input v-model="editor.form.description" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
      </el-form>

      <div class="editor-items-head">
        <span class="ei-title">学习条目（顺序即学习顺序）</span>
        <el-button size="small" type="primary" plain @click="openItemDlg">
          <el-icon style="margin-right: 4px"><Plus /></el-icon>添加条目
        </el-button>
      </div>
      <el-empty v-if="!editor.items.length" description="还没有条目，先添加课程/章节/外链/富文本/附件" :image-size="70" />
      <div v-else class="editor-items">
        <div v-for="(it, i) in editor.items" :key="i" class="ei-row">
          <span class="ei-order">{{ i + 1 }}</span>
          <el-tag size="small" :type="typeTag(it.item_type)">{{ typeLabel(it.item_type) }}</el-tag>
          <span class="ei-name">{{ it.title || it.url || it.file_name || '未命名条目' }}</span>
          <span class="ei-min">{{ it.estimated_minutes || 60 }} 分钟</span>
          <el-switch v-model="it.required" size="small" active-text="必修" inline-prompt />
          <div class="ei-ops">
            <el-button size="small" text :disabled="i === 0" @click="moveItem(i, -1)">上移</el-button>
            <el-button size="small" text :disabled="i === editor.items.length - 1" @click="moveItem(i, 1)">下移</el-button>
            <el-button size="small" text type="danger" @click="editor.items.splice(i, 1)">删除</el-button>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="editor.visible = false">取消</el-button>
        <el-button type="primary" :loading="editor.saving" @click="saveTemplate">保存模板</el-button>
      </template>
    </el-dialog>

    <!-- ── 添加条目 ───────────────────────────────────────── -->
    <el-dialog v-model="itemDlg" title="添加学习条目" width="560px" append-to-body>
      <el-form label-width="90px">
        <el-form-item label="条目类型">
          <el-radio-group v-model="itemForm.item_type" @change="resetItemPickers">
            <el-radio-button value="course">课程</el-radio-button>
            <el-radio-button value="chapter">章节</el-radio-button>
            <el-radio-button value="knowledge_point">知识点</el-radio-button>
            <el-radio-button value="link">外链</el-radio-button>
            <el-radio-button value="text">富文本</el-radio-button>
            <el-radio-button value="file">附件</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="['course', 'chapter', 'knowledge_point'].includes(itemForm.item_type)" label="专业">
          <el-select v-model="picker.majorId" filterable placeholder="选择专业" style="width: 100%" @change="loadPickerCourses">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="['course', 'chapter', 'knowledge_point'].includes(itemForm.item_type)" label="课程" required>
          <el-select v-model="picker.courseId" filterable placeholder="选择课程" style="width: 100%"
            :disabled="!picker.majorId" @change="loadPickerChapters">
            <el-option v-for="c in picker.courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="['chapter', 'knowledge_point'].includes(itemForm.item_type)" label="章节" required>
          <el-select v-model="picker.chapterId" filterable placeholder="选择章节" style="width: 100%"
            :disabled="!picker.courseId" @change="loadPickerKps">
            <el-option v-for="c in picker.chapters" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="itemForm.item_type === 'knowledge_point'" label="知识点" required>
          <el-select v-model="picker.kpId" filterable placeholder="选择知识点" style="width: 100%"
            :disabled="!picker.chapterId">
            <el-option v-for="k in picker.kps" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
        </el-form-item>

        <el-form-item v-if="itemForm.item_type === 'link'" label="链接地址" required>
          <el-input v-model="itemForm.url" placeholder="https://..." maxlength="500" />
        </el-form-item>
        <el-form-item v-if="itemForm.item_type === 'text'" label="文字内容" required>
          <el-input v-model="itemForm.content" type="textarea" :rows="4" maxlength="5000" show-word-limit
            placeholder="写清这一步要学什么、看哪些要点" />
        </el-form-item>
        <el-form-item v-if="itemForm.item_type === 'file'" label="附件" required>
          <el-upload :show-file-list="false" :http-request="uploadItemFile">
            <el-button size="small" :loading="itemUploading">
              {{ itemForm.file_name ? '重新上传' : '选择文件上传' }}
            </el-button>
          </el-upload>
          <div v-if="itemForm.file_name" class="form-hint">
            已上传：{{ itemForm.original_name || itemForm.file_name }}
            <el-link type="primary" :href="'/uploads/' + itemForm.file_name" target="_blank" rel="noopener">查看</el-link>
          </div>
        </el-form-item>

        <el-form-item label="展示标题">
          <el-input v-model="itemForm.title" maxlength="200" placeholder="留空则用课程/章节/知识点名称" />
        </el-form-item>
        <el-form-item label="预计分钟">
          <el-input-number v-model="itemForm.estimated_minutes" :min="5" :max="1200" :step="10" />
          <el-checkbox v-model="itemForm.required" style="margin-left: 16px">必修</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="itemDlg = false">取消</el-button>
        <el-button type="primary" :loading="itemAdding" @click="addItem">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()

const activeTab = ref('catalog')
const majors = ref([])

// ── 专业课程库 ──────────────────────────────────────────
const catalog = ref({ majors: [], totals: {} })
const catalogKw = ref('')
const catalogLoading = ref(false)
const openMajors = ref([])

const catalogStats = computed(() => {
  const t = catalog.value.totals || {}
  return [
    { label: '专业', value: t.majors || 0 },
    { label: '课程', value: t.courses || 0 },
    { label: '章节', value: t.chapters || 0 },
    { label: '知识点', value: t.knowledge_points || 0 },
  ]
})

const loadCatalog = async () => {
  catalogLoading.value = true
  try {
    const res = await request.get('/api/learning/plan-templates/catalog',
      { params: { q: catalogKw.value || undefined } })
    catalog.value = res.data || { majors: [], totals: {} }
    // 默认展开第一个专业，避免一屏全折叠看不出有内容
    if (!openMajors.value.length && catalog.value.majors.length) {
      openMajors.value = [String(catalog.value.majors[0].id)]
    }
  } catch (e) {
    catalog.value = { majors: [], totals: {} }
  }
  catalogLoading.value = false
}

// ── 模板列表 ────────────────────────────────────────────
const listTabs = [
  { name: 'market', label: '模板库' },
  { name: 'mine', label: '我的模板' },
]
const filters = reactive({ q: '', major_id: null, type: '' })
const marketList = ref([])
const mineList = ref([])
const listTotal = ref(0)
const listLoading = ref(false)

const currentList = computed(() => (activeTab.value === 'mine' ? mineList.value : marketList.value))

const loadTemplates = async () => {
  const scope = activeTab.value === 'mine' ? 'mine' : 'market'
  listLoading.value = true
  try {
    const res = await request.get('/api/learning/plan-templates', {
      params: {
        scope,
        q: filters.q || undefined,
        major_id: filters.major_id || undefined,
        type: filters.type || undefined,
        per_page: 100,
      }
    })
    if (scope === 'mine') mineList.value = res.data.items || []
    else marketList.value = res.data.items || []
    listTotal.value = res.data.total || 0
  } catch (e) { /* 拦截器已提示 */ }
  listLoading.value = false
}

const onTabChange = (name) => {
  if (name !== 'catalog') loadTemplates()
}

// ── 详情 ────────────────────────────────────────────────
const detailDlg = ref(false)
const detail = ref(null)

const viewTemplate = async (t) => {
  try {
    const res = await request.get(`/api/learning/plan-templates/${t.id}`)
    detail.value = res.data
    detailDlg.value = true
  } catch (e) { /* 拦截器已提示 */ }
}

// ── 使用模板 ────────────────────────────────────────────
const useDlg = ref(false)
const useTarget = ref(null)
const useMajorId = ref(null)
const useTitle = ref('')
const using = ref(false)

const askUse = (t) => {
  useTarget.value = t
  useMajorId.value = t.major_id || null
  useTitle.value = ''
  useDlg.value = true
}

const doUse = async () => {
  if (!useMajorId.value) {
    ElMessage.warning('请选择所属专业')
    return
  }
  using.value = true
  try {
    const res = await request.post(`/api/learning/plan-templates/${useTarget.value.id}/use`, {
      major_id: useMajorId.value,
      title: useTitle.value || undefined,
    })
    ElMessage.success(res.data.message || '已生成学习路径')
    useDlg.value = false
    detailDlg.value = false
    router.push(`/learning/paths/${res.data.path_id}`)
  } catch (e) { /* 拦截器已提示 */ }
  using.value = false
}

// ── 编辑器 ──────────────────────────────────────────────
const emptyForm = () => ({
  title: '', description: '', major_id: null,
  template_type: 'structured', visibility: 'private',
  difficulty: 'medium', target_hours: null,
})
const editor = reactive({ visible: false, id: null, saving: false, form: emptyForm(), items: [] })

const openCreate = (preset = {}) => {
  editor.id = null
  editor.form = { ...emptyForm(), major_id: preset.major_id || null }
  editor.items = (preset.items || []).map(it => ({
    item_type: it.item_type, title: it.title || '',
    course_id: it.course_id || null, chapter_id: it.chapter_id || null,
    knowledge_point_id: it.knowledge_point_id || null,
    url: it.url || '', content: it.content || '',
    file_name: it.file_name || null, file_size: it.file_size || null,
    required: it.required !== false,
    estimated_minutes: it.estimated_minutes || 60,
  }))
  editor.visible = true
}

const openEdit = async (t) => {
  try {
    const res = await request.get(`/api/learning/plan-templates/${t.id}`)
    const d = res.data
    editor.id = d.id
    editor.form = {
      title: d.title, description: d.description || '',
      major_id: d.major_id, template_type: d.template_type,
      visibility: d.visibility, difficulty: d.difficulty || 'medium',
      target_hours: d.target_hours,
    }
    editor.items = (d.items || []).map(it => ({
      item_type: it.item_type, title: it.raw_title || '',
      course_id: it.course_id, chapter_id: it.chapter_id,
      knowledge_point_id: it.knowledge_point_id,
      url: it.url || '', content: it.content || '',
      file_name: it.file_name, file_size: it.file_size,
      required: it.required,
      estimated_minutes: it.estimated_minutes || 60,
    }))
    editor.visible = true
  } catch (e) { /* 拦截器已提示 */ }
}

const saveTemplate = async () => {
  if (!editor.form.title.trim()) {
    ElMessage.warning('请填写模板标题')
    return
  }
  editor.saving = true
  const payload = { ...editor.form, items: editor.items }
  try {
    if (editor.id) {
      await request.put(`/api/learning/plan-templates/${editor.id}`, payload)
    } else {
      await request.post('/api/learning/plan-templates', payload)
    }
    ElMessage.success('模板已保存')
    editor.visible = false
    if (activeTab.value === 'catalog') activeTab.value = 'mine'
    await loadTemplates()
  } catch (e) { /* 拦截器已提示 */ }
  editor.saving = false
}

const removeTemplate = async (t) => {
  try {
    await ElMessageBox.confirm(
      `删除模板「${t.title}」？已用它生成的学习路径不受影响。`, '删除模板',
      { type: 'warning' })
  } catch (e) { return }
  try {
    await request.delete(`/api/learning/plan-templates/${t.id}`)
    ElMessage.success('模板已删除')
    loadTemplates()
  } catch (e) { /* 拦截器已提示 */ }
}

const moveItem = (idx, delta) => {
  const target = idx + delta
  if (target < 0 || target >= editor.items.length) return
  const list = editor.items
  const [it] = list.splice(idx, 1)
  list.splice(target, 0, it)
}

// ── 添加条目 ────────────────────────────────────────────
const itemDlg = ref(false)
const itemAdding = ref(false)
const itemUploading = ref(false)
const emptyItemForm = () => ({
  item_type: 'course', title: '', url: '', content: '',
  file_name: null, original_name: '', file_size: null,
  required: true, estimated_minutes: 60,
})
const itemForm = reactive(emptyItemForm())
const picker = reactive({ majorId: null, courseId: null, chapterId: null, kpId: null, courses: [], chapters: [], kps: [] })

const openItemDlg = () => {
  Object.assign(itemForm, emptyItemForm())
  resetItemPickers()
  itemDlg.value = true
}

const resetItemPickers = () => {
  picker.majorId = editor.form.major_id || null
  picker.courseId = null
  picker.chapterId = null
  picker.kpId = null
  picker.courses = []
  picker.chapters = []
  picker.kps = []
  if (picker.majorId) loadPickerCourses(picker.majorId)
}

const loadPickerCourses = async (majorId) => {
  picker.courseId = null
  picker.chapterId = null
  picker.kpId = null
  picker.chapters = []
  picker.kps = []
  picker.courses = []
  if (!majorId) return
  try {
    const res = await request.get('/api/courses', { params: { major_id: majorId } })
    picker.courses = res.data || []
  } catch (e) { /* 拦截器已提示 */ }
}

const loadPickerChapters = async (courseId) => {
  picker.chapterId = null
  picker.kpId = null
  picker.kps = []
  picker.chapters = []
  if (!courseId) return
  try {
    const res = await request.get('/api/chapters', { params: { course_id: courseId } })
    picker.chapters = res.data || []
  } catch (e) { /* 拦截器已提示 */ }
}

const loadPickerKps = async (chapterId) => {
  picker.kpId = null
  picker.kps = []
  if (!chapterId) return
  try {
    const res = await request.get('/api/learning/knowledge-points', { params: { chapter_id: chapterId } })
    picker.kps = res.data || []
  } catch (e) { /* 拦截器已提示 */ }
}

const uploadItemFile = async (options) => {
  const fd = new FormData()
  fd.append('file', options.file)
  itemUploading.value = true
  try {
    const res = await request.post('/api/learning/plan-templates/upload', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } })
    itemForm.file_name = res.data.file_name
    itemForm.original_name = res.data.original_name
    itemForm.file_size = res.data.file_size
    if (!itemForm.title) itemForm.title = res.data.original_name
    ElMessage.success('附件已上传')
  } catch (e) { /* 拦截器已提示 */ }
  itemUploading.value = false
}

const addItem = () => {
  const t = itemForm.item_type
  const item = {
    item_type: t, title: itemForm.title || '',
    required: itemForm.required,
    estimated_minutes: itemForm.estimated_minutes || 60,
    url: '', content: '', file_name: null, file_size: null,
    course_id: null, chapter_id: null, knowledge_point_id: null,
  }
  if (t === 'course' || t === 'chapter' || t === 'knowledge_point') {
    if (!picker.courseId) { ElMessage.warning('请选择课程'); return }
    item.course_id = picker.courseId
  }
  if (t === 'chapter' || t === 'knowledge_point') {
    if (!picker.chapterId) { ElMessage.warning('请选择章节'); return }
    item.chapter_id = picker.chapterId
    item.course_id = null
  }
  if (t === 'knowledge_point') {
    if (!picker.kpId) { ElMessage.warning('请选择知识点'); return }
    item.knowledge_point_id = picker.kpId
    item.chapter_id = null
  }
  if (t === 'link') {
    if (!itemForm.url.trim()) { ElMessage.warning('请填写链接地址'); return }
    item.url = itemForm.url.trim()
  }
  if (t === 'text') {
    if (!itemForm.content.trim()) { ElMessage.warning('请填写文字内容'); return }
    item.content = itemForm.content.trim()
  }
  if (t === 'file') {
    if (!itemForm.file_name) { ElMessage.warning('请先上传附件'); return }
    item.file_name = itemForm.file_name
    item.file_size = itemForm.file_size
  }
  editor.items.push(item)
  itemDlg.value = false
}

// ── 展示工具 ────────────────────────────────────────────
const typeLabel = (t) => ({
  course: '课程', chapter: '章节', knowledge_point: '知识点',
  link: '外链', text: '富文本', file: '附件',
}[t] || t)

const typeTag = (t) => ({
  course: 'primary', chapter: 'success', knowledge_point: 'warning',
  link: 'info', text: 'info', file: 'danger',
}[t] || 'info')

const diffLabel = (d) => ({ easy: '简单', medium: '中等', hard: '困难' }[d] || d || '中等')

const formatMinutes = (m) => {
  const v = Number(m || 0)
  if (v < 60) return `${v} 分钟`
  const h = Math.floor(v / 60)
  const rest = v % 60
  return rest ? `${h} 小时 ${rest} 分钟` : `${h} 小时`
}

const loadMajors = async () => {
  try {
    const res = await request.get('/api/majors')
    majors.value = res.data || []
  } catch (e) { majors.value = [] }
}

onMounted(() => {
  loadMajors()
  loadCatalog()
})
</script>

<style scoped>
.repo-page {
  padding: 20px;
  max-width: 1240px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.page-title {
  font-size: 26px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--text-primary);
}

.page-subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
}

.stat-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.stat-chip {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 8px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.stat-num {
  font-size: 20px;
  font-weight: 700;
  color: var(--brand-primary, #06b6d4);
}

.stat-label {
  font-size: 13px;
  color: var(--text-muted);
}

.major-name {
  font-size: 15px;
  font-weight: 600;
  margin-right: 10px;
  color: var(--text-primary);
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  padding: 4px 0 8px;
}

.course-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cc-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.cc-name {
  font-weight: 600;
  color: var(--text-primary);
}

.cc-desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 36px;
}

.cc-meta {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: var(--text-muted);
}

.cc-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: auto;
}

.filter-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.filter-count {
  margin-left: auto;
  font-size: 13px;
  color: var(--text-muted);
}

.tpl-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.tpl-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tc-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.tc-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.tc-desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
  min-height: 38px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tc-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.tc-meta {
  display: flex;
  gap: 14px;
  font-size: 12px;
  color: var(--text-muted);
}

.tc-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  border-top: 1px dashed var(--border-color);
  padding-top: 10px;
  margin-top: auto;
}

.tc-owner {
  font-size: 12px;
  color: var(--text-muted);
}

.tc-ops {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
}

.detail-desc {
  margin: 0 0 10px;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 16px;
}

.detail-item {
  display: flex;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px dashed var(--border-color);
}

.di-order {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--brand-primary, #06b6d4);
  color: #fff;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.di-body {
  flex: 1;
  min-width: 0;
}

.di-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.di-title {
  font-weight: 600;
  color: var(--text-primary);
}

.di-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 4px;
}

.di-content {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary, var(--text-muted));
  white-space: pre-wrap;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 16px;
}

.editor-items-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 4px 0 10px;
}

.ei-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.editor-items {
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.ei-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px dashed var(--border-color);
}

.ei-row:last-child {
  border-bottom: none;
}

.ei-order {
  width: 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.ei-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--text-primary);
}

.ei-min {
  font-size: 12px;
  color: var(--text-muted);
}

.ei-ops {
  display: flex;
  gap: 0;
}

.form-hint {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
}
</style>
