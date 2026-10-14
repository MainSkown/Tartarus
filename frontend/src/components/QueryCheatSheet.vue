<script setup lang="ts">
import { watch } from 'vue'
import { QUERY_EXAMPLES } from '@/services/query-examples'
import { useFieldCatalogStore } from '@/stores/field-catalog'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean]; choose: [query: string] }>()

const catalog = useFieldCatalogStore()

const GRAMMAR = [
  'Terms next to each other are ANDed. NOT binds first, then AND, then OR; use parentheses to group.',
  'Words with no field search the summary, command line, paths, URL and API arguments.',
  'Values are case-insensitive. Quote a value that has spaces; a backslash is written as one or two.',
  '* and ? are wildcards. A bare * after the colon tests that the field exists.',
  'Numbers and dates take comparisons; a date alone is the whole day.',
]

const OPERATORS = [
  { syntax: 'field:value', meaning: 'the field equals the value' },
  { syntax: 'field:(a OR b)', meaning: 'the field equals any of the values' },
  { syntax: 'field:*', meaning: 'the field exists' },
  { syntax: 'field >= 1024', meaning: 'also >  <  <=, on numbers and dates' },
  { syntax: 'AND  OR  NOT', meaning: 'combine terms' },
  { syntax: '( )', meaning: 'group terms' },
  { syntax: '"two words"', meaning: 'a value with spaces' },
  { syntax: '*.exe  c?d', meaning: 'wildcards inside a value' },
]

function choose(query: string): void {
  emit('choose', query)
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) void catalog.load()
  },
  { immediate: true },
)
</script>

<template>
  <q-dialog
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <q-card class="query-cheat-sheet">
      <header class="query-cheat-sheet__header">
        <h2 class="query-cheat-sheet__title text-mono">
          QUERY SYNTAX
        </h2>
        <q-btn
          flat
          square
          no-caps
          dense
          class="query-cheat-sheet__close text-mono"
          label="CLOSE"
          @click="emit('update:modelValue', false)"
        />
      </header>

      <div class="query-cheat-sheet__body scrollable-panel">
        <div class="query-cheat-sheet__columns">
          <div class="query-cheat-sheet__column">
            <section>
              <h3 class="query-cheat-sheet__heading text-mono">
                GRAMMAR
              </h3>
              <ul class="query-cheat-sheet__grammar">
                <li
                  v-for="line in GRAMMAR"
                  :key="line"
                >
                  {{ line }}
                </li>
              </ul>
            </section>
          </div>

          <div class="query-cheat-sheet__column">
            <section>
              <h3 class="query-cheat-sheet__heading text-mono">
                OPERATORS
              </h3>
              <dl class="query-cheat-sheet__operators">
                <template
                  v-for="operator in OPERATORS"
                  :key="operator.syntax"
                >
                  <dt class="text-mono">
                    {{ operator.syntax }}
                  </dt>
                  <dd>{{ operator.meaning }}</dd>
                </template>
              </dl>
            </section>
          </div>

          <div class="query-cheat-sheet__column">
            <section>
              <h3 class="query-cheat-sheet__heading text-mono">
                EXAMPLES (CLICK TO TRY)
              </h3>
              <ul class="query-cheat-sheet__examples">
                <li
                  v-for="example in QUERY_EXAMPLES"
                  :key="example.query"
                >
                  <button
                    type="button"
                    class="query-cheat-sheet__example"
                    @click="choose(example.query)"
                  >
                    <code>{{ example.query }}</code>
                    <span class="query-cheat-sheet__note">{{ example.description }}</span>
                  </button>
                </li>
              </ul>
            </section>
          </div>
        </div>

        <section v-if="catalog.aliasRows.length > 0">
          <h3 class="query-cheat-sheet__heading text-mono">
            ALIASES
          </h3>
          <ul class="query-cheat-sheet__aliases">
            <li
              v-for="row in catalog.aliasRows"
              :key="row.alias"
              class="query-cheat-sheet__alias text-mono"
            >
              <span class="query-cheat-sheet__alias-name">{{ row.alias }}</span>
              <span
                class="query-cheat-sheet__alias-field"
                :title="row.field"
              >{{ row.field }}</span>
            </li>
          </ul>
        </section>
      </div>
    </q-card>
  </q-dialog>
</template>

<style scoped>
.query-cheat-sheet {
  display: flex;
  flex-direction: column;
  width: 1200px;
  max-width: 94vw;
  max-height: 92vh;
}

.query-cheat-sheet__header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-sm) var(--spacing-lg);
  border-bottom: 1px solid var(--border-subtle);
}

.query-cheat-sheet__title {
  margin: 0;
  color: var(--blue-primary);
  font-size: 0.9rem;
  line-height: 1.2;
  letter-spacing: 2px;
}

.query-cheat-sheet__close {
  color: var(--text-gray);
}

.query-cheat-sheet__body {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-height: 0;
  padding: var(--spacing-sm) var(--spacing-lg) var(--spacing-md);
  overflow-y: auto;
}

.query-cheat-sheet__columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.3fr);
  gap: var(--spacing-lg);
}

.query-cheat-sheet__column {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-width: 0;
}

.query-cheat-sheet__heading {
  margin: 0 0 var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.65rem;
  line-height: 1.2;
  letter-spacing: 1px;
}

.query-cheat-sheet__grammar {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  margin: 0;
  padding-left: var(--spacing-md);
  color: var(--text-gray-light);
  font-size: 0.85rem;
  line-height: 1.35;
}

.query-cheat-sheet__operators {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: var(--spacing-xs) var(--spacing-md);
  margin: 0;
  font-size: 0.8rem;
}

.query-cheat-sheet__operators dt {
  color: var(--blue-lighter);
}

.query-cheat-sheet__operators dd {
  margin: 0;
  color: var(--text-gray);
}

.query-cheat-sheet__examples {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}

.query-cheat-sheet__example {
  display: flex;
  flex-direction: column;
  width: 100%;
  padding: 2px var(--spacing-sm);
  border: 1px solid var(--border-subtle);
  background: var(--black);
  text-align: left;
  cursor: pointer;
  transition: background-color var(--transition-fast), border-color var(--transition-fast);
}

.query-cheat-sheet__example:hover,
.query-cheat-sheet__example:focus-visible {
  border-color: var(--blue-primary);
  background: var(--hover-bg);
  outline: none;
}

.query-cheat-sheet__example code {
  overflow: hidden;
  padding: 0;
  border: none;
  background: transparent;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8rem;
}

.query-cheat-sheet__note {
  overflow: hidden;
  color: var(--text-gray);
  font-size: 0.7rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.query-cheat-sheet__aliases {
  column-count: 5;
  column-gap: var(--spacing-lg);
  margin: 0;
  padding: var(--spacing-sm);
  border: 1px solid var(--border-subtle);
  background: var(--black);
  font-size: 0.7rem;
  list-style: none;
}

.query-cheat-sheet__alias {
  display: flex;
  gap: var(--spacing-sm);
  padding: 1px 0;
  break-inside: avoid;
}

.query-cheat-sheet__alias-name {
  flex: none;
  min-width: 5.5ch;
  color: var(--blue-lighter);
}

.query-cheat-sheet__alias-field {
  min-width: 0;
  overflow: hidden;
  color: var(--text-gray);
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 960px) {
  .query-cheat-sheet__columns {
    grid-template-columns: minmax(0, 1fr);
  }

  .query-cheat-sheet__aliases {
    column-count: 2;
  }
}
</style>
