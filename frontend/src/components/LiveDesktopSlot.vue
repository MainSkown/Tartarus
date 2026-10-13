<script setup lang="ts">
import type { AnalysisRead } from '@/api'
import PaneHeading from '@/components/PaneHeading.vue'

defineProps<{ analysis: AnalysisRead }>()
</script>

<template>
  <section
    class="live-desktop"
    data-live="desktop"
  >
    <PaneHeading label="DESKTOP" />
    <p class="live-desktop__note text-mono text-gray">
      &gt; desktop panel arrives in the next step
    </p>
  </section>
</template>

<style scoped>
.live-desktop {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-xs) var(--spacing-sm) var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.live-desktop__note {
  margin: var(--spacing-sm) 0 0;
  font-size: 0.75rem;
}
</style>
