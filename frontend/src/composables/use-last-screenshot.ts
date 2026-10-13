import { computed, watch, type ComputedRef, type Ref } from 'vue'
import { viewsArtifacts, type AnalysisStatus, type ArtifactsView } from '@/api'
import { useAnalysisView } from '@/composables/use-analysis-view'

type Screenshots = Pick<ArtifactsView, 'screenshots'>

export interface LastScreenshot {
  /** The number of the last screenshot, 0 when there is none. */
  last: ComputedRef<number>
  count: ComputedRef<number>
  loading: Ref<boolean>
  error: Ref<string | undefined>
  reload: () => Promise<void>
}

/** The screenshots of a finished run; only a done report has any, so other statuses do not ask. */
export function useLastScreenshot(analysisId: () => number, status: () => AnalysisStatus): LastScreenshot {
  const { data, loading, error, reload } = useAnalysisView<Screenshots>(analysisId, (analysis_id) =>
    status() === 'done' ? viewsArtifacts({ path: { analysis_id } }) : Promise.resolve({ data: { screenshots: [] } }),
  )
  watch(status, () => void reload())
  const screenshots = computed(() => data.value?.screenshots ?? [])
  const last = computed(() => Math.max(0, ...screenshots.value.map((screenshot) => screenshot.n)))
  const count = computed(() => screenshots.value.length)
  return { last, count, loading, error, reload }
}
