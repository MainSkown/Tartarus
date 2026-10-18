<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisRead } from '@/api'
import CopyButton from '@/components/CopyButton.vue'
import ExportMenu from '@/components/ExportMenu.vue'
import GuestChip from '@/components/GuestChip.vue'
import RunCountdown from '@/components/RunCountdown.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TagInput from '@/components/TagInput.vue'
import { type Reading, useTickingSeconds } from '@/composables/use-ticking-seconds'
import { t, type MessageKey } from '@/i18n'
import { isActiveStatus } from '@/services/analysis-status'
import { formatDuration, secondsBetween } from '@/services/format-duration'
import { formatTimestamp } from '@/services/format-time'
import { ANALYSIS_TARGET } from '@/stores/annotations'

const props = defineProps<{ analysis: AnalysisRead; busy: boolean }>()
const emit = defineEmits<{ cancel: []; delete: [] }>()

const FAILURE_TITLE_KEYS: Partial<Record<AnalysisRead['status'], MessageKey>> = {
  failed: 'analysis.header.failedTitle',
  report_failed: 'analysis.header.reportFailedTitle',
}

const canCancel = computed(() => props.analysis.status === 'queued')
// CAPE cannot delete a task that is still being analysed, so the backend answers 409 for these.
const canDelete = computed(() => !isActiveStatus(props.analysis.status))
const failureTitle = computed(() => {
  const key = FAILURE_TITLE_KEYS[props.analysis.status]
  return key ? t(key) : undefined
})
const duration = computed(() => {
  const { started_at, finished_at } = props.analysis
  return started_at && finished_at ? formatDuration(secondsBetween(started_at, finished_at)) : undefined
})
const showRemaining = computed(
  () => props.analysis.options.interactive === true && props.analysis.status === 'running' && props.analysis.deadline_at !== null,
)
const remaining = useTickingSeconds(() => remainingUntil(props.analysis.deadline_at), {
  direction: -1,
  counting: () => props.analysis.status === 'running',
})

function remainingUntil(deadlineAt: string | null): Reading | undefined {
  if (deadlineAt === null) return undefined
  const receivedAt = Date.now()
  return { seconds: secondsBetween(new Date(receivedAt).toISOString(), deadlineAt), receivedAt }
}
</script>

<template>
  <header class="analysis-header">
    <div class="analysis-header__title">
      <span class="analysis-header__id text-mono">{{ t('analysis.header.id', { id: analysis.id }) }}</span>
      <h1
        class="analysis-header__filename text-mono"
        :title="analysis.filename"
      >
        {{ analysis.filename }}
      </h1>
      <StatusBadge :status="analysis.status" />
      <TagInput
        class="analysis-header__tags"
        :target="ANALYSIS_TARGET"
      />
      <div class="analysis-header__actions">
        <q-btn
          v-if="canCancel"
          outline
          square
          :label="t('analysis.header.cancel')"
          class="analysis-header__cancel text-mono"
          :disable="busy"
          @click="emit('cancel')"
        />
        <ExportMenu :analysis="analysis" />
        <q-btn
          v-if="canDelete"
          outline
          square
          :label="t('analysis.header.delete')"
          class="analysis-header__delete text-mono"
          :disable="busy"
          @click="emit('delete')"
        />
      </div>
    </div>

    <div class="analysis-header__hash-row">
      <span class="analysis-header__label text-mono">{{ t('analysis.header.sha256') }}</span>
      <code
        class="analysis-header__hash text-mono"
        :title="analysis.sample_sha256"
      >{{ analysis.sample_sha256 }}</code>
      <CopyButton
        class="analysis-header__copy"
        :text="analysis.sample_sha256"
        :what="t('analysis.header.sha256')"
      />
    </div>

    <dl class="analysis-header__timing text-mono">
      <div>
        <dt>{{ t('analysis.header.submitted') }}</dt>
        <dd>{{ formatTimestamp(analysis.submitted_at) }}</dd>
      </div>
      <div
        v-if="analysis.guest"
        class="analysis-header__guest"
      >
        <dt>{{ t('analysis.header.guest') }}</dt>
        <dd>
          <GuestChip
            :name="analysis.guest"
            :badges="analysis.guest_badges"
          />
        </dd>
      </div>
      <div
        v-if="analysis.started_at"
        class="analysis-header__started"
      >
        <dt>{{ t('analysis.header.started') }}</dt>
        <dd>{{ formatTimestamp(analysis.started_at) }}</dd>
      </div>
      <div
        v-if="duration"
        class="analysis-header__duration"
      >
        <dt>{{ t('analysis.header.duration') }}</dt>
        <dd>{{ duration }}</dd>
      </div>
      <div
        v-if="showRemaining"
        class="analysis-header__remaining"
      >
        <dt>{{ t('analysis.header.remaining') }}</dt>
        <dd>
          <RunCountdown
            :seconds="remaining"
            interactive
            running
          />
        </dd>
      </div>
    </dl>

    <div
      v-if="failureTitle"
      class="analysis-header__banner"
      role="alert"
    >
      <strong class="text-mono">{{ failureTitle }}</strong>
      <span>{{ analysis.error ?? t('analysis.header.noErrorMessage') }}</span>
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
  min-height: 36px;
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

.analysis-header__actions {
  display: flex;
  flex: none;
  gap: var(--spacing-sm);
  margin-left: auto;
  align-self: flex-start;
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

.analysis-header__tags {
  flex: 1 1 12rem;
  min-width: 0;
}

.analysis-header__hash {
  min-width: 0;
  color: var(--text-gray);
  font-size: 0.8rem;
  overflow-wrap: anywhere;
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

.analysis-header__guest {
  min-width: 0;
  max-width: 100%;
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
