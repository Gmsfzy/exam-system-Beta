/**
 * 题型/难度枚举单一来源（v4.6.1 枚举收敛）
 *
 * 与后端 database/models.py 的 QuestionTypeEnum / _QUESTION_TYPE_LABELS /
 * DifficultyEnum.LABELS 一一对应：新增枚举值时两侧同步修改。
 * 动态下发场景可走接口：GET /api/question-types、GET /api/difficulties。
 */

export const QUESTION_TYPE_LABELS = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  fill_blank: '填空题',
  true_false: '判断题',
  short_answer: '问答题',
  programming: '编程题',
  application: '应用题',
  calculation: '计算题',
  essay: '简答题', // 历史数据展示兜底（后端现行枚举无此值）
}

export const DIFFICULTY_LABELS = {
  easy: '简单',
  medium: '中等',
  hard: '困难',
}

/** 下拉选项（表单/筛选用），顺序与后端枚举声明一致 */
export const QUESTION_TYPE_OPTIONS = ['single_choice', 'multiple_choice', 'fill_blank', 'true_false', 'short_answer', 'programming', 'application', 'calculation']
  .map(value => ({ value, label: QUESTION_TYPE_LABELS[value] }))

export const DIFFICULTY_OPTIONS = ['easy', 'medium', 'hard']
  .map(value => ({ value, label: DIFFICULTY_LABELS[value] }))

/** 带选项(A/B/C/D)的题型：渲染分支/判分逻辑统一引用，勿再散落字面量数组 */
export const OPTION_TYPES = ['single_choice', 'multiple_choice']

export const typeLabel = (t) => QUESTION_TYPE_LABELS[t] || t || ''
export const difficultyLabel = (d) => DIFFICULTY_LABELS[d] || d || ''
export const hasOptions = (t) => OPTION_TYPES.includes(t)
