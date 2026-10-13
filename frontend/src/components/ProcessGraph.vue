<script setup lang="ts">
import cytoscape, { type Core, type LayoutOptions } from 'cytoscape'
import dagre from 'cytoscape-dagre'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ProcessNode } from '@/api'
import { graphStylesheet, readGraphColors, toGraphElements, type GraphColors } from '@/services/process-graph'

const props = defineProps<{ roots: ProcessNode[]; selectedId?: string }>()
const emit = defineEmits<{ select: [entityId: string] }>()

cytoscape.use(dagre)

const FIT_PADDING = 30
const MAX_FIT_ZOOM = 1
const ZOOM_STEP = 1.25
const EXPORT_SCALE = 2
const LAYOUT = {
  name: 'dagre',
  rankDir: 'TB',
  nodeSep: 30,
  rankSep: 50,
  fit: false,
  animate: false,
  nodeDimensionsIncludeLabels: true,
} as LayoutOptions

const canvas = ref<HTMLElement>()
const showInjection = ref(true)
const showHosts = ref(false)

let graph: Core | undefined
let colors: GraphColors | undefined
let resizeObserver: ResizeObserver | undefined

function elements() {
  return toGraphElements(props.roots, { injection: showInjection.value, hosts: showHosts.value })
}

function applySelection(): void {
  if (!graph) return
  const { selectedId } = props
  graph.batch(() => {
    graph!.nodes().forEach((node) => {
      const selected = node.id() === selectedId
      node.toggleClass('selected', selected)
      node.toggleClass('dimmed', selectedId !== undefined && !selected && !node.hasClass('host'))
    })
  })
}

function fit(): void {
  if (!graph) return
  graph.fit(undefined, FIT_PADDING)
  // A small tree would otherwise be blown up to fill the canvas.
  if (graph.zoom() > MAX_FIT_ZOOM) {
    graph.zoom(MAX_FIT_ZOOM)
    graph.center()
  }
}

function layOut(): void {
  graph?.layout(LAYOUT).run()
  fit()
}

function redraw(): void {
  if (!graph) return
  graph.elements().remove()
  graph.add(elements())
  applySelection()
  layOut()
}

function zoomBy(factor: number): void {
  if (!graph) return
  graph.zoom({ level: graph.zoom() * factor, renderedPosition: { x: graph.width() / 2, y: graph.height() / 2 } })
}

function exportPng(): void {
  if (!graph || !colors) return
  const link = document.createElement('a')
  link.href = graph.png({ full: true, scale: EXPORT_SCALE, bg: colors.background })
  link.download = 'process-graph.png'
  link.click()
}

onMounted(() => {
  colors = readGraphColors(canvas.value!)
  graph = cytoscape({
    container: canvas.value,
    elements: elements(),
    style: graphStylesheet(colors),
    minZoom: 0.1,
    maxZoom: 3,
    boxSelectionEnabled: false,
  })
  graph.on('tap', 'node', (event) => {
    if (!event.target.hasClass('host')) emit('select', event.target.id())
  })
  applySelection()
  layOut()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => graph?.resize())
    resizeObserver.observe(canvas.value!)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  graph?.destroy()
  graph = undefined
})

watch(() => props.selectedId, applySelection)
watch([() => props.roots, showInjection, showHosts], redraw)
</script>

<template>
  <div class="process-graph">
    <div class="process-graph__toolbar">
      <q-btn
        flat
        dense
        square
        icon="fit_screen"
        aria-label="Fit graph to view"
        title="Fit graph to view"
        @click="fit"
      />
      <q-btn
        flat
        dense
        square
        icon="add"
        aria-label="Zoom in"
        title="Zoom in"
        @click="zoomBy(ZOOM_STEP)"
      />
      <q-btn
        flat
        dense
        square
        icon="remove"
        aria-label="Zoom out"
        title="Zoom out"
        @click="zoomBy(1 / ZOOM_STEP)"
      />
      <q-btn
        flat
        dense
        square
        icon="account_tree"
        aria-label="Reset layout"
        title="Reset layout"
        @click="layOut"
      />
      <q-btn
        flat
        dense
        square
        icon="download"
        aria-label="Export PNG"
        title="Export PNG"
        @click="exportPng"
      />
      <q-toggle
        v-model="showInjection"
        dense
        label="INJECTION"
        class="process-graph__toggle text-mono"
      />
      <q-toggle
        v-model="showHosts"
        dense
        label="HOSTS"
        class="process-graph__toggle text-mono"
      />
      <slot name="toolbar-end" />
    </div>
    <div
      ref="canvas"
      class="process-graph__canvas"
      role="img"
      aria-label="Process graph; the same data is available as a tree"
    />
  </div>
</template>

<style scoped>
.process-graph {
  display: flex;
  flex-direction: column;
  flex: 1 1 0;
  min-width: 0;
  min-height: 0;
}

.process-graph__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-sm);
  padding-bottom: var(--spacing-sm);
}

.process-graph__toggle {
  margin-left: var(--spacing-sm);
  font-size: 0.7rem;
  letter-spacing: 1px;
}

.process-graph__canvas {
  flex: 1 1 0;
  min-width: 0;
  min-height: 360px;
  overflow: hidden;
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}
</style>
