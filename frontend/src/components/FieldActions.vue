<script setup lang="ts">
import { computed } from 'vue'
import CopyButton from '@/components/CopyButton.vue'
import { useQueryStateStore } from '@/stores/query-state'

const props = defineProps<{ field: string; value: string | number }>()
const store = useQueryStateStore()

const text = computed(() => String(props.value))
const target = computed(() => `${props.field}: ${text.value}`)

function filter(negate: boolean): void {
  store.addChip({ field: props.field, value: text.value, negate })
}
</script>

<template>
  <span class="field-actions">
    <button
      type="button"
      class="field-actions__button"
      :aria-label="`Filter on ${target}`"
      title="Filter on"
      @click="filter(false)"
    >
      <q-icon
        name="add"
        size="14px"
      />
    </button>
    <button
      type="button"
      class="field-actions__button"
      :aria-label="`Filter out ${target}`"
      title="Filter out"
      @click="filter(true)"
    >
      <q-icon
        name="remove"
        size="14px"
      />
    </button>
    <CopyButton
      :text="text"
      :what="`${field} value`"
    />
  </span>
</template>

<style scoped>
.field-actions {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 2px;
  vertical-align: middle;
}

.field-actions__button {
  padding: 2px;
  border: none;
  background: transparent;
  color: var(--text-gray);
  cursor: pointer;
  line-height: 0;
}

.field-actions__button:hover,
.field-actions__button:focus-visible {
  color: var(--blue-hover);
}
</style>
