<script setup lang="ts">
import type { DetectionGroup } from '@/api'
import SeverityBadge from '@/components/SeverityBadge.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import { t } from '@/i18n'
import { rulesetLabel } from '@/services/detection-groups'

defineProps<{ groups: DetectionGroup[]; selectedId: string | undefined }>()
const emit = defineEmits<{ select: [id: string] }>()
</script>

<template>
  <div class="detection-list">
    <section
      v-for="group in groups"
      :key="group.ruleset"
      class="detection-group"
    >
      <PaneHeading :label="rulesetLabel(group.ruleset)" />
      <button
        v-for="detection in group.detections"
        :key="detection.id"
        type="button"
        class="detection-entry"
        :aria-current="detection.id === selectedId"
        @click="emit('select', detection.id)"
      >
        <SeverityBadge :severity="detection.severity" />
        <span
          v-if="detection.related_event_total > 0"
          class="detection-entry__count text-mono text-gray"
        >{{ t('detections.list.events', detection.related_event_total) }}</span>
        <span class="detection-entry__name text-mono">{{ detection.name }}</span>
        <span
          v-if="detection.techniques.length > 0"
          class="detection-entry__techniques text-mono text-gray"
        >{{ detection.techniques.join(' ') }}</span>
      </button>
    </section>
  </div>
</template>

<style scoped>
.detection-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-width: 0;
}

.detection-group {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.detection-entry {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: center;
  gap: var(--spacing-xs) var(--spacing-sm);
  padding: var(--spacing-sm);
  border: none;
  border-left: 3px solid transparent;
  background: transparent;
  color: var(--text-white);
  text-align: left;
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.detection-entry:hover,
.detection-entry:focus-visible {
  background: var(--hover-bg);
}

.detection-entry[aria-current='true'] {
  border-left-color: var(--blue-primary);
  background: color-mix(in srgb, var(--active-bg) 35%, transparent);
}

.detection-entry__count {
  justify-self: end;
  font-size: 0.8rem;
}

.detection-entry__name {
  grid-column: 1 / -1;
  overflow-wrap: anywhere;
}

.detection-entry__techniques {
  grid-column: 1 / -1;
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}
</style>
