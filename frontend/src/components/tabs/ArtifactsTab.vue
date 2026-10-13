<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { viewsArtifacts, type AnalysisRead } from '@/api'
import ArtifactConfigs from '@/components/ArtifactConfigs.vue'
import ArtifactIocs from '@/components/ArtifactIocs.vue'
import ArtifactRegistry from '@/components/ArtifactRegistry.vue'
import ArtifactTable from '@/components/ArtifactTable.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'

type SubTabKey = 'dropped' | 'payloads' | 'dumps' | 'registry' | 'iocs'

const props = defineProps<{ analysis: AnalysisRead }>()

const active = ref<SubTabKey>('dropped')
const opened = reactive(new Set<SubTabKey>(['dropped']))
const registryCount = ref<number>()
const iocCount = ref<number>()

const { data, loading, error, reload } = useAnalysisView(
  () => props.analysis.id,
  (id) => viewsArtifacts({ path: { analysis_id: id } }),
)

const dumpCount = computed(() => data.value && data.value.procdumps.length + (data.value.memory_dump ? 1 : 0))

const subTabs = computed<{ key: SubTabKey; label: string; count: number | undefined }[]>(() => [
  { key: 'dropped', label: 'DROPPED FILES', count: data.value?.dropped.length },
  { key: 'payloads', label: 'PAYLOADS & CONFIGS', count: data.value?.payloads.length },
  { key: 'dumps', label: 'PROCESS DUMPS', count: dumpCount.value },
  { key: 'registry', label: 'REGISTRY', count: registryCount.value },
  { key: 'iocs', label: 'IOCs', count: iocCount.value },
])

function select(key: SubTabKey): void {
  opened.add(key)
  active.value = key
}

const noPayloads = computed(() => data.value?.payloads.length === 0 && data.value.configs.length === 0)
const noDumps = computed(() => dumpCount.value === 0)
</script>

<template>
  <section
    data-tab="artifacts"
    class="artifacts-tab"
  >
    <q-tabs
      :model-value="active"
      dense
      align="left"
      no-caps
      inline-label
      outside-arrows
      mobile-arrows
      class="artifact-sub-tabs"
      @update:model-value="select"
    >
      <q-tab
        v-for="tab in subTabs"
        :key="tab.key"
        :name="tab.key"
        :label="tab.count === undefined ? tab.label : `${tab.label} (${tab.count})`"
      />
    </q-tabs>

    <div
      v-show="active === 'dropped'"
      class="artifact-panel"
    >
      <ViewState
        :loading="loading"
        :error="error"
        :empty="data?.dropped.length === 0"
        empty-message="no files were dropped"
        @retry="reload"
      >
        <ArtifactTable
          v-if="data"
          :analysis-id="analysis.id"
          :artifacts="data.dropped"
        />
      </ViewState>
    </div>

    <div
      v-show="active === 'payloads'"
      class="artifact-panel"
    >
      <ViewState
        :loading="loading"
        :error="error"
        :empty="noPayloads"
        empty-message="no payloads or configs were extracted"
        @retry="reload"
      >
        <template v-if="data">
          <ArtifactTable
            v-if="data.payloads.length"
            :analysis-id="analysis.id"
            :artifacts="data.payloads"
            show-family
          />
          <ArtifactConfigs :configs="data.configs" />
        </template>
      </ViewState>
    </div>

    <div
      v-show="active === 'dumps'"
      class="artifact-panel"
    >
      <ViewState
        :loading="loading"
        :error="error"
        :empty="noDumps"
        empty-message="no process or memory dumps were captured"
        @retry="reload"
      >
        <template v-if="data">
          <ArtifactTable
            v-if="data.procdumps.length"
            :analysis-id="analysis.id"
            :artifacts="data.procdumps"
          />
          <template v-if="data.memory_dump">
            <h3 class="memory-heading text-mono">
              MEMORY DUMP
            </h3>
            <ArtifactTable
              :analysis-id="analysis.id"
              :artifacts="[data.memory_dump]"
            />
          </template>
        </template>
      </ViewState>
    </div>

    <div
      v-if="opened.has('registry')"
      v-show="active === 'registry'"
      class="artifact-panel"
    >
      <ArtifactRegistry
        :analysis-id="analysis.id"
        @counted="registryCount = $event"
      />
    </div>

    <div
      v-if="opened.has('iocs')"
      v-show="active === 'iocs'"
      class="artifact-panel"
    >
      <ArtifactIocs
        :analysis-id="analysis.id"
        @counted="iocCount = $event"
      />
    </div>
  </section>
</template>

<style scoped>
.artifacts-tab {
  min-width: 0;
  padding: var(--spacing-md) var(--spacing-lg);
}

.artifact-sub-tabs {
  margin-bottom: var(--spacing-md);
  border-bottom: 2px solid var(--border-primary);
}

.memory-heading {
  margin: var(--spacing-md) 0 var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 1px;
}

.artifact-panel {
  min-width: 0;
}
</style>
