<script setup lang="ts">
import type { ListingEvent } from '@/api'
import LaneIcon from '@/components/LaneIcon.vue'
import { eventTitle } from '@/services/event-display'
import { formatCount } from '@/services/format-number'
import { formatClockTime } from '@/services/format-time'

defineProps<{ title: string; listing: ListingEvent }>()
const emit = defineEmits<{ open: [id: string] }>()
</script>

<template>
  <section
    v-if="listing.items.length > 0 || listing.total > 0"
    class="related-list"
  >
    <h4 class="related-list__heading text-mono">
      <span>{{ title }}</span>
      <span class="text-gray">{{
        listing.items.length < listing.total
          ? `showing ${formatCount(listing.items.length)} of ${formatCount(listing.total)}`
          : formatCount(listing.total)
      }}</span>
    </h4>
    <ul class="related-list__items">
      <li
        v-for="event in listing.items"
        :key="event.id"
      >
        <button
          type="button"
          class="related-event"
          :title="eventTitle(event)"
          @click="emit('open', event.id)"
        >
          <span class="related-event__time text-mono text-gray">{{ formatClockTime(event.time) }}</span>
          <span class="related-event__lane">
            <LaneIcon
              v-if="event.lane"
              :lane="event.lane"
            />
          </span>
          <span class="related-event__action text-mono">{{ event.action }}</span>
          <span class="related-event__summary">{{ event.summary }}</span>
        </button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.related-list + .related-list {
  margin-top: var(--spacing-md);
}

.related-list__heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin: 0 0 var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.65rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.related-list__items {
  margin: 0;
  padding: 0;
  list-style: none;
}

.related-event {
  display: grid;
  grid-template-areas:
    'time lane action'
    'summary summary summary';
  grid-template-columns: 5.6rem 16px minmax(0, 1fr);
  align-items: center;
  column-gap: var(--spacing-sm);
  width: 100%;
  padding: 3px var(--spacing-xs) 4px;
  border: none;
  border-bottom: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-white);
  font-size: 0.75rem;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
}

.related-event > * {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.related-event__time {
  grid-area: time;
}

.related-event__lane {
  grid-area: lane;
  line-height: 0;
}

.related-event__action {
  grid-area: action;
}

.related-event__summary {
  grid-area: summary;
}

.related-event:hover,
.related-event:focus-visible {
  background: var(--hover-bg);
  color: var(--blue-hover);
}

.related-event:focus-visible {
  outline: 2px solid var(--blue-light);
  outline-offset: -2px;
}
</style>
