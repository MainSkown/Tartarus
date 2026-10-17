<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AnalysisRead } from '@/api'
import LiveDesktopSlot from '@/components/LiveDesktopSlot.vue'
import LiveDetectionsPanel from '@/components/LiveDetectionsPanel.vue'
import LiveEndRunButton from '@/components/LiveEndRunButton.vue'
import LiveExtendButton from '@/components/LiveExtendButton.vue'
import LiveEventStream from '@/components/LiveEventStream.vue'
import LiveFinishedPanel from '@/components/LiveFinishedPanel.vue'
import LiveNotice from '@/components/LiveNotice.vue'
import LiveProcessTree from '@/components/LiveProcessTree.vue'
import LiveStatusBar from '@/components/LiveStatusBar.vue'
import { useEndRun } from '@/composables/use-end-run'
import { useExtendRun } from '@/composables/use-extend-run'
import { useLiveAnalysis } from '@/composables/use-live-analysis'
import { useViewportFill } from '@/composables/use-viewport-fill'
import { isTerminalStatus } from '@/services/analysis-status'
import { describeLiveError, processesEmptyMessage, streamEmptyMessage } from '@/services/live-state'

// The tab's own top and bottom padding (2 x spacing-sm), measured from the section top, so the page itself never scrolls.
const BOTTOM_GAP = 16

const props = defineProps<{ analysis: AnalysisRead }>()
const emit = defineEmits<{ 'open-tab': [tab: string] }>()

const live = useLiveAnalysis(props.analysis.id)

const root = ref<HTMLElement>()
const { height: fillHeight } = useViewportFill(root, BOTTOM_GAP)

const interactive = computed(() => props.analysis.options.interactive === true)
// The polled analysis can be ahead of a socket that is reconnecting, so a final status there wins.
const status = computed(() =>
  isTerminalStatus(props.analysis.status) ? props.analysis.status : (live.status.value?.status ?? props.analysis.status),
)
const endRun = useEndRun({
  analysisId: () => props.analysis.id,
  status: () => status.value,
  monitorUp: () => live.monitorStarted.value,
})
const extendRun = useExtendRun({
  analysisId: () => props.analysis.id,
  status: () => status.value,
  interactive: () => interactive.value,
  deadlineAt: () => props.analysis.deadline_at,
  startedAt: () => props.analysis.started_at,
})
const finished = computed(() => live.finished.value || isTerminalStatus(props.analysis.status))
// The guest stops when the run ends, a while before the analysis is done: its processes have ended.
const guestStopped = computed(() => finished.value || status.value === 'processing' || status.value === 'ingesting')
const selectedPid = computed(() => live.filter.value.pids[0])
const filtered = computed(() => live.filter.value.lanes.length > 0 || live.filter.value.pids.length > 0)
const queuePosition = computed(() => props.analysis.queue_position)
const total = computed(() => live.counts.value?.total ?? live.received.value)
const streamEmpty = computed(() =>
  streamEmptyMessage({
    status: status.value,
    processCount: live.processCount.value,
    queuePosition: queuePosition.value,
    filtered: filtered.value,
  }),
)

function selectProcess(pid: number | undefined): void {
  live.setFilter({ pids: pid === undefined ? [] : [pid] })
}
</script>

<template>
  <section
    ref="root"
    class="live-tab"
    :class="{ 'live-tab--desktop': interactive }"
    data-tab="live"
    :style="{ '--tab-fill-height': `${fillHeight}px` }"
  >
    <LiveStatusBar
      :status="status"
      :live="live.status.value"
      :connection="live.connection.value"
      :ended="finished"
      :interactive="interactive"
      :total="total"
      :listed="live.events.value.length"
      :events-per-minute="live.eventsPerMinute.value"
      :queue-position="queuePosition"
    >
      <template #actions>
        <LiveEndRunButton
          :phase="endRun.phase.value"
          :label="endRun.label.value"
          :title="endRun.title.value"
          @press="endRun.press"
        />
        <LiveExtendButton
          :visible="extendRun.visible.value"
          :disabled="extendRun.disabled.value"
          :title="extendRun.title.value"
          @press="extendRun.press"
        />
      </template>
    </LiveStatusBar>

    <div
      v-if="live.errors.value.length > 0 || live.notFound.value"
      class="live-tab__notices"
    >
      <LiveNotice
        v-if="live.notFound.value"
        level="warning"
      >
        the live stream does not know this analysis
      </LiveNotice>
      <LiveNotice
        v-for="error in live.errors.value"
        :key="error.code"
        level="warning"
      >
        {{ describeLiveError(error) }}
      </LiveNotice>
    </div>

    <div
      class="live-tab__top"
      :class="{ 'live-tab__top--desktop': interactive }"
    >
      <LiveDesktopSlot
        v-if="interactive"
        :analysis="analysis"
        :end-requested="endRun.requested.value"
      />
      <LiveProcessTree
        :roots="live.roots.value"
        :selected-pid="selectedPid"
        :empty-message="processesEmptyMessage({ status, queuePosition })"
        :run-over="guestStopped"
        @select="selectProcess"
      />
      <LiveFinishedPanel
        v-if="finished"
        :analysis-id="analysis.id"
        :status="status"
        @open-summary="emit('open-tab', 'summary')"
      />
      <LiveDetectionsPanel
        v-else
        :detections="live.detections.value"
      />
    </div>

    <LiveEventStream
      class="live-tab__stream"
      :events="live.events.value"
      :paused="live.paused.value"
      :backlog="live.backlog.value"
      :filter="live.filter.value"
      :dropped="live.dropped.value"
      :trimmed="live.trimmed.value"
      :empty-message="streamEmpty"
      @pause="live.pause"
      @resume="live.resume"
      @filter="live.setFilter"
    />
  </section>
</template>

<style scoped>
.live-tab {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
  height: max(26rem, var(--tab-fill-height));
  padding: var(--spacing-sm) var(--spacing-lg);
  box-sizing: border-box;
}

.live-tab__notices {
  display: flex;
  flex: none;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.live-tab__top {
  display: grid;
  flex: 6 1 0;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: var(--spacing-sm);
  min-height: 0;
}

.live-tab__top--desktop {
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr);
}

/* The guest screen is 16:10 and gets its size from the height it is given, so it takes the whole left column and the stream moves beside it. */
@media (min-width: 901px) {
  .live-tab--desktop {
    display: grid;
    grid-template-columns: minmax(0, 1.8fr) minmax(0, 1fr) minmax(0, 1fr);
    grid-template-rows: auto auto minmax(0, 1fr) minmax(0, 1fr);
    column-gap: var(--spacing-sm);
    row-gap: 0;
  }

  .live-tab--desktop > .live-tab__top {
    display: contents;
  }

  .live-tab--desktop > [data-live='status'],
  .live-tab--desktop > .live-tab__notices {
    grid-column: 1 / -1;
    margin-bottom: var(--spacing-sm);
  }

  .live-tab--desktop > [data-live='status'] {
    grid-row: 1;
  }

  .live-tab--desktop > .live-tab__notices {
    grid-row: 2;
  }

  .live-tab--desktop .live-tab__top > [data-live='desktop'] {
    grid-area: 3 / 1 / 5 / 2;
  }

  .live-tab--desktop .live-tab__top > [data-live='processes'] {
    grid-area: 3 / 2 / 4 / 3;
    margin-bottom: var(--spacing-sm);
  }

  .live-tab--desktop .live-tab__top > [data-live='detections'],
  .live-tab--desktop .live-tab__top > [data-live='finished'] {
    grid-area: 3 / 3 / 4 / 4;
    margin-bottom: var(--spacing-sm);
  }

  .live-tab--desktop > .live-tab__stream {
    grid-area: 4 / 2 / 5 / 4;
  }
}

.live-tab__stream {
  flex: 6 1 0;
}

@media (max-width: 900px) {
  .live-tab {
    height: auto;
  }

  .live-tab__top,
  .live-tab__top--desktop {
    flex: none;
    grid-template-columns: minmax(0, 1fr);
  }

  .live-tab__top > * {
    height: 14rem;
  }

  .live-tab__top > [data-live='detections'],
  .live-tab__top > [data-live='desktop'] {
    height: auto;
  }

  .live-tab__stream {
    flex: none;
    height: 24rem;
  }
}
</style>
