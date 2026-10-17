<script setup lang="ts">
import GuestTextInput from '@/components/guest/GuestTextInput.vue'

withDefaults(defineProps<{ modelValue: string; error?: string; label?: string }>(), { label: 'GUEST NAME', error: undefined })
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <div class="name-field">
    <GuestTextInput
      :model-value="modelValue"
      :label="label"
      :error="error"
      class="name-field__input text-mono"
      @update:model-value="(value) => $emit('update:modelValue', value)"
    />
    <p class="name-field__hint">
      Only Tartarus sees this name; Windows never does.
    </p>
  </div>
</template>

<style scoped>
.name-field {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.name-field__hint {
  margin: 0;
  color: var(--text-gray);
  font-size: 0.75rem;
}
</style>
