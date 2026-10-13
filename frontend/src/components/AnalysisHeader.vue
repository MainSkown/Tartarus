<script setup lang="ts">
import { computed } from 'vue'
import { copyToClipboard, Notify } from 'quasar'
import type { AnalysisRead } from '@/api'
import StatusBadge from '@/components/StatusBadge.vue'
import { isActiveStatus } from '@/services/analysis-status'
import { formatDuration, formatUtcTimestamp, secondsBetween } from '@/services/format-duration'

const props = defineProps<{ analysis: AnalysisRead; busy: boolean }>()
const emit = defineEmits<{ cancel: []; delete: [] }>()

const FAILURE_TITLES: Partial<Record<AnalysisRead['status'], string>> = {
  failed: 'ANALYSIS FAILED',
  report_failed: 'REPORT FAILED',
}

const canCancel = computed(() => props.analysis.status === 'queued')
// CAPE cannot delete a task that is still being analysed, so the backend answers 409 for these.
const canDelete = computed(() => !isActiveStatus(props.analysis.status))
const failureTitle = computed(() => FAILURE_TITLES[props.analysis.status])
const duration = computed(() => {
  const { started_at, finished_at } = props.analysis
  return started_at && finished_at ? formatDuration(secondsBetween(started_at, finished_at)) : undefined
})

async function copyHash(): Promise<void> {
  await copyToClipboard(props.analysis.sample_sha256)
  Notify.create({ type: 'tt-success', message: 'SHA-256 copied' })
}
</script>

<template>
  <header class="analysis-header">
    <div class="analysis-header__title">
      <span class="analysis-header__id text-mono">#{{ analysis.id }}</span>
      <h1
        class="analysis-header__filename text-mono"
        :title="analysis.filename"
      >
        {{ analysis.filename }}
      </h1>
      <StatusBadge :status="analysis.status" />
      <span class="analysis-header__spacer" />
      <q-btn
        v-if="canCancel"
        outline
        square
        label="[CANCEL]"
        class="analysis-header__cancel text-mono"
        :disable="busy"
        @click="emit('cancel')"
      />
      <q-btn
        v-if="canDelete"
        outline
        square
        label="[DELETE]"
        class="analysis-header__delete text-mono"
        :disable="busy"
        @click="emit('delete')"
      />
    </div>

    <div class="analysis-header__hash-row">
      <span class="analysis-header__label text-mono">SHA-256</span>
      <code
        class="analysis-header__hash text-mono"
        :title="analysis.sample_sha256"
      >{{ analysis.sample_sha256 }}</code>
      <button
        type="button"
        class="analysis-header__copy"
        aria-label="Copy SHA-256"
        @click="copyHash"
      >
        <q-icon
          name="content_copy"
          size="14px"
        />
      </button>
    </div>

    <dl class="analysis-header__timing text-mono">
      <div>
        <dt>SUBMITTED</dt>
        <dd>{{ formatUtcTimestamp(analysis.submitted_at) }}</dd>
      </div>
      <div
        v-if="analysis.started_at"
        class="analysis-header__started"
      >
        <dt>STARTED</dt>
        <dd>{{ formatUtcTimestamp(analysis.started_at) }}</dd>
      </div>
      <div
        v-if="duration"
        class="analysis-header__duration"
      >
        <dt>DURATION</dt>
        <dd>{{ duration }}</dd>
      </div>
    </dl>

    <div
      v-if="failureTitle"
      class="analysis-header__banner"
      role="alert"
    >
      <strong class="text-mono">{{ failureTitle }}</strong>
      <span>{{ analysis.error ?? 'The analysis ended with no error message.' }}</span>
    </div>
  </header>
</template>

<style scoped>
.analysis-header {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  padding: var(--spacing-md) var(--spacing-lg);
}

.analysis-header__title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--spacing-md);
}

.analysis-header__id {
  color: var(--text-gray);
}

.analysis-header__filename {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  margin: 0;
  overflow: hidden;
  font-size: 1.1rem;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.analysis-header__spacer {
  flex: 1;
}

.analysis-header__cancel {
  color: var(--blue-primary);
}

.analysis-header__delete {
  color: var(--status-critical);
}

.analysis-header__hash-row {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-sm);
}

.analysis-header__label {
  flex: none;
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.analysis-header__hash {
  min-width: 0;
  color: var(--text-gray);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.analysis-header__copy {
  flex: none;
  padding: 2px;
  border: none;
  background: transparent;
  color: var(--text-gray);
  cursor: pointer;
}

.analysis-header__copy:hover {
  color: var(--blue-hover);
}

.analysis-header__timing {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs) var(--spacing-lg);
  margin: 0;
  font-size: 0.8rem;
}

.analysis-header__timing dt {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.analysis-header__timing dd {
  margin: 0;
  color: var(--text-gray-light);
}

.analysis-header__banner {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--status-critical);
  background: var(--critical-dark);
  box-shadow: var(--shadow-critical);
  overflow-wrap: anywhere;
}

.analysis-header__banner strong {
  color: var(--status-critical);
  font-size: 0.75rem;
  letter-spacing: 1px;
}
</style>
