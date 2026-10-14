<script setup lang="ts">
import FilterChips from '@/components/FilterChips.vue'
import QueryBar from '@/components/QueryBar.vue'

defineProps<{ analysisId: number }>()
</script>

<template>
  <section
    class="query-header"
    aria-label="Query"
  >
    <QueryBar :analysis-id="analysisId" />
    <FilterChips />
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
