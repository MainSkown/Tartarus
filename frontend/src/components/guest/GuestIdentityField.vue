<script setup lang="ts">
import { computed } from 'vue'
import GuestTextInput from '@/components/guest/GuestTextInput.vue'
import { BLANK_IDENTITY_LABEL } from '@/services/guest-form'

const props = withDefaults(
  defineProps<{
    modelValue: string
    label: string
    placeholder?: string
    error?: string
    hint?: string
    secret?: boolean
    /** Shown but not editable, with `reason` saying why. */
    readonly?: boolean
    reason?: string
  }>(),
  { placeholder: BLANK_IDENTITY_LABEL, error: undefined, hint: undefined, reason: undefined },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const blank = computed(() => props.modelValue === '')
const note = computed(() => (props.readonly ? props.reason : props.hint))
</script>

<template>
  <div class="identity-field">
    <div class="identity-field__row">
      <GuestTextInput
        :model-value="modelValue"
        :label="label"
        :error="error"
        :revealable="secret && !readonly"
        :disable="readonly"
        :placeholder="placeholder"
        class="identity-field__input text-mono"
        @update:model-value="(value) => emit('update:modelValue', value)"
      />
      <q-btn
        v-if="!readonly"
        flat
        square
        label="[RANDOM]"
        :aria-pressed="blank"
        class="identity-field__random text-mono"
        :class="{ 'is-active': blank }"
        @click="emit('update:modelValue', '')"
      />
    </div>
    <p
      v-if="note"
      class="identity-field__hint"
    >
      {{ note }}
    </p>
  </div>
</template>

<style scoped>
.identity-field {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
}

.identity-field__row {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-sm);
}

.identity-field__input {
  flex: 1 1 auto;
  min-width: 0;
}

.identity-field__random {
  flex: none;
  height: 40px;
  color: var(--text-gray);
  font-size: 0.8rem;
}

.identity-field__random:hover {
  color: var(--blue-hover);
}

.identity-field__random.is-active {
  background: var(--blue-dark);
  color: var(--text-white);
}

.identity-field__hint {
  margin: 0;
  color: var(--text-gray);
  font-size: 0.75rem;
}
</style>
