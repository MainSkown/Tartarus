<script setup lang="ts">
import { copyToClipboard, Notify } from 'quasar'
import { t } from '@/i18n'

const props = defineProps<{ text: string; what: string; label?: string }>()

async function copy(): Promise<void> {
  try {
    await copyToClipboard(props.text)
    Notify.create({ type: 'tt-success', message: t('widgets.copy.copied', { what: props.what }) })
  } catch {
    Notify.create({ type: 'tt-error', message: t('widgets.copy.failed', { what: props.what }) })
  }
}
</script>

<template>
  <button
    type="button"
    class="copy-button"
    :aria-label="t('widgets.copy.label', { what })"
    @click="copy"
  >
    <q-icon
      name="content_copy"
      size="14px"
    />
    <span
      v-if="label"
      class="copy-button__label text-mono"
    >{{ label }}</span>
  </button>
</template>

<style scoped>
.copy-button {
  flex: none;
  padding: 2px;
  border: none;
  background: transparent;
  color: var(--text-gray);
  cursor: pointer;
  vertical-align: middle;
}

.copy-button__label {
  margin-left: var(--spacing-xs);
  font-size: 0.75rem;
}

.copy-button:hover,
.copy-button:focus-visible {
  color: var(--blue-hover);
}
</style>
