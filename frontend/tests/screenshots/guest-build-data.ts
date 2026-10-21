import type { Page, Route } from '@playwright/test'
import type { BuildStep, BuildView, ErrorEnvelope, Guest, JobRead, StepProgress } from '../../src/api/types.gen'
import { LAB1, LAB4_BUILDING } from './guest-page-data'

export const NOW = new Date('2026-10-17T10:10:00Z')
export const BUILD_ID = 'build-lab4'

const minutesAgo = (minutes: number): string => new Date(NOW.getTime() - minutes * 60_000).toISOString()
const secondsAgo = (seconds: number): string => new Date(NOW.getTime() - seconds * 1_000).toISOString()

// The sentences are the ones profile.json gives these steps.
const DESCRIPTIONS: Record<string, string> = {
  preflight: 'Checks that this computer can build the guest: hardware virtualization is on, there is enough disk space and nothing else is in the way. It takes a few seconds.',
  define: "Creates the guest's empty disk and registers its virtual machine with this computer. It takes a few seconds.",
  install: 'Windows installs itself, then its first-logon script sets the guest up. The desktop may look idle for minutes; that is normal. Nothing is needed from you unless the build pauses.',
  provision: "Collects the guest's own setup log, removes the installers it left behind and lets the guest settle. Nothing is needed from you.",
  'tamper-off':
    "Switches Windows Security's Tamper Protection off, so the Defender settings made earlier take effect, and proves it with a harmless test file. If the switch cannot be found, the build pauses and asks you to switch it off on the desktop.",
  snapshot: 'Shuts the guest down cleanly, starts it again, lets it settle and takes the clean snapshot that every analysis starts from. This takes a few minutes.',
  register: 'Hands the finished guest over to the analysis system, so that it can run analyses.',
}

interface StepSpec {
  name: string
  desktop?: boolean
  weight?: number
}

const BUILD_PIPELINE: StepSpec[] = [
  { name: 'preflight' },
  { name: 'define' },
  { name: 'install', desktop: true, weight: 8 },
  { name: 'provision', desktop: true, weight: 4 },
  { name: 'tamper-off', desktop: true },
  { name: 'snapshot' },
  { name: 'register' },
]

const CLONE_PIPELINE: StepSpec[] = [
  { name: 'preflight' },
  { name: 'copy' },
  { name: 'define' },
  { name: 'reconfigure', desktop: true, weight: 3 },
  { name: 'tamper-off', desktop: true },
  { name: 'snapshot' },
  { name: 'register' },
]

/** One step per spec: the ones before `at` are done, the one at `at` is in `status`, the rest wait. */
export function stepsAt(pipeline: StepSpec[], at: number, status: StepProgress, exitCode?: number): BuildStep[] {
  return pipeline.map((spec, index) => {
    const state: StepProgress = index < at ? 'succeeded' : index === at ? status : 'pending'
    const started = index <= at ? minutesAgo((at - index + 1) * 2) : null
    const finished = state === 'succeeded' ? minutesAgo((at - index) * 2 + 0.5) : null
    return {
      name: spec.name,
      status: state,
      started,
      finished,
      exit_code: state === 'failed' ? (exitCode ?? 1) : state === 'succeeded' ? 0 : null,
      weight: spec.weight ?? 1,
      timeout_s: 1800,
      desktop: spec.desktop ?? false,
      progress: state === 'succeeded' ? 100 : 0,
      description: DESCRIPTIONS[spec.name] ?? null,
    }
  })
}

export const BUILD_STEPS = BUILD_PIPELINE
export const CLONE_STEPS = CLONE_PIPELINE

const LOG = [
  'control: build build-lab4 started (kind build)',
  'preflight: media Win11_25H2_Polish_x64.iso ok, 8 GB free for the disk',
  'define: domain lab4 defined, MAC 52:54:00:3e:91:0a',
  'install: booting the installer',
  'guest: Windows Setup is copying files',
  'guest: Windows Setup is installing features',
  'install: installer finished, waiting for the agent',
  'provision: agent answered on 192.168.150.13:8000',
  'provision: setting the static address',
  'guest: renaming the computer to DESKTOP-J6C1N5Z',
  'provision: installing Sysmon',
]

export function buildView(overrides: Partial<BuildView> = {}): BuildView {
  return {
    id: BUILD_ID,
    guest: 'lab4',
    kind: 'build',
    status: 'running',
    step: 1,
    steps: stepsAt(BUILD_PIPELINE, 1, 'running'),
    percent: 12,
    message: 'Defining the guest',
    desktop: false,
    pause: null,
    created: minutesAgo(3),
    updated: minutesAgo(0),
    last_activity: secondsAgo(4),
    log: LOG.slice(0, 3),
    ...overrides,
  }
}

export const RUNNING_EARLY = buildView()

export const RUNNING_DESKTOP = buildView({
  step: 2,
  steps: stepsAt(BUILD_PIPELINE, 2, 'running'),
  percent: 34,
  message: 'Installing: copying files',
  desktop: true,
  log: LOG.slice(0, 6),
})

// What the control service logs for the `install` step: its own lines, the step's raw protocol lines and the guest's relayed log.
const INSTALL_STEP = (percent: number, message: string, lastActivity: string, log: string[]): BuildView =>
  buildView({
    step: 2,
    steps: stepsAt(BUILD_PIPELINE, 2, 'running').map((step) => (step.name === 'install' ? { ...step, progress: percent } : step)),
    percent: 8 + Math.round(percent * 0.5),
    message,
    desktop: true,
    last_activity: lastActivity,
    log,
  })

const INSTALL_ESTIMATED_LOG = [
  'control: build build-lab4 started (kind build)',
  '== step preflight',
  'STEP Checking the host',
  'PROGRESS 100',
  '== step define',
  'STEP Defining the guest',
  'PROGRESS 100',
  '== step install',
  'STEP Installing Windows',
  'PROGRESS 10',
  'LOG Windows Setup is copying files',
  'LOG Windows is installing, about 1 min so far (estimated)',
  'PROGRESS 12',
  'LOG Windows is installing, about 2 min so far (estimated)',
  'PROGRESS 14',
  'LOG Windows is installing, about 3 min so far (estimated)',
]

const GUEST_PROVISIONING_LOG = [
  'LOG guest: 2026-10-17 10:02:11  provisioning started from D:\\ into C:\\tartarus',
  'LOG guest: 2026-10-17 10:02:11  PLAN 11',
  'LOG guest: 2026-10-17 10:02:12  STEP copy payload to the work folder',
  'LOG guest: 2026-10-17 10:02:19    ok (copied the agent, python and pillow)',
  'LOG guest: 2026-10-17 10:02:19  STEP static IP 192.168.150.13/24, gateway and DNS 192.168.150.1',
  'LOG guest: 2026-10-17 10:02:23    ok (adapter Ethernet set to 192.168.150.13)',
  'LOG guest: 2026-10-17 10:02:23  STEP disable the firewall and open port 8000',
  'LOG guest: 2026-10-17 10:02:24    ok',
  'LOG guest: 2026-10-17 10:02:24  STEP install 32-bit Python 3.11',
]

export const INSTALL_ESTIMATED = INSTALL_STEP(14, 'Windows is installing, about 3 min so far (estimated)', secondsAgo(20), INSTALL_ESTIMATED_LOG)

const PROVISIONING_MESSAGE = 'Windows is provisioning itself: install 32-bit Python 3.11'
const PROVISIONING_LOG = [...INSTALL_ESTIMATED_LOG, 'PROGRESS 17', 'STEP Windows is provisioning itself: copy payload to the work folder', ...GUEST_PROVISIONING_LOG, 'PROGRESS 36']

export const PROVISIONING_LIVE = INSTALL_STEP(36, PROVISIONING_MESSAGE, secondsAgo(6), PROVISIONING_LOG)

export const QUIET_THREE_MINUTES = INSTALL_STEP(36, PROVISIONING_MESSAGE, secondsAgo(187), PROVISIONING_LOG)

export const LONG_MESSAGE = INSTALL_STEP(
  36,
  `Windows is provisioning itself: ${'install the optional language packs and the update for the Windows Defender platform, then restart the guest '.repeat(2)}and wait`,
  secondsAgo(12),
  PROVISIONING_LOG,
)

export const PAUSED = buildView({
  status: 'paused',
  step: 4,
  steps: stepsAt(BUILD_PIPELINE, 4, 'paused'),
  percent: 71,
  message: 'Waiting for you',
  desktop: true,
  pause: {
    instructions:
      'The scripted step could not find the setting. On the desktop below, open Windows Security, go to Virus & threat protection > Manage settings and switch Tamper Protection off. Then press CONTINUE.',
  },
  log: [...LOG, 'tamper-off: the toggle was not found; paused for the analyst'],
})

export const FAILED = buildView({
  status: 'failed',
  step: 3,
  steps: stepsAt(BUILD_PIPELINE, 3, 'failed', 1),
  percent: 52,
  message: 'provision exited with code 1: the agent did not answer within 600 s',
  log: [...LOG, 'provision: waiting for the agent (attempt 58 of 60)', 'provision: the agent did not answer within 600 s', 'control: step provision failed with exit code 1'],
})

export const FAILED_INSTALL_OUTPUT = buildView({
  status: 'failed',
  step: 2,
  steps: stepsAt(BUILD_PIPELINE, 2, 'failed', 1),
  percent: 31,
  message:
    'install exited with code 1: the guest never started provisioning; look at the guest\'s screen. Last output: Windows is installing, about 55 min so far (estimated) / Setup has not written to the disk for 20 min',
  desktop: false,
  log: [...INSTALL_ESTIMATED_LOG, 'LOG Windows is installing, about 55 min so far (estimated)', 'PROGRESS 19', 'LOG Setup has not written to the disk for 20 min', 'control: step install failed with exit code 1'],
})

export const CANCELLED = buildView({
  status: 'failed',
  step: 2,
  // A cancelled step has no exit code of its own: the control service stopped it.
  steps: stepsAt(BUILD_PIPELINE, 2, 'failed').map((step) => ({ ...step, exit_code: null })),
  percent: 34,
  message: 'the build was cancelled',
  log: [...LOG.slice(0, 6), 'control: build build-lab4 cancelled during install'],
})

export const SUCCEEDED = buildView({
  status: 'succeeded',
  step: 6,
  steps: stepsAt(BUILD_PIPELINE, 7, 'succeeded'),
  percent: 100,
  message: 'Built',
  log: [...LOG, 'snapshot: snapshot clean taken', 'register: lab4 registered with CAPE'],
})

export const CLONE_RUNNING = buildView({
  kind: 'clone',
  step: 3,
  steps: stepsAt(CLONE_PIPELINE, 3, 'running'),
  percent: 46,
  message: 'Reconfiguring the copy: renaming the computer',
  desktop: true,
  log: ['control: clone build-lab4 started (kind clone)', 'copy: qemu-img convert finished in 11 s', 'define: domain lab4 defined', 'reconfigure: waiting for the agent at the new address'],
})

const LONG_STEPS: StepSpec[] = Array.from({ length: 16 }, (_, index) => ({ name: index === 9 ? 'install-all-the-optional-windows-updates-and-language-packs' : `phase-${index + 1}` }))
const LONG_LINE = `provision: ${'C:\\Users\\Marta\\AppData\\Local\\Temp\\tartarus-provision\\very-long-directory-name-'.repeat(4)}setup.log`

export const LONG = buildView({
  step: 9,
  steps: stepsAt(LONG_STEPS, 9, 'running'),
  percent: 58,
  message: `Installing ${'the optional Windows updates and language packs, '.repeat(3)}`,
  log: [
    ...Array.from({ length: 40 }, (_, index) => `${index % 3 === 0 ? 'guest: ' : 'provision: '}line ${index + 1} of the build output`),
    LONG_LINE,
    `guest: ${'x'.repeat(220)}`,
  ],
})

export const SELFTEST_JOB: JobRead = job('running', 'Self-test: analysis running', 93)

export function job(status: JobRead['status'], step: string, progress: number, result: JobRead['result'] = null): JobRead {
  return { id: 7, type: 'guest_build', analysis_id: null, status, step, progress, result, log: '', created_at: minutesAgo(20), updated_at: minutesAgo(0) }
}

const PASSED_DETAILS = {
  message: 'all checks passed',
  analysis_id: 41,
  signals: {
    'events.process': { ok: true, message: '3 processes recorded' },
    'events.file': { ok: true, message: '12 file events recorded' },
    'events.registry': { ok: true, message: '2 registry events recorded' },
    'report.present': { ok: true, message: 'the analysis has a report' },
    'report.dns_answer': { ok: true, message: 'tartarus-selftest.example was looked up, with no answer recorded' },
  },
  proofs: { defender: { ok: true, message: 'the EICAR test file was kept: Defender is off, as asked' } },
  giveaways: [],
}

export const JOB_READY = job('done', 'Self-test: judging', 100, { guest: 'lab4', state: 'ready', selftest: PASSED_DETAILS })

const FAILED_DETAILS = {
  message: 'no registry event was recorded; the guest gives itself away: account "Analyst"; folder C:\\tartarus; Defender removed the EICAR file although it should be off',
  analysis_id: 70,
  signals: {
    ...PASSED_DETAILS.signals,
    'events.registry': { ok: false, message: 'no registry event was recorded' },
  },
  proofs: { defender: { ok: false, message: 'Defender removed the EICAR file although it should be off' } },
  giveaways: ['account "Analyst"', 'folder C:\\tartarus', 'firewall rule "Tartarus agent"'],
}

export const JOB_SELFTEST_FAILED = job('failed', 'Self-test: judging', 97, { error: `The self-test of lab4 failed: ${FAILED_DETAILS.message}` })

export const GUESTS_SELFTEST_FAILED: Guest[] = [LAB1, { ...LAB4_BUILDING, state: 'failed', snapshot: null, selftest: FAILED_DETAILS, error: 'self-test failed' }]
export const GUESTS_BUILDING: Guest[] = [LAB1, LAB4_BUILDING]

const errorEnvelope = (code: string, message: string): ErrorEnvelope => ({ error: { code, message, details: {} } })

export type BuildReply = BuildView | { failure: 404 | 502; message: string }

export interface BuildApiMock {
  /** The nth read of the build answers `reads[n]`; the last reply stays. */
  reads: BuildReply[]
  guests?: Guest[]
  /** The job that follows the build once it succeeded. */
  job?: JobRead
  /** A delay before the build is answered, for the loading state. */
  readDelayMs?: number
  /** The action answers 409 with this message. */
  actionRefusal?: string
  /** The cancel answers 409 with this message. */
  cancelRefusal?: string
  /** What the build reads as once an accepted cancel has been answered. */
  afterCancel?: BuildReply
  /** The action answers only after this settles, to photograph its busy state. */
  holdAction?: Promise<void>
}

function jsonOf(reply: BuildReply): { status: number; json: unknown } {
  if ('failure' in reply) return { status: reply.failure, json: errorEnvelope(reply.failure === 404 ? 'not_found' : 'guest_control_unreachable', reply.message) }
  return { status: 200, json: reply }
}

function apiRoute(options: BuildApiMock): (route: Route) => Promise<void> {
  let reads = 0
  let cancelled = false
  return async (route) => {
    const { pathname } = new URL(route.request().url())
    const method = route.request().method()
    if (pathname === '/api/guests') {
      await route.fulfill({ json: options.guests ?? GUESTS_BUILDING })
    } else if (pathname === '/api/guests/profiles') {
      await route.fulfill({ json: [] })
    } else if (pathname === '/api/guests/builds/active') {
      if (options.job) await route.fulfill({ json: { build_id: BUILD_ID, guest: 'lab4', job_id: options.job.id } })
      else await route.fulfill({ status: 404, json: errorEnvelope('not_found', 'no build is running') })
    } else if (method === 'POST' && /\/builds\/[^/]+\/cancel$/.test(pathname)) {
      await options.holdAction
      if (options.cancelRefusal) await route.fulfill({ status: 409, json: errorEnvelope('conflict', options.cancelRefusal) })
      else {
        cancelled = true
        await route.fulfill({ status: 202, json: { build_id: BUILD_ID, guest: 'lab4' } })
      }
    } else if (method === 'POST' && /\/builds\/[^/]+\/(resume|restart|continue)$/.test(pathname)) {
      await options.holdAction
      if (options.actionRefusal) await route.fulfill({ status: 409, json: errorEnvelope('conflict', options.actionRefusal) })
      else await route.fulfill({ status: 202, json: { job_id: 8, build_id: BUILD_ID, guest: 'lab4' } })
    } else if (pathname.startsWith('/api/guests/builds/')) {
      if (options.readDelayMs) await new Promise((resolve) => setTimeout(resolve, options.readDelayMs))
      const scripted = options.reads[Math.min(reads, options.reads.length - 1)]!
      const reply = cancelled && options.afterCancel ? options.afterCancel : scripted
      reads += 1
      await route.fulfill(jsonOf(reply))
    } else if (pathname.startsWith('/api/jobs/')) {
      await route.fulfill({ json: options.job })
    } else {
      await route.fallback()
    }
  }
}

export async function mockBuildApi(page: Page, options: BuildApiMock): Promise<void> {
  await page.route((url) => url.pathname.startsWith('/api/guests') || url.pathname.startsWith('/api/jobs/'), apiRoute(options))
}
