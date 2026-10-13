<script setup lang="ts">
withDefaults(defineProps<{ level?: 'info' | 'warning' }>(), { level: 'info' })
</script>

<template>
  <p
    class="live-notice text-mono"
    :class="`live-notice--${level}`"
    :role="level === 'warning' ? 'alert' : 'status'"
  >
    <q-icon
      :name="level === 'warning' ? 'warning' : 'info_outline'"
      size="14px"
      aria-hidden="true"
    />
    <span class="live-notice__text"><slot /></span>
  </p>
</template>

<style scoped>
.live-notice {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-sm);
  min-width: 0;
  margin: 0;
  padding: var(--spacing-xs) var(--spacing-sm);
  border-left: 2px solid var(--text-gray-dark);
  background: var(--dark-bg);
  color: var(--text-gray);
  font-size: 0.7rem;
  line-height: 1.4;
}

.live-notice--warning {
  border-left-color: var(--status-medium);
  color: var(--status-medium);
}

.live-notice__text {
  min-width: 0;
  overflow-wrap: anywhere;
}
</style>
