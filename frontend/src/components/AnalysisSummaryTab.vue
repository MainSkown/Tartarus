<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisRead, AnalysisStatus, ReportSummary } from '@/api'
import DefenderVerdict from '@/components/DefenderVerdict.vue'
import HiddenEventsNote from '@/components/HiddenEventsNote.vue'
import LaneBars from '@/components/LaneBars.vue'
import MemoryStatus from '@/components/MemoryStatus.vue'
import ScreenshotStrip from '@/components/ScreenshotStrip.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import StatTile from '@/components/StatTile.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { t, type MessageKey } from '@/i18n'
import { compareSeverity } from '@/services/analysis-status'
import { guestRunsDefender } from '@/services/defender-verdict'
import { formatDuration } from '@/services/format-duration'
import { laneBars } from '@/services/lanes'

const props = defineProps<{ analysis: AnalysisRead }>()

const PHASE_KEYS: Partial<Record<AnalysisStatus, MessageKey>> = {
  starting: 'analysis.summary.starting',
  running: 'analysis.summary.running',
  processing: 'analysis.summary.processing',
  ingesting: 'analysis.summary.ingesting',
}

const NO_REPORT_KEYS: Partial<Record<AnalysisStatus, MessageKey>> = {
  failed: 'analysis.summary.failed',
  report_failed: 'analysis.summary.reportFailed',
  cancelled: 'analysis.summary.cancelled',
}

function queuedMessage(position: number | null): string {
  if (position === null) return t('analysis.summary.queued')
  return position === 1 ? t('analysis.summary.queuedNext') : t('analysis.summary.queuedAt', { position })
}

function translatedOrUndefined(key: MessageKey | undefined): string | undefined {
  return key ? t(key) : undefined
}

const phase = computed(() => translatedOrUndefined(PHASE_KEYS[props.analysis.status]))
const noReportMessage = computed(() =>
  props.analysis.status === 'queued'
    ? queuedMessage(props.analysis.queue_position)
    : translatedOrUndefined(NO_REPORT_KEYS[props.analysis.status]),
)
const report = computed<ReportSummary>(() => props.analysis.summary ?? {})
const signatures = computed(() =>
  [...(report.value.signatures ?? [])].sort((a, b) => compareSeverity(b.severity, a.severity)),
)
const techniques = computed(() => report.value.techniques ?? [])
const hasDetections = computed(() => signatures.value.length > 0 || techniques.value.length > 0)
const lanes = computed(() => laneBars(report.value.lane_counts))
const defender = computed(() => (guestRunsDefender(props.analysis.guest_badges) ? (report.value.defender ?? null) : null))
const blockedBeforeRun = computed(() => defender.value?.blocked_before_run === true)
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
        :aria-label="t('analysis.summary.progressLabel', { status: analysis.status })"
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
      <DefenderVerdict
        v-if="defender && blockedBeforeRun"
        :verdict="defender"
      />

      <div class="analysis-summary__tiles">
        <StatTile
          :label="t('analysis.summary.tile.score')"
          :value="analysis.score"
        />
        <StatTile :label="t('analysis.summary.tile.maxSeverity')">
          <SeverityBadge
            v-if="analysis.max_severity"
            :severity="analysis.max_severity"
          />
        </StatTile>
        <StatTile
          :label="t('analysis.summary.tile.processes')"
          :value="report.process_count"
        />
        <StatTile
          :label="t('analysis.summary.tile.duration')"
          :value="duration"
        />
        <StatTile
          :label="t('analysis.summary.tile.filesWritten')"
          :value="report.files_written"
        />
        <StatTile
          :label="t('analysis.summary.tile.registryKeysWritten')"
          :value="report.registry_keys_written"
        />
      </div>

      <template v-if="lanes.length > 0">
        <h2 class="analysis-summary__heading text-mono">
          {{ t('analysis.summary.eventsByLane') }}
        </h2>
        <LaneBars :bars="lanes" />
      </template>
      <HiddenEventsNote :counts="report.hidden_events" />

      <template v-if="report.memory">
        <h2 class="analysis-summary__heading text-mono">
          {{ t('analysis.summary.memory.heading') }}
        </h2>
        <MemoryStatus
          :memory="report.memory"
          :finding-count="report.lane_counts?.memory"
        />
      </template>

      <h2 class="analysis-summary__heading text-mono">
        {{ t('analysis.summary.screenshots') }}
      </h2>
      <ScreenshotStrip :analysis-id="analysis.id" />

      <h2 class="analysis-summary__heading text-mono">
        {{ t('analysis.summary.network') }}
      </h2>
      <div class="analysis-summary__tiles">
        <StatTile
          :label="t('analysis.summary.tile.dns')"
          :value="report.network?.dns"
        />
        <StatTile
          :label="t('analysis.summary.tile.hosts')"
          :value="report.network?.hosts"
        />
        <StatTile
          :label="t('analysis.summary.tile.tcp')"
          :value="report.network?.tcp"
        />
      </div>

      <template v-if="analysis.detected_families.length > 0">
        <h2 class="analysis-summary__heading text-mono">
          {{ t('analysis.summary.detectedFamilies') }}
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

      <template v-if="defender && !blockedBeforeRun">
        <h2 class="analysis-summary__heading text-mono">
          {{ t('analysis.summary.defender.heading') }}
        </h2>
        <DefenderVerdict :verdict="defender" />
      </template>

      <TerminalEmpty
        v-if="!hasDetections"
        :message="t('analysis.summary.noDetections')"
      />

      <template v-else>
        <h2 class="analysis-summary__heading text-mono">
          {{ t('analysis.summary.signatures') }}
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
          {{ t('analysis.summary.attackTechniques') }}
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
