<script setup lang="ts">
import GuestTextInput from '@/components/guest/GuestTextInput.vue'
import type { ProfileOption } from '@/api'
import { t } from '@/i18n'

defineProps<{
  option: ProfileOption
  modelValue: unknown
  /** Shown with its value but not editable, for an option a clone cannot change. */
  locked?: boolean
  lockedReason?: string
  error?: string
}>()
defineEmits<{ 'update:modelValue': [value: unknown] }>()
</script>

<template>
  <div
    class="option-field"
    :class="{ 'option-field--locked': locked }"
  >
    <q-toggle
      v-if="option.type === 'bool'"
      :model-value="modelValue === true"
      :label="option.label"
      :disable="locked"
      dense
      dark
      class="option-field__control option-field__toggle text-mono"
      @update:model-value="(value) => $emit('update:modelValue', value)"
    />
    <q-select
      v-else-if="option.type === 'choice'"
      :model-value="modelValue"
      :options="option.choices ?? []"
      :label="option.label"
      :disable="locked"
      :error="Boolean(error)"
      :error-message="error"
      outlined
      dense
      square
      dark
      hide-bottom-space
      stack-label
      popup-content-class="option-field__menu"
      class="option-field__control text-mono"
      @update:model-value="(value) => $emit('update:modelValue', value)"
    />
    <GuestTextInput
      v-else
      :model-value="String(modelValue ?? '')"
      :label="option.label"
      :revealable="option.type === 'secret'"
      :disable="locked"
      :error="error"
      class="option-field__control text-mono"
      @update:model-value="(value) => $emit('update:modelValue', value)"
    />

    <p
      v-if="option.help"
      class="option-field__help"
    >
      {{ option.help }}
    </p>
    <p
      v-if="option.requires_user_step"
      class="option-field__step text-mono"
    >
      <q-icon
        name="back_hand"
        size="14px"
        aria-hidden="true"
      />
      {{ t('guests.option.manualStep') }}
    </p>
    <p
      v-if="locked && lockedReason"
      class="option-field__reason text-mono"
    >
      {{ lockedReason }}
    </p>
    <p
      v-if="error && option.type === 'bool'"
      class="option-field__error"
      role="alert"
    >
      {{ error }}
    </p>
  </div>
</template>

<style scoped>
.option-field {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  min-width: 0;
  padding: var(--spacing-md);
  border: 1px solid var(--border-subtle);
  background: var(--dark-bg);
}

.option-field--locked {
  opacity: 0.7;
}

.option-field__toggle {
  align-self: flex-start;
  font-size: 0.85rem;
}

.option-field__control {
  letter-spacing: 1px;
  text-transform: uppercase;
}

/* The value of a select is what the analyst reads, not a label. */
.option-field__control :deep(.q-field__native) {
  text-transform: none;
}

.option-field__help {
  margin: 0;
  max-width: 70ch;
  color: var(--text-gray);
  font-size: 0.8rem;
  line-height: 1.5;
}

.option-field__step,
.option-field__reason {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin: 0;
  color: var(--status-medium);
  font-size: 0.75rem;
}

.option-field__reason {
  color: var(--text-gray);
}

.option-field__error {
  margin: 0;
  color: var(--status-critical);
  font-size: 0.75rem;
}
</style>
