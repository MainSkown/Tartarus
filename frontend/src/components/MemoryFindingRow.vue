<script setup lang="ts">
import { computed, ref } from 'vue'
import CopyButton from '@/components/CopyButton.vue'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import MemoryFindingDetail from '@/components/MemoryFindingDetail.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import { t } from '@/i18n'
import { memoryFindingFilters } from '@/services/events-filters'
import { processTitle } from '@/services/process-graph'
import type { MemoryFinding } from '@/services/memory-findings'

const props = defineProps<{ analysisId: number; finding: MemoryFinding }>()

const open = ref(false)
const processLabel = computed(() =>
  props.finding.process ? processTitle(props.finding.process) : t('artifacts.memory.finding.unknownProcess'),
)
const toggleLabel = computed(() =>
  open.value
    ? t('artifacts.memory.finding.hide', { process: processLabel.value })
    : t('artifacts.memory.finding.show', { process: processLabel.value }),
)
</script>

<template>
  <tbody class="finding">
    <tr class="finding-row">
      <td class="cell-toggle">
        <button
          type="button"
          class="finding-toggle"
          :aria-expanded="open"
          :aria-label="toggleLabel"
          @click="open = !open"
        >
          <q-icon
            :name="open ? 'expand_more' : 'chevron_right'"
            size="18px"
          />
        </button>
      </td>
      <td class="cell-severity">
        <SeverityBadge :severity="finding.severity" />
      </td>
      <td class="cell-process">
        <ProcessChip :process="finding.process" />
      </td>
      <td class="cell-address">
        <template v-if="finding.address">
          <span
            class="finding-address"
            :title="finding.address"
          >{{ finding.address }}</span>
          <CopyButton
            :text="finding.address"
            :what="t('artifacts.memory.finding.addressNoun')"
          />
        </template>
        <span
          v-else
          class="cell-empty"
        >–</span>
        <FilterEventsButton :target="{ chips: memoryFindingFilters(finding) }" />
      </td>
      <td class="cell-protection">
        <template v-if="finding.protection">
          {{ finding.protection }}
        </template>
        <span
          v-else
          class="cell-empty"
        >–</span>
      </td>
      <td class="cell-note">
        <span
          v-if="finding.note"
          :title="finding.note"
        >{{ finding.note }}</span>
        <span
          v-else
          class="cell-empty"
        >–</span>
      </td>
    </tr>
    <tr
      v-if="open"
      class="finding-detail-row"
    >
      <td class="cell-detail-gutter" />
      <td
        class="cell-detail"
        colspan="5"
      >
        <MemoryFindingDetail
          :analysis-id="analysisId"
          :event-id="finding.id"
        />
      </td>
    </tr>
  </tbody>
</template>

<style scoped>
.finding + .finding {
  border-top: 1px solid var(--border-subtle);
}

.cell-toggle {
  padding-inline: var(--spacing-xs);
}

.finding-toggle {
  display: flex;
  padding: 2px;
  border: none;
  background: transparent;
  color: var(--blue-primary);
  cursor: pointer;
}

.finding-toggle:hover,
.finding-toggle:focus-visible {
  color: var(--blue-hover);
}

.finding-address {
  display: inline-block;
  max-width: 19ch;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}

.cell-note {
  white-space: normal;
  overflow-wrap: anywhere;
}

.finding-detail-row td {
  border-bottom: none;
  padding-top: 0;
}

/* Below this the table would scroll sideways and hide the note, so a finding stacks into three lines: who, where, what. */
@container finding-list (max-width: 900px) {
  .finding {
    display: block;
  }

  .finding-row {
    display: grid;
    grid-template-columns: 2rem minmax(0, 1fr) minmax(0, 1fr);
    grid-template-areas:
      'toggle severity process'
      '. address protection'
      '. note note';
    align-items: center;
    row-gap: var(--spacing-xs);
    padding: var(--spacing-sm) 0;
  }

  .finding-row > td {
    min-width: 0;
    padding: 0 var(--spacing-sm);
    border: none;
  }

  .finding-row > .cell-toggle {
    grid-area: toggle;
    padding-inline: var(--spacing-xs);
  }

  .finding-row > .cell-severity {
    grid-area: severity;
  }

  .finding-row > .cell-process {
    grid-area: process;
  }

  .finding-row > .cell-address {
    grid-area: address;
  }

  .finding-row > .cell-protection {
    grid-area: protection;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .finding-row > .cell-note {
    grid-area: note;
  }

  .finding-detail-row {
    display: block;
  }

  .finding-detail-row > .cell-detail-gutter {
    display: none;
  }

  .finding-detail-row > .cell-detail {
    display: block;
    padding: 0 var(--spacing-sm) var(--spacing-sm);
  }
}
</style>
