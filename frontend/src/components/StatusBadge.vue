<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisStatus, GuestState, Validity } from '@/api'
import { analysisStatusMeta } from '@/services/analysis-status'
import { buildPhaseMeta, type BuildPhase } from '@/services/guest-build'
import { guestStateMeta } from '@/services/guest-state'
import { validityMeta } from '@/services/rule-view'

// One badge look for all four: an analysis `status`, a rule's `validity`, a guest's state or a build's phase.
const props = defineProps<{ status?: AnalysisStatus; validity?: Validity; guestState?: GuestState; buildPhase?: BuildPhase }>()

const kind = computed(() => props.buildPhase ?? props.guestState ?? props.validity ?? props.status!)
const meta = computed(() => {
  if (props.buildPhase) return buildPhaseMeta(props.buildPhase)
  if (props.guestState) return guestStateMeta(props.guestState)
  return props.validity ? validityMeta(props.validity) : analysisStatusMeta(props.status!)
})
</script>

<template>
  <span
    class="status-badge text-mono"
    :class="`status-badge--${kind}`"
    :style="{ color: `var(${meta.color})` }"
  >
    <span
      v-if="meta.active"
      class="live-dot status-badge__dot"
      aria-hidden="true"
    />
    <q-icon
      :name="meta.icon"
      size="14px"
      aria-hidden="true"
    />
    <span class="status-badge__label">{{ meta.label }}</span>
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border: 1px solid currentColor;
  font-size: 0.75rem;
  letter-spacing: 1px;
  white-space: nowrap;
}

.status-badge__dot {
  flex: none;
}

@media (prefers-reduced-motion: reduce) {
  .status-badge__dot {
    animation: none;
  }
}
</style>
