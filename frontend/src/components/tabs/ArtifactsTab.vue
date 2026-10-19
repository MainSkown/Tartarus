<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { viewsArtifacts, type AnalysisRead } from '@/api'
import ArtifactConfigs from '@/components/ArtifactConfigs.vue'
import ArtifactIocs from '@/components/ArtifactIocs.vue'
import ArtifactMemory from '@/components/ArtifactMemory.vue'
import ArtifactRegistry from '@/components/ArtifactRegistry.vue'
import ArtifactTable from '@/components/ArtifactTable.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { t } from '@/i18n'

type SubTabKey = 'dropped' | 'payloads' | 'dumps' | 'memory' | 'registry' | 'iocs'

const props = defineProps<{ analysis: AnalysisRead }>()

const active = ref<SubTabKey>('dropped')
const opened = reactive(new Set<SubTabKey>(['dropped']))
const memoryCount = ref<number>()
const registryCount = ref<number>()
const iocCount = ref<number>()

const { data, loading, error, reload } = useAnalysisView(
  () => props.analysis.id,
  (id) => viewsArtifacts({ path: { analysis_id: id } }),
)

const memory = computed(() => props.analysis.summary?.memory ?? null)
// The findings count belongs on the sub-tab before it is opened, as the dropped files' does.
const loadMemoryAtOnce = computed(() => memory.value?.findings === 'ok')

const subTabs = computed<{ key: SubTabKey; label: string; count: number | undefined }[]>(() => [
  { key: 'dropped', label: t('artifacts.tabs.droppedFiles'), count: data.value?.dropped.length },
  { key: 'payloads', label: t('artifacts.tabs.payloadsAndConfigs'), count: data.value?.payloads.length },
  { key: 'dumps', label: t('artifacts.tabs.processDumps'), count: data.value?.procdumps.length },
  { key: 'memory', label: t('artifacts.tabs.memory'), count: memoryCount.value },
  { key: 'registry', label: t('artifacts.tabs.registry'), count: registryCount.value },
  { key: 'iocs', label: t('artifacts.tabs.iocs'), count: iocCount.value },
])

function tabLabel(tab: { label: string; count: number | undefined }): string {
  return tab.count === undefined ? tab.label : t('artifacts.tabs.withCount', { label: tab.label, count: tab.count })
}

function select(key: SubTabKey): void {
  opened.add(key)
  active.value = key
}

const noPayloads = computed(() => data.value?.payloads.length === 0 && data.value.configs.length === 0)
const noDumps = computed(() => data.value?.procdumps.length === 0)
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
        :label="tabLabel(tab)"
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
        :empty-message="t('artifacts.empty.droppedFiles')"
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
        :empty-message="t('artifacts.empty.payloadsAndConfigs')"
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
        :empty-message="t('artifacts.empty.processDumps')"
        @retry="reload"
      >
        <ArtifactTable
          v-if="data?.procdumps.length"
          :analysis-id="analysis.id"
          :artifacts="data.procdumps"
        />
      </ViewState>
    </div>

    <div
      v-if="opened.has('memory') || loadMemoryAtOnce"
      v-show="active === 'memory'"
      class="artifact-panel"
    >
      <ArtifactMemory
        :analysis-id="analysis.id"
        :memory="memory"
        :dump="data?.memory_dump ?? null"
        :artifacts-loading="loading"
        :artifacts-error="error"
        @counted="memoryCount = $event"
        @retry-artifacts="reload"
      />
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

.artifact-panel {
  min-width: 0;
}
</style>
