<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { QVirtualScroll } from 'quasar'
import LaneIcon from '@/components/LaneIcon.vue'
import LiveNotice from '@/components/LiveNotice.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import { formatCount } from '@/services/format-number'
import { LANE_ORDER, laneMeta } from '@/services/lanes'
import type { LiveEvent } from '@/services/live-messages'
import type { LiveFilter } from '@/services/live-state'
import { processClock } from '@/services/process-graph'

const ROW_HEIGHT = 24
// Rows rendered at least, so a burst of events never shows blank rows before the list has re-measured.
const MIN_RENDERED_ROWS = 40
// The api lane has its own switch: it is the bulk of every run and must be asked for.
const CHIP_LANES = LANE_ORDER.filter((lane) => lane !== 'api')

const props = defineProps<{
  events: LiveEvent[]
  paused: boolean
  backlog: number
  filter: LiveFilter
  dropped: number
  trimmed: number
  emptyMessage: string
}>()
const emit = defineEmits<{ pause: []; resume: []; filter: [changes: Partial<LiveFilter>] }>()

const root = ref<HTMLElement>()
const scroller = ref<InstanceType<typeof QVirtualScroll>>()
const following = ref(true)

interface ScrollPosition {
  to: number
  direction: 'increase' | 'decrease'
}

function onScroll({ to, direction }: ScrollPosition): void {
  const atNewest = to >= props.events.length - 1
  if (direction === 'decrease' && !atNewest) following.value = false
  else if (direction === 'increase' && atNewest) following.value = true
}

// Rows have a fixed height, so the scrollable height is exact before the rows in view are rendered.
// QVirtualScroll.scrollTo does nothing on the first batch, while the list is still being measured.
function followNewest(): void {
  const list = scroller.value?.$el as HTMLElement | undefined
  if (following.value && list) list.scrollTop = list.scrollHeight
}

function toggleLane(lane: string): void {
  const chosen = props.filter.lanes
  emit('filter', { lanes: chosen.includes(lane) ? chosen.filter((known) => known !== lane) : [...chosen, lane] })
}

function setIncludeApi(event: Event): void {
  emit('filter', { includeApi: (event.target as HTMLInputElement).checked })
}

const plural = (count: number, noun: string): string => `${formatCount(count)} ${noun}${count === 1 ? '' : 's'}`

// A notice appearing above the list or the window resizing moves the end of the list away from the viewport.
let resizeObserver: ResizeObserver | undefined

watch(() => props.events.length, followNewest, { flush: 'post' })
onMounted(() => {
  followNewest()
  if (typeof ResizeObserver === 'undefined' || !root.value) return
  resizeObserver = new ResizeObserver(followNewest)
  resizeObserver.observe(root.value)
})
onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<template>
  <section
    ref="root"
    class="live-stream"
    data-live="stream"
  >
    <div class="live-stream__bar">
      <PaneHeading
        class="live-stream__title"
        label="EVENT STREAM"
      />
      <div
        class="live-stream__lanes"
        role="group"
        aria-label="Lanes"
      >
        <button
          v-for="lane in CHIP_LANES"
          :key="lane"
          type="button"
          class="live-stream__lane button text-mono"
          :class="{ 'is-active': filter.lanes.includes(lane) }"
          :aria-pressed="filter.lanes.includes(lane)"
          @click="toggleLane(lane)"
        >
          <LaneIcon :lane="lane" /><span class="live-stream__lane-label">{{ laneMeta(lane).label }}</span>
        </button>
      </div>
      <label class="live-stream__api text-mono">
        <input
          type="checkbox"
          class="checkbox-input"
          :checked="filter.includeApi"
          @change="setIncludeApi"
        >
        SHOW API CALLS
      </label>
      <span class="live-stream__spacer" />
      <button
        type="button"
        class="live-stream__follow button text-mono"
        :class="{ 'is-active': following }"
        :aria-pressed="following"
        @click="following = !following"
      >
        FOLLOW
      </button>
      <button
        type="button"
        class="live-stream__pause button text-mono"
        :class="{ 'is-active': paused }"
        @click="paused ? emit('resume') : emit('pause')"
      >
        <q-icon
          :name="paused ? 'play_arrow' : 'pause'"
          size="14px"
          aria-hidden="true"
        />{{ paused ? 'RESUME' : 'PAUSE' }}<span
          v-if="paused && backlog > 0"
          class="live-stream__backlog"
        >+{{ formatCount(backlog) }} new</span>
      </button>
    </div>

    <LiveNotice
      v-if="dropped > 0"
      class="live-stream__skipped"
      level="warning"
    >
      <span title="the events table arrives with M3">{{ plural(dropped, 'event') }} skipped by the server, open table</span>
    </LiveNotice>
    <LiveNotice
      v-if="trimmed > 0"
      class="live-stream__trimmed"
    >
      {{ plural(trimmed, 'older event') }} trimmed
    </LiveNotice>

    <q-virtual-scroll
      v-if="events.length > 0"
      ref="scroller"
      class="live-stream__list"
      :items="events"
      :virtual-scroll-item-size="ROW_HEIGHT"
      :virtual-scroll-slice-size="MIN_RENDERED_ROWS"
      @virtual-scroll="onScroll"
    >
      <template #default="{ item, index }">
        <div
          :key="index"
          class="live-event text-mono"
          :data-event-id="item.event.id"
        >
          <span class="live-event__time text-gray">{{ processClock(item['@timestamp']) }}</span>
          <span class="live-event__lane-cell">
            <LaneIcon :lane="item.tartarus.lane" />
            <span class="live-event__lane">{{ laneMeta(item.tartarus.lane).label }}</span>
          </span>
          <ProcessChip
            class="live-event__process"
            :process="item.process?.pid === undefined ? null : { pid: item.process.pid, name: item.process.name ?? null }"
          />
          <span
            class="live-event__summary"
            :title="item.tartarus.summary"
          >{{ item.tartarus.summary }}</span>
        </div>
      </template>
    </q-virtual-scroll>
    <p
      v-else
      class="live-stream__empty text-mono text-gray"
    >
      &gt; {{ emptyMessage }}
    </p>
  </section>
</template>

<style scoped>
.live-stream {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-xs) var(--spacing-sm) var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.live-stream__bar {
  display: flex;
  flex: none;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-sm);
  padding-bottom: var(--spacing-xs);
  border-bottom: 2px solid var(--border-primary);
}

.live-stream__title {
  margin: 0;
  padding: 0;
  border-bottom: none;
  white-space: nowrap;
}

.live-stream__lanes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
}

.live-stream__spacer {
  flex: 1 1 0;
}

.live-stream__lane,
.live-stream__follow,
.live-stream__pause {
  gap: var(--spacing-xs);
  min-height: 24px;
  padding: 0 var(--spacing-sm);
  border: 1px solid var(--border-primary);
  font-size: 0.65rem;
  letter-spacing: 1px;
  white-space: nowrap;
}

.live-stream__lane.is-active:hover,
.live-stream__follow.is-active:hover,
.live-stream__pause.is-active:hover {
  color: var(--text-white);
}

.live-stream__backlog {
  margin-left: var(--spacing-xs);
  color: var(--blue-lighter);
  font-weight: bold;
}

.live-stream__api {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  color: var(--text-gray);
  font-size: 0.65rem;
  letter-spacing: 1px;
  white-space: nowrap;
  cursor: pointer;
}

.live-stream__list {
  flex: 1 1 0;
  min-height: 0;
}

.live-stream__empty {
  margin: var(--spacing-sm) 0 0;
  font-size: 0.75rem;
}

.live-event {
  display: grid;
  grid-template-columns: 6.5rem 6.5rem minmax(0, 22ch) minmax(0, 1fr);
  align-items: center;
  gap: var(--spacing-sm);
  height: 24px;
  font-size: 0.75rem;
  white-space: nowrap;
}

.live-event__lane-cell {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  min-width: 0;
  font-size: 0.65rem;
  letter-spacing: 1px;
}

.live-event__summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* The summary names the process, so the narrow row gives its room to the summary. */
@media (max-width: 700px) {
  .live-event {
    grid-template-columns: 5.6rem 5.4rem minmax(0, 1fr);
    gap: var(--spacing-xs);
  }

  .live-event__process {
    display: none;
  }
}
</style>
