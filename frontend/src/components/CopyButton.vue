<script setup lang="ts">
import { copyToClipboard, Notify } from 'quasar'

const props = defineProps<{ text: string; what: string }>()

async function copy(): Promise<void> {
  try {
    await copyToClipboard(props.text)
    Notify.create({ type: 'tt-success', message: `${props.what} copied` })
  } catch {
    Notify.create({ type: 'tt-error', message: `Could not copy the ${props.what}` })
  }
}
</script>

<template>
  <button
    type="button"
    class="copy-button"
    :aria-label="`Copy ${what}`"
    @click="copy"
  >
    <q-icon
      name="content_copy"
      size="14px"
    />
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

.copy-button:hover,
.copy-button:focus-visible {
  color: var(--blue-hover);
}
</style>
