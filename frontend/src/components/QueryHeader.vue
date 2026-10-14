<script setup lang="ts">
import { computed } from 'vue'
import FilterChips from '@/components/FilterChips.vue'
import QueryBar from '@/components/QueryBar.vue'
import { pidNamesOf } from '@/services/pid-names'
import { useEventsStore } from '@/stores/events'
import { useQueryStateStore } from '@/stores/query-state'

defineProps<{ analysisId: number }>()
const query = useQueryStateStore()
const events = useEventsStore()

// The names come from the events the table already lists, so a pid chip is named once they load and never waits for them.
const pidNames = computed(() => pidNamesOf(events.events, query.pids))
</script>

<template>
  <section
    class="query-header"
    aria-label="Query"
  >
    <QueryBar :analysis-id="analysisId" />
    <FilterChips :pid-names="pidNames" />
  </section>
</template>

<style scoped>
.query-header {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
  padding: var(--spacing-sm) var(--spacing-lg) 0;
}
</style>
