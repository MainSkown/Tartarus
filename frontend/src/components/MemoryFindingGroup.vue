<script setup lang="ts">
import { computed, ref } from 'vue'
import MemoryFindingRow from '@/components/MemoryFindingRow.vue'
import { t } from '@/i18n'
import { pluginHelp, type FindingGroup } from '@/services/memory-findings'

const ROWS_PER_STEP = 25

const props = defineProps<{ analysisId: number; group: FindingGroup }>()

const shown = ref(ROWS_PER_STEP)
const visible = computed(() => props.group.findings.slice(0, shown.value))
const remaining = computed(() => props.group.findings.length - visible.value.length)
const help = computed(() => pluginHelp(props.group.name))
</script>

<template>
  <details
    class="finding-group"
    open
  >
    <summary class="finding-group__summary text-mono">
      <span
        class="finding-group__name"
        :title="group.plugin"
      >{{ group.name }}</span>
      <span
        v-if="help"
        class="finding-group__help text-gray"
      >{{ help }}</span>
      <span class="finding-group__count">{{ t('artifacts.memory.findings.count', group.findings.length) }}</span>
    </summary>
    <div
      class="tt-table-scroll"
      role="region"
      :aria-label="t('artifacts.memory.findings.groupLabel', { plugin: group.name })"
    >
      <table class="tt-table finding-table text-mono">
        <colgroup>
          <col class="col-toggle">
          <col class="col-severity">
          <col class="col-process">
          <col class="col-address">
          <col class="col-protection">
          <col>
        </colgroup>
        <thead>
          <tr>
            <th>
              <span class="sr-only">{{ t('artifacts.memory.column.details') }}</span>
            </th>
            <th>{{ t('artifacts.memory.column.severity') }}</th>
            <th>{{ t('artifacts.column.process') }}</th>
            <th>{{ t('artifacts.memory.column.address') }}</th>
            <th>{{ t('artifacts.memory.column.protection') }}</th>
            <th>{{ t('artifacts.memory.column.note') }}</th>
          </tr>
        </thead>
        <MemoryFindingRow
          v-for="finding in visible"
          :key="finding.id"
          :analysis-id="analysisId"
          :finding="finding"
        />
      </table>
    </div>
    <button
      v-if="remaining > 0"
      type="button"
      class="finding-group__more text-mono"
      :aria-label="t('artifacts.memory.findings.showMoreLabel', { plugin: group.name })"
      @click="shown += ROWS_PER_STEP"
    >
      {{ t('artifacts.memory.findings.showMore', { count: Math.min(ROWS_PER_STEP, remaining) }) }}
    </button>
  </details>
</template>

<style scoped>
.finding-group + .finding-group {
  margin-top: var(--spacing-md);
}

.finding-group__summary {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
  cursor: pointer;
  list-style: none;
}

.finding-group__summary::-webkit-details-marker {
  display: none;
}

.finding-group__summary::before {
  content: '▸';
  color: var(--blue-primary);
}

.finding-group[open] > .finding-group__summary::before {
  content: '▾';
}

.finding-group__summary:hover,
.finding-group__summary:focus-visible {
  background: var(--hover-bg);
  outline: none;
}

.finding-group[open] > .finding-group__summary {
  border-bottom: none;
}

.finding-group__name {
  flex: none;
  font-weight: bold;
}

.finding-group__help {
  min-width: 0;
  overflow: hidden;
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.finding-group__count {
  flex: none;
  margin-left: auto;
  color: var(--text-gray);
}

.finding-group__more {
  display: block;
  box-sizing: border-box;
  width: 100%;
  margin-top: var(--spacing-xs);
  padding: var(--spacing-sm);
  border: 1px solid var(--border-secondary);
  background: var(--black);
  color: var(--blue-primary);
  font-size: 0.75rem;
  cursor: pointer;
}

.finding-group__more:hover,
.finding-group__more:focus-visible {
  background: var(--hover-bg);
  color: var(--blue-hover);
}

/* The table's own width, not the window's, decides the layout: see the rows for the stacked one. */
.tt-table-scroll {
  container: finding-list / inline-size;
}

/* Fixed columns so the groups' tables line up one under the other; the note takes what is left. */
.finding-table {
  min-width: 64rem;
  table-layout: fixed;
}

@container finding-list (max-width: 900px) {
  .finding-table {
    display: block;
    min-width: 0;
  }

  .finding-table colgroup {
    display: none;
  }

  /* The column titles go, but stay for screen readers: the cells keep their labels in the order they are read. */
  .finding-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
  }
}

.col-toggle {
  width: 2.5rem;
}

.col-severity {
  width: 7.5rem;
}

.col-process {
  width: 13rem;
}

.col-address {
  width: 13.5rem;
}

.col-protection {
  width: 12.5rem;
}

.tt-table th,
.tt-table :deep(td) {
  padding-inline: var(--spacing-sm);
}
</style>
