<script setup lang="ts">
import { computed } from 'vue'
import TagChip from '@/components/TagChip.vue'

const props = withDefaults(defineProps<{ tags: string[]; max?: number }>(), { max: 2 })

const shown = computed(() => props.tags.slice(0, props.max))
const hidden = computed(() => props.tags.slice(props.max))
</script>

<template>
  <span class="tag-list">
    <TagChip
      v-for="tag in shown"
      :key="tag"
      :name="tag"
    />
    <span
      v-if="hidden.length > 0"
      class="tag-list__more text-mono"
      :title="hidden.join(', ')"
    >+{{ hidden.length }}</span>
  </span>
</template>

<style scoped>
.tag-list {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  min-width: 0;
  max-width: 100%;
}

.tag-list > :deep(.tag-chip) {
  flex: 0 1 auto;
  max-width: 18ch;
}

.tag-list__more {
  flex: none;
  color: var(--text-gray);
  font-size: 0.75rem;
}
</style>
