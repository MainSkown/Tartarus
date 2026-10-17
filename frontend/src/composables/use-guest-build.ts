import { computed, onScopeDispose, ref, watch, type ComputedRef, type Ref } from 'vue'
import { guestsActiveBuild, guestsContinueBuild, guestsReadBuild, guestsResumeBuild, guestsRestartBuild, jobsRead } from '@/api'
import type { BuildStarted, BuildView, Guest, JobProgress } from '@/api'
import { confirmDestructive } from '@/services/confirm'
import {
  actionRefusal,
  phaseOf,
  progressShown,
  restartConfirmation,
  selfTestFailureMessage,
  selfTestVerdictOf,
  type BuildPhase,
  type FollowedJob,
  type LoadFailure,
  type SelfTestVerdict,
  type ShownProgress,
} from '@/services/guest-build'
import { isFinishedJob } from '@/services/job-status'
import { NOT_FOUND_STATUS, quietOn } from '@/services/quiet-statuses'
import { useGuestsStore } from '@/stores/guests'
import { useSystemStore } from '@/stores/system'

export const POLL_INTERVAL_MS = 2_000
export const LOG_TAIL = 200

const GUEST_BUILD_JOB = 'guest_build'
const READ_QUIET = quietOn(404, 500, 502, 503, 504)
// The page shows these under the button that was pressed, so a toast on top would only repeat them.
const ACTION_QUIET = quietOn(409, 500, 502, 503, 504)
const POLLED_PHASES: readonly BuildPhase[] = ['loading', 'unreachable', 'running', 'paused', 'selftest']

export type BuildAction = 'resume' | 'restart' | 'continue'

export interface GuestBuild {
  build: Ref<BuildView | undefined>
  guest: ComputedRef<Guest | undefined>
  phase: ComputedRef<BuildPhase>
  progress: ComputedRef<ShownProgress>
  /** What the self-test found: from the job once it ended, else from the guest's own record. */
  verdict: ComputedRef<SelfTestVerdict | undefined>
  failureMessage: ComputedRef<string>
  /** The last read failed while an earlier answer is still on screen. */
  connectionLost: Ref<boolean>
  hasDesktop: ComputedRef<boolean>
  busy: Ref<BuildAction | undefined>
  actionError: Ref<string | undefined>
  resume: () => Promise<void>
  restart: () => Promise<void>
  continueBuild: () => Promise<void>
}

type Started = { data?: BuildStarted; error?: unknown; response?: Response }

/**
 * What the build page shows and does: the build read every two seconds while it runs, the job
 * that follows it once its last step succeeded (the self-test), and the three ways to move a
 * stuck build on.
 */
export function useGuestBuild(buildId: () => string): GuestBuild {
  const guests = useGuestsStore()
  const system = useSystemStore()

  const build = ref<BuildView>()
  const job = ref<FollowedJob>()
  const loadFailure = ref<LoadFailure>()
  const connectionLost = ref(false)
  const busy = ref<BuildAction>()
  const actionError = ref<string>()
  let jobId: number | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let ticking = false
  let tickAgain = false
  let disposed = false

  const guest = computed(() => (build.value ? guests.byName(build.value.guest) : undefined))
  const phase = computed(() => phaseOf({ build: build.value, loadFailure: loadFailure.value, job: job.value, guestState: guest.value?.state }))
  const progress = computed(() => progressShown(phase.value, build.value, job.value))
  const verdict = computed(() => selfTestVerdictOf(job.value, guest.value))
  const failureMessage = computed(() => selfTestFailureMessage(job.value, verdict.value))
  const hasDesktop = computed(() => build.value?.desktop === true && (phase.value === 'running' || phase.value === 'paused'))

  async function readBuild(): Promise<void> {
    const id = buildId()
    const { data, error, response } = await guestsReadBuild({ path: { build_id: id }, query: { tail: LOG_TAIL }, meta: READ_QUIET })
    if (id !== buildId()) return
    if (data && !error) {
      build.value = data
      loadFailure.value = undefined
      connectionLost.value = false
      return
    }
    if (response?.status === NOT_FOUND_STATUS) loadFailure.value = 'not-found'
    else if (build.value) connectionLost.value = true
    else loadFailure.value = 'unreachable'
  }

  async function findJob(): Promise<number | undefined> {
    const { data } = await guestsActiveBuild({ meta: READ_QUIET })
    return data?.build_id === buildId() ? data.job_id : undefined
  }

  function adopt(incoming: Pick<JobProgress, 'status' | 'step' | 'progress' | 'result'>): void {
    const { status, step, progress: percent, result } = incoming
    job.value = { status, step, progress: percent, result }
  }

  async function readJob(id: number): Promise<void> {
    const { data, error } = await jobsRead({ path: { job_id: id }, meta: READ_QUIET })
    if (data && !error) {
      adopt(data)
      connectionLost.value = false
    } else {
      connectionLost.value = true
    }
  }

  async function followSelfTest(): Promise<void> {
    jobId ??= await findJob()
    if (jobId !== undefined) await readJob(jobId)
    // The job's result has the verdict only for a pass; the guest's record has it either way.
    if (jobId === undefined || (job.value && isFinishedJob(job.value.status))) await guests.load()
  }

  async function tick(): Promise<void> {
    if (!build.value || build.value.status !== 'succeeded') await readBuild()
    if (build.value?.status === 'succeeded') await followSelfTest()
  }

  async function run(): Promise<void> {
    if (ticking) {
      tickAgain = true
      return
    }
    ticking = true
    try {
      do {
        tickAgain = false
        await tick()
      } while (tickAgain)
    } finally {
      ticking = false
    }
    if (!disposed && POLLED_PHASES.includes(phase.value)) timer = setTimeout(() => void run(), POLL_INTERVAL_MS)
  }

  function kick(): void {
    clearTimeout(timer)
    void run()
  }

  function reset(): void {
    build.value = undefined
    job.value = undefined
    loadFailure.value = undefined
    connectionLost.value = false
    actionError.value = undefined
    jobId = undefined
    kick()
  }

  async function act(action: BuildAction, call: () => Promise<Started>): Promise<void> {
    if (busy.value) return
    busy.value = action
    actionError.value = undefined
    const { data, error, response } = await call()
    busy.value = undefined
    if (!data || error) {
      actionError.value = actionRefusal(response?.status, error)
      return
    }
    jobId = data.job_id
    job.value = undefined
    kick()
  }

  const path = () => ({ path: { build_id: buildId() }, meta: ACTION_QUIET })

  async function restart(): Promise<void> {
    if (!build.value || busy.value) return
    if (await confirmDestructive(restartConfirmation(build.value))) await act('restart', () => guestsRestartBuild(path()))
  }

  watch(buildId, reset, { immediate: true })
  const stopListening = system.onJob((incoming) => {
    if (incoming.type !== GUEST_BUILD_JOB || incoming.id !== jobId) return
    adopt(incoming)
    if (isFinishedJob(incoming.status)) kick()
  })
  onScopeDispose(() => {
    disposed = true
    clearTimeout(timer)
    stopListening()
  })

  return {
    build,
    guest,
    phase,
    progress,
    verdict,
    failureMessage,
    connectionLost,
    hasDesktop,
    busy,
    actionError,
    resume: () => act('resume', () => guestsResumeBuild(path())),
    restart,
    continueBuild: () => act('continue', () => guestsContinueBuild(path())),
  }
}
