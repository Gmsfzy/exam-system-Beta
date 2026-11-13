 <template>
  <div class="my-knowledge">
    <div class="page-header">
      <div>
        <h1 class="page-title">我的知识库</h1>
        <p class="page-subtitle">你积累下来的知识点 · 总结笔记 · 熟悉程度 · 温习提醒 · 关联文档</p>
      </div>
      <div class="header-right">
        <el-tag v-if="total" type="info" effect="plain">共 {{ total }} 个知识点</el-tag>
        <el-radio-group v-model="mode" size="default">
          <el-radio-button value="list">列表</el-radio-button>
          <el-radio-button value="map">掌握地图</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <!-- 本页是个人知识资产库，不充当练习入口：空态只说明“积累从哪来”，不往刷题引 -->
    <el-empty v-if="!loading && !total"
              description="还没有积累：在专业路径学过、写过总结的知识点会收录在这里" :image-size="80">
      <el-button type="primary" @click="$router.push('/learning/paths')">去学习路径</el-button>
      <el-button @click="$router.push('/learning/materials')">去资料库</el-button>
    </el-empty>

    <template v-else>
      <!-- 列表模式 -->
      <div v-if="mode === 'list'" v-loading="loading" class="list-layout">
        <div class="panel tree-panel">
          <el-tree ref="treeRef" :data="treeData" node-key="key" highlight-current default-expand-all
                   :expand-on-click-node="false" @node-click="onTreeClick">
            <template #default="{ data: node }">
              <span class="tree-node">
                <span class="tree-label">{{ node.label }}</span>
                <span v-if="node.count != null" class="tree-count">{{ node.count }}</span>
              </span>
            </template>
          </el-tree>
        </div>

        <div class="cards-area">
          <div v-if="!filteredKps.length" class="panel"><el-empty :image-size="52" description="该范围暂无知识点" /></div>
          <div class="kp-grid">
            <div v-for="kp in filteredKps" :key="kp.knowledge_point_id" class="panel kp-card">
              <div class="kp-top">
                <el-progress type="circle" :width="58" :stroke-width="5"
                             :percentage="Math.round(kp.mastery_shown)" :color="masteryColor(kp.mastery_shown)" />
                <div class="kp-info">
                  <div class="kp-name" :title="kp.name">{{ kp.name }}</div>
                  <div class="kp-tags">
                    <el-tag size="small" :type="statusType(kp.level_status)" effect="plain">
                      {{ statusLabel(kp.level_status) }}
                    </el-tag>
                    <el-tag v-if="kp.decay_risk" size="small" type="danger">⚠ 需温习</el-tag>
                  </div>
                </div>
              </div>
              <div class="kp-note" :class="{ empty: !kp.note_excerpt }" @click="openNote(kp)">
                <template v-if="kp.note_excerpt">
                  <el-icon size="13"><Notebook /></el-icon> {{ kp.note_excerpt }}
                </template>
                <template v-else>＋ 点击为此知识点写总结笔记</template>
              </div>
              <!-- 知识库↔资料库：同一个知识点下沉的教案/讲义/总结就地可看，不必去资料库再找 -->
              <div v-if="kp.material_count" class="kp-mats">
                <span class="kp-mats-head" @click="toggleMats(kp)">
                  <el-icon size="13"><Tickets /></el-icon>
                  关联文档 {{ kp.material_count }} 份
                  <span class="kp-mats-caret">{{ isExpanded(kp) ? '▲' : '▼' }}</span>
                </span>
                <ul v-if="isExpanded(kp)" class="kp-mats-list">
                  <li v-for="m in kp.materials" :key="m.id" @click="openMaterial(m)">
                    <em class="mat-kind">{{ KINDS[m.kind] || m.kind }}</em>
                    <span class="mat-title" :title="m.title">{{ m.title }}</span>
                  </li>
                  <li v-if="kp.material_count > (kp.materials || []).length" class="kp-mats-more"
                      @click="$router.push('/learning/materials')">
                    共 {{ kp.material_count }} 份，到资料库看全部 →
                  </li>
                </ul>
              </div>
              <div class="kp-foot">
                <span class="kp-time">{{ kp.last_verified_at ? '上次学习 ' + kp.last_verified_at.slice(0, 10) : '尚未学习' }}</span>
                <el-button size="small" text type="primary" @click="openNote(kp)">
                  {{ kp.has_note ? '编辑笔记' : '写笔记' }}
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 掌握地图模式 -->
      <div v-else class="map-layout">
        <div class="map-toolbar panel">
          <span class="map-label">专业范围</span>
          <el-select v-model="mapMajorId" size="small" style="width: 220px" @change="loadGraph">
            <el-option v-for="m in majors" :key="m.major_id" :label="m.major_name" :value="m.major_id" />
          </el-select>
          <div class="legend">
            <span class="legend-item"><i style="background:#ef4444"></i>生疏</span>
            <span class="legend-item"><i style="background:#f59e0b"></i>学习中</span>
            <span class="legend-item"><i style="background:#10b981"></i>已掌握</span>
            <span class="legend-item"><i style="background:#94a3b8"></i>未学习</span>
            <span class="legend-item"><i class="ring"></i>⚠ 需温习</span>
          </div>
        </div>
        <div class="panel graph-panel" v-loading="graphLoading">
          <KnowledgeGraph :nodes="graph.nodes" :edges="graph.edges" :mastery="true" height="600px"
                          @node-tap="onGraphTap" />
        </div>
      </div>
    </template>

    <!-- 笔记编辑弹窗 -->
    <el-dialog v-model="noteVisible" :title="`笔记：${noteKp?.name || ''}`" width="620px" destroy-on-close>
      <el-input v-model="noteText" type="textarea" :rows="10" maxlength="5000" show-word-limit
                placeholder="用自己的话总结这个知识点：核心概念、常见误区、记忆方法…（仅自己可见）" />
      <div class="note-toolbar">
        <el-button size="small" type="primary" plain :loading="polishing" @click="polishNote">
          <el-icon><MagicStick /></el-icon>&nbsp;AI 润色提炼
        </el-button>
        <span class="note-tip">润色基于当前输入，保留原意仅做结构化整理</span>
      </div>
      <template #footer>
        <el-button @click="noteVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveNote">保存</el-button>
      </template>
    </el-dialog>

    <!-- 文档预览：就地读完整内容，与资料库同一个渲染器 -->
    <el-dialog v-model="matVisible" :title="mat?.title" width="760px" top="6vh" destroy-on-close>
      <div v-if="mat" class="mat-head">
        <el-tag size="small" effect="plain">{{ KINDS[mat.kind] || mat.kind }}</el-tag>
        <span class="mat-head-meta">{{ mat.updated_at ? '更新于 ' + mat.updated_at.slice(0, 10) : '' }}</span>
        <el-button size="small" text type="primary" @click="matVisible = false">收起</el-button>
      </div>
      <el-scrollbar max-height="60vh">
        <MdView :content="mat?.content || ''" />
      </el-scrollbar>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import request from '../utils/request'
import KnowledgeGraph from '../components/KnowledgeGraph.vue'
import MdView from '../components/MdView.vue'

const KINDS = { video_script: '视频脚本', mindmap: '思维导图', lesson_plan: '教案', lecture: '讲解稿', summary: '总结要点', quiz: '自测题组', manual: '手写' }

const loading = ref(false)
const mode = ref('list')
const majors = ref([])
const total = ref(0)

// ── 数据加载：majors→courses→chapters→kps 层级 ──────────────────
async function load() {
  loading.value = true
  try {
    const res = await request.get('/api/learning/my-knowledge')
    majors.value = res.data.majors || []
    total.value = res.data.total || 0
    if (mapMajorId.value == null && majors.value.length) {
      mapMajorId.value = majors.value[0].major_id
    }
  } catch (e) { /* ignore */ }
  loading.value = false
}
onMounted(load)

// 左树数据
const treeData = computed(() => majors.value.map(m => ({
  key: `m-${m.major_id}`, label: m.major_name, scope: { majorId: m.major_id },
  count: countKps(m),
  children: (m.courses || []).map(c => ({
    key: `c-${c.course_id}`, label: c.name, scope: { majorId: m.major_id, courseId: c.course_id },
    count: (c.chapters || []).reduce((s, h) => s + h.knowledge_points.length, 0),
    children: (c.chapters || []).map(h => ({
      key: `h-${h.chapter_id}`, label: h.name,
      scope: { majorId: m.major_id, courseId: c.course_id, chapterId: h.chapter_id },
      count: h.knowledge_points.length,
    })),
  })),
})))

function countKps(m) {
  return (m.courses || []).reduce((s, c) =>
    s + (c.chapters || []).reduce((s2, h) => s2 + h.knowledge_points.length, 0), 0)
}

// 树筛选
const scope = ref(null)
function onTreeClick(node) { scope.value = node.scope || null }

const filteredKps = computed(() => {
  const s = scope.value
  const out = []
  for (const m of majors.value) {
    if (s && s.majorId && m.major_id !== s.majorId) continue
    for (const c of m.courses || []) {
      if (s && s.courseId && c.course_id !== s.courseId) continue
      for (const h of c.chapters || []) {
        if (s && s.chapterId && h.chapter_id !== s.chapterId) continue
        out.push(...h.knowledge_points)
      }
    }
  }
  return out
})

function masteryColor(v) {
  if (v >= 80) return '#10b981'
  if (v > 0) return '#f59e0b'
  return '#cbd5e1'
}
function statusLabel(s) { return { mastered: '已掌握', learning: '学习中', untouched: '未触达' }[s] || s }
function statusType(s) { return { mastered: 'success', learning: 'warning', untouched: 'info' }[s] || 'info' }

// ── 笔记编辑 + AI 润色 ─────────────────────────────────────────
const noteVisible = ref(false)
const noteKp = ref(null)
const noteText = ref('')
const saving = ref(false)
const polishing = ref(false)

async function openNote(kp) {
  noteKp.value = kp
  noteVisible.value = true
  noteText.value = ''
  try {
    const res = await request.get('/api/learning/kp-notes', { params: { knowledge_point_id: kp.knowledge_point_id } })
    noteText.value = res.data.content || ''
  } catch (e) { /* ignore */ }
}

async function saveNote() {
  if (!noteKp.value) return
  saving.value = true
  try {
    await request.put(`/api/learning/kp-notes/${noteKp.value.knowledge_point_id}`, { content: noteText.value })
    ElMessage.success('笔记已保存')
    noteVisible.value = false
    await load()
  } catch (e) { /* ignore */ }
  saving.value = false
}

async function polishNote() {
  if (!noteText.value.trim()) { ElMessage.warning('请先输入笔记内容'); return }
  if (!noteKp.value) return
  polishing.value = true
  try {
    const res = await request.post(`/api/learning/kp-notes/${noteKp.value.knowledge_point_id}/ai-polish`,
      { content: noteText.value })
    noteText.value = res.data.polished
    ElMessage.success('已用 AI 润色结果替换草稿')
  } catch (e) { /* 拦截器已提示（AI 不可用时后端返回 500 + 提示语） */ }
  polishing.value = false
}

// ── 掌握地图 ───────────────────────────────────────────────────
const mapMajorId = ref(null)
const graph = ref({ nodes: [], edges: [] })
const graphLoading = ref(false)

async function loadGraph() {
  if (!mapMajorId.value) return
  graphLoading.value = true
  try {
    const res = await request.get('/api/learning/knowledge-graph',
      { params: { major_id: mapMajorId.value, mine: 1 } })
    graph.value = res.data
  } catch (e) { /* ignore */ }
  graphLoading.value = false
}

watch(mode, (m) => { if (m === 'map' && !graph.value.nodes.length) loadGraph() })

function onGraphTap(node) {
  if (node && node.id && node.name) {
    openNote({ knowledge_point_id: node.id, name: node.name, has_note: node.has_note })
  }
}

// ── 关联文档（知识库↔资料库）───────────────────────────
// 展开态用 Set 记 kp id（只存本地视图状态，不随后端数据走），默认全闭合不堆长列表
const expanded = ref(new Set())
const matVisible = ref(false)
const mat = ref(null)

function toggleMats(kp) {
  const s = new Set(expanded.value)
  if (s.has(kp.knowledge_point_id)) s.delete(kp.knowledge_point_id)
  else s.add(kp.knowledge_point_id)
  expanded.value = s
}
function isExpanded(kp) {
  return expanded.value.has(kp.knowledge_point_id)
}

async function openMaterial(m) {
  try {
    const res = await request.get(`/api/learning/materials/${m.id}`)
    mat.value = res.data.material
    matVisible.value = true
  } catch (e) { /* 拦截器已提示 */ }
}
</script>

<style scoped>
.my-knowledge { padding: 20px; max-width: 1200px; }

.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.page-title { font-size: 26px; font-weight: 700; margin: 0 0 6px; color: var(--text-primary); }
.page-subtitle { font-size: 13px; color: var(--text-muted); margin: 0; }
.header-right { display: flex; align-items: center; gap: 14px; }

.panel { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 14px; }

.list-layout { display: grid; grid-template-columns: 250px 1fr; gap: 16px; align-items: start; }
.tree-panel { padding: 12px 8px; max-height: 72vh; overflow: auto; position: sticky; top: 16px; }
.tree-node { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.tree-count { font-size: 11px; color: var(--text-muted); background: var(--bg-tertiary); border-radius: 8px; padding: 0 6px; }

.kp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 14px; }
.kp-card { padding: 16px; display: flex; flex-direction: column; gap: 10px; }
.kp-top { display: flex; gap: 12px; align-items: center; }
.kp-info { flex: 1; min-width: 0; }
.kp-name { font-size: 14px; font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-bottom: 6px; }
.kp-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.kp-note {
  font-size: 12px; color: var(--text-secondary, var(--text-muted)); background: var(--bg-tertiary);
  border-radius: 8px; padding: 8px 10px; cursor: pointer; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  min-height: 34px;
}
.kp-note.empty { color: var(--text-muted); opacity: 0.8; }
.kp-note:hover { outline: 1px solid var(--primary-color, #6366f1); }
.kp-mats { font-size: 12px; }
.kp-mats-head { display: flex; align-items: center; gap: 5px; color: var(--text-secondary, var(--text-muted)); cursor: pointer; }
.kp-mats-head:hover { color: var(--primary-color, #6366f1); }
.kp-mats-caret { margin-left: auto; font-size: 10px; opacity: 0.7; }
.kp-mats-list { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.kp-mats-list li {
  display: flex; align-items: center; gap: 6px; cursor: pointer;
  background: var(--bg-tertiary); border-radius: 6px; padding: 4px 8px;
}
.kp-mats-list li:hover { outline: 1px solid var(--primary-color, #6366f1); }
.mat-kind {
  font-style: normal; font-size: 10px; flex: none; padding: 0 5px; border-radius: 4px;
  background: var(--bg-card); border: 1px solid var(--border-color); color: var(--text-muted);
}
.mat-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); }
.kp-mats-more { color: var(--text-muted); font-size: 11px; justify-content: center; }
.kp-foot { display: flex; justify-content: space-between; align-items: center; }
.kp-time { font-size: 11px; color: var(--text-muted); }

.mat-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.mat-head-meta { font-size: 12px; color: var(--text-muted); }

.map-layout { display: flex; flex-direction: column; gap: 14px; }
.map-toolbar { display: flex; align-items: center; gap: 12px; padding: 12px 16px; }
.map-label { font-size: 13px; color: var(--text-muted); }
.legend { display: flex; gap: 12px; margin-left: auto; flex-wrap: wrap; }
.legend-item { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-muted); }
.legend-item i { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.legend-item i.ring { background: transparent; border: 2px solid #ef4444; }
.graph-panel { padding: 8px; }

.note-toolbar { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.note-tip { font-size: 12px; color: var(--text-muted); }

@media (max-width: 900px) {
  .list-layout { grid-template-columns: 1fr; }
  .tree-panel { position: static; max-height: 220px; }
}
</style>
