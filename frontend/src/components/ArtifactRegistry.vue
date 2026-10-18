<script setup lang="ts">
import { watch } from 'vue'
import { viewsRegistry } from '@/api'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { t } from '@/i18n'
import { registryChangeFilters } from '@/services/events-filters'
import { formatTimestamp } from '@/services/format-time'

const OPEN_ALL_UP_TO_KEYS = 10

const props = defineProps<{ analysisId: number }>()
const emit = defineEmits<{ counted: [count: number | undefined] }>()

const { data, loading, error, reload } = useAnalysisView(
  () => props.analysisId,
  (id) => viewsRegistry({ path: { analysis_id: id } }),
)

watch(() => data.value?.total, (total) => emit('counted', total), { immediate: true })

function groupTitle(group: { hive: string | null; key: string }): string {
  return group.hive ? `${group.hive}\\${group.key}` : group.key
}
</script>

<template>
  <ViewState
    :loading="loading"
    :error="error"
    :empty="data?.keys.length === 0"
    :empty-message="t('artifacts.empty.registry')"
    @retry="reload"
  >
    <template v-if="data">
      <details
        v-for="group in data.keys"
        :key="`${group.hive}\\${group.key}`"
        class="registry-group"
        :open="data.keys.length <= OPEN_ALL_UP_TO_KEYS"
      >
        <summary class="group-summary text-mono">
          <span
            class="group-title"
            :title="groupTitle(group)"
          >{{ groupTitle(group) }}</span>
          <span class="group-count">{{ t('artifacts.registry.changes', group.changes.length) }}</span>
        </summary>
        <div class="tt-table-scroll">
          <table class="tt-table text-mono">
            <thead>
              <tr>
                <th>{{ t('artifacts.column.action') }}</th>
                <th>{{ t('artifacts.column.value') }}</th>
                <th>{{ t('artifacts.column.type') }}</th>
                <th>{{ t('artifacts.column.data') }}</th>
                <th>{{ t('artifacts.column.process') }}</th>
                <th>{{ t('artifacts.column.time') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="change in group.changes"
                :key="change.event_id"
              >
                <td>
                  {{ change.action }}
                  <FilterEventsButton :target="{ chips: registryChangeFilters({ hive: group.hive, key: group.key, value_name: change.value_name }) }" />
                </td>
                <td>
                  <span
                    v-if="change.value_name"
                    class="cell-clip"
                    :title="change.value_name"
                  >{{ change.value_name }}</span>
                  <span
                    v-else
                    class="cell-empty"
                  >–</span>
                </td>
                <td>
                  <template v-if="change.data_type">
                    {{ change.data_type }}
                  </template>
                  <span
                    v-else
                    class="cell-empty"
                  >–</span>
                </td>
                <td>
                  <span
                    v-if="change.data.length"
                    class="cell-clip"
                    :title="change.data.join(', ')"
                  >{{ change.data.join(', ') }}</span>
                  <span
                    v-else
                    class="cell-empty"
                  >–</span>
                </td>
                <td>
                  <ProcessChip :process="change.process" />
                </td>
                <td>{{ formatTimestamp(change.time) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </template>
  </ViewState>
</template>

<style scoped>
.registry-group + .registry-group {
  margin-top: var(--spacing-sm);
}

.group-summary {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
  cursor: pointer;
  list-style: none;
}

.group-summary::-webkit-details-marker {
  display: none;
}

.group-summary::before {
  content: '▸';
  color: var(--blue-primary);
}

.registry-group[open] > .group-summary::before {
  content: '▾';
}

.group-summary:hover,
.group-summary:focus-visible {
  background: var(--hover-bg);
  outline: none;
}

.group-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-count {
  flex: none;
  margin-left: auto;
  color: var(--text-gray);
}

.registry-group[open] > .group-summary {
  border-bottom: none;
}

.cell-clip {
  display: block;
  max-width: min(40ch, 40vw);
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
