<script setup lang="ts">
defineProps<{ label: string }>()
</script>

<template>
  <h3 class="pane-heading text-mono">
    {{ label }}
  </h3>
</template>

<style scoped>
.pane-heading {
  margin: 0 0 var(--spacing-xs);
  padding: var(--spacing-xs) var(--spacing-sm);
  border-bottom: 2px solid var(--border-primary);
  color: var(--blue-primary);
  font-size: 0.75rem;
  line-height: 1.2;
  letter-spacing: 2px;
}
</style>
