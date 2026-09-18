<template>
  <div class="kg-wrapper">
    <div ref="containerRef" v-show="nodes.length > 0" class="kg-container" :style="{ height }"></div>
    <div v-if="nodes.length === 0" class="kg-empty" :style="{ height }">
      <div class="kg-empty-icon">
        <el-icon :size="30" color="#06b6d4"><Share /></el-icon>
      </div>
      <p>暂无图谱数据</p>
      <span v-if="editable">请先创建知识点，再在知识点之间建立关系边</span>
      <span v-else>该范围内还没有知识点或关系</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import cytoscape from 'cytoscape'

const props = defineProps({
  nodes: { type: Array, default: () => [] },       // [{id,name,description,difficulty,chapter_id,chapter_name}]
  edges: { type: Array, default: () => [] },       // [{id,source,target,relation_type,weight}]
  layout: { type: String, default: 'cose' },       // cose / breadthfirst / circle
  height: { type: String, default: '560px' },
  highlightIds: { type: Array, default: () => [] }, // 高亮的知识点 id（如已掌握）
  editable: { type: Boolean, default: false },
})
const emit = defineEmits(['node-tap', 'edge-tap', 'background-tap'])

const containerRef = ref(null)
let cy = null
let themeObserver = null

const DIFF_COLORS = { easy: '#10b981', medium: '#f59e0b', hard: '#ef4444' }
const ACCENT = '#06b6d4'

const isDark = () => document.documentElement.classList.contains('dark')

// 按关联度（边数）计算节点尺寸：38px 起步，每多一条边 +3，封顶 62px
function buildElements() {
  const highlight = new Set(props.highlightIds)
  const deg = {}
  props.edges.forEach(e => {
    if (e.source == null || e.target == null) return
    deg[e.source] = (deg[e.source] || 0) + 1
    deg[e.target] = (deg[e.target] || 0) + 1
  })
  return [
    ...props.nodes.map(n => {
      const d = deg[n.id] || 0
      return {
        data: {
          id: `kp-${n.id}`,
          name: n.name,
          color: DIFF_COLORS[n.difficulty] || '#10b981',
          'border-color': highlight.has(n.id) ? ACCENT : (isDark() ? '#334155' : '#ffffff'),
          'border-width': highlight.has(n.id) ? 4 : 2.5,
          size: 38 + Math.min(d, 8) * 3,
          raw: n,
        },
        classes: highlight.has(n.id) ? 'hl' : '',
      }
    }),
    ...props.edges
      .filter(e => e.source != null && e.target != null)
      .map(e => ({
        data: {
          id: `edge-${e.id}`,
          source: `kp-${e.source}`,
          target: `kp-${e.target}`,
          relation: e.relation_type || 'related',
          raw: e,
        },
      })),
  ]
}

function getLayout() {
  if (props.layout === 'breadthfirst') {
    return { name: 'breadthfirst', directed: true, spacingFactor: 1.2, padding: 30, animate: true, animationDuration: 400 }
  }
  if (props.layout === 'circle') {
    return { name: 'circle', spacingFactor: 1.15, padding: 30, animate: true, animationDuration: 400 }
  }
  return {
    name: 'cose', padding: 30, animate: true, animationDuration: 450,
    randomize: true, spacingFactor: 1.1, idealEdgeLength: () => 130,
    nodeOverlap: 24, nodeRepulsion: () => 9000,
  }
}

// ── hover 交互：聚焦邻域，淡出无关元素 ─────────────────────────────
const focusNeighborhood = (ele) => {
  if (!cy) return
  cy.elements().addClass('dimmed')
  ele.removeClass('dimmed')
  if (ele.isNode()) {
    ele.connectedEdges().removeClass('dimmed').addClass('edge-focus')
    ele.neighborhood('node').removeClass('dimmed')
  }
  ele.addClass('node-focus')
}

const clearFocus = () => {
  if (!cy) return
  cy.elements().removeClass('dimmed node-focus edge-focus')
}

const render = () => {
  if (!containerRef.value || props.nodes.length === 0) return
  const dark = isDark()
  if (cy) { cy.destroy(); cy = null }

  const edgeColor = dark ? 'rgba(148, 163, 184, 0.55)' : 'rgba(100, 116, 139, 0.45)'
  const labelColor = dark ? '#e2e8f0' : '#334155'
  const labelBg = dark ? 'rgba(15, 23, 42, 0.75)' : 'rgba(255, 255, 255, 0.85)'

  cy = cytoscape({
    container: containerRef.value,
    elements: buildElements(),
    layout: getLayout(),
    style: [
      {
        selector: 'node',
        style: {
          label: 'data(name)',
          width: 'data(size)',
          height: 'data(size)',
          'background-color': 'data(color)',
          'background-opacity': 0.92,
          'border-width': 'data(border-width)',
          'border-color': 'data(border-color)',
          // 发光底层：掌握/聚焦节点泛青色光晕
          'underlay-color': ACCENT,
          'underlay-opacity': 0,
          'underlay-padding': 10,
          color: labelColor,
          'font-size': 12,
          'font-weight': 600,
          'text-valign': 'bottom',
          'text-margin-y': 7,
          'text-wrap': 'wrap',
          'text-max-width': 96,
          'text-background-color': labelBg,
          'text-background-opacity': 1,
          'text-background-padding': 3,
          'text-background-shape': 'roundrectangle',
          'overlay-padding': 4,
          'transition-property': 'width height border-width underlay-opacity overlay-opacity opacity',
          'transition-duration': '0.18s',
        },
      },
      {
        selector: 'node.hl',
        style: { 'underlay-opacity': 0.35 },
      },
      {
        selector: 'node.node-focus',
        style: { 'underlay-opacity': 0.4, 'border-color': ACCENT },
      },
      {
        // 抓取/按下反馈：青色光圈 + 加粗描边
        selector: 'node.grabbed',
        style: {
          'overlay-color': ACCENT,
          'overlay-opacity': 0.14,
          'border-width': 4,
          'border-color': ACCENT,
        },
      },
      {
        selector: 'node, edge',
        style: {
          'transition-property': 'opacity, line-color, width, underlay-opacity, overlay-opacity',
          'transition-duration': '0.18s',
        },
      },
      {
        // 非邻域淡出
        selector: '.dimmed',
        style: { opacity: 0.15 },
      },
      {
        selector: 'edge',
        style: {
          width: 2,
          'curve-style': 'bezier',
          'control-point-step-size': 64,
          'line-color': edgeColor,
          'target-arrow-color': edgeColor,
          'target-arrow-shape': 'none',
          'arrow-scale': 1.15,
          'overlay-padding': 3,
        },
      },
      {
        selector: 'edge.edge-focus',
        style: {
          width: 3.5,
          'line-color': ACCENT,
          'target-arrow-color': ACCENT,
          'overlay-color': ACCENT,
          'overlay-opacity': 0.08,
        },
      },
      {
        selector: 'edge[relation = "prerequisite"]',
        style: { 'line-style': 'solid', 'target-arrow-shape': 'triangle' },
      },
      {
        selector: 'edge[relation = "related"]',
        style: { 'line-style': 'dashed' },
      },
      {
        selector: 'edge[relation = "derived"]',
        style: { 'line-style': 'dotted', 'target-arrow-shape': 'triangle' },
      },
    ],
    minZoom: 0.25,
    maxZoom: 2.5,
    wheelSensitivity: 0.25,
    autoungrabify: false,
  })

  cy.on('tap', 'node', evt => emit('node-tap', evt.target.data('raw')))
  cy.on('tap', 'edge', evt => emit('edge-tap', evt.target.data('raw')))
  cy.on('tap', evt => { if (evt.target === cy) emit('background-tap') })

  // hover 高亮：节点聚焦邻域、边加粗着色，光标跟随
  cy.on('mouseover', 'node', evt => {
    focusNeighborhood(evt.target)
    containerRef.value.style.cursor = 'pointer'
  })
  cy.on('mouseout', 'node', () => {
    clearFocus()
    containerRef.value.style.cursor = ''
  })
  cy.on('mouseover', 'edge', evt => {
    evt.target.addClass('edge-focus')
    containerRef.value.style.cursor = 'pointer'
  })
  cy.on('mouseout', 'edge', evt => {
    evt.target.removeClass('edge-focus')
    containerRef.value.style.cursor = ''
  })
  cy.on('grabon', 'node', evt => evt.target.addClass('grabbed'))
  cy.on('graboff', 'node', evt => evt.target.removeClass('grabbed'))

  // 便于 E2E 调试：暴露实例供测试脚本读取节点坐标/触发事件
  containerRef.value.__kg_cy = cy
}

// 数据变化重建图谱；布局切换只重跑布局（保留已拖动的位置意义不大，直接重排）
watch(() => [props.nodes, props.edges, props.highlightIds], render, { deep: true })
watch(() => props.layout, () => { if (cy && props.nodes.length) cy.layout(getLayout()).run() })

// 主题切换（明/暗）时重渲染，保证边与文字颜色随主题变化
const startThemeWatch = () => {
  themeObserver = new MutationObserver(() => render())
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
}

const onResize = () => {
  if (cy) { cy.resize(); cy.fit(undefined, 30) }
}

onMounted(() => {
  render()
  startThemeWatch()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  if (themeObserver) themeObserver.disconnect()
  window.removeEventListener('resize', onResize)
  if (cy) { cy.destroy(); cy = null }
})
</script>

<style scoped>
.kg-wrapper {
  position: relative;
  width: 100%;
}

.kg-container {
  width: 100%;
  background: var(--bg-card);
  border-radius: 12px;
}

.kg-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: var(--bg-card);
  border: 1px dashed var(--border-color);
  border-radius: 12px;
  color: var(--text-muted);
}

.kg-empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(6, 182, 212, 0.12), rgba(59, 130, 246, 0.12));
  box-shadow: 0 6px 18px rgba(6, 182, 212, 0.18);
}

.kg-empty p {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--text-primary);
}

.kg-empty span {
  font-size: 12px;
  opacity: 0.8;
}
</style>
