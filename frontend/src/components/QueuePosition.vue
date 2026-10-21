<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { useQueueStore } from '@/stores/queue'

const props = defineProps<{ analysisId: number }>()

const queue = useQueueStore()

const label = computed<string | undefined>(() => {
  const entry = queue.queuedEntryOf(props.analysisId)
  if (!entry) return undefined
  return entry.guest
    ? t('dashboard.queue.forGuest', { position: entry.position, guest: entry.guest })
    : t('dashboard.queue.position', { position: entry.position })
})
</script>

<template>
  <span
    v-if="label"
    class="queue-position text-mono"
    :title="label"
  >{{ label }}</span>
</template>

<style scoped>
.queue-position {
  display: block;
  margin-top: var(--spacing-xs);
  color: var(--text-gray);
  font-size: 0.7rem;
  letter-spacing: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 14rem;
}
</style>
