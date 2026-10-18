<script setup lang="ts">
import type { RuleRead } from '@/api'
import SeverityBadge from '@/components/SeverityBadge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { t } from '@/i18n'
import { formatCount } from '@/services/format-number'
import { severityOfLevel, shortPath, toggleBlockedReason } from '@/services/rule-view'

defineProps<{ rules: RuleRead[]; selectedId: string | undefined; togglingIds: ReadonlySet<string> }>()

const emit = defineEmits<{ select: [id: string]; toggle: [id: string, enabled: boolean] }>()

function toggleEnabled(rule: RuleRead, event: Event): void {
  emit('toggle', rule.id, (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="tt-table-scroll rules-table-scroll">
    <table class="tt-table rules-table text-mono">
      <thead>
        <tr>
          <th class="col-switch">
            {{ t('rules.table.enabled') }}
          </th>
          <th class="col-title">
            {{ t('rules.table.title') }}
          </th>
          <th>{{ t('rules.table.level') }}</th>
          <th class="col-logsource">
            {{ t('rules.table.logsource') }}
          </th>
          <th>{{ t('rules.table.status') }}</th>
          <th class="col-path">
            {{ t('rules.table.path') }}
          </th>
          <th class="col-numeric">
            {{ t('rules.table.hits') }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="rule in rules"
          :key="rule.id"
          class="rule-row"
          :class="{ 'rule-row--selected': rule.id === selectedId, 'rule-row--disabled': !rule.enabled }"
          :aria-current="rule.id === selectedId ? 'true' : undefined"
          tabindex="0"
          @click="emit('select', rule.id)"
          @keydown.enter="emit('select', rule.id)"
        >
          <td
            class="col-switch"
            data-cell="enabled"
          >
            <span class="rule-switch">
              <input
                type="checkbox"
                role="switch"
                class="checkbox-input"
                :checked="rule.enabled"
                :disabled="toggleBlockedReason(rule) !== undefined || togglingIds.has(rule.id)"
                :aria-label="t('rules.toggle.enabledFor', { title: rule.title })"
                :aria-describedby="toggleBlockedReason(rule) ? `blocked-${rule.id}` : undefined"
                @change="toggleEnabled(rule, $event)"
                @click.stop
                @keydown.enter.stop
              >
              <template v-if="toggleBlockedReason(rule)">
                <span
                  :id="`blocked-${rule.id}`"
                  class="sr-only"
                >{{ toggleBlockedReason(rule) }}</span>
                <q-tooltip>{{ toggleBlockedReason(rule) }}</q-tooltip>
              </template>
            </span>
          </td>
          <td
            class="col-title"
            data-cell="title"
          >
            <span
              class="cell-text"
              :title="rule.title"
            >{{ rule.title }}</span>
          </td>
          <td data-cell="level">
            <SeverityBadge
              v-if="severityOfLevel(rule.level)"
              :severity="severityOfLevel(rule.level)!"
            />
            <span
              v-else
              class="cell-empty"
            >–</span>
          </td>
          <td
            class="col-logsource"
            data-cell="logsource"
          >
            <template v-if="rule.logsource_category">
              {{ rule.logsource_category }}
            </template>
            <span
              v-else
              class="cell-empty"
            >–</span>
          </td>
          <td data-cell="validity">
            <StatusBadge :validity="rule.validity" />
          </td>
          <td
            class="col-path"
            data-cell="path"
          >
            <span
              class="cell-text cell-path"
              :title="rule.path"
            >{{ shortPath(rule.path) }}</span>
          </td>
          <td
            class="col-numeric"
            data-cell="hits"
            :class="{ 'cell-empty': rule.hits === 0 }"
          >
            {{ formatCount(rule.hits) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.rule-row {
  cursor: pointer;
}

.rule-row:hover,
.rule-row:focus-visible {
  background: var(--border-subtle);
  outline: none;
}

.rule-row--selected,
.rule-row--selected:hover,
.rule-row--selected:focus-visible {
  background: color-mix(in srgb, var(--active-bg) 35%, transparent);
}

.rule-row:focus-visible {
  box-shadow: inset 3px 0 0 var(--blue-primary);
}

/* The title and the badges dim; the switch keeps its look so the way back is always visible. */
.rule-row--disabled [data-cell]:not([data-cell='enabled']) {
  opacity: 0.5;
}

.col-switch {
  width: 1%;
  text-align: center;
}

.col-numeric {
  text-align: right;
}

.rule-switch {
  display: inline-flex;
  align-items: center;
}

.cell-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cell-path {
  max-width: 30ch;
  color: var(--text-gray);
}

/* `width: 100%` with `max-width: 0` is the table-cell way to say "take the room the other columns leave, and truncate to it". */
.col-title {
  width: 100%;
  min-width: 9rem;
  max-width: 0;
}

/* The table sits beside the rule pane at some widths, so its columns drop with the room it has, not the window's. */
.rules-table-scroll {
  container: rules-table / inline-size;
}

@container rules-table (max-width: 1100px) {
  .col-path {
    display: none;
  }
}

@container rules-table (max-width: 700px) {
  .col-logsource {
    display: none;
  }

  .rules-table th,
  .rules-table td {
    padding-inline: var(--spacing-sm);
  }
}
</style>
