<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ process: { pid: number; name: string | null } | null }>()

const label = computed(() => {
  const { process } = props
  if (process === null) return '–'
  return process.name ? `${process.name} (${process.pid})` : `pid ${process.pid}`
})
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
