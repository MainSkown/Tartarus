<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Notify } from 'quasar'
import { useRoute, useRouter } from 'vue-router'
import AnalysisHeader from '@/components/AnalysisHeader.vue'
import AnalysisSummaryTab from '@/components/AnalysisSummaryTab.vue'
import AnalysisTabs from '@/components/AnalysisTabs.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { DEFAULT_TAB } from '@/services/analysis-tabs'
import { confirmDestructive } from '@/services/confirm'
import { deleteConfirmation } from '@/services/delete-confirmation'
import { NOT_FOUND_STATUS } from '@/services/quiet-statuses'
import { useAnalysesStore } from '@/stores/analyses'

const route = useRoute()
const router = useRouter()
const store = useAnalysesStore()

const acting = ref(false)

const analysisId = computed(() => (/^\d+$/.test(String(route.params.id)) ? Number(route.params.id) : undefined))
const activeTab = computed(() => (typeof route.params.tab === 'string' && route.params.tab) || DEFAULT_TAB)
const analysis = computed(() => (store.current?.id === analysisId.value ? store.current : undefined))
const loadFailed = computed(() => store.loadError !== undefined && !store.loading)
const notFound = computed(
  () => analysisId.value === undefined || (loadFailed.value && store.loadErrorStatus === NOT_FOUND_STATUS),
)

async function load(): Promise<void> {
  if (analysisId.value === undefined) return
  store.startPolling()
  await store.fetchOne(analysisId.value)
}

async function perform(action: (id: number) => Promise<boolean>, failureMessage: string): Promise<boolean> {
  if (analysisId.value === undefined) return false
  acting.value = true
  const succeeded = await action(analysisId.value)
  acting.value = false
  if (!succeeded) Notify.create({ type: 'tt-error', message: failureMessage })
  return succeeded
}

async function cancelAnalysis(): Promise<void> {
  await perform(store.cancel, 'Could not cancel the analysis')
}

async function deleteAnalysis(): Promise<void> {
  if (!analysis.value) return
  const confirmed = await confirmDestructive(deleteConfirmation(analysis.value))
  if (!confirmed) return
  if (await perform(store.remove, 'Could not delete the analysis')) await router.push({ name: 'dashboard' })
}

function selectTab(tab: string): void {
  void router.push({ name: 'analysis-workspace', params: { id: String(analysisId.value), tab } })
}

watch(analysisId, load)
onMounted(load)
onBeforeUnmount(store.stopPolling)
</script>

<template>
  <div class="analysis-page">
    <TerminalEmpty
      v-if="notFound"
      message="analysis not found"
    />

    <template v-else-if="analysis">
      <AnalysisHeader
        :analysis="analysis"
        :busy="acting"
        @cancel="cancelAnalysis"
        @delete="deleteAnalysis"
      />
      <AnalysisTabs
        :active="activeTab"
        @select="selectTab"
      />
      <AnalysisSummaryTab
        v-if="activeTab === DEFAULT_TAB"
        :analysis="analysis"
      />
      <TerminalEmpty
        v-else
        :message="`${activeTab} arrives with M1b`"
      />
    </template>

    <div
      v-else-if="loadFailed"
      class="page-state text-mono"
    >
      <p class="text-gray">
        &gt; failed to load: {{ store.loadError }}
      </p>
      <q-btn
        outline
        square
        label="[RETRY]"
        class="retry-btn text-mono"
        @click="load"
      />
    </div>

    <div
      v-else
      class="page-state"
    >
      <span
        class="loader"
        role="status"
        aria-label="Loading analysis"
      />
    </div>
  </div>
</template>

<style scoped>
.analysis-page {
  min-width: 0;
}

.page-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-xl) 0;
}

.retry-btn {
  color: var(--blue-primary);
}
</style>
