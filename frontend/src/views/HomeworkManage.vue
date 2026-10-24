<template>
  <div class="page-wrapper">
    <div class="page-header">
      <div class="header-title">
        <h2><el-icon :size="24" class="title-icon"><Notebook /></el-icon> 作业管理</h2>
      </div>
      <el-button v-if="view === 'hw'" type="primary" :icon="Plus" @click="openCreate">新建作业</el-button>
      <el-button v-else-if="view === 'tpl'" type="primary" :icon="Plus" @click="openTplCreate">新建模板</el-button>
      <el-button v-else type="primary" :icon="Plus" @click="openSeriesCreate">新建系列</el-button>
    </div>

    <el-radio-group v-model="view" style="margin-bottom: 12px">
      <el-radio-button label="hw">作业</el-radio-button>
      <el-radio-button label="tpl">模板</el-radio-button>
      <el-radio-button label="series">系列</el-radio-button>
    </el-radio-group>

    <template v-if="view === 'hw'">
    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane label="草稿" name="draft" />
      <el-tab-pane label="已发布" name="published" />
      <el-tab-pane label="已关闭" name="closed" />
    </el-tabs>

    <el-empty v-if="!items.length" description="还没有作业，点击右上角新建" />
    <el-table v-else :data="items" stripe>
      <el-table-column prop="title" label="标题" min-width="200">
        <template #default="{ row }">
          <router-link :to="`/homeworks/${row.id}/grade`" class="link">{{ row.title }}</router-link>
          <el-tag size="small" effect="plain" style="margin-left: 8px">
            {{ row.hw_type === 'open' ? '开放式' : '题集式' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="提交/名单" width="110" align="center">
        <template #default="{ row }">
          {{ row.stats?.submitted_count ?? 0 }} / {{ row.stats?.student_count ?? 0 }}
        </template>
      </el-table-column>
      <el-table-column label="截止" width="160">
        <template #default="{ row }">
          <span v-if="row.has_deadline" :class="{ overdue: row.is_expired }">{{ (row.deadline || '').slice(0, 16) }}</span>
          <el-tag v-else size="small" type="info" effect="plain">不限期</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)" :disabled="row.status !== 'draft'">编辑</el-button>
          <el-button v-if="row.status === 'draft'" size="small" type="success" @click="doPublish(row)">发布</el-button>
          <el-button v-if="row.status === 'published'" size="small" type="warning" @click="doClose(row)">关闭</el-button>
          <el-dropdown trigger="click" style="margin-left: 8px" @command="(c) => onRowCommand(c, row)">
            <el-button size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="stats">成绩统计</el-dropdown-item>
                <el-dropdown-item command="copy">复制为草稿</el-dropdown-item>
                <el-dropdown-item command="urge" :disabled="row.status !== 'published'">催交未交</el-dropdown-item>
                <el-dropdown-item command="export">导出成绩</el-dropdown-item>
                <el-dropdown-item command="delete" :disabled="row.status !== 'draft'" divided>删除草稿</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>
    </template>

    <!-- 模板 / 系列筛选 -->
    <div v-if="view !== 'hw'" class="list-toolbar">
      <el-input v-model="viewKeyword" placeholder="按名称搜索" clearable :prefix-icon="Search"
                style="width: 240px" />
      <span class="hint">共 {{ view === 'tpl' ? filteredTemplates.length : filteredSeries.length }} 条</span>
    </div>

    <!-- 模板列表 -->
    <template v-else-if="view === 'tpl'">
      <el-skeleton v-if="tplLoading" :rows="5" animated style="padding: 12px" />
      <el-empty v-else-if="!filteredTemplates.length"
                :description="viewKeyword ? '没有匹配的模板' : '还没有模板，点击右上角新建'" />
      <template v-else>
        <el-table :data="pagedTemplates" stripe>
          <el-table-column prop="title" label="模板名称" min-width="160" />
          <el-table-column label="筛选" min-width="160">
            <template #default="{ row }">
              <span class="muted small">{{ tplFilterText(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="题量 / 难度分布" width="220">
            <template #default="{ row }">
              <div class="dist-cell">
                <span>{{ tplTotal(row) }} 题</span>
                <div class="dist-bars">
                  <span v-for="(n, d) in tplDistribution(row)" :key="d" class="dist-seg"
                        :class="'d-' + d" :style="{ flex: n }" :title="`${difficultyLabel(d)} ${n} 题`" />
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="默认分值" width="90" align="center">
            <template #default="{ row }">{{ row.config?.default_score ?? 5 }}</template>
          </el-table-column>
          <el-table-column label="操作" width="280" align="center">
            <template #default="{ row }">
              <el-button size="small" @click="openTplEdit(row)">编辑</el-button>
              <el-button size="small" type="success" :loading="generatingId === row.id"
                         @click="genFromTpl(row)">生成作业</el-button>
              <el-button size="small" type="danger" text @click="delTpl(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination v-if="filteredTemplates.length > pageSize" v-model:current-page="page"
                       :page-size="pageSize" :total="filteredTemplates.length"
                       layout="prev, pager, next" style="margin-top: 12px; justify-content: flex-end" />
      </template>
    </template>

    <!-- 系列列表 -->
    <template v-else>
      <el-skeleton v-if="seriesLoading" :rows="4" animated style="padding: 12px" />
      <el-empty v-else-if="!filteredSeries.length"
                :description="viewKeyword ? '没有匹配的系列' : '还没有系列，点击右上角新建'" />
      <template v-else>
        <el-table :data="pagedSeries" stripe>
          <el-table-column prop="title" label="系列名称" min-width="160" />
          <el-table-column label="进度" width="150" align="center">
            <template #default="{ row }">
              <el-progress :percentage="Math.round(row.generated_count / row.count * 100)"
                           :stroke-width="8" />
              <span class="muted small">{{ row.generated_count }} / {{ row.count }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="seriesStatusTag(row.status)">{{ seriesStatusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="首次发布" width="150">
            <template #default="{ row }">{{ (row.start_at || '').slice(0, 16) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="330" align="center">
            <template #default="{ row }">
              <el-button size="small" @click="openTimeline(row)">时间轴</el-button>
              <el-button size="small" type="success" :disabled="row.status === 'active' || row.status === 'completed'" @click="startSeries(row)">启动</el-button>
              <el-button size="small" :disabled="row.generated_count >= row.count" @click="genNow(row)">立即生成下一份</el-button>
              <el-button size="small" type="danger" text @click="delSeries(row)">停止</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination v-if="filteredSeries.length > pageSize" v-model:current-page="page"
                       :page-size="pageSize" :total="filteredSeries.length"
                       layout="prev, pager, next" style="margin-top: 12px; justify-content: flex-end" />
      </template>
    </template>

    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="dialog" :title="form.id ? '编辑作业' : '新建作业'" width="760px" top="6vh">
      <el-form :model="form" label-width="96px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" placeholder="作业标题" />
        </el-form-item>
        <el-form-item label="形态">
          <el-radio-group v-model="form.hw_type" :disabled="!!form.id">
            <el-radio-button value="question_set">题集式</el-radio-button>
            <el-radio-button value="open">开放式</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="所属课程">
          <el-select v-model="form.course_id" clearable filterable placeholder="不关联（仅成绩册需要）" style="width: 240px">
            <el-option v-for="cs in courses" :key="cs.id" :label="cs.name" :value="cs.id" />
          </el-select>
          <span class="hint">挂课后该作业会计入课程成绩册的加权总评</span>
        </el-form-item>
        <el-form-item label="作业模式">
          <el-switch v-model="form.is_group" active-text="小组作业" inactive-text="个人作业" />
          <span class="hint">小组作业：组内共用一份提交，一人提交全组得分</span>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="作业说明（开放式必填）" />
        </el-form-item>
        <el-form-item label="截止时间">
          <el-switch v-model="form.has_deadline" active-text="设置截止时间" />
          <el-date-picker v-if="form.has_deadline" v-model="form.deadline" type="datetime"
                          value-format="YYYY-MM-DDTHH:mm:ss" placeholder="选择截止日期时间"
                          style="margin-left: 12px" />
          <span v-else class="hint">未设截止：作业长期有效，学生随时可交</span>
        </el-form-item>
        <el-form-item v-if="form.has_deadline" label="提前提醒">
          <el-input-number v-model="form.remind_before" :min="0" :max="10080" :step="60" />
          <span class="hint">分钟（0=不提醒，截止前 N 分钟提醒未交学生）</span>
        </el-form-item>
        <el-form-item label="及格线">
          <el-input-number v-model="form.pass_score" :min="0" :max="1000" :step="5" :precision="1"
                           :value-on-clear="null" controls-position="right" style="width: 160px" placeholder="留空不设" />
          <span class="hint">用于统计及格率/优秀率（优秀=满分90%），留空则不设</span>
        </el-form-item>
        <el-form-item label="评分制">
          <el-select v-model="form.grade_mode" size="small" style="width: 160px">
            <el-option label="分数制" value="numeric" />
            <el-option label="等级制" value="level" />
            <el-option label="评语制" value="comment" />
          </el-select>
          <span class="hint">仅影响成绩展示（不改判分）；等级阈值自定义请前往「评分制」页</span>
        </el-form-item>
        <el-form-item label="关联量规">
          <el-select v-model="form.rubric_id" clearable size="small" style="width: 220px"
                     placeholder="不关联（可选）">
            <el-option v-for="r in rubrics" :key="r.id" :label="r.title" :value="r.id" />
          </el-select>
          <span class="hint">批改时按量规维度拆解建议分（仅辅助，不改官方总分）；量规请前往「评分量规」页新建</span>
        </el-form-item>
        <el-form-item label="规则">
          <el-checkbox v-model="form.allow_late" :disabled="!form.has_deadline">允许迟交</el-checkbox>
          <el-checkbox v-model="form.allow_resubmit">允许重交</el-checkbox>
        </el-form-item>
        <el-form-item v-if="form.has_deadline" label="迟交扣分">
          <el-input-number v-model="form.late_penalty_pct" :min="0" :max="100" :step="5" />
          <span class="hint">%（0=不扣，允许迟交时按此比例从总分扣分）</span>
        </el-form-item>
        <el-form-item v-if="form.has_deadline" label="分级提醒">
          <div>
            <div v-for="(lv, i) in form.remind_levels" :key="i" style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <el-select v-model="lv.minutes" style="width: 140px">
                <el-option :value="4320" label="3 天前" />
                <el-option :value="1440" label="1 天前" />
                <el-option :value="720" label="12 小时前" />
                <el-option :value="60" label="1 小时前" />
                <el-option :value="30" label="30 分钟前" />
              </el-select>
              <el-button size="small" text type="danger" @click="form.remind_levels.splice(i, 1)">删除</el-button>
            </div>
            <el-button size="small" @click="addRemindLevel">+ 添加提醒档</el-button>
            <span class="hint">设了多档则优先于上方“提前提醒”单档；未交学生每档各提醒一次</span>
          </div>
        </el-form-item>
        <el-form-item label="批改与防抄">
          <el-checkbox v-model="form.blind_grading">匿名批改</el-checkbox>
          <el-checkbox v-model="form.shuffle_questions" :disabled="form.hw_type !== 'question_set'">题目乱序</el-checkbox>
          <el-checkbox v-model="form.shuffle_options" :disabled="form.hw_type !== 'question_set'">选项乱序</el-checkbox>
          <el-checkbox v-model="form.enable_monitor">防作弊监测</el-checkbox>
          <el-checkbox v-model="form.allow_revision">允许订正重做</el-checkbox>
          <span class="hint">匿名=批完前隐藏学生身份；乱序=每生题序/选项随机，判分自动还原；监测=采集切屏/粘贴等异常事件（只记不拦）；订正=批后可将已批提交退回学生重做</span>
        </el-form-item>
        <el-form-item label="参考资料">
          <div v-if="form.reference" class="ref-row">
            <el-link type="primary" @click="downloadRef">{{ form.reference.filename }}</el-link>
            <el-button size="small" text type="danger" @click="removeRef">删除</el-button>
          </div>
          <div v-else-if="!form.id" class="hint">保存草稿后，可在“编辑”中上传供学生下载的参考资料</div>
          <el-upload v-else :show-file-list="false" :http-request="uploadRef" action="#">
            <el-button size="small" :icon="Upload">上传参考资料</el-button>
            <span class="hint">学生作答页可下载查看</span>
          </el-upload>
        </el-form-item>

        <el-form-item v-if="form.hw_type === 'question_set'" label="题目">
          <div class="picker">
            <div class="picker-head">
              <div class="picker-tools">
                <el-select v-model="pickMajor" filterable placeholder="按专业筛选题库" clearable
                           style="width: 180px" @change="loadQuestions">
                  <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
                </el-select>
                <el-select v-model="randDifficulty" placeholder="难度" clearable size="small" style="width: 96px">
                  <el-option v-for="d in DIFFICULTY_OPTIONS" :key="d.value" :label="d.label" :value="d.value" />
                </el-select>
                <el-input-number v-model="randCount" :min="1" :max="50" size="small" controls-position="right" style="width: 92px" />
                <el-button size="small" :icon="MagicStick" @click="randomPick">随机抽题</el-button>
              </div>
              <span class="hint">已选 {{ form.questions.length }} 题，总分 {{ totalScore }}</span>
            </div>
            <el-table :data="questionPool" height="220" size="small" @select="onPick" @select-all="onPickAll">
              <el-table-column type="selection" width="46" :selectable="() => true" />
              <el-table-column prop="content" label="题干" min-width="220" show-overflow-tooltip />
              <el-table-column prop="type" label="类型" width="100" />
            </el-table>
            <div v-if="form.questions.length" class="chosen">
              <div v-for="(q, i) in form.questions" :key="q.question_id" class="chosen-row">
                <span class="idx">{{ i + 1 }}</span>
                <span class="ct" :title="q.content">{{ q.content }}</span>
                <el-input-number v-model="q.score" :min="0.5" :max="100" size="small" controls-position="right" />
                <el-button size="small" text type="danger" :icon="Delete" @click="removeQ(i)" />
              </div>
            </div>
          </div>
        </el-form-item>

        <el-form-item v-if="!form.is_group" label="发布名单">
          <el-select v-model="form.student_ids" multiple filterable placeholder="选择学生" style="width: 100%">
            <el-option v-for="s in students" :key="s.id" :label="s.username" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="小组名单">
          <div class="group-builder">
            <div v-for="(g, gi) in form.groups" :key="gi" class="group-row">
              <el-input v-model="g.name" placeholder="小组名称" style="width: 140px" />
              <el-select v-model="g.student_ids" multiple filterable placeholder="选择组员" style="flex:1">
                <el-option v-for="s in students" :key="s.id" :label="s.username" :value="s.id" />
              </el-select>
              <el-button size="small" text type="danger" :icon="Delete" @click="form.groups.splice(gi, 1)" />
            </div>
            <el-button size="small" :icon="Plus" @click="form.groups.push({ name: '', student_ids: [] })">添加小组</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存草稿</el-button>
      </template>
    </el-dialog>

    <!-- 成绩统计对话框 -->
    <el-dialog v-model="statsDialog" :title="`成绩统计 - ${statsHomework}`" width="560px">
      <el-descriptions :column="2" border v-loading="statsLoading">
        <el-descriptions-item label="发布名单">{{ stats.student_count ?? 0 }} 人</el-descriptions-item>
        <el-descriptions-item label="已提交">{{ stats.submitted_count ?? 0 }} 人（{{ stats.submitted_rate ?? 0 }}%）</el-descriptions-item>
        <el-descriptions-item label="已批改">{{ stats.graded_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="待批改">{{ stats.pending_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="平均分">{{ stats.avg_score ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="满分">{{ stats.full_score ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="最高分">{{ stats.max_score_value ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="最低分">{{ stats.min_score_value ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="及格率">{{ stats.pass_rate != null ? stats.pass_rate + '%' : '未设及格线' }}</el-descriptions-item>
        <el-descriptions-item label="优秀率">{{ stats.excellent_rate != null ? stats.excellent_rate + '%' : '—' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="statsDialog = false">关闭</el-button>
        <el-button type="primary" :icon="Download" @click="doExportStats">导出成绩</el-button>
      </template>
    </el-dialog>

    <!-- 模板对话框 -->
    <el-dialog v-model="tplDialog" :title="tplForm.id ? '编辑模板' : '新建模板'" width="680px" top="6vh">
      <el-form :model="tplForm" label-width="100px">
        <el-form-item label="模板名称" required>
          <el-input v-model="tplForm.title" maxlength="200" placeholder="如：高数周练" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="tplForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="专业" required>
          <el-select v-model="tplForm.major_id" filterable placeholder="必选，决定题库范围"
                     @change="onTplMajorChange" style="width: 100%">
            <el-option v-for="m in majors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="课程 / 章节">
          <div class="cascade-row">
            <el-select v-model="tplForm.course_id" clearable filterable placeholder="全部课程"
                       :disabled="!tplForm.major_id" @change="onTplCourseChange">
              <el-option v-for="c in tplCourses" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
            <el-select v-model="tplForm.chapter_id" clearable filterable placeholder="全部章节"
                       :disabled="!tplForm.course_id">
              <el-option v-for="c in tplChapters" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </div>
          <span class="hint">按专业 → 课程 → 章节逐级缩小抽题范围</span>
        </el-form-item>
        <el-form-item label="题型">
          <el-select v-model="tplForm.types" multiple collapse-tags placeholder="不选=全部">
            <el-option label="单选" value="single_choice" /><el-option label="多选" value="multiple_choice" />
            <el-option label="判断" value="true_false" /><el-option label="填空" value="fill_blank" />
            <el-option label="简答" value="short_answer" /><el-option label="编程" value="programming" />
          </el-select>
        </el-form-item>
        <el-form-item label="难度">
          <el-select v-model="tplForm.difficulty" clearable placeholder="不选=全部"
                     :disabled="tplForm.useDistribution">
            <el-option v-for="d in DIFFICULTY_OPTIONS" :key="d.value" :label="d.label" :value="d.value" />
          </el-select>
          <span class="hint">启用下方难度分布后，此单项难度不生效</span>
        </el-form-item>
        <el-form-item label="难度分布">
          <el-switch v-model="tplForm.useDistribution" active-text="按分布抽题" />
        </el-form-item>
        <el-form-item v-if="tplForm.useDistribution" label="各难度题数">
          <div class="dist-editor">
            <div v-for="d in DIFFICULTY_OPTIONS" :key="d.value" class="dist-row">
              <span class="dist-name">{{ d.label }}</span>
              <el-input-number v-model="tplForm.distribution[d.value]" :min="0" :max="50" size="small"
                               controls-position="right" />
              <div class="dist-preview">
                <div class="dist-seg" :class="'d-' + d.value"
                     :style="{ width: distPercent(d.value) + '%' }" />
              </div>
            </div>
            <div class="hint">合计 {{ distributionTotal }} 题
              <span v-if="!distributionTotal" class="error-text">· 请至少给一个难度分配题数</span>
            </div>
          </div>
        </el-form-item>
        <el-form-item v-else label="题量" required>
          <el-input-number v-model="tplForm.count" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="默认分值">
          <el-input-number v-model="tplForm.default_score" :min="1" :max="100" />
        </el-form-item>
        <el-form-item label="发布名单">
          <el-select v-model="tplForm.roster" multiple filterable placeholder="选择学生">
            <el-option v-for="s in students" :key="s.id" :label="s.username" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="截止(小时)">
          <el-input-number v-model="tplForm.deadline_hours" :min="0" placeholder="0=不设" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :loading="previewLoading" :disabled="!tplForm.major_id"
                   @click="previewTpl">预览抽题</el-button>
        <el-button @click="tplDialog = false">取消</el-button>
        <el-button type="primary" :loading="tplSaving" @click="saveTpl">保存</el-button>
      </template>
    </el-dialog>

    <!-- 抽题预览 -->
    <el-dialog v-model="previewDialog" title="抽题预览（不落库）" width="720px" top="8vh">
      <el-skeleton v-if="previewLoading" :rows="5" animated />
      <template v-else-if="previewResult">
        <div class="preview-stats">
          <el-tag effect="plain">题库可用 {{ previewResult.pool_total }} 题</el-tag>
          <el-tag type="success" effect="plain">本次抽中 {{ previewResult.picked_total }} 题</el-tag>
          <el-tag v-for="(n, d) in previewResult.available" :key="d" size="small" effect="plain">
            {{ difficultyLabel(d) }}池 {{ n }}
          </el-tag>
        </div>
        <div class="dist-bars preview-bars">
          <span v-for="(n, d) in previewResult.picked_counts" :key="d" class="dist-seg"
                :class="'d-' + d" :style="{ flex: n }"
                :title="`${difficultyLabel(d)} ${n} 题`" />
        </div>
        <el-table :data="previewResult.questions" size="small" max-height="360" stripe>
          <el-table-column type="index" width="50" />
          <el-table-column prop="content" label="题干" min-width="260" show-overflow-tooltip />
          <el-table-column label="难度" width="80">
            <template #default="{ row }">{{ difficultyLabel(row.difficulty) }}</template>
          </el-table-column>
          <el-table-column prop="score" label="分值" width="70" />
        </el-table>
      </template>
      <el-empty v-else description="点击「预览抽题」查看命中题目" />
      <template #footer>
        <el-button @click="previewDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 系列对话框 -->
    <el-dialog v-model="seriesDialog" title="新建作业系列" width="520px" top="10vh">
      <el-form :model="seriesForm" label-width="100px">
        <el-form-item label="选择模板" required>
          <el-select v-model="seriesForm.template_id" filterable placeholder="从已有模板选择">
            <el-option v-for="t in templates" :key="t.id" :label="t.title" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="系列名称">
          <el-input v-model="seriesForm.title" maxlength="200" />
        </el-form-item>
        <el-form-item label="首次发布" required>
          <el-date-picker v-model="seriesForm.start_at" type="datetime" placeholder="首次发布时间" style="width:100%" />
        </el-form-item>
        <el-form-item label="份数">
          <el-input-number v-model="seriesForm.count" :min="1" :max="30" />
        </el-form-item>
        <el-form-item label="间隔(小时)">
          <el-input-number v-model="seriesForm.interval_hours" :min="1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="seriesDialog = false">取消</el-button>
        <el-button type="primary" :loading="seriesSaving" @click="saveSeries">创建</el-button>
      </template>
    </el-dialog>

    <!-- 系列时间轴 -->
    <el-dialog v-model="timelineDialog" :title="`系列时间轴：${timeline?.title || ''}`"
               width="620px" top="8vh">
      <el-skeleton v-if="timelineLoading" :rows="5" animated />
      <template v-else-if="timeline">
        <div class="timeline-summary">
          <span>模板：{{ timeline.template_title || '—' }}</span>
          <span>共 {{ timeline.count }} 份 · 每 {{ timeline.interval_hours }} 小时一份</span>
        </div>
        <el-timeline>
          <el-timeline-item v-for="p in timelinePoints" :key="p.index"
                            :timestamp="p.planned" placement="top"
                            :type="p.generated ? 'success' : (p.overdue ? 'warning' : 'info')">
            <div class="tl-title">
              第 {{ p.index + 1 }} 份
              <el-tag v-if="p.generated" size="small" type="success">已生成</el-tag>
              <el-tag v-else-if="p.overdue" size="small" type="warning">已到期待生成</el-tag>
              <el-tag v-else size="small" type="info">计划中</el-tag>
            </div>
            <div class="muted small" v-if="p.generated">
              {{ p.generated.title }} · {{ p.generated.status }}
            </div>
          </el-timeline-item>
        </el-timeline>
      </template>
      <el-empty v-else description="暂无时间轴数据" />
      <template #footer>
        <el-button @click="timelineDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { Notebook, Plus, Delete, ArrowDown, Upload, MagicStick, Download, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import request from '../utils/request'
import { DIFFICULTY_OPTIONS, difficultyLabel } from '../utils/enums'

const tab = ref('all')
const items = ref([])
const dialog = ref(false)
const saving = ref(false)
const majors = ref([])
const students = ref([])
const rubrics = ref([])
const courses = ref([])
const questionPool = ref([])
const pickMajor = ref(null)
const randDifficulty = ref('')
const randCount = ref(5)
const statsDialog = ref(false)
const statsLoading = ref(false)
const stats = ref({})
const statsHomework = ref('')
const statsId = ref(null)

// v5.8 模板与系列
const view = ref('hw')
const templates = ref([])
const seriesList = ref([])
const tplDialog = ref(false)
const tplSaving = ref(false)
const tplLoading = ref(false)
const generatingId = ref(null)
const tplCourses = ref([])
const tplChapters = ref([])
const tplForm = reactive({
  id: null, title: '', description: '', major_id: null, course_id: null, chapter_id: null,
  types: [], difficulty: '', useDistribution: false,
  distribution: { easy: 0, medium: 0, hard: 0 },
  count: 5, default_score: 5, roster: [], deadline_hours: 0
})
const previewDialog = ref(false)
const previewLoading = ref(false)
const previewResult = ref(null)
const seriesLoading = ref(false)
const viewKeyword = ref('')
const page = ref(1)
const pageSize = 8
const timelineDialog = ref(false)
const timelineLoading = ref(false)
const timeline = ref(null)
const seriesDialog = ref(false)
const seriesSaving = ref(false)
const seriesForm = reactive({ template_id: null, title: '', start_at: null, count: 5, interval_hours: 24 })

const seriesStatusText = (s) => ({ draft: '草稿', active: '进行中', completed: '已完成', paused: '已暂停' }[s] || s)
const seriesStatusTag = (s) => ({ draft: 'info', active: 'success', completed: '', paused: 'warning' }[s] || 'info')

const filteredTemplates = computed(() => {
  const kw = viewKeyword.value.trim()
  return kw ? templates.value.filter(t => (t.title || '').includes(kw)) : templates.value
})
const filteredSeries = computed(() => {
  const kw = viewKeyword.value.trim()
  return kw ? seriesList.value.filter(s => (s.title || '').includes(kw)) : seriesList.value
})
const pagedTemplates = computed(() =>
  filteredTemplates.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const pagedSeries = computed(() =>
  filteredSeries.value.slice((page.value - 1) * pageSize, page.value * pageSize))

const distributionTotal = computed(() =>
  Object.values(tplForm.distribution).reduce((s, n) => s + (Number(n) || 0), 0))
const distPercent = (d) => {
  const total = distributionTotal.value
  return total ? Math.round((Number(tplForm.distribution[d]) || 0) / total * 100) : 0
}

const tplDistribution = (row) => {
  const c = row.config || {}
  if (Array.isArray(c.distribution) && c.distribution.length) {
    const out = {}
    c.distribution.forEach(s => { out[s.difficulty] = (out[s.difficulty] || 0) + (s.count || 0) })
    return out
  }
  const f = c.filters || {}
  if (f.difficulty) return { [f.difficulty]: c.count || 0 }
  return { easy: 1, medium: 1, hard: 1 }
}
const tplTotal = (row) => {
  const dist = tplDistribution(row)
  const sum = Object.values(dist).reduce((s, n) => s + n, 0)
  return (row.config || {}).count || sum
}
const tplFilterText = (row) => {
  const f = (row.config || {}).filters || {}
  const major = majors.value.find(m => m.id === f.major_id)
  return [major?.name || '全部专业',
    f.course_id ? `课程#${f.course_id}` : '',
    f.chapter_id ? `章节#${f.chapter_id}` : '',
    (f.types || []).length ? `${f.types.length} 种题型` : ''].filter(Boolean).join(' / ')
}

const loadTemplates = async () => {
  tplLoading.value = true
  try {
    const res = await request.get('/api/homeworks/templates')
    templates.value = res.data.items || []
    if (page.value > Math.max(1, Math.ceil(filteredTemplates.value.length / pageSize))) page.value = 1
  } finally {
    tplLoading.value = false
  }
}
const loadSeries = async () => {
  seriesLoading.value = true
  try {
    const res = await request.get('/api/homeworks/series')
    seriesList.value = res.data.items || []
  } finally {
    seriesLoading.value = false
  }
}

const loadTplCourses = async (majorId) => {
  tplCourses.value = []
  tplChapters.value = []
  if (!majorId) return
  const res = await request.get('/api/courses', { params: { major_id: majorId } })
  tplCourses.value = Array.isArray(res.data) ? res.data : (res.data.items || [])
}
const loadTplChapters = async (courseId) => {
  tplChapters.value = []
  if (!courseId) return
  const res = await request.get('/api/chapters', { params: { course_id: courseId } })
  tplChapters.value = Array.isArray(res.data) ? res.data : (res.data.items || [])
}
const onTplMajorChange = (majorId) => {
  tplForm.course_id = null
  tplForm.chapter_id = null
  loadTplCourses(majorId)
}
const onTplCourseChange = (courseId) => {
  tplForm.chapter_id = null
  loadTplChapters(courseId)
}

const resetTplForm = () => Object.assign(tplForm, {
  id: null, title: '', description: '', major_id: null, course_id: null, chapter_id: null,
  types: [], difficulty: '', useDistribution: false,
  distribution: { easy: 0, medium: 0, hard: 0 },
  count: 5, default_score: 5, roster: [], deadline_hours: 0
})
const openTplCreate = () => {
  resetTplForm()
  tplCourses.value = []
  tplChapters.value = []
  tplDialog.value = true
}
const openTplEdit = async (row) => {
  const c = row.config || {}
  const f = c.filters || {}
  const dist = { easy: 0, medium: 0, hard: 0 }
  ;(c.distribution || []).forEach(s => {
    if (s.difficulty in dist) dist[s.difficulty] = s.count || 0
  })
  Object.assign(tplForm, {
    id: row.id, title: row.title, description: row.description || '',
    major_id: f.major_id || null, course_id: f.course_id || null,
    chapter_id: f.chapter_id || null,
    types: f.types || [], difficulty: f.difficulty || '',
    useDistribution: Array.isArray(c.distribution) && c.distribution.length > 0,
    distribution: dist,
    count: c.count || 5, default_score: c.default_score || 5,
    roster: row.roster || [], deadline_hours: (row.settings || {}).deadline_hours || 0
  })
  tplDialog.value = true
  await Promise.all([
    loadTplCourses(tplForm.major_id),
    tplForm.course_id ? loadTplChapters(tplForm.course_id) : Promise.resolve()
  ])
}

const buildTplConfig = () => {
  const filters = { major_id: tplForm.major_id }
  if (tplForm.course_id) filters.course_id = tplForm.course_id
  if (tplForm.chapter_id) filters.chapter_id = tplForm.chapter_id
  if (tplForm.types.length) filters.types = tplForm.types
  if (tplForm.difficulty) filters.difficulty = tplForm.difficulty
  const config = { filters, default_score: tplForm.default_score }
  if (tplForm.useDistribution) {
    config.distribution = DIFFICULTY_OPTIONS
      .map(d => ({ difficulty: d.value, count: Number(tplForm.distribution[d.value]) || 0 }))
      .filter(s => s.count > 0)
    config.count = distributionTotal.value
  } else {
    config.count = tplForm.count
  }
  return config
}

const previewTpl = async () => {
  if (!tplForm.major_id) return ElMessage.warning('请先选择专业')
  if (tplForm.useDistribution && !distributionTotal.value) {
    return ElMessage.warning('请至少给一个难度分配题数')
  }
  previewLoading.value = true
  previewDialog.value = true
  try {
    const res = await request.post('/api/homeworks/templates/preview',
      { config: buildTplConfig() })
    previewResult.value = res.data
    if (!res.data.pool_total) ElMessage.warning(res.data.message || '没有匹配题目')
  } catch (e) {
    previewResult.value = null
  } finally {
    previewLoading.value = false
  }
}

const saveTpl = async () => {
  if (!tplForm.title.trim()) return ElMessage.warning('请填写模板名称')
  if (!tplForm.major_id) return ElMessage.warning('请选择专业')
  if (tplForm.useDistribution && !distributionTotal.value) {
    return ElMessage.warning('请至少给一个难度分配题数')
  }
  tplSaving.value = true
  try {
    const payload = {
      title: tplForm.title, description: tplForm.description,
      config: buildTplConfig(),
      settings: { deadline_hours: tplForm.deadline_hours || null },
      roster: tplForm.roster
    }
    if (tplForm.id) {
      await request.put(`/api/homeworks/templates/${tplForm.id}`, payload)
      ElMessage.success('已更新')
    } else {
      await request.post('/api/homeworks/templates', payload)
      ElMessage.success('已创建')
    }
    tplDialog.value = false
    loadTemplates()
  } finally { tplSaving.value = false }
}
const genFromTpl = async (row) => {
  generatingId.value = row.id
  try {
    const res = await request.post(`/api/homeworks/templates/${row.id}/generate`)
    ElMessage.success(res.data.message || '已生成作业草稿')
  } finally {
    generatingId.value = null
  }
}
const delTpl = async (row) => {
  const ok = await ElMessageBox.confirm(`删除模板「${row.title}」？`, '确认', {
    type: 'warning', confirmButtonText: '删除'
  }).catch(() => false)
  if (!ok) return
  await request.delete(`/api/homeworks/templates/${row.id}`)
  ElMessage.success('已删除')
  loadTemplates()
}
const openSeriesCreate = () => {
  Object.assign(seriesForm, { template_id: null, title: '', start_at: null, count: 5, interval_hours: 24 })
  seriesDialog.value = true
}
const saveSeries = async () => {
  if (!seriesForm.template_id) return ElMessage.warning('请选择模板')
  if (!seriesForm.start_at) return ElMessage.warning('请指定首次发布时间')
  seriesSaving.value = true
  try {
    await request.post('/api/homeworks/series', {
      template_id: seriesForm.template_id, title: seriesForm.title,
      start_at: seriesForm.start_at instanceof Date ? seriesForm.start_at.toISOString() : seriesForm.start_at,
      count: seriesForm.count, interval_hours: seriesForm.interval_hours
    })
    ElMessage.success('系列已创建，启动后到达时间自动生成')
    seriesDialog.value = false
    loadSeries()
  } finally { seriesSaving.value = false }
}
const startSeries = async (row) => {
  await request.post(`/api/homeworks/series/${row.id}/start`)
  ElMessage.success('已启动')
  loadSeries()
}
const genNow = async (row) => {
  const res = await request.post(`/api/homeworks/series/${row.id}/generate_now`)
  ElMessage.success(res.data.message || '已生成')
  loadSeries()
}
const delSeries = async (row) => {
  const ok = await ElMessageBox.confirm(`停止系列「${row.title}」？已生成的作业保留。`, '确认', {
    type: 'warning', confirmButtonText: '停止'
  }).catch(() => false)
  if (!ok) return
  await request.delete(`/api/homeworks/series/${row.id}`)
  ElMessage.success('已停止')
  loadSeries()
}

const pad = (n) => String(n).padStart(2, '0')
const fmtDateTime = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
  `${pad(d.getHours())}:${pad(d.getMinutes())}`
const timelinePoints = computed(() => {
  const s = timeline.value
  if (!s) return []
  const hws = s.homeworks || []
  const start = new Date((s.start_at || '').replace(' ', 'T'))
  return Array.from({ length: s.count }, (_, i) => {
    const dt = new Date(start.getTime() + i * (s.interval_hours || 24) * 3600000)
    return { index: i, planned: fmtDateTime(dt), generated: hws[i] || null,
             overdue: !hws[i] && dt < new Date() }
  })
})
const openTimeline = async (row) => {
  timeline.value = null
  timelineDialog.value = true
  timelineLoading.value = true
  try {
    const res = await request.get(`/api/homeworks/series/${row.id}`)
    timeline.value = res.data.series
  } finally {
    timelineLoading.value = false
  }
}

watch(view, (v) => {
  page.value = 1
  viewKeyword.value = ''
  if (v === 'tpl') loadTemplates()
  else if (v === 'series') loadSeries()
})
watch(viewKeyword, () => { page.value = 1 })

const form = reactive({
  id: null, title: '', description: '', hw_type: 'question_set', deadline: '', has_deadline: true,
  allow_late: true, allow_resubmit: true, remind_before: 0, pass_score: null, reference: null,
  late_penalty_pct: 0, blind_grading: false, shuffle_questions: false, shuffle_options: false,
  remind_levels: [],
  grade_mode: 'numeric', grade_scale: [], rubric_id: null,
  enable_monitor: false, allow_revision: false,
  course_id: null,
  questions: [], student_ids: [], is_group: false, groups: []
})

const totalScore = computed(() =>
  form.questions.reduce((s, q) => s + (Number(q.score) || 0), 0).toFixed(1))

const statusText = (s) => ({ draft: '草稿', published: '已发布', closed: '已关闭' }[s] || s)
const statusTag = (s) => ({ draft: 'info', published: 'success', closed: 'warning' }[s] || 'info')

const load = async () => {
  const params = tab.value === 'all' ? {} : { status: tab.value }
  const res = await request.get('/api/homeworks', { params })
  items.value = res.data.items || []
}

const loadMeta = async () => {
  const [m, s, r, cs] = await Promise.all([
    request.get('/api/majors'), request.get('/api/students'), request.get('/api/homeworks/rubrics'),
    request.get('/api/courses')
  ])
  majors.value = Array.isArray(m.data) ? m.data : (m.data.items || [])
  students.value = Array.isArray(s.data) ? s.data : (s.data.items || [])
  rubrics.value = r.data.items || []
  courses.value = Array.isArray(cs.data) ? cs.data : []
}

const loadQuestions = async () => {
  const params = pickMajor.value ? { major_id: pickMajor.value } : {}
  const res = await request.get('/api/questions', { params })
  questionPool.value = Array.isArray(res.data) ? res.data : []
}

const addRemindLevel = () => {
  if (!form.remind_levels) form.remind_levels = []
  form.remind_levels.push({ minutes: 1440, label: '1天' })
}

const openCreate = () => {
  Object.assign(form, {
    id: null, title: '', description: '', hw_type: 'question_set', deadline: '', has_deadline: true,
    allow_late: true, allow_resubmit: true, remind_before: 0, pass_score: null, reference: null,
    late_penalty_pct: 0, blind_grading: false, shuffle_questions: false, shuffle_options: false,
    remind_levels: [],
    grade_mode: 'numeric', grade_scale: [], rubric_id: null,
    enable_monitor: false, allow_revision: false,
    course_id: null,
    questions: [], student_ids: [], is_group: false, groups: []
  })
  pickMajor.value = null
  questionPool.value = []
  dialog.value = true
}

const openEdit = async (row) => {
  const res = await request.get(`/api/homeworks/${row.id}`)
  const hw = res.data
  Object.assign(form, {
    id: hw.id, title: hw.title, description: hw.description || '', hw_type: hw.hw_type,
    deadline: hw.deadline || '', has_deadline: !!hw.has_deadline,
    allow_late: hw.allow_late, allow_resubmit: hw.allow_resubmit,
    remind_before: hw.remind_before || 0, pass_score: hw.pass_score ?? null, reference: hw.reference || null,
    late_penalty_pct: hw.late_penalty_pct || 0, blind_grading: !!hw.blind_grading,
    shuffle_questions: !!hw.shuffle_questions, shuffle_options: !!hw.shuffle_options,
    enable_monitor: !!hw.enable_monitor,
    allow_revision: !!hw.allow_revision,
    remind_levels: (hw.remind_levels || []).map(l => ({ minutes: l.minutes, label: l.label || '' })),
    grade_mode: hw.grade_mode || 'numeric',
    grade_scale: Array.isArray(hw.grade_scale) ? hw.grade_scale.map(x => ({ label: x.label, min: Number(x.min) })) : [],
    rubric_id: hw.rubric_id ?? null,
    course_id: hw.course_id ?? null,
    questions: (hw.questions || []).map(q => ({ question_id: q.question_id, content: q.content, score: q.score })),
    student_ids: hw.student_ids || [],
    is_group: !!hw.is_group,
    groups: (hw.groups || []).map(g => ({ name: g.name, student_ids: (g.members || []).map(m => m.student_id) }))
  })
  await loadQuestions()
  dialog.value = true
}

const qKey = (id) => `q${id}`
const onPick = (selection, row) => {
  if (selection.includes(row) && !form.questions.find(q => q.question_id === row.id)) {
    form.questions.push({ question_id: row.id, content: row.content, score: 5 })
  }
}
const onPickAll = (selection) => {
  selection.forEach(row => {
    if (!form.questions.find(q => q.question_id === row.id)) {
      form.questions.push({ question_id: row.id, content: row.content, score: 5 })
    }
  })
}
const removeQ = (i) => form.questions.splice(i, 1)

const save = async () => {
  if (!form.title.trim()) return ElMessage.warning('请填写标题')
  if (form.has_deadline && !form.deadline) return ElMessage.warning('请选择截止时间，或关闭“设置截止时间”')
  saving.value = true
  try {
    const payload = {
      title: form.title, description: form.description, hw_type: form.hw_type,
      deadline: form.has_deadline ? form.deadline : '', allow_late: form.allow_late,
      allow_resubmit: form.allow_resubmit, remind_before: form.has_deadline ? form.remind_before : 0,
      pass_score: form.pass_score, is_group: form.is_group,
      course_id: form.course_id ?? null,
      blind_grading: form.blind_grading,
      shuffle_questions: form.hw_type === 'question_set' ? !!form.shuffle_questions : false,
      shuffle_options: form.hw_type === 'question_set' ? !!form.shuffle_options : false,
      enable_monitor: !!form.enable_monitor,
      allow_revision: !!form.allow_revision,
      late_penalty_pct: form.has_deadline ? (form.late_penalty_pct || 0) : 0,
      grade_mode: form.grade_mode,
      grade_scale: form.grade_mode === 'level' ? (form.grade_scale || []) : null,
      rubric_id: form.rubric_id || null,
    }
    const rl = (form.remind_levels || []).filter(l => l && Number(l.minutes) > 0)
    payload.remind_levels = rl.length ? rl.map(l => ({ minutes: Number(l.minutes), label: l.label || '' })) : null
    if (form.is_group) {
      payload.groups = form.groups.map(g => ({ name: g.name, student_ids: g.student_ids }))
    } else {
      payload.student_ids = form.student_ids
    }
    if (form.hw_type === 'question_set') {
      payload.questions = form.questions.map(q => ({ question_id: q.question_id, score: q.score }))
    }
    if (form.id) await request.put(`/api/homeworks/${form.id}`, payload)
    else await request.post('/api/homeworks', payload)
    ElMessage.success('已保存')
    dialog.value = false
    load()
  } finally {
    saving.value = false
  }
}

const doPublish = async (row) => {
  const res = await request.post(`/api/homeworks/${row.id}/publish`)
  ElMessage.success(res.data.message || '已发布')
  load()
}
const doClose = async (row) => {
  await ElMessageBox.confirm(`确认关闭作业《${row.title}》？关闭后不再接收提交。`, '提示', { type: 'warning' })
  await request.post(`/api/homeworks/${row.id}/close`)
  ElMessage.success('已关闭')
  load()
}
const doDelete = async (row) => {
  await ElMessageBox.confirm(`确认删除草稿《${row.title}》？`, '提示', { type: 'warning' })
  await request.delete(`/api/homeworks/${row.id}`)
  ElMessage.success('已删除')
  load()
}

const onRowCommand = (cmd, row) => {
  if (cmd === 'stats') return openStats(row)
  if (cmd === 'copy') return doCopy(row)
  if (cmd === 'urge') return doUrge(row)
  if (cmd === 'export') return doExport(row)
  if (cmd === 'delete') return doDelete(row)
}

const doUrge = async (row) => {
  const res = await request.post(`/api/homeworks/${row.id}/urge`)
  ElMessage.success(res.data.message || '已催交')
}

const doCopy = async (row) => {
  await request.post(`/api/homeworks/${row.id}/copy`)
  ElMessage.success('已复制为草稿')
  tab.value = 'draft'
  load()
}

const downloadBlob = async (url, filename) => {
  const res = await request.get(url, { responseType: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(res.data)
  link.download = filename || 'download'
  link.click()
  URL.revokeObjectURL(link.href)
}

const doExport = (row) => downloadBlob(`/api/homeworks/${row.id}/export`, `homework_${row.id}_scores.csv`)

const openStats = async (row) => {
  statsId.value = row.id
  statsHomework.value = row.title
  stats.value = {}
  statsDialog.value = true
  statsLoading.value = true
  try {
    const res = await request.get(`/api/homeworks/${row.id}/stats`)
    stats.value = res.data.stats || {}
  } finally {
    statsLoading.value = false
  }
}
const doExportStats = () => doExport({ id: statsId.value })

const randomPick = async () => {
  const params = { count: randCount.value || 5 }
  if (pickMajor.value) params.major_id = pickMajor.value
  if (randDifficulty.value) params.difficulty = randDifficulty.value
  const exclude = form.questions.map(q => q.question_id)
  if (exclude.length) params.exclude = exclude
  const res = await request.get('/api/homeworks/random_questions', { params })
  const items = res.data.items || []
  if (!items.length) return ElMessage.warning('题库无匹配题目')
  items.forEach(it => {
    if (!form.questions.find(q => q.question_id === it.question_id)) {
      form.questions.push({ question_id: it.question_id, content: it.content, score: it.score || 5 })
    }
  })
  ElMessage.success(`已随机抽取 ${items.length} 题`)
}

const uploadRef = async ({ file }) => {
  const fd = new FormData()
  fd.append('file', file)
  const res = await request.post(`/api/homeworks/${form.id}/reference`, fd,
    { headers: { 'Content-Type': 'multipart/form-data' } })
  form.reference = res.data.reference || null
  ElMessage.success(res.data.message || '已上传')
  load()
}
const removeRef = async () => {
  const res = await request.delete(`/api/homeworks/${form.id}/reference`)
  form.reference = null
  ElMessage.success(res.data.message || '已删除')
  load()
}
const downloadRef = () => form.reference &&
  downloadBlob(`/api/homeworks/${form.id}/reference`, form.reference.filename)

onMounted(() => { load(); loadMeta(); loadQuestions() })
</script>

<style scoped>
.page-wrapper { padding: 20px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.title-icon { vertical-align: middle; margin-right: 6px; color: #6366f1; }
.link { color: var(--el-color-primary, #409eff); }
.link:hover { text-decoration: underline; }
.overdue { color: #f56c6c; }
.hint { margin-left: 10px; font-size: 12px; color: #909399; }
.picker { width: 100%; }
.picker-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.picker-tools { display: flex; align-items: center; gap: 8px; }
.ref-row { display: flex; align-items: center; gap: 12px; }
.chosen { margin-top: 10px; max-height: 180px; overflow: auto; }
.chosen-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px dashed #ebeef5; }
.chosen-row .idx { width: 22px; color: #909399; }
.chosen-row .ct { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.group-builder { width: 100%; display: flex; flex-direction: column; gap: 8px; }
.group-row { display: flex; align-items: center; gap: 8px; }
.list-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.muted { color: #9ca3af; }
.small { font-size: 12px; }
.cascade-row { display: flex; gap: 8px; width: 100%; }
.cascade-row .el-select { flex: 1; }
.dist-cell { display: flex; flex-direction: column; gap: 6px; }
.dist-bars { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: #f0f2f5; }
.dist-seg { display: block; height: 100%; transition: flex .2s; }
.dist-seg.d-easy { background: #34d399; }
.dist-seg.d-medium { background: #60a5fa; }
.dist-seg.d-hard { background: #f59e0b; }
.dist-seg.d-unknown { background: #cbd5e1; }
.dist-editor { width: 100%; }
.dist-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.dist-name { width: 40px; font-size: 13px; color: #4b5563; }
.dist-preview { flex: 1; height: 8px; background: #f0f2f5; border-radius: 4px; overflow: hidden; }
.dist-preview .dist-seg { height: 100%; }
.error-text { color: #ef4444; }
.preview-stats { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.preview-bars { margin-bottom: 12px; height: 10px; }
.timeline-summary { display: flex; gap: 16px; font-size: 13px; color: #6b7280;
  padding: 8px 12px; background: #f8fafc; border-radius: 8px; margin-bottom: 14px; }
.tl-title { font-size: 13px; font-weight: 600; color: #374151; display: flex;
  align-items: center; gap: 8px; margin-bottom: 4px; }
</style>
