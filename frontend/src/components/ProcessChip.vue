<script setup lang="ts">
import { computed } from 'vue'
import { processTitle } from '@/services/process-graph'

const props = defineProps<{ process: { pid: number; name: string | null } | null }>()

const label = computed(() => (props.process === null ? '–' : processTitle(props.process)))
</script>

<template>
  <span
    class="process-chip text-mono"
    :title="process ? label : undefined"
  >{{ label }}</span>
</template>

<style scoped>
.process-chip {
  display: inline-block;
  max-width: 24ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
</style>
