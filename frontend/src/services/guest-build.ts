import type { BuildStep, BuildView, Guest, GuestState, JobRead, StepProgress } from '@/api'
import { errorMessage } from '@/services/api-error'
import type { ConfirmOptions } from '@/services/confirm'
import { formatDuration } from '@/services/format-duration'

export type FollowedJob = Pick<JobRead, 'status' | 'step' | 'progress' | 'result'>

export type LoadFailure = 'not-found' | 'unreachable'

/** The profile's own step names are shown as data, never matched on: `tamper-off` reads `TAMPER OFF`. */
export function humanStepName(name: string): string {
  return name.replace(/[-_]+/g, ' ').toUpperCase()
}

export function buildKindLabel(kind: string): string {
  return kind.toUpperCase()
}

interface StepMeta {
  label: string
  icon: string
  color: string
}

// A Record, so a status the backend adds is a compile error here.
const STEP_META: Record<StepProgress, StepMeta> = {
  pending: { label: 'PENDING', icon: 'radio_button_unchecked', color: '--text-gray-dark' },
  running: { label: 'RUNNING', icon: 'play_arrow', color: '--blue-primary' },
  succeeded: { label: 'DONE', icon: 'check_circle', color: '--status-success' },
  failed: { label: 'FAILED', icon: 'dangerous', color: '--status-critical' },
  paused: { label: 'PAUSED', icon: 'pause_circle', color: '--status-medium' },
}

export const STEP_STATUSES = Object.keys(STEP_META) as StepProgress[]

export function stepMeta(status: StepProgress): StepMeta {
  // The control service may be newer than this build of the GUI.
  return STEP_META[status] ?? { label: String(status).toUpperCase(), icon: 'help_outline', color: '--text-gray' }
}

/** How long a step took, or has taken so far when it is still running or waiting for the analyst. */
export function stepDurationLabel(step: BuildStep, now: number): string | undefined {
  if (!step.started) return undefined
  const end = step.finished ? Date.parse(step.finished) : now
  return formatDuration(Math.max(0, (end - Date.parse(step.started)) / 1000))
}

export function failedStep(build: BuildView): BuildStep | undefined {
  return build.steps.find((step) => step.status === 'failed')
}

export type BuildPhase = 'loading' | 'not-found' | 'unreachable' | 'running' | 'paused' | 'failed' | 'selftest' | 'ready' | 'selftest-failed'

export interface PhaseMeta {
  label: string
  icon: string
  color: string
  active: boolean
}

const PHASE_META: Record<BuildPhase, PhaseMeta> = {
  loading: { label: 'LOADING', icon: 'hourglass_empty', color: '--text-gray', active: true },
  'not-found': { label: 'NOT FOUND', icon: 'search_off', color: '--text-gray', active: false },
  unreachable: { label: 'UNREACHABLE', icon: 'cloud_off', color: '--status-medium', active: false },
  running: { label: 'RUNNING', icon: 'construction', color: '--blue-primary', active: true },
  paused: { label: 'PAUSED', icon: 'pause_circle', color: '--status-medium', active: false },
  failed: { label: 'FAILED', icon: 'dangerous', color: '--status-critical', active: false },
  selftest: { label: 'SELF-TEST', icon: 'science', color: '--blue-primary', active: true },
  ready: { label: 'READY', icon: 'check_circle', color: '--status-success', active: false },
  'selftest-failed': { label: 'SELF-TEST FAILED', icon: 'dangerous', color: '--status-critical', active: false },
}

export const BUILD_PHASES = Object.keys(PHASE_META) as BuildPhase[]

export function buildPhaseMeta(phase: BuildPhase): PhaseMeta {
  return PHASE_META[phase]
}

export interface PhaseInput {
  build?: BuildView
  loadFailure?: LoadFailure
  job?: FollowedJob
  guestState?: GuestState
}

const JOB_FAILED = ['failed', 'interrupted']

/**
 * What the page shows. The build says how far the steps got; once it succeeded the backend goes
 * on with the self-test, so the job (or, with no job known, the guest) says how that ended.
 */
export function phaseOf({ build, loadFailure, job, guestState }: PhaseInput): BuildPhase {
  if (!build) return loadFailure ?? 'loading'
  if (build.status !== 'succeeded') return build.status
  if (job) return phaseAfterBuildOf(job)
  if (guestState === 'ready' || guestState === 'broken') return 'ready'
  return guestState === 'failed' ? 'selftest-failed' : 'selftest'
}

function phaseAfterBuildOf(job: FollowedJob): BuildPhase {
  if (JOB_FAILED.includes(job.status)) return 'selftest-failed'
  return job.status === 'done' ? 'ready' : 'selftest'
}

export interface ShownProgress {
  percent: number
  message: string
}

const SELFTEST_STARTING = 'Self-test starting'
const READY_MESSAGE = 'Guest ready'

export function progressShown(phase: BuildPhase, build: BuildView | undefined, job: FollowedJob | undefined): ShownProgress {
  if (!build) return { percent: 0, message: '' }
  if (phase === 'ready') return { percent: 100, message: READY_MESSAGE }
  if (phase === 'selftest' || phase === 'selftest-failed') {
    return job ? { percent: job.progress, message: job.step } : { percent: build.percent, message: SELFTEST_STARTING }
  }
  return { percent: build.percent, message: build.message ?? '' }
}

export interface Check {
  id: string
  label: string
  ok: boolean
  message: string
}

export interface SelfTestVerdict {
  message: string
  /** The analysis of the benign sample, when the test got as far as submitting it. */
  analysisId: number | undefined
  signals: Check[]
  proofs: Check[]
  giveaways: string[]
}

const SIGNAL_LABELS: Record<string, string> = {
  'events.process': 'PROCESS EVENTS',
  'events.file': 'FILE EVENTS',
  'events.registry': 'REGISTRY EVENTS',
  'report.present': 'REPORT',
  'report.dns_answer': 'DNS LOOKUP',
}

export function signalLabel(id: string): string {
  return SIGNAL_LABELS[id] ?? id.replace(/[._-]+/g, ' ').toUpperCase()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function checksOf(raw: unknown, labelOf: (id: string) => string): Check[] {
  if (!isRecord(raw)) return []
  return Object.entries(raw).flatMap(([id, entry]) => {
    if (!isRecord(entry) || typeof entry.ok !== 'boolean') return []
    return [{ id, label: labelOf(id), ok: entry.ok, message: typeof entry.message === 'string' ? entry.message : '' }]
  })
}

function verdictOf(raw: unknown): SelfTestVerdict | undefined {
  if (!isRecord(raw) || typeof raw.message !== 'string') return undefined
  return {
    message: raw.message,
    analysisId: typeof raw.analysis_id === 'number' ? raw.analysis_id : undefined,
    signals: checksOf(raw.signals, signalLabel),
    proofs: checksOf(raw.proofs, (id) => id.replace(/[._-]+/g, ' ').toUpperCase()),
    giveaways: Array.isArray(raw.giveaways) ? raw.giveaways.filter((giveaway): giveaway is string => typeof giveaway === 'string') : [],
  }
}

/** A failed job keeps no details in its result, but the guest's own record does. */
export function selfTestVerdictOf(job: FollowedJob | undefined, guest: Pick<Guest, 'selftest'> | undefined): SelfTestVerdict | undefined {
  return verdictOf(job?.result?.selftest) ?? verdictOf(guest?.selftest)
}

export function selfTestFailureMessage(job: FollowedJob | undefined, verdict: SelfTestVerdict | undefined): string {
  if (verdict) return verdict.message
  if (job?.status === 'interrupted') return 'The self-test was interrupted before it finished.'
  const error = job?.result?.error
  return typeof error === 'string' ? error : 'The self-test did not pass.'
}

const GATEWAY_STATUSES = [502, 503, 504]

/** A conflict (an analysis is active) says why in the backend's own words; a gateway error is the control service. */
export function actionRefusal(status: number | undefined, error: unknown): string {
  if (status !== undefined && GATEWAY_STATUSES.includes(status)) {
    return 'The guest control service is not reachable; try again in a moment.'
  }
  return errorMessage(error)
}

export function restartConfirmation(build: Pick<BuildView, 'guest' | 'kind'>): ConfirmOptions {
  return {
    title: `Restart the ${build.kind} of ${build.guest}`,
    message: `Restart the ${build.kind} of ${build.guest} from the first step? What the ${build.kind} has done so far is discarded and cannot be recovered.`,
    confirmLabel: 'RESTART',
  }
}

const SELFTEST_STEP_STATUS: Partial<Record<BuildPhase, StepProgress>> = {
  selftest: 'running',
  ready: 'succeeded',
  'selftest-failed': 'failed',
}

/** The backend runs the self-test after the control service's last step; the list shows it as the last step. */
export function stepsWithSelfTest(steps: readonly BuildStep[], phase: BuildPhase): BuildStep[] {
  if (steps.length === 0) return []
  const selfTest: BuildStep = {
    name: 'self-test',
    status: SELFTEST_STEP_STATUS[phase] ?? 'pending',
    weight: 0,
    timeout_s: 0,
    desktop: false,
    progress: 0,
  }
  return [...steps, selfTest]
}
