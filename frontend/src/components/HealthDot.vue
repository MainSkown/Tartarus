<script setup lang="ts">
import { computed } from 'vue'
import type { HealthStatus } from '@/api'

export interface HealthSubStatus {
  label: string
  status: HealthStatus
  message?: string | null
}

const props = defineProps<{
  label: string
  status: HealthStatus
  message?: string | null
  subStatuses?: HealthSubStatus[]
}>()

const STATUS_CLASS: Record<HealthStatus, string> = {
  ok: 'health-dot--ok',
  degraded: 'health-dot--degraded',
  down: 'health-dot--down',
}

function describe(status: HealthStatus, message?: string | null): string {
  return message ? `${status} — ${message}` : status
}

// The combined "Store" dot has no message of its own (see system store's storeStatus): its
// tooltip lists Postgres and OpenSearch individually instead, per the gui spec scope note.
const description = computed(() => {
  if (props.subStatuses && props.subStatuses.length > 0) {
    return props.subStatuses.map((sub) => `${sub.label}: ${describe(sub.status, sub.message)}`).join(' · ')
  }
  return describe(props.status, props.message)
})
</script>

<template>
  <span
    class="health-dot text-mono"
    :class="STATUS_CLASS[status]"
    role="status"
    :aria-label="`${label}: ${description}`"
  >
    <span class="health-dot__mark">●</span>
    <span class="health-dot__label">{{ label }}</span>
    <!-- aria-label above carries the same text for assistive tech and tests; this tooltip
         is the sighted-hover presentation of it. -->
    <q-tooltip>{{ description }}</q-tooltip>
  </span>
</template>

<style scoped>
.health-dot {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  letter-spacing: 1px;
  cursor: default;
}

.health-dot--ok .health-dot__mark {
  color: var(--status-success);
}

.health-dot--degraded .health-dot__mark {
  color: var(--status-medium);
}

.health-dot--down .health-dot__mark {
  color: var(--status-critical);
}

.health-dot__label {
  color: var(--text-gray);
  text-transform: uppercase;
}
</style>
