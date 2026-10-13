<script setup lang="ts">
import { computed, ref } from 'vue'
import { viewsProcesses, type AnalysisRead } from '@/api'
import ProcessDetails from '@/components/ProcessDetails.vue'
import ProcessGraph from '@/components/ProcessGraph.vue'
import ProcessTreeList from '@/components/ProcessTreeList.vue'
import ProcessViewSwitch from '@/components/ProcessViewSwitch.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { useViewportFill } from '@/composables/use-viewport-fill'
import { flattenProcesses, injectionPeers, resolveSelection } from '@/services/process-graph'

type Mode = 'graph' | 'tree'

// The tab's own top and bottom padding (2 x spacing-sm), measured from the section top, so the page itself never scrolls.
const BOTTOM_GAP = 16

const props = defineProps<{ analysis: AnalysisRead }>()

const view = useAnalysisView(
  () => props.analysis.id,
  (id) => viewsProcesses({ path: { analysis_id: id } }),
)

const root = ref<HTMLElement>()
const { height: fillHeight } = useViewportFill(root, BOTTOM_GAP)
const mode = ref<Mode>('graph')
const chosenId = ref<string>()

const roots = computed(() => view.data.value?.roots ?? [])
const selectedId = computed(() => resolveSelection(roots.value, chosenId.value))
const selected = computed(() => flattenProcesses(roots.value).find((process) => process.entity_id === selectedId.value))
const peers = computed(() => (selected.value ? injectionPeers(roots.value, selected.value) : { into: [], from: [] }))
</script>

<template>
  <section
    ref="root"
    class="processes-tab"
    data-tab="processes"
    :style="{ '--tab-fill-height': `${fillHeight}px` }"
  >
    <ViewState
      :loading="view.loading.value"
      :error="view.error.value"
      :empty="roots.length === 0"
      empty-message="no processes recorded"
      @retry="view.reload"
    >
      <div class="processes-tab__body">
        <div class="processes-tab__main">
          <ProcessGraph
            v-if="mode === 'graph'"
            :roots="roots"
            :selected-id="selectedId"
            @select="chosenId = $event"
          >
            <template #toolbar-end>
              <ProcessViewSwitch
                v-model="mode"
                :total="view.data.value?.total ?? 0"
              />
            </template>
          </ProcessGraph>
          <template v-else>
            <div class="processes-tab__bar">
              <ProcessViewSwitch
                v-model="mode"
                :total="view.data.value?.total ?? 0"
              />
            </div>
            <ProcessTreeList
              :roots="roots"
              :selected-id="selectedId"
              @select="chosenId = $event"
            />
          </template>
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
  padding: var(--spacing-sm) var(--spacing-lg);
}

.processes-tab__body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: var(--spacing-md);
  height: max(400px, var(--tab-fill-height));
}

.processes-tab__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.processes-tab__bar {
  display: flex;
  padding-bottom: var(--spacing-sm);
}

.processes-tab__details {
  min-height: 0;
}

@media (max-width: 900px) {
  .processes-tab__body {
    grid-template-columns: minmax(0, 1fr);
    height: auto;
  }

  .processes-tab__main {
    height: 30rem;
  }
}
</style>
