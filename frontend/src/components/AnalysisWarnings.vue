<script setup lang="ts">
import LiveNotice from '@/components/LiveNotice.vue'
import { t } from '@/i18n'

defineProps<{ warnings: string[] | undefined }>()
</script>

<template>
  <ul
    v-if="warnings && warnings.length > 0"
    class="analysis-warnings"
    :aria-label="t('analysis.warnings.label')"
  >
    <li
      v-for="warning in warnings"
      :key="warning"
    >
      <LiveNotice level="warning">
        {{ warning }}
      </LiveNotice>
    </li>
  </ul>
</template>

<style scoped>
.analysis-warnings {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  margin: 0 0 var(--spacing-md);
  padding: 0;
  list-style: none;
  /* A long reason must not push the Events table off the screen: the list scrolls on its own. */
  max-height: 25vh;
  overflow-y: auto;
}
</style>
