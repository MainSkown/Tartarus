<script setup lang="ts">
import { computed } from 'vue'
import { ANALYSIS_TABS, selectableTab } from '@/services/analysis-tabs'

const props = defineProps<{ active: string }>()
const emit = defineEmits<{ select: [tab: string] }>()

const selected = computed(() => selectableTab(props.active))
</script>

<template>
  <nav
    class="analysis-tabs"
    role="tablist"
    aria-label="Analysis views"
  >
    <button
      v-for="tab in ANALYSIS_TABS"
      :key="tab.key"
      type="button"
      role="tab"
      class="analysis-tabs__tab text-mono"
      :aria-selected="tab.key === selected"
      :disabled="!tab.available"
      :title="tab.available ? undefined : 'Arrives with M1b'"
      @click="emit('select', tab.key)"
    >
      {{ tab.label }}
    </button>
  </nav>
</template>

<style scoped>
.analysis-tabs {
  display: flex;
  flex-wrap: wrap;
  border-bottom: 2px solid var(--border-primary);
}

.analysis-tabs__tab {
  padding: var(--spacing-sm) var(--spacing-md);
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  background: transparent;
  color: var(--text-gray);
  font-size: 0.8rem;
  letter-spacing: 1px;
  cursor: pointer;
  transition: color var(--transition-fast), background-color var(--transition-fast);
}

.analysis-tabs__tab:hover:not(:disabled) {
  background: var(--hover-bg);
  color: var(--blue-hover);
}

.analysis-tabs__tab[aria-selected='true'] {
  border-bottom-color: var(--blue-primary);
  color: var(--blue-primary);
}

.analysis-tabs__tab:disabled {
  color: var(--text-gray-darker);
  cursor: not-allowed;
}
</style>
