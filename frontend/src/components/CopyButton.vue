<script setup lang="ts">
import { copyToClipboard, Notify } from 'quasar'
import { computed, ref } from 'vue'
import { t } from '@/i18n'

/** `text` may be fetched when pressed; fetching nothing copies nothing and says nothing, the one that fetched has reported why. */
const props = defineProps<{ text: string | (() => Promise<string | undefined>); what: string; label?: string; disabled?: boolean }>()

const fetching = ref(false)
const unavailable = computed(() => props.disabled === true || fetching.value)

async function textToCopy(): Promise<string | undefined> {
  if (typeof props.text === 'string') return props.text
  fetching.value = true
  try {
    return await props.text()
  } finally {
    fetching.value = false
  }
}

async function copy(): Promise<void> {
  const text = await textToCopy()
  if (text === undefined) return
  try {
    await copyToClipboard(text)
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
    :aria-busy="fetching"
    :disabled="unavailable"
    @click="copy"
  >
    <q-spinner
      v-if="fetching"
      size="14px"
    />
    <q-icon
      v-else
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

.copy-button:disabled {
  cursor: default;
}

.copy-button:hover:enabled,
.copy-button:focus-visible:enabled {
  color: var(--blue-hover);
}
</style>
