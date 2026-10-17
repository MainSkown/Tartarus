<script setup lang="ts">
import type { GuestResources } from '@/api'

const props = defineProps<{
  modelValue: GuestResources
  errors?: Record<string, string>
  minDisk?: number
  diskLocked?: boolean
  diskReason?: string
  disable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: GuestResources] }>()

const FIELDS = [
  { key: 'vcpus', label: 'VCPUS', suffix: undefined },
  { key: 'ram_mb', label: 'RAM', suffix: 'MB' },
  { key: 'disk_gb', label: 'DISK', suffix: 'GB' },
] as const

function change(key: keyof GuestResources, value: string | number | null): void {
  emit('update:modelValue', { ...props.modelValue, [key]: Number(value) })
}

function noteOf(key: keyof GuestResources): string | undefined {
  if (key !== 'disk_gb') return undefined
  if (props.diskLocked) return props.diskReason
  return props.minDisk ? `minimum ${props.minDisk} GB` : undefined
}
</script>

<template>
  <div class="resources-fields">
    <div
      v-for="field in FIELDS"
      :key="field.key"
      class="resources-fields__item"
    >
      <q-input
        :model-value="modelValue[field.key]"
        :label="field.label"
        :suffix="field.suffix"
        :disable="disable || (field.key === 'disk_gb' && diskLocked)"
        :error="Boolean(errors?.[`resources.${field.key}`])"
        :error-message="errors?.[`resources.${field.key}`]"
        type="number"
        outlined
        dense
        square
        dark
        hide-bottom-space
        stack-label
        class="resources-fields__input text-mono"
        @update:model-value="(value) => change(field.key, value)"
      />
      <p
        v-if="noteOf(field.key)"
        class="resources-fields__note"
      >
        {{ noteOf(field.key) }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.resources-fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
  gap: var(--spacing-md);
}

.resources-fields__item {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
}

.resources-fields__input :deep(input[type='number']) {
  appearance: textfield;
}

.resources-fields__input :deep(input[type='number']::-webkit-inner-spin-button) {
  appearance: none;
}

.resources-fields__note {
  margin: 0;
  color: var(--text-gray);
  font-size: 0.75rem;
}
</style>
