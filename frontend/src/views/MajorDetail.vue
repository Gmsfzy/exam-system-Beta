<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-left">
        <el-button text @click="goBack" class="back-btn">
          <el-icon :size="20"><ArrowLeft /></el-icon>
          <span>返回</span>
        </el-button>
        <div class="header-info">
          <h2>{{ majorData.name }}</h2>
          <p v-if="majorData.description">{{ majorData.description }}</p>
        </div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="openCourseDialog">
          <el-icon><Plus /></el-icon>添加课程
        </el-button>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
            <el-icon :size="24" color="white"><Collection /></el-icon>
          </div>
        <div class="stat-info">
          <div class="stat-value">{{ courses.length }}</div>
          <div class="stat-label">课程数量</div>
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
        <h3>课程管理</h3>
      </div>
      <div v-if="courses.length" class="course-grid">
        <div v-for="course in courses" :key="course.id" class="course-card">
          <div class="course-header">
            <h4>{{ course.name }}</h4>
            <el-dropdown @command="cmd => handleCourseAction(cmd, course)">
              <el-icon class="more-icon"><More /></el-icon>
            </el-dropdown>
          </div>
          <p class="course-desc">{{ course.description || '暂无描述' }}</p>
          <div class="course-meta">
            <span class="meta-tag">学分: {{ course.credit }}</span>
            <span class="meta-tag">学期: {{ course.semester }}</span>
            <span class="meta-tag">{{ getCourseQuestionCount(course.id) }} 题</span>
          </div>
          <div class="course-actions">
            <el-button text @click="viewCourseChapters(course.id)">
              <el-icon><Notebook /></el-icon>章节管理
            </el-button>
            <el-button text @click="viewCourseQuestions(course.id)">
              <el-icon><Document /></el-icon>查看题目
            </el-button>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <el-icon :size="48" class="empty-icon"><Collection /></el-icon>
        <p>暂无课程，点击上方按钮添加</p>
      </div>
    </div>

    <el-dialog v-model="courseDialogVisible" :title="isEditCourse ? '编辑课程' : '添加课程'" width="500px">
      <el-form :model="courseForm" label-width="80px">
        <el-form-item label="课程名称">
          <el-input v-model="courseForm.name" placeholder="请输入课程名称" />
        </el-form-item>
        <el-form-item label="课程描述">
          <el-input v-model="courseForm.description" type="textarea" rows="3" placeholder="请输入课程描述" />
        </el-form-item>
        <el-form-item label="学分">
          <el-input v-model.number="courseForm.credit" type="number" placeholder="请输入学分" />
        </el-form-item>
        <el-form-item label="学期">
          <el-select v-model="courseForm.semester">
            <el-option label="第一学期" value="第一学期" />
            <el-option label="第二学期" value="第二学期" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="courseDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveCourse" :loading="saving">
          {{ isEditCourse ? '保存修改' : '确认添加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '../utils/request'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Plus, More, Collection, Document, Notebook } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const majorData = ref({ name: '', description: '' })
const courses = ref([])
const questions = ref([])
const courseDialogVisible = ref(false)
const isEditCourse = ref(false)
const saving = ref(false)

const courseForm = ref({ id: null, name: '', description: '', credit: 2, semester: '第一学期' })

const totalQuestions = computed(() => questions.value.length)

const getCourseQuestionCount = (courseId) => {
  return questions.value.filter(q => q.course_id === courseId).length
}

const goBack = () => {
  router.push('/majors')
}

const openCourseDialog = (course = null) => {
  if (course) {
    isEditCourse.value = true
    courseForm.value = { ...course }
  } else {
    isEditCourse.value = false
    courseForm.value = { id: null, name: '', description: '', credit: 2, semester: '第一学期' }
  }
  courseDialogVisible.value = true
}

const saveCourse = async () => {
  if (!courseForm.value.name.trim()) {
    ElMessage.warning('请输入课程名称')
    return
  }
  saving.value = true
  try {
    const data = { ...courseForm.value, major_id: route.params.id }
    if (isEditCourse.value) {
      await request.put(`/api/courses/${courseForm.value.id}`, data)
      ElMessage.success('更新成功')
    } else {
      await request.post('/api/courses', data)
      ElMessage.success('添加成功')
    }
    courseDialogVisible.value = false
    fetchCourses()
  } catch (e) {
    console.error(e)
  } finally {
    saving.value = false
  }
}

const deleteCourse = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该课程吗？', '提示', { type: 'warning' })
    await request.delete(`/api/courses/${id}`)
    ElMessage.success('删除成功')
    fetchCourses()
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}

const handleCourseAction = (cmd, course) => {
  if (cmd === 'edit') {
    openCourseDialog(course)
  } else if (cmd === 'delete') {
    deleteCourse(course.id)
  }
}

const viewCourseChapters = (courseId) => {
  router.push(`/chapters/${courseId}`)
}

const viewCourseQuestions = (courseId) => {
  router.push(`/questions?course=${courseId}`)
}

const getMajorId = () => {
  const id = String(route.params.id).split('/')[0]
  return parseInt(id) || 0
}

const fetchMajor = async () => {
  const id = getMajorId()
  if (!id) return
  const res = await request.get(`/api/majors/${id}`)
  majorData.value = res.data
}

const fetchCourses = async () => {
  const id = getMajorId()
  if (!id) return
  const res = await request.get(`/api/courses?major_id=${id}`)
  courses.value = res.data
}

const fetchQuestions = async () => {
  const id = getMajorId()
  if (!id) return
  const res = await request.get('/api/questions')
  questions.value = res.data.filter(q => q.major_id === id)
}

onMounted(() => {
  fetchMajor()
  fetchCourses()
  fetchQuestions()
})
</script>

<style scoped>
.page-wrapper {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border-color);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 20px;
}

.back-btn {
  padding: 12px 18px;
  border-radius: 12px;
  color: var(--text-muted);
  transition: all 0.3s ease;
}

.back-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  transform: translateX(-4px);
}

.header-info h2 {
  margin: 0 0 6px 0;
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
}

.header-info p {
  margin: 0;
  color: var(--text-muted);
  font-size: 15px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.header-actions .el-button--primary {
  border-radius: 12px;
  padding: 0 28px;
  height: 44px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  font-weight: 600;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.35);
  transition: all 0.3s ease;
}

.header-actions .el-button--primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(102, 126, 234, 0.45);
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
  margin-bottom: 32px;
}

.stat-card {
  background: var(--bg-card);
  border-radius: 16px;
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 18px;
  border: 1px solid var(--border-color);
  transition: all 0.3s ease;
}

.stat-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.stat-label {
  font-size: 14px;
  color: var(--text-muted);
  margin-top: 6px;
}

.section {
  margin-top: 32px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.section-header h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 24px;
}

.course-card {
  background: var(--bg-card);
  border-radius: 20px;
  padding: 28px;
  border: 1px solid var(--border-color);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.course-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 4px;
  background: linear-gradient(90deg, #667eea 0%, #8b5cf6 50%, #a855f7 100%);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.course-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.1);
  border-color: rgba(99, 102, 241, 0.2);
}

.course-card:hover::before {
  opacity: 1;
}

.course-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.course-header h4 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.course-desc {
  margin: 0 0 16px 0;
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.course-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 20px;
}

.meta-tag {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(139, 92, 246, 0.08) 100%);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  color: #6366f1;
  border: 1px solid rgba(99, 102, 241, 0.1);
}

.course-actions {
  display: flex;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}

.course-actions .el-button--text {
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 500;
  transition: all 0.25s ease;
}

.course-actions .el-button--text:hover {
  color: #6366f1;
  background: rgba(99, 102, 241, 0.08);
}

.more-icon {
  cursor: pointer;
  color: var(--text-light);
  padding: 10px;
  border-radius: 10px;
  transition: all 0.3s ease;
}

.more-icon:hover {
  background: var(--bg-tertiary);
  color: var(--text-muted);
  transform: rotate(90deg);
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  background: var(--bg-card);
  border-radius: 20px;
  border: 1px dashed var(--border-color);
}

.empty-icon {
  color: var(--text-light);
  margin-bottom: 16px;
}

.empty-state p {
  margin: 0;
  color: var(--text-muted);
  font-size: 15px;
}

.dark .page-header {
  border-bottom-color: var(--border-color);
}

.dark .header-info h2 {
  color: var(--text-primary);
}

.dark .header-info p {
  color: var(--text-muted);
}

.dark .back-btn {
  color: var(--text-muted);
}

.dark .back-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.dark .section-header h3 {
  color: var(--text-primary);
}

.dark .course-card {
  background: var(--bg-card);
  border-color: var(--border-color);
}

.dark .course-card:hover {
  border-color: rgba(99, 102, 241, 0.3);
}

.dark .course-header h4 {
  color: var(--text-primary);
}

.dark .course-desc {
  color: var(--text-muted);
}

.dark .meta-tag {
  background: rgba(99, 102, 241, 0.1);
  color: #818cf8;
  border-color: rgba(99, 102, 241, 0.2);
}

.dark .course-actions {
  border-top-color: var(--border-color);
}

.dark .course-actions .el-button--text {
  color: var(--text-muted);
}

.dark .course-actions .el-button--text:hover {
  color: #818cf8;
  background: rgba(99, 102, 241, 0.15);
}

.dark .more-icon {
  color: var(--text-light);
}

.dark .more-icon:hover {
  background: var(--bg-tertiary);
  color: var(--text-muted);
}

.dark .empty-state {
  background: var(--bg-card);
  border-color: var(--border-color);
}

.dark .empty-icon {
  color: var(--border-color);
}

.dark .empty-state p {
  color: var(--text-muted);
}

.dark .stat-card {
  background: var(--bg-card);
  border-color: var(--border-color);
}

.dark .stat-value {
  color: var(--text-primary);
}

.dark .stat-label {
  color: var(--text-muted);
}
</style>