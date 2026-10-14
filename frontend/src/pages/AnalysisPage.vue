<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Notify } from 'quasar'
import { useRoute, useRouter } from 'vue-router'
import AnalysisHeader from '@/components/AnalysisHeader.vue'
import AnalysisSummaryTab from '@/components/AnalysisSummaryTab.vue'
import AnalysisTabs from '@/components/AnalysisTabs.vue'
import QueryHeader from '@/components/QueryHeader.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { TAB_VIEWS } from '@/components/tabs'
import { useAnalysisTabNavigation } from '@/composables/use-analysis-tab-navigation'
import { useQueryUrlSync } from '@/composables/use-query-url-sync'
import { DEFAULT_TAB, LIVE_TAB, arrivalNote, isQueryableTab, nextLiveSession } from '@/services/analysis-tabs'
import { confirmDestructive } from '@/services/confirm'
import { deleteConfirmation } from '@/services/delete-confirmation'
import { NOT_FOUND_STATUS } from '@/services/quiet-statuses'
import { useAnalysesStore } from '@/stores/analyses'

const route = useRoute()
const router = useRouter()
const store = useAnalysesStore()
const { openTab } = useAnalysisTabNavigation()

const acting = ref(false)

const analysisId = computed(() => (/^\d+$/.test(String(route.params.id)) ? Number(route.params.id) : undefined))
const requestedTab = computed(() => (typeof route.params.tab === 'string' && route.params.tab) || undefined)
const analysis = computed(() => (store.current?.id === analysisId.value ? store.current : undefined))
const liveSession = ref(false)
const activeTab = computed(() => requestedTab.value ?? (liveSession.value ? LIVE_TAB : DEFAULT_TAB))
// LIVE asked for outside a live session (an analysis opened already finished) is not offered: SUMMARY shows instead.
const viewTab = computed(() => (activeTab.value === LIVE_TAB && !liveSession.value ? DEFAULT_TAB : activeTab.value))
const loadFailed = computed(() => store.loadError !== undefined && !store.loading)
const showQueryBar = computed(
  () => isQueryableTab(viewTab.value) && TAB_VIEWS[viewTab.value] !== undefined && analysis.value?.status === 'done',
)
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
  void openTab(tab)
}

useQueryUrlSync(() => analysisId.value)

watch(analysisId, () => (liveSession.value = false), { flush: 'sync' })
watch(analysis, (current) => (liveSession.value = nextLiveSession(liveSession.value, current)), {
  immediate: true,
  flush: 'sync',
})
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
        :live="liveSession"
        @select="selectTab"
      />
      <QueryHeader
        v-if="showQueryBar"
        :analysis-id="analysis.id"
      />
      <AnalysisSummaryTab
        v-if="viewTab === DEFAULT_TAB"
        :analysis="analysis"
      />
      <component
        :is="TAB_VIEWS[LIVE_TAB]"
        v-else-if="viewTab === LIVE_TAB"
        :key="analysis.id"
        :analysis="analysis"
        @open-tab="selectTab"
      />
      <template v-else-if="TAB_VIEWS[viewTab]">
        <component
          :is="TAB_VIEWS[viewTab]"
          v-if="analysis.status === 'done'"
          :analysis="analysis"
        />
        <TerminalEmpty
          v-else
          message="available once the analysis is done"
        />
      </template>
      <TerminalEmpty
        v-else
        :message="arrivalNote(viewTab)"
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
