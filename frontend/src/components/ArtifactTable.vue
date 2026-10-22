<script setup lang="ts">
import { computed } from 'vue'
import type { Artifact } from '@/api'
import CopyButton from '@/components/CopyButton.vue'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import { t } from '@/i18n'
import { filterOn } from '@/services/events-filters'
import { formatFileSize } from '@/services/file-size'

const HASH_PREFIX_LENGTH = 12

const props = defineProps<{ analysisId: number; artifacts: Artifact[]; showFamily?: boolean }>()

const anyDownloadable = computed(() => props.artifacts.some((artifact) => artifact.downloadable))

function downloadUrl(artifact: Artifact): string {
  return `/api/analyses/${props.analysisId}/artifacts/${encodeURIComponent(artifact.id)}/download`
}
</script>

<template>
  <div class="artifact-table">
    <p
      v-if="anyDownloadable"
      class="download-note text-mono text-gray"
    >
      {{ t('artifacts.table.downloadNote') }}
    </p>
    <div class="tt-table-scroll">
      <table class="tt-table text-mono">
        <thead>
          <tr>
            <th>{{ t('artifacts.column.name') }}</th>
            <th v-if="showFamily">
              {{ t('artifacts.column.family') }}
            </th>
            <th>{{ t('artifacts.column.guestPath') }}</th>
            <th class="num">
              {{ t('artifacts.column.size') }}
            </th>
            <th>{{ t('artifacts.column.type') }}</th>
            <th>{{ t('artifacts.column.sha256') }}</th>
            <th>{{ t('artifacts.column.yara') }}</th>
            <th>{{ t('artifacts.column.process') }}</th>
            <th class="col-download">
              {{ t('artifacts.column.download') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="artifact in artifacts"
            :key="artifact.id"
          >
            <td>
              <span
                class="cell-name"
                :title="artifact.name"
              >{{ artifact.name }}</span>
            </td>
            <td
              v-if="showFamily"
              class="cell-family"
            >
              {{ artifact.cape_type ?? '–' }}
            </td>
            <td>
              <template v-if="artifact.guest_path">
                <span
                  class="cell-path"
                  :title="artifact.guest_path"
                >{{ artifact.guest_path }}</span>
                <FilterEventsButton :target="{ chips: filterOn('file.path', artifact.guest_path) }" />
              </template>
              <span
                v-else
                class="cell-path cell-empty"
              >–</span>
            </td>
            <td class="num cell-size">
              {{ artifact.size === null ? '–' : formatFileSize(artifact.size) }}
            </td>
            <td>
              <span
                class="cell-type"
                :title="artifact.type ?? undefined"
              >{{ artifact.type ?? '–' }}</span>
            </td>
            <td class="cell-sha">
              <template v-if="artifact.sha256">
                <span :title="artifact.sha256">{{ artifact.sha256.slice(0, HASH_PREFIX_LENGTH) }}…</span>
                <CopyButton
                  :text="artifact.sha256"
                  :what="t('artifacts.table.sha256Noun')"
                />
                <FilterEventsButton :target="{ chips: filterOn('file.hash.sha256', artifact.sha256) }" />
              </template>
              <span
                v-else
                class="cell-empty"
              >–</span>
            </td>
            <td class="cell-yara">
              <template v-if="artifact.yara.length">
                <span
                  v-for="rule in artifact.yara"
                  :key="rule"
                  class="yara-hit"
                  :title="rule"
                >{{ rule }}</span>
              </template>
              <span
                v-else
                class="cell-empty"
              >–</span>
            </td>
            <td>
              <ProcessChip :process="artifact.source_process" />
            </td>
            <td class="col-download">
              <a
                v-if="artifact.downloadable"
                class="download-link"
                :href="downloadUrl(artifact)"
              >{{ t('artifacts.table.download') }}<q-tooltip>{{ t('artifacts.table.downloadTooltip') }}</q-tooltip></a>
              <span
                v-else
                class="download-unavailable"
                aria-disabled="true"
                :title="t('artifacts.table.notKeptTitle')"
              >{{ t('artifacts.table.notKept') }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.download-note {
  margin: 0 0 var(--spacing-sm);
  font-size: 0.75rem;
}

.cell-name,
.cell-path,
.cell-type {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Inline so the path's "show events" button sits beside it, not under it. */
.cell-path {
  display: inline-block;
  vertical-align: middle;
}

.cell-name {
  max-width: 20ch;
}

.cell-path {
  max-width: min(24ch, 40vw);
}

.cell-type {
  max-width: 16ch;
}

.tt-table th,
.tt-table td {
  padding-inline: var(--spacing-sm);
}

.cell-yara {
  max-width: 22ch;
  white-space: normal;
}

/* Stays in view when the table scrolls sideways: the download is the point of most rows. */
.col-download {
  position: sticky;
  right: 0;
  background: var(--black);
  border-left: 1px solid var(--border-subtle);
}

.yara-hit {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  margin-right: var(--spacing-xs);
  padding: 0 var(--spacing-xs);
  border: 1px solid var(--status-high);
  color: var(--status-high);
}

.download-link {
  color: var(--blue-primary);
  text-decoration: none;
}

.download-link:hover,
.download-link:focus-visible {
  color: var(--blue-hover);
}

.download-unavailable {
  color: var(--text-gray-darker);
  cursor: not-allowed;
}
</style>
