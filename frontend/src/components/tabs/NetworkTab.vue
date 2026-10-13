<script setup lang="ts">
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import type { AnalysisRead } from '@/api'

defineProps<{ analysis: AnalysisRead }>()
</script>

<template>
  <section data-tab="network">
    <TerminalEmpty message="the network view is not built yet" />
  </section>
</template>
