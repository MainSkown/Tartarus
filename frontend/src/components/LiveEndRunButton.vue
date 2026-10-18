<script setup lang="ts">
import { t } from '@/i18n'
import type { EndRunPhase } from '@/services/end-run'

const props = defineProps<{ phase: EndRunPhase; label: string; title: string }>()
const emit = defineEmits<{ press: [] }>()
</script>

<template>
  <span
    v-if="props.phase !== 'hidden'"
    class="live-end-run"
    :title="title"
  >
    <q-btn
      outline
      square
      dense
      no-caps
      :label="t('live.endRun.button', { label })"
      class="live-end-run__button text-mono"
      data-live="end-run"
      :data-phase="phase"
      :disable="phase !== 'ready'"
      @click="emit('press')"
    />
  </span>
</template>

<style scoped>
.live-end-run {
  display: inline-flex;
  flex: none;
}

.live-end-run__button {
  color: var(--status-critical);
  font-size: 0.7rem;
  letter-spacing: 1px;
}
</style>
