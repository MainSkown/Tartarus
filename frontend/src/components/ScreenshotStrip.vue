<script setup lang="ts">
import { computed, ref } from 'vue'
import { viewsArtifacts } from '@/api'
import ScreenshotLightbox from '@/components/ScreenshotLightbox.vue'
import ViewState from '@/components/ViewState.vue'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { t } from '@/i18n'
import { screenshotUrl } from '@/services/screenshot-url'

const props = defineProps<{ analysisId: number }>()

const { data, loading, error, reload } = useAnalysisView(
  () => props.analysisId,
  (analysis_id) => viewsArtifacts({ path: { analysis_id } }),
)

const count = computed(() => data.value?.screenshots.length ?? 0)
const numbers = computed(() => (data.value?.screenshots ?? []).map((screenshot) => screenshot.n))
const opened = ref<number | null>(null)
</script>

<template>
  <ViewState
    :loading="loading"
    :error="error"
    :empty="count === 0"
    :empty-message="t('analysis.screenshots.empty')"
    @retry="reload"
  >
    <div class="screenshot-strip">
      <p class="screenshot-strip__count text-mono text-gray">
        {{ t('analysis.screenshots.count', count) }}
      </p>
      <ul class="screenshot-strip__list">
        <li
          v-for="n in numbers"
          :key="n"
        >
          <button
            type="button"
            class="screenshot-strip__thumb"
            @click="opened = n"
          >
            <img
              :src="screenshotUrl(analysisId, n)"
              :alt="t('analysis.screenshot.alt', { n, count })"
              loading="lazy"
            >
          </button>
        </li>
      </ul>
      <ScreenshotLightbox
        v-model="opened"
        :analysis-id="analysisId"
        :count="count"
      />
    </div>
  </ViewState>
</template>

<style scoped>
.screenshot-strip {
  min-width: 0;
}

.screenshot-strip__count {
  margin: 0 0 var(--spacing-sm);
  font-size: 0.8rem;
}

.screenshot-strip__list {
  display: flex;
  gap: var(--spacing-sm);
  margin: 0;
  padding: 0 0 var(--spacing-sm);
  overflow-x: auto;
  list-style: none;
}

.screenshot-strip__thumb {
  display: block;
  padding: 0;
  border: 2px solid var(--border-primary);
  background: var(--black);
  cursor: pointer;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.screenshot-strip__thumb:hover,
.screenshot-strip__thumb:focus-visible {
  border-color: var(--blue-primary);
  box-shadow: var(--shadow-blue-medium);
}

.screenshot-strip__thumb img {
  display: block;
  width: 10rem;
  aspect-ratio: 16 / 10;
  object-fit: cover;
}
</style>
