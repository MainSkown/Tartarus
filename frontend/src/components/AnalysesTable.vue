<script setup lang="ts">
import type { AnalysisRead } from '@/api'
import AnalysisRowMenu from '@/components/AnalysisRowMenu.vue'
import GuestChip from '@/components/GuestChip.vue'
import QueuePosition from '@/components/QueuePosition.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TagList from '@/components/TagList.vue'
import { t } from '@/i18n'
import { isTerminalStatus } from '@/services/analysis-status'
import { formatTimestamp } from '@/services/format-time'

const SHA_PREFIX_LENGTH = 8

defineProps<{ analyses: AnalysisRead[] }>()

const emit = defineEmits<{
  open: [id: number]
  cancel: [id: number]
  reingest: [id: number]
  remove: [id: number]
}>()

function shaPrefix(sha256: string): string {
  return `${sha256.slice(0, SHA_PREFIX_LENGTH)}…`
}
</script>

<template>
  <div class="tt-table-scroll">
    <table class="tt-table analyses-table text-mono">
      <thead>
        <tr>
          <th class="col-id">
            #
          </th>
          <th>{{ t('dashboard.table.file') }}</th>
          <th class="col-optional">
            {{ t('dashboard.table.sha256') }}
          </th>
          <th class="col-optional">
            {{ t('dashboard.table.submitted') }}
          </th>
          <th>{{ t('dashboard.table.status') }}</th>
          <th class="col-numeric">
            {{ t('dashboard.table.score') }}
          </th>
          <th>{{ t('dashboard.table.severity') }}</th>
          <th class="col-optional">
            {{ t('dashboard.table.tags') }}
          </th>
          <th class="col-actions">
            <span class="sr-only">{{ t('dashboard.table.actions') }}</span>
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
            <GuestChip
              class="cell-guest"
              :name="analysis.guest"
              :badges="analysis.guest_badges"
            />
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
            <QueuePosition :analysis-id="analysis.id" />
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
          <td class="col-optional col-tags">
            <TagList
              :tags="analysis.tags"
              :max="1"
            />
          </td>
          <td class="col-actions">
            <AnalysisRowMenu
              :analysis="analysis"
              @open="emit('open', $event)"
              @reingest="emit('reingest', $event)"
              @cancel="emit('cancel', $event)"
              @remove="emit('remove', $event)"
            />
            <q-btn
              v-if="isTerminalStatus(analysis.status)"
              flat
              dense
              square
              icon="delete_outline"
              size="sm"
              :aria-label="t('dashboard.row.deleteFor', { id: analysis.id })"
              @click.stop="emit('remove', analysis.id)"
              @keydown.enter.stop
            >
              <q-tooltip>{{ t('dashboard.row.delete') }}</q-tooltip>
            </q-btn>
            <q-btn
              v-else
              flat
              dense
              square
              icon="stop_circle"
              size="sm"
              :aria-label="t('dashboard.row.cancelFor', { id: analysis.id })"
              @click.stop="emit('cancel', analysis.id)"
              @keydown.enter.stop
            >
              <q-tooltip>{{ t('dashboard.row.cancel') }}</q-tooltip>
            </q-btn>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.analysis-row {
  cursor: pointer;
}

.analysis-row:hover,
.analysis-row:focus-visible {
  background: var(--border-subtle);
  outline: none;
}

.col-id,
.col-numeric {
  text-align: right;
}

.col-actions {
  width: 1%;
  text-align: right;
  white-space: nowrap;
}

.col-actions :deep(.q-btn) {
  color: var(--text-gray);
}

.col-actions :deep(.q-btn:hover) {
  color: var(--blue-hover);
}

.col-tags {
  max-width: 24ch;
  overflow: hidden;
}

.cell-filename {
  display: block;
  max-width: min(28ch, 40vw);
  overflow: hidden;
  text-overflow: ellipsis;
}

/* The chip is a second line of the FILE cell, capped at the file name's width so it never widens the column. */
.cell-guest {
  margin-top: var(--spacing-xs);
  max-width: min(28ch, 40vw);
}

@media (max-width: 700px) {
  .col-optional,
  .col-id {
    display: none;
  }

  .analyses-table th,
  .analyses-table td {
    padding-inline: var(--spacing-sm);
  }

  .cell-filename {
    max-width: 12ch;
  }

  /* No width to spare beside the name, so the badges go under it. */
  .cell-guest {
    max-width: 14ch;
    flex-direction: column;
    align-items: stretch;
  }

  .cell-guest :deep(.guest-chip__badge) {
    padding-inline: var(--spacing-xs);
    overflow: hidden;
    border-top: 1px solid var(--border-subtle);
    border-left: none;
    text-overflow: ellipsis;
  }
}
</style>
