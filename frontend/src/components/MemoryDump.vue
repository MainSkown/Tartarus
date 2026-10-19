<script setup lang="ts">
import { computed } from 'vue'
import type { Artifact, MemorySummary } from '@/api'
import ArtifactTable from '@/components/ArtifactTable.vue'
import ViewState from '@/components/ViewState.vue'
import { t } from '@/i18n'
import { dumpFileStatus, dumpStatusText } from '@/services/memory-status'

const props = defineProps<{
  analysisId: number
  memory: MemorySummary | null
  dump: Artifact | null
  loading: boolean
  error?: string
}>()
const emit = defineEmits<{ retry: [] }>()

const submitOption = computed(() => t('submit.memory.label'))
const deleted = computed(() => props.memory?.dump_deleted === true)
const notTaken = computed(() => props.memory !== null && !props.memory.dump_taken)
const deleteFailed = computed(() => props.memory?.dump_deleted === false)
// A dump the summary says is gone needs no artifact to say so, and neither does one that was never taken.
const needsArtifacts = computed(() => !deleted.value && !notTaken.value)
const requested = computed(() => props.memory !== null || props.dump !== null)
const file = computed(() => (props.memory ? dumpFileStatus(props.memory) : null))
</script>

<template>
  <div class="memory-dump">
    <ViewState
      :loading="needsArtifacts && loading"
      :error="needsArtifacts ? error : undefined"
      @retry="emit('retry')"
    >
      <template v-if="notTaken">
        <p class="memory-dump__line text-mono text-gray">
          {{ t('artifacts.memory.dump.notTaken') }}
        </p>
      </template>
      <template v-else-if="!requested">
        <p class="memory-dump__line text-mono text-gray">
          &gt; {{ t('artifacts.memory.dump.none') }}
        </p>
        <p class="memory-dump__hint text-mono text-gray">
          {{ t('artifacts.memory.dump.noneHint', { option: submitOption }) }}
        </p>
      </template>
      <template v-else>
        <p
          v-if="memory && file"
          class="memory-dump__status text-mono"
        >
          <span>{{ dumpStatusText(memory) }}</span>
          <span :class="{ 'memory-dump__status--warn': file.warn }">{{ file.text }}</span>
        </p>
        <template v-if="deleted">
          <p class="memory-dump__line text-mono">
            {{ t('artifacts.memory.dump.deleted') }}
          </p>
          <p class="memory-dump__hint text-mono text-gray">
            {{ t('artifacts.memory.dump.deletedHint', { option: submitOption }) }}
          </p>
        </template>
        <p
          v-else-if="deleteFailed"
          class="memory-dump__line memory-dump__line--warn text-mono"
        >
          {{ t('artifacts.memory.dump.deleteFailed') }}
        </p>
        <ArtifactTable
          v-if="dump"
          :analysis-id="analysisId"
          :artifacts="[dump]"
        />
        <p
          v-else-if="!deleted"
          class="memory-dump__line text-mono text-gray"
        >
          {{ t('artifacts.memory.dump.gone') }}
        </p>
      </template>
    </ViewState>
  </div>
</template>

<style scoped>
.memory-dump__status {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs) 0;
  margin: 0 0 var(--spacing-sm);
  font-size: 0.8rem;
}

.memory-dump__status > span + span {
  margin-left: var(--spacing-sm);
  padding-left: var(--spacing-sm);
  border-left: 1px solid var(--border-secondary);
}

.memory-dump__status--warn,
.memory-dump__line--warn {
  color: var(--status-high);
}

.memory-dump__line,
.memory-dump__hint {
  margin: 0 0 var(--spacing-xs);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.memory-dump__hint {
  font-size: 0.75rem;
}
</style>
