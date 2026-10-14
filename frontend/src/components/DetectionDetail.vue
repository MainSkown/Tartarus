<script setup lang="ts">
import { computed } from 'vue'
import type { Detection } from '@/api'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import { rulesetLabel } from '@/services/detection-groups'
import { eventIdQuery } from '@/services/event-id-query'
import { filterOn } from '@/services/events-filters'
import { formatTimestamp } from '@/services/format-time'
import { laneMeta } from '@/services/lanes'

const props = defineProps<{ detection: Detection }>()

const WEB_ADDRESS = /^https?:\/\//i

const eventsCount = computed(() => {
  const { related_events, related_event_total } = props.detection
  return related_events.length < related_event_total
    ? `${related_events.length} of ${related_event_total} shown`
    : String(related_event_total)
})

const triggeringEventsQuery = computed(() => eventIdQuery(props.detection.related_events.map((event) => event.id)))
</script>

<template>
  <article class="detection-detail">
    <PaneHeading label="DESCRIPTION" />
    <div class="detection-detail__top">
      <SeverityBadge :severity="detection.severity" />
      <FilterEventsButton
        class="detection-detail__action detection-detail__rule-filter text-mono"
        :target="{ chips: filterOn('rule.name', detection.name) }"
      >
        [FILTER ON RULE]
      </FilterEventsButton>
    </div>
    <h2 class="detection-detail__name text-mono">
      {{ detection.name }}
    </h2>
    <p class="detection-detail__description">
      {{ detection.description ?? 'no description' }}
    </p>

    <dl class="detection-detail__facts">
      <dt class="text-mono">
        RULESET
      </dt>
      <dd class="detection-detail__ruleset text-mono">
        {{ rulesetLabel(detection.ruleset) }}
      </dd>
      <dt class="text-mono">
        PROCESS
      </dt>
      <dd class="detection-detail__process">
        <ProcessChip :process="detection.process" />
      </dd>
      <dt class="text-mono">
        TIME
      </dt>
      <dd class="detection-detail__time text-mono">
        {{ formatTimestamp(detection.time) }}
      </dd>
      <template v-if="detection.techniques.length > 0">
        <dt class="text-mono">
          TECHNIQUES
        </dt>
        <dd class="text-mono">
          {{ detection.techniques.join(' ') }}
        </dd>
      </template>
    </dl>

    <template v-if="detection.references.length > 0">
      <h3 class="detection-detail__heading text-mono">
        REFERENCES
      </h3>
      <ul class="detection-detail__references">
        <li
          v-for="reference in detection.references"
          :key="reference"
        >
          <a
            v-if="WEB_ADDRESS.test(reference)"
            :href="reference"
            target="_blank"
            rel="noopener noreferrer"
          >{{ reference }}</a>
          <span v-else>{{ reference }}</span>
        </li>
      </ul>
    </template>

    <template v-if="detection.match">
      <h3 class="detection-detail__heading text-mono">
        MATCHED CONDITION
      </h3>
      <pre class="code-block detection-detail__match">{{ detection.match }}</pre>
    </template>

    <h3 class="detection-detail__heading text-mono">
      TRIGGERING EVENTS
      <span
        v-if="detection.related_event_total > 0"
        class="detection-detail__events-count text-gray"
      >{{ eventsCount }}</span>
      <template v-if="triggeringEventsQuery">
        <span
          v-if="triggeringEventsQuery.used < detection.related_events.length"
          class="detection-detail__events-cut text-gray"
        >the query names {{ triggeringEventsQuery.used }} of {{ detection.related_events.length }}</span>
        <FilterEventsButton
          class="detection-detail__action detection-detail__show-events text-mono"
          :target="{ text: triggeringEventsQuery.text }"
          label="the triggering events"
        >
          [SHOW THESE EVENTS]
        </FilterEventsButton>
      </template>
    </h3>
    <ul
      v-if="detection.related_events.length > 0"
      class="detection-detail__events"
    >
      <li
        v-for="event in detection.related_events"
        :key="event.id"
        class="related-event"
      >
        <span class="related-event__lane text-mono">
          <q-icon
            :name="laneMeta(event.lane).icon"
            size="16px"
            :style="{ color: `var(${laneMeta(event.lane).color})` }"
            aria-hidden="true"
          />
          {{ laneMeta(event.lane).label }}
        </span>
        <span class="related-event__summary">{{ event.summary }}</span>
        <ProcessChip
          class="related-event__process"
          :process="event.process"
        />
        <span class="related-event__time text-mono">{{ formatTimestamp(event.time) }}</span>
      </li>
    </ul>
    <p
      v-else
      class="text-mono text-gray"
    >
      &gt; no triggering events recorded
    </p>
  </article>
</template>

<style scoped>
.detection-detail {
  min-width: 0;
}

.detection-detail__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
  /* The list's entries have this much padding above their badge; matching it puts both badges on one line. Padding, not margin: a block's margin would collapse into the heading's. */
  padding-top: var(--spacing-sm);
}

.detection-detail__action {
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 1px;
  white-space: nowrap;
}

.detection-detail__show-events {
  margin-left: auto;
}

.detection-detail__events-cut {
  margin-left: auto;
  font-weight: normal;
  letter-spacing: 0;
}

.detection-detail__events-cut + .detection-detail__show-events {
  margin-left: 0;
}

.detection-detail__name {
  margin: var(--spacing-sm) 0;
  font-size: 1.1rem;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.detection-detail__description {
  margin: 0 0 var(--spacing-md);
  overflow-wrap: anywhere;
}

.detection-detail__facts {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: var(--spacing-xs) var(--spacing-md);
  margin: 0;
}

.detection-detail__facts dt {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.detection-detail__facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.detection-detail__heading {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-md);
  margin: var(--spacing-lg) 0 var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.75rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

.detection-detail__events-count {
  font-weight: normal;
  letter-spacing: 0;
}

.detection-detail__references {
  margin: 0;
  padding: 0;
  list-style: none;
  overflow-wrap: anywhere;
}

.detection-detail__match {
  margin: 0;
  font-size: 0.85rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.detection-detail__events {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.related-event {
  display: grid;
  grid-template-columns: 6.5rem minmax(0, 1fr) auto;
  gap: 0 var(--spacing-md);
  padding: var(--spacing-xs) 0;
  border-bottom: 1px solid var(--border-subtle);
}

.related-event__lane {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  font-size: 0.75rem;
}

.related-event__summary {
  overflow-wrap: anywhere;
}

.related-event__process,
.related-event__time {
  font-size: 0.8rem;
}

.related-event__time {
  grid-column: 2 / -1;
  color: var(--text-gray-dark);
}

@media (max-width: 700px) {
  .related-event {
    grid-template-columns: minmax(0, 1fr);
  }

  .related-event__time {
    grid-column: auto;
  }
}
</style>
