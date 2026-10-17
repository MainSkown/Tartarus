import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Notify } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref, type EffectScope } from 'vue'
import type { BuildStep, JobProgress } from '@/api'
import type { SystemMessage } from '@/services/ws'
import { failed, succeeded } from './annotation-fixtures'
import { buildFixture, guestFixture } from './guest-fixtures'

const api = vi.hoisted(() => ({
  guestsList: vi.fn(),
  guestsReadBuild: vi.fn(),
  guestsActiveBuild: vi.fn(),
  guestsResumeBuild: vi.fn(),
  guestsRestartBuild: vi.fn(),
  guestsContinueBuild: vi.fn(),
  guestsCancelBuild: vi.fn(),
  jobsRead: vi.fn(),
  systemHealth: vi.fn(),
}))
const confirmDestructive = vi.hoisted(() => vi.fn())
let pushMessage: (message: SystemMessage) => void = () => undefined

vi.mock('@/api', () => api)
vi.mock('@/services/confirm', () => ({ confirmDestructive }))
vi.mock('@/services/ws', () => ({
  createSystemClient: () => ({
    state: { value: 'open' },
    subscribe: (handler: (message: SystemMessage) => void) => {
      pushMessage = handler
      return () => undefined
    },
    connect: () => undefined,
    disconnect: () => undefined,
  }),
}))

const { useGuestBuild, POLL_INTERVAL_MS, LOG_TAIL } = await import('@/composables/use-guest-build')

const step = (name: string, status: BuildStep['status'], desktop = false): BuildStep => ({ name, status, weight: 1, timeout_s: 60, desktop, progress: 0 })

const running = buildFixture({ id: 'b1', guest: 'lab4', status: 'running', percent: 30, steps: [step('install', 'running', true)], desktop: true })
const paused = buildFixture({ id: 'b1', guest: 'lab4', status: 'paused', pause: { instructions: 'Turn the toggle off' }, desktop: true })
const failedBuild = buildFixture({ id: 'b1', guest: 'lab4', status: 'failed', message: 'provision exited 1', steps: [step('provision', 'failed')] })
const succeededBuild = buildFixture({ id: 'b1', guest: 'lab4', status: 'succeeded', percent: 100 })

const SELFTEST = { message: 'all checks passed', analysis_id: 41, signals: { 'events.process': { ok: true, message: '3 processes' } }, proofs: {}, giveaways: [] }

function job(overrides: Partial<JobProgress> = {}): JobProgress {
  return { id: 7, type: 'guest_build', analysis_id: null, status: 'running', step: 'Self-test: analysis running', progress: 93, result: null, ...overrides }
}
const jobRead = (overrides: Partial<JobProgress> = {}) => succeeded({ ...job(overrides), log: '', created_at: '', updated_at: '' })
const accepted = (jobId = 9) => ({ data: { job_id: jobId, build_id: 'b1', guest: 'lab4' }, error: undefined, response: { status: 202 } })
// The cancel route answers 202 with no body and starts no job.
const cancelAccepted = { data: undefined, error: undefined, response: { status: 202 } }

let scope: EffectScope
const buildId = ref('b1')

function start() {
  scope = effectScope()
  return scope.run(() => useGuestBuild(() => buildId.value))!
}

const reads = () => api.guestsReadBuild.mock.calls.length
const tick = (times = 1) => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * times)

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  buildId.value = 'b1'
  api.systemHealth.mockResolvedValue({ data: undefined })
  api.guestsList.mockReset().mockResolvedValue(succeeded([guestFixture({ name: 'lab4', state: 'testing' })]))
  api.guestsReadBuild.mockReset().mockResolvedValue(succeeded(running))
  api.guestsActiveBuild.mockReset().mockResolvedValue(failed('no build', 404))
  api.guestsResumeBuild.mockReset().mockResolvedValue(accepted())
  api.guestsRestartBuild.mockReset().mockResolvedValue(accepted())
  api.guestsContinueBuild.mockReset().mockResolvedValue(accepted())
  api.guestsCancelBuild.mockReset().mockResolvedValue(cancelAccepted)
  api.jobsRead.mockReset().mockResolvedValue(jobRead())
  confirmDestructive.mockReset().mockResolvedValue(true)
})

afterEach(() => {
  scope.stop()
  vi.useRealTimers()
})

describe('useGuestBuild reading the build', () => {
  it('is loading, then reads the build with the last 200 log lines', async () => {
    const state = start()
    expect(state.phase.value).toBe('loading')
    await flushPromises()
    expect(LOG_TAIL).toBe(200)
    expect(api.guestsReadBuild).toHaveBeenCalledWith(expect.objectContaining({ path: { build_id: 'b1' }, query: { tail: 200 } }))
    expect(state.phase.value).toBe('running')
    expect(state.build.value?.guest).toBe('lab4')
  })

  it('reads again every two seconds while the build runs', async () => {
    start()
    await flushPromises()
    expect(POLL_INTERVAL_MS).toBe(2_000)
    expect(reads()).toBe(1)
    await tick()
    expect(reads()).toBe(2)
    await tick(3)
    expect(reads()).toBe(5)
  })

  it('goes on reading a paused build, which the analyst is about to continue', async () => {
    api.guestsReadBuild.mockResolvedValue(succeeded(paused))
    const state = start()
    await flushPromises()
    await tick(2)
    expect(state.phase.value).toBe('paused')
    expect(reads()).toBe(3)
  })

  it('stops reading when the build failed', async () => {
    api.guestsReadBuild.mockResolvedValue(succeeded(failedBuild))
    const state = start()
    await flushPromises()
    await tick(3)
    expect(state.phase.value).toBe('failed')
    expect(reads()).toBe(1)
  })

  it('stops reading when the scope ends', async () => {
    start()
    await flushPromises()
    scope.stop()
    await tick(3)
    expect(reads()).toBe(1)
  })

  it('is not found for a 404, and does not read again', async () => {
    api.guestsReadBuild.mockResolvedValue(failed('no such build', 404))
    const state = start()
    await flushPromises()
    await tick(2)
    expect(state.phase.value).toBe('not-found')
    expect(reads()).toBe(1)
  })

  it('is unreachable for a 502, and keeps trying quietly until the control service answers', async () => {
    api.guestsReadBuild.mockResolvedValueOnce(failed('guest control: unreachable', 502)).mockResolvedValue(succeeded(running))
    const state = start()
    await flushPromises()
    expect(state.phase.value).toBe('unreachable')
    await tick()
    expect(state.phase.value).toBe('running')
  })

  it('keeps the build it has and says the connection is lost when a later read fails', async () => {
    api.guestsReadBuild.mockResolvedValueOnce(succeeded(running)).mockResolvedValueOnce(failed('unreachable', 502)).mockResolvedValue(succeeded(running))
    const state = start()
    await flushPromises()
    expect(state.connectionLost.value).toBe(false)
    await tick()
    expect(state.phase.value).toBe('running')
    expect(state.connectionLost.value).toBe(true)
    await tick()
    expect(state.connectionLost.value).toBe(false)
  })

  it('starts over when the page is given another build', async () => {
    const state = start()
    await flushPromises()
    api.guestsReadBuild.mockResolvedValue(succeeded({ ...running, id: 'b2', guest: 'lab5' }))
    buildId.value = 'b2'
    await flushPromises()
    expect(api.guestsReadBuild).toHaveBeenLastCalledWith(expect.objectContaining({ path: { build_id: 'b2' } }))
    expect(state.build.value?.guest).toBe('lab5')
  })

  it('has a desktop only while the build runs or is paused at a step that shows one', async () => {
    const state = start()
    await flushPromises()
    expect(state.hasDesktop.value).toBe(true)
    api.guestsReadBuild.mockResolvedValue(succeeded({ ...running, desktop: false }))
    await tick()
    expect(state.hasDesktop.value).toBe(false)
    api.guestsReadBuild.mockResolvedValue(succeeded({ ...failedBuild, desktop: true }))
    await tick()
    expect(state.hasDesktop.value).toBe(false)
  })
})

describe('useGuestBuild following the job after the build succeeded', () => {
  beforeEach(() => {
    api.guestsReadBuild.mockResolvedValue(succeeded(succeededBuild))
    api.guestsActiveBuild.mockResolvedValue(succeeded({ build_id: 'b1', guest: 'lab4', job_id: 7 }))
  })

  it('finds the job through the active build and shows the self-test with the job’s percent', async () => {
    const state = start()
    await flushPromises()
    expect(api.jobsRead).toHaveBeenCalledWith(expect.objectContaining({ path: { job_id: 7 } }))
    expect(state.phase.value).toBe('selftest')
    expect(state.progress.value).toEqual({ percent: 93, message: 'Self-test: analysis running' })
  })

  it('stops reading the build, and reads the job every two seconds instead', async () => {
    start()
    await flushPromises()
    await tick(2)
    expect(reads()).toBe(1)
    expect(api.jobsRead).toHaveBeenCalledTimes(3)
  })

  it('does not take the job of another build', async () => {
    api.guestsActiveBuild.mockResolvedValue(succeeded({ build_id: 'other', guest: 'lab9', job_id: 3 }))
    start()
    await flushPromises()
    expect(api.jobsRead).not.toHaveBeenCalled()
  })

  it('follows the job’s pushes on the system socket by its id', async () => {
    const state = start()
    await flushPromises()
    pushMessage({ type: 'job', job: job({ id: 99, progress: 5 }) } as SystemMessage)
    expect(state.progress.value.percent).toBe(93)
    pushMessage({ type: 'job', job: job({ progress: 96, step: 'Self-test: judging' }) } as SystemMessage)
    expect(state.progress.value).toEqual({ percent: 96, message: 'Self-test: judging' })
  })

  it('is ready with the verdict of the job result when the job ended done, and stops', async () => {
    api.jobsRead.mockResolvedValue(jobRead({ status: 'done', progress: 100, result: { guest: 'lab4', state: 'ready', selftest: SELFTEST } }))
    const state = start()
    await flushPromises()
    expect(state.phase.value).toBe('ready')
    expect(state.verdict.value?.analysisId).toBe(41)
    const calls = api.jobsRead.mock.calls.length
    await tick(3)
    expect(api.jobsRead).toHaveBeenCalledTimes(calls)
  })

  it('is a failed self-test with the guest’s stored verdict when the job failed', async () => {
    api.jobsRead.mockResolvedValue(jobRead({ status: 'failed', result: { error: 'The self-test of lab4 failed: no registry event' } }))
    api.guestsList.mockResolvedValue(
      succeeded([guestFixture({ name: 'lab4', state: 'failed', selftest: { ...SELFTEST, message: 'no registry event was recorded', giveaways: ['account "Analyst"'] } })]),
    )
    const state = start()
    await flushPromises()
    expect(state.phase.value).toBe('selftest-failed')
    expect(state.failureMessage.value).toBe('no registry event was recorded')
    expect(state.verdict.value?.giveaways).toEqual(['account "Analyst"'])
  })

  it('says why from the job when no verdict was stored', async () => {
    api.jobsRead.mockResolvedValue(jobRead({ status: 'failed', result: { error: 'The self-test of lab4 failed: the control service went away' } }))
    api.guestsList.mockResolvedValue(succeeded([guestFixture({ name: 'lab4', state: 'failed', selftest: null })]))
    const state = start()
    await flushPromises()
    expect(state.failureMessage.value).toBe('The self-test of lab4 failed: the control service went away')
  })

  it('keeps the job it knows when a read of it fails', async () => {
    api.jobsRead.mockResolvedValueOnce(jobRead()).mockResolvedValueOnce(failed('down', 502)).mockResolvedValue(jobRead({ progress: 97 }))
    const state = start()
    await flushPromises()
    await tick()
    expect(state.phase.value).toBe('selftest')
    expect(state.connectionLost.value).toBe(true)
    await tick()
    expect(state.progress.value.percent).toBe(97)
    expect(state.connectionLost.value).toBe(false)
  })
})

describe('useGuestBuild opened after the whole build ended', () => {
  beforeEach(() => api.guestsReadBuild.mockResolvedValue(succeeded(succeededBuild)))

  it('reads the verdict from the guest when no job follows the build, and stops', async () => {
    api.guestsList.mockResolvedValue(succeeded([guestFixture({ name: 'lab4', state: 'ready', selftest: SELFTEST })]))
    const state = start()
    await flushPromises()
    expect(state.phase.value).toBe('ready')
    expect(state.verdict.value?.message).toBe('all checks passed')
    await tick(3)
    expect(api.guestsList).toHaveBeenCalledTimes(1)
  })

  it('is a failed self-test when the guest failed', async () => {
    api.guestsList.mockResolvedValue(succeeded([guestFixture({ name: 'lab4', state: 'failed', selftest: { message: 'giveaways found' } })]))
    const state = start()
    await flushPromises()
    expect(state.phase.value).toBe('selftest-failed')
    expect(state.failureMessage.value).toBe('giveaways found')
  })

  it('goes on asking while the guest is being tested', async () => {
    const state = start()
    await flushPromises()
    expect(state.phase.value).toBe('selftest')
    await tick(2)
    expect(api.guestsList.mock.calls.length).toBeGreaterThanOrEqual(3)
    api.guestsList.mockResolvedValue(succeeded([guestFixture({ name: 'lab4', state: 'ready' })]))
    await tick()
    expect(state.phase.value).toBe('ready')
  })
})

describe('useGuestBuild actions', () => {
  beforeEach(() => api.guestsReadBuild.mockResolvedValue(succeeded(failedBuild)))

  it('resumes the failed step of this build, then follows the same build again', async () => {
    const state = start()
    await flushPromises()
    api.guestsReadBuild.mockResolvedValue(succeeded(running))
    await state.resume()
    await flushPromises()
    expect(api.guestsResumeBuild).toHaveBeenCalledWith(expect.objectContaining({ path: { build_id: 'b1' } }))
    expect(state.phase.value).toBe('running')
    const before = reads()
    await tick()
    expect(reads()).toBeGreaterThan(before)
  })

  it('is busy while the request is out, and ignores a second press', async () => {
    const state = start()
    await flushPromises()
    let release: (value: unknown) => void = () => undefined
    api.guestsResumeBuild.mockReturnValue(new Promise((resolve) => (release = resolve)))
    const first = state.resume()
    void state.resume()
    expect(state.busy.value).toBe('resume')
    release(accepted())
    await first
    expect(state.busy.value).toBeUndefined()
    expect(api.guestsResumeBuild).toHaveBeenCalledTimes(1)
  })

  it('asks before it restarts, and does nothing when the analyst declines', async () => {
    const state = start()
    await flushPromises()
    confirmDestructive.mockResolvedValue(false)
    await state.restart()
    expect(confirmDestructive).toHaveBeenCalledWith(expect.objectContaining({ confirmLabel: 'RESTART', message: expect.stringContaining('lab4') }))
    expect(api.guestsRestartBuild).not.toHaveBeenCalled()
  })

  it('restarts from the first step once confirmed', async () => {
    const state = start()
    await flushPromises()
    await state.restart()
    expect(api.guestsRestartBuild).toHaveBeenCalledWith(expect.objectContaining({ path: { build_id: 'b1' } }))
  })

  it('continues a paused build', async () => {
    api.guestsReadBuild.mockResolvedValue(succeeded(paused))
    const state = start()
    await flushPromises()
    await state.continueBuild()
    expect(api.guestsContinueBuild).toHaveBeenCalledWith(expect.objectContaining({ path: { build_id: 'b1' } }))
  })

  it('shows the refusal of an active analysis (409) inline and goes on showing the failed build', async () => {
    api.guestsResumeBuild.mockResolvedValue(failed('An analysis is queued or running', 409))
    const state = start()
    await flushPromises()
    await state.resume()
    expect(state.actionError.value).toBe('An analysis is queued or running')
    expect(state.phase.value).toBe('failed')
    expect(state.busy.value).toBeUndefined()
  })

  it('says the control service is not reachable (502) and to try again', async () => {
    api.guestsContinueBuild.mockResolvedValue(failed('guest control: unreachable (connection refused)', 502))
    api.guestsReadBuild.mockResolvedValue(succeeded(paused))
    const state = start()
    await flushPromises()
    await state.continueBuild()
    expect(state.actionError.value).toContain('not reachable')
    expect(state.actionError.value).toContain('try again')
  })

  it('clears an earlier refusal when the action is tried again', async () => {
    api.guestsResumeBuild.mockResolvedValueOnce(failed('busy', 409)).mockResolvedValue(accepted())
    const state = start()
    await flushPromises()
    await state.resume()
    expect(state.actionError.value).toBe('busy')
    await state.resume()
    expect(state.actionError.value).toBeUndefined()
  })

  it('follows the job the action answered with once the build then succeeds', async () => {
    const state = start()
    await flushPromises()
    api.guestsReadBuild.mockResolvedValue(succeeded(succeededBuild))
    api.guestsActiveBuild.mockResolvedValue(failed('none', 404))
    api.jobsRead.mockResolvedValue(jobRead({ id: 9, progress: 95 }))
    await state.resume()
    await flushPromises()
    expect(api.jobsRead).toHaveBeenCalledWith(expect.objectContaining({ path: { job_id: 9 } }))
    expect(state.phase.value).toBe('selftest')
  })
})

describe('useGuestBuild cancelling', () => {
  beforeEach(() => {
    Notify.create = vi.fn()
  })

  it.each([
    { name: 'running', view: running, offered: true },
    { name: 'paused', view: paused, offered: true },
    { name: 'failed', view: failedBuild, offered: false },
    { name: 'succeeded', view: succeededBuild, offered: false },
  ])('is offered only while the build runs or is paused: $name', async ({ view, offered }) => {
    api.guestsReadBuild.mockResolvedValue(succeeded(view))
    const state = start()
    await flushPromises()
    expect(state.cancellable.value).toBe(offered)
  })

  it('asks before it cancels, and sends nothing when the analyst declines', async () => {
    const state = start()
    await flushPromises()
    confirmDestructive.mockResolvedValue(false)
    await state.cancel()
    expect(confirmDestructive).toHaveBeenCalledWith({
      title: 'Cancel this build?',
      message: 'The running step is stopped. The guest is kept as failed and can be resumed, restarted or deleted.',
      confirmLabel: 'CANCEL BUILD',
    })
    expect(api.guestsCancelBuild).not.toHaveBeenCalled()
  })

  it('sends the cancel request once when confirmed, and then reads the build again', async () => {
    const state = start()
    await flushPromises()
    api.guestsReadBuild.mockResolvedValue(succeeded(failedBuild))
    await state.cancel()
    await flushPromises()
    expect(api.guestsCancelBuild).toHaveBeenCalledTimes(1)
    expect(api.guestsCancelBuild).toHaveBeenCalledWith(expect.objectContaining({ path: { build_id: 'b1' } }))
    expect(state.phase.value).toBe('failed')
    expect(api.jobsRead).not.toHaveBeenCalled()
  })

  it('is busy while the request is out, and ignores a second press', async () => {
    const state = start()
    await flushPromises()
    let release: (value: unknown) => void = () => undefined
    api.guestsCancelBuild.mockReturnValue(new Promise((resolve) => (release = resolve)))
    const first = state.cancel()
    await flushPromises()
    expect(state.busy.value).toBe('cancel')
    await state.cancel()
    expect(confirmDestructive).toHaveBeenCalledTimes(1)
    release(cancelAccepted)
    await first
    expect(state.busy.value).toBeUndefined()
    expect(api.guestsCancelBuild).toHaveBeenCalledTimes(1)
  })

  it('shows the 409 reason as a warning toast and leaves the running build as it is', async () => {
    api.guestsCancelBuild.mockResolvedValue(failed('the build is not running', 409))
    const state = start()
    await flushPromises()
    await state.cancel()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-warning', message: 'the build is not running' }))
    expect(state.actionError.value).toBeUndefined()
    expect(state.phase.value).toBe('running')
    expect(state.busy.value).toBeUndefined()
  })

  it('says the control service is not reachable (502) in a warning toast', async () => {
    api.guestsCancelBuild.mockResolvedValue(failed('guest control: unreachable (connection refused)', 502))
    const state = start()
    await flushPromises()
    await state.cancel()
    expect(Notify.create).toHaveBeenCalledWith(expect.objectContaining({ type: 'tt-warning', message: expect.stringContaining('not reachable') }))
  })
})
