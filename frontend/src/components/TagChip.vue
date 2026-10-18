<script setup lang="ts">
import { t } from '@/i18n'

defineProps<{ name: string; removable?: boolean }>()
const emit = defineEmits<{ remove: [] }>()
</script>

<template>
  <span
    class="tag-chip text-mono"
    :title="name"
  >
    <span class="tag-chip__label">{{ name }}</span>
    <button
      v-if="removable"
      type="button"
      class="tag-chip__remove"
      :aria-label="t('tags.chip.remove', { name })"
      @click.stop="emit('remove')"
    >
      <q-icon
        name="close"
        size="14px"
        aria-hidden="true"
      />
    </button>
  </span>
</template>

<style scoped>
.tag-chip {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  max-width: 100%;
  border: 1px solid var(--border-secondary);
  background: var(--black);
  color: var(--blue-light);
  font-size: 0.75rem;
  line-height: 1.5;
}

.tag-chip__label {
  min-width: 0;
  padding: 0 var(--spacing-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-chip__remove {
  display: inline-flex;
  flex: none;
  align-items: center;
  align-self: stretch;
  padding: 0 var(--spacing-xs);
  border: none;
  border-left: 1px solid var(--border-subtle);
  background: transparent;
  color: var(--text-gray);
  cursor: pointer;
}

.tag-chip__remove:hover,
.tag-chip__remove:focus-visible {
  background: var(--hover-bg);
  color: var(--status-critical);
}
</style>
