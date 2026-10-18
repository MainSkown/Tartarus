<script setup lang="ts">
import { t } from '@/i18n'
import { extendLabel } from '@/services/extend-run'

const props = defineProps<{ visible: boolean; disabled: boolean; title: string }>()
const emit = defineEmits<{ press: [] }>()
</script>

<template>
  <span
    v-if="props.visible"
    class="live-extend-run"
    :title="title"
  >
    <q-btn
      outline
      square
      dense
      no-caps
      :label="t('live.extend.button', { label: extendLabel() })"
      class="live-extend-run__button text-mono"
      data-live="extend-run"
      :disable="disabled"
      @click="emit('press')"
    />
  </span>
</template>

<style scoped>
.live-extend-run {
  display: inline-flex;
  flex: none;
}

.live-extend-run__button {
  color: var(--blue-primary);
  font-size: 0.7rem;
  letter-spacing: 1px;
}
</style>
