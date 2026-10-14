<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AnalysisRead } from '@/api'
import EventDetailDrawer from '@/components/EventDetailDrawer.vue'
import EventTable from '@/components/EventTable.vue'
import Timeline from '@/components/Timeline.vue'
import ViewState from '@/components/ViewState.vue'
import { useViewportFill } from '@/composables/use-viewport-fill'
import { formatVisibleRange } from '@/services/timeline-axis'
import { spanToQueryRange } from '@/services/timeline-brush'
import { applyNavigation, type Navigation } from '@/services/timeline-navigation'
import { isWithin, type Span, type ZoomPreset } from '@/services/timeline-scale'
import { useEventsStore } from '@/stores/events'
import { useQueryStateStore } from '@/stores/query-state'
import { useTimelineStore } from '@/stores/timeline'

// The canvas is this tall whatever the window: six lanes, the detection track and the axis fit
// with the page header, tabs and query bar above and a few table rows below at 1280x720.
const CANVAS_HEIGHT = 248
// Below this the table stops shrinking and the page scrolls: a header, a few rows and the footer still fit.
const MIN_BODY_HEIGHT = 380
const BOTTOM_GAP = 16

const ZOOM_OPTIONS: { label: string; value: ZoomPreset }[] = [
  { label: 'FIT', value: 'fit' },
  { label: '1M', value: '1m' },
  { label: '10S', value: '10s' },
  { label: '1S', value: '1s' },
]

defineProps<{ analysis: AnalysisRead }>()

const query = useQueryStateStore()
const events = useEventsStore()
const timeline = useTimelineStore()

const root = ref<HTMLElement>()
const { height: fillHeight } = useViewportFill(root, BOTTOM_GAP)

// Selection and the open event are two things, as on the Events tab: the arrow keys move the first through the table.
const selectedId = ref<string | null>(query.eventId)

const visibleRange = computed(() => (timeline.view ? formatVisibleRange(timeline.view) : ''))
const canZoom = computed(() => timeline.status === 'ready')
const tableLoading = computed(() => events.loading || (!events.loaded && events.error === undefined))
const tableFiltered = computed(() => !query.isEmpty || timeline.tableRange !== null)
const canvasError = computed(() => (timeline.status === 'error' ? (timeline.error?.message ?? 'unknown error') : undefined))

const selectedTime = computed<number | null>(() => {
  if (selectedId.value === null) return null
  const listed = events.events.find((event) => event.id === selectedId.value)
  const drawn = timeline.data?.mode === 'events' ? timeline.data.events.find((event) => event.id === selectedId.value) : undefined
  const event = listed ?? drawn
  return event ? Date.parse(event.time) : null
})

function chooseZoom(preset: ZoomPreset): void {
  const focus = selectedTime.value !== null && timeline.view && isWithin(timeline.view, selectedTime.value) ? selectedTime.value : undefined
  timeline.applyPreset(preset, focus)
}

function select(id: string): void {
  selectedId.value = id
  if (query.eventId !== null) query.openEvent(id)
}

function openEvent(id: string): void {
  selectedId.value = id
  query.openEvent(id)
}

function setRange(span: Span): void {
  query.setTimeRange(spanToQueryRange(span))
}

function navigate(navigation: Navigation): void {
  applyNavigation(timeline, navigation)
}

function clearFilters(): void {
  query.reset()
  timeline.fit()
}

watch(() => query.eventId, (id) => {
  if (id !== null) selectedId.value = id
})
watch(selectedTime, (time) => {
  if (time !== null) timeline.reveal(time)
})
watch(() => timeline.tableRange, (range) => events.setRangeOverride(range), { immediate: true })

onMounted(() => {
  timeline.activate()
  events.activate()
})
onBeforeUnmount(() => {
  timeline.deactivate()
  events.deactivate()
  events.clearRangeOverride()
})
</script>

<template>
  <section
    ref="root"
    class="timeline-tab"
    data-tab="timeline"
    :style="{ '--tab-fill-height': `${fillHeight}px`, '--canvas-height': `${CANVAS_HEIGHT}px`, '--min-body-height': `${MIN_BODY_HEIGHT}px` }"
  >
    <div class="timeline-tab__body">
      <div class="timeline-tab__toolbar">
        <div
          class="radio-group timeline-tab__zoom"
          role="radiogroup"
          aria-label="Zoom"
        >
          <template
            v-for="option in ZOOM_OPTIONS"
            :key="option.value"
          >
            <input
              :id="`timeline-zoom-${option.value}`"
              type="radio"
              class="radio-input"
              name="timeline-zoom"
              :value="option.value"
              :checked="timeline.preset === option.value"
              :disabled="!canZoom"
              @change="chooseZoom(option.value)"
            >
            <label
              :for="`timeline-zoom-${option.value}`"
              class="radio-label text-mono"
            >{{ option.label }}</label>
          </template>
        </div>
        <span
          class="timeline-tab__range text-mono text-gray"
          aria-live="polite"
        >{{ visibleRange }}</span>
      </div>

      <div class="timeline-tab__canvas">
        <ViewState
          :loading="timeline.status === 'loading'"
          :error="canvasError"
          :empty="timeline.status === 'empty'"
          empty-message="no events in this analysis"
          @retry="timeline.retry()"
        >
          <Timeline
            v-if="timeline.view && timeline.full"
            :view="timeline.view"
            :full="timeline.full"
            :data="timeline.data"
            :chip="timeline.chipSpan"
            :selected-id="selectedId"
            :selected-time="selectedTime"
            :loading="timeline.loading"
            :height="CANVAS_HEIGHT"
            @navigate="navigate"
            @open-event="openEvent"
            @select-range="setRange"
            @clear-range="query.clearTimeRange()"
          />
        </ViewState>
      </div>

      <EventTable
        class="timeline-tab__table"
        :events="events.events"
        :total="events.total"
        :loading="tableLoading"
        :loading-more="events.loadingMore"
        :has-more="events.hasMore"
        :sort="events.sort"
        :selected-id="selectedId"
        :filtered="tableFiltered"
        :error="events.error?.message"
        :load-more-error="events.loadMoreError"
        @select="select"
        @open="query.openEvent"
        @toggle-sort="events.toggleSort"
        @load-more="events.loadMore"
        @retry="events.retry"
        @clear="clearFilters"
      />
    </div>
    <EventDetailDrawer />
  </section>
</template>

<style scoped>
.timeline-tab {
  min-width: 0;
  padding: var(--spacing-sm) var(--spacing-lg);
}

.timeline-tab__body {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: var(--spacing-sm);
  height: max(var(--min-body-height), var(--tab-fill-height));
}

.timeline-tab__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-md);
  min-width: 0;
}

.timeline-tab__zoom .radio-label {
  padding: 2px var(--spacing-md);
  font-size: 0.75rem;
  letter-spacing: 1px;
}

.timeline-tab__range {
  flex: 1 1 0;
  min-width: 0;
  overflow: hidden;
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline-tab__canvas {
  min-width: 0;
  min-height: calc(var(--canvas-height) + 4px);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.timeline-tab__canvas :deep(.view-state),
.timeline-tab__canvas :deep(.terminal-empty) {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: var(--canvas-height);
}

/* The table is short here: its failure message and retry sit side by side so neither is cut off. */
.timeline-tab__table :deep(.view-state) {
  flex-direction: row;
  flex-wrap: wrap;
  justify-content: center;
  padding: var(--spacing-sm);
}

.timeline-tab__table :deep(.view-state p) {
  margin: 0;
}
</style>
