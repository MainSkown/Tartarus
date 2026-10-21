<script setup lang="ts">
import { onMounted } from 'vue'
import FieldActions from '@/components/FieldActions.vue'
import IocAnalysesLink from '@/components/IocAnalysesLink.vue'
import { t } from '@/i18n'
import type { SourceField } from '@/services/event-source'
import { iocKindOfField } from '@/services/events-filters'
import { useFieldCatalogStore } from '@/stores/field-catalog'

defineProps<{ fields: SourceField[] }>()

const catalog = useFieldCatalogStore()

// A composite alias such as `domain` stands for several fields, so a chip on it is not one field's value.
function isFilterable(name: string): boolean {
  const field = catalog.find(name)
  return field !== undefined && field.searchable && field.members.length === 0
}

onMounted(() => void catalog.load())
</script>

<template>
  <div
    class="fields-table"
    role="table"
    :aria-label="t('events.fields.label')"
  >
    <div
      v-for="(field, index) in fields"
      :key="`${field.name}-${index}`"
      class="field-row"
      role="row"
    >
      <span
        class="field-row__name text-mono"
        role="rowheader"
      >{{ field.name }}</span>
      <span
        class="field-row__value text-mono"
        role="cell"
      >{{ field.value }}</span>
      <span class="field-row__actions">
        <IocAnalysesLink
          v-if="iocKindOfField(field.name)"
          :kind="iocKindOfField(field.name)!"
          :value="field.value"
        />
        <FieldActions
          :field="field.name"
          :value="field.value"
          :filterable="isFilterable(field.name)"
        />
      </span>
    </div>
  </div>
</template>

<style scoped>
.fields-table {
  border-top: 1px solid var(--border-subtle);
}

/* The name sits above the value so a long command line or path has the whole width to wrap in. */
.field-row {
  display: grid;
  grid-template-areas:
    'name actions'
    'value value';
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  column-gap: var(--spacing-sm);
  padding: 3px var(--spacing-xs) 5px;
  border-bottom: 1px solid var(--border-subtle);
}

.field-row:hover {
  background: var(--hover-bg);
}

.field-row__name {
  grid-area: name;
  color: var(--text-gray);
  font-size: 0.7rem;
  overflow-wrap: anywhere;
}

.field-row__value {
  grid-area: value;
  color: var(--text-white);
  font-size: 0.75rem;
  word-break: break-all;
}

.field-row__actions {
  grid-area: actions;
  display: inline-flex;
  align-items: center;
}
</style>
