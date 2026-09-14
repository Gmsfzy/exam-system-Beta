<template>
  <div class="page-wrapper">
    <div class="stats-row">
      <div class="stat-card" v-for="stat in stats" :key="stat.label">
        <div class="stat-icon" :style="{ background: stat.bg }">
          <el-icon :size="24" color="white"><component :is="stat.icon" /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ stat.value }}</div>
          <div class="stat-label">{{ stat.label }}</div>
        </div>
      </div>
    </div>

    <div class="filter-bar">
      <div class="filter-left">
        <el-radio-group v-model="scope" size="small" @change="loadQuestions" class="scope-toggle">
          <el-radio-button value="">全部题目</el-radio-button>
          <el-radio-button value="mine">我的题目</el-radio-button>
          <el-radio-button value="public">公共题库</el-radio-button>
        </el-radio-group>
        <div class="search-box">
          <el-icon :size="16" class="search-icon"><Search /></el-icon>
          <el-input
            v-model="searchKeyword"
            placeholder="搜索题目内容..."
            clearable
            class="search-input"
          />
        </div>
        <el-select v-model="filter.major_id" placeholder="全部专业" clearable class="filter-select" @change="handleMajorChange">
          <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-select v-model="filter.course_id" placeholder="全部课程" clearable class="filter-select">
          <el-option v-for="c in filteredCourses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-select v-model="filter.type" placeholder="全部题型" clearable class="filter-select">
          <el-option v-for="(label, key) in typeLabels" :key="key" :label="label" :value="key" />
        </el-select>
        <el-select v-model="filter.difficulty" placeholder="全部难度" clearable class="filter-select">
          <el-option label="简单" value="easy" />
          <el-option label="中等" value="medium" />
          <el-option label="困难" value="hard" />
        </el-select>
      </div>
      <div class="action-buttons">
        <el-button type="success" class="import-btn" @click="openImportDialog">
          <el-icon><Upload /></el-icon>
          <span>批量导入</span>
        </el-button>
        <el-button type="primary" class="add-btn" @click="openAddDialog">
          <el-icon><Plus /></el-icon>
          <span>添加题目</span>
        </el-button>
      </div>
    </div>

    <el-dialog
      v-model="importDialogVisible"
      title="批量导入题目"
      width="600px"
      class="import-dialog"
      destroy-on-close
    >
      <div class="import-content">
        <div class="import-hint">
          <strong><i class="el-icon-lightbulb text-warning mr-2"></i>使用说明：</strong>
          <ul class="mt-2 pl-4">
            <li>支持 <code>.csv</code>、<code>.xlsx</code>（Excel）和 <code>.doc/.docx</code>（Word）格式</li>
            <li>表头必须与模板一致，下载模板后填写即可</li>
            <li>专业名不存在时会自动创建</li>
            <li>题型可选：单选题 / 多选题 / 填空题 / 判断题 / 问答题 / 编程题 / 应用题 / 计算题</li>
            <li>难度可选：简单 / 中等 / 困难</li>
          </ul>
        </div>
        <div class="form-group mt-4">
          <label class="font-weight-bold small">选择文件</label>
          <div class="custom-file-upload">
            <input type="file" name="file" id="importFileInput" accept=".csv,.xlsx,.xls,.doc,.docx" @change="handleFileSelect" />
            <label for="importFileInput" class="upload-label">
              <i class="el-icon-upload"></i>
              <span>{{ selectedFileName || '点击选择文件' }}</span>
            </label>
          </div>
        </div>
        <div class="template-links mt-4 text-center">
          <el-button type="text" class="template-btn" @click="downloadTemplate('csv')">
            <i class="el-icon-file-csv"></i>下载 CSV 模板
          </el-button>
          <el-button type="text" class="template-btn" @click="downloadTemplate('excel')">
            <i class="el-icon-file-excel"></i>下载 Excel 模板
          </el-button>
          <el-button type="text" class="template-btn" @click="downloadTemplate('word')">
            <i class="el-icon-file-word"></i>下载 Word 模板
          </el-button>
        </div>
      </div>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleImport" :loading="importing" :disabled="!selectedFile">
          <el-icon><Upload /></el-icon>开始导入
        </el-button>
      </template>
    </el-dialog>

    <div v-if="filteredQuestions.length" class="question-grid">
      <div
        v-for="q in filteredQuestions"
        :key="q.id"
        class="question-card"
        @click="viewDetail(q)"
      >
        <div class="card-header">
          <div class="card-badges">
            <span class="badge-type" :class="q.type">{{ typeLabels[q.type] || q.type }}</span>
            <span class="badge-diff" :class="q.difficulty">{{ diffLabels[q.difficulty] }}</span>
            <span class="badge-source" :class="q.source || 'manual'">{{ sourceLabels[q.source] || '手动输入' }}</span>
            <span v-if="q.is_public" class="badge-public">公共</span>
            <span v-if="q.creator_name" class="badge-creator">{{ q.creator_name }}</span>
          </div>
          <el-dropdown @command="cmd => handleCardAction(cmd, q)" @click.stop>
            <el-icon class="more-icon"><More /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="edit" :disabled="!q.is_owner"><el-icon><Edit /></el-icon>编辑</el-dropdown-item>
                <el-dropdown-item command="toggle_public" v-if="q.is_owner">
                  <el-icon><Share /></el-icon>{{ q.is_public ? '移出公共题库' : '加入公共题库' }}
                </el-dropdown-item>
                <el-dropdown-item command="delete" divided :disabled="!q.is_owner"><el-icon><Delete /></el-icon>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <div class="card-body">
          <div class="question-content">
            <KatexRenderer :formula="q.content" />
          </div>
          <div v-if="q.options" class="question-options">
            <div v-for="(opt, idx) in parseOptions(q.options)" :key="idx" class="option-item">
              <span class="option-label">{{ ['A','B','C','D','E','F'][idx] }}</span>
              <span class="option-text">
                <KatexRenderer :formula="opt" />
              </span>
            </div>
          </div>
        </div>

        <div class="card-footer">
          <div class="footer-left">
            <el-icon :size="14"><Collection /></el-icon>
            <span>{{ q.major_name }}</span>
          </div>
          <div class="footer-right">
            <el-tag size="small" :type="q.is_correct ? 'success' : 'info'" effect="plain">
              答案: {{ q.answer }}
            </el-tag>
          </div>
        </div>
        
        <div v-if="q.knowledge" class="knowledge-tags">
          <el-tag v-for="(tag, idx) in q.knowledge.split(',').filter(t => t.trim())" :key="idx" size="small" effect="plain">
            {{ tag.trim() }}
          </el-tag>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <el-icon :size="64" class="empty-icon"><DocumentDelete /></el-icon>
      <h3>暂无题目</h3>
      <p>点击右上角添加按钮创建第一道题目</p>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑题目' : '添加题目'"
      width="900px"
      class="question-dialog"
      destroy-on-close
    >
      <el-form :model="form" label-width="90px" class="dialog-form">
        <el-form-item label="题目内容">
          <div class="editor-textarea-wrapper">
            <div class="editor-toolbar">
              <div class="toolbar-group">
                <el-button type="text" size="small" class="editor-btn" title="加粗" @click="insertFormat('**', '**', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-bold" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="斜体" @click="insertFormat('*', '*', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-italic" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="下划线" @click="insertFormat('<u>', '</u>', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-underline" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="删除线" @click="insertFormat('~~', '~~', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-strikethrough" />
                </el-button>
              </div>
              <div class="toolbar-group">
                <el-button type="text" size="small" class="editor-btn" title="上标" @click="insertFormat('^', '', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-superscript" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="下标" @click="insertFormat('_', '', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-subscript" />
                </el-button>
              </div>
              <div class="toolbar-group">
                <el-button type="text" size="small" class="editor-btn" title="分数" @click="insertFormat('\\frac{分子}{分母}', '', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-divide" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="根号" @click="insertFormat('\\sqrt{内容}', '', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-square-root-variable" />
                </el-button>
              </div>
              <div class="toolbar-group math-group">
                <el-button type="text" size="small" class="editor-btn math-btn" title="α" @click="insertSymbol('\\alpha', 'contentTextarea')">α</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="β" @click="insertSymbol('\\beta', 'contentTextarea')">β</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="γ" @click="insertSymbol('\\gamma', 'contentTextarea')">γ</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="π" @click="insertSymbol('\\pi', 'contentTextarea')">π</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="θ" @click="insertSymbol('\\theta', 'contentTextarea')">θ</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="λ" @click="insertSymbol('\\lambda', 'contentTextarea')">λ</el-button>
              </div>
              <div class="toolbar-group math-group">
                <el-button type="text" size="small" class="editor-btn math-btn" title="∫" @click="insertSymbol('\\int', 'contentTextarea')">∫</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="∑" @click="insertSymbol('\\sum', 'contentTextarea')">∑</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="√" @click="insertSymbol('\\sqrt', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-square-root-variable" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="∞" @click="insertSymbol('\\infty', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-infinity" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="≠" @click="insertSymbol('\\neq', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-not-equal" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="≤" @click="insertSymbol('\\leq', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-less-than-equal" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="≥" @click="insertSymbol('\\geq', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-greater-than-equal" />
                </el-button>
              </div>
              <div class="toolbar-group">
                <el-button type="text" size="small" class="editor-btn" title="插入公式块" @click="insertFormat('$$\\n', '\\n$$', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-square" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="插入行内公式" @click="insertFormat('$', '$', 'contentTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-circle" />
                </el-button>
              </div>
            </div>
            <el-input 
              v-model="form.content" 
              type="textarea" 
              rows="4" 
              placeholder="请输入题目内容，支持 LaTeX 公式，如 $x^2 + y^2 = r^2$"
              class="content-textarea"
              id="contentTextarea"
            />
          </div>
          <div class="media-toolbar">
            <el-button type="text" size="small" class="media-btn" @click="insertMedia('image')">
              <el-icon class="media-icon"><Picture /></el-icon>插入图片
            </el-button>
            <el-button type="text" size="small" class="media-btn" @click="insertMedia('video')">
              <el-icon class="media-icon"><VideoPlay /></el-icon>插入视频
            </el-button>
            <el-button type="text" size="small" class="media-btn" @click="insertMedia('gif')">
              <el-icon class="media-icon"><PictureFilled /></el-icon>插入动图
            </el-button>
          </div>
          <div v-if="uploadedFiles.length > 0" class="uploaded-files-preview">
            <div v-for="(file, idx) in uploadedFiles" :key="idx" class="preview-item">
              <div class="preview-content">
                <img v-if="file.type === 'image'" :src="file.url" class="preview-image" />
                <video v-else :src="file.url" class="preview-video" controls />
              </div>
              <div class="preview-info">
                <span class="preview-filename">{{ file.url.split('/').pop() }}</span>
              </div>
              <button type="button" class="remove-preview-btn" @click="removeUploadedFile(idx)">
                <el-icon><Close /></el-icon>
              </button>
            </div>
          </div>
        </el-form-item>

        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="题型">
              <el-select v-model="form.type" style="width: 100%" @change="handleTypeChange">
                <el-option v-for="(label, key) in typeLabels" :key="key" :label="label" :value="key" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="难度">
              <el-select v-model="form.difficulty" style="width: 100%">
                <el-option label="简单" value="easy" />
                <el-option label="中等" value="medium" />
                <el-option label="困难" value="hard" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="题目来源">
              <el-select v-model="form.source" style="width: 100%">
                <el-option label="手动输入" value="manual" />
                <el-option label="AI生成" value="ai" />
                <el-option label="历年真题" value="past_exam" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="选项" v-if="showOptions">
          <div class="options-editor">
            <div v-for="(opt, idx) in optionList" :key="idx" class="option-row">
              <span class="option-letter">{{ ['A','B','C','D','E','F','G','H'][idx] }}</span>
              <el-input 
                v-model="optionList[idx]" 
                :placeholder="`选项 ${['A','B','C','D','E','F','G','H'][idx]}`" 
                class="option-input"
              />
              <el-button 
                v-if="optionList.length > 2" 
                type="danger" 
                size="small" 
                icon="Delete" 
                @click="removeOption(idx)"
              />
            </div>
            <el-button 
              v-if="optionList.length < 8" 
              type="primary" 
              size="small" 
              icon="Plus" 
              @click="addOption"
              class="add-option-btn"
            >添加选项</el-button>
            <small class="text-muted d-block mt-2">答案请填写选项字母，如：A 或 AB</small>
          </div>
        </el-form-item>

        <el-form-item label="答案" v-if="showTrueFalse">
          <div class="true-false-options">
            <div class="true-false-row">
              <label class="true-false-label">
                <input type="radio" v-model="form.answer" value="正确" />
                <span class="true-option">✓ 正确</span>
              </label>
              <label class="true-false-label">
                <input type="radio" v-model="form.answer" value="错误" />
                <span class="false-option">✗ 错误</span>
              </label>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="正确答案" v-if="showTextAnswer">
          <el-input v-model="form.answer" :placeholder="answerPlaceholder" />
        </el-form-item>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="专业">
              <el-select v-model="form.major_id" style="width: 100%" @change="handleMajorChangeInForm">
                <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="课程">
              <el-select v-model="form.course_id" style="width: 100%" placeholder="请选择课程">
                <el-option v-for="c in formFilteredCourses" :key="c.id" :label="c.name" :value="c.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="答案解析">
          <div class="editor-textarea-wrapper">
            <div class="editor-toolbar analysis-toolbar">
              <div class="toolbar-group">
                <el-button type="text" size="small" class="editor-btn" title="加粗" @click="insertFormat('**', '**', 'analysisTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-bold" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="斜体" @click="insertFormat('*', '*', 'analysisTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-italic" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="下划线" @click="insertFormat('<u>', '</u>', 'analysisTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-underline" />
                </el-button>
              </div>
              <div class="toolbar-group math-group">
                <el-button type="text" size="small" class="editor-btn math-btn" title="α" @click="insertSymbol('\\alpha', 'analysisTextarea')">α</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="β" @click="insertSymbol('\\beta', 'analysisTextarea')">β</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="π" @click="insertSymbol('\\pi', 'analysisTextarea')">π</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="∫" @click="insertSymbol('\\int', 'analysisTextarea')">∫</el-button>
                <el-button type="text" size="small" class="editor-btn math-btn" title="∑" @click="insertSymbol('\\sum', 'analysisTextarea')">∑</el-button>
              </div>
              <div class="toolbar-group">
                <el-button type="text" size="small" class="editor-btn" title="插入公式块" @click="insertFormat('$$\\n', '\\n$$', 'analysisTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-square" />
                </el-button>
                <el-button type="text" size="small" class="editor-btn" title="插入行内公式" @click="insertFormat('$', '$', 'analysisTextarea')">
                  <FontAwesomeIcon icon="fa-solid fa-circle" />
                </el-button>
              </div>
            </div>
            <el-input v-model="form.analysis" type="textarea" rows="3" placeholder="请输入答案解析（可选）" id="analysisTextarea" />
          </div>
        </el-form-item>

        <el-form-item label="公开到公共题库">
          <el-switch v-model="form.is_public" />
          <span class="form-tip" style="margin-left: 10px;">开启后其他教师可在「公共题库」中查看本题</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveQuestion" :loading="saving">
          {{ isEdit ? '保存修改' : '确认添加' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="题目详情" width="800px" class="detail-dialog">
      <div v-if="detailQuestion" class="detail-content">
        <div class="detail-badges">
          <span class="badge-type" :class="detailQuestion.type">
            {{ typeLabels[detailQuestion.type] }}
          </span>
          <span class="badge-diff" :class="detailQuestion.difficulty">
            {{ diffLabels[detailQuestion.difficulty] }}
          </span>
          <span class="badge-source" :class="detailQuestion.source || 'manual'">
            {{ sourceLabels[detailQuestion.source] || '手动输入' }}
          </span>
          <span class="badge-major">{{ detailQuestion.major_name }}</span>
        </div>
        <div class="detail-section">
          <h4>题目内容</h4>
          <p><KatexRenderer :formula="detailQuestion.content" /></p>
        </div>
        <div v-if="detailQuestion.options" class="detail-section">
          <h4>选项</h4>
          <div v-for="(opt, idx) in parseOptions(detailQuestion.options)" :key="idx" class="detail-option">
            <span class="opt-label">{{ ['A','B','C','D','E','F'][idx] }}</span>
            <span><KatexRenderer :formula="opt" /></span>
          </div>
        </div>
        <div class="detail-section">
          <h4>答案</h4>
          <p class="answer-text"><KatexRenderer :formula="detailQuestion.answer" /></p>
        </div>
        <div v-if="detailQuestion.analysis" class="detail-section">
          <h4>解析</h4>
          <p class="analysis-text"><KatexRenderer :formula="detailQuestion.analysis" /></p>
        </div>
        <div v-if="detailQuestion.knowledge" class="detail-section">
          <h4>知识点</h4>
          <div class="knowledge-list">
            <el-tag v-for="(tag, idx) in detailQuestion.knowledge.split(',').filter(t => t.trim())" :key="idx" size="small">
              {{ tag.trim() }}
            </el-tag>
          </div>
        </div>
        <div class="detail-section">
          <h4>题目来源</h4>
          <div class="source-edit-row">
            <el-select v-model="detailQuestion.source" style="width: 150px" @change="updateSource">
              <el-option label="手动输入" value="manual" />
              <el-option label="AI生成" value="ai" />
              <el-option label="历年真题" value="past_exam" />
            </el-select>
            <el-button type="success" size="small" @click="updateSource">
              <el-icon><Edit /></el-icon>保存
            </el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="primary" @click="editDetailQuestion">
          <el-icon><Edit /></el-icon>编辑题目
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import request from '../utils/request'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Search, More, Edit, Delete, Collection, Close, Upload, Share,
  Document, DocumentDelete, DocumentChecked, Warning, VideoPlay, PictureFilled, Picture
} from '@element-plus/icons-vue'
import KatexRenderer from '../components/KatexRenderer.vue'

const questions = ref([])
const majors = ref([])
const courses = ref([])
const dialogVisible = ref(false)
const detailVisible = ref(false)
const importDialogVisible = ref(false)
const isEdit = ref(false)
const saving = ref(false)
const importing = ref(false)
const selectedFile = ref(null)
const selectedFileName = ref('')
const searchKeyword = ref('')
const detailQuestion = ref(null)
const uploadedFiles = ref([])

const filter = ref({ major_id: '', course_id: '', type: '', difficulty: '' })
const scope = ref('')

const typeLabels = {
  single_choice: '单选题', multiple_choice: '多选题', fill_blank: '填空题',
  true_false: '判断题', short_answer: '问答题', programming: '编程题',
  application: '应用题', calculation: '计算题'
}
const diffLabels = { easy: '简单', medium: '中等', hard: '困难' }
const sourceLabels = { manual: '手动输入', ai: 'AI生成', past_exam: '历年真题' }

const optionTypes = ['single_choice', 'multiple_choice']
const showOptions = computed(() => optionTypes.includes(form.value.type))
const showTrueFalse = computed(() => form.value.type === 'true_false')
const showTextAnswer = computed(() => !optionTypes.includes(form.value.type) && form.value.type !== 'true_false')

const answerPlaceholder = computed(() => {
  if (form.value.type === 'fill_blank') {
    return '请输入填空答案，多个空用 | 分隔，如：答案1|答案2'
  } else if (optionTypes.includes(form.value.type)) {
    return '请输入选项字母，如：A 或 AB'
  }
  return '请输入正确答案'
})

const optionList = ref(['', '', '', ''])

const stats = computed(() => [
  { label: '总题目数', value: questions.value.length, icon: 'Document', bg: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' },
  { label: '单选题', value: questions.value.filter(q => q.type === 'single_choice').length, icon: 'DocumentChecked', bg: 'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)' },
  { label: '多选题', value: questions.value.filter(q => q.type === 'multiple_choice').length, icon: 'Warning', bg: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)' },
  { label: '其他题型', value: questions.value.filter(q => !['single_choice','multiple_choice'].includes(q.type)).length, icon: 'DocumentDelete', bg: 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)' },
])

const filteredQuestions = computed(() => {
  return questions.value.filter(q => {
    if (filter.value.major_id && q.major_id !== filter.value.major_id) return false
    if (filter.value.course_id && q.course_id !== filter.value.course_id) return false
    if (filter.value.type && q.type !== filter.value.type) return false
    if (filter.value.difficulty && q.difficulty !== filter.value.difficulty) return false
    if (searchKeyword.value && !q.content.includes(searchKeyword.value)) return false
    return true
  })
})

const filteredCourses = computed(() => {
  if (!filter.value.major_id) return courses.value
  return courses.value.filter(c => c.major_id === filter.value.major_id)
})

const formFilteredCourses = computed(() => {
  if (!form.value.major_id) return courses.value
  return courses.value.filter(c => c.major_id === form.value.major_id)
})

const handleMajorChange = () => {
  filter.value.course_id = ''
  fetchCourses()
}

const handleMajorChangeInForm = () => {
  form.value.course_id = ''
}

const handleTypeChange = () => {
  if (!optionTypes.includes(form.value.type) && form.value.type !== 'true_false') {
    optionList.value = ['', '', '', '']
  }
}

const form = ref({
  id: null, content: '', type: 'single_choice', difficulty: 'medium',
  major_id: '', course_id: '', options: '', answer: '', analysis: '', source: 'manual'
})

const parseOptions = (opts) => {
  try { return JSON.parse(opts) } catch { return [] }
}

const addOption = () => {
  if (optionList.value.length < 8) {
    optionList.value.push('')
  }
}

const removeOption = (idx) => {
  if (optionList.value.length > 2) {
    optionList.value.splice(idx, 1)
  }
}

const syncOptions = () => {
  if (form.value.options) {
    const opts = parseOptions(form.value.options)
    optionList.value = opts.length > 0 ? opts : ['', '', '', '']
  } else {
    optionList.value = ['', '', '', '']
  }
}

const buildOptions = () => {
  const validOptions = optionList.value.filter(o => o.trim())
  if (validOptions.length > 0) {
    form.value.options = JSON.stringify(validOptions)
  } else {
    form.value.options = ''
  }
}

const fetchQuestions = async () => {
  const params = {}
  if (scope.value) params.scope = scope.value
  const res = await request.get('/api/questions', { params })
  questions.value = res.data
}

// 兼容模板中 @change="loadQuestions" 的调用名
const loadQuestions = fetchQuestions

const fetchMajors = async () => {
  const res = await request.get('/api/majors')
  majors.value = res.data
}

const fetchCourses = async () => {
  const res = await request.get('/api/courses')
  courses.value = res.data
}

const openAddDialog = () => {
  isEdit.value = false
  form.value = { id: null, content: '', type: 'single_choice', difficulty: 'medium', major_id: majors.value[0]?.id || '', course_id: '', options: '', answer: '', analysis: '', source: 'manual', is_public: false }
  optionList.value = ['', '', '', '']
  uploadedFiles.value = []
  dialogVisible.value = true
}

const openImportDialog = () => {
  importDialogVisible.value = true
  selectedFile.value = null
  selectedFileName.value = ''
}

const handleFileSelect = (e) => {
  const file = e.target.files[0]
  if (file) {
    selectedFile.value = file
    selectedFileName.value = file.name
  }
}

const downloadTemplate = async (format) => {
  try {
    const response = await request.get(`/api/questions/template/${format}`, {
      responseType: 'blob'
    })
    
    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    
    const filename = `question_template.${format === 'excel' ? 'xlsx' : format}`
    link.download = filename
    
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    
    ElMessage.success('模板下载成功')
  } catch (error) {
    console.error('下载模板失败:', error)
    ElMessage.error('下载模板失败')
  }
}

const handleImport = async () => {
  if (!selectedFile.value) return
  
  importing.value = true
  
  const formData = new FormData()
  formData.append('file', selectedFile.value)
  
  try {
    const response = await request.post('/api/questions/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000
    })
    
    const { success, count, message } = response.data
    
    if (success) {
      ElMessage.success(`导入成功！共导入 ${count} 道题目`)
      importDialogVisible.value = false
      fetchQuestions()
    } else {
      ElMessage.warning(message || '导入部分成功')
    }
  } catch (error) {
    console.error('导入失败:', error)
    ElMessage.error('导入失败，请检查文件格式')
  } finally {
    importing.value = false
    selectedFile.value = null
    selectedFileName.value = ''
  }
}

const viewDetail = (q) => {
  detailQuestion.value = q
  detailVisible.value = true
}

const editDetailQuestion = () => {
  if (detailQuestion.value) {
    isEdit.value = true
    form.value = { ...detailQuestion.value }
    syncOptions()
    uploadedFiles.value = []
    detailVisible.value = false
    dialogVisible.value = true
  }
}

const updateSource = async () => {
  if (!detailQuestion.value) return
  try {
    await request.put(`/api/questions/${detailQuestion.value.id}`, {
      ...detailQuestion.value,
      source: detailQuestion.value.source
    })
    ElMessage.success('来源更新成功')
    fetchQuestions()
  } catch (e) {
    ElMessage.error('更新失败')
  }
}

const handleCardAction = (cmd, q) => {
  if (cmd === 'edit') {
    isEdit.value = true
    form.value = { ...q, is_public: !!q.is_public }
    syncOptions()
    uploadedFiles.value = []
    dialogVisible.value = true
  } else if (cmd === 'delete') {
    deleteQuestion(q.id)
  } else if (cmd === 'toggle_public') {
    togglePublic(q)
  }
}

const togglePublic = async (q) => {
  try {
    const res = await request.post(`/api/questions/${q.id}/toggle_public`)
    ElMessage.success(res.data.message)
    fetchQuestions()
  } catch (e) { /* 拦截器已处理 */ }
}

const insertFormat = (before, after, textareaId) => {
  const textarea = document.getElementById(textareaId)
  if (!textarea) return
  
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const selectedText = textarea.value.substring(start, end)
  const textBefore = textarea.value.substring(0, start)
  const textAfter = textarea.value.substring(end)
  
  const insertText = before + (selectedText || '') + after
  textarea.value = textBefore + insertText + textAfter
  
  textarea.focus()
  const cursorPos = start + before.length + (selectedText ? selectedText.length : 0)
  textarea.setSelectionRange(cursorPos, cursorPos)
}

const insertSymbol = (symbol, textareaId) => {
  const textarea = document.getElementById(textareaId)
  if (!textarea) return
  
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const textBefore = textarea.value.substring(0, start)
  const textAfter = textarea.value.substring(end)
  
  textarea.value = textBefore + '$' + symbol + '$' + textAfter
  
  textarea.focus()
  textarea.setSelectionRange(start + symbol.length + 2, start + symbol.length + 2)
}

const insertMedia = async (type) => {
  const input = document.createElement('input')
  input.type = 'file'
  input.style.display = 'none'
  
  if (type === 'image') {
    input.accept = 'image/jpeg,image/png,image/webp'
  } else if (type === 'video') {
    input.accept = 'video/mp4,video/webm,video/avi'
  } else if (type === 'gif') {
    input.accept = 'image/gif'
  }
  
  input.onchange = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    
    const loading = ElLoading.service({ text: '上传中...' })
    
    const formData = new FormData()
    formData.append('file', file)
    
    try {
      const res = await request.post('/api/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 30000
      })
      
      const url = res.data.url
      uploadedFiles.value.push({ url, type: type === 'video' ? 'video' : 'image' })
      
      const textarea = document.querySelector('.question-dialog textarea.el-textarea__inner')
      if (textarea) {
        const cursorPos = textarea.selectionStart
        const textBefore = form.value.content.substring(0, cursorPos)
        const textAfter = form.value.content.substring(cursorPos)
        
        if (type === 'video') {
          form.value.content = textBefore + '\n[视频:' + url + ']\n' + textAfter
        } else {
          form.value.content = textBefore + '\n![图片](' + url + ')\n' + textAfter
        }
        
        setTimeout(() => {
          textarea.focus()
          textarea.setSelectionRange(cursorPos + (type === 'video' ? 10 : 8), cursorPos + (type === 'video' ? 10 : 8))
        }, 100)
      } else {
        if (type === 'video') {
          form.value.content += '\n[视频:' + url + ']\n'
        } else {
          form.value.content += '\n![图片](' + url + ')\n'
        }
      }
      
      ElMessage.success('上传成功')
    } catch (e) {
      console.error('上传错误:', e)
      ElMessage.error('上传失败，请检查网络或文件大小')
    } finally {
      loading.close()
    }
  }
  
  input.click()
}

const removeUploadedFile = (idx) => {
  uploadedFiles.value.splice(idx, 1)
}

const saveQuestion = async () => {
  saving.value = true
  try {
    if (showOptions.value) {
      buildOptions()
    }
    if (isEdit.value) {
      await request.put(`/api/questions/${form.value.id}`, form.value)
      ElMessage.success('更新成功')
    } else {
      await request.post('/api/questions', form.value)
      ElMessage.success('添加成功')
    }
    dialogVisible.value = false
    fetchQuestions()
  } catch (e) {
    console.error(e)
  } finally {
    saving.value = false
  }
}

const deleteQuestion = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该题目吗？', '提示', { type: 'warning' })
    await request.delete(`/api/questions/${id}`)
    ElMessage.success('删除成功')
    fetchQuestions()
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}

onMounted(() => {
  fetchQuestions()
  fetchMajors()
  fetchCourses()
})
</script>

<style scoped>
.page-wrapper {
  max-width: 1400px;
  margin: 0 auto;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}
.stat-card {
  background: white;
  border-radius: 16px;
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  transition: all 0.3s;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(0,0,0,0.08);
}
.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1;
}
.stat-label {
  font-size: 14px;
  color: #64748b;
  margin-top: 6px;
}

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
  gap: 20px;
}
.filter-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}
.search-box {
  position: relative;
  flex: 1;
  max-width: 360px;
}
.search-icon {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
  z-index: 2;
  transition: all 0.3s;
}
.search-box:focus-within .search-icon {
  color: #667eea;
  transform: translateY(-50%) scale(1.1);
}
.search-input :deep(.el-input__wrapper) {
  padding-left: 44px;
  border-radius: 16px;
  background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid rgba(148, 163, 184, 0.2);
  box-shadow: 
    0 1px 2px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.search-input :deep(.el-input__wrapper):hover {
  border-color: rgba(102, 126, 234, 0.3);
}
.search-input :deep(.el-input__wrapper):focus-within {
  border-color: #667eea;
  box-shadow: 
    0 0 0 3px rgba(102, 126, 234, 0.1),
    0 4px 12px rgba(102, 126, 234, 0.15);
}
.filter-select {
  width: 160px;
}
.filter-select :deep(.el-input__wrapper) {
  border-radius: 14px;
  background: linear-gradient(145deg, #ffffff 0%, #f8fafc 100%);
  border: 1px solid rgba(148, 163, 184, 0.2);
  transition: all 0.3s;
}
.filter-select :deep(.el-input__wrapper):hover {
  border-color: rgba(102, 126, 234, 0.3);
}
.filter-select :deep(.el-input__wrapper):focus-within {
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}
.add-btn {
  border-radius: 16px;
  padding: 0 28px;
  height: 44px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  font-weight: 600;
  font-size: 14px;
  box-shadow: 
    0 4px 15px rgba(102, 126, 234, 0.35),
    0 2px 4px rgba(118, 75, 162, 0.2);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}
.add-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.2) 0%, transparent 50%);
}
.add-btn:hover {
  transform: translateY(-2px);
  box-shadow: 
    0 8px 25px rgba(102, 126, 234, 0.45),
    0 4px 10px rgba(118, 75, 162, 0.3);
}
.add-btn:active {
  transform: translateY(0);
}

.question-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 24px;
}
.question-card {
  background: var(--bg-card);
  border-radius: 24px;
  padding: 32px;
  box-shadow: var(--shadow-sm);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
  border: 1px solid var(--border-color);
  position: relative;
  overflow: hidden;
}
.question-card::before {
  content: '';
  position: absolute;
  top: -40px;
  right: -40px;
  width: 100px;
  height: 100px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.05) 0%, transparent 70%);
  opacity: 0;
  transition: opacity 0.4s ease;
}
.question-card:hover {
  transform: translateY(-8px) scale(1.01);
  box-shadow: var(--shadow-xl);
  border-color: rgba(99, 102, 241, 0.2);
}
.question-card:hover::before {
  opacity: 1;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
  position: relative;
  z-index: 1;
}
.card-badges {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.badge-type, .badge-diff, .badge-major {
  padding: 6px 14px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  position: relative;
  overflow: hidden;
  transition: all 0.3s;
}
.badge-type::before, .badge-diff::before, .badge-major::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.3) 0%, transparent 50%);
}
.badge-type.single_choice { 
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%); 
  color: #1d4ed8;
  box-shadow: 0 2px 8px rgba(30, 77, 216, 0.15);
}
.badge-type.multiple_choice { 
  background: linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%); 
  color: #be185d;
  box-shadow: 0 2px 8px rgba(190, 24, 93, 0.15);
}
.badge-type.fill_blank { 
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); 
  color: #b45309;
  box-shadow: 0 2px 8px rgba(180, 83, 9, 0.15);
}
.badge-type.true_false { 
  background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%); 
  color: #047857;
  box-shadow: 0 2px 8px rgba(4, 120, 87, 0.15);
}
.badge-type { 
  background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%); 
  color: #475569;
}

.badge-diff.easy { 
  background: linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%); 
  color: #047857;
}
.badge-diff.medium { 
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); 
  color: #b45309;
}
.badge-diff.hard { 
  background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); 
  color: #b91c1c;
}
.badge-major { 
  background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%); 
  color: #7c3aed;
}
.badge-source {
  padding: 6px 14px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  position: relative;
  overflow: hidden;
  transition: all 0.3s;
}
.badge-source::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.3) 0%, transparent 50%);
}
.badge-source.manual {
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  color: #1d4ed8;
  box-shadow: 0 2px 8px rgba(30, 77, 216, 0.15);
}
.badge-source.ai {
  background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%);
  color: #7c3aed;
  box-shadow: 0 2px 8px rgba(124, 58, 237, 0.15);
}
.badge-source.past_exam {
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #b45309;
  box-shadow: 0 2px 8px rgba(180, 83, 9, 0.15);
}

.badge-public {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  background: linear-gradient(135deg, #ddd6fe 0%, #c4b5fd 100%);
  color: #6d28d9;
  box-shadow: 0 2px 8px rgba(109, 40, 217, 0.12);
}

.badge-creator {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  background: rgba(148, 163, 184, 0.12);
  color: #64748b;
}

.scope-toggle {
  margin-right: 4px;
}

.more-icon {
  color: #94a3b8;
  cursor: pointer;
  padding: 8px;
  border-radius: 12px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  background: rgba(148, 163, 184, 0.08);
}
.more-icon:hover {
  background: rgba(148, 163, 184, 0.15);
  color: #64748b;
  transform: rotate(90deg);
}

.card-body {
  margin-bottom: 20px;
  position: relative;
  z-index: 1;
}
.question-content {
  font-size: 16px;
  color: #1e293b;
  line-height: 1.7;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  padding: 16px;
  background: rgba(148, 163, 184, 0.06);
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.1);
  position: relative;
}
.question-content::before {
  content: '';
  position: absolute;
  top: 12px;
  left: 12px;
  width: 4px;
  height: 4px;
  background: #667eea;
  border-radius: 50%;
}
.question-options {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.option-item {
  display: flex;
  gap: 12px;
  font-size: 14px;
  color: #475569;
  padding: 12px 14px;
  background: rgba(241, 245, 249, 0.6);
  border-radius: 12px;
  border: 1px solid transparent;
  transition: all 0.3s;
}
.option-item:hover {
  background: rgba(102, 126, 234, 0.06);
  border-color: rgba(102, 126, 234, 0.2);
}
.option-label {
  font-weight: 700;
  color: #667eea;
  min-width: 24px;
  font-size: 13px;
  padding: 4px 8px;
  background: rgba(102, 126, 234, 0.1);
  border-radius: 6px;
  text-align: center;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: linear-gradient(135deg, rgba(241, 245, 249, 0.6) 0%, rgba(226, 232, 240, 0.4) 100%);
  border-radius: 14px;
  position: relative;
  z-index: 1;
}
.footer-left {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}

.empty-state {
  text-align: center;
  padding: 80px 20px;
  color: #94a3b8;
}
.empty-state h3 {
  font-size: 20px;
  color: #475569;
  margin: 16px 0 8px;
}
.empty-state p {
  font-size: 14px;
}
.empty-icon {
  color: #cbd5e1;
}

.detail-content {
  padding: 10px 0;
}
.detail-badges {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
}
.detail-section {
  margin-bottom: 20px;
}
.detail-section h4 {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 8px;
  font-weight: 500;
}
.detail-section p {
  color: #1e293b;
  line-height: 1.6;
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: 10px;
}
.source-edit-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.source-edit-row .el-select {
  border-radius: 8px;
}
.source-edit-row .el-button {
  border-radius: 8px;
}
.detail-option {
  display: flex;
  gap: 10px;
  padding: 8px 12px;
  margin-bottom: 6px;
  background: #f8fafc;
  border-radius: 8px;
  font-size: 14px;
}
.opt-label {
  font-weight: 600;
  color: #3b82f6;
  min-width: 24px;
}
.answer-text {
  color: #059669;
  font-weight: 600;
}
.analysis-text {
  color: #7c3aed;
}

.question-dialog :deep(.el-dialog__header) {
  padding: 20px 24px;
  border-bottom: 1px solid #f1f5f9;
}
.question-dialog :deep(.el-dialog__body) {
  padding: 24px;
}
.dialog-form :deep(.el-input__wrapper),
.dialog-form :deep(.el-textarea__inner) {
  border-radius: 10px;
}

.options-editor {
  margin-top: 8px;
}
.option-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.option-letter {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
  flex-shrink: 0;
}
.option-input {
  flex: 1;
}
.add-option-btn {
  margin-top: 8px;
}

.true-false-options {
  margin-top: 8px;
}
.true-false-row {
  display: flex;
  gap: 24px;
}
.true-false-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 12px 20px;
  border-radius: 12px;
  background: #f8fafc;
  transition: all 0.3s;
}
.true-false-label:hover {
  background: #f1f5f9;
}
.true-false-label input[type="radio"] {
  display: none;
}
.true-false-label input[type="radio"]:checked + span {
  font-weight: 600;
}
.true-false-label input[type="radio"]:checked + .true-option {
  color: #059669;
  background: rgba(5, 150, 105, 0.1);
}
.true-false-label input[type="radio"]:checked + .false-option {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.1);
}
.true-option, .false-option {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 14px;
  transition: all 0.3s;
}
.true-option { color: #64748b; }
.false-option { color: #64748b; }

.media-toolbar {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  padding: 12px 16px;
  background: rgba(102, 126, 234, 0.04);
  border-radius: 12px;
  border: 1px solid rgba(102, 126, 234, 0.1);
}
.media-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #667eea;
  font-size: 13px;
  font-weight: 500;
  padding: 8px 14px;
  border-radius: 8px;
  transition: all 0.2s;
}
.media-btn:hover {
  color: #764ba2;
  background: rgba(102, 126, 234, 0.1);
}
.media-icon {
  font-size: 16px;
}

.uploaded-files-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 16px;
}
.preview-item {
  position: relative;
  background: #f8fafc;
  border-radius: 12px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  transition: all 0.3s;
}
.preview-item:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
}
.preview-content {
  position: relative;
}
.preview-image {
  max-width: 180px;
  max-height: 120px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.preview-video {
  max-width: 220px;
  max-height: 130px;
  border-radius: 8px;
}
.preview-info {
  margin-top: 8px;
}
.preview-filename {
  font-size: 12px;
  color: #64748b;
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
}
.remove-preview-btn {
  position: absolute;
  top: -10px;
  right: -10px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #ef4444;
  color: white;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.3);
  transition: all 0.2s;
}
.remove-preview-btn:hover {
  background: #dc2626;
  transform: scale(1.1);
}

.dark .page-wrapper {
  background: var(--bg-secondary);
}
.dark .stats-row {
  background: transparent;
}
.dark .stat-card {
  background: var(--gradient-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: var(--shadow-card);
  border: 1px solid var(--glass-border);
}
.dark .stat-value {
  color: var(--text-primary);
}
.dark .stat-label {
  color: var(--text-light);
}
.dark .search-box {
  background: transparent;
}
.dark .search-icon {
  color: var(--text-light);
}
.dark .search-box:focus-within .search-icon {
  color: var(--primary-500);
}
.dark .search-input :deep(.el-input__wrapper) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
  box-shadow: 0 1px 2px rgba(0,0,0,0.3) !important;
}
.dark .search-input :deep(.el-input__inner) {
  color: var(--text-primary) !important;
}
.dark .search-input :deep(.el-input__placeholder) {
  color: var(--text-disabled) !important;
}
.dark .search-input :deep(.el-input__wrapper):focus-within {
  border-color: var(--primary-500) !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2), 0 4px 12px rgba(99, 102, 241, 0.15) !important;
}
.dark .filter-select :deep(.el-input__wrapper),
.dark .filter-select :deep(.el-select__wrapper) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
}
.dark .filter-select :deep(.el-input__inner),
.dark .filter-select :deep(.el-select__inner),
.dark .filter-select :deep(.el-select__selected-item) {
  color: var(--text-primary) !important;
  font-weight: 500;
}
.dark .filter-select :deep(.el-input__placeholder),
.dark .filter-select :deep(.el-select__placeholder) {
  color: var(--text-light) !important;
}
.dark .filter-select :deep(.el-input__wrapper):focus-within,
.dark .filter-select :deep(.el-select__wrapper):focus-within {
  border-color: var(--primary-500) !important;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2) !important;
}
.dark .filter-select :deep(.el-select-dropdown) {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
}
.dark .filter-select :deep(.el-option) {
  color: var(--text-secondary) !important;
  font-weight: 500;
}
.dark .filter-select :deep(.el-option:hover) {
  background: var(--bg-hover) !important;
}
.dark .filter-select :deep(.el-option.selected) {
  background: var(--primary-500) !important;
  color: #ffffff !important;
}
.dark .filter-select :deep(.el-select__icon),
.dark .filter-select :deep(.el-input__icon) {
  color: var(--text-light) !important;
}
.dark .question-card {
  background: var(--bg-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: var(--shadow-card);
  border: 1px solid var(--glass-border);
}
.dark .question-card:hover {
  border-color: var(--border-glow);
  box-shadow: var(--shadow-glow), var(--shadow-card);
}
.dark .badge-type,
.dark .badge-diff,
.dark .badge-major,
.dark .badge-source {
  background: rgba(255,255,255,0.08) !important;
  color: var(--text-secondary) !important;
  border: 1px solid var(--glass-border);
}
.dark .badge-type.single_choice { 
  background: rgba(59, 130, 246, 0.15) !important; 
  color: #93c5fd !important;
}
.dark .badge-type.multiple_choice { 
  background: rgba(236, 72, 153, 0.15) !important; 
  color: #f9a8d4 !important;
}
.dark .badge-type.fill_blank { 
  background: rgba(251, 191, 36, 0.15) !important; 
  color: #fcd34d !important;
}
.dark .badge-type.true_false { 
  background: rgba(16, 185, 129, 0.15) !important; 
  color: #6ee7b7 !important;
}
.dark .badge-diff.easy { 
  background: rgba(16, 185, 129, 0.15) !important; 
  color: #6ee7b7 !important;
}
.dark .badge-diff.medium { 
  background: rgba(251, 191, 36, 0.15) !important; 
  color: #fcd34d !important;
}
.dark .badge-diff.hard { 
  background: rgba(239, 68, 68, 0.15) !important; 
  color: #fca5a5 !important;
}
.dark .badge-source.manual {
  background: rgba(59, 130, 246, 0.15) !important;
  color: #93c5fd !important;
}
.dark .badge-source.ai {
  background: rgba(168, 85, 247, 0.15) !important;
  color: #c4b5fd !important;
}
.dark .badge-source.past_exam {
  background: rgba(251, 191, 36, 0.15) !important;
  color: #fcd34d !important;
}
.dark .question-content {
  color: var(--text-primary);
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--glass-border);
}
.dark .option-item {
  color: var(--text-secondary);
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--glass-border);
}
.dark .option-item:hover {
  background: rgba(99, 102, 241, 0.15);
  border-color: rgba(99, 102, 241, 0.35);
}
.dark .option-label {
  color: var(--primary-600);
  background: rgba(99, 102, 241, 0.2);
}
.dark .card-footer {
  background: rgba(255,255,255,0.03);
  border-top: 1px solid var(--glass-border);
}
.dark .footer-left {
  color: var(--text-light);
}
.dark .more-icon {
  color: var(--text-light);
  background: rgba(100, 116, 139, 0.15);
  border: 1px solid var(--glass-border);
}
.dark .empty-state h3 {
  color: var(--text-primary);
}
.dark .empty-state p {
  color: var(--text-light);
}
.dark .detail-section h4 {
  color: var(--text-light);
}
.dark .detail-section p {
  color: var(--text-primary);
  background: var(--bg-tertiary);
  border: 1px solid var(--glass-border);
}
.dark .detail-option {
  background: var(--bg-tertiary);
  border: 1px solid var(--glass-border);
}
.dark .question-dialog :deep(.el-dialog) {
  background: var(--bg-card) !important;
}
.dark .question-dialog :deep(.el-dialog__header) {
  border-bottom-color: var(--glass-border);
  background: rgba(0, 0, 0, 0.1);
}
.dark .question-dialog :deep(.el-dialog__title) {
  color: var(--text-primary);
}
.dark .question-dialog :deep(.el-form-item__label) {
  color: var(--text-light);
}
.dark .question-dialog :deep(.el-input__wrapper) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
}
.dark .question-dialog :deep(.el-input__inner) {
  color: var(--text-primary) !important;
  font-weight: 500;
}
.dark .question-dialog :deep(.el-textarea__inner) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
  color: var(--text-primary) !important;
}
.dark .media-toolbar {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.2);
}
.dark .media-btn {
  color: var(--primary-600);
}
.dark .media-btn:hover {
  color: var(--primary-700);
  background: rgba(99, 102, 241, 0.18);
}
.dark .preview-item {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
}
.dark .preview-filename {
  color: var(--text-light);
}
.dark .question-dialog :deep(.el-select) {
  background: var(--bg-input) !important;
}
.dark .question-dialog :deep(.el-input__wrapper),
.dark .question-dialog :deep(.el-select__wrapper) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
}
.dark .question-dialog :deep(.el-input__inner),
.dark .question-dialog :deep(.el-select__inner),
.dark .question-dialog :deep(.el-select__selected-item) {
  color: var(--text-primary) !important;
  font-weight: 500;
}
.dark .question-dialog :deep(.el-input__placeholder),
.dark .question-dialog :deep(.el-select__placeholder) {
  color: var(--text-light) !important;
}
.dark .question-dialog :deep(.el-select__icon),
.dark .question-dialog :deep(.el-input__icon) {
  color: var(--text-light) !important;
}
.dark .question-dialog :deep(.el-select-dropdown) {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
}
.dark .question-dialog :deep(.el-option) {
  color: var(--text-secondary) !important;
  font-weight: 500;
}
.dark .question-dialog :deep(.el-option:hover) {
  background: var(--bg-hover) !important;
}
.dark .question-dialog :deep(.el-option.selected) {
  background: var(--primary-500) !important;
  color: #ffffff !important;
}
.dark .question-dialog :deep(.el-button) {
  background: var(--bg-tertiary) !important;
  border-color: var(--border-color) !important;
  color: var(--text-secondary) !important;
}
.dark .question-dialog :deep(.el-button--primary) {
  background: var(--gradient-primary) !important;
  border-color: transparent !important;
}
.dark .question-dialog :deep(.el-button--danger) {
  background: rgba(239, 68, 68, 0.15) !important;
  border-color: rgba(239, 68, 68, 0.3) !important;
  color: #ef4444 !important;
}
.dark .question-dialog :deep(.el-button--text) {
  background: transparent !important;
  border-color: transparent !important;
  color: #818cf8 !important;
}
.dark .true-false-label {
  background: #334155;
  border: 1px solid rgba(255,255,255,0.08);
}
.dark .true-false-label:hover {
  background: #475569;
}
.dark .true-option, .dark .false-option {
  color: #94a3b8;
}
.dark .true-false-label input[type="radio"]:checked + .true-option {
  color: #10b981;
  background: rgba(16, 185, 129, 0.15);
}
.dark .true-false-label input[type="radio"]:checked + .false-option {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.15);
}
.dark .option-letter {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
}
.dark .options-editor :deep(.el-input__wrapper) {
  background: #334155 !important;
  border-color: rgba(255,255,255,0.1) !important;
}
.dark .options-editor :deep(.el-input__inner) {
  color: #f1f5f9 !important;
}
.dark .options-editor :deep(.el-input__placeholder) {
  color: #64748b !important;
}

.dark .detail-section p {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}

.dark .detail-option {
  background: var(--bg-tertiary);
}

.dark .opt-label {
  color: #818cf8;
}

.dark .preview-item {
  background: var(--bg-tertiary);
  border-color: var(--border-color);
}

.dark .preview-image {
  border-color: var(--border-color);
}

.dark .preview-filename {
  color: var(--text-light);
}

.dark .media-toolbar {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.2);
}

.dark .media-btn {
  color: #818cf8;
}

.dark .media-btn:hover {
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.15);
}

/* 导入功能样式 */
.action-buttons {
  display: flex;
  gap: 12px;
}

.import-btn {
  border-radius: 16px;
  padding: 0 24px;
  height: 44px;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border: none;
  font-weight: 600;
  font-size: 14px;
  box-shadow: 0 4px 15px rgba(16, 185, 129, 0.35);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.import-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 25px rgba(16, 185, 129, 0.45);
}

.import-content {
  padding: 8px 0;
}

.import-hint {
  background: rgba(245, 158, 11, 0.08);
  border-left: 4px solid #f59e0b;
  padding: 16px;
  border-radius: 0 12px 12px 0;
}

.import-hint code {
  background: rgba(0, 0, 0, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  color: #667eea;
}

.import-hint ul {
  margin: 0;
  padding-left: 20px;
}

.import-hint li {
  font-size: 13px;
  color: #64748b;
  margin-bottom: 6px;
}

.custom-file-upload {
  margin-top: 8px;
}

.custom-file-upload input[type="file"] {
  display: none;
}

.upload-label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  border: 2px dashed #cbd5e1;
  border-radius: 16px;
  cursor: pointer;
  transition: all 0.3s;
  background: #fafbfc;
  font-size: 14px;
  color: #64748b;
}

.upload-label:hover {
  border-color: #667eea;
  background: rgba(102, 126, 234, 0.04);
}

.upload-label i {
  font-size: 24px;
  color: #667eea;
}

.template-links {
  display: flex;
  gap: 16px;
  justify-content: center;
}

.template-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #667eea;
  font-size: 13px;
  font-weight: 500;
  padding: 8px 14px;
  border-radius: 10px;
  transition: all 0.2s;
}

.template-btn:hover {
  color: #764ba2;
  background: rgba(102, 126, 234, 0.08);
}

.import-dialog :deep(.el-dialog__header) {
  padding: 20px 24px;
  border-bottom: 1px solid #f1f5f9;
}

.import-dialog :deep(.el-dialog__body) {
  padding: 24px;
}

/* 暗色模式 - 导入功能 */
.dark .import-hint {
  background: rgba(245, 158, 11, 0.1);
  border-left-color: #fbbf24;
}

.dark .import-hint code {
  background: rgba(255, 255, 255, 0.1);
  color: #a5b4fc;
}

.dark .import-hint li {
  color: #94a3b8;
}

.dark .upload-label {
  border-color: #475569;
  background: #334155;
  color: #cbd5e1;
}

.dark .upload-label:hover {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.1);
}

.dark .upload-label i {
  color: #a5b4fc;
}

.dark .template-btn {
  color: #a5b4fc;
}

.dark .template-btn:hover {
  color: #c7d2fe;
  background: rgba(99, 102, 241, 0.15);
}

.dark .import-dialog :deep(.el-dialog) {
  background: var(--bg-card) !important;
}

.dark .import-dialog :deep(.el-dialog__header) {
  border-bottom-color: var(--glass-border);
  background: rgba(0, 0, 0, 0.1);
}

.dark .import-dialog :deep(.el-dialog__title) {
  color: var(--text-primary);
}

@media (max-width: 768px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .question-grid {
    grid-template-columns: 1fr;
  }
  .filter-left {
    flex-wrap: wrap;
  }
}

.editor-textarea-wrapper {
  position: relative;
}

.editor-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px 10px 0 0;
  margin-bottom: -1px;
}

.editor-toolbar .toolbar-group {
  display: flex;
  align-items: center;
  gap: 2px;
  padding-right: 10px;
  border-right: 1px solid #e2e8f0;
  margin-right: 4px;
}

.editor-toolbar .toolbar-group:last-child {
  border-right: none;
  padding-right: 0;
  margin-right: 0;
}

.editor-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: #475569;
  transition: all 0.2s;
}

.editor-btn:hover {
  background: rgba(102, 126, 234, 0.1);
  color: #667eea;
}

.editor-btn:active {
  background: rgba(102, 126, 234, 0.2);
}

.editor-btn.math-btn {
  font-size: 14px;
  font-weight: 500;
}

.editor-btn :deep(.svg-inline--fa) {
  font-size: 14px;
}

.analysis-toolbar {
  padding: 8px 12px;
}

.editor-textarea-wrapper :deep(.el-textarea__inner) {
  border-radius: 0 0 10px 10px;
  border-top-left-radius: 0;
  border-top-right-radius: 0;
  resize: vertical;
}

.dark .editor-toolbar {
  background: #334155;
  border-color: #475569;
}

.dark .editor-btn {
  color: #cbd5e1;
}

.dark .editor-btn:hover {
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
}

.dark .editor-toolbar .toolbar-group {
  border-right-color: #475569;
}

.dark .editor-textarea-wrapper :deep(.el-textarea__inner) {
  background: var(--bg-input) !important;
  border-color: var(--border-color) !important;
  color: var(--text-primary) !important;
}
</style>