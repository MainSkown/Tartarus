<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisStatus } from '@/api'
import { analysisStatusMeta } from '@/services/analysis-status'

const props = defineProps<{ status: AnalysisStatus }>()

const meta = computed(() => analysisStatusMeta(props.status))
</script>

<template>
  <span
    class="status-badge text-mono"
    :class="`status-badge--${status}`"
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
