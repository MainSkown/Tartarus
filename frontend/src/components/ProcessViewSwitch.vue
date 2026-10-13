<script setup lang="ts">
type Mode = 'graph' | 'tree'

const MODES = [
  { label: 'GRAPH', value: 'graph' },
  { label: 'TREE', value: 'tree' },
]

defineProps<{ total: number }>()
const mode = defineModel<Mode>({ required: true })
</script>

<template>
  <div class="process-view-switch">
    <span class="process-view-switch__count text-mono text-gray">{{ total }} {{ total === 1 ? 'process' : 'processes' }}</span>
    <q-btn-toggle
      v-model="mode"
      :options="MODES"
      unelevated
      square
      no-caps
      class="process-view-switch__toggle text-mono"
      aria-label="Process view"
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
