<script setup lang="ts">
import { watch } from 'vue'
import EventTable from '@/components/EventTable.vue'
import FilterChips from '@/components/FilterChips.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import QueryBar from '@/components/QueryBar.vue'
import { useCrossSearch } from '@/composables/use-cross-search'
import { t } from '@/i18n'
import { useQueryStateStore } from '@/stores/query-state'

const query = useQueryStateStore()
const { rows, total, sort, loading, loadingMore, hasMore, error, loadMoreError, searched, run, retry, loadMore, toggleSort, clear } =
  useCrossSearch()

// Value completions are per analysis, so this page's bar completes field names only.
query.bindTo(undefined)
watch(
  () => query.searchFilter,
  (filter) => (query.isEmpty ? clear() : void run(filter)),
  { immediate: true },
)
</script>

<template>
  <section class="search-page">
    <PaneHeading :label="t('search.title')" />
    <div class="search-page__query">
      <QueryBar />
      <FilterChips />
    </div>

    <p
      v-if="!searched"
      class="search-page__hint text-mono text-gray"
    >
      {{ t('search.hint') }}
    </p>
    <div
      v-else
      class="search-page__results"
    >
      <EventTable
        :events="rows"
        :total="total"
        :loading="loading"
        :loading-more="loadingMore"
        :has-more="hasMore"
        :sort="sort"
        :selected-id="null"
        filtered
        :error="error?.message"
        :load-more-error="loadMoreError"
        :end-column="t('search.table.analysis')"
        @toggle-sort="toggleSort"
        @load-more="loadMore"
        @retry="retry"
        @clear="query.reset"
      >
        <template #end="{ item }">
          <router-link
            class="search-page__analysis text-mono"
            :to="`/analyses/${item.analysis_id}`"
          >
            {{ t('search.table.analysisLink', { id: item.analysis_id }) }}
          </router-link>
        </template>
      </EventTable>
    </div>
  </section>
</template>

<style scoped>
.search-page {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  height: 100%;
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-sm) var(--spacing-lg);
}

.search-page__query {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.search-page__hint {
  padding: var(--spacing-md) 0;
  font-size: 0.8rem;
}

.search-page__results {
  flex: 1 1 0;
  min-height: 0;
}

.search-page__analysis {
  color: var(--blue-primary);
  font-size: 0.75rem;
}
</style>
