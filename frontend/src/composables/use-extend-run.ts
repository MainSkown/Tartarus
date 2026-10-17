import { computed, ref, type ComputedRef } from 'vue'
import { Notify } from 'quasar'
import { analysesExtend, type AnalysisStatus } from '@/api'
import { errorMessage } from '@/services/api-error'
import { secondsBetween } from '@/services/format-duration'
import { EXTEND_STEP_S, LONGEST_RUN_S, extendTitle } from '@/services/extend-run'
import { quietOn } from '@/services/quiet-statuses'
import { useAnalysesStore } from '@/stores/analyses'

const HTTP_CONFLICT = 409

export interface ExtendRunOptions {
  analysisId: () => number
  status: () => AnalysisStatus
  interactive: () => boolean
  deadlineAt: () => string | null
  startedAt: () => string | null
}

export interface ExtendRun {
  visible: ComputedRef<boolean>
  atLongest: ComputedRef<boolean>
  pending: ComputedRef<boolean>
  disabled: ComputedRef<boolean>
  title: ComputedRef<string>
  press: () => Promise<void>
}

/** Pushes the deadline of an interactive run that is still running by one step, up to the longest the run may last. */
export function useExtendRun(options: ExtendRunOptions): ExtendRun {
  const store = useAnalysesStore()
  const requesting = ref(false)

  const visible = computed(
    () => options.interactive() && options.status() === 'running' && options.deadlineAt() !== null,
  )
  const atLongest = computed(() => {
    const deadline = options.deadlineAt()
    const started = options.startedAt()
    return deadline !== null && started !== null && secondsBetween(started, deadline) >= LONGEST_RUN_S
  })
  const pending = computed(() => requesting.value)
  const disabled = computed(() => pending.value || atLongest.value)

  async function press(): Promise<void> {
    if (!visible.value || disabled.value) return
    requesting.value = true
    const { data, error, response } = await analysesExtend({
      path: { analysis_id: options.analysisId() },
      body: { seconds: EXTEND_STEP_S },
      meta: quietOn(HTTP_CONFLICT),
    })
    requesting.value = false
    if (data) {
      store.replaceEverywhere(data)
      return
    }
    // Any other failure was already toasted by the API interceptor; a 409 carries the reason the server refused.
    if (response?.status === HTTP_CONFLICT) Notify.create({ type: 'tt-warning', message: errorMessage(error) })
  }

  return {
    visible,
    atLongest,
    pending,
    disabled,
    title: computed(() => extendTitle(atLongest.value)),
    press,
  }
}
