<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-left">
        <el-button text @click="goBack" class="back-btn">
          <el-icon :size="20"><ArrowLeft /></el-icon>
          <span>返回</span>
        </el-button>
        <div class="header-info">
          <h2>章节管理 - {{ courseName }}</h2>
          <p>{{ majorName }} - {{ departmentName }}</p>
        </div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openChapterDialog">
          <el-icon><Plus /></el-icon>添加章节
        </el-button>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
          <el-icon :size="24" color="white"><Notebook /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ chapters.length }}</div>
          <div class="stat-label">章节数量</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%)">
          <el-icon :size="24" color="white"><Document /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ totalQuestions }}</div>
          <div class="stat-label">题目数量</div>
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-header">
        <h3>章节列表</h3>
      </div>
      <div v-if="chapters.length" class="chapter-list">
        <div v-for="chapter in chapters" :key="chapter.id" class="chapter-card">
          <div class="chapter-header">
            <div class="chapter-title">
              <el-icon :size="18" class="title-icon"><Notebook /></el-icon>
              <span>{{ chapter.name }}</span>
            </div>
            <el-dropdown @command="cmd => handleChapterAction(cmd, chapter)">
              <el-icon class="more-icon"><More /></el-icon>
            </el-dropdown>
          </div>
          <p v-if="chapter.description" class="chapter-desc">{{ chapter.description }}</p>
          <div class="chapter-meta">
            <span class="meta-tag">{{ getChapterQuestionCount(chapter.id) }} 道题目</span>
          </div>
          <div class="chapter-actions">
            <el-button text @click="viewChapterQuestions(chapter.id)">
              <el-icon><Document /></el-icon>查看题目
            </el-button>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <el-icon :size="48" class="empty-icon"><Notebook /></el-icon>
        <p>暂无章节</p>
        <p class="empty-hint">您可以点击上方按钮添加章节，也可以跳过章节管理直接创建题目</p>
      </div>
    </div>

    <el-dialog v-model="chapterDialogVisible" :title="isEditChapter ? '编辑章节' : '添加章节'" width="500px">
      <el-form :model="chapterForm" label-width="80px">
        <el-form-item label="章节名称">
          <el-input v-model="chapterForm.name" placeholder="请输入章节名称" />
        </el-form-item>
        <el-form-item label="章节描述">
          <el-input v-model="chapterForm.description" type="textarea" rows="3" placeholder="请输入章节描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="chapterDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveChapter" :loading="saving">
          {{ isEditChapter ? '保存修改' : '确认添加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { useRoute, useRouter } from "vue-router"
import request from "../utils/request"
import { ElMessage, ElMessageBox } from "element-plus"
import { ArrowLeft, Plus, More, Notebook, Document } from "@element-plus/icons-vue"

const route = useRoute()
const router = useRouter()

const courseId = ref(0)
const courseName = ref("")
const majorName = ref("")
const departmentName = ref("")
const chapters = ref([])
const questions = ref([])
const chapterDialogVisible = ref(false)
const isEditChapter = ref(false)
const saving = ref(false)

const chapterForm = ref({ id: null, name: "", description: "" })

const totalQuestions = computed(() => questions.value.length)

const getChapterQuestionCount = (chapterId) => {
  return questions.value.filter(q => q.chapter_id === chapterId).length
}

const goBack = () => {
  router.back()
}

const openChapterDialog = (chapter = null) => {
  if (chapter) {
    isEditChapter.value = true
    chapterForm.value = { ...chapter }
  } else {
    isEditChapter.value = false
    chapterForm.value = { id: null, name: "", description: "" }
  }
  chapterDialogVisible.value = true
}

const saveChapter = async () => {
  if (!chapterForm.value.name.trim()) {
    ElMessage.warning("请输入章节名称")
    return
  }
  saving.value = true
  try {
    const data = { ...chapterForm.value, course_id: courseId.value }
    if (isEditChapter.value) {
      await request.put(`/api/chapters/${chapterForm.value.id}`, data)
      ElMessage.success("更新成功")
    } else {
      await request.post("/api/chapters", data)
      ElMessage.success("添加成功")
    }
    chapterDialogVisible.value = false
    fetchChapters()
  } catch (e) {
    console.error(e)
  } finally {
    saving.value = false
  }
}

const deleteChapter = async (id) => {
  try {
    await ElMessageBox.confirm("确定删除该章节吗？", "提示", { type: "warning" })
    await request.delete(`/api/chapters/${id}`)
    ElMessage.success("删除成功")
    fetchChapters()
    fetchQuestions()
  } catch (e) {
    if (e !== "cancel") console.error(e)
  }
}

const handleChapterAction = (cmd, chapter) => {
  if (cmd === "edit") {
    openChapterDialog(chapter)
  } else if (cmd === "delete") {
    deleteChapter(chapter.id)
  }
}

const viewChapterQuestions = (chapterId) => {
  router.push(`/questions?chapter=${chapterId}`)
}

const getCourseId = () => {
  const id = String(route.params.id).split("/")[0]
  return parseInt(id) || 0
}

const fetchCourseInfo = async () => {
  const id = getCourseId()
  if (!id) return
  const res = await request.get(`/api/courses/${id}`)
  courseId.value = id
  courseName.value = res.data.name
  if (res.data.major) {
    majorName.value = res.data.major.name
    if (res.data.major.department) {
      departmentName.value = res.data.major.department.name
    }
  }
}

const fetchChapters = async () => {
  const id = getCourseId()
  if (!id) return
  const res = await request.get(`/api/chapters?course_id=${id}`)
  chapters.value = res.data
}

const fetchQuestions = async () => {
  const id = getCourseId()
  if (!id) return
  const res = await request.get("/api/questions")
  questions.value = res.data.filter(q => q.course_id === id)
}

onMounted(() => {
  fetchCourseInfo()
  fetchChapters()
  fetchQuestions()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e2e8f0;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.header-info h2 {
  margin: 0 0 4px 0;
  font-size: 24px;
  color: #1e293b;
}
.header-info p {
  margin: 0;
  color: #64748b;
  font-size: 14px;
}
.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
.stat-card {
  background: white;
  border-radius: 12px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.stat-info {
  flex: 1;
}
.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}
.stat-label {
  font-size: 14px;
  color: #64748b;
  margin: 0;
}
.section {
  margin-top: 24px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.section-header h3 {
  margin: 0;
  font-size: 18px;
  color: #1e293b;
}
.chapter-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}
.chapter-card {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  border: 1px solid #e2e8f0;
}
.chapter-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.chapter-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chapter-title span {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
}
.title-icon {
  color: #667eea;
}
.chapter-desc {
  margin: 0 0 12px 0;
  color: #64748b;
  font-size: 14px;
}
.chapter-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.meta-tag {
  background: #f1f5f9;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  color: #64748b;
}
.chapter-actions {
  display: flex;
  gap: 8px;
}
.more-icon {
  cursor: pointer;
  color: #94a3b8;
  padding: 4px;
}
.empty-state {
  text-align: center;
  padding: 40px;
  background: #f8fafc;
  border-radius: 12px;
}
.empty-icon {
  color: #cbd5e1;
  margin-bottom: 12px;
}
.empty-state p {
  margin: 0 0 8px 0;
  color: #94a3b8;
}
.empty-hint {
  font-size: 14px !important;
}

.dark .meta-tag {
  background: rgba(99, 102, 241, 0.1);
  color: #818cf8;
}

.dark .empty-state {
  background: var(--bg-card);
}

.dark .empty-icon {
  color: var(--border-color);
}

.dark .empty-state p {
  color: var(--text-muted);
}
</style>