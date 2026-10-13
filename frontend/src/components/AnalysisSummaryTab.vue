<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisRead, AnalysisStatus, ReportSummary } from '@/api'
import SeverityBadge from '@/components/SeverityBadge.vue'
import StatTile from '@/components/StatTile.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { compareSeverity } from '@/services/analysis-status'
import { formatDuration } from '@/services/format-duration'

const props = defineProps<{ analysis: AnalysisRead }>()

const PHASES: Partial<Record<AnalysisStatus, string>> = {
  starting: 'starting the guest',
  running: 'detonating in the guest',
  processing: 'CAPE is processing the results',
  ingesting: 'reading the report',
}

const NO_REPORT_MESSAGES: Partial<Record<AnalysisStatus, string>> = {
  queued: 'queued, waiting for the guest to be free',
  failed: 'no report: the analysis failed before CAPE produced one',
  report_failed: 'the report could not be read',
  cancelled: 'cancelled before it ran',
}

function queuedMessage(position: number | null): string {
  if (position === null) return NO_REPORT_MESSAGES.queued!
  const place = position === 1 ? 'next in the queue' : `position ${position} in the queue`
  return `queued, ${place}, waiting for the guest to be free`
}

const phase = computed(() => PHASES[props.analysis.status])
const noReportMessage = computed(() =>
  props.analysis.status === 'queued' ? queuedMessage(props.analysis.queue_position) : NO_REPORT_MESSAGES[props.analysis.status],
)
const report = computed<ReportSummary>(() => props.analysis.summary ?? {})
const signatures = computed(() =>
  [...(report.value.signatures ?? [])].sort((a, b) => compareSeverity(b.severity, a.severity)),
)
const techniques = computed(() => report.value.techniques ?? [])
const hasDetections = computed(() => signatures.value.length > 0 || techniques.value.length > 0)
const duration = computed(() => (report.value.duration_s == null ? null : formatDuration(report.value.duration_s)))
</script>

<template>
  <section class="analysis-summary">
    <template v-if="phase">
      <q-linear-progress
        indeterminate
        color="primary"
        track-color="grey-9"
        class="analysis-summary__progress"
        :aria-label="`Analysis ${analysis.status}`"
      />
      <p class="analysis-summary__phase text-mono text-gray">
        {{ phase }}
      </p>
    </template>

    <TerminalEmpty
      v-else-if="noReportMessage"
      :message="noReportMessage"
    />

    <template v-else>
      <div class="analysis-summary__tiles">
        <StatTile
          label="SCORE"
          :value="analysis.score"
        />
        <StatTile label="MAX SEVERITY">
          <SeverityBadge
            v-if="analysis.max_severity"
            :severity="analysis.max_severity"
          />
        </StatTile>
        <StatTile
          label="PROCESSES"
          :value="report.process_count"
        />
        <StatTile
          label="DURATION"
          :value="duration"
        />
        <StatTile
          label="FILES WRITTEN"
          :value="report.files_written"
        />
        <StatTile
          label="REGISTRY KEYS WRITTEN"
          :value="report.registry_keys_written"
        />
      </div>

      <h2 class="analysis-summary__heading text-mono">
        NETWORK
      </h2>
      <div class="analysis-summary__tiles">
        <StatTile
          label="DNS"
          :value="report.network?.dns"
        />
        <StatTile
          label="HOSTS"
          :value="report.network?.hosts"
        />
        <StatTile
          label="TCP"
          :value="report.network?.tcp"
        />
      </div>

      <template v-if="analysis.detected_families.length > 0">
        <h2 class="analysis-summary__heading text-mono">
          DETECTED FAMILIES
        </h2>
        <ul class="analysis-summary__families text-mono">
          <li
            v-for="family in analysis.detected_families"
            :key="family"
          >
            {{ family }}
          </li>
        </ul>
      </template>

      <TerminalEmpty
        v-if="!hasDetections"
        message="no detections: CAPE raised no signatures"
      />

      <template v-else>
        <h2 class="analysis-summary__heading text-mono">
          SIGNATURES
        </h2>
        <ul class="analysis-summary__list analysis-summary__list--signatures">
          <li
            v-for="signature in signatures"
            :key="signature.name"
            class="signature-row"
          >
            <SeverityBadge :severity="signature.severity" />
            <span class="signature-row__name text-mono">{{ signature.name }}</span>
            <span class="signature-row__description text-gray">{{ signature.description }}</span>
          </li>
        </ul>

        <h2 class="analysis-summary__heading text-mono">
          ATT&amp;CK TECHNIQUES
        </h2>
        <ul class="analysis-summary__list">
          <li
            v-for="technique in techniques"
            :key="technique.id"
            class="technique"
          >
            <span class="technique__id text-mono">{{ technique.id }}</span>
            <span class="technique__signatures text-gray">{{ technique.signatures.join(', ') }}</span>
          </li>
        </ul>
      </template>
    </template>
  </section>
</template>

<style scoped>
.analysis-summary {
  padding: var(--spacing-lg);
}

.analysis-summary__progress {
  max-width: 480px;
}

.analysis-summary__phase {
  margin: var(--spacing-sm) 0 0;
}

.analysis-summary__tiles {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-md);
}

.analysis-summary__heading {
  margin: var(--spacing-lg) 0 var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.75rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

.analysis-summary__tiles + .analysis-summary__heading {
  margin-top: var(--spacing-lg);
}

.analysis-summary__families,
.analysis-summary__list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}

.signature-row,
.technique {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--spacing-sm) var(--spacing-md);
  min-width: 0;
}

.signature-row__name,
.technique__id {
  font-weight: bold;
  overflow-wrap: anywhere;
}

.analysis-summary__list--signatures {
  display: grid;
  grid-template-columns: max-content fit-content(24rem) minmax(0, 1fr);
  align-items: baseline;
  gap: var(--spacing-sm) var(--spacing-md);
}

.analysis-summary__list--signatures .signature-row {
  display: contents;
}

@media (max-width: 700px) {
  .analysis-summary__list--signatures {
    display: flex;
  }

  .analysis-summary__list--signatures .signature-row {
    display: flex;
  }
}

.signature-row__description,
.technique__signatures {
  min-width: 0;
  overflow-wrap: anywhere;
}
</style>
