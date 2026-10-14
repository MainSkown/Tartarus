<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Notify } from 'quasar'
import type { Validity } from '@/api'
import RuleDetailPane from '@/components/RuleDetailPane.vue'
import RulesTable from '@/components/RulesTable.vue'
import TerminalEmpty from '@/components/TerminalEmpty.vue'
import ViewState from '@/components/ViewState.vue'
import { severityMeta } from '@/services/analysis-status'
import { RULE_LEVELS, VALIDITIES, filterRules, reloadSummary, severityOfLevel, sortRules, validityMeta } from '@/services/rule-view'
import { useRulesStore } from '@/stores/rules'

const CUSTOM_RULES_DIR = 'rules/sigma/custom/'

const LEVEL_OPTIONS = RULE_LEVELS.map((level) => ({ value: level, label: severityMeta(severityOfLevel(level)!).label }))
const VALIDITY_OPTIONS = VALIDITIES.map((validity) => ({ value: validity, label: validityMeta(validity).label }))

const rules = useRulesStore()

const text = ref('')
const level = ref<string | null>(null)
const validity = ref<Validity | null>(null)
const detailPane = ref<HTMLElement>()

const filtered = computed(() => text.value.trim() !== '' || level.value !== null || validity.value !== null)
const visible = computed(() =>
  sortRules(filterRules(rules.items, { text: text.value, level: level.value, validity: validity.value })),
)
const loadingFirstList = computed(() => rules.loading && rules.items.length === 0)
const countLabel = computed(() => {
  const noun = rules.items.length === 1 ? 'rule' : 'rules'
  return filtered.value ? `showing ${visible.value.length} of ${rules.items.length} ${noun}` : `${rules.items.length} ${noun}`
})

function clearFilters(): void {
  text.value = ''
  level.value = null
  validity.value = null
}

async function toggle(id: string, enabled: boolean): Promise<void> {
  if (await rules.toggleEnabled(id, enabled)) return
  const title = rules.items.find((rule) => rule.id === id)?.title ?? id
  Notify.create({ type: 'tt-error', message: `Could not ${enabled ? 'enable' : 'disable'} ${title}` })
}

async function reload(): Promise<void> {
  if (rules.reloading) return
  if (await rules.reload()) Notify.create({ type: 'tt-success', message: reloadSummary(rules.items) })
  else Notify.create({ type: 'tt-error', message: 'Could not reload the rules' })
}

// Below the width where the pane sits beside the table it stacks under it, out of sight on a long list.
watch(
  () => rules.selectedId,
  async (id) => {
    if (id === undefined) return
    await nextTick()
    detailPane.value?.scrollIntoView?.({ block: 'nearest' })
  },
)

onMounted(() => {
  rules.clearSelection()
  void rules.load()
})
</script>

<template>
  <div class="rules-page">
    <div class="rules-header">
      <h1 class="section-title text-mono">
        SIGMA RULES
      </h1>
      <q-btn
        outline
        square
        label="[RELOAD]"
        class="reload-btn text-mono"
        :loading="rules.reloading"
        @click="reload"
      />
    </div>
    <p class="rules-note text-mono text-gray">
      Loaded from <code>rules/sigma/</code>: the shipped set in <code>default/</code> and <code>tartarus/</code>.
      Put your own rules in <code>{{ CUSTOM_RULES_DIR }}</code>; changed files reload by themselves, or press RELOAD.
    </p>

    <div class="rules-filters">
      <q-input
        v-model="text"
        outlined
        dense
        hide-bottom-space
        clearable
        placeholder="search title, path or id"
        aria-label="Search rules"
        class="search-input text-mono"
      >
        <template #prepend>
          <q-icon name="search" />
        </template>
      </q-input>
      <q-select
        v-model="level"
        :options="LEVEL_OPTIONS"
        outlined
        dense
        hide-bottom-space
        clearable
        emit-value
        map-options
        label="LEVEL"
        class="filter-select text-mono"
      />
      <q-select
        v-model="validity"
        :options="VALIDITY_OPTIONS"
        outlined
        dense
        hide-bottom-space
        clearable
        emit-value
        map-options
        label="STATUS"
        class="filter-select text-mono"
      />
      <span
        v-if="rules.items.length > 0"
        class="rules-count text-mono text-gray"
      >{{ countLabel }}</span>
    </div>

    <ViewState
      :loading="loadingFirstList"
      :error="rules.loadError"
      :empty="rules.items.length === 0"
      :empty-message="`no rules loaded: put Sigma YAML files in ${CUSTOM_RULES_DIR} and press RELOAD`"
      @retry="rules.load"
    >
      <div
        class="rules-body"
        :class="{ 'rules-body--split': rules.selected }"
      >
        <RulesTable
          v-if="visible.length > 0"
          :rules="visible"
          :selected-id="rules.selectedId"
          :toggling-ids="rules.toggling"
          @select="rules.select"
          @toggle="toggle"
        />
        <div
          v-else
          class="rules-state text-mono"
        >
          <TerminalEmpty message="no rules match" />
          <q-btn
            outline
            square
            label="[CLEAR FILTERS]"
            class="clear-filters-btn text-mono"
            @click="clearFilters"
          />
        </div>
        <aside
          v-if="rules.selected"
          ref="detailPane"
          class="rules-detail"
        >
          <RuleDetailPane
            :rule="rules.selected"
            :detail="rules.detail"
            :loading="rules.detailLoading"
            :error="rules.detailError"
            @close="rules.clearSelection"
            @retry="rules.select(rules.selected.id)"
          />
        </aside>
      </div>
    </ViewState>
  </div>
</template>

<style scoped>
.rules-page {
  padding: var(--spacing-lg);
}

.rules-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.section-title {
  color: var(--blue-primary);
  font-size: 0.9rem;
  /* Quasar's typography gives h1 a 6rem line-height, which shrinking the font doesn't undo. */
  line-height: 1.2;
  letter-spacing: 2px;
  margin: 0;
}

.reload-btn,
.clear-filters-btn {
  color: var(--blue-primary);
}

.rules-note {
  max-width: 90ch;
  margin: var(--spacing-sm) 0 var(--spacing-lg);
  font-size: 0.8rem;
  line-height: 1.5;
}

.rules-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-md);
}

.search-input {
  width: 280px;
  max-width: 100%;
}

.filter-select {
  width: 160px;
  max-width: 100%;
}

.rules-count {
  margin-left: auto;
  font-size: 0.75rem;
}

.rules-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
  padding: var(--spacing-xl) 0;
}

.rules-state :deep(.terminal-empty) {
  padding: 0;
}

.rules-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--spacing-lg);
  align-items: start;
}

.rules-body > :first-child {
  min-width: 0;
}

.rules-detail {
  min-width: 0;
  padding-top: var(--spacing-md);
  border-top: 2px solid var(--border-primary);
}

@media (min-width: 1100px) {
  .rules-body--split {
    grid-template-columns: minmax(0, 1fr) minmax(22rem, 32rem);
  }

  .rules-detail {
    position: sticky;
    top: 4rem;
    max-height: calc(100vh - 4.5rem);
    overflow-y: auto;
    padding-top: 0;
    border-top: none;
  }
}
</style>
