<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AnalysisRead } from '@/api'
import AnalysisWarnings from '@/components/AnalysisWarnings.vue'
import EventDetailDrawer from '@/components/EventDetailDrawer.vue'
import EventFacets from '@/components/EventFacets.vue'
import EventTable from '@/components/EventTable.vue'
import { useFacetPanel } from '@/composables/use-facet-panel'
import { useViewportFill } from '@/composables/use-viewport-fill'
import { useEventFacetsStore } from '@/stores/event-facets'
import { useEventsStore } from '@/stores/events'
import { useQueryStateStore } from '@/stores/query-state'

// The tab's own top and bottom padding (2 x spacing-sm), measured from the section top, so the page itself never scrolls.
const BOTTOM_GAP = 16

defineProps<{ analysis: AnalysisRead }>()

const query = useQueryStateStore()
const events = useEventsStore()
const facets = useEventFacetsStore()
const facetPanel = useFacetPanel()

const root = ref<HTMLElement>()
const { height: fillHeight } = useViewportFill(root, BOTTOM_GAP)

// Selection and the open event are two things: the arrow keys move the first through the table, Enter or a click opens the second.
const selectedId = ref<string | null>(query.eventId)
const tableLoading = computed(() => events.loading || (!events.loaded && events.error === undefined))

function select(id: string): void {
  selectedId.value = id
  if (query.eventId !== null) query.openEvent(id)
}

watch(
  () => query.eventId,
  (id) => {
    if (id !== null) selectedId.value = id
  },
)

onMounted(() => {
  events.activate()
  facets.activate()
})
onBeforeUnmount(() => {
  events.deactivate()
  facets.deactivate()
})
</script>

<template>
  <section
    ref="root"
    class="events-tab"
    data-tab="events"
    :style="{ '--tab-fill-height': `${fillHeight}px` }"
  >
    <div
      class="events-tab__body"
      :class="{ 'is-facets-collapsed': !facetPanel.open.value }"
    >
      <EventFacets
        :open="facetPanel.open.value"
        @toggle="facetPanel.toggle"
      />
      <div class="events-tab__main">
        <AnalysisWarnings :warnings="analysis.summary?.warnings" />
        <EventTable
          class="events-tab__table"
          :events="events.events"
          :total="events.total"
          :loading="tableLoading"
          :loading-more="events.loadingMore"
          :has-more="events.hasMore"
          :sort="events.sort"
          :selected-id="selectedId"
          :filtered="!query.isEmpty"
          :error="events.error?.message"
          :load-more-error="events.loadMoreError"
          @select="select"
          @open="query.openEvent"
          @toggle-sort="events.toggleSort"
          @load-more="events.loadMore"
          @retry="events.retry"
          @clear="query.reset"
        />
      </div>
    </div>
    <EventDetailDrawer />
  </section>
</template>

<style scoped>
.events-tab {
  min-width: 0;
  padding: var(--spacing-sm) var(--spacing-lg);
}

/* Below 240px the table stops shrinking and the page scrolls instead; a header, a bar and a few rows still fit. */
.events-tab__body {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: var(--spacing-md);
  height: max(240px, var(--tab-fill-height));
}

.events-tab__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.events-tab__main > .events-tab__table {
  flex: 1 1 0;
  height: auto;
}

.events-tab__body.is-facets-collapsed {
  grid-template-columns: 40px minmax(0, 1fr);
}
</style>
