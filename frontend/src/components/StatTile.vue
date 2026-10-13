<script setup lang="ts">
defineProps<{ label: string; value?: string | number | null }>()
</script>

<template>
  <div class="stat-tile">
    <span class="stat-tile__label text-mono">{{ label }}</span>
    <span class="stat-tile__value text-mono">
      <slot>{{ value ?? '–' }}</slot>
    </span>
  </div>
</template>

<style scoped>
.stat-tile {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 7rem;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--border-primary);
  background: var(--card-bg);
}

.stat-tile__label {
  color: var(--blue-primary);
  font-size: 0.65rem;
  font-weight: bold;
  letter-spacing: 1px;
}

.stat-tile__value {
  font-size: 1.25rem;
  overflow-wrap: anywhere;
}
</style>
