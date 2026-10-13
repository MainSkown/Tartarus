<script setup lang="ts">
import PaneHeading from '@/components/PaneHeading.vue'
</script>

<template>
  <section
    class="live-detections"
    data-live="detections"
  >
    <PaneHeading label="DETECTIONS" />
    <p class="live-detections__empty text-mono text-gray">
      &gt; none yet: CAPE signatures run after the analysis, and live rules arrive with Sigma
    </p>
  </section>
</template>

<style scoped>
.live-detections {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-xs) var(--spacing-sm) var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.live-detections__empty {
  margin: var(--spacing-sm) 0 0;
  font-size: 0.75rem;
  line-height: 1.5;
}
</style>
