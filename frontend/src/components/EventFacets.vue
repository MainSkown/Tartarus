<script setup lang="ts">
import { computed, onMounted } from 'vue'
import FacetGroup from '@/components/FacetGroup.vue'
import PaneHeading from '@/components/PaneHeading.vue'
import { t } from '@/i18n'
import { FACET_FIELDS } from '@/services/event-fields'
import { facetChipAction } from '@/services/facet-actions'
import { useEventFacetsStore } from '@/stores/event-facets'
import { useFieldCatalogStore } from '@/stores/field-catalog'
import { useQueryStateStore } from '@/stores/query-state'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ toggle: [] }>()

const facets = useEventFacetsStore()
const query = useQueryStateStore()
const catalog = useFieldCatalogStore()

// A chip may have been typed with an alias (`lane:file`); the facets know fields by their catalog name.
const canonicalChips = computed(() => query.chips.map((chip) => ({ ...chip, field: catalog.canonicalName(chip.field) })))

function pick(field: string, value: string, negate: boolean): void {
  const action = facetChipAction(canonicalChips.value, field, value, negate)
  if (action.kind === 'add') query.addChip(action.chip)
  else if (action.kind === 'toggle') query.toggleChip(action.index)
  else query.removeChip(action.index)
}

onMounted(() => void catalog.load())
</script>

<template>
  <aside
    class="event-facets"
    :class="{ 'is-collapsed': !open }"
    :aria-label="t('events.facets.label')"
  >
    <header class="event-facets__header">
      <PaneHeading
        v-if="open"
        class="event-facets__title"
        :label="t('events.facets.title')"
      />
      <button
        type="button"
        class="event-facets__toggle button"
        :aria-expanded="open"
        :aria-label="open ? t('events.facets.hide') : t('events.facets.show')"
        :title="open ? t('events.facets.hide') : t('events.facets.show')"
        @click="emit('toggle')"
      >
        <q-icon
          :name="open ? 'chevron_left' : 'chevron_right'"
          size="18px"
        />
      </button>
    </header>

    <span
      v-if="!open"
      class="event-facets__strip text-mono"
    >{{ t('events.facets.title') }}</span>

    <div
      v-else
      class="event-facets__body scrollable-panel"
    >
      <div
        v-if="facets.error"
        class="event-facets__error text-mono"
      >
        <p class="text-gray">
          {{ t('events.facets.unavailable', { error: facets.error }) }}
        </p>
        <button
          type="button"
          class="event-facets__retry button text-mono"
          @click="facets.retry()"
        >
          {{ t('common.retry') }}
        </button>
      </div>
      <template v-else>
        <FacetGroup
          v-for="field in FACET_FIELDS"
          :key="field"
          :field="field"
          :facet="facets.byField(field)"
          :loading="facets.loading"
          :chips="canonicalChips"
          @pick="(value, negate) => pick(field, value, negate)"
        />
      </template>
    </div>
  </aside>
</template>

<style scoped>
.event-facets {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.event-facets__header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
}

.event-facets.is-collapsed .event-facets__header {
  justify-content: center;
}

.event-facets__title {
  flex: 1 1 0;
  margin: 0;
  border-bottom: none;
}

.event-facets__toggle {
  flex: none;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
}

.event-facets__strip {
  padding-top: var(--spacing-sm);
  color: var(--blue-primary);
  font-size: 0.65rem;
  letter-spacing: 2px;
  text-align: center;
  writing-mode: vertical-rl;
  align-self: center;
}

.event-facets__body {
  flex: 1 1 0;
  min-height: 0;
}

.event-facets__error {
  padding: var(--spacing-sm);
  font-size: 0.75rem;
}

.event-facets__error p {
  margin: 0 0 var(--spacing-sm);
  overflow-wrap: anywhere;
}

.event-facets__retry {
  justify-content: flex-start;
  padding: 0 var(--spacing-sm);
  color: var(--blue-primary);
}
</style>
