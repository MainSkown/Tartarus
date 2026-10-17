<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisStatus } from '@/api'
import RunCountdown from '@/components/RunCountdown.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import type { LiveStatusSnapshot } from '@/composables/use-live-analysis'
import { useTickingSeconds, type Reading } from '@/composables/use-ticking-seconds'
import { shownDuration } from '@/services/countdown'
import { formatCount } from '@/services/format-number'
import type { WsConnectionState } from '@/services/ws'

const LINK_LABELS: Record<WsConnectionState, string> = {
  connecting: 'CONNECTING',
  open: 'CONNECTED',
  reconnecting: 'RECONNECTING',
  closed: 'CLOSED',
}

const props = defineProps<{
  status: AnalysisStatus
  live?: LiveStatusSnapshot
  connection: WsConnectionState
  ended: boolean
  interactive?: boolean
  total: number
  /** How many events the stream lists; fewer than `total` while a lane is hidden or the buffer is full. */
  listed?: number
  eventsPerMinute: number
  queuePosition: number | null
}>()

const counting = computed(() => props.status === 'running' && props.live !== undefined)
const readingOf = (field: 'elapsed_s' | 'remaining_s'): Reading | undefined =>
  props.live && { seconds: props.live[field], receivedAt: props.live.receivedAt }
const elapsedS = useTickingSeconds(() => readingOf('elapsed_s'), { direction: 1, counting: () => counting.value })
const remainingS = useTickingSeconds(() => readingOf('remaining_s'), { direction: -1, counting: () => counting.value })
const shownLabel = computed(() =>
  props.listed !== undefined && props.listed !== props.total ? ` (${formatCount(props.listed)} shown)` : '',
)
const queued = computed(() => props.status === 'queued')
const link = computed(() => (props.ended ? 'STREAM ENDED' : LINK_LABELS[props.connection]))
</script>

<template>
  <div
    class="live-status text-mono"
    data-live="status"
  >
    <StatusBadge :status="status" />

    <template v-if="queued">
      <span class="live-status__item text-gray">{{ queuePosition === null ? 'waiting for the guest' : `position ${queuePosition} in the queue` }}</span>
    </template>
    <template v-else>
      <span
        class="live-status__item"
        data-field="elapsed"
      ><span class="live-status__label">ELAPSED</span> {{ shownDuration(elapsedS) }}</span>
      <span
        class="live-status__item"
        data-field="remaining"
      ><span class="live-status__label">REMAINING</span> <RunCountdown
        :seconds="remainingS"
        :interactive="interactive"
        :running="status === 'running'"
      /></span>
    </template>

    <span
      class="live-status__item live-status__link"
      :class="`live-status__link--${ended ? 'ended' : connection}`"
      data-field="link"
    ><span
      class="live-status__dot"
      aria-hidden="true"
    />{{ link }}</span>

    <span
      class="live-status__item live-status__events"
      data-field="events"
    ><strong>{{ formatCount(total) }} events</strong>{{ shownLabel }} · {{ formatCount(eventsPerMinute) }}/min</span>

    <slot name="actions" />
  </div>
</template>

<style scoped>
.live-status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-lg);
  min-width: 0;
  padding: var(--spacing-xs) var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
  font-size: 0.8rem;
}

.live-status__item {
  white-space: nowrap;
}

.live-status__label {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.live-status__link {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  font-size: 0.7rem;
  letter-spacing: 1px;
}

.live-status__dot {
  width: 8px;
  height: 8px;
  background: var(--text-gray-dark);
}

.live-status__link--open .live-status__dot {
  background: var(--status-success);
}

.live-status__link--connecting .live-status__dot,
.live-status__link--reconnecting .live-status__dot {
  background: var(--status-medium);
}

.live-status__link--reconnecting {
  color: var(--status-medium);
}

.live-status__events {
  margin-left: auto;
}
</style>
