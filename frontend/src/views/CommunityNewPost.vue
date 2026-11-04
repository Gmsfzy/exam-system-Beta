<template>
  <div class="page-wrapper">
    <el-page-header @back="goBack" content="发起讨论" class="back" />

    <div class="page-header-inline">
      <h2><el-icon :size="22" class="title-icon"><ChatLineSquare /></el-icon> 发起讨论</h2>
      <p class="sub-info">发帖可关联题目 / 作业 / 考试，自动反向聚合到对应详情页的「讨论」tab</p>
    </div>

    <el-form
      :model="form"
      label-width="100px"
      class="publish-form"
      v-loading="submitting"
      @submit.prevent="submit"
    >
      <el-form-item label="标题" required>
        <el-input
          v-model="form.title"
          maxlength="100"
          show-word-limit
          placeholder="例如：为什么我这道链表反转总是空指针？"
        />
      </el-form-item>

      <el-form-item label="分类" required>
        <el-select
          v-model="form.category_key"
          placeholder="选择分类"
          style="width: 100%"
        >
          <el-option
            v-for="c in categories"
            :key="c.key"
            :label="c.name"
            :value="c.key"
          />
        </el-select>
        <span class="hint">默认「其他」</span>
      </el-form-item>

      <el-form-item label="圈子">
        <el-select
          v-model="form.course_id"
          placeholder="选择课程圈子（可选）"
          clearable
          filterable
          style="width: 100%"
        >
          <el-option
            v-for="c in circles"
            :key="c.course_id"
            :label="`${c.name}（${c.post_count} 帖）`"
            :value="c.course_id"
          />
        </el-select>
        <span class="hint">加入课程圈子后，同学可在圈子内看到该帖</span>
      </el-form-item>

      <el-form-item label="正文" required>
        <el-input
          ref="bodyInputRef"
          v-model="form.body"
          type="textarea"
          :autosize="{ minRows: 6, maxRows: 14 }"
          maxlength="5000"
          show-word-limit
          placeholder="请详细描述你的问题、解法或经验… 输入 @用户名 可提醒对方，支持 Markdown 与公式"
        />
      </el-form-item>

      <el-form-item label="图片/附件">
        <el-upload
          :show-file-list="false"
          :http-request="handleUpload"
          :disabled="uploading"
          accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.txt,.md,.zip,.rar,.7z"
        >
          <el-button :icon="Upload" :loading="uploading">上传并插入正文</el-button>
        </el-upload>
        <span class="hint">图片会插入 Markdown 图片语法，其它文件插入下载链接</span>
      </el-form-item>

      <el-form-item label="关联类型">
        <el-select
          v-model="form.linked_type"
          placeholder="不关联"
          clearable
          style="width: 100%"
        >
          <el-option label="不关联" value="" />
          <el-option label="题目" value="question" />
          <el-option label="作业" value="homework" />
          <el-option label="考试" value="exam" />
        </el-select>
      </el-form-item>

      <el-form-item v-if="form.linked_type" label="关联 ID">
        <el-input-number
          v-model="form.linked_id"
          :min="1"
          placeholder="请输入对应的 ID"
          style="width: 240px"
        />
        <el-alert
          v-if="form.linked_type"
          type="info"
          :closable="false"
          show-icon
          class="linked-alert"
          :title="`关联成功后，这个帖子会自动出现在对应${linkedLabel(form.linked_type)}详情页的「讨论」tab`"
        />
      </el-form-item>

      <el-form-item v-if="form.linked_type === 'question'" label="悬赏积分">
        <el-input-number v-model="form.bounty_points" :min="0" :max="100" />
        <span class="hint">0–100 分，采纳答案后自动转给最佳答主；未采纳前会先冻结</span>
      </el-form-item>

      <el-form-item label="标签">
        <el-select
          v-model="form.tags"
          multiple
          filterable
          allow-create
          default-first-option
          :multiple-limit="5"
          placeholder="输入标签后回车，最多 5 个"
          style="width: 100%"
        />
        <span class="hint">用于聚合同类话题，如「链表」「动态规划」</span>
      </el-form-item>

      <el-form-item label="投票">
        <div class="poll-editor">
          <el-switch v-model="form.poll_enabled" active-text="发起投票" inactive-text="不投票" />
          <div v-if="form.poll_enabled" class="poll-options">
            <div v-for="(_, i) in form.poll_options" :key="i" class="poll-option-row">
              <el-input
                v-model="form.poll_options[i]"
                maxlength="100"
                :placeholder="`选项 ${i + 1}`"
              />
              <el-button
                v-if="form.poll_options.length > 2"
                link
                type="danger"
                @click="removePollOption(i)"
              >删除</el-button>
            </div>
            <el-button
              v-if="form.poll_options.length < 6"
              size="small"
              :icon="Plus"
              @click="addPollOption"
            >添加选项</el-button>
          </div>
        </div>
      </el-form-item>

      <el-form-item label="匿名发布">
        <el-switch v-model="form.is_anonymous" />
        <span class="hint">匿名后其他人只看到「匿名#N」</span>
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :icon="Promotion" @click="submit">发布</el-button>
        <el-button @click="goBack">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatLineSquare, Promotion, Upload, Plus } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()
const route = useRoute()
const submitting = ref(false)
const uploading = ref(false)
const bodyInputRef = ref(null)

const categories = ref([])
const circles = ref([])

const DEFAULT_CATEGORIES = [
  { key: 'discussion', name: '错题讨论' },
  { key: 'solution', name: '解法分享' },
  { key: 'help', name: '求助答疑' },
  { key: 'experience', name: '经验交流' },
  { key: 'resource', name: '资源下载' },
  { key: 'other', name: '其他' },
]

const form = reactive({
  title: '',
  category_key: 'other',
  body: '',
  linked_type: '',
  linked_id: null,
  course_id: null,
  bounty_points: 0,
  is_anonymous: false,
  tags: [],
  poll_enabled: false,
  poll_options: ['', ''],
})

const linkedLabel = (t) => ({ question: '题目', homework: '作业', exam: '考试' }[t] || t)

const goBack = () => window.history.back()

const addPollOption = () => {
  if (form.poll_options.length < 6) form.poll_options.push('')
}
const removePollOption = (i) => {
  if (form.poll_options.length > 2) form.poll_options.splice(i, 1)
}

// 上传成功后把 Markdown 片段插入正文光标处
const insertAtCursor = (text) => {
  const textarea = bodyInputRef.value?.textarea
  if (!textarea) {
    form.body = form.body ? `${form.body}\n${text}` : text
    return
  }
  const start = textarea.selectionStart ?? form.body.length
  const end = textarea.selectionEnd ?? form.body.length
  form.body = form.body.slice(0, start) + text + form.body.slice(end)
  nextTick(() => {
    textarea.focus()
    const pos = start + text.length
    textarea.setSelectionRange(pos, pos)
  })
}

const handleUpload = async ({ file }) => {
  const fd = new FormData()
  fd.append('file', file)
  uploading.value = true
  try {
    const res = await request.post('/api/community/upload', fd)
    const d = res.data || {}
    if (!d.url) return ElMessage.error('上传失败')
    const snippet = d.is_image
      ? `![${d.name}](${d.url})`
      : `[${d.name}](${d.url})`
    insertAtCursor(`${snippet}\n`)
    ElMessage.success('上传成功，已插入正文')
  } catch (e) {
    // request 拦截器已提示
  } finally {
    uploading.value = false
  }
}

const submit = async () => {
  if (form.title.trim() === '') return ElMessage.warning('请填写标题')
  if (!form.body.trim()) return ElMessage.warning('请填写正文')
  if (form.linked_type && !form.linked_id) return ElMessage.warning('请输入关联 ID')

  const pollOptions = form.poll_enabled
    ? form.poll_options.map((t) => t.trim()).filter(Boolean)
    : null
  if (form.poll_enabled && pollOptions.length < 2) {
    return ElMessage.warning('投票至少需要 2 个选项')
  }

  const payload = {
    title: form.title.trim(),
    category: form.category_key || 'other',
    content: form.body.trim(),
    is_anonymous: form.is_anonymous,
    linked_type: form.linked_type || null,
    linked_id: form.linked_id || null,
    course_id: form.course_id || null,
    bounty_points: form.linked_type === 'question' ? (form.bounty_points || 0) : 0,
    tags: form.tags,
    poll_options: pollOptions,
  }

  submitting.value = true
  try {
    const res = await request.post('/api/community/posts', payload)
    const newPost = res.data?.post || res.data
    ElMessage.success('发布成功')
    if (newPost?.id) {
      router.push(`/community/${newPost.id}`)
    } else {
      router.push('/community')
    }
  } catch (e) {
    // request 拦截器已经弹过错误，这里只做静默
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  // v6.1 跨模块求助入口：支持从作业/考试结果页带参跳转，预填关联信息
  const q = route.query
  if (q.linked_type) form.linked_type = String(q.linked_type)
  if (q.linked_id) form.linked_id = Number(q.linked_id) || null
  if (q.course_id) form.course_id = Number(q.course_id) || null
  if (q.category) form.category_key = String(q.category)
  if (q.title) form.title = String(q.title)
  if (q.tags) {
    const t = String(q.tags)
    form.tags = t.split(',').map((s) => s.trim()).filter(Boolean).slice(0, 5)
  }

  try {
    const res = await request.get('/api/community/categories')
    if (Array.isArray(res.data) && res.data.length) {
      // 后端返回 [{value, label}],映射为 {key, name}
      categories.value = res.data.map((c) => ({ key: c.value, name: c.label }))
    } else {
      categories.value = DEFAULT_CATEGORIES
    }
  } catch {
    categories.value = DEFAULT_CATEGORIES
  }

  try {
    const res = await request.get('/api/community/circles')
    circles.value = res.data?.items || []
  } catch {
    circles.value = []
  }
})
</script>

<style scoped>
.back { margin-bottom: 12px; }
.page-header-inline { margin-bottom: 18px; }
.page-header-inline h2 { margin: 0 0 4px; display: flex; align-items: center; gap: 8px; }
.title-icon { color: #14b8a6; }
.sub-info { color: var(--el-text-color-secondary, #909399); font-size: 13px; margin: 0; }

.publish-form {
  max-width: 760px;
  background: var(--el-bg-color, #fff);
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 12px;
  padding: 24px;
}

.hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
}

.linked-alert {
  margin-top: 8px;
  margin-left: 100px;
  max-width: 560px;
}

.poll-editor { width: 100%; }
.poll-options { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.poll-option-row { display: flex; gap: 8px; align-items: center; max-width: 560px; }
</style>
