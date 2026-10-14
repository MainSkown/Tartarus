<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EventDetail } from '@/api'
import CopyButton from '@/components/CopyButton.vue'
import EventFieldsTable from '@/components/EventFieldsTable.vue'
import LaneIcon from '@/components/LaneIcon.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import RelatedEventList from '@/components/RelatedEventList.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import TargetAnnotations from '@/components/TargetAnnotations.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import ViewState from '@/components/ViewState.vue'
import { eventProcess, eventTitle } from '@/services/event-display'
import { flattenSource } from '@/services/event-source'
import { formatPreciseTimestamp } from '@/services/format-time'
import { eventTarget } from '@/stores/annotations'

const SKELETON_LINES = 10

const ANNOTATE_HINT = 'events can be tagged and noted once the analysis is finished'

const props = withDefaults(
  defineProps<{
    eventId: string
    detail?: EventDetail
    loading: boolean
    error?: string
    notFound: boolean
    hasPrevious: boolean
    hasNext: boolean
    annotatable?: boolean
  }>(),
  { detail: undefined, error: undefined, annotatable: true },
)
const emit = defineEmits<{
  close: []
  previous: []
  next: []
  retry: []
  'open-event': [id: string]
}>()

const rawOpen = ref(false)
const event = computed(() => props.detail?.event)
const fields = computed(() => (props.detail ? flattenSource(props.detail.source) : []))
const rawJson = computed(() => JSON.stringify(props.detail?.source ?? {}, null, 2))
const hasRelated = computed(() => {
  const related = props.detail?.related
  return related !== undefined && (related.references.total > 0 || related.referenced_by.total > 0)
})

function onKeydown(key: KeyboardEvent): void {
  if (key.key === 'ArrowUp' && props.hasPrevious) emit('previous')
  else if (key.key === 'ArrowDown' && props.hasNext) emit('next')
  else return
  key.preventDefault()
}
</script>

<template>
  <div
    class="event-detail"
    tabindex="-1"
    data-autofocus
    @keydown="onKeydown"
  >
    <header class="event-detail__header">
      <div class="event-detail__nav">
        <button
          type="button"
          class="event-detail__step button"
          aria-label="Previous event"
          title="Previous event (↑)"
          :disabled="!hasPrevious"
          @click="emit('previous')"
        >
          <q-icon
            name="keyboard_arrow_up"
            size="20px"
          />
        </button>
        <button
          type="button"
          class="event-detail__step button"
          aria-label="Next event"
          title="Next event (↓)"
          :disabled="!hasNext"
          @click="emit('next')"
        >
          <q-icon
            name="keyboard_arrow_down"
            size="20px"
          />
        </button>
        <span class="event-detail__label text-mono">EVENT</span>
        <button
          type="button"
          class="event-detail__step event-detail__close button"
          aria-label="Close event"
          title="Close (Esc)"
          @click="emit('close')"
        >
          <q-icon
            name="close"
            size="20px"
          />
        </button>
      </div>

      <template v-if="event">
        <h3 class="event-detail__title">
          <LaneIcon
            v-if="event.lane"
            :lane="event.lane"
          />
          <span
            class="event-detail__summary"
            :title="eventTitle(event)"
          >{{ eventTitle(event) }}</span>
        </h3>
        <div class="event-detail__meta">
          <span
            class="event-detail__time text-mono text-gray"
            :title="event.time"
          >{{ formatPreciseTimestamp(event.time) }}</span>
          <ProcessChip :process="eventProcess(event)" />
          <SeverityBadge
            v-if="event.severity"
            :severity="event.severity"
          />
        </div>
      </template>
      <p
        v-else
        class="event-detail__id text-mono text-gray"
      >
        {{ eventId }}
      </p>
    </header>

    <div
      class="event-detail__body scrollable-panel"
      :class="{ 'is-stale': loading && detail }"
    >
      <TerminalEmpty
        v-if="notFound"
        message="event not found: it is no longer in this analysis"
      />
      <ViewState
        v-else-if="error"
        :error="error"
        @retry="emit('retry')"
      />
      <div
        v-else-if="!detail"
        class="event-detail__skeleton"
        aria-busy="true"
        aria-label="Loading event"
      >
        <span
          v-for="line in SKELETON_LINES"
          :key="line"
          class="skeleton"
        />
      </div>

      <template v-else>
        <TargetAnnotations
          class="event-detail__section"
          :target="eventTarget(eventId)"
          :editable="annotatable"
          :hint="ANNOTATE_HINT"
        />

        <section class="event-detail__section">
          <h4 class="event-detail__heading text-mono">
            FIELDS
          </h4>
          <EventFieldsTable :fields="fields" />
        </section>

        <section class="event-detail__section">
          <div class="event-detail__raw-bar">
            <button
              type="button"
              class="event-detail__raw-toggle event-detail__heading text-mono"
              :aria-expanded="rawOpen"
              @click="rawOpen = !rawOpen"
            >
              <q-icon
                :name="rawOpen ? 'expand_more' : 'chevron_right'"
                size="16px"
                aria-hidden="true"
              />RAW JSON
            </button>
            <CopyButton
              v-if="rawOpen"
              :text="rawJson"
              what="raw JSON"
            />
          </div>
          <pre
            v-if="rawOpen"
            class="event-detail__raw code-block"
          >{{ rawJson }}</pre>
        </section>

        <section class="event-detail__section">
          <h4 class="event-detail__heading text-mono">
            RELATED EVENTS
          </h4>
          <template v-if="hasRelated">
            <RelatedEventList
              title="REFERENCES"
              :listing="detail.related.references"
              @open="emit('open-event', $event)"
            />
            <RelatedEventList
              title="REFERENCED BY"
              :listing="detail.related.referenced_by"
              @open="emit('open-event', $event)"
            />
          </template>
          <p
            v-else
            class="event-detail__none text-mono text-gray"
          >
            no related events
          </p>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.event-detail {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  outline: none;
}

.event-detail__header {
  display: flex;
  flex: none;
  flex-direction: column;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md) var(--spacing-md);
  border-bottom: 2px solid var(--border-primary);
}

.event-detail__nav {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.event-detail__label {
  margin-left: var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 2px;
}

.event-detail__step {
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid var(--border-primary);
}

.event-detail__step:disabled {
  color: var(--text-gray-darker);
  cursor: not-allowed;
}

.event-detail__step:disabled:hover {
  background: var(--black);
  color: var(--text-gray-darker);
}

.event-detail__close {
  margin-left: auto;
}

.event-detail__title {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-sm);
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.event-detail__summary {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-clamp: 3;
}

.event-detail__title .q-icon {
  flex: none;
  margin-top: 2px;
}

.event-detail__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-md);
  font-size: 0.75rem;
}

.event-detail__id {
  margin: 0;
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.event-detail__body {
  flex: 1 1 0;
  min-height: 0;
  padding: var(--spacing-sm) var(--spacing-md) var(--spacing-md);
}

.event-detail__body.is-stale > * {
  opacity: 0.45;
  transition: opacity var(--transition-fast);
}

.event-detail__section {
  margin-bottom: var(--spacing-md);
}

.event-detail__heading {
  margin: 0 0 var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.65rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.event-detail__raw-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.event-detail__raw-toggle {
  display: inline-flex;
  align-items: center;
  padding: 0;
  border: none;
  background: transparent;
  font-weight: bold;
  cursor: pointer;
}

.event-detail__raw-toggle:hover,
.event-detail__raw-toggle:focus-visible {
  color: var(--blue-hover);
}

.event-detail__raw {
  max-height: 18rem;
  margin: var(--spacing-xs) 0 0;
  overflow: auto;
  font-size: 0.75rem;
  white-space: pre-wrap;
  word-break: break-all;
}

.event-detail__none {
  margin: 0;
  font-size: 0.75rem;
}

.event-detail__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  padding-top: var(--spacing-sm);
}

.event-detail__skeleton .skeleton {
  height: 12px;
}

.event-detail__skeleton .skeleton:nth-child(3n) {
  width: 60%;
}

.event-detail__skeleton .skeleton:nth-child(3n + 1) {
  width: 80%;
}
</style>
