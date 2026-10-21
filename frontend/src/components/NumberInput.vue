<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'

const props = withDefaults(
  defineProps<{ modelValue?: string | number | null; min?: number; max?: number; step?: number; disable?: boolean }>(),
  { modelValue: undefined, min: undefined, max: undefined, step: 1, disable: false },
)
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const parsed = computed(() => (props.modelValue === '' || props.modelValue == null ? NaN : Number(props.modelValue)))

function stepBy(direction: 1 | -1): void {
  // An empty field has nothing to step from: the first press lands on the lowest allowed value.
  const stepped = Number.isNaN(parsed.value) ? 0 : parsed.value + direction * props.step
  const clamped = Math.min(props.max ?? Infinity, Math.max(props.min ?? -Infinity, stepped))
  emit('update:modelValue', String(clamped))
}
</script>

<template>
  <q-input
    :model-value="modelValue"
    type="number"
    :min="min"
    :max="max"
    :step="step"
    :disable="disable"
    outlined
    dense
    hide-bottom-space
    class="number-input"
    @update:model-value="(value) => emit('update:modelValue', String(value ?? ''))"
  >
    <template #append>
      <span class="number-input__steppers">
        <button
          type="button"
          class="number-input__step"
          :aria-label="t('widgets.numberInput.increase')"
          :disabled="disable"
          tabindex="-1"
          @click="stepBy(1)"
        >
          <q-icon
            name="keyboard_arrow_up"
            size="16px"
          />
        </button>
        <button
          type="button"
          class="number-input__step"
          :aria-label="t('widgets.numberInput.decrease')"
          :disabled="disable"
          tabindex="-1"
          @click="stepBy(-1)"
        >
          <q-icon
            name="keyboard_arrow_down"
            size="16px"
          />
        </button>
      </span>
    </template>
  </q-input>
</template>

<style scoped>
.number-input :deep(input[type='number']) {
  appearance: textfield;
}

.number-input :deep(input[type='number']::-webkit-inner-spin-button),
.number-input :deep(input[type='number']::-webkit-outer-spin-button) {
  appearance: none;
}

.number-input__steppers {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-primary);
}

.number-input__step {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 14px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--text-gray);
  cursor: pointer;
}

.number-input__step + .number-input__step {
  border-top: 1px solid var(--border-primary);
}

.number-input__step:hover:not(:disabled),
.number-input__step:focus-visible {
  background: var(--border-subtle);
  color: var(--blue-hover);
}

.number-input__step:disabled {
  cursor: default;
  opacity: 0.4;
}
</style>
