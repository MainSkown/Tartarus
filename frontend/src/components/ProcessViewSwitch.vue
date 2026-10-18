<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'

type Mode = 'graph' | 'tree'

defineProps<{ total: number }>()
const mode = defineModel<Mode>({ required: true })

const modeOptions = computed(() => [
  { label: t('analysis.processes.view.graph'), value: 'graph' },
  { label: t('analysis.processes.view.tree'), value: 'tree' },
])
</script>

<template>
  <div class="process-view-switch">
    <span class="process-view-switch__count text-mono text-gray">{{ t('analysis.processes.count', total) }}</span>
    <q-btn-toggle
      v-model="mode"
      :options="modeOptions"
      unelevated
      square
      no-caps
      class="process-view-switch__toggle text-mono"
      :aria-label="t('analysis.processes.view.label')"
    />
  </div>
</template>

<style scoped>
.process-view-switch {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-md);
  margin-left: auto;
}

.process-view-switch__count {
  font-size: 0.7rem;
  letter-spacing: 1px;
  white-space: nowrap;
}

.process-view-switch__toggle {
  border: 2px solid var(--border-primary);
}

.process-view-switch__toggle :deep(.q-btn) {
  min-height: 28px;
  padding: 0 var(--spacing-md);
  font-size: 0.75rem;
}
</style>
