<script setup lang="ts">
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import { t } from '@/i18n'

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
      :aria-label="t('widgets.view.loading')"
    />
  </div>
  <div
    v-else-if="error"
    class="view-state text-mono"
  >
    <p class="text-gray">
      &gt; {{ t('widgets.view.failed', { error }) }}
    </p>
    <q-btn
      outline
      square
      :label="t('common.retry')"
      class="retry-btn text-mono"
      @click="emit('retry')"
    />
  </div>
  <TerminalEmpty
    v-else-if="empty"
    :message="emptyMessage ?? t('widgets.view.nothingToShow')"
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
