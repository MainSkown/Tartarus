<script setup lang="ts">
import { computed, ref } from 'vue'
import { viewsArtifacts, type AnalysisStatus, type ArtifactsView } from '@/api'
import PaneHeading from '@/components/PaneHeading.vue'
import ScreenshotLightbox from '@/components/ScreenshotLightbox.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { analysisStatusMeta } from '@/services/analysis-status'
import { screenshotUrl } from '@/services/screenshot-url'

const props = defineProps<{ analysisId: number; status: AnalysisStatus }>()
const emit = defineEmits<{ 'open-summary': [] }>()

// Only a finished report has screenshots to read; a failed or cancelled run has none, and asking would be a needless error.
const { data, loading, error, reload } = useAnalysisView<Pick<ArtifactsView, 'screenshots'>>(
  () => props.analysisId,
  (analysis_id) =>
    props.status === 'done' ? viewsArtifacts({ path: { analysis_id } }) : Promise.resolve({ data: { screenshots: [] } }),
)

const screenshots = computed(() => data.value?.screenshots ?? [])
const last = computed(() => Math.max(0, ...screenshots.value.map((screenshot) => screenshot.n)))
const opened = ref<number | null>(null)
</script>

<template>
  <section
    class="live-finished"
    data-live="finished"
  >
    <PaneHeading label="RUN FINISHED" />
    <ViewState
      :loading="loading"
      :error="error"
      @retry="reload"
    >
      <div class="live-finished__body">
        <button
          v-if="last > 0"
          type="button"
          class="live-finished__image"
          @click="opened = last"
        >
          <img
            :src="screenshotUrl(analysisId, last)"
            :alt="`Screenshot ${last} of ${screenshots.length}`"
          >
        </button>
        <div class="live-finished__text">
          <p class="live-finished__state text-mono">
            ended: {{ analysisStatusMeta(status).label }}
          </p>
          <p
            v-if="last === 0"
            class="live-finished__none text-mono text-gray"
          >
            &gt; no screenshot was captured
          </p>
          <q-btn
            outline
            square
            label="[SUMMARY]"
            class="live-finished__summary text-mono"
            @click="emit('open-summary')"
          />
        </div>
      </div>
      <ScreenshotLightbox
        v-model="opened"
        :analysis-id="analysisId"
        :count="screenshots.length"
      />
    </ViewState>
  </section>
</template>

<style scoped>
.live-finished {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--spacing-xs) var(--spacing-sm) var(--spacing-sm);
  border: 2px solid var(--border-primary);
  background: var(--dark-bg);
}

.live-finished__body {
  display: flex;
  flex: 1 1 0;
  gap: var(--spacing-md);
  min-height: 0;
  margin-top: var(--spacing-xs);
}

.live-finished__image {
  flex: 0 1 60%;
  min-width: 0;
  min-height: 0;
  padding: 0;
  border: 2px solid var(--border-primary);
  background: var(--black);
  cursor: pointer;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.live-finished__image:hover,
.live-finished__image:focus-visible {
  border-color: var(--blue-primary);
  box-shadow: var(--shadow-blue-medium);
}

.live-finished__image img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.live-finished__text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--spacing-sm);
  min-width: 0;
}

.live-finished__state,
.live-finished__none {
  margin: 0;
  font-size: 0.8rem;
}

.live-finished__summary {
  color: var(--blue-primary);
  white-space: nowrap;
}
</style>
