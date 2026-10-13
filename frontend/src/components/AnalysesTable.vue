<script setup lang="ts">
import type { AnalysisRead } from '@/api'
import SeverityBadge from '@/components/SeverityBadge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { isTerminalStatus } from '@/services/analysis-status'
import { formatTimestamp } from '@/services/format-time'

const SHA_PREFIX_LENGTH = 8

defineProps<{ analyses: AnalysisRead[] }>()

const emit = defineEmits<{
  open: [id: number]
  cancel: [id: number]
  remove: [id: number]
}>()

function shaPrefix(sha256: string): string {
  return `${sha256.slice(0, SHA_PREFIX_LENGTH)}…`
}
</script>

<template>
  <div class="analyses-table-scroll">
    <table class="analyses-table text-mono">
      <thead>
        <tr>
          <th class="col-id">
            #
          </th>
          <th>FILE</th>
          <th class="col-optional">
            SHA256
          </th>
          <th class="col-optional">
            SUBMITTED
          </th>
          <th>STATUS</th>
          <th class="col-numeric">
            SCORE
          </th>
          <th>SEVERITY</th>
          <th class="col-actions">
            <span class="sr-only">ACTIONS</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="analysis in analyses"
          :key="analysis.id"
          class="analysis-row"
          tabindex="0"
          @click="emit('open', analysis.id)"
          @keydown.enter="emit('open', analysis.id)"
        >
          <td class="col-id">
            {{ analysis.id }}
          </td>
          <td>
            <span
              class="cell-filename"
              :title="analysis.filename"
            >{{ analysis.filename }}</span>
          </td>
          <td
            class="col-optional cell-sha"
            :title="analysis.sample_sha256"
          >
            {{ shaPrefix(analysis.sample_sha256) }}
          </td>
          <td class="col-optional">
            {{ formatTimestamp(analysis.submitted_at) }}
          </td>
          <td>
            <StatusBadge :status="analysis.status" />
          </td>
          <td class="col-numeric">
            <template v-if="analysis.score !== null">
              {{ analysis.score.toFixed(1) }}
            </template>
            <span
              v-else
              class="cell-empty"
            >–</span>
          </td>
          <td>
            <SeverityBadge
              v-if="analysis.max_severity"
              :severity="analysis.max_severity"
            />
            <span
              v-else
              class="cell-empty"
            >–</span>
          </td>
          <td class="col-actions">
            <q-btn
              v-if="isTerminalStatus(analysis.status)"
              flat
              dense
              square
              icon="delete_outline"
              size="sm"
              :aria-label="`Delete analysis ${analysis.id}`"
              @click.stop="emit('remove', analysis.id)"
              @keydown.enter.stop
            >
              <q-tooltip>Delete</q-tooltip>
            </q-btn>
            <q-btn
              v-else
              flat
              dense
              square
              icon="stop_circle"
              size="sm"
              :aria-label="`Cancel analysis ${analysis.id}`"
              @click.stop="emit('cancel', analysis.id)"
              @keydown.enter.stop
            >
              <q-tooltip>Cancel</q-tooltip>
            </q-btn>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.analyses-table-scroll {
  overflow-x: auto;
  border: 2px solid var(--border-primary);
}

.analyses-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

th {
  padding: var(--spacing-sm) var(--spacing-md);
  text-align: left;
  color: var(--blue-primary);
  font-size: 0.65rem;
  letter-spacing: 1px;
  border-bottom: 2px solid var(--border-primary);
  white-space: nowrap;
}

td {
  padding: var(--spacing-sm) var(--spacing-md);
  border-bottom: 1px solid var(--border-subtle);
  white-space: nowrap;
}

.analysis-row {
  cursor: pointer;
}

.analysis-row:hover,
.analysis-row:focus-visible {
  background: var(--border-subtle);
  outline: none;
}

.analysis-row:last-child td {
  border-bottom: none;
}

.col-id,
.col-numeric {
  text-align: right;
}

.col-actions {
  width: 1%;
  text-align: right;
}

.cell-filename {
  display: block;
  max-width: min(28ch, 40vw);
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-empty {
  color: var(--text-gray-dark);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
}

@media (max-width: 700px) {
  .col-optional {
    display: none;
  }
}
</style>
