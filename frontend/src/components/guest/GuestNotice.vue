<script setup lang="ts">
defineProps<{ tone: 'error' | 'warning' }>()
</script>

<template>
  <div
    class="guest-notice"
    :class="`guest-notice--${tone}`"
    :role="tone === 'error' ? 'alert' : 'note'"
  >
    <q-icon
      :name="tone === 'error' ? 'dangerous' : 'warning'"
      size="18px"
      aria-hidden="true"
    />
    <div class="guest-notice__text">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.guest-notice {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  border: 2px solid currentColor;
  font-size: 0.85rem;
  line-height: 1.5;
}

.guest-notice--error {
  color: var(--status-critical);
}

.guest-notice--warning {
  color: var(--status-medium);
}

.guest-notice__text {
  min-width: 0;
  overflow-wrap: anywhere;
}
</style>
