<script setup lang="ts">
import { computed, ref } from 'vue'
import { viewsAttack, viewsDetections } from '@/api'
import type { AnalysisRead, AttackTechniqueHit } from '@/api'
import AttackMatrix from '@/components/AttackMatrix.vue'
import DetectionDetail from '@/components/DetectionDetail.vue'
import DetectionList from '@/components/DetectionList.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { t, type MessageKey } from '@/i18n'
import { detectionById, displayedGroups } from '@/services/detection-groups'

const props = defineProps<{ analysis: AnalysisRead }>()

type Mode = 'detections' | 'attack'
const MODES: { value: Mode; label: MessageKey }[] = [
  { value: 'detections', label: 'detections.modes.detections' },
  { value: 'attack', label: 'detections.modes.attack' },
]

const detections = useAnalysisView(
  () => props.analysis.id,
  (analysis_id) => viewsDetections({ path: { analysis_id } }),
)
const attack = useAnalysisView(
  () => props.analysis.id,
  (analysis_id) => viewsAttack({ path: { analysis_id } }),
)

const mode = ref<Mode>('detections')
const technique = ref<AttackTechniqueHit>()
const pickedId = ref<string>()

const allGroups = computed(() => detections.data.value?.groups ?? [])
const groups = computed(() => displayedGroups(allGroups.value, technique.value?.detection_ids))
const selected = computed(
  () => (pickedId.value && detectionById(groups.value, pickedId.value)) || groups.value[0]?.detections[0],
)

function showTechnique(hit: AttackTechniqueHit): void {
  const listed = hit.detection_ids.some((id) => detectionById(allGroups.value, id))
  technique.value = listed ? hit : undefined
  pickedId.value = undefined
  mode.value = 'detections'
}

function techniqueFilterLabel(hit: AttackTechniqueHit): string {
  return hit.name
    ? t('detections.technique.filterNamed', { id: hit.id, name: hit.name })
    : t('detections.technique.filter', { id: hit.id })
}

function clearTechnique(): void {
  technique.value = undefined
  pickedId.value = undefined
}
</script>

<template>
  <section
    data-tab="detections"
    class="detections-tab"
  >
    <div
      class="radio-group detections-tab__mode"
      role="radiogroup"
      :aria-label="t('detections.viewLabel')"
    >
      <template
        v-for="option in MODES"
        :key="option.value"
      >
        <input
          :id="`detections-mode-${option.value}`"
          v-model="mode"
          type="radio"
          class="radio-input"
          name="detections-mode"
          :value="option.value"
        >
        <label
          :for="`detections-mode-${option.value}`"
          class="radio-label text-mono"
        >{{ t(option.label) }}</label>
      </template>
    </div>

    <ViewState
      v-if="mode === 'attack'"
      :loading="attack.loading.value"
      :error="attack.error.value"
      :empty="attack.data.value?.tactics.length === 0"
      :empty-message="t('detections.empty.attack')"
      @retry="attack.reload"
    >
      <AttackMatrix
        v-if="attack.data.value"
        :matrix="attack.data.value"
        @select="showTechnique"
      />
    </ViewState>

    <ViewState
      v-else
      :loading="detections.loading.value"
      :error="detections.error.value"
      :empty="allGroups.length === 0"
      :empty-message="t('detections.empty.detections')"
      @retry="detections.reload"
    >
      <p
        v-if="technique"
        class="technique-filter text-mono"
      >
        <span>{{ techniqueFilterLabel(technique) }}</span>
        <button
          type="button"
          class="technique-filter__clear text-mono"
          @click="clearTechnique"
        >
          {{ t('detections.technique.clear') }}
        </button>
      </p>
      <div class="detections-tab__panes">
        <DetectionList
          :groups="groups"
          :selected-id="selected?.id"
          @select="pickedId = $event"
        />
        <DetectionDetail
          v-if="selected"
          :detection="selected"
        />
      </div>
    </ViewState>
  </section>
</template>

<style scoped>
.detections-tab {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  min-width: 0;
  padding: var(--spacing-lg);
}

.detections-tab__mode .radio-label {
  font-size: 0.8rem;
  letter-spacing: 1px;
}

.technique-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--spacing-md);
  margin: 0;
  color: var(--blue-light);
  font-size: 0.85rem;
  overflow-wrap: anywhere;
}

.technique-filter__clear {
  padding: 0;
  border: none;
  background: transparent;
  color: var(--blue-primary);
  cursor: pointer;
}

.technique-filter__clear:hover {
  color: var(--blue-hover);
}

.detections-tab__panes {
  display: grid;
  grid-template-columns: minmax(16rem, 24rem) minmax(0, 1fr);
  gap: var(--spacing-lg);
  align-items: start;
}

@media (max-width: 900px) {
  .detections-tab__panes {
    grid-template-columns: minmax(0, 1fr);
  }

  .detections-tab__panes > .detection-detail {
    padding-top: var(--spacing-md);
    border-top: 2px solid var(--border-primary);
  }
}
</style>
