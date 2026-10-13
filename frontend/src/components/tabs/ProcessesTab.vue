<script setup lang="ts">
import { computed, ref } from 'vue'
import { viewsProcesses, type AnalysisRead } from '@/api'
import ProcessDetails from '@/components/ProcessDetails.vue'
import ProcessGraph from '@/components/ProcessGraph.vue'
import ProcessTreeList from '@/components/ProcessTreeList.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { flattenProcesses, injectionPeers, resolveSelection } from '@/services/process-graph'

type Mode = 'graph' | 'tree'

const MODES = [
  { label: 'GRAPH', value: 'graph' },
  { label: 'TREE', value: 'tree' },
]

const props = defineProps<{ analysis: AnalysisRead }>()

const view = useAnalysisView(
  () => props.analysis.id,
  (id) => viewsProcesses({ path: { analysis_id: id } }),
)

const mode = ref<Mode>('graph')
const chosenId = ref<string>()

const roots = computed(() => view.data.value?.roots ?? [])
const selectedId = computed(() => resolveSelection(roots.value, chosenId.value))
const selected = computed(() => flattenProcesses(roots.value).find((process) => process.entity_id === selectedId.value))
const peers = computed(() => (selected.value ? injectionPeers(roots.value, selected.value) : { into: [], from: [] }))
</script>

<template>
  <section
    class="processes-tab"
    data-tab="processes"
  >
    <ViewState
      :loading="view.loading.value"
      :error="view.error.value"
      :empty="roots.length === 0"
      empty-message="no processes recorded"
      @retry="view.reload"
    >
      <div class="processes-tab__bar">
        <span class="processes-tab__count text-mono">{{ view.data.value?.total }} PROCESSES</span>
        <q-btn-toggle
          v-model="mode"
          :options="MODES"
          unelevated
          square
          no-caps
          class="processes-tab__mode text-mono"
          aria-label="Process view"
        />
      </div>
      <div class="processes-tab__body">
        <div class="processes-tab__main">
          <ProcessGraph
            v-if="mode === 'graph'"
            :roots="roots"
            :selected-id="selectedId"
            @select="chosenId = $event"
          />
          <ProcessTreeList
            v-else
            :roots="roots"
            :selected-id="selectedId"
            @select="chosenId = $event"
          />
        </div>
        <ProcessDetails
          v-if="selected"
          :key="selected.entity_id"
          class="processes-tab__details"
          :analysis-id="analysis.id"
          :node="selected"
          :injected-into="peers.into"
          :injected-from="peers.from"
        />
      </div>
    </ViewState>
  </section>
</template>

<style scoped>
.processes-tab {
  min-width: 0;
  padding: var(--spacing-lg);
}

.processes-tab__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-md);
}

.processes-tab__count {
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 2px;
}

.processes-tab__mode {
  border: 2px solid var(--border-primary);
}

.processes-tab__body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: var(--spacing-md);
  align-items: start;
}

.processes-tab__main {
  min-width: 0;
}

@media (max-width: 900px) {
  .processes-tab__body {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
