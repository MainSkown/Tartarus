<script setup lang="ts">
defineProps<{ name?: string | null; badges?: string[] }>()
</script>

<template>
  <span
    v-if="name"
    class="guest-chip text-mono"
  >
    <span
      class="guest-chip__name"
      :title="name"
    >{{ name }}</span>
    <span
      v-for="badge in badges"
      :key="badge"
      class="guest-chip__badge"
    >{{ badge }}</span>
  </span>
</template>

<style scoped>
.guest-chip {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  max-width: 100%;
  border: 1px solid var(--border-secondary);
  background: var(--black);
  font-size: 0.75rem;
  line-height: 1.5;
}

.guest-chip__name {
  min-width: 0;
  padding: 0 var(--spacing-sm);
  overflow: hidden;
  color: var(--blue-light);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.guest-chip__badge {
  flex: none;
  padding: 0 var(--spacing-xs);
  border-left: 1px solid var(--border-subtle);
  color: var(--text-gray);
  font-size: 0.65rem;
  letter-spacing: 1px;
  white-space: nowrap;
}
</style>
