<script setup lang="ts">
import type { AnalysisRead } from '@/api'
import ExportEntries from '@/components/ExportEntries.vue'
import { t } from '@/i18n'

defineProps<{ analysis: AnalysisRead }>()
</script>

<template>
  <q-btn
    outline
    square
    :label="t('reports.export.button')"
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
