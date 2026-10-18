<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { viewsIocs, type IocType } from '@/api'
import CopyButton from '@/components/CopyButton.vue'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { t } from '@/i18n'
import { iocFilters } from '@/services/events-filters'

const IOC_TYPES: IocType[] = ['hash', 'domain', 'ip', 'url', 'mutex', 'registry', 'file']

const props = defineProps<{ analysisId: number }>()
const emit = defineEmits<{ counted: [count: number | undefined] }>()

const { data, loading, error, reload } = useAnalysisView(
  () => props.analysisId,
  (id) => viewsIocs({ path: { analysis_id: id } }),
)

const selectedType = ref<IocType>()

const iocs = computed(() => data.value?.iocs ?? [])
const typeCounts = computed(() =>
  IOC_TYPES.map((type) => ({ type, count: iocs.value.filter((ioc) => ioc.type === type).length })).filter(
    ({ count }) => count > 0,
  ),
)
const shown = computed(() => (selectedType.value ? iocs.value.filter((ioc) => ioc.type === selectedType.value) : iocs.value))

function toggleType(type: IocType): void {
  selectedType.value = selectedType.value === type ? undefined : type
}

watch(() => data.value?.iocs.length, (count) => emit('counted', count), { immediate: true })
watch(() => props.analysisId, () => {
  selectedType.value = undefined
})
</script>

<template>
  <ViewState
    :loading="loading"
    :error="error"
    :empty="iocs.length === 0 && data !== undefined"
    :empty-message="t('artifacts.empty.iocs')"
    @retry="reload"
  >
    <template v-if="data">
      <div
        class="type-chips"
        role="group"
        :aria-label="t('artifacts.iocs.filterByType')"
      >
        <button
          type="button"
          class="type-chip text-mono"
          :aria-pressed="selectedType === undefined"
          @click="selectedType = undefined"
        >
          {{ t('artifacts.iocs.all', { count: iocs.length }) }}
        </button>
        <button
          v-for="{ type, count } in typeCounts"
          :key="type"
          type="button"
          class="type-chip text-mono"
          :aria-pressed="selectedType === type"
          @click="toggleType(type)"
        >
          {{ t('artifacts.iocs.typeCount', { type, count }) }}
        </button>
      </div>
      <p
        v-if="data.truncated_types.length"
        class="truncated-note text-mono text-gray"
      >
        {{ t('artifacts.iocs.cutShort', { types: data.truncated_types.join(', ') }) }}
      </p>
      <div class="tt-table-scroll">
        <table class="tt-table text-mono">
          <thead>
            <tr>
              <th>{{ t('artifacts.column.type') }}</th>
              <th>{{ t('artifacts.column.value') }}</th>
              <th class="num">
                {{ t('artifacts.column.count') }}
              </th>
              <th>{{ t('artifacts.column.context') }}</th>
              <th>{{ t('artifacts.column.process') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ioc in shown"
              :key="`${ioc.type}:${ioc.value}`"
            >
              <td>{{ ioc.type }}</td>
              <td>
                <span
                  class="cell-value"
                  :title="ioc.value"
                >{{ ioc.value }}</span>
                <CopyButton
                  :text="ioc.value"
                  :what="t('artifacts.iocs.indicatorNoun')"
                />
                <FilterEventsButton :target="{ chips: iocFilters(ioc.type, ioc.value) }" />
              </td>
              <td class="num cell-count">
                {{ ioc.count }}
              </td>
              <td>
                <span
                  class="cell-context"
                  :title="ioc.context"
                >{{ ioc.context }}</span>
              </td>
              <td>
                <ProcessChip :process="ioc.process" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </ViewState>
</template>

<style scoped>
.tt-table th,
.tt-table td {
  padding-inline: var(--spacing-sm);
}

.type-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-sm);
}

.type-chip {
  padding: var(--spacing-xs) var(--spacing-sm);
  border: 1px solid var(--border-secondary);
  background: var(--black);
  color: var(--blue-light);
  font-size: 0.75rem;
  cursor: pointer;
  transition: background-color var(--transition-fast), color var(--transition-fast);
}

.type-chip:hover {
  background: var(--hover-bg);
}

.type-chip[aria-pressed='true'] {
  border-color: var(--blue-primary);
  background: var(--blue-dark);
  color: var(--text-white);
}

.truncated-note {
  margin: 0 0 var(--spacing-sm);
  font-size: 0.75rem;
}

.cell-value,
.cell-context {
  display: inline-block;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}

.cell-value {
  max-width: min(44ch, 40vw);
}

.cell-context {
  max-width: min(34ch, 30vw);
}
</style>
