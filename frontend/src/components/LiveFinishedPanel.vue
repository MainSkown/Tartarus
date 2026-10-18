<script setup lang="ts">
import { ref } from 'vue'
import type { AnalysisStatus } from '@/api'
import { t } from '@/i18n'
import PaneHeading from '@/components/PaneHeading.vue'
import ScreenshotLightbox from '@/components/ScreenshotLightbox.vue'
import ViewState from '@/components/ViewState.vue'
import { useLastScreenshot } from '@/composables/use-last-screenshot'
import { analysisStatusMeta } from '@/services/analysis-status'
import { screenshotUrl } from '@/services/screenshot-url'

const props = defineProps<{ analysisId: number; status: AnalysisStatus }>()
const emit = defineEmits<{ 'open-summary': [] }>()

const { last, count, loading, error, reload } = useLastScreenshot(
  () => props.analysisId,
  () => props.status,
)
const opened = ref<number | null>(null)
</script>

<template>
  <section
    class="live-finished"
    data-live="finished"
  >
    <PaneHeading :label="t('live.finished.heading')" />
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
            :alt="t('live.finished.screenshotAlt', { last, count })"
          >
        </button>
        <div class="live-finished__text">
          <p class="live-finished__state text-mono">
            {{ t('live.finished.ended', { status: analysisStatusMeta(status).label }) }}
          </p>
          <p
            v-if="last === 0"
            class="live-finished__none text-mono text-gray"
          >
            &gt; {{ t('live.finished.noScreenshot') }}
          </p>
          <q-btn
            outline
            square
            :label="t('live.finished.summary')"
            class="live-finished__summary text-mono"
            @click="emit('open-summary')"
          />
        </div>
      </div>
      <ScreenshotLightbox
        v-model="opened"
        :analysis-id="analysisId"
        :count="count"
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
