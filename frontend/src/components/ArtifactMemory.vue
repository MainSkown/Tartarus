<script setup lang="ts">
import { computed, watch } from 'vue'
import type { Artifact, MemorySummary } from '@/api'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import MemoryDump from '@/components/MemoryDump.vue'
import MemoryFindingGroup from '@/components/MemoryFindingGroup.vue'
import ViewState from '@/components/ViewState.vue'
import { useMemoryFindings } from '@/composables/use-memory-findings'
import { t } from '@/i18n'
import { groupFindings } from '@/services/memory-findings'
import { findingsStatusText } from '@/services/memory-status'

const SKELETON_ROWS = 4

const props = defineProps<{
  analysisId: number
  memory: MemorySummary | null
  dump: Artifact | null
  artifactsLoading: boolean
  artifactsError?: string
}>()
const emit = defineEmits<{ counted: [count: number | undefined]; 'retry-artifacts': [] }>()

const readable = computed(() => props.memory?.findings === 'ok')
const { findings, total, truncated, counted, loading, error, reload } = useMemoryFindings(
  () => props.analysisId,
  () => readable.value,
)

const groups = computed(() => groupFindings(findings.value))
const dumpStillThere = computed(() => props.dump?.downloadable === true)

watch(counted, (count) => emit('counted', count), { immediate: true })
</script>

<template>
  <div class="artifact-memory">
    <section class="memory-section">
      <h3 class="memory-heading text-mono">
        {{ t('artifacts.memory.dump.heading') }}
      </h3>
      <MemoryDump
        :analysis-id="analysisId"
        :memory="memory"
        :dump="dump"
        :loading="artifactsLoading"
        :error="artifactsError"
        @retry="emit('retry-artifacts')"
      />
    </section>

    <section
      v-if="memory"
      class="memory-section memory-findings"
    >
      <h3 class="memory-heading text-mono">
        {{ t('artifacts.memory.findings.heading') }}
      </h3>

      <template v-if="!readable">
        <p
          class="memory-findings__status text-mono"
          :class="memory.findings === 'failed' ? 'memory-findings__status--bad' : 'memory-findings__status--warn'"
        >
          {{ findingsStatusText(memory) }}
        </p>
        <p
          v-if="memory.error"
          class="memory-findings__error text-mono text-gray"
        >
          {{ memory.error }}
        </p>
        <p
          v-if="dumpStillThere"
          class="memory-findings__hint text-mono text-gray"
        >
          {{ t('artifacts.memory.findings.dumpStillThere') }}
        </p>
      </template>

      <div
        v-else-if="loading"
        class="memory-findings__skeleton"
        aria-busy="true"
        :aria-label="t('artifacts.memory.findings.loading')"
      >
        <span
          v-for="row in SKELETON_ROWS"
          :key="row"
          class="skeleton"
        />
      </div>
      <ViewState
        v-else-if="error"
        :error="error"
        @retry="reload"
      />
      <template v-else>
        <p
          v-if="memory.error"
          class="memory-findings__note memory-findings__note--warn text-mono"
        >
          {{ t('artifacts.memory.findings.partial', { error: memory.error }) }}
        </p>
        <p
          v-if="truncated"
          class="memory-findings__note text-mono text-gray"
        >
          {{ t('artifacts.memory.findings.truncated', { shown: findings.length, total }) }}
          <FilterEventsButton :target="{ chips: [{ field: 'event.module', value: 'volatility' }] }" />
        </p>
        <MemoryFindingGroup
          v-for="group in groups"
          :key="group.plugin"
          :analysis-id="analysisId"
          :group="group"
        />
        <template v-if="groups.length === 0">
          <p class="memory-findings__status text-mono">
            &gt; {{ t('artifacts.memory.findings.none') }}
          </p>
          <p class="memory-findings__hint text-mono text-gray">
            {{ t('artifacts.memory.findings.noneHint') }}
          </p>
        </template>
      </template>
    </section>
  </div>
</template>

<style scoped>
.artifact-memory {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  min-width: 0;
}

.memory-section {
  min-width: 0;
}

.memory-heading {
  margin: 0 0 var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.75rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.memory-findings__status,
.memory-findings__error,
.memory-findings__hint,
.memory-findings__note {
  margin: 0 0 var(--spacing-xs);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.memory-findings__hint {
  font-size: 0.75rem;
}

.memory-findings__note {
  margin-bottom: var(--spacing-sm);
}

.memory-findings__status--warn,
.memory-findings__note--warn {
  color: var(--status-high);
}

.memory-findings__status--bad {
  color: var(--status-critical);
}

.memory-findings__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  padding: var(--spacing-md);
  border: 2px solid var(--border-primary);
}

.memory-findings__skeleton .skeleton {
  height: 14px;
}

.memory-findings__skeleton .skeleton:nth-child(2n) {
  width: 85%;
}

.memory-findings__skeleton .skeleton:nth-child(3n) {
  width: 65%;
}
</style>
