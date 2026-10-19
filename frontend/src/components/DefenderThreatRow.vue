<script setup lang="ts">
import { computed } from 'vue'
import type { DefenderThreat, Scope } from '@/api'
import CopyButton from '@/components/CopyButton.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import TagChip from '@/components/TagChip.vue'
import { t, type MessageKey } from '@/i18n'
import { severityOfRank } from '@/services/analysis-status'
import { OUTCOME_META } from '@/services/defender-verdict'
import { splitPath } from '@/services/file-path'
import { formatTimestamp } from '@/services/format-time'

const SCOPE_KEYS: Record<Scope, MessageKey> = {
  sample: 'analysis.summary.defender.scope.sample',
  dropped: 'analysis.summary.defender.scope.dropped',
  tooling: 'analysis.summary.defender.scope.tooling',
  other: 'analysis.summary.defender.scope.other',
}

const props = defineProps<{ threat: DefenderThreat }>()

const file = computed(() => (props.threat.path === null ? null : splitPath(props.threat.path)))
const outcome = computed(() => OUTCOME_META[props.threat.outcome])
</script>

<template>
  <li class="defender-threat">
    <div class="defender-threat__title">
      <SeverityBadge :severity="severityOfRank(threat.severity)" />
      <span class="defender-threat__name text-mono">{{ threat.name ?? t('analysis.summary.defender.unknownThreat') }}</span>
      <TagChip :name="t(SCOPE_KEYS[threat.scope])" />
    </div>
    <div
      v-if="file && threat.path"
      class="defender-threat__location"
    >
      <span
        class="defender-threat__path text-mono"
        :title="threat.path"
      >
        <span class="defender-threat__directory">{{ file.directory }}</span><span class="defender-threat__file">{{ file.name }}</span>
      </span>
      <CopyButton
        :text="threat.path"
        :what="t('analysis.summary.defender.path')"
      />
    </div>
    <p class="defender-threat__facts text-mono text-gray">
      <span
        class="defender-threat__outcome"
        :style="{ color: `var(${outcome.color})` }"
      >{{ t(outcome.labelKey) }}</span>
      <span>{{ threat.action }}</span>
      <span v-if="threat.detected_at">{{ t('analysis.summary.defender.detectedAt', { time: formatTimestamp(threat.detected_at) }) }}</span>
      <span v-if="threat.removed_at">{{ t('analysis.summary.defender.removedAt', { time: formatTimestamp(threat.removed_at) }) }}</span>
    </p>
  </li>
</template>

<style scoped>
.defender-threat {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
  padding: var(--spacing-sm) 0;
  border-top: 1px solid var(--border-subtle);
}

.defender-threat__title,
.defender-threat__facts {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--spacing-xs) var(--spacing-md);
  min-width: 0;
}

.defender-threat__name {
  min-width: 0;
  font-weight: bold;
  overflow-wrap: anywhere;
}

.defender-threat__location {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  min-width: 0;
}

/* The directory gives way first: what a truncated path must keep is the file name. */
.defender-threat__path {
  display: flex;
  min-width: 0;
  font-size: 0.85rem;
}

.defender-threat__directory {
  min-width: 0;
  overflow: hidden;
  color: var(--text-gray);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.defender-threat__file {
  flex: none;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.defender-threat__facts {
  margin: 0;
  font-size: 0.75rem;
}
</style>
