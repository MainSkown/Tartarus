<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import LaneIcon from '@/components/LaneIcon.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import { formatBrushLabel } from '@/services/timeline-axis'
import { laneMeta } from '@/services/lanes'
import { drawTimeline, type DrawState } from '@/services/timeline-draw'
import { createGesture, type GestureEffect } from '@/services/timeline-gesture'
import { hitTest, type Hit } from '@/services/timeline-hit-test'
import { keyCommand } from '@/services/timeline-keyboard'
import { bandRect, buildScene, computeLayout, type ClusterMark, type SceneData } from '@/services/timeline-layout'
import type { Navigation } from '@/services/timeline-navigation'
import { readTimelinePalette, type TimelinePalette } from '@/services/timeline-palette'
import { isWithin, spanLength, timeToX, wheelZoomFactor, xToTime, type Span } from '@/services/timeline-scale'
import { tooltipAnchor, tooltipFor } from '@/services/timeline-tooltip'

defineOptions({ name: 'TimelineCanvas' })

const TOOLTIP_OFFSET = 14
const LINE_SCROLL_PX = 16
const PAGE_SCROLL_PX = 100
// A count mark opens to this many times the span of the events it holds, so they land well apart.
const CLUSTER_ZOOM_SPREAD = 1.5
const DETECTION_LABEL = 'DETECTIONS'
const DETECTION_ICON = 'flag'
const CLOCK_LABEL = 'UTC'

const props = defineProps<{
  view: Span
  full: Span
  data: SceneData | undefined
  /** The time-range chip, drawn as a band with handles. */
  chip: Span | null
  selectedId: string | null
  selectedTime: number | null
  loading: boolean
  height: number
}>()

const emit = defineEmits<{
  navigate: [navigation: Navigation]
  'open-event': [id: string]
  'select-range': [span: Span]
  'clear-range': []
}>()

type CursorClass = 'is-default' | 'is-pointer' | 'is-grab' | 'is-grabbing' | 'is-crosshair' | 'is-resize'

const root = ref<HTMLElement>()
const canvas = ref<HTMLCanvasElement>()
const size = ref({ width: 0 })
const palette = ref<TimelinePalette>()
const hovered = ref<{ hit: Hit; x: number; y: number }>()
const preview = ref<Span | null>(null)
const mode = ref<'idle' | 'press' | 'pan' | 'brush' | 'handle'>('idle')

const layout = computed(() => computeLayout(size.value.width, props.height))
const pixelRatio = (): number => window.devicePixelRatio || 1
const scene = computed(() => buildScene({ layout: layout.value, view: props.view, data: props.data }))
const chipBand = computed(() => (props.chip ? bandRect(props.chip, props.view, layout.value) : null))
const shownBand = computed(() => {
  const span = preview.value ?? props.chip
  return span ? bandRect(span, props.view, layout.value) : null
})
const selectedX = computed(() =>
  props.selectedTime !== null && isWithin(props.view, props.selectedTime) ? layout.value.gutter + timeToX(props.selectedTime, props.view, layout.value.plotWidth) : null,
)
const drawState = computed<DrawState>(() => ({
  band: shownBand.value,
  brushLabel: preview.value ? formatBrushLabel(preview.value) : null,
  hover: mode.value === 'idle' ? (hovered.value?.hit ?? null) : null,
  selectedId: props.selectedId,
  selectedX: selectedX.value,
  stale: props.loading,
}))

const tooltip = computed(() => (mode.value === 'idle' && hovered.value ? tooltipFor(hovered.value.hit) : null))
const tooltipStyle = computed(() => {
  const pointer = hovered.value
  if (!pointer) return {}
  const anchor = tooltipAnchor(pointer, layout.value)
  return {
    ...(anchor.horizontal === 'left' ? { left: `${pointer.x + TOOLTIP_OFFSET}px` } : { right: `${layout.value.width - pointer.x + TOOLTIP_OFFSET}px` }),
    ...(anchor.vertical === 'top' ? { top: `${pointer.y + TOOLTIP_OFFSET}px` } : { bottom: `${layout.value.height - pointer.y + TOOLTIP_OFFSET}px` }),
  }
})

// What the root says about the scene lets the screenshot and end-to-end tests aim a pointer without knowing the layout.
const geometry = computed(() =>
  JSON.stringify({
    gutter: layout.value.gutter,
    plotWidth: layout.value.plotWidth,
    detectionY: layout.value.detectionTrack.centre,
    axisY: layout.value.axis.top + layout.value.axis.height / 2,
    lanes: Object.fromEntries(layout.value.lanes.map((lane) => [lane.lane, lane.centre])),
    viewStart: props.view.start,
    viewEnd: props.view.end,
  }),
)

const hasNothingToShow = computed(() => props.data !== undefined && scene.value.marks.length === 0 && scene.value.bars.length === 0)

const cursor = computed<CursorClass>(() => {
  if (mode.value === 'pan') return 'is-grabbing'
  if (mode.value === 'brush') return 'is-crosshair'
  if (mode.value === 'handle') return 'is-resize'
  switch (hovered.value?.hit.kind) {
    case 'mark':
    case 'cluster':
    case 'bar':
    case 'detection':
      return 'is-pointer'
    case 'handle':
      return 'is-resize'
    case 'axis':
      return 'is-crosshair'
    case 'plot':
      return 'is-grab'
    default:
      return 'is-default'
  }
})

const gesture = createGesture(() => ({
  view: props.view,
  full: props.full,
  plotWidth: layout.value.plotWidth,
  gutter: layout.value.gutter,
  chip: props.chip,
}))

function pointerAt(event: MouseEvent): { x: number; y: number } {
  const rect = canvas.value!.getBoundingClientRect()
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

function navigate(navigation: Navigation): void {
  emit('navigate', navigation)
}

function clickOn(hit: Hit): void {
  if (hit.kind === 'mark') emit('open-event', hit.mark.id)
  else if (hit.kind === 'detection') emit('open-event', hit.detection.id)
  else if (hit.kind === 'bar') navigate({ kind: 'view', span: { start: hit.bar.start, end: hit.bar.end } })
  else if (hit.kind === 'cluster') openCluster(hit.mark)
}

function openCluster(cluster: ClusterMark): void {
  const length = cluster.end - cluster.start
  if (length === 0) emit('open-event', cluster.ids[0]!)
  else navigate({ kind: 'view', span: { start: cluster.start - length * CLUSTER_ZOOM_SPREAD, end: cluster.end + length * CLUSTER_ZOOM_SPREAD } })
}

function apply(effect: GestureEffect | undefined): void {
  mode.value = gesture.mode
  if (!effect) return
  switch (effect.type) {
    case 'pan':
      return navigate({ kind: 'pan-pixels', dx: effect.dx, width: layout.value.plotWidth })
    case 'brush':
    case 'handle':
      preview.value = effect.span
      return
    case 'brush-end':
    case 'handle-end':
      preview.value = null
      if (effect.span) emit('select-range', effect.span)
      return
    case 'cancel':
      preview.value = null
      return
    case 'click':
      return clickOn(effect.hit)
  }
}

function onPointerDown(event: PointerEvent): void {
  if (event.button !== 0) return
  const { x, y } = pointerAt(event)
  hovered.value = undefined
  gesture.down(hitTest(scene.value, chipBand.value, x, y), x, y)
  mode.value = gesture.mode
  canvas.value!.setPointerCapture?.(event.pointerId)
}

function onPointerMove(event: PointerEvent): void {
  const { x, y } = pointerAt(event)
  if (gesture.mode !== 'idle') return apply(gesture.move(x, y))
  const hit = hitTest(scene.value, chipBand.value, x, y)
  hovered.value = hit ? { hit, x, y } : undefined
}

function onPointerUp(event: PointerEvent): void {
  canvas.value!.releasePointerCapture?.(event.pointerId)
  apply(gesture.up(pointerAt(event).x))
}

function onPointerLeave(): void {
  if (gesture.mode === 'idle') hovered.value = undefined
}

function onWheel(event: WheelEvent): void {
  const { x } = pointerAt(event)
  const { gutter, plotWidth } = layout.value
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return navigate({ kind: 'pan-pixels', dx: -event.deltaX, width: plotWidth })
  const unit = event.deltaMode === 1 ? LINE_SCROLL_PX : event.deltaMode === 2 ? PAGE_SCROLL_PX : 1
  const overPlot = x >= gutter
  const time = overPlot ? xToTime(Math.min(x - gutter, plotWidth), props.view, plotWidth) : props.view.start + spanLength(props.view) / 2
  navigate({ kind: 'zoom', time, factor: wheelZoomFactor(event.deltaY * unit) })
}

function focusTime(): number {
  return props.selectedTime !== null && isWithin(props.view, props.selectedTime) ? props.selectedTime : props.view.start + spanLength(props.view) / 2
}

function onKeydown(event: KeyboardEvent): void {
  const command = keyCommand(event)
  if (command === null) return
  event.preventDefault()
  switch (command.type) {
    case 'pan':
      return navigate({ kind: 'pan-fraction', fraction: command.fraction })
    case 'zoom':
      return navigate({ kind: 'zoom', time: focusTime(), factor: command.factor })
    case 'fit':
      return navigate({ kind: 'fit' })
    case 'jump':
      return navigate({ kind: 'jump', edge: command.edge })
    case 'escape':
      if (gesture.mode === 'idle') emit('clear-range')
      else apply(gesture.cancel())
  }
}

function measure(): void {
  if (!root.value) return
  size.value = { width: Math.round(root.value.getBoundingClientRect().width) }
}

function paint(): void {
  const context = canvas.value?.getContext('2d')
  if (!context || !palette.value) return
  const ratio = pixelRatio()
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  drawTimeline(context, scene.value, drawState.value, palette.value)
}

let paintQueued = false
let frame: number | undefined
function schedulePaint(): void {
  if (paintQueued) return
  paintQueued = true
  frame = requestAnimationFrame(() => {
    paintQueued = false
    paint()
  })
}

let observer: ResizeObserver | undefined
onMounted(() => {
  const style = getComputedStyle(document.documentElement)
  palette.value = readTimelinePalette((token) => style.getPropertyValue(token).trim())
  measure()
  observer = new ResizeObserver(measure)
  observer.observe(root.value!)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  if (frame !== undefined) cancelAnimationFrame(frame)
})

watch([scene, drawState, palette], schedulePaint, { flush: 'post' })
</script>

<template>
  <div
    ref="root"
    class="timeline"
    :style="{ height: `${layout.height}px` }"
    :data-source="scene.source"
    :data-marks="scene.marks.length"
    :data-bars="scene.bars.length"
    :data-detections="scene.detections.length"
    :data-geometry="geometry"
  >
    <canvas
      ref="canvas"
      class="timeline__canvas"
      :class="cursor"
      :width="Math.round(layout.width * pixelRatio())"
      :height="Math.round(layout.height * pixelRatio())"
      :style="{ width: `${layout.width}px`, height: `${layout.height}px` }"
      tabindex="0"
      aria-label="Timeline of the analysis's events, one lane per category"
      aria-description="Arrow left and right pan, plus and minus zoom, 0 fits the whole run, Home and End jump to the start and the end, Escape clears the selected range"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="apply(gesture.cancel())"
      @pointerleave="onPointerLeave"
      @wheel.prevent="onWheel"
      @dblclick="navigate({ kind: 'fit' })"
      @keydown="onKeydown"
    />

    <div
      class="timeline__gutter text-mono"
      :style="{ width: `${layout.gutter}px` }"
      aria-hidden="true"
    >
      <div
        class="timeline__gutter-row"
        :style="{ top: `${layout.detectionTrack.top}px`, height: `${layout.detectionTrack.height}px` }"
      >
        <q-icon
          :name="DETECTION_ICON"
          size="16px"
        />
        <span class="timeline__gutter-label">{{ DETECTION_LABEL }}</span>
      </div>
      <div
        v-for="lane in layout.lanes"
        :key="lane.lane"
        class="timeline__gutter-row"
        :style="{ top: `${lane.top}px`, height: `${lane.height}px` }"
      >
        <LaneIcon :lane="lane.lane" />
        <span class="timeline__gutter-label">{{ laneMeta(lane.lane).label }}</span>
      </div>
      <div
        class="timeline__gutter-row timeline__gutter-row--axis"
        :style="{ top: `${layout.axis.top}px`, height: `${layout.axis.height}px` }"
      >
        <span class="timeline__gutter-label">{{ CLOCK_LABEL }}</span>
      </div>
    </div>

    <div
      v-if="loading"
      class="timeline__loading"
      role="status"
      aria-label="Loading the range"
    />

    <p
      v-if="hasNothingToShow && !loading"
      class="timeline__empty text-mono text-gray"
      :style="{ left: `${layout.gutter}px`, top: `${layout.lanes[0]!.top}px`, width: `${layout.plotWidth}px`, height: `${layout.axis.top - layout.lanes[0]!.top}px` }"
    >
      &gt; no events in this range
    </p>

    <div
      v-if="tooltip"
      class="timeline__tooltip"
      :style="tooltipStyle"
      role="tooltip"
    >
      <div class="timeline__tooltip-head">
        <SeverityBadge
          v-if="tooltip.severity"
          :severity="tooltip.severity"
        />
        <LaneIcon
          v-if="tooltip.lane"
          :lane="tooltip.lane"
        />
        <span class="timeline__tooltip-title">{{ tooltip.title }}</span>
      </div>
      <dl class="timeline__tooltip-rows text-mono">
        <template
          v-for="(row, index) in tooltip.rows"
          :key="index"
        >
          <dt class="text-gray">
            {{ row.label }}
          </dt>
          <dd>{{ row.value }}</dd>
        </template>
      </dl>
      <p class="timeline__tooltip-hint text-mono text-gray">
        {{ tooltip.hint }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.timeline {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  background: var(--dark-bg);
  user-select: none;
}

.timeline__canvas {
  display: block;
  touch-action: none;
}

.timeline__canvas:focus-visible {
  outline: 2px solid var(--blue-light);
  outline-offset: -2px;
}

.timeline__canvas.is-pointer { cursor: pointer; }
.timeline__canvas.is-grab { cursor: grab; }
.timeline__canvas.is-grabbing { cursor: grabbing; }
.timeline__canvas.is-crosshair { cursor: crosshair; }
.timeline__canvas.is-resize { cursor: ew-resize; }

.timeline__gutter {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  pointer-events: none;
}

.timeline__gutter-row {
  position: absolute;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: 0 var(--spacing-sm);
  color: var(--text-gray);
  font-size: 0.65rem;
  letter-spacing: 1px;
  white-space: nowrap;
}

.timeline__gutter-row--axis {
  color: var(--text-gray-dark);
}

.timeline__loading {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  overflow: hidden;
  pointer-events: none;
}

.timeline__loading::after {
  content: '';
  display: block;
  width: 30%;
  height: 100%;
  background: linear-gradient(90deg, var(--blue-primary), var(--blue-light));
  animation: timeline-loading 1.2s linear infinite;
}

@keyframes timeline-loading {
  from { transform: translateX(-100%); }
  to { transform: translateX(340%); }
}

.timeline__empty {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  font-size: 0.8rem;
  pointer-events: none;
}

.timeline__tooltip {
  position: absolute;
  z-index: 2;
  max-width: min(380px, 70%);
  padding: var(--spacing-sm);
  border: 1px solid var(--blue-primary);
  background: var(--card-bg);
  font-size: 0.8rem;
  pointer-events: none;
}

.timeline__tooltip-head {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-xs);
}

.timeline__tooltip-title {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow-wrap: anywhere;
  font-weight: 600;
}

.timeline__tooltip-rows {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 2px var(--spacing-sm);
  margin: 0;
  font-size: 0.72rem;
}

.timeline__tooltip-rows dt,
.timeline__tooltip-rows dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.timeline__tooltip-hint {
  margin: var(--spacing-xs) 0 0;
  font-size: 0.68rem;
}

@media (prefers-reduced-motion: reduce) {
  .timeline__loading::after {
    animation: none;
    width: 100%;
  }
}
</style>
