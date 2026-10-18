<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { formatClockTime } from '@/services/format-time'
import type { QueryTimeRange } from '@/services/query-url'
import { useQueryStateStore } from '@/stores/query-state'

/** `pidNames` lets a caller that knows the processes (the Processes tab) add the image name to a pid chip. */
const props = defineProps<{ pidNames?: Record<number, string> }>()
// A query-grammar token, shown as written and never translated.
const NEGATION_TOKEN = 'NOT'
const store = useQueryStateStore()

function describeTimeRange({ from, to }: QueryTimeRange): string {
  if (from !== null && to !== null) return t('events.chips.range', { from: formatClockTime(from), to: formatClockTime(to) })
  return from !== null ? t('events.chips.from', { time: formatClockTime(from) }) : t('events.chips.until', { time: formatClockTime(to!) })
}

const chips = computed(() =>
  store.chips.map((chip) => {
    const text = `${chip.field}: ${chip.value}`
    const label = chip.negate ? `${NEGATION_TOKEN} ${text}` : text
    const action = t(chip.negate ? 'events.chips.include' : 'events.chips.exclude')
    return { key: `${chip.field}\u0000${chip.value}`, text, negate: chip.negate, title: t('events.chips.clickTo', { label, action }) }
  }),
)

const pids = computed(() =>
  store.pids.map((pid) => {
    const name = props.pidNames?.[pid]
    return { pid, text: name ? `pid: ${pid} (${name})` : `pid: ${pid}` }
  }),
)

const time = computed(() => (store.timeRange ? `time: ${describeTimeRange(store.timeRange)}` : undefined))
const visible = computed(() => chips.value.length > 0 || pids.value.length > 0 || time.value !== undefined)
</script>

<template>
  <div
    v-if="visible"
    class="filter-chips"
    role="group"
    :aria-label="t('events.chips.label')"
  >
    <q-chip
      v-for="(chip, index) in chips"
      :key="chip.key"
      class="filter-chip"
      :class="{ 'is-negated': chip.negate }"
      clickable
      removable
      square
      icon-remove="close"
      :title="chip.title"
      :remove-aria-label="t('events.chips.removeFilter', { text: chip.text })"
      @click="store.toggleChip(index)"
      @remove="store.removeChip(index)"
    >
      <span
        v-if="chip.negate"
        class="filter-chip__not"
      >{{ NEGATION_TOKEN }}</span>
      <span class="filter-chip__label">{{ chip.text }}</span>
    </q-chip>

    <q-chip
      v-for="pid in pids"
      :key="`pid-${pid.pid}`"
      class="filter-chip"
      removable
      square
      icon-remove="close"
      :title="pid.text"
      :remove-aria-label="t('events.chips.removeFilter', { text: `pid: ${pid.pid}` })"
      @remove="store.togglePid(pid.pid)"
    >
      <span class="filter-chip__label">{{ pid.text }}</span>
    </q-chip>

    <q-chip
      v-if="time"
      class="filter-chip"
      removable
      square
      icon-remove="close"
      :title="time"
      :remove-aria-label="t('events.chips.removeTime')"
      @remove="store.clearTimeRange()"
    >
      <span class="filter-chip__label">{{ time }}</span>
    </q-chip>
  </div>
</template>

<style scoped>
.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  min-width: 0;
}

.filter-chips :deep(.q-chip) {
  min-width: 0;
  max-width: 100%;
  margin: 0;
}

.filter-chips :deep(.q-chip__content) {
  min-width: 0;
}

.filter-chips :deep(.q-chip__icon--remove) {
  margin-left: var(--spacing-sm);
  color: inherit;
  font-size: 1.15em;
}

.filter-chip__label {
  min-width: 0;
  max-width: 40ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.filter-chip__not {
  margin-right: var(--spacing-xs);
  font-weight: bold;
}
</style>
