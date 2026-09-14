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
        <span class="hint">投稿被采纳后发放给投稿人</span>
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

const qTypes = {
  single_choice: '单选题', multiple_choice: '多选题', fill_blank: '填空题',
  true_false: '判断题', short_answer: '简答题', essay: '问答题'
}
const qDiffs = { easy: '简单', medium: '中等', hard: '困难' }

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
})
const snapshot = reactive({ content: '', answer: '' })

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
  submitting.value = true
  try {
    await request.post('/api/bounties', payload)
    ElMessage.success('悬赏发布成功')
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
