<script setup lang="ts">
import type { ProcessRef } from '@/api'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import { t } from '@/i18n'
import type { EventsFilter } from '@/services/events-filters'

export interface NetworkColumn {
  label: string
  numeric?: boolean
}

export interface NetworkTableRow {
  key: string
  cells: (string | number | null)[]
  /** Per cell, what its "show events" button applies; an absent or empty entry means no button. */
  cellFilters?: EventsFilter[][]
  process?: ProcessRef | null
}

defineProps<{
  columns: NetworkColumn[]
  rows: NetworkTableRow[]
  total: number
  withProcess?: boolean
  simulated?: boolean
}>()
</script>

<template>
  <div class="network-table">
    <p class="network-table__note text-mono">
      <span class="network-table__count text-gray">{{ t('network.table.listed', { shown: rows.length, total }) }}</span>
      <span
        v-if="simulated"
        class="network-table__inetsim"
        :title="t('network.table.inetsimTitle')"
      >{{ t('network.table.inetsim') }}</span>
    </p>
    <div class="tt-table-scroll">
      <table class="tt-table text-mono">
        <thead>
          <tr>
            <th
              v-for="column in columns"
              :key="column.label"
              :class="{ num: column.numeric }"
            >
              {{ column.label }}
            </th>
            <th v-if="withProcess">
              {{ t('network.column.process') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.key"
          >
            <td
              v-for="(column, index) in columns"
              :key="column.label"
              :class="{ num: column.numeric }"
            >
              <span
                class="cell-value"
                :title="String(row.cells[index] ?? '–')"
              >{{ row.cells[index] ?? '–' }}</span>
              <FilterEventsButton :target="{ chips: row.cellFilters?.[index] ?? [] }" />
            </td>
            <td v-if="withProcess">
              <FilterEventsButton
                v-if="row.process"
                :target="{ pid: row.process.pid }"
              >
                <ProcessChip :process="row.process" />
              </FilterEventsButton>
              <ProcessChip
                v-else
                :process="null"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.network-table__note {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin: var(--spacing-sm) 0;
  font-size: 0.75rem;
}

.network-table__inetsim {
  padding: 0 var(--spacing-sm);
  border: 1px solid var(--border-secondary);
  color: var(--blue-light);
  letter-spacing: 1px;
}

.cell-value {
  display: inline-block;
  max-width: min(38ch, 60vw);
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
}
</style>
