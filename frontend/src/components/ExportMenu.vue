<script setup lang="ts">
import type { AnalysisRead } from '@/api'
import ExportEntries from '@/components/ExportEntries.vue'

defineProps<{ analysis: AnalysisRead }>()
</script>

<template>
  <q-btn
    outline
    square
    label="[EXPORT]"
    class="export-menu__button text-mono"
    aria-haspopup="menu"
  >
    <q-menu
      anchor="bottom right"
      self="top right"
    >
      <ExportEntries :analysis="analysis" />
    </q-menu>
  </q-btn>
</template>

<style scoped>
.export-menu__button {
  color: var(--blue-primary);
}
</style>
