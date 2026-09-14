<template>
  <div class="learning-home">
    <div class="page-header">
      <h1 class="page-title">自我学习</h1>
      <p class="page-subtitle">错题回顾 · 自由刷题 · 目标规划 · 数据分析</p>
    </div>

    <!-- 概览卡片 -->
    <div class="overview-grid">
      <div class="overview-card">
        <div class="overview-icon wrong">
          <el-icon :size="22"><Warning /></el-icon>
        </div>
        <div class="overview-info">
          <span class="overview-value">{{ overview.wrong_unmastered }}</span>
          <span class="overview-label">待攻克错题</span>
        </div>
      </div>
      <div class="overview-card">
        <div class="overview-icon practice">
          <el-icon :size="22"><EditPen /></el-icon>
        </div>
        <div class="overview-info">
          <span class="overview-value">{{ overview.total_questions }}</span>
          <span class="overview-label">近 {{ overview.period_days }} 天刷题</span>
        </div>
      </div>
      <div class="overview-card">
        <div class="overview-icon ratio">
          <el-icon :size="22"><DataLine /></el-icon>
        </div>
        <div class="overview-info">
          <span class="overview-value">{{ (overview.score_ratio * 100).toFixed(1) }}%</span>
          <span class="overview-label">平均正确率</span>
        </div>
      </div>
      <div class="overview-card">
        <div class="overview-icon plan">
          <el-icon :size="22"><Flag /></el-icon>
        </div>
        <div class="overview-info">
          <span class="overview-value">{{ overview.active_plans }}</span>
          <span class="overview-label">进行中计划</span>
        </div>
      </div>
    </div>

    <!-- 功能模块卡片 -->
    <div class="module-grid">
      <div class="module-card" @click="$router.push('/learning/wrong')">
        <div class="module-icon" style="background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%)">
          <el-icon :size="28" color="white"><CollectionTag /></el-icon>
        </div>
        <h3>错题本</h3>
        <p>自动收录答错的题目，重做练习直到掌握</p>
        <span class="module-action">进入 →</span>
      </div>
      <div class="module-card" @click="$router.push('/learning/practice')">
        <div class="module-icon" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%)">
          <el-icon :size="28" color="white"><EditPen /></el-icon>
        </div>
        <h3>自由刷题</h3>
        <p>按专业/课程/章节筛选，随时练习不计分</p>
        <span class="module-action">进入 →</span>
      </div>
      <div class="module-card" @click="$router.push('/learning/plan')">
        <div class="module-icon" style="background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)">
          <el-icon :size="28" color="white"><Flag /></el-icon>
        </div>
        <h3>学习计划</h3>
        <p>设定练习目标，追踪完成进度</p>
        <span class="module-action">进入 →</span>
      </div>
      <div class="module-card" @click="$router.push('/learning/report')">
        <div class="module-icon" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%)">
          <el-icon :size="28" color="white"><PieChart /></el-icon>
        </div>
        <h3>学习报告</h3>
        <p>聚合历史数据，查看能力雷达与薄弱项</p>
        <span class="module-action">进入 →</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import request from '../utils/request'

const overview = ref({
  wrong_total: 0, wrong_unmastered: 0, wrong_mastered: 0,
  total_questions: 0, correct_count: 0, score_ratio: 0,
  total_time_sec: 0, sessions_count: 0,
  active_plans: 0, period_days: 30,
})

onMounted(async () => {
  try {
    const res = await request.get('/api/learning/report/overview?days=30')
    Object.assign(overview.value, res.data)
  } catch (e) { /* 首次使用可能无数据，静默忽略 */ }
})
</script>

<style scoped>
.learning-home {
  padding: 20px;
  max-width: 1200px;
}

.page-header {
  margin-bottom: 28px;
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

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}

.overview-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
}

.overview-icon {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.overview-icon.wrong { background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); }
.overview-icon.practice { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
.overview-icon.ratio { background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); }
.overview-icon.plan { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); }

.overview-info {
  display: flex;
  flex-direction: column;
}

.overview-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.overview-label {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.module-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 16px;
  padding: 28px 24px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.module-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.12);
  border-color: rgba(99, 102, 241, 0.4);
}

.module-icon {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 18px;
}

.module-card h3 {
  font-size: 17px;
  font-weight: 600;
  margin: 0 0 8px;
  color: var(--text-primary);
}

.module-card p {
  font-size: 13px;
  color: var(--text-muted);
  margin: 0 0 16px;
  line-height: 1.6;
}

.module-action {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-light);
  transition: color 0.3s ease;
}

.module-card:hover .module-action {
  color: #6366f1;
}

@media (max-width: 900px) {
  .overview-grid, .module-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
