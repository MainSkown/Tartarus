<script setup lang="ts">
import { computed, ref } from 'vue'
import { MAX_COLUMNS, columnFieldGroups, offeredColumnFields } from '@/services/event-columns'
import { useFieldCatalogStore } from '@/stores/field-catalog'

defineProps<{ chosen: string[]; atLimit: boolean }>()
const emit = defineEmits<{ toggle: [field: string]; clear: [] }>()

const catalog = useFieldCatalogStore()
const search = ref('')
const groups = computed(() => columnFieldGroups(offeredColumnFields(catalog.fields), search.value))
</script>

<template>
  <button
    type="button"
    class="column-chooser__trigger button text-mono"
    :class="{ 'is-active': chosen.length > 0 }"
    aria-haspopup="true"
    aria-label="Columns"
    :title="chosen.length > 0 ? `Columns: ${chosen.length} added` : 'Choose columns'"
  >
    <q-icon
      name="view_column"
      size="16px"
      aria-hidden="true"
    /><span
      v-if="chosen.length > 0"
      class="column-chooser__count"
    >+{{ chosen.length }}</span>
    <q-menu
      class="column-chooser"
      anchor="bottom right"
      self="top right"
      @before-show="catalog.load()"
    >
      <div class="column-chooser__body">
        <q-input
          v-model="search"
          class="column-chooser__search"
          dense
          outlined
          square
          dark
          clearable
          placeholder="find a field"
          aria-label="Find a field"
        />
        <p
          v-if="atLimit"
          class="column-chooser__limit text-mono"
          role="status"
        >
          {{ MAX_COLUMNS }} columns is the most a search returns: remove one to add another
        </p>
        <div class="column-chooser__list scrollable-panel">
          <p
            v-if="groups.length === 0"
            class="column-chooser__empty text-mono text-gray"
          >
            &gt; {{ catalog.fields.length === 0 ? 'loading fields' : 'no field matches' }}
          </p>
          <section
            v-for="group in groups"
            :key="group.name"
          >
            <h4 class="column-chooser__group text-mono">
              {{ group.name }}
            </h4>
            <label
              v-for="field in group.fields"
              :key="field.name"
              class="column-chooser__field"
              :title="field.description"
            >
              <input
                type="checkbox"
                class="checkbox-input"
                :checked="chosen.includes(field.name)"
                :disabled="atLimit && !chosen.includes(field.name)"
                @change="emit('toggle', field.name)"
              >
              <span class="column-chooser__name text-mono">{{ field.name }}</span>
            </label>
          </section>
        </div>
        <div class="column-chooser__footer text-mono">
          <span class="text-gray">fields the table can show</span>
          <button
            type="button"
            class="column-chooser__reset button text-mono"
            :disabled="chosen.length === 0"
            @click="emit('clear')"
          >
            RESET
          </button>
        </div>
      </div>
    </q-menu>
  </button>
</template>

<style scoped>
.column-chooser__trigger {
  gap: var(--spacing-xs);
  min-width: 24px;
  height: 22px;
  padding: 0 var(--spacing-xs);
  border: 1px solid var(--border-primary);
  font-size: 0.65rem;
  letter-spacing: 1px;
  white-space: nowrap;
}

.column-chooser__trigger.is-active:hover {
  color: var(--text-white);
}

.column-chooser__count {
  font-weight: bold;
}

.column-chooser__body {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  width: 20rem;
  max-width: 90vw;
  /* Quasar caps the menu to the room left in the window; the list takes what the rest leaves. */
  max-height: inherit;
  padding: var(--spacing-sm);
}

.column-chooser__search :deep(.q-field__native) {
  font-family: var(--font-mono);
  font-size: 0.8rem;
}

.column-chooser__list {
  flex: 1 1 auto;
  min-height: 5rem;
}

.column-chooser__group {
  margin: var(--spacing-sm) 0 var(--spacing-xs);
  color: var(--blue-primary);
  font-size: 0.65rem;
  line-height: 1.2;
  letter-spacing: 1px;
  text-transform: uppercase;
}

.column-chooser__field {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: 2px var(--spacing-xs);
  cursor: pointer;
}

.column-chooser__field:has(:disabled) {
  opacity: 0.5;
  cursor: not-allowed;
}

.column-chooser__limit {
  margin: 0;
  padding: var(--spacing-xs) var(--spacing-sm);
  border: 1px solid var(--status-medium);
  color: var(--status-medium);
  font-size: 0.7rem;
  line-height: 1.3;
}

.column-chooser__field:hover {
  background: var(--hover-bg);
}

.column-chooser__name {
  min-width: 0;
  overflow: hidden;
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.column-chooser__empty {
  margin: 0;
  font-size: 0.75rem;
}

.column-chooser__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-sm);
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--border-subtle);
  font-size: 0.65rem;
}

.column-chooser__reset {
  min-height: 22px;
  padding: 0 var(--spacing-sm);
  border: 1px solid var(--border-primary);
  font-size: 0.65rem;
  letter-spacing: 1px;
}

.column-chooser__reset:disabled {
  color: var(--text-gray-darker);
  cursor: not-allowed;
}
</style>
