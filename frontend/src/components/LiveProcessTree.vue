<script setup lang="ts">
import { computed } from 'vue'
import PaneHeading from '@/components/PaneHeading.vue'
import { t } from '@/i18n'
import ProcessChip from '@/components/ProcessChip.vue'
import { treeRows, type ProcessTreeNode } from '@/services/live-state'
import { processLifetime } from '@/services/process-graph'

const props = defineProps<{ roots: ProcessTreeNode[]; selectedPid?: number; emptyMessage: string; runOver?: boolean }>()
const emit = defineEmits<{ select: [pid: number | undefined] }>()

const rows = computed(() => treeRows(props.roots))

// A process the guest never reported an end for was cut off by the end of the run, not still running.
const isRunning = (process: { end: string | null }): boolean => process.end === null && !props.runOver

function toggle(pid: number): void {
  emit('select', pid === props.selectedPid ? undefined : pid)
}
</script>

<template>
  <section
    class="live-processes"
    data-live="processes"
  >
    <PaneHeading :label="t('live.processes.heading', { count: rows.length })" />
    <ul
      v-if="rows.length > 0"
      class="live-processes__list"
    >
      <li
        v-for="{ process, depth } in rows"
        :key="process.pid"
      >
        <button
          type="button"
          class="live-process text-mono"
          :class="{ 'live-process--ended': !isRunning(process), 'live-process--selected': process.pid === selectedPid }"
          :data-depth="depth"
          :style="{ paddingLeft: `calc(var(--spacing-sm) + ${depth} * 1.1rem)` }"
          :aria-pressed="process.pid === selectedPid"
          @click="toggle(process.pid)"
        >
          <span
            v-if="isRunning(process)"
            class="live-dot live-process__dot"
            aria-hidden="true"
          />
          <span
            v-else
            class="live-process__dot"
            aria-hidden="true"
          />
          <ProcessChip :process="process" />
          <span class="live-process__state">{{ isRunning(process) ? t('live.processes.running') : t('live.processes.ended') }}</span>
          <span
            v-if="process.end !== null"
            class="live-process__lifetime"
          >{{ processLifetime(process) }}</span>
        </button>
      </li>
    </ul>
    <p
      v-else
      class="live-processes__empty text-mono text-gray"
    >
      &gt; {{ emptyMessage }}
    </p>
  </section>
</template>

<style scoped>
.live-processes {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-xs) var(--spacing-sm) var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.live-processes__list {
  flex: 1 1 0;
  min-height: 0;
  margin: 0;
  padding: 0;
  overflow: auto;
  list-style: none;
}

.live-processes__empty {
  margin: var(--spacing-sm) 0 0;
  font-size: 0.75rem;
}

.live-process {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  width: 100%;
  min-width: 0;
  padding: 2px var(--spacing-sm);
  border: none;
  background: transparent;
  color: var(--text-white);
  font-size: 0.8rem;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--transition-fast);
}

.live-process:hover {
  background: var(--hover-bg);
}

.live-process--selected {
  background: var(--hover-bg);
  box-shadow: inset 0 0 0 2px var(--blue-light), var(--shadow-blue-weak);
}

.live-process--ended {
  opacity: 0.6;
}

.live-process__dot {
  flex: none;
  width: 8px;
  height: 8px;
  border: 1px solid var(--text-gray-dark);
}

.live-process__dot.live-dot {
  border: none;
}

.live-process__state {
  margin-left: auto;
  color: var(--text-gray);
  font-size: 0.65rem;
  letter-spacing: 1px;
}

.live-process__lifetime {
  flex: none;
  min-width: 3.5ch;
  color: var(--text-gray);
  font-size: 0.7rem;
  text-align: right;
}

@media (prefers-reduced-motion: reduce) {
  .live-process__dot.live-dot {
    animation: none;
  }
}
</style>
