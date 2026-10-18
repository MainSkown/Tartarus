<script setup lang="ts">
import { computed } from 'vue'
import CopyButton from '@/components/CopyButton.vue'
import { t } from '@/i18n'
import { useQueryStateStore } from '@/stores/query-state'

const props = withDefaults(defineProps<{ field: string; value: string | number; filterable?: boolean }>(), {
  filterable: true,
})
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
      v-if="filterable"
      type="button"
      class="field-actions__button"
      :aria-label="t('events.filter.onTarget', { target })"
      :title="t('events.filter.on')"
      @click="filter(false)"
    >
      <q-icon
        name="add"
        size="14px"
      />
    </button>
    <button
      v-if="filterable"
      type="button"
      class="field-actions__button"
      :aria-label="t('events.filter.outTarget', { target })"
      :title="t('events.filter.out')"
      @click="filter(true)"
    >
      <q-icon
        name="remove"
        size="14px"
      />
    </button>
    <CopyButton
      :text="text"
      :what="t('events.fields.valueNoun', { field })"
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
