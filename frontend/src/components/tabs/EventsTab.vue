<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisRead } from '@/api'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { useQueryStateStore } from '@/stores/query-state'

defineProps<{ analysis: AnalysisRead }>()

const store = useQueryStateStore()
const filterJson = computed(() => JSON.stringify(store.searchFilter, null, 2))
</script>

<template>
  <section data-tab="events">
    <TerminalEmpty message="the events table is built next" />
    <pre class="code-block events-filter">{{ filterJson }}</pre>
  </section>
</template>

<style scoped>
section {
  min-width: 0;
  padding: var(--spacing-sm) var(--spacing-lg);
}

.events-filter {
  max-height: 14rem;
  margin: 0;
  overflow: auto;
}
</style>
