import type { BuildStep, BuildView, Guest, GuestState, JobRead, StepProgress } from '@/api'
import { t, type MessageKey } from '@/i18n'
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

// A Record, so a status the backend adds is a compile error here. The label is a key, translated when read.
const STEP_META: Record<StepProgress, Omit<StepMeta, 'label'> & { labelKey: MessageKey }> = {
  pending: { labelKey: 'guests.build.step.pending', icon: 'radio_button_unchecked', color: '--text-gray-dark' },
  running: { labelKey: 'guests.build.step.running', icon: 'play_arrow', color: '--blue-primary' },
  succeeded: { labelKey: 'guests.build.step.succeeded', icon: 'check_circle', color: '--status-success' },
  failed: { labelKey: 'guests.build.step.failed', icon: 'dangerous', color: '--status-critical' },
  paused: { labelKey: 'guests.build.step.paused', icon: 'pause_circle', color: '--status-medium' },
}

export const STEP_STATUSES = Object.keys(STEP_META) as StepProgress[]

export function stepMeta(status: StepProgress): StepMeta {
  const known = STEP_META[status]
  // The control service may be newer than this build of the GUI.
  if (!known) return { label: String(status).toUpperCase(), icon: 'help_outline', color: '--text-gray' }
  const { labelKey, ...rest } = known
  return { label: t(labelKey), ...rest }
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

// The control service's own text for a cancelled build; there is no structured field for it.
export const CANCELLED_BUILD_MESSAGE = 'the build was cancelled'

export function failureTitle(build: BuildView): string {
  if (build.message === CANCELLED_BUILD_MESSAGE) return t('guests.build.failure.cancelled')
  const failing = failedStep(build)
  return failing ? t('guests.build.failure.step', { step: humanStepName(failing.name) }) : t('guests.build.failure.build')
}

export type BuildPhase = 'loading' | 'not-found' | 'unreachable' | 'running' | 'paused' | 'failed' | 'selftest' | 'ready' | 'selftest-failed'

export interface PhaseMeta {
  label: string
  icon: string
  color: string
  active: boolean
}

const PHASE_META: Record<BuildPhase, Omit<PhaseMeta, 'label'> & { labelKey: MessageKey }> = {
  loading: { labelKey: 'guests.build.phase.loading', icon: 'hourglass_empty', color: '--text-gray', active: true },
  'not-found': { labelKey: 'guests.build.phase.notFound', icon: 'search_off', color: '--text-gray', active: false },
  unreachable: { labelKey: 'guests.build.phase.unreachable', icon: 'cloud_off', color: '--status-medium', active: false },
  running: { labelKey: 'guests.build.phase.running', icon: 'construction', color: '--blue-primary', active: true },
  paused: { labelKey: 'guests.build.phase.paused', icon: 'pause_circle', color: '--status-medium', active: false },
  failed: { labelKey: 'guests.build.phase.failed', icon: 'dangerous', color: '--status-critical', active: false },
  selftest: { labelKey: 'guests.build.phase.selfTest', icon: 'science', color: '--blue-primary', active: true },
  ready: { labelKey: 'guests.build.phase.ready', icon: 'check_circle', color: '--status-success', active: false },
  'selftest-failed': { labelKey: 'guests.build.phase.selfTestFailed', icon: 'dangerous', color: '--status-critical', active: false },
}

export const BUILD_PHASES = Object.keys(PHASE_META) as BuildPhase[]

export function buildPhaseMeta(phase: BuildPhase): PhaseMeta {
  const { labelKey, ...rest } = PHASE_META[phase]
  return { label: t(labelKey), ...rest }
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

export function progressShown(phase: BuildPhase, build: BuildView | undefined, job: FollowedJob | undefined): ShownProgress {
  if (!build) return { percent: 0, message: '' }
  if (phase === 'ready') return { percent: 100, message: t('guests.build.progress.guestReady') }
  if (phase === 'selftest' || phase === 'selftest-failed') {
    return job ? { percent: job.progress, message: job.step } : { percent: build.percent, message: t('guests.build.progress.selfTestStarting') }
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

// The ids are the control service's; one it does not know yet is shown as its id, formatted.
const SIGNAL_LABEL_KEYS: Record<string, MessageKey> = {
  'events.process': 'guests.build.signal.processEvents',
  'events.file': 'guests.build.signal.fileEvents',
  'events.registry': 'guests.build.signal.registryEvents',
  'report.present': 'guests.build.signal.report',
  'report.dns_answer': 'guests.build.signal.dnsLookup',
}

export function signalLabel(id: string): string {
  const key = SIGNAL_LABEL_KEYS[id]
  return key ? t(key) : id.replace(/[._-]+/g, ' ').toUpperCase()
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
  if (job?.status === 'interrupted') return t('guests.build.selfTest.interrupted')
  const error = job?.result?.error
  return typeof error === 'string' ? error : t('guests.build.selfTest.notPassed')
}

const GATEWAY_STATUSES = [502, 503, 504]

/** A conflict (an analysis is active) says why in the backend's own words; a gateway error is the control service. */
export function actionRefusal(status: number | undefined, error: unknown): string {
  if (status !== undefined && GATEWAY_STATUSES.includes(status)) {
    return t('guests.build.controlServiceUnreachable')
  }
  return errorMessage(error)
}

export function cancelConfirmation(): ConfirmOptions {
  return {
    title: t('guests.build.cancel.title'),
    message: t('guests.build.cancel.message'),
    confirmLabel: t('guests.build.cancel.confirm'),
  }
}

export function restartConfirmation({ guest, kind }: Pick<BuildView, 'guest' | 'kind'>): ConfirmOptions {
  return {
    title: t('guests.build.restart.title', { kind, guest }),
    message: t('guests.build.restart.message', { kind, guest }),
    confirmLabel: t('guests.build.restart.confirm'),
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
