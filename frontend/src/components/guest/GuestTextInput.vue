<script setup lang="ts">
import { ref } from 'vue'
import { t } from '@/i18n'

defineProps<{ modelValue: string; label: string; error?: string; revealable?: boolean; disable?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const revealed = ref(false)
</script>

<template>
  <q-input
    :model-value="modelValue"
    :label="label"
    :type="revealable && !revealed ? 'password' : 'text'"
    outlined
    dense
    square
    dark
    hide-bottom-space
    stack-label
    autocomplete="off"
    :disable="disable"
    :error="Boolean(error)"
    :error-message="error"
    @update:model-value="(value) => emit('update:modelValue', String(value ?? ''))"
  >
    <template
      v-if="revealable && !disable"
      #append
    >
      <q-btn
        flat
        dense
        square
        :icon="revealed ? 'visibility_off' : 'visibility'"
        :aria-label="revealed ? t('guests.textInput.hide') : t('guests.textInput.show')"
        :aria-pressed="revealed"
        class="guest-text-input__reveal"
        @click="revealed = !revealed"
      />
    </template>
  </q-input>
</template>

<style scoped>
.guest-text-input__reveal {
  color: var(--text-gray);
}
</style>
