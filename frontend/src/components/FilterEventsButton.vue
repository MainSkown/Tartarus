<script setup lang="ts">
import { computed } from 'vue'
import { useFilterEvents } from '@/composables/use-filter-events'
import { t } from '@/i18n'
import { describeTarget, type EventsTarget } from '@/services/events-filters'

/**
 * Takes the analyst to the Events tab with `target` applied to the shared query. An icon by
 * default; content in the slot is shown in its place (a process chip, a text label). `label`
 * names the target when it is too long to read out as the button's name. Chips that are empty
 * (a row without the value) leave nothing to render.
 */
const props = defineProps<{ target: EventsTarget; label?: string }>()
const { filterOnEvents, showProcessEvents, showEventsMatching } = useFilterEvents()

const nothingToApply = computed(() => 'chips' in props.target && props.target.chips.length === 0)
const name = computed(() => t('events.filter.showWith', { target: props.label ?? describeTarget(props.target) }))

async function show(): Promise<void> {
  const { target } = props
  if ('pid' in target) await showProcessEvents(target.pid)
  else if ('text' in target) await showEventsMatching(target.text)
  else await filterOnEvents(...target.chips)
}
</script>

<template>
  <button
    v-if="!nothingToApply"
    type="button"
    class="filter-events-button"
    :class="{ 'filter-events-button--content': $slots.default }"
    :aria-label="name"
    :title="t('events.filter.show')"
    @click="show"
  >
    <slot>
      <q-icon
        name="manage_search"
        size="16px"
      />
    </slot>
  </button>
</template>

<style scoped>
.filter-events-button {
  flex: none;
  padding: 2px;
  border: none;
  background: transparent;
  color: var(--text-gray);
  line-height: 0;
  cursor: pointer;
  vertical-align: middle;
  /* The padding is a bigger target, not more height: a row that holds one is as tall as one that does not. */
  margin-block: -4px;
  margin-inline-start: var(--spacing-xs);
}

.filter-events-button:hover,
.filter-events-button:focus-visible {
  color: var(--blue-hover);
}

.filter-events-button--content {
  padding: 0;
  color: inherit;
  margin: 0;
  font: inherit;
  line-height: inherit;
  text-align: left;
}

/* On the content itself: an inline-block child (a process chip) does not take its parent's underline. */
.filter-events-button--content :slotted(*) {
  text-decoration: underline dotted var(--text-gray-darker);
  text-underline-offset: 3px;
}

.filter-events-button--content:hover :slotted(*),
.filter-events-button--content:focus-visible :slotted(*) {
  text-decoration-color: currentcolor;
}
</style>
