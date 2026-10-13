<script setup lang="ts">
import TerminalEmpty from '@/components/TerminalEmpty.vue'

defineProps<{ loading?: boolean; error?: string; empty?: boolean; emptyMessage?: string }>()
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div
    v-if="loading"
    class="view-state"
  >
    <span
      class="loader"
      role="status"
      aria-label="Loading"
    />
  </div>
  <div
    v-else-if="error"
    class="view-state text-mono"
  >
    <p class="text-gray">
      &gt; failed to load: {{ error }}
    </p>
    <q-btn
      outline
      square
      label="[RETRY]"
      class="retry-btn text-mono"
      @click="emit('retry')"
    />
  </div>
  <TerminalEmpty
    v-else-if="empty"
    :message="emptyMessage ?? 'nothing to show'"
  />
  <slot v-else />
</template>

<style scoped>
.view-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-xl) 0;
}

.retry-btn {
  color: var(--blue-primary);
}
</style>
