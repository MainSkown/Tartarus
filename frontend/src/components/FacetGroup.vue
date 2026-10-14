<script setup lang="ts">
import { computed } from 'vue'
import type { Facet, FilterChip } from '@/api'
import LaneIcon from '@/components/LaneIcon.vue'
import { fieldLabel } from '@/services/event-fields'
import { facetValueMark } from '@/services/facet-actions'
import { formatCount } from '@/services/format-number'

const LANE_FIELD = 'tartarus.lane'
const SKELETON_LINES = 4
const MIN_BAR_PERCENT = 2

const props = defineProps<{ field: string; facet?: Facet; loading: boolean; chips: FilterChip[] }>()
const emit = defineEmits<{ pick: [value: string, negate: boolean] }>()

const values = computed(() => {
  const counts = props.facet?.values ?? []
  const most = Math.max(...counts.map(({ count }) => count), 1)
  return counts.map(({ value, count }) => ({
    value,
    count,
    mark: facetValueMark(props.chips, props.field, value),
    percent: Math.max((count / most) * 100, MIN_BAR_PERCENT),
  }))
})
</script>

<template>
  <section
    class="facet-group"
    :class="{ 'is-stale': loading && facet !== undefined }"
  >
    <h4
      class="facet-group__heading text-mono"
      :title="field"
    >
      <span>{{ fieldLabel(field) }}</span>
      <span
        v-if="facet"
        class="facet-group__total text-gray"
      >{{ formatCount(facet.total) }}</span>
    </h4>

    <ul
      v-if="values.length > 0"
      class="facet-group__values"
    >
      <li
        v-for="entry in values"
        :key="entry.value"
        class="facet-value"
        :class="{ 'is-included': entry.mark === 'included', 'is-excluded': entry.mark === 'excluded' }"
      >
        <button
          type="button"
          class="facet-value__pick"
          :aria-pressed="entry.mark !== undefined"
          :title="`${entry.value}: click to filter on, alt-click to filter out`"
          @click="emit('pick', entry.value, $event.altKey)"
        >
          <LaneIcon
            v-if="field === LANE_FIELD"
            :lane="entry.value"
          />
          <span class="facet-value__name text-mono">{{ entry.value }}</span>
          <span class="facet-value__count text-mono">{{ formatCount(entry.count) }}</span>
          <span
            class="facet-value__bar"
            :style="{ width: `${entry.percent}%` }"
          />
        </button>
        <button
          type="button"
          class="facet-value__exclude"
          :aria-label="`Filter out ${field}: ${entry.value}`"
          title="Filter out"
          @click="emit('pick', entry.value, true)"
        >
          <q-icon
            name="remove"
            size="14px"
          />
        </button>
      </li>
    </ul>
    <ul
      v-else-if="loading"
      class="facet-group__values"
      aria-hidden="true"
    >
      <li
        v-for="line in SKELETON_LINES"
        :key="line"
        class="facet-value facet-value--skeleton"
      >
        <span class="skeleton" />
      </li>
    </ul>
    <p
      v-else
      class="facet-group__empty text-mono text-gray"
    >
      no values
    </p>
  </section>
</template>

<style scoped>
.facet-group {
  padding: var(--spacing-sm) 0;
  border-bottom: 1px solid var(--border-subtle);
}

.facet-group.is-stale .facet-group__values {
  opacity: 0.6;
  transition: opacity var(--transition-fast);
}

.facet-group__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin: 0 0 var(--spacing-xs);
  padding: 0 var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.65rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.facet-group__total {
  font-weight: normal;
}

.facet-group__values {
  margin: 0;
  padding: 0;
  list-style: none;
}

.facet-group__empty {
  margin: 0;
  padding: 0 var(--spacing-sm);
  font-size: 0.7rem;
}

.facet-value {
  position: relative;
  display: flex;
  align-items: center;
  height: 24px;
}

.facet-value__pick {
  position: relative;
  display: flex;
  flex: 1 1 0;
  align-items: center;
  gap: var(--spacing-xs);
  min-width: 0;
  height: 100%;
  padding: 0 0 0 var(--spacing-sm);
  border: none;
  background: transparent;
  color: var(--text-white);
  text-align: left;
  cursor: pointer;
}

.facet-value__name {
  flex: 1 1 0;
  min-width: 0;
  overflow: hidden;
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.facet-value__count {
  flex: none;
  color: var(--text-gray);
  font-size: 0.7rem;
}

/* The bar sits under the line, so a long value name still has the whole width to itself. */
.facet-value__bar {
  position: absolute;
  bottom: 1px;
  left: var(--spacing-sm);
  height: 2px;
  max-width: calc(100% - var(--spacing-sm));
  background: var(--blue-dark);
}

.facet-value__exclude {
  flex: none;
  width: 20px;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-gray);
  line-height: 0;
  opacity: 0;
  cursor: pointer;
}

.facet-value:hover .facet-value__exclude,
.facet-value:focus-within .facet-value__exclude {
  opacity: 1;
}

.facet-value:hover {
  background: var(--hover-bg);
}

.facet-value__pick:focus-visible,
.facet-value__exclude:focus-visible {
  outline: 2px solid var(--blue-light);
  outline-offset: -2px;
}

.facet-value__exclude:hover {
  color: var(--status-high);
}

.facet-value.is-included {
  background: rgba(3, 105, 161, 0.35);
}

.facet-value.is-included .facet-value__bar {
  background: var(--blue-primary);
}

.facet-value.is-excluded .facet-value__name {
  color: var(--status-high);
  text-decoration: line-through;
}

.facet-value.is-excluded .facet-value__bar {
  background: var(--status-high);
}

.facet-value--skeleton {
  padding: 0 var(--spacing-sm);
}

.facet-value--skeleton .skeleton {
  height: 8px;
}

.facet-value--skeleton:nth-child(2) .skeleton {
  width: 70%;
}

.facet-value--skeleton:nth-child(3) .skeleton {
  width: 50%;
}
</style>
