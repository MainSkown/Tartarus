<script setup lang="ts">
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import type { AnalysisRead } from '@/api'

defineProps<{ analysis: AnalysisRead }>()
</script>

<template>
  <section data-tab="detections">
    <TerminalEmpty message="the detections view is not built yet" />
  </section>
</template>
