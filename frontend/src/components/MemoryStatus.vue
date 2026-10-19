<script setup lang="ts">
import { computed } from 'vue'
import type { MemorySummary } from '@/api'
import { t } from '@/i18n'
import { dumpFileStatus, dumpStatusText, findingsStatusText } from '@/services/memory-status'

const props = defineProps<{ memory: MemorySummary; findingCount?: number | null }>()

const dump = computed(() => dumpStatusText(props.memory))
const findings = computed(() => findingsStatusText(props.memory, props.findingCount))
const dumpFile = computed(() => dumpFileStatus(props.memory))
</script>

<template>
  <dl class="memory-status">
    <dt class="text-mono">
      {{ t('analysis.summary.memory.dump') }}
    </dt>
    <dd class="text-mono">
      {{ dump }}
    </dd>
    <dt class="text-mono">
      {{ t('analysis.summary.memory.findings') }}
    </dt>
    <dd class="text-mono">
      <span :class="{ 'memory-status__bad': memory.findings === 'failed', 'memory-status__warn': memory.findings === 'unavailable' }">{{ findings }}</span>
      <span
        v-if="memory.error"
        class="memory-status__error text-gray"
      >{{ memory.error }}</span>
    </dd>
    <template v-if="dumpFile">
      <dt class="text-mono">
        {{ t('analysis.summary.memory.dumpFile') }}
      </dt>
      <dd
        class="text-mono"
        :class="{ 'memory-status__warn': dumpFile.warn }"
      >
        {{ dumpFile.text }}
      </dd>
    </template>
  </dl>
</template>

<style scoped>
.memory-status {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: baseline;
  gap: var(--spacing-xs) var(--spacing-lg);
  margin: 0;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--border-primary);
  background: var(--card-bg);
}

.memory-status dt {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.memory-status dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
}

.memory-status__error {
  display: block;
  font-size: 0.85rem;
}

.memory-status__bad {
  color: var(--status-critical);
}

.memory-status__warn {
  color: var(--status-high);
}
</style>
