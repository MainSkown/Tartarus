<script setup lang="ts">
import type { GuestResources } from '@/api'
import NumberInput from '@/components/NumberInput.vue'
import { t } from '@/i18n'

const props = defineProps<{
  modelValue: GuestResources
  errors?: Record<string, string>
  minDisk?: number
  diskLocked?: boolean
  diskReason?: string
  disable?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: GuestResources] }>()

function errorOf(key: keyof GuestResources): string | undefined {
  return props.errors?.[`resources.${key}`]
}

const FIELDS = [
  { key: 'vcpus', labelKey: 'guests.resources.field.vcpus', suffixKey: undefined },
  { key: 'ram_mb', labelKey: 'guests.resources.field.ram', suffixKey: 'guests.resources.unit.mb' },
  { key: 'disk_gb', labelKey: 'guests.resources.field.disk', suffixKey: 'guests.resources.unit.gb' },
] as const

function change(key: keyof GuestResources, value: string | number | null): void {
  emit('update:modelValue', { ...props.modelValue, [key]: Number(value) })
}

function noteOf(key: keyof GuestResources): string | undefined {
  if (key !== 'disk_gb') return undefined
  if (props.diskLocked) return props.diskReason
  return props.minDisk ? t('guests.resources.minimumDisk', { gb: props.minDisk }) : undefined
}
</script>

<template>
  <div class="resources-fields">
    <div
      v-for="field in FIELDS"
      :key="field.key"
      class="resources-fields__item"
    >
      <number-input
        :model-value="modelValue[field.key]"
        :label="t(field.labelKey)"
        :suffix="field.suffixKey && t(field.suffixKey)"
        :disable="disable || (field.key === 'disk_gb' && diskLocked)"
        :error="Boolean(errorOf(field.key))"
        :error-message="errorOf(field.key)"
        square
        dark
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

.resources-fields__note {
  margin: 0;
  color: var(--text-gray);
  font-size: 0.75rem;
}
</style>
