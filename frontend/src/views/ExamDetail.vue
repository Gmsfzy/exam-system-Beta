<template>
  <div class="page-wrapper" v-loading="loading">
    <div class="page-header">
      <div class="header-title">
        <h2>
          <el-icon :size="22" class="title-icon"><Calendar /></el-icon> 考试详情
          <span v-if="exam" class="q-id">#{{ exam.id }}</span>
        </h2>
        <p class="sub-info">考试只读概览 · 供社区「考试关联」与通知一步直达</p>
      </div>
      <div class="header-actions">
        <el-button v-if="exam" :icon="ChatDotRound" @click="goDiscuss">讨论区</el-button>
        <el-button text :icon="Back" @click="goBack">返回</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" class="err-alert" />

    <el-empty v-else-if="!loading && !exam" description="考试不存在，或您无权查看（未被邀请）" />

    <div v-if="exam" class="detail-card">
      <div class="exam-title-row">
        <h3 class="exam-title">{{ exam.title }}</h3>
        <span class="status-badge" :class="exam.status">{{ statusLabel(exam.status) }}</span>
      </div>
      <p v-if="exam.description" class="exam-desc">{{ exam.description }}</p>

      <div class="kv-grid">
        <div class="kv"><span class="k">开始时间</span><span class="v">{{ exam.start_time || '—' }}</span></div>
        <div class="kv"><span class="k">结束时间</span><span class="v">{{ exam.end_time || '—' }}</span></div>
        <div class="kv"><span class="k">考试时长</span><span class="v">{{ exam.duration ? exam.duration + ' 分钟' : '—' }}</span></div>
        <div class="kv"><span class="k">题目数量</span><span class="v">{{ exam.question_count }}</span></div>
        <div class="kv"><span class="k">参考人数</span><span class="v">{{ exam.student_count }}</span></div>
      </div>

      <!-- 教师：考务配置 + 邀请码 + 管理入口 -->
      <template v-if="isTeacher">
        <h4 class="sec-title">考务配置</h4>
        <div class="kv-grid">
          <div class="kv"><span class="k">最大作答次数</span><span class="v">{{ exam.max_attempts }}</span></div>
          <div class="kv"><span class="k">选项乱序</span><span class="v">{{ exam.shuffle_options ? '是' : '否' }}</span></div>
          <div class="kv"><span class="k">匿名批改</span><span class="v">{{ exam.anonymous_grading ? '是' : '否' }}</span></div>
          <div class="kv"><span class="k">成绩已发布</span><span class="v">{{ exam.results_published ? '是' : '否' }}</span></div>
        </div>
        <div v-if="exam.invitation_code" class="invite">
          <span class="k">邀请码</span>
          <code class="code">{{ exam.invitation_code }}</code>
          <span v-if="exam.invitation_url" class="link" @click="copyUrl">复制链接</span>
        </div>
        <div class="action-row">
          <el-button type="primary" :icon="EditPen" @click="go('/exams/' + exam.id + '/edit')">编辑考卷</el-button>
          <el-button :icon="View" @click="go('/exams/' + exam.id + '/monitor')">实时监考</el-button>
          <el-button :icon="TrendCharts" @click="go('/results/exam/' + exam.id)">查看成绩</el-button>
          <el-button :icon="DataAnalysis" @click="go('/exams/' + exam.id + '/item-analysis')">试题分析</el-button>
        </div>
      </template>

      <!-- 学生：去作答 / 成绩 -->
      <template v-else>
        <div class="action-row">
          <el-button v-if="exam.status === 'published'" type="primary" :icon="VideoPlay"
                     @click="go('/exam/take/' + exam.id)">去作答</el-button>
          <el-button v-if="exam.results_published" :icon="Medal" @click="go('/results/exam/' + exam.id)">我的成绩</el-button>
          <span v-if="exam.status !== 'published' && !exam.results_published" class="hint">该考试当前不可作答</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Calendar, Back, ChatDotRound, EditPen, View, TrendCharts, DataAnalysis, VideoPlay, Medal,
} from '@element-plus/icons-vue'
import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const error = ref('')
const exam = ref(null)

const isTeacher = computed(() => auth.user?.role === 'teacher')

const statusLabel = (s) => ({ draft: '草稿', published: '已发布', ended: '已结束' }[s] || s)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await request.get(`/api/exams/${route.params.id}`)
    exam.value = res.data
  } catch (e) {
    const status = e?.response?.status
    if (status === 404) error.value = '考试不存在'
    else if (status === 403) error.value = '您无权查看该考试（非创建教师或未被邀请参加）'
    else if (status !== 401) error.value = '加载考试失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const go = (path) => router.push(path)
const goDiscuss = () =>
  router.push({ path: '/community', query: { linked_type: 'exam', linked_id: route.params.id } })

const copyUrl = async () => {
  try { await navigator.clipboard.writeText(exam.value.invitation_url); ElMessage.success('邀请链接已复制') }
  catch { ElMessage.warning('复制失败，请手动选择链接') }
}

const goBack = () => {
  if (window.history.length > 1) router.back()
  else router.push(isTeacher.value ? '/exams' : '/student')
}

onMounted(load)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.header-title h2 { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 20px; }
.title-icon { color: #409eff; }
.q-id { color: #909399; font-weight: 400; font-size: 15px; }
.sub-info { color: #909399; font-size: 13px; margin: 6px 0 0; }
.err-alert { margin-bottom: 12px; }
.detail-card { background: #fff; border-radius: 10px; padding: 20px 22px; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05); }
.exam-title-row { display: flex; align-items: center; gap: 12px; }
.exam-title { margin: 0; font-size: 18px; color: #303133; }
.status-badge { font-size: 12px; padding: 2px 10px; border-radius: 12px; color: #fff; background: #909399; }
.status-badge.published { background: #67c23a; }
.status-badge.draft { background: #e6a23c; }
.status-badge.ended { background: #909399; }
.exam-desc { color: #606266; margin: 10px 0 4px; line-height: 1.6; }
.kv-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px 24px; margin: 16px 0; }
.kv { display: flex; justify-content: space-between; border-bottom: 1px dashed #ebeef5; padding: 6px 0; }
.kv .k { color: #909399; }
.kv .v { color: #303133; font-weight: 500; }
.sec-title { margin: 8px 0 4px; font-size: 14px; color: #303133; border-left: 3px solid #409eff; padding-left: 8px; }
.invite { display: flex; align-items: center; gap: 12px; margin: 8px 0 4px; }
.invite .code { background: #f4f4f5; padding: 2px 10px; border-radius: 6px; font-size: 15px; letter-spacing: 1px; }
.invite .link { color: #409eff; cursor: pointer; font-size: 13px; }
.action-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 18px; }
.hint { color: #a8abb2; font-size: 13px; }
</style>
