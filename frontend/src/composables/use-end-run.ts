import { computed, onScopeDispose, ref, watch, type ComputedRef } from 'vue'
import { Notify } from 'quasar'
import { analysesFinish, type AnalysisStatus } from '@/api'
import { t } from '@/i18n'
import { errorMessage } from '@/services/api-error'
import { confirmDestructive } from '@/services/confirm'
import { endRunLabel, endRunPhase, endRunTitle, type EndRunPhase } from '@/services/end-run'
import { quietOn } from '@/services/quiet-statuses'

export const COOLDOWN_MS = 5_000
// Measured on the real stack: the status leaves `running` 11 to 18 s after the guest stops.
export const GIVE_UP_MS = 45_000

const HTTP_CONFLICT = 409

export interface EndRunOptions {
  analysisId: () => number
  status: () => AnalysisStatus
  /** The live feed has shown the first process or event, so the monitor is running in the guest. */
  monitorUp: () => boolean
}

export interface EndRun {
  phase: ComputedRef<EndRunPhase>
  label: ComputedRef<string>
  title: ComputedRef<string>
  /** The user confirmed and the run has not left `running` yet: the request is on its way or accepted. */
  requested: ComputedRef<boolean>
  press: () => Promise<void>
}

/** Ends a running analysis early. Hidden unless the analysis is `running`; the backend refuses a run whose monitor has not started, so the button waits for the feed to show it. */
export function useEndRun(options: EndRunOptions): EndRun {
  const confirming = ref(false)
  const ending = ref(false)
  const cooling = ref(false)
  let coolingTimer: ReturnType<typeof setTimeout> | undefined
  let giveUpTimer: ReturnType<typeof setTimeout> | undefined

  const phase = computed(() =>
    endRunPhase({ status: options.status(), monitorUp: options.monitorUp(), confirming: confirming.value, ending: ending.value, cooling: cooling.value }),
  )

  function clearTimers(): void {
    clearTimeout(coolingTimer)
    clearTimeout(giveUpTimer)
  }

  function reset(): void {
    clearTimers()
    confirming.value = false
    ending.value = false
    cooling.value = false
  }

  function giveUp(): void {
    ending.value = false
    Notify.create({ type: 'tt-warning', message: t('live.endRun.takingLong') })
  }

  function holdOffAfter(message: string): void {
    Notify.create({ type: 'tt-warning', message })
    cooling.value = true
    coolingTimer = setTimeout(() => (cooling.value = false), COOLDOWN_MS)
  }

  async function ask(): Promise<void> {
    ending.value = true
    const { error, response } = await analysesFinish({ path: { analysis_id: options.analysisId() }, meta: quietOn(HTTP_CONFLICT) })
    const stillRunning = options.status() === 'running'
    if (!error && stillRunning) {
      giveUpTimer = setTimeout(giveUp, GIVE_UP_MS)
      return
    }
    ending.value = false
    // Any other failure was already toasted by the API interceptor; a 409 is ours to read.
    if (error && stillRunning && response?.status === HTTP_CONFLICT) holdOffAfter(errorMessage(error))
  }

  async function press(): Promise<void> {
    if (phase.value !== 'ready') return
    confirming.value = true
    const confirmed = await confirmDestructive({
      title: t('live.endRun.confirm.title'),
      message: t('live.endRun.confirm.message'),
      confirmLabel: t('live.endRun.confirm.action'),
    })
    confirming.value = false
    if (confirmed) await ask()
  }

  watch(() => options.status() !== 'running', (over) => over && reset(), { flush: 'sync' })
  onScopeDispose(clearTimers)

  return {
    phase,
    label: computed(() => endRunLabel(phase.value)),
    title: computed(() => endRunTitle(phase.value)),
    requested: computed(() => ending.value),
    press,
  }
}
