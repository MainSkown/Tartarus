<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Notify } from 'quasar'
import { useRouter } from 'vue-router'
import type { AnalysisStatus } from '@/api'
import AnalysesTable from '@/components/AnalysesTable.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { ANALYSIS_STATUSES, analysisStatusMeta } from '@/services/analysis-status'
import { confirmDestructive } from '@/services/confirm'
import { deleteConfirmation } from '@/services/delete-confirmation'
import { openSubmitDialog } from '@/services/submit-dialog'
import { useAnalysesStore, type AnalysisListQuery } from '@/stores/analyses'
import { useSystemStore } from '@/stores/system'

const SEARCH_DEBOUNCE_MS = 300

const STATUS_OPTIONS = ANALYSIS_STATUSES.map((status) => ({
  value: status,
  label: analysisStatusMeta(status).label,
}))

const analyses = useAnalysesStore()
const system = useSystemStore()
const router = useRouter()

const search = ref('')
const status = ref<AnalysisStatus | null>(null)

const filtered = computed(() => search.value.trim() !== '' || status.value !== null)
const listQuery = computed<AnalysisListQuery>(() => ({
  ...(search.value.trim() && { q: search.value.trim() }),
  ...(status.value && { status: status.value }),
}))

const guestKnownNotReady = computed(() => system.health !== undefined && !system.guestReady)
const showLoader = computed(() => analyses.loading && analyses.items.length === 0 && !analyses.loadError)
const showEmpty = computed(
  () => !analyses.loading && !analyses.loadError && analyses.items.length === 0,
)
const showTable = computed(() => !analyses.loadError && analyses.items.length > 0)

let filterTimer: ReturnType<typeof setTimeout> | undefined

function reload(): void {
  void analyses.fetchList(listQuery.value)
}

function clearFilters(): void {
  search.value = ''
  status.value = null
}

watch(listQuery, () => {
  clearTimeout(filterTimer)
  filterTimer = setTimeout(reload, SEARCH_DEBOUNCE_MS)
})

function openAnalysis(id: number): void {
  void router.push({ name: 'analysis-workspace', params: { id } })
}

function filenameOf(id: number): string {
  return analyses.items.find((item) => item.id === id)?.filename ?? ''
}

async function deleteAnalysis(id: number): Promise<void> {
  const analysis = analyses.items.find((item) => item.id === id)
  if (!analysis) return
  const confirmed = await confirmDestructive(deleteConfirmation(analysis))
  if (!confirmed) return
  if (!(await analyses.remove(id))) Notify.create({ type: 'tt-error', message: `Could not delete #${id}` })
}

async function cancelAnalysis(id: number): Promise<void> {
  const confirmed = await confirmDestructive({
    title: `Cancel #${id}`,
    message: `Stop the analysis of ${filenameOf(id)}? A cancelled run cannot be resumed.`,
    confirmLabel: 'CANCEL ANALYSIS',
  })
  if (!confirmed) return
  if (!(await analyses.cancel(id))) Notify.create({ type: 'tt-error', message: `Could not cancel #${id}` })
}

reload()
onMounted(analyses.startPolling)
onUnmounted(() => {
  clearTimeout(filterTimer)
  analyses.stopPolling()
})
</script>

<template>
  <div class="dashboard-page">
    <div class="dashboard-header">
      <h1 class="section-title text-mono">
        ANALYSES
      </h1>
      <div class="dashboard-filters">
        <q-input
          v-model="search"
          outlined
          dense
          hide-bottom-space
          clearable
          placeholder="search name or hash"
          aria-label="Search analyses"
          class="search-input text-mono"
        >
          <template #prepend>
            <q-icon name="search" />
          </template>
        </q-input>
        <q-select
          v-model="status"
          :options="STATUS_OPTIONS"
          outlined
          dense
          hide-bottom-space
          clearable
          emit-value
          map-options
          label="STATUS"
          class="status-select text-mono"
        />
      </div>
    </div>

    <div
      v-if="showLoader"
      class="page-state"
    >
      <span
        class="loader"
        role="status"
        aria-label="Loading analyses"
      />
    </div>

    <div
      v-else-if="analyses.loadError"
      class="page-state text-mono"
    >
      <p class="text-gray">
        &gt; failed to load: {{ analyses.loadError }}
      </p>
      <q-btn
        outline
        square
        label="[RETRY]"
        class="retry-btn text-mono"
        @click="reload"
      />
    </div>

    <div
      v-else-if="showEmpty"
      class="page-state text-mono"
    >
      <template v-if="filtered">
        <TerminalEmpty message="no analyses match" />
        <q-btn
          outline
          square
          label="[CLEAR FILTERS]"
          class="clear-filters-btn text-mono"
          @click="clearFilters"
        />
      </template>
      <template v-else-if="guestKnownNotReady">
        <TerminalEmpty message="guest VM not ready" />
        <p class="empty-reason text-gray">
          {{ system.guestMessage }}
        </p>
        <q-btn
          outline
          square
          label="[BUILD GUEST]"
          class="build-guest-btn text-mono"
          @click="router.push({ name: 'guest' })"
        />
      </template>
      <template v-else>
        <TerminalEmpty message="no analyses yet" />
        <q-btn
          outline
          square
          label="[+ SUBMIT SAMPLE]"
          class="submit-btn text-mono"
          @click="openSubmitDialog"
        />
      </template>
    </div>

    <template v-if="showTable">
      <AnalysesTable
        :analyses="analyses.items"
        @open="openAnalysis"
        @cancel="cancelAnalysis"
        @remove="deleteAnalysis"
      />
      <p
        v-if="analyses.total > analyses.items.length"
        class="list-footer text-mono text-gray"
      >
        showing {{ analyses.items.length }} of {{ analyses.total }}
      </p>
    </template>
  </div>
</template>

<style scoped>
.dashboard-page {
  padding: var(--spacing-lg);
}

.dashboard-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.section-title {
  color: var(--blue-primary);
  font-size: 0.9rem;
  /* Quasar's typography gives h1 a 6rem line-height, which shrinking the font doesn't undo. */
  line-height: 1.2;
  letter-spacing: 2px;
  margin: 0;
}

.dashboard-filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-md);
}

.search-input {
  width: 260px;
  max-width: 100%;
}

.status-select {
  width: 180px;
  max-width: 100%;
}

.page-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-xl) 0;
}

.page-state :deep(.terminal-empty) {
  padding: 0;
}

.empty-reason {
  margin: 0;
  max-width: 60ch;
  text-align: center;
  overflow-wrap: anywhere;
}

.retry-btn,
.submit-btn,
.build-guest-btn,
.clear-filters-btn {
  color: var(--blue-primary);
}

.list-footer {
  margin: var(--spacing-sm) 0 0;
  font-size: 0.75rem;
}
</style>
