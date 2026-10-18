<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisStatus } from '@/api'
import RunCountdown from '@/components/RunCountdown.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import type { LiveStatusSnapshot } from '@/composables/use-live-analysis'
import { useTickingSeconds, type Reading } from '@/composables/use-ticking-seconds'
import { t, type MessageKey } from '@/i18n'
import { shownDuration } from '@/services/countdown'
import { formatCount } from '@/services/format-number'
import type { WsConnectionState } from '@/services/ws'

const LINK_LABELS: Record<WsConnectionState, MessageKey> = {
  connecting: 'live.status.linkConnecting',
  open: 'live.status.linkConnected',
  reconnecting: 'live.status.linkReconnecting',
  closed: 'live.status.linkClosed',
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
  props.listed !== undefined && props.listed !== props.total ? t('live.status.shown', { count: formatCount(props.listed) }) : '',
)
const queued = computed(() => props.status === 'queued')
const link = computed(() => (props.ended ? t('live.status.streamEnded') : t(LINK_LABELS[props.connection])))
</script>

<template>
  <div
    class="live-status text-mono"
    data-live="status"
  >
    <span class="live-status__lead">
      <StatusBadge :status="status" />
      <slot name="after-status" />
    </span>

    <template v-if="queued">
      <span class="live-status__item text-gray">{{ queuePosition === null ? t('live.status.waiting') : t('live.status.queuePosition', { position: queuePosition }) }}</span>
    </template>
    <template v-else>
      <span
        class="live-status__item"
        data-field="elapsed"
      ><span class="live-status__label">{{ t('live.status.elapsed') }}</span> {{ shownDuration(elapsedS) }}</span>
      <span
        class="live-status__item"
        data-field="remaining"
      ><span class="live-status__label">{{ t('live.status.remaining') }}</span> <RunCountdown
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
    ><strong>{{ t('live.status.events', { count: formatCount(total) }, total) }}</strong>{{ shownLabel }} {{ t('live.status.rate', { count: formatCount(eventsPerMinute) }) }}</span>

    <span class="live-status__actions">
      <slot name="actions" />
    </span>
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

/* The badge and what sits beside it wrap as one group, so a button never parts from the state it belongs to. */
.live-status__lead {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: var(--spacing-sm);
}

.live-status__actions {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: var(--spacing-sm);
}
</style>
