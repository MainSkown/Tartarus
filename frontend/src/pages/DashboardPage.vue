<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Notify } from 'quasar'
import { useRouter } from 'vue-router'
import type { AnalysisStatus } from '@/api'
import AnalysesTable from '@/components/AnalysesTable.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { t } from '@/i18n'
import { ANALYSIS_STATUSES, analysisStatusMeta } from '@/services/analysis-status'
import { confirmDestructive } from '@/services/confirm'
import { deleteConfirmation } from '@/services/delete-confirmation'
import { openSubmitDialog } from '@/services/submit-dialog'
import { useAnalysesStore, type AnalysisListQuery } from '@/stores/analyses'
import { useTagsStore } from '@/stores/tags'
import { useSystemStore } from '@/stores/system'

const SEARCH_DEBOUNCE_MS = 300

const STATUS_OPTIONS = ANALYSIS_STATUSES.map((status) => ({
  value: status,
  label: analysisStatusMeta(status).label,
}))

const analyses = useAnalysesStore()
const tags = useTagsStore()
const system = useSystemStore()
const router = useRouter()

const search = ref('')
const status = ref<AnalysisStatus | null>(null)
const tag = ref<string | null>(null)

const tagOptions = computed(() => tags.items.map(({ name, count }) => ({ value: name, label: t('dashboard.filter.tagOption', { name, count }) })))
const filtered = computed(() => search.value.trim() !== '' || status.value !== null || tag.value !== null)
const listQuery = computed<AnalysisListQuery>(() => ({
  ...(search.value.trim() && { q: search.value.trim() }),
  ...(status.value && { status: status.value }),
  ...(tag.value && { tag: tag.value }),
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
  tag.value = null
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
  if (!(await analyses.remove(id))) Notify.create({ type: 'tt-error', message: t('dashboard.notice.deleteFailed', { id }) })
}

async function reingestAnalysis(id: number): Promise<void> {
  // A refusal (409 while another analysis is active) was already toasted with the backend's reason.
  if (await analyses.reingest(id)) Notify.create({ type: 'tt-info', message: t('dashboard.notice.reingesting', { id }) })
}

async function cancelAnalysis(id: number): Promise<void> {
  const confirmed = await confirmDestructive({
    title: t('dashboard.cancel.title', { id }),
    message: t('dashboard.cancel.message', { filename: filenameOf(id) }),
    confirmLabel: t('dashboard.cancel.confirm'),
  })
  if (!confirmed) return
  if (!(await analyses.cancel(id))) Notify.create({ type: 'tt-error', message: t('dashboard.notice.cancelFailed', { id }) })
}

reload()
void tags.load()
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
        {{ t('dashboard.title') }}
      </h1>
      <div class="dashboard-filters">
        <q-input
          v-model="search"
          outlined
          dense
          hide-bottom-space
          clearable
          :placeholder="t('dashboard.search.placeholder')"
          :aria-label="t('dashboard.search.label')"
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
          :label="t('dashboard.filter.status')"
          class="status-select text-mono"
        />
        <q-select
          v-model="tag"
          :options="tagOptions"
          outlined
          dense
          hide-bottom-space
          clearable
          emit-value
          map-options
          :label="t('dashboard.filter.tag')"
          :display-value="tag ?? undefined"
          menu-anchor="bottom right"
          menu-self="top right"
          popup-content-class="tag-select-menu"
          class="tag-select text-mono"
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
        :aria-label="t('dashboard.loading')"
      />
    </div>

    <div
      v-else-if="analyses.loadError"
      class="page-state text-mono"
    >
      <p class="text-gray">
        {{ t('dashboard.loadFailed', { error: analyses.loadError }) }}
      </p>
      <q-btn
        outline
        square
        :label="t('common.retry')"
        class="retry-btn text-mono"
        @click="reload"
      />
    </div>

    <div
      v-else-if="showEmpty"
      class="page-state text-mono"
    >
      <template v-if="filtered">
        <TerminalEmpty :message="t('dashboard.empty.noMatches')" />
        <q-btn
          outline
          square
          :label="t('dashboard.empty.clearFilters')"
          class="clear-filters-btn text-mono"
          @click="clearFilters"
        />
      </template>
      <template v-else-if="guestKnownNotReady">
        <TerminalEmpty :message="t('dashboard.empty.guestNotReady')" />
        <p class="empty-reason text-gray">
          {{ system.guestMessage }}
        </p>
        <q-btn
          outline
          square
          :label="t('dashboard.empty.buildGuest')"
          class="build-guest-btn text-mono"
          @click="router.push({ name: 'guest' })"
        />
      </template>
      <template v-else>
        <TerminalEmpty :message="t('dashboard.empty.none')" />
        <q-btn
          outline
          square
          :label="t('dashboard.empty.submitSample')"
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
        @reingest="reingestAnalysis"
        @remove="deleteAnalysis"
      />
      <p
        v-if="analyses.total > analyses.items.length"
        class="list-footer text-mono text-gray"
      >
        {{ t('dashboard.showing', { shown: analyses.items.length, total: analyses.total }) }}
      </p>
    </template>
  </div>
</template>

<!-- Not scoped: the options menu is teleported out of the page. -->
<style>
/* The filter sits at the right edge: the menu opens leftwards from it, and a 40-character tag may not widen it past the window. */
.tag-select-menu {
  max-width: min(22rem, 90vw);
}

.tag-select-menu .q-item__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

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

.status-select,
.tag-select {
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
