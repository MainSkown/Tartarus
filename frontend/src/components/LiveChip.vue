<script setup lang="ts">
import { computed, onScopeDispose, ref } from 'vue'
import type { RunningAnalysis } from '@/api'
import { t } from '@/i18n'
import { clockDuration, elapsedSecondsAt } from '@/services/queue-view'
import { useQueueStore } from '@/stores/queue'

const TICK_MS = 1000

const queue = useQueueStore()
const now = ref(Date.now())
const ticker = setInterval(() => (now.value = Date.now()), TICK_MS)
onScopeDispose(() => clearInterval(ticker))

const single = computed<RunningAnalysis | undefined>(() => (queue.runningCount === 1 ? queue.running[0] : undefined))

function clockOf(analysis: RunningAnalysis): string {
  return clockDuration(elapsedSecondsAt(analysis, now.value))
}

function analysisRoute(id: number) {
  return { name: 'analysis-workspace', params: { id } }
}
</script>

<template>
  <div
    v-if="queue.runningCount > 0"
    class="live-chip-host"
  >
    <router-link
      v-if="single"
      :to="analysisRoute(single.id)"
      class="live-chip text-mono"
    >
      <span
        class="live-dot"
        aria-hidden="true"
      />
      {{ t('shell.live.single', { id: single.id, clock: clockOf(single) }) }}
    </router-link>
    <button
      v-else
      type="button"
      class="live-chip text-mono"
      aria-haspopup="menu"
    >
      <span
        class="live-dot"
        aria-hidden="true"
      />
      {{ t('shell.live.count', { count: queue.runningCount }) }}
      <q-menu
        anchor="bottom right"
        self="top right"
        class="live-chip-menu"
      >
        <q-list
          dense
          :aria-label="t('shell.live.menuLabel')"
          class="text-mono"
        >
          <q-item-label
            header
            class="live-chip-menu__title"
          >
            {{ t('shell.live.menuTitle', { count: queue.runningCount }, queue.runningCount) }}
          </q-item-label>
          <q-item
            v-for="analysis in queue.running"
            :key="analysis.id"
            v-close-popup
            clickable
            :to="analysisRoute(analysis.id)"
            class="live-chip-menu__item"
          >
            <q-item-section>
              <q-item-label class="live-chip-menu__file">
                {{ t('shell.live.item', { id: analysis.id, filename: analysis.filename }) }}
              </q-item-label>
              <q-item-label
                caption
                class="live-chip-menu__meta"
              >
                {{ t('shell.live.meta', { guest: analysis.guest ?? t('shell.live.noGuest'), clock: clockOf(analysis) }) }}
              </q-item-label>
            </q-item-section>
          </q-item>
        </q-list>
      </q-menu>
    </button>
  </div>
</template>

<style scoped>
.live-chip-host {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.live-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
  padding: 2px var(--spacing-sm);
  border: 1px solid var(--blue-primary);
  background: transparent;
  color: var(--blue-primary);
  font: inherit;
  font-size: 0.8rem;
  letter-spacing: 1px;
  white-space: nowrap;
  cursor: pointer;
  text-decoration: none;
}

.live-chip:hover,
.live-chip:focus-visible {
  color: var(--blue-hover);
  border-color: var(--blue-hover);
}

</style>

<!-- Not scoped: the menu is teleported out of this component, so scoped selectors never reach it. -->
<style>
.live-chip-menu {
  max-width: min(24rem, 90vw);
}

.live-chip-menu__title {
  letter-spacing: 1px;
}

.live-chip-menu__item .q-item__section {
  min-width: 0;
}

.live-chip-menu__file,
.live-chip-menu__meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
