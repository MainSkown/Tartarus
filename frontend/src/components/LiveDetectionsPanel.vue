<script setup lang="ts">
import { computed } from 'vue'
import PaneHeading from '@/components/PaneHeading.vue'
import ProcessChip from '@/components/ProcessChip.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import { t } from '@/i18n'
import { rulesetLabel } from '@/services/detection-groups'
import type { LiveDetection } from '@/services/live-detections'
import { processClock } from '@/services/process-graph'

const props = defineProps<{ detections: readonly LiveDetection[] }>()

const newestFirst = computed(() => [...props.detections].reverse())
const heading = computed(() =>
  props.detections.length > 0 ? t('live.detections.headingCount', { count: props.detections.length }) : t('live.detections.heading'),
)
</script>

<template>
  <section
    class="live-detections"
    data-live="detections"
  >
    <PaneHeading :label="heading" />
    <p
      v-if="detections.length === 0"
      class="live-detections__empty text-mono text-gray"
    >
      &gt; {{ t('live.detections.empty') }}
    </p>
    <ul
      v-else
      class="live-detections__list"
    >
      <li
        v-for="detection in newestFirst"
        :key="detection.id"
        class="live-detections__item"
        :data-detection-id="detection.id"
      >
        <div class="live-detections__head">
          <SeverityBadge :severity="detection.severity" />
          <span class="live-detections__ruleset text-mono text-gray">{{ rulesetLabel(detection.ruleset) }}</span>
          <span class="live-detections__time text-mono text-gray">{{ processClock(detection.time) }}</span>
        </div>
        <span
          class="live-detections__name text-mono"
          :title="detection.name"
        >{{ detection.name }}</span>
        <div class="live-detections__facts text-mono text-gray">
          <span
            v-if="detection.techniques.length > 0"
            class="live-detections__techniques"
          >{{ detection.techniques.join(' ') }}</span>
          <ProcessChip
            v-if="detection.process"
            :process="detection.process"
          />
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.live-detections {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-xs) var(--spacing-sm) var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.live-detections__empty {
  margin: var(--spacing-sm) 0 0;
  font-size: 0.75rem;
  line-height: 1.5;
}

.live-detections__list {
  display: flex;
  flex-direction: column;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.live-detections__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--spacing-xs) var(--spacing-xs) var(--spacing-xs) var(--spacing-sm);
  border-bottom: 1px solid var(--border-subtle);
}

.live-detections__head {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
}

.live-detections__ruleset,
.live-detections__time {
  font-size: 0.7rem;
  letter-spacing: 1px;
}

.live-detections__time {
  margin-left: auto;
}

.live-detections__name {
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.live-detections__facts {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--spacing-sm);
  font-size: 0.7rem;
}
</style>
