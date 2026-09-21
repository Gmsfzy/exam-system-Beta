<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><EditPen /></el-icon> 发布悬赏</h2>
        <p><span class="sub-info">题目征集：悬赏优质自编题；答案征集：为题目求优质答案/解析</span></p>
      </div>
    </div>

    <el-form :model="form" label-width="100px" class="publish-form" v-loading="submitting">
      <el-form-item label="悬赏类型">
        <el-radio-group v-model="form.bounty_type">
          <el-radio-button label="question">题目征集</el-radio-button>
          <el-radio-button label="answer">答案征集</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="悬赏标题" required>
        <el-input v-model="form.title" maxlength="100" show-word-limit placeholder="例如：求数据结构二叉树遍历单选题" />
      </el-form-item>

      <el-form-item label="需求描述">
        <el-input v-model="form.description" type="textarea" :rows="3"
                  placeholder="详细说明你需要的题目知识点、难度要求，或答案的解析要求" />
      </el-form-item>

      <el-form-item label="标签">
        <el-input v-model="form.tags" placeholder="多个标签用逗号分隔，便于搜索发现（选填）" maxlength="200" />
      </el-form-item>

      <el-form-item label="采纳名额">
        <el-input-number v-model="form.max_accepts" :min="1" :max="20" />
        <span class="hint">默认 1（单一中标）；大于 1 可采纳多条优质投稿</span>
      </el-form-item>

      <el-form-item label="可见范围">
        <el-radio-group v-model="form.visibility">
          <el-radio label="public">公开（全体可见）</el-radio>
          <el-radio label="targeted">定向（仅指定用户）</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="form.visibility === 'targeted'" label="定向用户ID">
        <el-input v-model="targetUsers" placeholder="输入可见的用户ID，逗号分隔" />
      </el-form-item>

      <!-- 题目征集：专业/题型/难度 -->
      <template v-if="form.bounty_type === 'question'">
        <el-form-item label="所属专业" required>
          <el-select v-model="form.major_id" placeholder="选择专业" style="width: 100%">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="期望题型">
          <el-select v-model="form.q_type" placeholder="不限" clearable style="width: 100%">
            <el-option v-for="(label, key) in qTypes" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="期望难度">
          <el-select v-model="form.q_difficulty" placeholder="不限" clearable style="width: 100%">
            <el-option v-for="(label, key) in qDiffs" :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
      </template>

      <!-- 答案征集：关联已有题 / 自带题目 -->
      <template v-else>
        <el-form-item label="题目来源">
          <el-radio-group v-model="answerMode">
            <el-radio label="existing">关联题库已有题</el-radio>
            <el-radio label="inline">悬赏单自带题目</el-radio>
          </el-radio-group>
        </el-form-item>

        <template v-if="answerMode === 'existing'">
          <el-form-item label="选择题目" required>
            <el-select v-model="form.target_question_id" filterable placeholder="输入题干搜索题目"
                       style="width: 100%">
              <el-option v-for="q in questions" :key="q.id"
                         :label="(q.content || '').slice(0, 40)" :value="q.id" />
            </el-select>
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="题目题干" required>
            <el-input v-model="snapshot.content" type="textarea" :rows="2" placeholder="请输入题目内容" />
          </el-form-item>
          <el-form-item label="参考答案">
            <el-input v-model="snapshot.answer" placeholder="可选：提供参考答案（投稿人需给出解析）" />
          </el-form-item>
        </template>
      </template>

      <el-form-item label="赏金（积分）" required>
        <el-input-number v-model="form.reward_points" :min="1" :max="500" :step="5" />
        <span class="hint">投稿被采纳后发放给投稿人{{ form.max_accepts > 1 ? `（每条中标各发 ${form.reward_points} 分）` : '' }}</span>
      </el-form-item>

      <el-form-item label="截止时间">
        <el-date-picker v-model="form.deadline" type="datetime" placeholder="不选则长期有效"
                        value-format="YYYY-MM-DDTHH:mm:ss" style="width: 100%" />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :icon="Promotion" @click="submit">发布悬赏</el-button>
        <el-button @click="$router.back()">取消</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { EditPen, Promotion } from '@element-plus/icons-vue'
import request from '../utils/request'

const router = useRouter()
const submitting = ref(false)
const majors = ref([])
const questions = ref([])
const answerMode = ref('existing')

// v4.6.1 枚举收敛：题型/难度单一来源 frontend/src/utils/enums.js（顺手修正旧 map 中 short_answer/essay 标签互换的漂移）
import { QUESTION_TYPE_LABELS, DIFFICULTY_LABELS } from '../utils/enums'

const qTypes = QUESTION_TYPE_LABELS
const qDiffs = DIFFICULTY_LABELS

const form = reactive({
  bounty_type: 'question',
  title: '',
  description: '',
  major_id: null,
  q_type: '',
  q_difficulty: '',
  reward_points: 10,
  deadline: '',
  target_question_id: null,
  tags: '',
  max_accepts: 1,
  visibility: 'public',
})
const snapshot = reactive({ content: '', answer: '' })
const targetUsers = ref('')

const submit = async () => {
  if (!form.title.trim()) return ElMessage.warning('请填写悬赏标题')
  if (form.bounty_type === 'question' && !form.major_id) return ElMessage.warning('题目征集请选择所属专业')
  if (form.bounty_type === 'answer' && answerMode.value === 'existing' && !form.target_question_id)
    return ElMessage.warning('请选择要关联的题目')
  if (form.bounty_type === 'answer' && answerMode.value === 'inline' && !snapshot.content.trim())
    return ElMessage.warning('请填写题目题干')

  const payload = { ...form }
  if (form.bounty_type === 'answer') {
    if (answerMode.value === 'inline') {
      payload.target_question_snapshot = { content: snapshot.content, answer: snapshot.answer }
      payload.target_question_id = null
    }
  }
  if (form.visibility === 'targeted') {
    const ids = targetUsers.value.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n))
    payload.target = { user_ids: ids, major_ids: [] }
  } else {
    payload.target = null
  }
  submitting.value = true
  try {
    const res = await request.post('/api/bounties', payload)
    // v4.5 审核门禁：存在其他教师时进入待审核
    if (res.data?.status === 'reviewing') {
      ElMessage.success('已提交审核，教师通过后自动上架悬赏广场')
    } else {
      ElMessage.success('悬赏发布成功')
    }
    router.push('/bounties')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  const [mj, qq] = await Promise.all([
    request.get('/api/majors'),
    request.get('/api/questions', { params: { page: 1, per_page: 200 } })
  ])
  majors.value = mj.data || []
  questions.value = (qq.data?.items || qq.data || []).slice(0, 200)
})
</script>

<style scoped>
.publish-form {
  max-width: 720px;
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
</style>
