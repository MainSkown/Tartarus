<script setup lang="ts">
import { computed } from 'vue'
import { countdownDisplay } from '@/services/countdown'

const props = withDefaults(defineProps<{ seconds: number | null; interactive?: boolean; running?: boolean }>(), {
  interactive: false,
  running: false,
})

const display = computed(() => countdownDisplay(props.seconds, { interactive: props.interactive, running: props.running }))
</script>

<template>
  <span
    class="run-countdown text-mono"
    :class="{ 'run-countdown--warning': display.warning }"
  >{{ display.text }}</span>
</template>

<style scoped>
.run-countdown--warning {
  color: var(--status-medium);
}
</style>
