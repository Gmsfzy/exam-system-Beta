<template>
  <div class="hw-discuss" v-loading="loading">
    <div class="discuss-editor">
      <el-input v-model="draft" type="textarea" :rows="3" maxlength="2000" show-word-limit
                placeholder="有问题或想法？在这里发起讨论（请友善交流）" />
      <div class="editor-foot">
        <span class="hint">支持作业级讨论；回复将展示在该楼层下</span>
        <el-button type="primary" size="small" :loading="posting"
                   :disabled="!draft.trim()" @click="create(null)">发布</el-button>
      </div>
    </div>

    <el-empty v-if="!items.length && !loading" description="还没有讨论，来提第一个问题吧"
              :image-size="76" />

    <div v-for="c in items" :key="c.id" class="comment">
      <div class="avatar" :class="{ teacher: c.is_teacher }">{{ initial(c.username) }}</div>
      <div class="body">
        <div class="head">
          <span class="name">{{ c.username }}</span>
          <el-tag v-if="c.is_teacher" size="small" type="warning" effect="plain">教师</el-tag>
          <span class="time">{{ fmt(c.created_at) }}</span>
        </div>
        <div class="content" :class="{ deleted: c.deleted }">{{ c.content }}</div>
        <div v-if="!c.deleted" class="actions">
          <el-button link size="small" @click="startReply(c)">回复</el-button>
          <el-button v-if="c.mine || canModerate" link size="small" type="danger"
                     @click="remove(c)">删除</el-button>
        </div>

        <div v-if="replyTo && replyTo.id === c.id" class="reply-editor">
          <el-input v-model="replyText" type="textarea" :rows="2" maxlength="2000"
                    :placeholder="`回复 ${c.username}`" />
          <div class="reply-btns">
            <el-button size="small" @click="cancelReply">取消</el-button>
            <el-button type="primary" size="small" :loading="replySubmitting"
                       :disabled="!replyText.trim()" @click="create(c)">回复</el-button>
          </div>
        </div>

        <div v-if="c.replies && c.replies.length" class="replies">
          <div v-for="r in c.replies" :key="r.id" class="reply-row">
            <div class="head">
              <span class="name">{{ r.username }}</span>
              <el-tag v-if="r.is_teacher" size="small" type="warning" effect="plain">教师</el-tag>
              <span class="time">{{ fmt(r.created_at) }}</span>
            </div>
            <div class="content" :class="{ deleted: r.deleted }">{{ r.content }}</div>
            <div v-if="!r.deleted" class="actions">
              <el-button link size="small" @click="startReply(c)">回复</el-button>
              <el-button v-if="r.mine || canModerate" link size="small" type="danger"
                         @click="remove(r)">删除</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="total > pageSize" class="pager">
      <el-pagination small background layout="prev, pager, next" :total="total"
                     :page-size="pageSize" :current-page="page" @current-change="onPage" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'

const props = defineProps({
  homeworkId: { type: [Number, String], required: true },
  questionId: { type: [Number, String], default: null },
  canModerate: { type: Boolean, default: false }
})

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const posting = ref(false)
const draft = ref('')
const replyTo = ref(null)
const replyText = ref('')
const replySubmitting = ref(false)

const initial = (name) => (name || '?').slice(0, 1).toUpperCase()
const fmt = (v) => (v || '').slice(0, 16).replace('T', ' ')

const load = async () => {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize }
    if (props.questionId) params.question_id = props.questionId
    const res = await request.get(`/api/homeworks/${props.homeworkId}/comments`, { params })
    items.value = res.data.items || []
    total.value = res.data.total || 0
  } finally {
    loading.value = false
  }
}

const create = async (parent) => {
  const text = parent ? replyText.value.trim() : draft.value.trim()
  if (!text) return
  if (parent) replySubmitting.value = true
  else posting.value = true
  try {
    const payload = { content: text }
    if (parent) payload.parent_id = parent.id
    if (props.questionId) payload.question_id = props.questionId
    await request.post(`/api/homeworks/${props.homeworkId}/comments`, payload)
    if (parent) {
      replyText.value = ''
      replyTo.value = null
    } else {
      draft.value = ''
      page.value = 1
    }
    ElMessage.success('已发布')
    await load()
  } finally {
    replySubmitting.value = false
    posting.value = false
  }
}

const startReply = (c) => {
  replyTo.value = c
  replyText.value = ''
}

const cancelReply = () => {
  replyTo.value = null
  replyText.value = ''
}

const remove = async (c) => {
  await ElMessageBox.confirm('删除后内容将不可见（保留楼层结构），确认删除？', '删除评论',
    { type: 'warning' })
  await request.delete(`/api/homeworks/${props.homeworkId}/comments/${c.id}`)
  ElMessage.success('已删除')
  await load()
}

const onPage = (p) => {
  page.value = p
  load()
}

onMounted(load)
</script>

<style scoped>
.hw-discuss { color: #374151; }
.discuss-editor { background: #f8fafc; border: 1px solid #eef2f7; border-radius: 10px; padding: 12px; }
.editor-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
.hint { font-size: 12px; color: #9ca3af; }
.comment { display: flex; gap: 10px; padding: 14px 0; border-bottom: 1px dashed #eef2f7; }
.comment:last-child { border-bottom: none; }
.avatar { width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0; display: flex;
  align-items: center; justify-content: center; color: #fff; font-weight: 600;
  background: linear-gradient(135deg, #8b5cf6, #6366f1); }
.avatar.teacher { background: linear-gradient(135deg, #f59e0b, #f97316); }
.body { flex: 1; min-width: 0; }
.head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.name { font-weight: 600; font-size: 13px; color: #111827; }
.time { font-size: 12px; color: #9ca3af; }
.content { line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.content.deleted { color: #9ca3af; font-style: italic; }
.actions { margin-top: 4px; }
.reply-editor { margin-top: 8px; }
.reply-btns { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
.replies { margin-top: 10px; padding: 10px 12px; background: #f9fafb; border-radius: 8px; }
.reply-row { padding: 6px 0; border-bottom: 1px dashed #e5e7eb; }
.reply-row:last-child { border-bottom: none; }
.pager { display: flex; justify-content: center; margin-top: 12px; }
</style>
