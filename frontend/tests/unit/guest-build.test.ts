import { describe, expect, it } from 'vitest'
import type { BuildStep, StepProgress } from '@/api'
import {
  BUILD_PHASES,
  actionRefusal,
  STEP_STATUSES,
  buildKindLabel,
  buildPhaseMeta,
  cancelConfirmation,
  failedStep,
  failureTitle,
  humanStepName,
  phaseOf,
  progressShown,
  restartConfirmation,
  selfTestFailureMessage,
  selfTestVerdictOf,
  signalLabel,
  stepDurationLabel,
  stepsWithSelfTest,
  stepMeta,
} from '@/services/guest-build'
import { buildFixture, guestFixture } from './guest-fixtures'

const CANCELLED = 'the build was cancelled'

function step(overrides: Partial<BuildStep> = {}): BuildStep {
  return { name: 'install', status: 'pending', weight: 1, timeout_s: 60, desktop: false, progress: 0, ...overrides }
}

describe('humanStepName', () => {
  it.each([
    ['tamper-off', 'TAMPER OFF'],
    ['install', 'INSTALL'],
    ['copy', 'COPY'],
    ['install-windows-updates', 'INSTALL WINDOWS UPDATES'],
  ])('shows %s as %s', (name, label) => {
    expect(humanStepName(name)).toBe(label)
  })

  it('also reads underscores as spaces', () => {
    expect(humanStepName('wait_for_agent')).toBe('WAIT FOR AGENT')
  })
})

describe('buildKindLabel', () => {
  it('is the kind in capitals, and the kind as given for one that is newer than this GUI', () => {
    expect(buildKindLabel('build')).toBe('BUILD')
    expect(buildKindLabel('clone')).toBe('CLONE')
    expect(buildKindLabel('rebuild')).toBe('REBUILD')
  })
})

describe('stepMeta', () => {
  it('has a label, an icon and a colour for every step status', () => {
    for (const status of STEP_STATUSES) {
      const meta = stepMeta(status)
      expect(meta.label).not.toBe('')
      expect(meta.icon).not.toBe('')
      expect(meta.color).toMatch(/^--/)
    }
  })

  it('calls the five statuses by name', () => {
    const labels = Object.fromEntries(STEP_STATUSES.map((status: StepProgress) => [status, stepMeta(status).label]))
    expect(labels).toEqual({ pending: 'PENDING', running: 'RUNNING', succeeded: 'DONE', failed: 'FAILED', paused: 'PAUSED' })
  })

  it('does not break on a status that is newer than this GUI', () => {
    expect(stepMeta('skipped' as StepProgress).label).toBe('SKIPPED')
  })
})

describe('stepDurationLabel', () => {
  const NOW = Date.parse('2026-10-17T10:10:00Z')

  it('is empty for a step that has not started', () => {
    expect(stepDurationLabel(step(), NOW)).toBeUndefined()
  })

  it('is the time between start and finish for a finished step', () => {
    expect(stepDurationLabel(step({ status: 'succeeded', started: '2026-10-17T10:00:00Z', finished: '2026-10-17T10:04:30Z' }), NOW)).toBe('4m 30s')
  })

  it('counts up to now for a step that is running', () => {
    expect(stepDurationLabel(step({ status: 'running', started: '2026-10-17T10:09:15Z' }), NOW)).toBe('45s')
  })

  it('counts up to now for a paused step, which is still waiting for the analyst', () => {
    expect(stepDurationLabel(step({ status: 'paused', started: '2026-10-17T10:08:00Z' }), NOW)).toBe('2m 0s')
  })

  it('never goes negative when the clocks disagree', () => {
    expect(stepDurationLabel(step({ status: 'running', started: '2026-10-17T10:10:05Z' }), NOW)).toBe('0s')
  })
})

describe('failedStep', () => {
  it('is the step that failed', () => {
    const build = buildFixture({ status: 'failed', steps: [step({ name: 'a', status: 'succeeded' }), step({ name: 'b', status: 'failed' }), step({ name: 'c' })] })
    expect(failedStep(build)?.name).toBe('b')
  })

  it('is nothing when no step failed', () => {
    expect(failedStep(buildFixture({ steps: [step()] }))).toBeUndefined()
  })
})

describe('failureTitle', () => {
  const failedBuild = (message: string, failingStep = 'install') =>
    buildFixture({ status: 'failed', message, steps: [step({ name: 'define', status: 'succeeded' }), step({ name: failingStep, status: 'failed', exit_code: 1 })] })

  it('names a cancelled build as cancelled, whatever step it stopped in', () => {
    expect(failureTitle(failedBuild(CANCELLED))).toBe('BUILD CANCELLED')
  })

  it('names any other failed build by the step that failed', () => {
    expect(failureTitle(failedBuild('provision exited with code 1', 'tamper-off'))).toBe('TAMPER OFF FAILED')
  })

  it('falls back to BUILD FAILED when no step is marked failed', () => {
    expect(failureTitle(buildFixture({ status: 'failed', message: 'control service crashed', steps: [] }))).toBe('BUILD FAILED')
  })
})

describe('phaseOf', () => {
  const build = (status: 'running' | 'paused' | 'failed' | 'succeeded') => buildFixture({ status })
  const job = (status: 'pending' | 'running' | 'paused' | 'done' | 'failed' | 'interrupted', result: Record<string, unknown> | null = null) => ({
    status,
    step: 'Self-test: analysis running',
    progress: 93,
    result,
  })

  it('is loading until the build or a failure has come', () => {
    expect(phaseOf({})).toBe('loading')
  })

  it('is not found or unreachable when the first read failed that way', () => {
    expect(phaseOf({ loadFailure: 'not-found' })).toBe('not-found')
    expect(phaseOf({ loadFailure: 'unreachable' })).toBe('unreachable')
  })

  it('keeps showing a build already read when a later read failed', () => {
    expect(phaseOf({ build: build('running'), loadFailure: 'unreachable' })).toBe('running')
  })

  it.each(['running', 'paused', 'failed'] as const)('follows the build while it is %s', (status) => {
    expect(phaseOf({ build: build(status) })).toBe(status)
  })

  it('is the self-test while the build succeeded and the job goes on', () => {
    for (const status of ['pending', 'running', 'paused'] as const) {
      expect(phaseOf({ build: build('succeeded'), job: job(status) })).toBe('selftest')
    }
  })

  it('is ready when the job ended done', () => {
    expect(phaseOf({ build: build('succeeded'), job: job('done', { state: 'ready' }) })).toBe('ready')
  })

  it('is a failed self-test when the job failed after the build succeeded, or was interrupted', () => {
    expect(phaseOf({ build: build('succeeded'), job: job('failed') })).toBe('selftest-failed')
    expect(phaseOf({ build: build('succeeded'), job: job('interrupted') })).toBe('selftest-failed')
  })

  it('does not follow a job that failed while the build itself is still shown as running', () => {
    expect(phaseOf({ build: build('running'), job: job('failed') })).toBe('running')
  })

  describe('with no job known', () => {
    it.each([
      ['ready', 'ready'],
      ['failed', 'selftest-failed'],
      ['testing', 'selftest'],
      ['building', 'selftest'],
    ] as const)('reads a %s guest as %s', (state, phase) => {
      expect(phaseOf({ build: build('succeeded'), guestState: state })).toBe(phase)
    })

    it('waits as a self-test until the guest is known', () => {
      expect(phaseOf({ build: build('succeeded') })).toBe('selftest')
    })

    it('treats a guest that is gone as finished', () => {
      expect(phaseOf({ build: build('succeeded'), guestState: 'broken' })).toBe('ready')
    })
  })
})

describe('buildPhaseMeta', () => {
  it('has a label, an icon and a colour for every phase, active only while something goes on', () => {
    for (const phase of BUILD_PHASES) {
      const meta = buildPhaseMeta(phase)
      expect(meta.label).not.toBe('')
      expect(meta.icon).not.toBe('')
      expect(meta.color).toMatch(/^--/)
    }
    const active = BUILD_PHASES.filter((phase) => buildPhaseMeta(phase).active)
    expect(active).toEqual(['loading', 'running', 'selftest'])
  })

  it('names the self-test phase and the final verdicts', () => {
    expect(buildPhaseMeta('selftest').label).toBe('SELF-TEST')
    expect(buildPhaseMeta('ready').label).toBe('READY')
    expect(buildPhaseMeta('selftest-failed').label).toBe('SELF-TEST FAILED')
  })
})

describe('progressShown', () => {
  const running = buildFixture({ status: 'running', percent: 42, message: 'Provisioning the guest' })

  it('is the build’s own percent and message while it runs', () => {
    expect(progressShown('running', running, undefined)).toEqual({ percent: 42, message: 'Provisioning the guest' })
  })

  it('is the job’s percent and step once the build succeeded', () => {
    expect(progressShown('selftest', buildFixture({ status: 'succeeded', percent: 100 }), { status: 'running', step: 'Self-test: judging', progress: 97, result: null })).toEqual({
      percent: 97,
      message: 'Self-test: judging',
    })
  })

  it('is complete when ready', () => {
    expect(progressShown('ready', buildFixture({ status: 'succeeded' }), { status: 'done', step: 'x', progress: 100, result: null }).percent).toBe(100)
  })

  it('keeps the build’s percent when the self-test follows with no job yet', () => {
    expect(progressShown('selftest', buildFixture({ status: 'succeeded', percent: 100, message: 'Built' }), undefined)).toEqual({ percent: 100, message: 'Self-test starting' })
  })

  it('has nothing before the build is read', () => {
    expect(progressShown('loading', undefined, undefined)).toEqual({ percent: 0, message: '' })
  })
})

describe('selfTestVerdictOf', () => {
  const details = {
    message: 'all checks passed',
    analysis_id: 41,
    signals: { 'events.process': { ok: true, message: '3 processes recorded' }, 'events.registry': { ok: false, message: 'no registry event was recorded' } },
    proofs: { defender: { ok: true, message: 'EICAR was kept' } },
    giveaways: ['account "Analyst"'],
    facts_summary: { 'os.hostname': 'DESKTOP-1' },
  }

  it('reads the details of the job result', () => {
    const verdict = selfTestVerdictOf({ status: 'done', step: '', progress: 100, result: { guest: 'lab4', state: 'ready', selftest: details } }, undefined)!
    expect(verdict.message).toBe('all checks passed')
    expect(verdict.analysisId).toBe(41)
    expect(verdict.signals).toEqual([
      { id: 'events.process', label: 'PROCESS EVENTS', ok: true, message: '3 processes recorded' },
      { id: 'events.registry', label: 'REGISTRY EVENTS', ok: false, message: 'no registry event was recorded' },
    ])
    expect(verdict.proofs).toEqual([{ id: 'defender', label: 'DEFENDER', ok: true, message: 'EICAR was kept' }])
    expect(verdict.giveaways).toEqual(['account "Analyst"'])
  })

  it('falls back to the guest’s stored self-test when the job result has none, as for a job that failed', () => {
    const guest = guestFixture({ selftest: details })
    const verdict = selfTestVerdictOf({ status: 'failed', step: '', progress: 99, result: { error: 'The self-test of lab4 failed: x' } }, guest)
    expect(verdict?.message).toBe('all checks passed')
  })

  it('is nothing when neither holds details, or the self-test did not run', () => {
    expect(selfTestVerdictOf(undefined, undefined)).toBeUndefined()
    expect(selfTestVerdictOf({ status: 'done', step: '', progress: 100, result: { guest: 'lab4', state: 'testing', selftest: 'not run' } }, undefined)).toBeUndefined()
  })

  it('tolerates missing parts: no signals, no proofs, no giveaways, no analysis', () => {
    const verdict = selfTestVerdictOf(undefined, guestFixture({ selftest: { message: 'm' } }))!
    expect(verdict).toMatchObject({ message: 'm', analysisId: undefined, signals: [], proofs: [], giveaways: [] })
  })

  it('ignores entries that are not objects with a boolean ok', () => {
    const verdict = selfTestVerdictOf(undefined, guestFixture({ selftest: { message: 'm', signals: { a: 'x', b: { ok: 'yes' }, c: { ok: true } }, giveaways: ['g', 3] } }))!
    expect(verdict.signals.map((signal) => signal.id)).toEqual(['c'])
    expect(verdict.giveaways).toEqual(['g'])
  })
})

describe('signalLabel', () => {
  it.each([
    ['events.process', 'PROCESS EVENTS'],
    ['events.file', 'FILE EVENTS'],
    ['events.registry', 'REGISTRY EVENTS'],
    ['report.present', 'REPORT'],
    ['report.dns_answer', 'DNS LOOKUP'],
  ])('names %s', (id, label) => {
    expect(signalLabel(id)).toBe(label)
  })

  it('humanises a signal it does not know', () => {
    expect(signalLabel('guest.screen_size')).toBe('GUEST SCREEN SIZE')
  })
})

describe('selfTestFailureMessage', () => {
  it('is the verdict’s message when there is one', () => {
    const verdict = selfTestVerdictOf(undefined, guestFixture({ selftest: { message: 'no registry event was recorded' } }))
    expect(selfTestFailureMessage({ status: 'failed', step: '', progress: 0, result: { error: 'The self-test of lab4 failed: other' } }, verdict)).toBe('no registry event was recorded')
  })

  it('is the job’s error when no verdict was stored', () => {
    expect(selfTestFailureMessage({ status: 'failed', step: '', progress: 0, result: { error: 'The self-test of lab4 failed: x' } }, undefined)).toBe('The self-test of lab4 failed: x')
  })

  it('says it was interrupted for an interrupted job', () => {
    expect(selfTestFailureMessage({ status: 'interrupted', step: '', progress: 0, result: null }, undefined)).toContain('interrupted')
  })

  it('has a plain sentence when nothing says why', () => {
    expect(selfTestFailureMessage(undefined, undefined)).toContain('did not pass')
  })
})

describe('stepsWithSelfTest', () => {
  const steps = [step({ name: 'preflight', status: 'succeeded' }), step({ name: 'install', status: 'running' })]

  it.each([
    ['running', 'pending'],
    ['paused', 'pending'],
    ['failed', 'pending'],
    ['selftest', 'running'],
    ['ready', 'succeeded'],
    ['selftest-failed', 'failed'],
  ] as const)('ends the list with the self-test as %s while the page is %s', (phase, status) => {
    const shown = stepsWithSelfTest(steps, phase)
    expect(shown).toHaveLength(3)
    expect(shown[2]).toMatchObject({ name: 'self-test', status })
    expect(shown.slice(0, 2)).toEqual(steps)
  })

  it('adds nothing before the steps are known', () => {
    expect(stepsWithSelfTest([], 'loading')).toEqual([])
  })
})

describe('actionRefusal', () => {
  it.each([502, 503, 504])('names the control service for a %i gateway error', (status) => {
    expect(actionRefusal(status, undefined)).toBe('The guest control service is not reachable; try again in a moment.')
  })

  it('is the backend’s own sentence for any other refusal', () => {
    expect(actionRefusal(409, { error: { code: 'conflict', message: 'An analysis is active', details: {} } })).toBe('An analysis is active')
  })
})

describe('the confirmations', () => {
  it('asks before cancelling a build', () => {
    expect(cancelConfirmation()).toEqual({
      title: 'Cancel this build?',
      message: 'The running step is stopped. The guest is kept as failed and can be resumed, restarted or deleted.',
      confirmLabel: 'CANCEL BUILD',
    })
  })

  it('names the kind and the guest when asking before a restart', () => {
    expect(restartConfirmation({ guest: 'lab1', kind: 'clone' })).toEqual({
      title: 'Restart the clone of lab1',
      message: 'Restart the clone of lab1 from the first step? What the clone has done so far is discarded and cannot be recovered.',
      confirmLabel: 'RESTART',
    })
  })
})
