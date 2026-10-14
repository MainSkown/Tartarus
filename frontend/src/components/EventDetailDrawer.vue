<script setup lang="ts">
import { computed } from 'vue'
import EventDetailPanel from '@/components/EventDetailPanel.vue'
import { useEventDetail } from '@/composables/use-event-detail'
import { useAnalysesStore } from '@/stores/analyses'
import { useEventsStore } from '@/stores/events'
import { useQueryStateStore } from '@/stores/query-state'

type Step = 1 | -1

/**
 * The event open in the shared query state, shown in a drawer on the right. Stepping goes through
 * the events store's list, the one the table shows, and a related event replaces the open one.
 */
const query = useQueryStateStore()
const events = useEventsStore()
const analyses = useAnalysesStore()

const eventId = computed(() => query.eventId)
// The backend refuses event annotations until the run is done: a live event's id can change when the final ingest merges calls.
const annotatable = computed(() => (analyses.current?.status ?? 'done') === 'done')
const detail = useEventDetail(
  () => query.analysisId,
  () => eventId.value,
)

function hasNeighbour(step: Step): boolean {
  return eventId.value !== null && events.hasNeighbour(eventId.value, step)
}

async function step(direction: Step): Promise<void> {
  if (eventId.value === null) return
  const target = await events.neighbour(eventId.value, direction)
  if (target !== undefined) query.openEvent(target)
}

function onDialogUpdate(open: boolean): void {
  if (!open) query.closeEvent()
}
</script>

<template>
  <q-dialog
    class="event-drawer-dialog"
    :model-value="eventId !== null"
    position="right"
    full-height
    no-route-dismiss
    transition-show="slide-left"
    transition-hide="slide-right"
    @update:model-value="onDialogUpdate"
  >
    <q-card
      class="event-drawer"
      role="dialog"
      aria-label="Event detail"
    >
      <EventDetailPanel
        v-if="eventId !== null"
        :event-id="eventId"
        :detail="detail.detail.value"
        :loading="detail.loading.value"
        :error="detail.error.value"
        :not-found="detail.notFound.value"
        :has-previous="hasNeighbour(-1)"
        :has-next="hasNeighbour(1)"
        :annotatable="annotatable"
        @close="query.closeEvent()"
        @previous="step(-1)"
        @next="step(1)"
        @retry="detail.reload()"
        @open-event="query.openEvent($event)"
      />
    </q-card>
  </q-dialog>
</template>

<!-- Not scoped: QDialog's root is a teleport, which carries no scope attribute. -->
<style>
/* Docked to the right edge, not floating: Quasar pads a dialog 24px from the window. */
.event-drawer-dialog .q-dialog__inner {
  padding: 0;
}
</style>

<style scoped>
.event-drawer {
  width: 480px;
  max-width: 100vw;
  height: 100%;
  max-height: 100%;
  border-width: 0 0 0 2px;
}
</style>
