<script setup lang="ts">
import { computed } from 'vue'
import type { BuildStep } from '@/api'
import { useNow } from '@/composables/use-now'
import { t } from '@/i18n'
import { humanStepName, stepDurationLabel, stepMeta } from '@/services/guest-build'

const props = defineProps<{ steps: readonly BuildStep[] }>()

const TICK_MS = 1_000
const now = useNow(TICK_MS)

const rows = computed(() =>
  props.steps.map((step) => ({
    step,
    meta: stepMeta(step.status),
    name: humanStepName(step.name),
    duration: stepDurationLabel(step, now.value),
  })),
)
</script>

<template>
  <ol
    v-if="rows.length > 0"
    class="build-steps"
  >
    <li
      v-for="{ step, meta, name, duration } in rows"
      :key="step.name"
      class="build-step"
      :class="`build-step--${step.status}`"
      :data-status="step.status"
      :style="{ '--step-color': `var(${meta.color})` }"
    >
      <span class="build-step__mark">
        <span
          v-if="step.status === 'running'"
          class="loader build-step__spinner"
          aria-hidden="true"
        />
        <q-icon
          v-else
          :name="meta.icon"
          size="18px"
          aria-hidden="true"
        />
      </span>
      <span class="build-step__text">
        <span class="build-step__name text-mono">{{ name }}</span>
        <span
          class="build-step__status text-mono"
        >{{ meta.label }}</span>
        <span
          v-if="step.status === 'failed' && step.exit_code != null"
          class="build-step__exit text-mono"
        >{{ t('guests.buildSteps.exit', { code: step.exit_code }) }}</span>
        <q-icon
          v-if="step.desktop"
          name="desktop_windows"
          size="14px"
          class="build-step__desktop"
          :title="t('guests.buildSteps.desktop')"
          data-step-desktop
        />
      </span>
      <span
        v-if="duration"
        class="build-step__duration text-mono"
      >{{ duration }}</span>
    </li>
  </ol>
  <p
    v-else
    class="build-steps__empty text-mono text-gray"
  >
    {{ t('guests.buildSteps.empty') }}
  </p>
</template>

<style scoped>
.build-steps {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.build-step {
  display: grid;
  grid-template-columns: 1.5rem minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm);
  border-left: 3px solid transparent;
  border-bottom: 1px solid var(--border-subtle);
}

.build-step--running {
  border-left-color: var(--blue-primary);
  background: var(--hover-bg);
}

.build-step--failed {
  border-left-color: var(--status-critical);
  background: rgba(239, 68, 68, 0.1);
}

.build-step--paused {
  border-left-color: var(--status-medium);
  background: rgba(234, 179, 8, 0.1);
}

.build-step__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--step-color);
}

.build-step__spinner {
  --size: 0.3px;
}

.build-step__text {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--spacing-sm);
  min-width: 0;
}

.build-step__name {
  color: var(--text-white);
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}

.build-step--pending .build-step__name {
  color: var(--text-gray);
}

.build-step__status {
  color: var(--step-color);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.build-step__exit {
  color: var(--status-critical);
  font-size: 0.7rem;
}

.build-step__desktop {
  align-self: center;
  color: var(--text-gray-dark);
}

.build-step__duration {
  color: var(--text-gray);
  font-size: 0.75rem;
  white-space: nowrap;
}

.build-steps__empty {
  margin: 0;
  padding: var(--spacing-md);
}
</style>
