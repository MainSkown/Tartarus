<script setup lang="ts">
import { t } from '@/i18n'
import type { LaneBar } from '@/services/lanes'

defineProps<{ bars: LaneBar[] }>()
</script>

<template>
  <ul
    class="lane-bars"
    :aria-label="t('timeline.laneBars.ariaLabel')"
  >
    <li
      v-for="bar in bars"
      :key="bar.lane"
      class="lane-bar"
    >
      <span class="lane-bar__name text-mono">
        <q-icon
          :name="bar.icon"
          size="18px"
          :style="{ color: `var(${bar.color})` }"
          aria-hidden="true"
        />
        <span class="lane-bar__label">{{ bar.label }}</span>
      </span>
      <span class="lane-bar__track">
        <span
          class="lane-bar__fill"
          :style="{ width: `${bar.share * 100}%`, background: `var(${bar.color})` }"
        />
      </span>
      <span class="lane-bar__count text-mono">{{ bar.count }}</span>
    </li>
  </ul>
</template>

<style scoped>
.lane-bars {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr) max-content;
  gap: var(--spacing-sm) var(--spacing-md);
  max-width: 40rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.lane-bar {
  display: contents;
}

.lane-bar__name {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  font-size: 0.8rem;
  letter-spacing: 1px;
}

.lane-bar__track {
  align-self: center;
  height: 10px;
  background: var(--dark-bg);
}

.lane-bar__fill {
  display: block;
  height: 100%;
  min-width: 3px;
}

.lane-bar__count {
  min-width: 4ch;
  text-align: right;
}
</style>
