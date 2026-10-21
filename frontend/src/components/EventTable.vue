<script setup lang="ts" generic="T extends Event">
import { computed, nextTick, ref, watch } from 'vue'
import type { QVirtualScroll } from 'quasar'
import type { Event, SortOrder } from '@/api'
import EventColumnChooser from '@/components/EventColumnChooser.vue'
import LaneIcon from '@/components/LaneIcon.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import ViewState from '@/components/ViewState.vue'
import { t } from '@/i18n'
import { columnValue } from '@/services/event-columns'
import { eventProcess } from '@/services/event-display'
import { formatCount } from '@/services/format-number'
import { formatClockTime } from '@/services/format-time'
import { laneMeta } from '@/services/lanes'
import { scrollTopToReveal, shouldLoadMore } from '@/services/virtual-paging'
import { useEventColumnsStore } from '@/stores/event-columns'

const ROW_HEIGHT = 28
// Rows rendered at least, so a fast scroll never shows blank rows before the list has re-measured.
const MIN_RENDERED_ROWS = 40
const SKELETON_ROWS = 18
// Widths in rem of the default columns, then of each extra column; the summary takes what is left.
const DEFAULT_COLUMN_REMS = { time: 6.2, lane: 2, process: 10.5, action: 9.5, summary: 16, severity: 6.8 }
const EXTRA_COLUMN_REM = 14
const GAP_REM = 0.5
const PADDING_REM = 1

const props = defineProps<{
  events: T[]
  total: number
  loading: boolean
  loadingMore: boolean
  hasMore: boolean
  sort: SortOrder
  selectedId: string | null
  /** Whether a query, chip, process or time range narrows the list, which decides what "no events" means. */
  filtered: boolean
  error?: string
  loadMoreError?: string
  /** Header of an extra column that the parent fills through the `end` slot, one cell per row. */
  endColumn?: string
}>()
defineSlots<{ end?: (props: { item: T }) => unknown }>()
const emit = defineEmits<{
  select: [id: string]
  open: [id: string]
  'toggle-sort': []
  'load-more': []
  retry: []
  clear: []
}>()

const columns = useEventColumnsStore()
const list = ref<InstanceType<typeof QVirtualScroll>>()
const lastRendered = ref(0)

const showsSkeleton = computed(() => props.loading && props.events.length === 0)
const isEmpty = computed(() => !props.loading && props.events.length === 0)
const isStale = computed(() => props.loading && props.events.length > 0)
const ascending = computed(() => props.sort === '@timestamp')

const extraColumns = computed(() => columns.chosen.map((field) => ({ field, label: field.toUpperCase() })))
const endColumnCount = computed(() => (props.endColumn === undefined ? 0 : 1))
const extraColumnCount = computed(() => extraColumns.value.length + endColumnCount.value)
const HEAD_END_REM = 2.25
const gridColumns = computed(() => {
  const { time, lane, process, action, summary, severity } = DEFAULT_COLUMN_REMS
  const extras = Array.from({ length: extraColumnCount.value }, () => `${EXTRA_COLUMN_REM}rem`)
  return [`${time}rem`, `${lane}rem`, `${process}rem`, `${action}rem`, `minmax(${summary}rem, 1fr)`, `${severity}rem`, ...extras, `${HEAD_END_REM}rem`].join(' ')
})
const gridMinWidth = computed(() => {
  const fixed = Object.values(DEFAULT_COLUMN_REMS).reduce((sum, width) => sum + width, 0)
  const columnCount = Object.keys(DEFAULT_COLUMN_REMS).length + extraColumnCount.value + 1
  return `${fixed + HEAD_END_REM + extraColumnCount.value * EXTRA_COLUMN_REM + (columnCount - 1) * GAP_REM + 2 * PADDING_REM}rem`
})

const showsFooter = computed(() => !showsSkeleton.value && !isEmpty.value && !props.error)
const counter = computed(() => {
  return t('events.table.counter', { shown: formatCount(props.events.length), total: formatCount(props.total) }, props.total)
})

function listElement(): HTMLElement | undefined {
  return list.value?.$el as HTMLElement | undefined
}

function askForMoreIfNearEnd(): void {
  const near = shouldLoadMore({
    lastRendered: lastRendered.value,
    loaded: props.events.length,
    hasMore: props.hasMore,
    busy: props.loadingMore || props.loading || props.loadMoreError !== undefined,
  })
  if (near) emit('load-more')
}

function onVirtualScroll({ to }: { to: number }): void {
  lastRendered.value = to
  askForMoreIfNearEnd()
}

function revealSelected(): void {
  const scroller = listElement()
  const index = props.events.findIndex((event) => event.id === props.selectedId)
  if (!scroller || index < 0) return
  scroller.scrollTop = scrollTopToReveal({
    index,
    scrollTop: scroller.scrollTop,
    viewportHeight: scroller.clientHeight,
    rowHeight: ROW_HEIGHT,
  })
}

function moveSelection(step: 1 | -1): void {
  const current = props.events.findIndex((event) => event.id === props.selectedId)
  const target = current < 0 ? (step === 1 ? 0 : props.events.length - 1) : current + step
  const next = props.events[target]
  if (next) emit('select', next.id)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    moveSelection(event.key === 'ArrowDown' ? 1 : -1)
  } else if (event.key === 'Enter' && props.selectedId !== null) {
    event.preventDefault()
    emit('open', props.selectedId)
  }
}

function choose(id: string): void {
  emit('select', id)
  emit('open', id)
}

watch(() => props.events.length, askForMoreIfNearEnd)
watch(() => props.selectedId, () => void nextTick(revealSelected))
watch(
  () => props.events[0]?.id,
  () => {
    const scroller = listElement()
    if (scroller) scroller.scrollTop = 0
  },
  { flush: 'post' },
)
</script>

<template>
  <div class="event-table">
    <div class="event-table__state">
      <ViewState
        :error="error"
        @retry="emit('retry')"
      >
        <div
          v-if="isEmpty"
          class="event-table__empty"
        >
          <TerminalEmpty :message="filtered ? t('events.table.noMatch') : t('events.table.noEvents')" />
          <q-btn
            v-if="filtered"
            outline
            square
            class="event-table__clear text-mono"
            :label="t('events.table.clearQuery')"
            @click="emit('clear')"
          />
        </div>

        <div
          v-else
          class="event-table__scroll"
        >
          <div
            class="event-table__grid"
            :class="{ 'is-stale': isStale }"
            :style="{ '--event-columns': gridColumns, '--event-min-width': gridMinWidth }"
            role="grid"
            tabindex="0"
            :aria-label="t('events.table.label')"
            :aria-rowcount="total"
            @keydown="onKeydown"
          >
            <div
              class="event-table__head event-table__line text-mono"
              role="row"
            >
              <div
                role="columnheader"
                :aria-sort="ascending ? 'ascending' : 'descending'"
              >
                <button
                  type="button"
                  class="event-table__sort text-mono"
                  :title="ascending ? t('events.table.sortOldest') : t('events.table.sortNewest')"
                  @click="emit('toggle-sort')"
                >
                  {{ t('events.column.time') }}<q-icon
                    :name="ascending ? 'arrow_upward' : 'arrow_downward'"
                    size="12px"
                    aria-hidden="true"
                  />
                </button>
              </div>
              <div role="columnheader">
                {{ t('events.column.lane') }}
              </div>
              <div role="columnheader">
                {{ t('events.column.process') }}
              </div>
              <div role="columnheader">
                {{ t('events.column.action') }}
              </div>
              <div role="columnheader">
                {{ t('events.column.summary') }}
              </div>
              <div role="columnheader">
                {{ t('events.column.severity') }}
              </div>
              <div
                v-if="endColumn"
                role="columnheader"
              >
                {{ endColumn }}
              </div>
              <div
                v-for="column in extraColumns"
                :key="column.field"
                role="columnheader"
                :title="column.field"
              >
                {{ column.label }}
              </div>
              <div class="event-table__head-end">
                <EventColumnChooser
                  :chosen="columns.chosen"
                  :at-limit="columns.atLimit"
                  @toggle="columns.toggle"
                  @clear="columns.clear"
                />
              </div>
            </div>

            <div
              v-if="showsSkeleton"
              class="event-table__skeleton"
              aria-busy="true"
              :aria-label="t('events.table.loading')"
            >
              <div
                v-for="row in SKELETON_ROWS"
                :key="row"
                class="event-skeleton-row event-table__line"
              >
                <span class="skeleton" />
                <span class="skeleton skeleton--icon" />
                <span class="skeleton" />
                <span class="skeleton" />
                <span class="skeleton" />
                <span />
                <span
                  v-if="endColumn"
                  class="skeleton"
                />
                <span
                  v-for="column in extraColumns"
                  :key="column.field"
                  class="skeleton"
                />
              </div>
            </div>

            <q-virtual-scroll
              v-else
              ref="list"
              class="event-table__list"
              :items="events"
              :virtual-scroll-item-size="ROW_HEIGHT"
              :virtual-scroll-slice-size="MIN_RENDERED_ROWS"
              @virtual-scroll="onVirtualScroll"
            >
              <template #default="{ item }">
                <div
                  :key="item.id"
                  class="event-row event-table__line"
                  :class="{ 'is-selected': item.id === selectedId }"
                  role="row"
                  :aria-selected="item.id === selectedId"
                  :data-event-id="item.id"
                  @click="choose(item.id)"
                >
                  <span
                    class="event-row__time text-mono text-gray"
                    role="gridcell"
                    data-column="time"
                    :title="item.time"
                  >{{ formatClockTime(item.time) }}</span>
                  <span
                    role="gridcell"
                    data-column="lane"
                    :title="item.lane ? laneMeta(item.lane).label : undefined"
                  ><LaneIcon
                    v-if="item.lane"
                    :lane="item.lane"
                  /></span>
                  <span
                    role="gridcell"
                    data-column="process"
                  ><ProcessChip :process="eventProcess(item)" /></span>
                  <span
                    class="event-row__text text-mono"
                    role="gridcell"
                    data-column="action"
                    :title="item.action ?? undefined"
                  >{{ item.action }}</span>
                  <span
                    class="event-row__text event-row__summary"
                    role="gridcell"
                    data-column="summary"
                    :title="item.summary ?? undefined"
                  >{{ item.summary }}</span>
                  <span
                    role="gridcell"
                    data-column="severity"
                  ><SeverityBadge
                    v-if="item.severity"
                    :severity="item.severity"
                  /></span>
                  <span
                    v-if="endColumn"
                    class="event-row__text"
                    role="gridcell"
                    data-column="end"
                  ><slot
                    name="end"
                    :item="item"
                  /></span>
                  <span
                    v-for="column in extraColumns"
                    :key="column.field"
                    class="event-row__text text-mono"
                    role="gridcell"
                    :data-column="column.field"
                    :title="columnValue(item, column.field) || undefined"
                  >{{ columnValue(item, column.field) }}</span>
                </div>
              </template>
            </q-virtual-scroll>
          </div>
        </div>
      </ViewState>
    </div>

    <footer
      v-if="showsFooter"
      class="event-table__footer text-mono"
    >
      <span
        class="event-table__count text-gray"
        aria-live="polite"
      >{{ counter }}</span>
      <span
        v-if="loadMoreError"
        class="event-table__paging"
      >
        <span class="text-gray">{{ t('events.table.loadMoreFailed', { error: loadMoreError }) }}</span>
        <button
          type="button"
          class="event-table__retry button text-mono"
          @click="emit('load-more')"
        >
          {{ t('common.retry') }}
        </button>
      </span>
      <span
        v-else-if="loadingMore"
        class="event-table__paging"
      >
        <span
          class="loader event-table__loader"
          role="status"
          :aria-label="t('events.table.loadingMore')"
        />
        <span class="text-gray">{{ t('events.table.loadingMoreText') }}</span>
      </span>
    </footer>
  </div>
</template>

<style scoped>
/* The box has the same top and bottom edge as the facet panel beside it, so nothing sits above or below it. */
.event-table {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  border: 2px solid var(--border-primary);
  background: var(--black);
}

.event-table__count {
  font-size: 0.7rem;
}

.event-table__state {
  flex: 1 1 0;
  min-height: 0;
}

.event-table__empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--spacing-sm);
  padding: var(--spacing-md);
}

.event-table__empty :deep(.terminal-empty) {
  padding: 0;
}

.event-table__clear {
  color: var(--blue-primary);
  font-size: 0.75rem;
}

.event-table__scroll {
  height: 100%;
  min-height: 0;
  overflow-x: auto;
}

.event-table__grid {
  display: flex;
  flex-direction: column;
  min-width: var(--event-min-width);
  height: 100%;
}

.event-table__grid:focus-visible {
  outline: 2px solid var(--blue-light);
  outline-offset: -2px;
}

.event-table__grid.is-stale .event-table__list {
  opacity: 0.45;
  transition: opacity var(--transition-fast);
}

.event-table__line {
  display: grid;
  grid-template-columns: var(--event-columns);
  align-items: center;
  column-gap: var(--spacing-sm);
  padding: 0 var(--spacing-sm);
}

.event-table__head {
  flex: none;
  height: 28px;
  padding-right: calc(var(--spacing-sm) + 8px);
  border-bottom: 2px solid var(--border-primary);
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
  white-space: nowrap;
}

.event-table__head-end {
  position: sticky;
  right: 0;
  display: flex;
  justify-content: flex-end;
  margin-right: calc(-1 * (var(--spacing-sm) + 8px));
  padding-right: var(--spacing-xs);
  background: var(--black);
}

.event-table__head > * {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.event-table__sort {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  letter-spacing: inherit;
  cursor: pointer;
}

.event-table__sort:hover,
.event-table__sort:focus-visible {
  color: var(--blue-hover);
}

.event-table__list {
  flex: 1 1 0;
  min-height: 0;
  scrollbar-gutter: stable;
}

.event-row {
  height: 28px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 0.75rem;
  white-space: nowrap;
  cursor: pointer;
}

.event-row > * {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.event-row:hover {
  background: var(--hover-bg);
}

.event-row.is-selected {
  background: rgba(3, 105, 161, 0.35);
}

.event-row__summary {
  font-size: 0.8rem;
}

.event-table__skeleton {
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
  padding-right: 8px;
}

.event-skeleton-row {
  height: 28px;
  border-bottom: 1px solid var(--border-subtle);
}

.event-skeleton-row .skeleton {
  height: 10px;
}

.event-skeleton-row .skeleton--icon {
  width: 16px;
}

.event-skeleton-row:nth-child(3n) .skeleton:nth-child(5) {
  width: 55%;
}

.event-skeleton-row:nth-child(3n + 1) .skeleton:nth-child(5) {
  width: 80%;
}

.event-table__footer {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
  height: 24px;
  padding: 0 var(--spacing-sm);
  border-top: 1px solid var(--border-primary);
  font-size: 0.7rem;
  white-space: nowrap;
}

.event-table__paging {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.event-table__loader {
  flex: none;
  transform: scale(0.4);
  margin: -10px;
}

.event-table__retry {
  padding: 0 var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.75rem;
}
</style>
