<script setup lang="ts">
import TagChip from '@/components/TagChip.vue'

defineProps<{ badges: readonly string[] }>()
</script>

<template>
  <ul
    v-if="badges.length > 0"
    class="guest-badges"
  >
    <li
      v-for="badge in badges"
      :key="badge"
    >
      <TagChip :name="badge" />
    </li>
  </ul>
</template>

<style scoped>
.guest-badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}

.guest-badges li {
  display: flex;
  min-width: 0;
  max-width: 100%;
}
</style>
