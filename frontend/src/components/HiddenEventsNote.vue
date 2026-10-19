<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { formatCount } from '@/services/format-number'
import { hiddenEventBreakdown, hiddenEventsTotal } from '@/services/hidden-events'

const props = defineProps<{ counts: Record<string, number> | undefined }>()

const total = computed(() => hiddenEventsTotal(props.counts))
const reasons = computed(() => hiddenEventBreakdown(props.counts))
</script>

<template>
  <p
    v-if="total > 0"
    class="hidden-events text-mono text-gray"
    tabindex="0"
  >
    {{ t('analysis.summary.hiddenEvents.note', { total: formatCount(total) }, total) }}
    <q-tooltip>
      <ul
        class="hidden-events__reasons"
        :aria-label="t('analysis.summary.hiddenEvents.reasonsLabel')"
      >
        <li
          v-for="reason in reasons"
          :key="reason.label"
        >
          <span>{{ reason.label }}</span>
          <span class="hidden-events__count">{{ formatCount(reason.count) }}</span>
        </li>
      </ul>
    </q-tooltip>
  </p>
</template>

<style scoped>
.hidden-events {
  width: fit-content;
  max-width: 100%;
  margin: var(--spacing-sm) 0 0;
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.hidden-events__reasons {
  margin: 0;
  padding: 0;
  list-style: none;
}

.hidden-events__reasons li {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.hidden-events__count {
  font-weight: bold;
}
</style>
