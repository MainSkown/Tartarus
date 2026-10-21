<script setup lang="ts">
defineProps<{ label: string }>()
</script>

<template>
  <div class="pane-heading text-mono">
    <h3 class="pane-heading__title">
      {{ label }}
    </h3>
    <div
      v-if="$slots.default"
      class="pane-heading__actions"
    >
      <slot />
    </div>
  </div>
</template>

<style scoped>
.pane-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0 var(--spacing-sm);
  min-height: var(--pane-heading-height);
  margin: 0 0 var(--spacing-xs);
  padding: 0 var(--spacing-sm);
  border-bottom: 2px solid var(--border-primary);
}

.pane-heading__title {
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.75rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

.pane-heading__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0 var(--spacing-xs);
  min-width: 0;
  margin-left: auto;
}

/* Whatever the buttons are made of, in a panel header they share one height, so the row never reads ragged. */
.pane-heading__actions :deep(.q-btn),
.pane-heading__actions :deep(.copy-button) {
  display: inline-flex;
  align-items: center;
  min-height: var(--pane-action-height);
  padding: 0 var(--spacing-xs);
  font-size: 0.75rem;
  line-height: 1;
}
</style>
