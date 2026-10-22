<template>
  <div class="ai-review" :class="[`kind-${kind}`, { degraded }]">
    <div v-if="degraded" class="degraded-tip">
      <el-icon><WarningFilled /></el-icon>
      <span>AI 服务暂不可用，以下为规则版讲评（统计数据完整）</span>
    </div>

    <div v-if="content.summary" class="summary-block">
      <el-icon class="summary-icon"><ChatDotRound /></el-icon>
      <p>{{ content.summary }}</p>
    </div>

    <!-- 班级：共性错因 -->
    <template v-if="kind === 'class'">
      <div v-if="mistakes.length" class="section">
        <div class="section-title"><el-icon><Aim /></el-icon>共性错因与讲评</div>
        <div v-for="(m, i) in mistakes" :key="i" class="mistake-item">
          <div class="mistake-head">
            <span class="idx">{{ i + 1 }}</span>
            <span class="q">{{ m.question || '题目' }}</span>
          </div>
          <div v-if="m.mistake" class="mistake-line"><b>错因</b>{{ m.mistake }}</div>
          <div v-if="m.advice" class="advice-line"><b>建议</b>{{ m.advice }}</div>
        </div>
      </div>

      <div v-if="content.weak_points?.length" class="section">
        <div class="section-title"><el-icon><Warning /></el-icon>薄弱知识点</div>
        <div class="tag-row">
          <el-tag v-for="p in content.weak_points" :key="p" type="danger" effect="light" size="small">
            {{ p }}
          </el-tag>
        </div>
      </div>

      <div v-if="content.teaching_suggestions?.length" class="section">
        <div class="section-title"><el-icon><Reading /></el-icon>讲评课建议</div>
        <ul class="plain-list">
          <li v-for="(s, i) in content.teaching_suggestions" :key="i">{{ s }}</li>
        </ul>
      </div>
    </template>

    <!-- 单份：亮点 / 改进 / 下一步 -->
    <template v-else>
      <div v-if="content.strengths?.length" class="section">
        <div class="section-title green"><el-icon><CircleCheck /></el-icon>做得好的地方</div>
        <ul class="plain-list green-list">
          <li v-for="(s, i) in content.strengths" :key="i">{{ s }}</li>
        </ul>
      </div>

      <div v-if="improvements.length" class="section">
        <div class="section-title"><el-icon><TrendCharts /></el-icon>改进方向</div>
        <div v-for="(m, i) in improvements" :key="i" class="mistake-item">
          <div class="mistake-head">
            <span class="idx">{{ i + 1 }}</span>
            <span class="q">{{ m.point || '待提升项' }}</span>
          </div>
          <div v-if="m.advice" class="advice-line"><b>建议</b>{{ m.advice }}</div>
        </div>
      </div>

      <div v-if="content.next_steps?.length" class="section">
        <div class="section-title"><el-icon><Finished /></el-icon>下一步行动</div>
        <ul class="plain-list">
          <li v-for="(s, i) in content.next_steps" :key="i">{{ s }}</li>
        </ul>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  WarningFilled, ChatDotRound, Aim, Warning, Reading, CircleCheck,
  TrendCharts, Finished,
} from '@element-plus/icons-vue'

const props = defineProps({
  content: { type: Object, default: () => ({}) },
  kind: { type: String, default: 'class' },   // class | submission
  degraded: { type: Boolean, default: false },
})

const mistakes = computed(() => props.content.common_mistakes || [])
const improvements = computed(() => props.content.improvements || [])
</script>

<style scoped>
.ai-review {
  border-radius: 12px;
  padding: 16px 18px;
  background: linear-gradient(160deg, rgba(99, 102, 241, 0.06), rgba(255, 255, 255, 0.9));
  border: 1px solid rgba(99, 102, 241, 0.16);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.08);
}
.ai-review.kind-submission {
  background: linear-gradient(160deg, rgba(6, 182, 212, 0.07), rgba(255, 255, 255, 0.92));
  border-color: rgba(6, 182, 212, 0.2);
  box-shadow: 0 6px 20px rgba(6, 182, 212, 0.08);
}
.degraded-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
  color: #b88230;
  background: rgba(230, 162, 60, 0.1);
}
.summary-block {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.75);
  border-left: 3px solid #6366f1;
}
.kind-submission .summary-block { border-left-color: #06b6d4; }
.summary-icon { color: #6366f1; margin-top: 2px; flex-shrink: 0; }
.kind-submission .summary-icon { color: #06b6d4; }
.summary-block p { margin: 0; line-height: 1.7; color: #303133; font-size: 14px; }
.section { margin-top: 16px; }
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: #4b5563;
  margin-bottom: 8px;
}
.section-title.green { color: #15803d; }
.mistake-item {
  padding: 10px 12px;
  margin-bottom: 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(0, 0, 0, 0.04);
}
.mistake-head { display: flex; align-items: baseline; gap: 8px; }
.mistake-head .idx {
  width: 20px; height: 20px; line-height: 20px; text-align: center;
  border-radius: 50%; font-size: 12px; color: #fff; background: #f56c6c; flex-shrink: 0;
}
.kind-submission .mistake-head .idx { background: #06b6d4; }
.mistake-head .q { font-weight: 500; color: #303133; font-size: 13px; line-height: 1.6; }
.mistake-line, .advice-line { margin-top: 6px; font-size: 13px; line-height: 1.65; color: #606266; }
.mistake-line b, .advice-line b {
  display: inline-block; margin-right: 6px; font-weight: 600; color: #909399; font-size: 12px;
}
.advice-line { color: #3f6212; }
.tag-row { display: flex; flex-wrap: wrap; gap: 8px; }
.plain-list { margin: 0; padding-left: 20px; color: #606266; font-size: 13px; line-height: 1.9; }
.green-list { color: #3f6212; }
</style>
