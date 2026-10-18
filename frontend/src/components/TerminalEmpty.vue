<script setup lang="ts">
import { t } from '@/i18n'

// The shared terminal-style empty-state line (gui spec "States and feedback" -> Empty:
// `> no events match`). Used both as a stand-in for pages that have no real content yet
// (PlaceholderPage.vue) and later for genuine empty states (e.g. "no analyses yet").
const props = withDefaults(defineProps<{ message?: string }>(), {
  message: () => t('widgets.terminal.notImplemented'),
})
</script>

<template>
  <p class="terminal-empty text-mono text-gray">
    &gt; {{ props.message }}
  </p>
</template>

<style scoped>
.terminal-empty {
  padding: var(--spacing-md);
}
</style>
