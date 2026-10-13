<script setup lang="ts">
import { computed } from 'vue'
import type { Severity } from '@/api'
import { severityMeta } from '@/services/analysis-status'

const props = defineProps<{ severity: Severity; count?: number }>()

const meta = computed(() => severityMeta(props.severity))
</script>

<template>
  <q-badge
    outline
    class="severity-badge text-mono"
    :style="{ color: `var(${meta.color})` }"
  >
    <q-icon
      :name="meta.icon"
      size="14px"
      aria-hidden="true"
    />
    <span class="severity-badge__label">{{ meta.label }}</span>
    <span
      v-if="count !== undefined"
      class="severity-badge__count"
    >{{ count }}</span>
  </q-badge>
</template>

<style scoped>
.severity-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  letter-spacing: 1px;
  white-space: nowrap;
}

.severity-badge__count {
  font-weight: bold;
}
</style>
