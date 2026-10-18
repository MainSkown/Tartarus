<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { viewsProcesses, type AnalysisRead } from '@/api'
import NoteEditor from '@/components/NoteEditor.vue'
import TagChip from '@/components/TagChip.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisTabNavigation } from '@/composables/use-analysis-tab-navigation'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { useFilterEvents } from '@/composables/use-filter-events'
import { t } from '@/i18n'
import { groupAnnotations, type AnnotationEntry } from '@/services/annotation-groups'
import { quietOn } from '@/services/quiet-statuses'
import { flattenProcesses, processTitle } from '@/services/process-graph'
import { ANALYSIS_TARGET, useAnnotationsStore } from '@/stores/annotations'

const EVENT_ID_PREFIX = 8
const PROCESSES_TAB = 'processes'
const SELECTED_PID_PARAM = 'sel'

const props = defineProps<{ analysis: AnalysisRead }>()

const route = useRoute()
const annotations = useAnnotationsStore()
const { openTab } = useAnalysisTabNavigation()
const { showEvent } = useFilterEvents()

// Names make a pid readable; without them (a run that is not ingested, an index that is down) the pid stands alone.
const processes = useAnalysisView(
  () => props.analysis.id,
  (id) => viewsProcesses({ path: { analysis_id: id }, meta: quietOn(404, 409, 500, 502, 504) }),
)
const processNames = computed(
  () => new Map(flattenProcesses(processes.data.value?.roots ?? []).map((process) => [String(process.pid), process.name])),
)

const groups = computed(() => groupAnnotations(annotations.tags, annotations.notes))
const sections = computed(() => [
  { key: 'analysis', title: t('notes.tab.sections.analysis'), entries: groups.value.analysis ? [groups.value.analysis] : [] },
  { key: 'processes', title: t('notes.tab.sections.processes'), entries: groups.value.processes },
  { key: 'events', title: t('notes.tab.sections.events'), entries: groups.value.events },
])
const shownSections = computed(() => sections.value.filter((section) => section.entries.length > 0))
const nothingYet = computed(() => shownSections.value.length === 0)
const loadingFirst = computed(() => annotations.loading && annotations.tags.length + annotations.notes.length === 0)

function targetLabel(entry: AnnotationEntry): { text: string; title?: string } {
  const { type, ref } = entry.target
  if (type === 'process') return { text: processTitle({ pid: Number(ref), name: processNames.value.get(ref) ?? null }) }
  return { text: t('notes.tab.eventTarget', { id: ref.slice(0, EVENT_ID_PREFIX) }), title: ref }
}

function follow(entry: AnnotationEntry): void {
  const { type, ref } = entry.target
  if (type === 'process') void openTab(PROCESSES_TAB, { ...route.query, [SELECTED_PID_PARAM]: ref })
  else void showEvent(ref)
}

// The editor above shows the analysis's note; listing it again would repeat it on the same screen.
const notesOf = (entry: AnnotationEntry) => (entry.target.type === 'analysis' ? [] : entry.notes)
</script>

<template>
  <section
    data-tab="notes"
    class="notes-tab"
  >
    <section class="notes-tab__section">
      <h2 class="notes-tab__heading text-mono">
        {{ t('notes.tab.analysisNote') }}
      </h2>
      <NoteEditor
        :target="ANALYSIS_TARGET"
        :label="t('notes.tab.analysisNoteLabel')"
      />
    </section>

    <section class="notes-tab__section">
      <h2 class="notes-tab__heading text-mono">
        {{ t('notes.tab.byTarget') }}
      </h2>
      <ViewState
        :loading="loadingFirst"
        :error="annotations.loadError"
        :empty="nothingYet"
        :empty-message="t('notes.tab.emptyMessage')"
        @retry="annotations.reload"
      >
        <section
          v-for="section in shownSections"
          :key="section.key"
          class="notes-group"
        >
          <h3 class="notes-group__title text-mono">
            {{ section.title }}
            <span
              v-if="section.key !== 'analysis'"
              class="notes-group__count"
            >{{ section.entries.length }}</span>
          </h3>
          <ul class="notes-group__entries">
            <li
              v-for="entry in section.entries"
              :key="`${entry.target.type}:${entry.target.ref}`"
              class="notes-entry"
              :class="{ 'is-orphaned': entry.orphaned }"
            >
              <header
                v-if="entry.target.type !== 'analysis'"
                class="notes-entry__head text-mono"
              >
                <span
                  v-if="entry.orphaned"
                  class="notes-entry__target"
                  :title="targetLabel(entry).title"
                >{{ targetLabel(entry).text }}</span>
                <button
                  v-else
                  type="button"
                  class="notes-entry__link text-mono"
                  :title="targetLabel(entry).title"
                  @click="follow(entry)"
                >
                  {{ targetLabel(entry).text }}
                </button>
                <span
                  v-if="entry.orphaned"
                  class="notes-entry__orphan"
                  :title="t('notes.tab.orphanedHint')"
                >{{ t('notes.tab.orphaned') }}</span>
              </header>
              <ul
                v-if="entry.tags.length > 0"
                class="notes-entry__tags"
                :aria-label="t('tags.list.label')"
              >
                <li
                  v-for="tag in entry.tags"
                  :key="tag.link_id"
                >
                  <TagChip :name="tag.tag" />
                </li>
              </ul>
              <p
                v-for="note in notesOf(entry)"
                :key="note.id"
                class="notes-entry__note"
              >
                {{ note.body }}
              </p>
            </li>
          </ul>
        </section>
      </ViewState>
    </section>
  </section>
</template>

<style scoped>
.notes-tab {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-lg);
  min-width: 0;
  padding: var(--spacing-lg);
}

.notes-tab__heading {
  margin: 0 0 var(--spacing-sm);
  /* Quasar's typography gives headings a tall line-height that shrinking the font does not undo. */
  line-height: 1.2;
  color: var(--blue-primary);
  font-size: 0.75rem;
  letter-spacing: 2px;
}

.notes-group {
  margin-bottom: var(--spacing-md);
}

.notes-group__title {
  margin: 0 0 var(--spacing-xs);
  line-height: 1.2;
  color: var(--text-gray);
  font-size: 0.65rem;
  letter-spacing: 1px;
}

.notes-group__count {
  margin-left: var(--spacing-xs);
  color: var(--blue-light);
}

.notes-group__entries {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}

.notes-entry {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  min-width: 0;
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--border-primary);
  background: var(--dark-bg);
}

.notes-entry.is-orphaned {
  border-style: dashed;
  border-color: rgba(234, 179, 8, 0.5);
}

.notes-entry__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--spacing-sm);
  min-width: 0;
  font-size: 0.8rem;
}

.notes-entry__target {
  min-width: 0;
  color: var(--text-gray);
  overflow-wrap: anywhere;
}

.notes-entry__link {
  min-width: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--blue-primary);
  font-size: inherit;
  text-align: left;
  overflow-wrap: anywhere;
  cursor: pointer;
}

.notes-entry__link:hover,
.notes-entry__link:focus-visible {
  color: var(--blue-hover);
  text-decoration: underline;
}

.notes-entry__orphan {
  flex: none;
  padding: 0 var(--spacing-xs);
  border: 1px solid var(--status-medium);
  color: var(--status-medium);
  font-size: 0.65rem;
  letter-spacing: 1px;
}

.notes-entry__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}

.notes-entry__tags > li {
  display: flex;
  min-width: 0;
  max-width: 100%;
}

.notes-entry__note {
  max-height: 12rem;
  margin: 0;
  overflow: auto;
  font-size: 0.85rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
</style>
